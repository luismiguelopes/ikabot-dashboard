#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Target farming (F4): a continuous spy → evaluate → attack → wait → repeat loop per
target, driven by a per-target state machine persisted in SQLite (farm_targets).

Reuses the existing pipelines instead of reimplementing them:
- re-spy by enqueueing into the shared "spy_dispatch" queue (the spy state machine
  drives it to a DONE mission with a fresh report)
- attack by enqueueing into the shared "attack" queue (process_attack_queue dispatches,
  retries, logs to attack_log/loot_log and respects the global pause)

State machine per target:
  IDLE      → when now >= nextRunAt: enqueue a spy → SPYING
  SPYING    → when a fresh DONE report arrives: evaluate loot/garrison;
              worth it → enqueue attack(s) → ATTACKING; else → IDLE (+interval)
              (no report after 6h → IDLE +interval)
  ATTACKING → when troops are estimated back: → IDLE (+interval)
"""

import json
import math
import os
import random
import time

from empire_utils import LOGS_DIR, logger

# P7.1: last-resort backstop, NOT the primary timeout. A live/executing mission is owned by
# the espionage state machine, which terminalises it on its own (FAILED at 12h no-arrival /
# 2h no-report). The farm must never abort a still-live mission earlier than that on a naive
# wall-clock: during downtime the old 6h clock fired on healthy in-flight missions and
# orphaned their reports (the Polis case). So this backstop sits ABOVE the espionage 12h
# limit — it only frees a head if the espionage machine itself somehow never terminated it.
_SPY_TIMEOUT_SECS = 13 * 3600
# Grace after dispatch before a SPYING head with no in-flight mission is treated as stuck.
# Long enough to clear the dispatch-write race and a normal launch; short enough that a
# silently-failed dispatch doesn't pin the whole queue for the full 6h timeout.
_SPY_STUCK_GRACE = 12 * 60
_RELAUNCH_DELAY_RANGE = (1, 15)   # random minutes after troops return before next raid
_SEA_BATTLE_MARGIN_SECS = 20 * 60  # extra troop delay when the blockade must FIGHT combat
                                   # ships (rounds are ~15 min) instead of scaring flee ones
_EARLY_RESPY_LEAD = 5 * 60        # spy this long before troops dock, so the report is
                                  # ready on arrival (re-spy rounds skip the post-return wait)
FARM_SETTINGS_PATH = os.path.join(LOGS_DIR, "farm_settings.json")
MOVEMENTS_PATH = os.path.join(LOGS_DIR, "movements.json")


def _load_farm_settings():
    try:
        with open(FARM_SETTINGS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_farm_army():
    """User-defined minimal army loadout for the farm: {unitId: qty}.
    Farm targets are pre-scouted safe cities, so a small fixed force is enough — no
    need to empty a city of all its troops. Empty → fall back to all troops."""
    try:
        army = _load_farm_settings().get("army", {})
        return {str(k): int(v) for k, v in army.items() if int(v) > 0}
    except (ValueError, TypeError):
        return {}


def get_farm_spy_agents():
    """How many spies each farm re-scout sends (from farm settings, default 1)."""
    try:
        return max(1, int(_load_farm_settings().get("spyAgents", 1)))
    except (ValueError, TypeError):
        return 1


def get_farm_fleet():
    """User-defined combat-fleet loadout for the blockade wave: {unitId: qty}. A small fixed
    force (e.g. 10 steam rams) drives off flee-ships without exposing the whole fleet. Empty
    → send the origin's entire fleet (legacy behaviour)."""
    try:
        fleet = _load_farm_settings().get("fleet", {})
        return {str(k): int(v) for k, v in fleet.items() if int(v) > 0}
    except (ValueError, TypeError):
        return {}


def early_respy_enabled():
    """Pipelined re-spy: scout while the troops return so a re-spy round doesn't pay the
    spy round-trip after they dock. On by default; kill switch in farm settings."""
    return bool(_load_farm_settings().get("earlyRespyEnabled", True))


def _next_round_needs_spy(t):
    """True if the round after the current raid will re-scout: the periodic re-spy cadence
    is due, the target currently shows a fleet, or it's a known fleet-target (its fleet
    flees and returns, so we must always re-scout to know if the port is clean)."""
    respy_every = max(1, int(t.get("respy_every", 3)))
    return (int(t.get("raids_since_spy", 0)) >= respy_every
            or int(t.get("last_enemy_ships", 0)) > 0
            or int(t.get("is_fleet_target", 0)) == 1)


def _enabled_targets():
    try:
        from db_manager import farm_list
        return [t for t in farm_list() if t.get("enabled")]
    except Exception:
        logger.error("[farm] leitura de alvos falhou", exc_info=True)
        return []


def has_active_farm():
    return bool(_enabled_targets())


# ── Inactivity confirmation ─────────────────────────────────────────────────────
# A "safe" target (is_fleet_target=0) is raided directly between scouts. The ONLY thing
# that can make it unsafe is the owner stopping being inactive — an inactive player can't
# garrison troops nor receive a deployed fleet (game rule), so no fleet/army can appear.
# So instead of re-spying the garrison we just re-confirm the owner is still inactive.
_SCAN_FRESH_SECS = 48 * 3600


def _scan_says_inactive(target_city_id):
    """Cheap pre-check from world_scan.json (only lists inactive/vacation players). True if
    the target is there in a recent scan; None if unknown/stale (caller confirms live)."""
    try:
        with open(os.path.join(LOGS_DIR, "world_scan.json")) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if int(time.time()) - int(data.get("lastUpdated", 0) or 0) > _SCAN_FRESH_SECS:
        return None
    for p in data.get("players", []):
        if str(p.get("cityId", "")) == str(target_city_id):
            st = p.get("state")
            if st == "vacation":
                return "vacation"
            return st == "inactive"
    return None   # absent → ambiguous (active, or just not scanned)


# Memo so one farm pass (verdict + attack seconds apart) doesn't fetch the same island twice.
_INACTIVE_MEMO_SECS = 120
_inactive_memo = {}   # tid -> (checked_at, True/False)


def _confirm_inactive(session, t):
    """Real-time confirmation that the target's owner is still inactive, done immediately
    before EVERY farm action (scout or attack): fetches the island view live and reads the
    city's state at the coordinates. The cached world scan is only a fallback when the live
    fetch fails. Returns True (inactive → farmable), "vacation" (the game REFUSES attacks
    on vacation players — skip the target), False (active again → unsafe), or None
    (couldn't tell — caller decides: scout instead of attacking blind)."""
    tid = str(t["target_city_id"])
    now = time.time()
    hit = _inactive_memo.get(tid)
    if hit and now - hit[0] < _INACTIVE_MEMO_SECS:
        return hit[1]
    island_id = str(t.get("island_id", ""))
    if island_id:
        try:
            from ikabot.helpers.getJson import getIsland
            time.sleep(random.randint(3, 8))
            island = getIsland(session.get("view=island&islandId=" + island_id))
            for c in island.get("cities", []):
                if str(c.get("id", "")) == tid:
                    st = c.get("state")
                    res = "vacation" if st == "vacation" else (st == "inactive")
                    _inactive_memo[tid] = (now, res)
                    return res
        except Exception:
            logger.warning("[farm] %s: fetch da ilha para confirmar inactividade falhou — "
                           "a tentar o world scan em cache", t.get("target_city_name", tid))
    return _scan_says_inactive(tid)


def _disable_active_target(t):
    """The owner is active again → the target is no longer farmable. Disable it + alert."""
    nm = t.get("target_city_name", t["target_city_id"])
    logger.warning("[farm] %s: jogador já não está inactivo — alvo desactivado", nm)
    try:
        from telegram_notifier import notify_farm_active
        notify_farm_active(nm, t.get("target_player", ""))
    except Exception:
        pass
    from db_manager import farm_update
    farm_update(t["target_city_id"], {"state": "IDLE", "enabled": 0, "next_action": "spy"})


_VACATION_SKIP_SECS = 24 * 3600


def _skip_vacation_target(t):
    """Vacation mode: the game refuses attacks outright (type=11 'está de férias'), so
    raiding or scouting is pointless — but vacation ends, so instead of disabling the
    target we push it 24h ahead and let the queue advance to the next due target."""
    nm = t.get("target_city_name", t["target_city_id"])
    logger.warning("[farm] %s: jogador em modo de férias — o jogo recusa ataques; "
                   "alvo saltado por 24h", nm)
    from db_manager import farm_update
    farm_update(t["target_city_id"], {"state": "IDLE",
                "next_run_at": int(time.time()) + _VACATION_SKIP_SECS,
                "next_action": "spy"})


def _recent_return_loot(t):
    """ACTUAL loot the last raid on this target brought home (from loot_log), or None if no
    return is recorded since the last attack. Unlike last_loot (the stale SCOUTED warehouse
    total kept for ranking), this reflects how drained the target is RIGHT NOW: troops carry
    min(warehouse, capacity), so a return below min_loot means the warehouse was below the
    threshold when we hit it — the target is drained, even though last_loot is still high."""
    last_atk = int(t.get("last_attack_at", 0) or 0)
    if last_atk <= 0:
        return None
    name = str(t.get("target_city_name", "") or "")
    try:
        from db_manager import get_loot_log
        for row in get_loot_log(limit=8, target=name):
            if int(row.get("ts", 0) or 0) < last_atk:
                continue
            if name and name.lower() not in str(row.get("from_city", "")).lower():
                continue
            return sum(int(row.get(k, 0) or 0)
                       for k in ("wood", "wine", "marble", "crystal", "sulfur"))
    except Exception:
        return None
    return None


def _returned_since_scout(t):
    """Total loot brought home since the last scout (last_spy_at). Raids only happen after a
    scout's report, so this is exactly what we've drained from the scouted warehouse."""
    since = int(t.get("last_spy_at", 0) or 0)
    if since <= 0:
        return 0
    name = str(t.get("target_city_name", "") or "")
    total = 0
    try:
        from db_manager import get_loot_log
        for row in get_loot_log(limit=30, target=name):
            if int(row.get("ts", 0) or 0) < since:
                continue
            if name and name.lower() not in str(row.get("from_city", "")).lower():
                continue
            total += sum(int(row.get(k, 0) or 0)
                         for k in ("wood", "wine", "marble", "crystal", "sulfur"))
    except Exception:
        return 0
    return total


def _estimated_warehouse(t):
    """How much loot is likely in the target RIGHT NOW: the scouted warehouse minus what we've
    already brought home since that scout. Ignores regeneration, so it's conservative — it may
    re-scout a touch early, which is far cheaper than sending the whole army round-trip for the
    scraps of an already-drained target (F1). Falls back to the scouted value if unknown."""
    scouted = int(t.get("last_loot", 0) or 0)
    return max(0, scouted - _returned_since_scout(t))


# ── Ship reservation ───────────────────────────────────────────────────────────
# Trade ships ("transporters") are the SAME pool used to pillage and to move resources
# between own cities. Internal logistics (consolidation, wine top-ups, construction
# transports) would otherwise sweep the fleet and starve the farm of ships — but the
# farm GENERATES resources and its raids are time-sensitive, while logistics only moves
# them around and has a freighter fallback the farm doesn't. So logistics must leave a
# reserve of trade ships free for any imminent farm raid. This is the bulletproof part:
# regardless of cycle ordering, logistics can never take the ships the farm is about to
# need.
FARM_RESERVE_HORIZON_MIN = 45    # reserve ships for raids becoming due within this window
_MIN_RESERVE_PER_TARGET  = 1


def _reserve_settings():
    """(enabled, horizon_minutes) from farm_settings.json — defaults on, 45 min."""
    s = _load_farm_settings()
    try:
        horizon = max(0, int(s.get("reserveHorizonMin", FARM_RESERVE_HORIZON_MIN)))
    except (ValueError, TypeError):
        horizon = FARM_RESERVE_HORIZON_MIN
    return bool(s.get("shipReserveEnabled", True)), horizon


def _pending_plunder_transporters(now, horizon_secs):
    """Trade ships already committed to queued army plunders dispatching within horizon."""
    try:
        from db_manager import queue_items
    except Exception:
        return 0
    total = 0
    try:
        for it in queue_items("attack"):
            if it.get("missionType") != "army":
                continue
            tr = int(it.get("transporters", 0) or 0)
            if tr <= 0:
                continue
            if int(it.get("dispatchAfter", 0) or 0) <= now + horizon_secs:
                total += tr
    except Exception:
        pass
    return total


def farm_ship_reserve(now=None):
    """How many trade ships internal logistics must leave free for the farm right now.

    Counts queued army plunders plus enabled farm targets whose next raid is due within
    the reserve horizon. Targets currently out on a raid (ATTACKING) aren't counted — their
    ships are already gone. Returns 0 when the reserve is disabled or nothing is imminent.
    Over-reserving is safe (logistics falls back to freighters); under-reserving starves
    the farm, so when a target's transporter count is unknown we still reserve a floor."""
    enabled, horizon_min = _reserve_settings()
    if not enabled:
        return 0
    if now is None:
        now = int(time.time())
    horizon = horizon_min * 60
    reserve = _pending_plunder_transporters(now, horizon)
    for t in _enabled_targets():
        if t.get("state", "IDLE") == "ATTACKING":
            continue  # ships already committed to this raid
        if int(t.get("next_run_at", 0) or 0) <= now + horizon:
            reserve += max(_MIN_RESERVE_PER_TARGET, int(t.get("last_transporters", 0) or 0))
    return reserve


def apply_ship_reserve(ships_available, label, now=None):
    """Subtract the farm reserve from a logistics ship budget, logging when it bites.
    Returns the trade ships logistics may use this round (freighters are unaffected)."""
    try:
        reserve = farm_ship_reserve(now)
    except Exception:
        reserve = 0
    if reserve <= 0 or ships_available <= 0:
        return ships_available
    usable = max(0, ships_available - reserve)
    if usable < ships_available:
        logger.info("[%s] %d navios de comércio reservados p/ o farm — %d livres p/ logística",
                    label, reserve, usable)
    return usable


def _pick_spy_origin(own_cities, spy_counts, target):
    """Closest own city that has a safehouse and spies available to send."""
    by_city = spy_counts.get("byCityId", {})
    tx, ty = target.get("island_x", 0), target.get("island_y", 0)
    best, best_d = None, float("inf")
    for c in own_cities:
        if c.get("safehousePosition") is None:
            continue
        counts = by_city.get(str(c.get("cityId")), {})
        avail = counts.get("inDefense")
        if avail is None:
            avail = counts.get("available")
        if not avail or avail <= 0:
            continue
        d = (c.get("x", 0) - tx) ** 2 + (c.get("y", 0) - ty) ** 2
        if d < best_d:
            best_d, best = d, c
    return best


def _latest_done_report(missions, target_city_id, since):
    """Latest DONE mission for the target with a report newer than `since`."""
    best, best_ts = None, since
    for m in missions:
        if m.get("state") != "DONE":
            continue
        if str(m.get("targetCityId", "")) != str(target_city_id):
            continue
        res = m.get("result") or {}
        ts = res.get("reportedAt") or m.get("executedAt") or m.get("dispatchedAt") or 0
        if ts >= best_ts:
            best, best_ts = m, ts
    return best


def _free_ships(session):
    """Live count of free transport ships — the farm must not launch a sea raid while
    the previous raid's ships are still returning (would fail with type=11)."""
    try:
        from ikabot.helpers.naval import getAvailableShips
        return int(getAvailableShips(session))
    except Exception:
        return 0


def _real_return_eta(target):
    """Read the ACTUAL arrival time of our returning raid from movements.json — accounts
    for the game's real speeds and the loot-loading time. A returning plunder keeps the
    enemy in `destination` (origin stays our launching city), so match the target there.
    Returns the soonest arrival ts, or None if no return is in flight."""
    try:
        with open(MOVEMENTS_PATH) as f:
            movements = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    city = (target.get("target_city_name") or "").lower()
    player = (target.get("target_player") or "").lower()
    best = None
    for m in movements:
        if not m.get("isOwn") or m.get("direction") != "<-":
            continue
        dest = (m.get("destination") or "").lower()   # the enemy this raid hit
        if (city and city in dest) or (player and player in dest):
            arr = m.get("arrivalTime", 0)
            if arr and (best is None or arr < best):
                best = arr
    return best


_RAID_GRACE_SECS = 5 * 60   # let movements populate before trusting "no movement = home"


def _raid_in_flight(target):
    """True if ANY own movement (outbound OR returning) involves this target — i.e. the raid
    isn't home yet. Used to detect when an overshooting return estimate has already elapsed:
    no movement to/from the target + grace passed = troops are back, don't keep waiting."""
    try:
        with open(MOVEMENTS_PATH) as f:
            movements = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    city = (target.get("target_city_name") or "").lower()
    player = (target.get("target_player") or "").lower()
    for m in movements:
        if not m.get("isOwn"):
            continue
        for fld in ("destination", "origin"):
            v = (m.get(fld) or "").lower()
            if (city and city in v) or (player and player in v):
                return True
    return False


def _ships_back_eta(target, now, session=None, first_city_id=None):
    """When to retry an attack that's blocked on ships: the real return arrival from the
    movements API (so we wake exactly when the fleet lands), or a short fallback if no
    return is visible yet. Refreshes movements first (rate-limited across targets) so the
    just-launched raid's return is actually in the data."""
    if session and first_city_id and now - getattr(_ships_back_eta, "_last_refresh", 0) > 90:
        _ships_back_eta._last_refresh = now
        try:
            from empire_collector import refresh_movements
            refresh_movements(session, first_city_id)
        except Exception:
            pass
    eta = _real_return_eta(target)
    if eta and eta > now:
        return eta + random.randint(30, 90)   # small buffer after the fleet docks
    return now + random.randint(5, 15) * 60


def _spy_is_stuck(t, now):
    """A SPYING head whose spy has neither returned a report nor left any in-flight mission:
    the dispatch silently failed or the mission record vanished. Past the grace window this
    is a dead head that must be released so the queue advances — without waiting the full
    6h timeout. (A genuinely in-flight spy always has a live mission, so this never fires
    on a healthy wait.)"""
    disp = int(t.get("spy_dispatched_at", 0))
    if now - disp <= _SPY_STUCK_GRACE:
        return False
    try:
        from espionage_manager import has_live_mission
        return not has_live_mission(t["target_city_id"], disp)
    except Exception:
        return False


def _spy_report_ready(missions, t, now):
    """True if a SPYING target has a fresh report, has timed out, or is a dead head."""
    if _latest_done_report(missions, t["target_city_id"], int(t.get("spy_dispatched_at", 0)) - 120):
        return True
    if now - int(t.get("spy_dispatched_at", 0)) > _SPY_TIMEOUT_SECS:
        return True
    return _spy_is_stuck(t, now)


# ── Pure queue: one active target at a time ─────────────────────────────────────
# Farming all targets in parallel made them fight over one city's trade-ship pool and
# spin re-spying with "0 navios". Instead we drain ONE target at a time: pick the best
# loot/hour target, hammer it until its scouted loot falls below min_loot, then disable
# it for good and move to the next. Priority is dynamic — it re-ranks as fresh spy reports
# update last_loot, without waiting to scout every target first.

_DEFAULT_ROUND_TRIP = 4 * 3600   # fallback when a target's real travel time isn't known yet


def _round_trip_secs(t):
    """Round-trip travel estimate for loot/hour ranking. Uses the real one-way troop time
    measured on the last raid (×2) when known, else a neutral default."""
    j = int(t.get("last_troop_journey", 0) or 0)
    return j * 2 if j > 0 else _DEFAULT_ROUND_TRIP


def _priority_score(t):
    """Loot per second: higher = attacked first. Targets with no scouted loot yet score 0
    (they wait until nothing better is known), but are still spied/attacked when they reach
    the head — the per-target state machine always scouts before committing troops."""
    return int(t.get("last_loot", 0) or 0) / max(1, _round_trip_secs(t))


def _queue_head(targets):
    """The single target the farm works right now: the one already mid-cycle (SPYING/
    ATTACKING — its ships/spies are committed), else the highest loot/hour target. None if
    the list is empty. Tie-break by last_loot then creation order (stable)."""
    if not targets:
        return None
    active = [t for t in targets if t.get("state", "IDLE") != "IDLE"]
    if active:
        return active[0]
    # Among IDLE targets prefer the DUE ones: a rich target rescheduled into the future
    # (vacation skip, retry backoff) must not block due targets behind it.
    now = int(time.time())
    due = [t for t in targets if now >= int(t.get("next_run_at", 0) or 0)]
    pool = due or targets
    return max(pool, key=lambda t: (_priority_score(t), int(t.get("last_loot", 0) or 0),
                                    -int(t.get("created_at", 0) or 0)))


def has_due_farm():
    """Precise due-check for smart_sleep — True only when the queue head will actually act."""
    head = _queue_head(_enabled_targets())
    if not head:
        return False
    now = int(time.time())
    st = head.get("state", "IDLE")
    if st == "IDLE":
        return now >= int(head.get("next_run_at", 0))
    if st == "ATTACKING":
        ra = int(head.get("attack_return_at", 0))
        if now >= ra:
            return True
        return (early_respy_enabled() and int(head.get("respy_launched_at", 0)) == 0
                and _next_round_needs_spy(head) and now >= ra - _EARLY_RESPY_LEAD)
    if st == "SPYING":
        from espionage_manager import _load_missions
        return _spy_report_ready(_load_missions().get("missions", []), head, now)
    return False


def next_farm_eta():
    """Soonest wake time for the queue head (IDLE next run / ATTACKING return / SPYING
    backstop), or None. A live spy's own ETA is already scheduled via spy_eta; the SPYING
    value here is the backstop that guarantees a stuck head (dead mission) is re-evaluated
    at the grace deadline, then the timeout — instead of relying on the opportunistic poll."""
    head = _queue_head(_enabled_targets())
    if not head:
        return None
    now = int(time.time())
    st = head.get("state", "IDLE")
    if st == "SPYING":
        disp = int(head.get("spy_dispatched_at", 0))
        grace = disp + _SPY_STUCK_GRACE
        return max(now, grace if now < grace else disp + _SPY_TIMEOUT_SECS)
    if st == "IDLE":
        # Soonest next_run over ALL idle targets — with due-preference in _queue_head,
        # whichever becomes due first will be the head at that moment.
        runs = [int(t.get("next_run_at", 0) or 0) for t in _enabled_targets()
                if t.get("state", "IDLE") == "IDLE"]
        return max(min(runs) if runs else int(head.get("next_run_at", 0)), now)
    if st == "ATTACKING":
        ra = int(head.get("attack_return_at", 0))
        if (early_respy_enabled() and int(head.get("respy_launched_at", 0)) == 0
                and _next_round_needs_spy(head)):
            return max(ra - _EARLY_RESPY_LEAD, now)
        return max(ra, now)
    return None


def process_farm_targets(session, in_active_hours=True):
    if not in_active_hours:
        return
    from empire_utils import is_paused
    if is_paused():
        return
    targets = _enabled_targets()
    if not targets:
        return

    import json
    from db_manager import farm_update, queue_add
    from espionage_manager import _load_missions, SPY_COUNTS_PATH, OWN_CITIES_PATH
    from attack_manager import (
        _get_best_origin_city, _build_troop_units, _build_fleet_units,
        _enemy_fleet_count, _classify_enemy_fleet, _calc_travel_secs,
        MILITARY_JSON_PATH,
    )

    def _load(path, default):
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    own_cities  = _load(OWN_CITIES_PATH, [])
    spy_counts  = _load(SPY_COUNTS_PATH, {})
    military    = _load(MILITARY_JSON_PATH, {})
    missions    = _load_missions().get("missions", [])
    first_city_id = str(own_cities[0]["cityId"]) if own_cities else None
    farm_army   = get_farm_army()   # {} → send all troops (legacy behaviour)
    spy_agents  = get_farm_spy_agents()
    now = int(time.time())

    ship_cap = 500
    try:
        from ikabot.helpers.pedirInfo import getShipCapacity
        cap, _ = getShipCapacity(session)
        if cap > 0:
            ship_cap = cap
    except Exception:
        pass

    def _enqueue_attack(t, loot, enemy_ships, combat_ships=0):
        """Pick origin, build units and enqueue the attack(s). Returns (return_at,
        transporters) or None if no usable origin. Cadence is the real round-trip.
        combat_ships > 0 → the blockade wave has to FIGHT (not just scare off flee
        ships), so the troops get an extra battle margin before sailing."""
        name = t.get("target_city_name", t["target_city_id"])
        ix, iy = t.get("island_x", 0), t.get("island_y", 0)
        required = set(farm_army) if farm_army else None
        origin = _get_best_origin_city(ix, iy, military, needs_fleet=(enemy_ships > 0),
                                       required_units=required)
        if not origin:
            return None
        # ── F4.b: decide whether this wave needs a blockade first ───────────────
        # enemy_ships>0  → fleet present now → blockade first.
        # enemy_ships==0 on a known fleet-target whose fleet is still dispersed
        #   (enemy_return_at in the future) → troops only, AS LONG AS they land before the
        #   fleet returns; if it would return first, clear the port again with a blockade.
        need_fleet = enemy_ships > 0
        ret_at = int(t.get("enemy_return_at", 0))
        if enemy_ships == 0 and ret_at > now:
            troop_j = int(t.get("last_troop_journey", 0))
            if troop_j <= 0 or now + troop_j + 300 >= ret_at:
                need_fleet = True   # fleet back too soon (or timing unknown) → re-blockade

        origin = _get_best_origin_city(ix, iy, military, needs_fleet=need_fleet,
                                       required_units=required)
        if not origin:
            return None
        origin_name, origin_id, ox, oy = origin

        # Size troops/fleet from LIVE origin counts: the 8h military cache lags the loadout
        # units cycling through raids, so cached counts get rejected with "no units selected".
        try:
            from empire_collector import refresh_city_military
            fresh = refresh_city_military(session, origin_id, origin_name)
            if fresh:
                military.setdefault("byCityName", {})[origin_name] = fresh
        except Exception:
            pass

        fleet_travel = _calc_travel_secs(ox, oy, ix, iy)
        troop_travel = int(fleet_travel * 2 / 3)   # rough fallback (real times below)
        transporters = max(1, math.ceil(loot / ship_cap))
        if farm_army:
            avail = military.get("byCityName", {}).get(origin_name, {}).get("troops", {})
            troop_units = {uid: min(qty, avail.get(uid, {}).get("amount", 0))
                           for uid, qty in farm_army.items()
                           if avail.get(uid, {}).get("amount", 0) > 0}
        else:
            troop_units = _build_troop_units(origin_name, military)
        if not troop_units:
            return None

        # Combat fleet for the blockade: the configured small loadout (e.g. 10 steam rams)
        # capped to what the origin has; empty loadout → whole fleet (legacy).
        fleet_units = {}
        if need_fleet:
            farm_fleet = get_farm_fleet()
            if farm_fleet:
                avail_f = military.get("byCityName", {}).get(origin_name, {}).get("fleet", {})
                fleet_units = {uid: min(qty, avail_f.get(uid, {}).get("amount", 0))
                               for uid, qty in farm_fleet.items()
                               if avail_f.get(uid, {}).get("amount", 0) > 0}
            if not fleet_units:
                fleet_units = _build_fleet_units(origin_name, military)

        # Real travel time from the game form (slowest unit sets the pace). Fetched for EVERY
        # raid now, not just fleet ones: the cheap _calc_travel_secs estimate can overshoot
        # badly, leaving attack_return_at far in the future so the target stays stuck in
        # ATTACKING (troops already home, ships free) and blocks the whole queue. One extra
        # throttled form fetch is worth an accurate return time.
        is_fleet_target = need_fleet or ret_at > 0 or int(t.get("is_fleet_target", 0)) == 1
        est_fleet, est_troop = fleet_travel, troop_travel
        try:
            import ikabot.config as ikc
            from attack_manager import (fetch_fleet_journey, fetch_troop_journey,
                                        record_travel_calibration)
            rt = fetch_troop_journey(session, ikc, origin_id, t["target_city_id"])
            if rt:
                troop_travel = rt
                record_travel_calibration("troop", est_troop, rt)
            if need_fleet:
                rf = fetch_fleet_journey(session, ikc, origin_id, t["target_city_id"],
                                         list(fleet_units))
                if rf:
                    fleet_travel = rf
                    record_travel_calibration("fleet", est_fleet, rf)
        except Exception:
            logger.warning("[farm] %s: leitura de tempos reais falhou — a usar estimativa", name)

        base = {
            "originCityId":     str(origin_id), "originCityName": origin_name,
            "targetCityId":     str(t["target_city_id"]), "targetCityName": name,
            "targetPlayerName": t.get("target_player", ""),
            "islandX": ix, "islandY": iy, "islandId": str(t.get("island_id", "")),
            "targetType": "enemy", "addedAt": now,
        }
        new_enemy_return = ret_at  # unchanged unless we blockade again

        if need_fleet:
            # Wave 1: blockade fleet leaves now, ARRIVES at now+fleet_travel and drives the
            # enemy fleet off (it flees & disperses). Wave 2: troops timed to LAND fleet_lead
            # after the fleet — inside the clean window. Transports are usually faster than
            # warships, so we DELAY the troop launch (real times) so the order is fleet→troops.
            queue_add("attack", dict(base, missionType="fleet",
                      units=fleet_units, transporters=0, dispatchAfter=now))
            fleet_lead    = max(1, int(t.get("fleet_lead_min", 5))) * 60
            if combat_ships > 0:
                fleet_lead += _SEA_BATTLE_MARGIN_SECS   # sea battle rounds take ~15 min
            fleet_arrival = now + fleet_travel
            troop_arrival = fleet_arrival + fleet_lead
            army_after    = max(now, troop_arrival - troop_travel)
            return_at     = troop_arrival + troop_travel + 300
            # the driven-off fleet returns disperse_min after the blockade lands
            new_enemy_return = fleet_arrival + max(1, int(t.get("disperse_min", 240))) * 60
            logger.info("[farm] %s: bloqueio+tropas de %s (saque ~%d, %d navios) — frota chega "
                        "em %dmin, tropas %dmin depois; inimigo volta ~%dh depois",
                        name, origin_name, loot, transporters, round(fleet_travel / 60),
                        fleet_lead // 60, max(1, int(t.get("disperse_min", 240))) // 60)
        else:
            army_after    = now
            troop_arrival = now + troop_travel
            return_at     = troop_arrival + troop_travel + 300
            if ret_at > now:
                logger.info("[farm] %s: só tropas de %s (porto limpo — frota inimiga dispersa "
                            "até ~%dmin) (saque ~%d, %d navios)",
                            name, origin_name, max(0, (ret_at - now) // 60), loot, transporters)
            else:
                logger.info("⚔️ [farm] %s: ataque agendado de %s (saque ~%d, %d navios)",
                            name, origin_name, loot, transporters)
        queue_add("attack", dict(base, missionType="army",
                  units=troop_units, transporters=transporters, dispatchAfter=army_after))
        return {"return_at": return_at, "transporters": transporters,
                "enemy_return_at": new_enemy_return, "troop_journey": troop_travel,
                "is_fleet_target": 1 if (is_fleet_target or enemy_ships > 0) else 0}

    def _launch_respy(t, need_garrison=True):
        """Re-scout a target: reuse spies already stationed there (fast, no travel, no
        spies burned), else dispatch fresh ones. `need_garrison=False` → warehouse-only
        re-scout (safe target). Returns 'stationed'/'dispatched' on success, or None when
        no spy origin is available."""
        tid = t["target_city_id"]
        from espionage_manager import reexecute_stationed_spy
        if reexecute_stationed_spy(tid, fast=True, need_garrison=need_garrison):
            return "stationed"
        origin = _pick_spy_origin(own_cities, spy_counts, t)
        if not origin:
            return None
        queue_add("spy_dispatch", {
            "originCityId":     str(origin["cityId"]),
            "targetCityId":     str(tid),
            "islandId":         str(t.get("island_id", "")),
            "targetPlayerName": t.get("target_player", ""),
            "targetCityName":   t.get("target_city_name", tid),
            "islandX":          t.get("island_x", 0),
            "islandY":          t.get("island_y", 0),
            "numAgents":        spy_agents,
            "numDecoys":        0,
            "fast":             True,   # warehouse→garrison back-to-back
            "needGarrison":     bool(need_garrison),
            "queuedAt":         now,
        })
        return "dispatched"

    def _safe_target_verdict(t):
        """Decide a target's next re-scout. EVERY verdict starts with a live inactivity
        re-check at the coordinates (user rule: never spy or attack without re-confirming
        the owner is still inactive). Returns:
          - "disable": the owner is active again → disabled + alerted.
          - "garrison": needs a FULL scout — first contact, a fleet target, OR (P5.5) a safe
            target whose inactivity could NOT be confirmed (island fetch + scan both failed).
            Escalating to a garrison scout instead of attacking blind closes the fail-open hole.
          - "warehouse": safe target confirmed still inactive → a warehouse-only re-scout is safe.
        """
        confirmed = _confirm_inactive(session, t)
        if confirmed is False:
            _disable_active_target(t)
            return "disable"
        if confirmed == "vacation":
            _skip_vacation_target(t)
            return "skip"
        if int(t.get("last_spy_at", 0)) == 0 or int(t.get("is_fleet_target", 0)) == 1:
            return "garrison"
        return "warehouse" if confirmed is True else "garrison"

    # Pure queue: work ONLY the head target (the active one, else the best loot/hour).
    # Iterating over a 1-item list keeps the existing `continue`-based body intact.
    head = _queue_head(targets)
    for t in ([head] if head else []):
        tid      = t["target_city_id"]
        state    = t.get("state", "IDLE")
        interval = max(1, int(t.get("interval_hours", 8))) * 3600
        name     = t.get("target_city_name", tid)

        # ── IDLE → next raid ────────────────────────────────────────────────
        # Two regimes:
        #  • SAFE target (is_fleet_target=0, set by a FULL scout that confirmed no fleet):
        #    raid directly with troops, no scout. An inactive owner can't gain a fleet/army
        #    (game rule), so the only risk is the owner reactivating — re-confirmed below
        #    every `respy_every` rounds, not every round.
        #  • FLEET target (is_fleet_target=1, e.g. The Rock): never direct-attack — always a
        #    full re-scout (garrison + movements) because its fleet flees and returns.
        # The danger from the old blind shortcut (sending troops into a returning fleet) is
        # gone: the gate is is_fleet_target, which only a full scout can set to 0.
        if state == "IDLE":
            if now < int(t.get("next_run_at", 0)):
                continue

            min_loot   = int(t.get("min_loot", 50000))
            first_scout = int(t.get("last_spy_at", 0)) == 0

            # ── Direct raid on a safe target (no scout) ─────────────────────
            # A target counts as DRAINED (→ re-scout, don't raid on stale intel) when EITHER
            # signal says so: (a) the ESTIMATED warehouse — scouted last_loot minus loot already
            # brought home since that scout — has dropped below min_loot (cumulative drainage,
            # catches the wasteful LAST raid one step early); or (b) the last real return was
            # itself below min_loot (troops carry min(warehouse, capacity), so a tiny return
            # proves the warehouse is near-empty NOW even if the scout still reads 268k). Both
            # are needed: the estimate misses a suddenly-small warehouse, the last return misses
            # a steady drain that hasn't dipped below the bar yet. Together they stop the bot
            # sending the whole army round-trip for scraps (F1 / the 5k-return-vs-268k-scout bug).
            est = _estimated_warehouse(t)
            recent = _recent_return_loot(t)
            drained = est < min_loot or (recent is not None and recent < min_loot)
            if (not first_scout and not _next_round_needs_spy(t)
                    and int(t.get("is_fleet_target", 0)) == 0
                    and not drained):
                # Live inactivity check at the coordinates immediately before the raid
                # (user rule): False → target gone; None → scout instead of blind attack.
                confirmed = _confirm_inactive(session, t)
                if confirmed is False:
                    _disable_active_target(t)
                    continue
                if confirmed == "vacation":
                    _skip_vacation_target(t)
                    continue
                if confirmed is None:
                    logger.info("[farm] %s: inactividade não confirmada em tempo real — "
                                "a re-espiar antes de atacar", name)
                if confirmed is True:
                    res = _enqueue_attack(t, est, 0)   # size troops to the realistic remaining loot
                    if res:
                        farm_update(tid, {
                            "state": "ATTACKING", "attack_return_at": res["return_at"],
                            "last_attack_at": now, "last_transporters": res["transporters"],
                            "raids_since_spy": int(t.get("raids_since_spy", 0)) + 1,
                            "total_raids": int(t.get("total_raids", 0)) + 1,
                            "enemy_return_at": res["enemy_return_at"],
                            "last_troop_journey": res["troop_journey"],
                        })
                        logger.info("⚔️ [farm] %s: ataque directo (~%d estimado, sem re-espionagem)", name, est)
                        continue
                    # Origin has no free troops/ships right now (still returning) — retry when
                    # they land, don't burn a scout.
                    eta = _ships_back_eta(t, now, session, first_city_id)
                    farm_update(tid, {"state": "IDLE", "next_run_at": eta, "next_action": "attack"})
                    logger.info("[farm] %s: sem tropas/navios livres na origem — nova tentativa ~%dmin",
                                name, max(0, (eta - now) // 60))
                    continue
            elif (not first_scout and not _next_round_needs_spy(t)
                    and int(t.get("is_fleet_target", 0)) == 0
                    and int(t.get("last_loot", 0)) >= min_loot and drained):
                # Scouted loot still looks rich but the target is drained — re-scout instead of
                # sending a raid that would scrape the bottom (F1).
                reason = ("último regresso real %d" % recent
                          if recent is not None and recent < min_loot
                          else "armazém estimado %d" % est)
                logger.info("[farm] %s: %s < %d (drenado) — a re-espiar em vez de atacar "
                            "a última vaga por migalhas", name, reason, min_loot)

            # ── Periodic / first scout ──────────────────────────────────────
            # First contact and fleet targets need the full garrison; a safe target's periodic
            # re-scout is warehouse-only (loot + drained check) and instead re-confirms the
            # owner is still inactive — the only thing that can turn it unsafe.
            verdict = _safe_target_verdict(t)
            if verdict in ("disable", "skip"):
                continue
            need_garrison = (verdict == "garrison")

            spy = _launch_respy(t, need_garrison=need_garrison)
            if spy is None:
                logger.info("[farm] %s: sem cidade com espiões — nova tentativa em 1h", name)
                farm_update(tid, {"next_run_at": now + 3600})
                continue
            farm_update(tid, {"state": "SPYING", "spy_dispatched_at": now,
                              "last_spy_at": now, "respy_launched_at": 0})
            tag = "" if need_garrison else " (só armazém)"
            if spy == "stationed":
                logger.info("[farm] %s: re-execução nos espiões já estacionados%s", name, tag)
            else:
                logger.info("[farm] %s: re-espionagem enviada (%d espião(s))%s", name, spy_agents, tag)
            continue

        # ── SPYING → evaluate the fresh report ──────────────────────────────
        if state == "SPYING":
            m = _latest_done_report(missions, tid, int(t.get("spy_dispatched_at", 0)) - 120)
            if not m:
                from espionage_manager import latest_failed_after
                if latest_failed_after(tid, int(t.get("spy_dispatched_at", 0))):
                    # the (reused or fresh) spy was detected/gone — retry soon with a dispatch
                    wait = random.randint(5, 15) * 60
                    logger.info("[farm] %s: espião falhou — nova espionagem em %dmin", name, wait // 60)
                    farm_update(tid, {"state": "IDLE", "next_run_at": now + wait, "next_action": "spy"})
                elif _spy_is_stuck(t, now):
                    # No report, no failure, and no in-flight mission: the dispatch never took.
                    # Release the head now so the queue advances instead of blocking on it for
                    # the full timeout. Short retry, like the failed path.
                    wait = random.randint(5, 15) * 60
                    logger.info("[farm] %s: espião não chegou a partir — nova espionagem em %dmin", name, wait // 60)
                    farm_update(tid, {"state": "IDLE", "next_run_at": now + wait, "next_action": "spy"})
                elif now - int(t.get("spy_dispatched_at", 0)) > _SPY_TIMEOUT_SECS:
                    # Last-resort backstop only: the mission is still 'live' after 13h, beyond
                    # the espionage machine's own 12h termination. Free the head so the queue
                    # can't freeze. NOT the normal path — a live mission is left to reach
                    # DONE (evaluated above) or FAILED (retried above) on its own.
                    logger.warning("[farm] %s: espião preso há >13h — a libertar (backstop)", name)
                    farm_update(tid, {"state": "IDLE", "next_run_at": now + interval,
                                      "next_action": "spy"})
                # else: mission is live and within the backstop → keep waiting. The espionage
                # state machine owns its progression; the farm no longer aborts it on a naive
                # wall-clock, which used to kill in-flight reports across downtime.
                continue

            loot     = sum((m.get("result") or {}).get("resources", {}).values())
            garrison = (m.get("garrisonResult") or {}).get("troops") or {}
            # Type-based decision: flee ships (lancha/reparador) are driven off by a blockade;
            # any other warship actually fights → too dangerous. combat ships beyond the
            # tolerated cap (max_enemy_ships, default 0) → skip + alert.
            combat_ships, flee_ships = _classify_enemy_fleet(garrison)
            min_loot   = int(t.get("min_loot", 50000))
            max_combat = int(t.get("max_enemy_ships", 0))

            if loot < min_loot:
                # Drained: the target's scouted loot fell below its threshold → disable it
                # for good and let the queue advance to the next-best target.
                logger.info("[farm] %s: saque %d < %d — drenado, alvo desactivado",
                            name, loot, min_loot)
                try:
                    from telegram_notifier import notify_farm_drained
                    notify_farm_drained(name, t.get("target_player", ""), loot)
                except Exception:
                    pass
                # Also hide it from the inactives list (mark 'ignorar' → moves to the
                # "Ignoradas" tab, reversible there) — a drained target is just noise.
                try:
                    from espionage_manager import _auto_mark_ignored
                    _auto_mark_ignored(tid, t.get("target_player", ""),
                                       t.get("island_x", ""), t.get("island_y", ""),
                                       f"Drenado pelo farm — saque {loot} < {min_loot}")
                except Exception:
                    pass
                farm_update(tid, {"state": "IDLE", "enabled": 0, "last_loot": loot,
                                  "next_action": "spy"})
                continue
            if combat_ships > max_combat:
                logger.warning("[farm] %s: %d navios de combate > máximo %d — "
                               "alvo saltado + alerta", name, combat_ships, max_combat)
                try:
                    from telegram_notifier import notify_farm_blocked
                    notify_farm_blocked(name, t.get("target_player", ""), combat_ships)
                except Exception:
                    pass
                farm_update(tid, {"state": "IDLE", "next_run_at": now + interval,
                                  "last_loot": loot, "last_enemy_ships": combat_ships + flee_ships,
                                  "is_fleet_target": 1,
                                  "next_action": "spy"})
                continue

            # Every enemy ship must be cleared by the blockade wave before the troops sail:
            # unescorted transports lose ANY sea fight (seen live: 150 hoplites bounced off
            # 2 triremes). Flee ships run from the blockade; tolerated combat ships
            # (≤ max_enemy_ships) get fought by it — never ignored.
            enemy_ships = flee_ships + combat_ships

            # Don't launch while the previous raid's ships are still returning — keep
            # the fresh intel and retry directly in a few minutes once they're back.
            if enemy_ships == 0 and _free_ships(session) < 1:
                eta = _ships_back_eta(t, now, session, first_city_id)
                farm_update(tid, {"state": "IDLE", "next_run_at": eta,
                                  "last_loot": loot, "last_enemy_ships": enemy_ships,
                                  "next_action": "attack"})
                logger.info("[farm] %s: relatório pronto mas 0 navios — ataque agendado para o regresso (~%dmin)",
                            name, max(0, (eta - now) // 60))
                continue

            # Live inactivity check at the coordinates immediately before launching (user
            # rule). None → proceed: unlike the direct raid there IS a fresh spy report in
            # hand, so a failed island fetch doesn't force a blind decision.
            confirmed = _confirm_inactive(session, t)
            if confirmed is False:
                _disable_active_target(t)
                continue
            if confirmed == "vacation":
                _skip_vacation_target(t)
                continue

            res = _enqueue_attack(t, loot, enemy_ships, combat_ships)
            if not res:
                # Report is fresh; we just lack free troops/ships now (returning) → retry when
                # they land and attack directly, no need to re-scout.
                eta = _ships_back_eta(t, now, session, first_city_id)
                logger.info("[farm] %s: relatório pronto mas sem tropas/navios livres — "
                            "nova tentativa ~%dmin", name, max(0, (eta - now) // 60))
                farm_update(tid, {"state": "IDLE", "next_run_at": eta, "last_loot": loot,
                                  "last_enemy_ships": enemy_ships, "next_action": "attack"})
                continue
            farm_update(tid, {
                "state": "ATTACKING", "attack_return_at": res["return_at"], "last_attack_at": now,
                "last_loot": loot, "last_enemy_ships": enemy_ships,
                "last_transporters": res["transporters"], "raids_since_spy": 1,
                "total_raids": int(t.get("total_raids", 0)) + 1,
                "total_loot": int(t.get("total_loot", 0)) + loot,
                "respy_launched_at": 0,
                "enemy_return_at": res["enemy_return_at"],
                "last_troop_journey": res["troop_journey"],
                "is_fleet_target": res["is_fleet_target"],
            })
            continue

        # ── ATTACKING → wait for the real return, then relaunch soon ────────
        if state == "ATTACKING":
            return_at = int(t.get("attack_return_at", 0))
            # Refresh movements (rate-limited) so the in-flight state is current before we
            # decide whether the raid is still out.
            if first_city_id and now - getattr(process_farm_targets, "_atk_mv_refresh", 0) > 90:
                process_farm_targets._atk_mv_refresh = now
                try:
                    from empire_collector import refresh_movements
                    refresh_movements(session, first_city_id)
                except Exception:
                    pass
            # Refine the wake from the actual fleet movement when available
            real = _real_return_eta(t)
            if real and abs(real - return_at) > 60:
                farm_update(tid, {"attack_return_at": real})
                return_at = real
            elif (not real and now < return_at and int(t.get("last_attack_at", 0)) > 0
                  and not _raid_in_flight(t)
                  and now - int(t.get("last_attack_at", 0)) > _RAID_GRACE_SECS):
                # The estimate overshot: no movement to/from this target and grace has passed →
                # troops are already home and ships are free. Don't block the queue any longer.
                logger.info("[farm] %s: tropas já em casa (sem movimento em curso) — estimativa "
                            "de regresso era longa demais, a desbloquear a fila", name)
                return_at = now

            # Pipelined re-spy: scout WHILE the troops are still on their way home (spies
            # use the safehouse, not ships) so a re-spy round is ready to attack the moment
            # they dock — no extra spy round-trip afterwards. Fired ~_EARLY_RESPY_LEAD before
            # arrival so the loot reading reflects the (re-accumulated) warehouse.
            if (now < return_at and early_respy_enabled()
                    and int(t.get("respy_launched_at", 0)) == 0
                    and _next_round_needs_spy(t)
                    and now >= return_at - _EARLY_RESPY_LEAD):
                # Safe targets pipeline a warehouse-only re-scout (+inactivity re-check); fleet
                # targets and unconfirmed-inactivity (P5.5) pipeline the full garrison scout.
                verdict = _safe_target_verdict(t)
                if verdict in ("disable", "skip"):
                    continue
                need_garrison = (verdict == "garrison")
                spy = _launch_respy(t, need_garrison=need_garrison)
                if spy:
                    farm_update(tid, {"respy_launched_at": now,
                                      "spy_dispatched_at": now, "last_spy_at": now})
                    logger.info("[farm] %s: re-espionagem antecipada enquanto as tropas regressam (%s%s)",
                                name, spy, "" if need_garrison else ", só armazém")
                continue

            if now >= return_at:
                # Bounce detection: a raid that came home without ANY registered loot most
                # likely turned back from a sea fight (enemy warship docked since the last
                # garrison scout — seen live with 2 triremes at a "safe" target). Don't
                # re-attack blind: force a FULL garrison re-scout (fleet targets always get
                # one) so the blockade/skip logic can see the port. Worst case (loot_log
                # missed a real return) costs one spy round instead of a 6h bounced raid.
                if int(t.get("last_attack_at", 0) or 0) > 0 and _recent_return_loot(t) is None:
                    delay = random.randint(*_RELAUNCH_DELAY_RANGE) * 60
                    farm_update(tid, {"state": "IDLE", "next_run_at": now + delay,
                                      "next_action": "spy", "is_fleet_target": 1,
                                      "respy_launched_at": 0})
                    logger.warning("[farm] %s: tropas regressaram SEM saque registado — "
                                   "possível ricochete naval; re-espionagem completa em %dmin",
                                   name, delay // 60)
                    continue
                if int(t.get("respy_launched_at", 0)) > 0:
                    # An early re-spy is already in flight/done — hand straight to the
                    # SPYING evaluator (attacks as soon as the report + ships are ready),
                    # skipping the IDLE backoff and a redundant second scout.
                    farm_update(tid, {"state": "SPYING", "respy_launched_at": 0})
                    logger.info("[farm] %s: tropas em casa — a avaliar o relatório antecipado", name)
                    continue
                respy_every = max(1, int(t.get("respy_every", 3)))
                rss = int(t.get("raids_since_spy", 0))
                # Re-spy if it's time, or if the target ever showed a fleet (needs fresh intel)
                next_action = "spy" if (rss >= respy_every or int(t.get("last_enemy_ships", 0)) > 0) else "attack"
                delay = random.randint(*_RELAUNCH_DELAY_RANGE) * 60
                farm_update(tid, {"state": "IDLE", "next_run_at": now + delay,
                                  "next_action": next_action})
                logger.info("[farm] %s: tropas regressaram — próxima ronda em %dmin (%s)",
                            name, delay // 60, next_action)
            continue
