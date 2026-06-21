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

_SPY_TIMEOUT_SECS = 6 * 3600
_RELAUNCH_DELAY_RANGE = (1, 15)   # random minutes after troops return before next raid
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


def _spy_report_ready(missions, t, now):
    """True if a SPYING target either has a fresh report or has timed out."""
    if _latest_done_report(missions, t["target_city_id"], int(t.get("spy_dispatched_at", 0)) - 120):
        return True
    return now - int(t.get("spy_dispatched_at", 0)) > _SPY_TIMEOUT_SECS


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
    return max(targets, key=lambda t: (_priority_score(t), int(t.get("last_loot", 0) or 0),
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
    """Soonest wake time for the queue head (IDLE next run / ATTACKING return), or None.
    SPYING is omitted — that wake is driven by the spy mission ETA already."""
    head = _queue_head(_enabled_targets())
    if not head:
        return None
    now = int(time.time())
    st = head.get("state", "IDLE")
    if st == "IDLE":
        return max(int(head.get("next_run_at", 0)), now)
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

    def _enqueue_attack(t, loot, enemy_ships):
        """Pick origin, build units and enqueue the attack(s). Returns (return_at,
        transporters) or None if no usable origin. Cadence is the real round-trip."""
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

        # Real travel times from the game forms (slowest unit sets the pace) — only for
        # fleet-related targets; pure plunder targets keep the cheap estimate (no extra HTTP).
        is_fleet_target = need_fleet or ret_at > 0 or int(t.get("is_fleet_target", 0)) == 1
        if is_fleet_target:
            try:
                import ikabot.config as ikc
                from attack_manager import fetch_fleet_journey, fetch_troop_journey
                rt = fetch_troop_journey(session, ikc, origin_id, t["target_city_id"])
                if rt:
                    troop_travel = rt
                if need_fleet:
                    rf = fetch_fleet_journey(session, ikc, origin_id, t["target_city_id"],
                                             list(fleet_units))
                    if rf:
                        fleet_travel = rf
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
                logger.info("[farm] %s: ataque agendado de %s (saque ~%d, %d navios)",
                            name, origin_name, loot, transporters)
        queue_add("attack", dict(base, missionType="army",
                  units=troop_units, transporters=transporters, dispatchAfter=army_after))
        return {"return_at": return_at, "transporters": transporters,
                "enemy_return_at": new_enemy_return, "troop_journey": troop_travel,
                "is_fleet_target": 1 if (is_fleet_target or enemy_ships > 0) else 0}

    def _launch_respy(t):
        """Re-scout a target: reuse spies already stationed there (fast, no travel, no
        spies burned), else dispatch fresh ones. Returns 'stationed'/'dispatched' on
        success, or None when no spy origin is available."""
        tid = t["target_city_id"]
        from espionage_manager import reexecute_stationed_spy
        if reexecute_stationed_spy(tid, fast=True):
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
            "queuedAt":         now,
        })
        return "dispatched"

    # Pure queue: work ONLY the head target (the active one, else the best loot/hour).
    # Iterating over a 1-item list keeps the existing `continue`-based body intact.
    head = _queue_head(targets)
    for t in ([head] if head else []):
        tid      = t["target_city_id"]
        state    = t.get("state", "IDLE")
        interval = max(1, int(t.get("interval_hours", 8))) * 3600
        name     = t.get("target_city_name", tid)

        # ── IDLE → next raid: always re-spy first ───────────────────────────
        # No "direct attack with last intel" shortcut: it assumed 0 enemy ships and could
        # send troops into a fleet that returned/appeared between scouts (e.g. a flee-fleet
        # target like The Rock whose lanchas come back). The pipelined re-spy (F4.c) launches
        # the scout WHILE the troops return, so re-spying every round costs ~nothing and
        # guarantees we know the port state before committing troops.
        if state == "IDLE":
            if now < int(t.get("next_run_at", 0)):
                continue

            # Re-scout (unless an early pipelined re-spy was already launched during the
            # troops' return — then we'd already be in SPYING, not here).
            spy = _launch_respy(t)
            if spy is None:
                logger.info("[farm] %s: sem cidade com espiões — nova tentativa em 1h", name)
                farm_update(tid, {"next_run_at": now + 3600})
                continue
            farm_update(tid, {"state": "SPYING", "spy_dispatched_at": now,
                              "last_spy_at": now, "respy_launched_at": 0})
            if spy == "stationed":
                logger.info("[farm] %s: re-execução nos espiões já estacionados", name)
            else:
                logger.info("[farm] %s: re-espionagem enviada (%d espião(s))", name, spy_agents)
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
                elif now - int(t.get("spy_dispatched_at", 0)) > _SPY_TIMEOUT_SECS:
                    logger.info("[farm] %s: sem relatório após 6h — a reagendar", name)
                    farm_update(tid, {"state": "IDLE", "next_run_at": now + interval,
                                      "next_action": "spy"})
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
                farm_update(tid, {"state": "IDLE", "enabled": 0, "last_loot": loot,
                                  "next_action": "spy"})
                continue
            if combat_ships > max_combat:
                logger.warning("[farm] %s: %d navios de combate (não fogem ao bloqueio) — "
                               "alvo saltado + alerta", name, combat_ships)
                try:
                    from telegram_notifier import notify_farm_blocked
                    notify_farm_blocked(name, t.get("target_player", ""), combat_ships)
                except Exception:
                    pass
                farm_update(tid, {"state": "IDLE", "next_run_at": now + interval,
                                  "last_loot": loot, "last_enemy_ships": combat_ships + flee_ships,
                                  "is_fleet_target": 1 if flee_ships > 0 else int(t.get("is_fleet_target", 0)),
                                  "next_action": "spy"})
                continue

            # Only flee ships remain → drive them off with the blockade; 0 → troops only.
            enemy_ships = flee_ships

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

            res = _enqueue_attack(t, loot, enemy_ships)
            if not res:
                logger.warning("[farm] %s: sem origem utilizável — a reagendar", name)
                farm_update(tid, {"state": "IDLE", "next_run_at": now + interval,
                                  "last_loot": loot, "next_action": "spy"})
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
            # Refine the wake from the actual fleet movement when available
            real = _real_return_eta(t)
            if real and abs(real - return_at) > 60:
                farm_update(tid, {"attack_return_at": real})
                return_at = real

            # Pipelined re-spy: scout WHILE the troops are still on their way home (spies
            # use the safehouse, not ships) so a re-spy round is ready to attack the moment
            # they dock — no extra spy round-trip afterwards. Fired ~_EARLY_RESPY_LEAD before
            # arrival so the loot reading reflects the (re-accumulated) warehouse.
            if (now < return_at and early_respy_enabled()
                    and int(t.get("respy_launched_at", 0)) == 0
                    and _next_round_needs_spy(t)
                    and now >= return_at - _EARLY_RESPY_LEAD):
                spy = _launch_respy(t)
                if spy:
                    farm_update(tid, {"respy_launched_at": now,
                                      "spy_dispatched_at": now, "last_spy_at": now})
                    logger.info("[farm] %s: re-espionagem antecipada enquanto as tropas regressam (%s)",
                                name, spy)
                continue

            if now >= return_at:
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
