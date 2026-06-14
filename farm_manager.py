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

import math
import time

from empire_utils import LOGS_DIR, logger

_SPY_TIMEOUT_SECS = 6 * 3600


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
    now = int(time.time())

    ship_cap = 500
    try:
        from ikabot.helpers.pedirInfo import getShipCapacity
        cap, _ = getShipCapacity(session)
        if cap > 0:
            ship_cap = cap
    except Exception:
        pass

    for t in targets:
        tid      = t["target_city_id"]
        state    = t.get("state", "IDLE")
        interval = max(1, int(t.get("interval_hours", 8))) * 3600
        name     = t.get("target_city_name", tid)

        # ── IDLE → start a re-spy when due ──────────────────────────────────
        if state == "IDLE":
            if now < int(t.get("next_run_at", 0)):
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
                "numAgents":        1,
                "numDecoys":        0,
                "queuedAt":         now,
            })
            farm_update(tid, {"state": "SPYING", "spy_dispatched_at": now, "last_spy_at": now})
            logger.info("[farm] %s: re-espionagem enviada de %s", name, origin.get("name"))
            continue

        # ── SPYING → evaluate the fresh report ──────────────────────────────
        if state == "SPYING":
            m = _latest_done_report(missions, tid, int(t.get("spy_dispatched_at", 0)) - 120)
            if not m:
                if now - int(t.get("spy_dispatched_at", 0)) > _SPY_TIMEOUT_SECS:
                    logger.info("[farm] %s: sem relatório após 6h — a reagendar", name)
                    farm_update(tid, {"state": "IDLE", "next_run_at": now + interval})
                continue

            loot     = sum((m.get("result") or {}).get("resources", {}).values())
            garrison = (m.get("garrisonResult") or {}).get("troops") or {}
            enemy_ships = _enemy_fleet_count(garrison)
            min_loot = int(t.get("min_loot", 50000))
            max_ships = int(t.get("max_enemy_ships", 0))

            if loot < min_loot:
                logger.info("[farm] %s: saque %d < %d — a reagendar", name, loot, min_loot)
                farm_update(tid, {"state": "IDLE", "next_run_at": now + interval, "last_loot": loot})
                continue
            if enemy_ships > max_ships:
                logger.info("[farm] %s: frota inimiga %d > máx %d — a reagendar", name, enemy_ships, max_ships)
                farm_update(tid, {"state": "IDLE", "next_run_at": now + interval, "last_loot": loot})
                continue

            origin = _get_best_origin_city(t.get("island_x", 0), t.get("island_y", 0),
                                           military, needs_fleet=(enemy_ships > 0))
            if not origin:
                logger.warning("[farm] %s: sem origem com tropas — a reagendar", name)
                farm_update(tid, {"state": "IDLE", "next_run_at": now + interval, "last_loot": loot})
                continue

            origin_name, origin_id, ox, oy = origin
            travel       = _calc_travel_secs(ox, oy, t.get("island_x", 0), t.get("island_y", 0))
            troop_travel = int(travel * 2 / 3)
            battle_delay = _estimate_battle_delay_mins(enemy_ships, {}) * 60
            transporters = max(1, math.ceil(loot / ship_cap))
            troop_units  = _build_troop_units(origin_name, military)

            base = {
                "originCityId":     str(origin_id),
                "originCityName":   origin_name,
                "targetCityId":     str(tid),
                "targetCityName":   name,
                "targetPlayerName": t.get("target_player", ""),
                "islandX":          t.get("island_x", 0),
                "islandY":          t.get("island_y", 0),
                "islandId":         str(t.get("island_id", "")),
                "targetType":       "enemy",
                "addedAt":          now,
            }
            if enemy_ships > 0:
                # Clear the port first, then send troops after the battle delay
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

            farm_update(tid, {
                "state": "ATTACKING", "attack_return_at": return_at, "last_attack_at": now,
                "last_loot": loot, "total_raids": int(t.get("total_raids", 0)) + 1,
                "total_loot": int(t.get("total_loot", 0)) + loot,
            })
            logger.info("[farm] %s: ataque agendado de %s (saque ~%d, %d navios)",
                        name, origin_name, loot, transporters)
            continue

        # ── ATTACKING → wait for the troops to get back, then loop ──────────
        if state == "ATTACKING":
            if now >= int(t.get("attack_return_at", 0)):
                logger.info("[farm] %s: ciclo concluído — próxima ronda em %dh",
                            name, interval // 3600)
                farm_update(tid, {"state": "IDLE", "next_run_at": now + interval})
            continue
