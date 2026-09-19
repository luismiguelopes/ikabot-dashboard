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
import math
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
    "ignoreCityIds": [],              # source cities never drained by consolidation
}

_WINE_CRITICAL_SECS = 6 * 3600   # below this runway, wine beats the farm reserve

WINE_SETTINGS_PATH = os.path.join(LOGS_DIR, "wine_settings.json")
_DEFAULT_WINE_SETTINGS = {
    "enabled":           True,  # on by default: a wine-out costs population, so the safe
                                # default is to balance. A saved setting still overrides this.
    "thresholdHours":    12,   # act when a city's wine runway drops below this
    "targetHours":       48,   # top the city up to this many hours of consumption
    "donorReserveHours": 96,   # non-producing city lends only what exceeds this runway
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

    # Consolidation is pure housekeeping — yield trade ships to any imminent farm raid.
    # (shipType "freighters"/"both" is unaffected; the freighter pass still runs.)
    if use_trans:
        try:
            from farm_manager import apply_ship_reserve
            trans_avail = apply_ship_reserve(trans_avail, "consolidate")
        except Exception:
            pass

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

    ignored = {str(c) for c in (settings.get("ignoreCityIds") or [])}
    for src in random.sample(own_cities, len(own_cities)):
        if str(src.get("cityId")) == str(settings["destCityId"]):
            continue
        if str(src.get("cityId")) in ignored:
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


# ── Wine balancer (F9) ────────────────────────────────────────────────────────

def get_wine_settings():
    try:
        with open(WINE_SETTINGS_PATH) as f:
            s = json.load(f)
        for k, v in _DEFAULT_WINE_SETTINGS.items():
            s.setdefault(k, v)
        return s
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULT_WINE_SETTINGS)


def save_wine_settings(data):
    settings = dict(_DEFAULT_WINE_SETTINGS)
    settings["enabled"]        = bool(data.get("enabled", False))
    settings["thresholdHours"] = max(1, min(168, int(data.get("thresholdHours", 12))))
    settings["targetHours"]    = max(settings["thresholdHours"], min(336, int(data.get("targetHours", 48))))
    settings["donorReserveHours"] = max(settings["targetHours"],
                                        min(720, int(data.get("donorReserveHours", 96))))
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(WINE_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
    return settings


def process_wine_balancer(session, in_active_hours=True):
    """Pre-empt AND recover wine shortages. A city is needy when either:
      - it is still consuming and its runway (wineRunsOutIn) drops below thresholdHours, or
      - it has already emptied: production 0 and live consumption 0 (you can't consume wine
        you don't have, so the game reports 0) with stock below thresholdHours of the sister
        cities' median consumption. It is then topped up using that median as a consumption
        estimate; once primed, the next cycle sees its real consumption and the runway path
        takes over.
    Sources, in order:
      1. real wine producers (wineProductionPerHour > 0), lending above targetHours;
      2. net consumers with a comfortable surplus (runway ≥ donorReserveHours), lending what
         exceeds that many hours of their own consumption (e.g. the farm-loot city sitting on
         2000h of wine while six cities starve at <12h).
    A city with production 0 and consumption 0 is NEVER a donor — treating an emptied city as
    a "producer" would let the balancer ship away its last drops, worsening the shortage."""
    if not in_active_hours:
        return
    from empire_utils import is_paused
    if is_paused():
        return
    settings = get_wine_settings()
    if not settings.get("enabled"):
        return

    from ikabot.helpers.naval import getAvailableShips
    from ikabot.helpers.pedirInfo import getShipCapacity
    from queue_processor import _dispatch_transport, _load_resources_json

    resources = _load_resources_json()
    if not resources:
        return
    try:
        with open(OWN_CITIES_PATH) as f:
            own = {c["name"]: c for c in json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return

    threshold_h = int(settings["thresholdHours"])
    threshold   = threshold_h * 3600
    target_h    = int(settings["targetHours"])
    donor_floor = max(int(settings.get("donorReserveHours", 96)), target_h)

    # Median consumption of the cities that ARE consuming — used to size top-ups for
    # emptied cities whose live consumption reads 0 only because they have no wine left.
    active_cons = sorted(int(d.get("wineConsumptionPerHour", 0) or 0)
                         for d in resources.values()
                         if int(d.get("wineConsumptionPerHour", 0) or 0) > 0)
    median_cons = active_cons[len(active_cons) // 2] if active_cons else 0

    needy, sources = [], []
    for name, d in resources.items():
        cons     = int(d.get("wineConsumptionPerHour", 0) or 0)
        prod     = int(d.get("wineProductionPerHour", 0) or 0)
        stock    = int(d.get("Wine", 0) or 0)
        runs_out = d.get("wineRunsOutIn", -1)
        if runs_out != -1 and 0 < runs_out < threshold and cons > 0:
            # still draining, runway below threshold
            deficit = max(0, cons * target_h - stock)
            if deficit > 0:
                needy.append((name, runs_out, deficit))
        elif prod == 0 and cons == 0 and median_cons > 0 and stock < median_cons * threshold_h:
            # emptied consumer: it stopped "consuming" only because it ran dry. Prime it
            # with the sister cities' median consumption; runway ~0 => most urgent + critical.
            deficit = max(0, median_cons * target_h - stock)
            if deficit > 0:
                needy.append((name, 1, deficit))
        elif prod > 0 and runs_out == -1:
            # tier 0 — real wine producer: keep targetHours for itself, lend the rest
            reserve = cons * target_h
            spare = max(0, stock - reserve)
            if spare > 0:
                sources.append([name, spare, 0])
        elif runs_out != -1 and runs_out >= donor_floor * 3600:
            # tier 1 — net consumer with a comfortable surplus: lend down to donor_floor
            spare = max(0, stock - cons * donor_floor)
            if spare > 0:
                sources.append([name, spare, 1])

    if not needy or not sources:
        return
    # producers first, then surplus donors with the biggest spare first
    sources.sort(key=lambda src: (src[2], -src[1]))

    needy.sort(key=lambda x: x[1])  # most urgent (lowest runway) first
    try:
        ships_available = int(getAvailableShips(session))
        ship_cap, _ = getShipCapacity(session)
        time.sleep(random.randint(2, 5))
    except Exception:
        logger.warning("[wine] não foi possível obter navios — a saltar")
        return
    if ships_available <= 0 or ship_cap <= 0:
        return

    # Yield trade ships to the farm — EXCEPT when a city is critically low on wine, since
    # losing population to a wine-out is worse than a delayed raid.
    critical = any(0 < ro < _WINE_CRITICAL_SECS for _, ro, _ in needy)
    if not critical:
        try:
            from farm_manager import apply_ship_reserve
            ships_available = apply_ship_reserve(ships_available, "wine")
        except Exception:
            pass
        if ships_available <= 0:
            return

    first = True
    for dest_name, runs_out, deficit in needy:
        if ships_available <= 0:
            break
        dest = own.get(dest_name)
        dest_island = str((dest or {}).get("islandId", ""))
        if not dest or not dest_island:
            continue
        remaining = deficit
        for src in sources:
            if remaining <= 0 or ships_available <= 0:
                break
            src_name, spare = src[0], src[1]
            if spare <= 0 or src_name == dest_name:
                continue
            src_city = own.get(src_name)
            if not src_city:
                continue
            amount = min(spare, remaining)
            ships_to_use = min(math.ceil(amount / ship_cap), ships_available)
            amount = min(amount, ships_to_use * ship_cap)
            if amount <= 0:
                continue
            if not first:
                time.sleep(random.randint(12, 30))
            first = False
            ok = _dispatch_transport(session, src_city["cityId"], dest["cityId"],
                                     dest_island, ships_to_use, [0, int(amount), 0, 0, 0])
            if ok:
                ships_available -= ships_to_use
                src[1] -= amount
                remaining -= amount
                logger.info("[wine] %s → %s: %d vinho (%d navios, runway %dh)",
                            src_name, dest_name, int(amount), ships_to_use, runs_out // 3600)
            else:
                logger.warning("[wine] envio de %s → %s recusado", src_name, dest_name)


# ── Wine market buyer (F10) ───────────────────────────────────────────────────
# Buys wine from other players' market offers to keep the empire stocked. The wine
# balancer only redistributes an existing (finite) pool; with no wine producer the
# pool only shrinks, so buying is the piece that replenishes it. Roles stay split:
# this buyer refills the empire's total, the balancer spreads it to every city.
WINE_BUY_SETTINGS_PATH = os.path.join(LOGS_DIR, "wine_buy_settings.json")
WINE_BUY_STATUS_PATH   = os.path.join(LOGS_DIR, "wine_buy_status.json")
_DEFAULT_WINE_BUY_SETTINGS = {
    "enabled":          False,   # opt-in: this is the only feature that spends gold
    "dryRun":           True,    # start safe: log the plan, buy nothing
    "targetHours":      72,      # keep this many hours of wine per city (empire target)
    "maxPricePerUnit":  15,      # never buy above this gold/unit (offers are player-priced)
    "goldFloor":        100000,  # never let gold drop below this
    "maxSpendPerCycle": 200000,  # cap gold spent per run
    "ignoreCityIds":    [],
}


def get_wine_buy_settings():
    settings = dict(_DEFAULT_WINE_BUY_SETTINGS)
    try:
        with open(WINE_BUY_SETTINGS_PATH) as f:
            settings.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return settings


def save_wine_buy_settings(data):
    settings = dict(_DEFAULT_WINE_BUY_SETTINGS)
    settings["enabled"]          = bool(data.get("enabled", False))
    settings["dryRun"]           = bool(data.get("dryRun", True))
    settings["targetHours"]      = max(1, min(336, int(data.get("targetHours", 72))))
    settings["maxPricePerUnit"]  = max(1, min(10000, int(data.get("maxPricePerUnit", 15))))
    settings["goldFloor"]        = max(0, int(data.get("goldFloor", 100000)))
    settings["maxSpendPerCycle"] = max(0, int(data.get("maxSpendPerCycle", 200000)))
    settings["ignoreCityIds"]    = [str(c) for c in (data.get("ignoreCityIds") or [])]
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(WINE_BUY_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
    return settings


def _wine_buy_deficit(resources, own, settings):
    """Total wine (and per-city breakdown) the empire is short of its per-city target
    of targetHours of consumption. Emptied cities (live consumption 0) are sized from
    the sister cities' median consumption, exactly like the balancer."""
    target_h = int(settings["targetHours"])
    ignored_ids = {str(c) for c in settings.get("ignoreCityIds", [])}
    ignored_names = {name for name, c in own.items()
                     if str(c.get("cityId")) in ignored_ids}
    active = sorted(int(d.get("wineConsumptionPerHour", 0) or 0)
                    for d in resources.values()
                    if int(d.get("wineConsumptionPerHour", 0) or 0) > 0)
    median = active[len(active) // 2] if active else 0

    total, detail = 0, []
    for name, d in resources.items():
        if name in ignored_names:
            continue
        cons  = int(d.get("wineConsumptionPerHour", 0) or 0)
        prod  = int(d.get("wineProductionPerHour", 0) or 0)
        stock = int(d.get("Wine", 0) or 0)
        eff_cons = cons if cons > 0 else (median if prod == 0 else 0)
        if eff_cons <= 0:
            continue
        need = max(0, eff_cons * target_h - stock)
        if need > 0:
            total += need
            detail.append((name, need))
    detail.sort(key=lambda x: -x[1])
    return total, detail


def _write_wine_buy_status(status):
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        status["now"] = int(time.time())
        with open(WINE_BUY_STATUS_PATH, "w") as f:
            json.dump(status, f, indent=2)
    except Exception:
        logger.error("[wine-buy] falha a escrever status", exc_info=True)


def _set_market_resource(session, city, resource_index):
    """Non-interactive equivalent of buyResources.chooseResource: tells the branch
    office which resource to list offers for. resource_index: 0=wood..4=sulfur."""
    import ikabot.config as config
    search = "resource" if resource_index == 0 else resource_index
    session.post(params={
        "cityId": city["id"], "position": city["pos"], "view": "branchOffice",
        "activeTab": "bargain", "type": 444, "searchResource": search,
        "range": city["rango"], "backgroundView": "city", "currentCityId": city["id"],
        "templateView": "branchOffice", "currentTab": "bargain",
        "actionRequest": config.actionRequest, "ajax": 1,
    })


_WINE_RESOURCE_INDEX = 1  # materials_names = [Wood, Wine, Marble, Crystal, Sulfur]


def process_wine_buyer(session, in_active_hours=True, force_preview=False):
    """Top up the empire's wine from the market, within hard gold/price guards.
    Off and dry-run by default. The balancer then spreads what lands.
    force_preview: run once in dry-run even when disabled, to populate the UI preview."""
    if not in_active_hours and not force_preview:
        return
    from empire_utils import is_paused
    if is_paused():
        return
    settings = get_wine_buy_settings()
    if not settings.get("enabled") and not force_preview:
        return

    from queue_processor import _load_resources_json
    resources = _load_resources_json()
    if not resources:
        return
    try:
        with open(OWN_CITIES_PATH) as f:
            own = {c["name"]: c for c in json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return

    deficit, detail = _wine_buy_deficit(resources, own, settings)
    dry = True if force_preview else bool(settings.get("dryRun", True))
    if deficit <= 0:
        _write_wine_buy_status({"dryRun": dry, "deficit": 0, "bought": 0, "spent": 0,
                                "note": "sem défice — nada a comprar", "buys": []})
        return

    from ikabot.helpers.market import getCommercialCities, getGold
    from ikabot.function.buyResources import getOffers, buy
    from ikabot.helpers.pedirInfo import getShipCapacity
    from ikabot.helpers.naval import getAvailableShips

    commercial = getCommercialCities(session)
    time.sleep(random.randint(2, 5))
    if not commercial:
        logger.info("[wine-buy] nenhuma cidade com entreposto — a saltar")
        _write_wine_buy_status({"dryRun": dry, "deficit": deficit, "bought": 0, "spent": 0,
                                "note": "sem entreposto comercial", "buys": []})
        return

    gold, _gp = getGold(session, commercial[0])
    gold_floor = int(settings["goldFloor"])
    budget = min(gold - gold_floor, int(settings["maxSpendPerCycle"]))
    if budget <= 0:
        logger.info("[wine-buy] ouro (%d) no/abaixo do piso (%d) — a saltar", gold, gold_floor)
        _write_wine_buy_status({"dryRun": dry, "deficit": deficit, "bought": 0, "spent": 0,
                                "gold": gold, "note": "ouro no piso", "buys": []})
        return

    try:
        ship_cap, _ = getShipCapacity(session)
        ships = int(getAvailableShips(session))
        time.sleep(random.randint(2, 5))
    except Exception:
        logger.warning("[wine-buy] não foi possível obter navios — a saltar")
        return
    if ship_cap <= 0:
        return
    # Yield trade ships to the farm — the buyer is a background top-up, never urgent.
    try:
        from farm_manager import apply_ship_reserve
        ships = apply_ship_reserve(ships, "wine-buy")
    except Exception:
        pass
    if not dry and ships <= 0:
        logger.info("[wine-buy] sem navios livres (reservados p/ farm) — a saltar")
        _write_wine_buy_status({"dryRun": dry, "deficit": deficit, "bought": 0, "spent": 0,
                                "gold": gold, "note": "sem navios livres", "buys": []})
        return

    max_price = int(settings["maxPricePerUnit"])
    remaining = deficit
    spent = bought = 0
    cheapest = None
    buys = []
    first = True
    for city in commercial:
        if remaining <= 0 or budget <= 0 or (not dry and ships <= 0):
            break
        try:
            _set_market_resource(session, city, _WINE_RESOURCE_INDEX)
            time.sleep(random.randint(2, 5))
            offers = [o for o in getOffers(session, city)
                      if o.get("tipo") == "wine" and o["amountAvailable"] > 0
                      and o["precio"] <= max_price]
        except Exception:
            logger.error("[wine-buy] falha a obter ofertas em %s", city.get("name"), exc_info=True)
            continue
        offers.sort(key=lambda o: o["precio"])
        for offer in offers:
            if remaining <= 0 or budget <= 0 or (not dry and ships <= 0):
                break
            price = offer["precio"]
            cheapest = price if cheapest is None else min(cheapest, price)
            by_gold  = budget // price
            by_ships = (ships * ship_cap) if not dry else remaining
            amt = int(min(offer["amountAvailable"], remaining, by_gold, by_ships))
            if amt <= 0:
                continue
            ships_to_use = int(math.ceil(amt / ship_cap))
            cost = amt * price
            # offer["ciudadDestino"]/["jugadorAComprar"] are the SELLER's city and player
            # (ikabot's naming is misleading); the wine is delivered to our own commercial
            # city (city["name"]), then the balancer spreads it.
            rec = {"seller": offer["jugadorAComprar"], "fromCity": offer["ciudadDestino"],
                   "toCity": city["name"], "amount": amt, "price": price, "cost": cost}
            if dry:
                logger.info("[wine-buy][dry] compraria %d vinho @%d a %s (%s) → %s (%d ouro)",
                            amt, price, offer["jugadorAComprar"], offer["ciudadDestino"], city["name"], cost)
            else:
                if not first:
                    time.sleep(random.randint(8, 20))
                first = False
                try:
                    buy(session, city, offer, amt, ships, ship_cap)
                except Exception:
                    logger.error("[wine-buy] compra recusada/erro", exc_info=True)
                    continue
                ships -= ships_to_use
                logger.info("[wine-buy] comprei %d vinho @%d a %s (%s) → %s (%d ouro)",
                            amt, price, offer["jugadorAComprar"], offer["ciudadDestino"], city["name"], cost)
            buys.append(rec)
            budget    -= cost
            spent     += cost
            bought    += amt
            remaining -= amt

    avg = round(spent / bought, 1) if bought else 0
    note = "plano (dry-run)" if dry else "compra executada"
    if bought == 0:
        note = "sem ofertas dentro do tecto de preço" if cheapest is None else "nada comprado"
    _write_wine_buy_status({"dryRun": dry, "deficit": deficit, "bought": bought,
                            "spent": spent, "avgPrice": avg, "cheapest": cheapest,
                            "gold": gold, "goldFloor": gold_floor, "note": note,
                            "buys": buys[:20], "topCities": detail[:8]})
    logger.info("[wine-buy] %s: %d vinho por %d ouro (défice %d, preço médio %s)",
                "dry-run" if dry else "comprado", bought, spent, deficit, avg)
