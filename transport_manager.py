#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scheduled resource transports between own cities, fed by the Flask UI:
- manual transport queue (shared_queue "transport" in SQLite): origin, destination,
  resource amounts, ship count and type (transporters or freighters), dispatchAfter
- consolidation mode (à la ikabot "consolidate resources"): periodically sends the
  surplus (above the queue resourceBuffer and building-queue reservations) from every
  city to one destination city, using free transporters
Reuses the dispatch/bundling machinery from queue_processor.
"""

import json
import os
import random
import time

from empire_utils import LOGS_DIR, logger

TRANSPORT_QUEUE            = "transport"
OWN_CITIES_PATH            = os.path.join(LOGS_DIR, "own_cities.json")
CONSOLIDATE_SETTINGS_PATH  = os.path.join(LOGS_DIR, "consolidate_settings.json")
CONSOLIDATE_STATE_PATH     = os.path.join(LOGS_DIR, "consolidate_state.json")

# resources.json uses english display keys, in the canonical 5-resource order
_RESOURCES_ENG = ["Wood", "Wine", "Marble", "Crystal", "Sulfur"]

_DEFAULT_CONSOLIDATE_SETTINGS = {
    "enabled":       False,
    "destCityId":    "",
    "destCityName":  "",
    "intervalHours": 6,
    "minSendTotal":  1000,
    "shipType":      "transporters",  # transporters | freighters | both
}


# ── Manual transport queue ────────────────────────────────────────────────────

def _transport_queue_items():
    try:
        from db_manager import queue_items
        return queue_items(TRANSPORT_QUEUE)
    except Exception:
        logger.error("[transport] leitura da fila falhou", exc_info=True)
        return []


def has_pending_transports():
    return bool(_transport_queue_items())


def has_due_transports():
    """True only if a pending transport reached its dispatchAfter (smart_sleep guard)."""
    try:
        now = int(time.time())
        return any(int(it.get("dispatchAfter", 0)) <= now
                   for it in _transport_queue_items())
    except Exception:
        return False


def _get_own_city(city_id):
    try:
        with open(OWN_CITIES_PATH) as f:
            for c in json.load(f):
                if str(c.get("cityId")) == str(city_id):
                    return c
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def _dispatch_scheduled_transport(session, item):
    """Send one scheduled transport. Amounts and ships are capped to what is actually
    available at dispatch time (stock in origin, free ships, fleet capacity).
    Returns (ok, error_str)."""
    from ikabot.helpers.getJson import getCity
    from ikabot.helpers.naval import getAvailableShips, getAvailableFreighters
    from ikabot.helpers.pedirInfo import getShipCapacity
    from queue_processor import _dispatch_transport

    origin_id      = str(item["originCityId"])
    dest_id        = str(item["destCityId"])
    island_id      = str(item.get("islandId", ""))
    use_freighters = item.get("shipType") == "freighters"
    requested      = [max(0, int(a)) for a in (item.get("resources") or [0] * 5)][:5]
    ships_wanted   = int(item.get("ships", 0))

    if not island_id:
        dest = _get_own_city(dest_id)
        island_id = str((dest or {}).get("islandId", ""))
    if not island_id:
        return False, "destino sem islandId — força uma actualização do império"

    # Live ship availability at dispatch time (scheduling may have been hours ago)
    try:
        if use_freighters:
            available_ships = int(getAvailableFreighters(session))
        else:
            available_ships = int(getAvailableShips(session))
        time.sleep(random.randint(2, 5))
    except Exception:
        return False, "não foi possível obter navios disponíveis"
    ships = min(ships_wanted, available_ships)
    if ships <= 0:
        return False, f"sem {'cargueiros' if use_freighters else 'navios'} livres"

    # Cap amounts to the origin's current stock
    try:
        html = session.get("view=city&cityId={}".format(origin_id))
        city = getCity(html)
        stock = [int(v) for v in city.get("availableResources", [0] * 5)]
        time.sleep(random.randint(2, 5))
    except Exception:
        return False, "não foi possível ler recursos da origem"
    send_list = [min(requested[i], max(0, stock[i])) for i in range(5)]

    # Cap to fleet capacity
    try:
        ship_cap, freighter_cap = getShipCapacity(session)
    except Exception:
        ship_cap, freighter_cap = 500, 50000
    capacity = ships * (freighter_cap if use_freighters else ship_cap)
    total = sum(send_list)
    if total > capacity:
        scaled = []
        remaining_cap = capacity
        for amount in send_list:
            take = min(amount, remaining_cap)
            scaled.append(take)
            remaining_cap -= take
        send_list = scaled
        total = sum(send_list)
    if total <= 0:
        return False, "sem recursos disponíveis na origem"

    logger.info("[transport] a enviar %s → %s: %s (%d %s)",
                item.get("originCityName", origin_id), item.get("destCityName", dest_id),
                {k: v for k, v in zip(_RESOURCES_ENG, send_list) if v > 0},
                ships, "cargueiros" if use_freighters else "navios")
    ok = _dispatch_transport(session, origin_id, dest_id, island_id,
                             ships, send_list, use_freighters=use_freighters)
    return ok, None if ok else "servidor recusou o transporte (type=11)"


def process_transport_queue(session, in_active_hours=True):
    """Dispatch transports whose dispatchAfter has been reached.
    Same per-item semantics as the attack queue: remove on success, retry up to 3x
    with random backoff on failure."""
    if not in_active_hours:
        return
    from empire_utils import is_paused
    if is_paused():
        logger.info("[pause] em pausa — fila de transportes ignorada")
        return

    pending = _transport_queue_items()
    if not pending:
        return

    try:
        from db_manager import queue_add, queue_remove
    except Exception:
        logger.error("[transport] db_manager indisponível", exc_info=True)
        return

    dispatched = 0
    for item in pending:
        if int(time.time()) < item.get("dispatchAfter", 0):
            continue

        if dispatched > 0:
            time.sleep(random.randint(12, 30))

        ok, error = _dispatch_scheduled_transport(session, item)
        dispatched += 1
        if ok:
            queue_remove(TRANSPORT_QUEUE, [item.get("id")])
            logger.info("[transport] transporte enviado → %s", item.get("destCityName"))
        else:
            retries = item.get("retries", 0) + 1
            if retries >= 3:
                queue_remove(TRANSPORT_QUEUE, [item.get("id")])
                logger.warning("[transport] falhou %d vezes (%s) → removido da fila",
                               retries, error)
            else:
                retry_mins = random.randint(10, 25)
                queue_add(TRANSPORT_QUEUE, dict(item, retries=retries,
                          dispatchAfter=int(time.time()) + retry_mins * 60))
                logger.warning("[transport] falhou (%s) — tentativa %d/3, nova em %d min",
                               error, retries, retry_mins)


# ── Consolidation mode ────────────────────────────────────────────────────────

def get_consolidate_settings():
    try:
        with open(CONSOLIDATE_SETTINGS_PATH) as f:
            s = json.load(f)
        for k, v in _DEFAULT_CONSOLIDATE_SETTINGS.items():
            s.setdefault(k, v)
        return s
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULT_CONSOLIDATE_SETTINGS)


def _load_consolidate_state():
    try:
        with open(CONSOLIDATE_STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"lastRun": 0, "lastSent": {}}


def _save_consolidate_state(state):
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(CONSOLIDATE_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _calc_surplus(avail, buffer, reserved):
    """Per-resource surplus a source city can give away: stock − buffer − reservations."""
    return [max(0, int(avail[i]) - int(buffer[i]) - int(reserved[i])) for i in range(5)]


def process_consolidation(session, in_active_hours=True):
    """Every intervalHours, send each city's surplus to the destination city.
    Respects the queue resourceBuffer and building-queue reservations, so it never
    starves a city below the configured floor nor steals from planned upgrades."""
    if not in_active_hours:
        return
    from empire_utils import is_paused
    if is_paused():
        return
    settings = get_consolidate_settings()
    if not settings.get("enabled") or not settings.get("destCityId"):
        return

    state = _load_consolidate_state()
    interval_secs = max(1, int(settings.get("intervalHours", 6))) * 3600
    now = int(time.time())
    if now < state.get("lastRun", 0) + interval_secs:
        return

    dest = _get_own_city(settings["destCityId"])
    if not dest:
        logger.warning("[consolidate] cidade destino %s não encontrada", settings["destCityId"])
        return
    dest_name   = dest.get("name", "")
    dest_island = str(dest.get("islandId", ""))
    if not dest_island:
        logger.warning("[consolidate] destino %s sem islandId — aguarda ciclo do império", dest_name)
        return

    from ikabot.helpers.naval import getAvailableShips, getAvailableFreighters
    from ikabot.helpers.pedirInfo import getShipCapacity
    from queue_processor import (
        _dispatch_transport, _build_send_list, _get_resource_buffer,
        _load_resources_json, _load_empire_json, _calc_city_reserved, _load_queue,
    )

    resources = _load_resources_json()
    if not resources:
        return
    buffer  = _get_resource_buffer()
    queues  = _load_queue().get("queues", {})
    empire  = _load_empire_json()
    costs   = {}
    try:
        from db_manager import get_building_costs
        costs = get_building_costs()
    except Exception:
        pass

    ship_type = settings.get("shipType", "transporters")
    if ship_type not in ("transporters", "freighters", "both"):
        ship_type = "transporters"
    use_trans   = ship_type in ("transporters", "both")
    use_freight = ship_type in ("freighters", "both")

    # Live availability + capacity for whichever ship types this mode uses
    try:
        ship_cap, freighter_cap = getShipCapacity(session)
        trans_avail = int(getAvailableShips(session)) if use_trans else 0
        time.sleep(random.randint(2, 5))
        freight_avail = int(getAvailableFreighters(session)) if use_freight else 0
        if use_freight:
            time.sleep(random.randint(2, 5))
    except Exception:
        logger.warning("[consolidate] não foi possível obter navios — a saltar")
        return

    min_send = int(settings.get("minSendTotal", 1000))
    try:
        with open(OWN_CITIES_PATH) as f:
            own_cities = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return

    # Mutable counters shared across cities; each pass below decrements its own type.
    avail = {"transporters": trans_avail, "freighters": freight_avail}
    sent_summary = {}
    dispatched_any = [False]  # list so the inner helper can flip it

    def _send_pass(src, dest_id, remaining, kind, capacity, max_ships):
        """One transport dispatch from src for the given ship kind, capped to max_ships.
        Mutates `remaining` (resources still to send) and returns ships used (0 if none)."""
        if max_ships <= 0 or sum(remaining) == 0:
            return 0
        send_list, ships_to_use = _build_send_list(remaining, remaining, capacity, max_ships)
        if sum(send_list) == 0:
            return 0
        if dispatched_any[0]:
            time.sleep(random.randint(12, 30))
        ok = _dispatch_transport(session, src.get("cityId"), dest_id, dest_island,
                                 ships_to_use, send_list,
                                 use_freighters=(kind == "freighters"))
        dispatched_any[0] = True
        if not ok:
            logger.warning("[consolidate] envio de %s (%s) recusado pelo servidor",
                           src.get("name", ""), kind)
            return 0
        for i in range(5):
            remaining[i] = max(0, remaining[i] - send_list[i])
        sent = sum(send_list)
        src_name = src.get("name", "")
        sent_summary[src_name] = sent_summary.get(src_name, 0) + sent
        logger.info("[consolidate] %s → %s: %s (%d %s)",
                    src_name, dest_name,
                    {k: v for k, v in zip(_RESOURCES_ENG, send_list) if v > 0},
                    ships_to_use, "cargueiros" if kind == "freighters" else "navios")
        return ships_to_use

    for src in random.sample(own_cities, len(own_cities)):
        if str(src.get("cityId")) == str(settings["destCityId"]):
            continue
        if avail["transporters"] <= 0 and avail["freighters"] <= 0:
            break
        src_name = src.get("name", "")
        src_res  = resources.get(src_name, {})
        stock    = [int(src_res.get(k, 0)) for k in _RESOURCES_ENG]
        reserved = _calc_city_reserved(src_name, queues, empire, costs)
        surplus  = _calc_surplus(stock, buffer, reserved)
        if sum(surplus) < min_send:
            continue

        remaining = list(surplus)
        # Transporters first (faster); freighters then mop up any large leftover.
        if use_trans:
            avail["transporters"] -= _send_pass(
                src, settings["destCityId"], remaining,
                "transporters", ship_cap, avail["transporters"])
        if use_freight:
            avail["freighters"] -= _send_pass(
                src, settings["destCityId"], remaining,
                "freighters", freighter_cap, avail["freighters"])

    state["lastRun"]  = now
    state["lastSent"] = sent_summary
    _save_consolidate_state(state)
    if sent_summary:
        logger.info("[consolidate] ronda concluída → %s: %s", dest_name, sent_summary)
