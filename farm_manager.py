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


def _enabled_targets():
    try:
        from db_manager import farm_list
        return [t for t in farm_list() if t.get("enabled")]
    except Exception:
        logger.error("[farm] leitura de alvos falhou", exc_info=True)
        return []


def has_active_farm():
    return bool(_enabled_targets())


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
    """Read the ACTUAL return time of our troops/fleet from movements.json (a returning
    own movement coming from the target's city/player). More accurate than the coordinate
    estimate — accounts for the game's real speeds. Returns ts or None."""
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
        origin = (m.get("origin") or "").lower()
        if (city and city in origin) or (player and player in origin):
            arr = m.get("arrivalTime", 0)
            if arr and (best is None or arr < best):
                best = arr
    return best


def _spy_report_ready(missions, t, now):
    """True if a SPYING target either has a fresh report or has timed out."""
    if _latest_done_report(missions, t["target_city_id"], int(t.get("spy_dispatched_at", 0)) - 120):
        return True
    return now - int(t.get("spy_dispatched_at", 0)) > _SPY_TIMEOUT_SECS


def has_due_farm():
    """Precise due-check for smart_sleep — must be True only when an action will actually
    be taken, otherwise the wake loop would spin (the SPYING branch reads missions)."""
    targets = _enabled_targets()
    if not targets:
        return False
    now = int(time.time())
    missions = None
    for t in targets:
        st = t.get("state", "IDLE")
        if st == "IDLE" and now >= int(t.get("next_run_at", 0)):
            return True
        if st == "ATTACKING" and now >= int(t.get("attack_return_at", 0)):
            return True
        if st == "SPYING":
            if missions is None:
                from espionage_manager import _load_missions
                missions = _load_missions().get("missions", [])
            if _spy_report_ready(missions, t, now):
                return True
    return False


def next_farm_eta():
    """Soonest farm wake time (IDLE next run / ATTACKING return) for smart_sleep, or None.
    SPYING is omitted — that wake is driven by the spy mission ETA already."""
    etas = []
    now = int(time.time())
    for t in _enabled_targets():
        st = t.get("state", "IDLE")
        if st == "IDLE":
            etas.append(max(int(t.get("next_run_at", 0)), now))
        elif st == "ATTACKING":
            etas.append(max(int(t.get("attack_return_at", 0)), now))
    return min(etas) if etas else None


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
        _enemy_fleet_count, _calc_travel_secs, _estimate_battle_delay_mins,
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
        origin_name, origin_id, ox, oy = origin
        travel       = _calc_travel_secs(ox, oy, ix, iy)
        troop_travel = int(travel * 2 / 3)
        battle_delay = _estimate_battle_delay_mins(enemy_ships, {}) * 60
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

        base = {
            "originCityId":     str(origin_id), "originCityName": origin_name,
            "targetCityId":     str(t["target_city_id"]), "targetCityName": name,
            "targetPlayerName": t.get("target_player", ""),
            "islandX": ix, "islandY": iy, "islandId": str(t.get("island_id", "")),
            "targetType": "enemy", "addedAt": now,
        }
        if enemy_ships > 0:
            queue_add("attack", dict(base, missionType="fleet",
                      units=_build_fleet_units(origin_name, military),
                      transporters=0, dispatchAfter=now))
            army_after = now + battle_delay
            return_at = now + battle_delay + troop_travel * 2 + 300
        else:
            army_after = now
            return_at = now + troop_travel * 2 + 300
        queue_add("attack", dict(base, missionType="army",
                  units=troop_units, transporters=transporters, dispatchAfter=army_after))
        logger.info("[farm] %s: ataque agendado de %s (saque ~%d, %d navios)",
                    name, origin_name, loot, transporters)
        return return_at, transporters

    for t in targets:
        tid      = t["target_city_id"]
        state    = t.get("state", "IDLE")
        interval = max(1, int(t.get("interval_hours", 8))) * 3600
        name     = t.get("target_city_name", tid)

        # ── IDLE → next raid: re-spy, or attack directly with last intel ────
        if state == "IDLE":
            if now < int(t.get("next_run_at", 0)):
                continue

            # Direct attack (skip re-spy) for a known-safe target between scout rounds
            if (t.get("next_action") == "attack" and int(t.get("last_loot", 0)) > 0
                    and int(t.get("last_enemy_ships", 0)) == 0):
                if _free_ships(session) < 1:
                    wait = random.randint(5, 15) * 60
                    farm_update(tid, {"next_run_at": now + wait})
                    logger.info("[farm] %s: sem navios livres — ataque adiado %dmin", name, wait // 60)
                    continue
                res = _enqueue_attack(t, int(t["last_loot"]), 0)
                if res:
                    return_at, transporters = res
                    farm_update(tid, {
                        "state": "ATTACKING", "attack_return_at": return_at,
                        "last_attack_at": now, "last_transporters": transporters,
                        "total_raids": int(t.get("total_raids", 0)) + 1,
                        "total_loot": int(t.get("total_loot", 0)) + int(t["last_loot"]),
                        "raids_since_spy": int(t.get("raids_since_spy", 0)) + 1,
                    })
                    logger.info("[farm] %s: ataque directo (sem re-espiar)", name)
                else:
                    farm_update(tid, {"next_action": "spy"})  # can't attack → spy next tick
                continue

            # Reuse spies already stationed at the target (re-run the warehouse mission)
            # instead of dispatching fresh ones — far faster and doesn't burn spies.
            from espionage_manager import reexecute_stationed_spy
            if reexecute_stationed_spy(tid, fast=True):
                farm_update(tid, {"state": "SPYING", "spy_dispatched_at": now, "last_spy_at": now})
                logger.info("[farm] %s: re-execução nos espiões já estacionados", name)
                continue

            origin = _pick_spy_origin(own_cities, spy_counts, t)
            if not origin:
                logger.info("[farm] %s: sem cidade com espiões — nova tentativa em 1h", name)
                farm_update(tid, {"next_run_at": now + 3600})
                continue
            queue_add("spy_dispatch", {
                "originCityId":     str(origin["cityId"]),
                "targetCityId":     str(tid),
                "islandId":         str(t.get("island_id", "")),
                "targetPlayerName": t.get("target_player", ""),
                "targetCityName":   name,
                "islandX":          t.get("island_x", 0),
                "islandY":          t.get("island_y", 0),
                "numAgents":        spy_agents,
                "numDecoys":        0,
                "fast":             True,   # farm re-scout: warehouse→garrison back-to-back
                "queuedAt":         now,
            })
            farm_update(tid, {"state": "SPYING", "spy_dispatched_at": now, "last_spy_at": now})
            logger.info("[farm] %s: re-espionagem enviada de %s (%d espião(s))",
                        name, origin.get("name"), spy_agents)
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
            enemy_ships = _enemy_fleet_count(garrison)
            min_loot = int(t.get("min_loot", 50000))
            max_ships = int(t.get("max_enemy_ships", 0))

            if loot < min_loot:
                logger.info("[farm] %s: saque %d < %d — a reagendar", name, loot, min_loot)
                farm_update(tid, {"state": "IDLE", "next_run_at": now + interval,
                                  "last_loot": loot, "next_action": "spy"})
                continue
            if enemy_ships > max_ships:
                logger.info("[farm] %s: frota inimiga %d > máx %d — a reagendar", name, enemy_ships, max_ships)
                farm_update(tid, {"state": "IDLE", "next_run_at": now + interval,
                                  "last_loot": loot, "next_action": "spy"})
                continue

            # Don't launch while the previous raid's ships are still returning — keep
            # the fresh intel and retry directly in a few minutes once they're back.
            if enemy_ships == 0 and _free_ships(session) < 1:
                wait = random.randint(5, 15) * 60
                farm_update(tid, {"state": "IDLE", "next_run_at": now + wait,
                                  "last_loot": loot, "last_enemy_ships": enemy_ships,
                                  "next_action": "attack"})
                logger.info("[farm] %s: relatório pronto mas 0 navios — ataque adiado %dmin",
                            name, wait // 60)
                continue

            res = _enqueue_attack(t, loot, enemy_ships)
            if not res:
                logger.warning("[farm] %s: sem origem utilizável — a reagendar", name)
                farm_update(tid, {"state": "IDLE", "next_run_at": now + interval,
                                  "last_loot": loot, "next_action": "spy"})
                continue
            return_at, transporters = res
            farm_update(tid, {
                "state": "ATTACKING", "attack_return_at": return_at, "last_attack_at": now,
                "last_loot": loot, "last_enemy_ships": enemy_ships,
                "last_transporters": transporters, "raids_since_spy": 1,
                "total_raids": int(t.get("total_raids", 0)) + 1,
                "total_loot": int(t.get("total_loot", 0)) + loot,
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
            if now >= return_at:
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
