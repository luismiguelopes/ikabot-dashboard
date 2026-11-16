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
import settings_registry
from empire_utils import atomic_write_json

TRANSPORT_QUEUE            = "transport"
OWN_CITIES_PATH            = os.path.join(LOGS_DIR, "own_cities.json")
CONSOLIDATE_SETTINGS_PATH  = os.path.join(LOGS_DIR, "consolidate_settings.json")
CONSOLIDATE_STATE_PATH     = os.path.join(LOGS_DIR, "consolidate_state.json")

# resources.json uses english display keys, in the canonical 5-resource order
_RESOURCES_ENG = ["Wood", "Wine", "Marble", "Crystal", "Sulfur"]

# Declared once in settings_registry (shared with the dashboard) — P13.30.
_DEFAULT_CONSOLIDATE_SETTINGS = settings_registry.defaults("consolidate")

_WINE_CRITICAL_SECS = 6 * 3600   # below this runway, wine beats the farm reserve

WINE_SETTINGS_PATH = os.path.join(LOGS_DIR, "wine_settings.json")
# P11.10: the wine settings include a floor of trade ships held back from the farm. The farm
# recycles transporters non-stop (same-island raids re-arm them the moment they dock), so
# without it an urgent wine transport can hit "no free ships" repeatedly (DeathCrow
# 2026-11-04: ~2h runway, 3 failed wine transports).
_DEFAULT_WINE_SETTINGS = settings_registry.defaults("wine")


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
    if ok:
        try:
            from telegram_notifier import notify_transport_sent, _pt_int
            summary = ", ".join(f"{_pt_int(v)} {k}" for k, v in zip(_RESOURCES_ENG, send_list) if v > 0)
            notify_transport_sent(item.get("originCityName", origin_id),
                                  item.get("destCityName", dest_id),
                                  f"{summary} ({ships} {'cargueiros' if use_freighters else 'navios'})")
        except Exception:
            pass
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
                record_transport_failure(item, error, retries)
                logger.warning("[transport] falhou %d vezes (%s) → removido da fila",
                               retries, error)
                try:
                    from telegram_notifier import notify_queue_item_dropped
                    notify_queue_item_dropped("transport", "%s → %s" % (item.get("originCityName", "?"), item.get("destCityName", "?")), "falhou %d vezes: %s" % (retries, error))
                except Exception:
                    pass
            else:
                retry_mins = random.randint(10, 25)
                queue_add(TRANSPORT_QUEUE, dict(item, retries=retries, lastError=str(error or "")[:200],
                          dispatchAfter=int(time.time()) + retry_mins * 60))
                logger.warning("[transport] falhou (%s) — tentativa %d/3, nova em %d min",
                               error, retries, retry_mins)


TRANSPORT_FAILURES_PATH = os.path.join(LOGS_DIR, "transport_failures.json")
_FAILURES_KEEP = 20


def record_transport_failure(item, error, retries, now=None):
    """Keep the last transports the bot gave up on (P13.58): a dropped item left the queue
    and only the log said why, so the dashboard's Alerts page could not show it. Local file
    only — nothing here talks to the game."""
    entry = {"ts": int(now or time.time()),
             "origin": item.get("originCityName") or "", "dest": item.get("destCityName") or "",
             "retries": retries, "error": str(error or "")[:200]}
    try:
        with open(TRANSPORT_FAILURES_PATH) as f:
            items = json.load(f).get("failures", [])
        if not isinstance(items, list):
            items = []
    except Exception:
        items = []
    items = (items + [entry])[-_FAILURES_KEEP:]
    try:
        atomic_write_json(TRANSPORT_FAILURES_PATH, {"failures": items}, indent=2)
    except Exception as e:
        logger.warning("[transport] não foi possível registar a falha: %s", e)


# ── Consolidation mode ────────────────────────────────────────────────────────

def get_consolidate_settings():
    return settings_registry.load("consolidate", CONSOLIDATE_SETTINGS_PATH)


def _load_consolidate_state():
    try:
        with open(CONSOLIDATE_STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"lastRun": 0, "lastSent": {}}


def _save_consolidate_state(state):
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        atomic_write_json(CONSOLIDATE_STATE_PATH, state, indent=2)
    except Exception:
        pass


def _calc_surplus(avail, buffer, reserved):
    """Per-resource surplus a source city can give away: stock − buffer − reservations."""
    return [max(0, int(avail[i]) - int(buffer[i]) - int(reserved[i])) for i in range(5)]


def _fair_ship_split(needs, avail):
    """Spread a shared fleet of `avail` ships across cities that each want `needs[i]`.

    Without this, the first rich city in a round grabbed as many ships as it wanted
    (up to the whole fleet) and starved the rest until the next interval — so the
    empire drained one city at a time. The fleet is the bottleneck (all own cities
    are same-island, equal travel time), so spreading it costs no throughput and
    lets every city start draining in the same round.

    Water-filling: each active city gets an even slice per round; a city needing less
    than its slice is served in full and its leftover ships flow to the others; any
    final odd ships go out one at a time. Never grants more than a city needs, and the
    grants sum to at most `avail`.
    """
    n = len(needs)
    grant = [0] * n
    remaining = max(0, int(avail))
    active = [i for i in range(n) if needs[i] > 0]
    while remaining > 0 and active:
        share = max(1, remaining // len(active))
        for i in list(active):
            give = min(share, needs[i] - grant[i], remaining)
            if give <= 0:
                active.remove(i)
                continue
            grant[i] += give
            remaining -= give
            if grant[i] >= needs[i]:
                active.remove(i)
            if remaining <= 0:
                break
    return grant


def _spread_resource(caps, total):
    """Distribute `total` units of one resource across cities, each capped by caps[i].

    Amounts jitter around an even split (±~40%) so the transports don't all carry an
    identical load, which is an obvious bot tell. The sum is still exactly
    min(total, sum(caps)) — it fills the destination's free space without overflowing —
    and no city is asked for more than its surplus. With random.uniform pinned to 1.0
    (tests) it collapses to an even split.
    """
    n = len(caps)
    caps = [max(0, int(c)) for c in caps]
    total = min(max(0, int(total)), sum(caps))
    if total <= 0 or n == 0:
        return [0] * n
    weights = [random.uniform(0.6, 1.4) if caps[i] > 0 else 0.0 for i in range(n)]
    sw = sum(weights) or 1.0
    alloc = [min(caps[i], int(total * weights[i] / sw)) for i in range(n)]
    # Hand the rounding/cap leftover to cities that still have room, in even chunks.
    rem = total - sum(alloc)
    guard = 0
    while rem > 0 and guard < 10000:
        guard += 1
        room = [i for i in range(n) if alloc[i] < caps[i]]
        if not room:
            break
        step = max(1, rem // len(room))
        for i in room:
            if rem <= 0:
                break
            add = min(step, caps[i] - alloc[i], rem)
            alloc[i] += add
            rem -= add
    return alloc


_CONSOLIDATE_RETRY_SECS = 30 * 60   # retry when a round had surplus but could send nothing


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

    # Destination warehouse headroom — never overflow the destination (cap guard).
    # When the destination's capacity/stock is known (resources.json), cap each resource to
    # the free space and decrement it as we allocate across source cities; unknown capacity
    # → no cap (keeps behaviour unchanged when the data isn't available).
    respect_cap = bool(settings.get("respectDestCap", True))
    dest_res = resources.get(dest_name, {}) if respect_cap else {}
    dest_cap = int(dest_res.get("storageCapacity", 0) or 0)
    if respect_cap and dest_cap > 0:
        headroom = [max(0, dest_cap - int(dest_res.get(k, 0) or 0)) for k in _RESOURCES_ENG]
    else:
        headroom = None
    skip_idx = {i for i, k in enumerate(_RESOURCES_ENG)
                if k in set(settings.get("skipResources") or [])}

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

    # ── Pre-pass: candidate sources and their raw surplus, fullest first ──────
    # (All own cities share an island, so source distance is uniform; fullest-first
    # decides who contributes when the destination can't take everyone.)
    candidates = []  # list of [src, surplus]
    for src in sorted(
            own_cities,
            key=lambda c: sum(int(resources.get(c.get("name", ""), {}).get(k, 0))
                              for k in _RESOURCES_ENG),
            reverse=True):
        if str(src.get("cityId")) == str(settings["destCityId"]):
            continue
        if str(src.get("cityId")) in ignored:
            continue
        src_name = src.get("name", "")
        src_res  = resources.get(src_name, {})
        stock    = [int(src_res.get(k, 0)) for k in _RESOURCES_ENG]
        reserved = _calc_city_reserved(src_name, queues, empire, costs)
        surplus  = _calc_surplus(stock, buffer, reserved)
        for i in skip_idx:
            surplus[i] = 0
        if sum(surplus) <= 0:
            continue
        candidates.append([src, surplus])

    # ── Spread the destination's free space across source cities ──────────────
    # Transports load their cargo at the origin before sailing (Ikariam charges a
    # loading time), so many cities loading a small share in parallel beats one city
    # loading the whole lot in series. When the destination is near-full, split its
    # limited free space across as many cities as can each still carry min_send, and
    # hand each one an even share per resource (same water-fill used for ships). An
    # unknown/uncapped destination keeps the simple path: each city offers its full
    # surplus and the ship split alone spreads the fleet.
    if headroom is not None:
        # How much can actually move this round = per resource, the smaller of the
        # destination's free space and what the cities together have to give. (Empty
        # headroom in a resource nobody has surplus of must not inflate the count.)
        movable = sum(min(headroom[r], sum(s[r] for _, s in candidates))
                      for r in range(5))
        max_cities = max(1, movable // max(1, min_send))
        chosen = candidates[:max_cities]
        for r in range(5):
            share = _spread_resource([s[r] for _, s in chosen], headroom[r])
            for j, (_, s) in enumerate(chosen):
                s[r] = share[j]
        eligible = [[src, s] for src, s in chosen if sum(s) > 0]
    else:
        eligible = [cs for cs in candidates if sum(cs[1]) >= min_send]

    # ── Fair allocation of each ship pool across the eligible cities ──────────
    # Ships a city needs to move its current (remaining) surplus in one go.
    def _needs(capacity):
        return [-(-sum(surplus) // capacity) if sum(surplus) > 0 else 0
                for _, surplus in eligible]

    dest_id = settings["destCityId"]
    # Transporters first (faster); freighters then mop up any large leftover.
    if use_trans:
        alloc = _fair_ship_split(_needs(ship_cap), avail["transporters"])
        for (src, remaining), cap_ships in zip(eligible, alloc):
            if avail["transporters"] <= 0:
                break
            avail["transporters"] -= _send_pass(
                src, dest_id, remaining, "transporters", ship_cap,
                min(cap_ships, avail["transporters"]))
    if use_freight:
        alloc = _fair_ship_split(_needs(freighter_cap), avail["freighters"])
        for (src, remaining), cap_ships in zip(eligible, alloc):
            if avail["freighters"] <= 0:
                break
            avail["freighters"] -= _send_pass(
                src, dest_id, remaining, "freighters", freighter_cap,
                min(cap_ships, avail["freighters"]))

    state["lastRun"]  = now
    if eligible and not sent_summary:
        # There WAS surplus to move but nothing left (no free ships, every dispatch refused).
        # Marking the round as done made it wait the whole interval (6h) again; look again
        # in half an hour instead.
        state["lastRun"] = now - interval_secs + min(interval_secs, _CONSOLIDATE_RETRY_SECS)
        logger.info("[consolidate] havia excedente mas nada saiu (sem navios?) — nova "
                    "tentativa em %d min", min(interval_secs, _CONSOLIDATE_RETRY_SECS) // 60)
    state["lastSent"] = sent_summary
    _save_consolidate_state(state)
    if sent_summary:
        logger.info("[consolidate] ronda concluída → %s: %s", dest_name, sent_summary)
        try:
            from telegram_notifier import notify_consolidation_done
            notify_consolidation_done(dest_name, str(sent_summary))
        except Exception:
            pass


# ── Wine balancer (F9) ────────────────────────────────────────────────────────

def get_wine_settings():
    return settings_registry.load("wine", WINE_SETTINGS_PATH)


def save_wine_settings(data):
    return settings_registry.update("wine", data, WINE_SETTINGS_PATH)


def wine_ship_reserve():
    """P11.10: trade ships the farm must always leave free for wine/urgent logistics.

    Mirror of the farm's apply_ship_reserve, but in wine's favour, and a PERMANENT floor rather
    than gated on runway: keep `reserveShips` trade ships out of the farm's reach at all times so
    an urgent wine transport / the balancer (F9) can always find ships, instead of the farm —
    which recycles transporters non-stop — starving them (DeathCrow 2026-11-04). The farm still
    uses everything above the floor; freighters are a separate pool and unaffected. Cheap to call
    on the farm's dispatch path (no HTTP). Returns 0 only when the reserve is switched off."""
    settings = get_wine_settings()
    if not settings.get("reserveShipsFromFarm", True):
        return 0
    return max(0, int(settings.get("reserveShips", 5)))


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
        if runs_out != -1 and 0 <= runs_out < threshold and cons > 0:
            # still draining, runway below threshold. 0 counts: a city that is already dry
            # while the game still reports its tavern consumption fell between this branch
            # (0 < runs_out) and the "emptied consumer" one (consumption 0) and got no wine.
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
    shipments = []
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
                shipments.append((src_name, dest_name, int(amount), ships_to_use))
            else:
                logger.warning("[wine] envio de %s → %s recusado", src_name, dest_name)
    if shipments:
        try:
            from telegram_notifier import notify_wine_balanced
            notify_wine_balanced(shipments)
        except Exception:
            pass


# ── Wine market buyer (F10) ───────────────────────────────────────────────────
# Buys wine from other players' market offers to keep the empire stocked. The wine
# balancer only redistributes an existing (finite) pool; with no wine producer the
# pool only shrinks, so buying is the piece that replenishes it. Roles stay split:
# this buyer refills the empire's total, the balancer spreads it to every city.
WINE_BUY_SETTINGS_PATH = os.path.join(LOGS_DIR, "wine_buy_settings.json")
WINE_BUY_STATUS_PATH   = os.path.join(LOGS_DIR, "wine_buy_status.json")
_DEFAULT_WINE_BUY_SETTINGS = settings_registry.defaults("wine_buy")


def get_wine_buy_settings():
    return settings_registry.load("wine_buy", WINE_BUY_SETTINGS_PATH)


def save_wine_buy_settings(data):
    return settings_registry.update("wine_buy", data, WINE_BUY_SETTINGS_PATH)


def _wine_buy_deficit(resources, own, settings):
    """Total wine (and per-city breakdown) the empire is short of its per-city target
    of targetHours of consumption. Emptied cities (live consumption 0) are sized from
    the sister cities' median consumption, exactly like the balancer."""
    target_h = int(settings["targetHours"])
    # Deadband low-water mark: a city is only bought for once it drops below refill_below
    # hours of consumption, then filled to target_h — so we buy big batches occasionally
    # instead of topping every city up to target every single cycle.
    refill_below = int(settings.get("refillBelowHours", target_h))
    refill_below = max(1, min(target_h, refill_below))
    crit_h = max(1, min(refill_below, int(settings.get("criticalHours", 6))))
    ignored_ids = {str(c) for c in settings.get("ignoreCityIds", [])}
    ignored_names = {name for name, c in own.items()
                     if str(c.get("cityId")) in ignored_ids}
    active = sorted(int(d.get("wineConsumptionPerHour", 0) or 0)
                    for d in resources.values()
                    if int(d.get("wineConsumptionPerHour", 0) or 0) > 0)
    median = active[len(active) // 2] if active else 0

    total, detail, critical = 0, [], False
    for name, d in resources.items():
        if name in ignored_names:
            continue
        cons  = int(d.get("wineConsumptionPerHour", 0) or 0)
        prod  = int(d.get("wineProductionPerHour", 0) or 0)
        stock = int(d.get("Wine", 0) or 0)
        eff_cons = cons if cons > 0 else (median if prod == 0 else 0)
        if eff_cons <= 0:
            continue
        if stock >= eff_cons * refill_below:
            continue  # still inside the deadband — leave it alone
        if stock < eff_cons * crit_h:
            critical = True  # wine emergency -> allowed to bypass the farm ship reserve
        need = max(0, eff_cons * target_h - stock)
        if need > 0:
            total += need
            detail.append((name, need))
    detail.sort(key=lambda x: -x[1])
    return total, detail, critical


def _write_wine_buy_status(status):
    """Write the status of this pass. A preview or an empty pass replaces the visible
    status, but the last purchase that really happened is kept in `lastPurchase` — it is
    only replaced by a newer live run that bought something (P13.48)."""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        status["now"] = int(time.time())
        if not status.get("dryRun") and status.get("bought", 0) > 0:
            status["lastPurchase"] = {
                "at": status["now"], "bought": status["bought"], "spent": status.get("spent", 0),
                "avgPrice": status.get("avgPrice", 0), "buys": status.get("buys", [])[:20],
            }
        else:
            try:
                with open(WINE_BUY_STATUS_PATH) as f:
                    prev = json.load(f).get("lastPurchase")
                if isinstance(prev, dict):
                    status["lastPurchase"] = prev
            except (FileNotFoundError, json.JSONDecodeError, AttributeError):
                pass
        atomic_write_json(WINE_BUY_STATUS_PATH, status, indent=2)
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


class _RecordingSession:
    """Pass-through session that keeps the last POST response. The stock buy() throws the
    game's answer away, so this is the only way to see whether a purchase went through."""

    def __init__(self, session):
        self._session = session
        self.last_post = None

    def post(self, *args, **kwargs):
        self.last_post = self._session.post(*args, **kwargs)
        return self.last_post

    def __getattr__(self, name):
        return getattr(self._session, name)


def _post_feedback(resp):
    """(type, text) of the provideFeedback entry in a game AJAX response, or (None, "")."""
    try:
        for entry in json.loads(resp, strict=False):
            if isinstance(entry, list) and entry and entry[0] == "provideFeedback":
                fbs = entry[1] if isinstance(entry[1], list) else [entry[1]]
                for fb in fbs:
                    if isinstance(fb, dict):
                        return int(fb.get("type", 0) or 0), str(fb.get("text", ""))
    except Exception:
        pass
    return None, ""


def _purchase_went_through(recorder, get_gold, gold_before, cost):
    """Did the purchase just attempted actually happen? (ok, why, gold_now)
    The game's feedback decides when there is one (10 = done, 11 = refused, with its text).
    With no readable feedback, look at the gold: a real purchase takes `cost` out at once."""
    ftype, text = _post_feedback(recorder.last_post)
    if ftype == 10:
        return True, text, gold_before - cost
    if ftype == 11:
        return False, text or "recusada pelo jogo", gold_before
    try:
        time.sleep(random.randint(2, 5))
        gold_now = get_gold()
    except Exception:
        return False, "sem confirmação do jogo (resposta ilegível e ouro por ler)", gold_before
    if gold_before - gold_now >= cost * 0.9:
        return True, "confirmada pelo ouro", gold_now
    return False, "o ouro não baixou — a oferta deve ter desaparecido", gold_now


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

    deficit, detail, critical = _wine_buy_deficit(resources, own, settings)
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
        _notify_buy_blocked("ouro no piso", f"{gold} ouro, piso {gold_floor}")
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
    # Yield trade ships to the farm — the buyer is a background top-up. EXCEPT when a
    # city is in a wine emergency (below criticalHours): then it may use the reserved
    # ships too, since a wine-out costs population (same stance as the balancer).
    if critical:
        logger.info("[wine-buy] ruptura crítica de vinho — a usar também os navios reservados ao farm")
    else:
        try:
            from farm_manager import apply_ship_reserve
            ships = apply_ship_reserve(ships, "wine-buy")
        except Exception:
            pass
    if not dry and ships <= 0:
        logger.info("[wine-buy] sem navios livres (reservados p/ farm) — a saltar")
        _notify_buy_blocked("sem navios livres", "reservados para o farm")
        _write_wine_buy_status({"dryRun": dry, "deficit": deficit, "bought": 0, "spent": 0,
                                "gold": gold, "note": "sem navios livres", "buys": []})
        return

    max_price = int(settings["maxPricePerUnit"])
    remaining = deficit
    spent = bought = failed = 0
    gold_now = gold
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
                recorder = _RecordingSession(session)
                try:
                    buy(recorder, city, offer, amt, ships, ship_cap)
                except Exception:
                    logger.error("[wine-buy] compra recusada/erro", exc_info=True)
                    continue
                # buy() returns nothing: "bought", the status and the alert used to count the
                # purchase even when the offer had gone. Only count what the game confirms.
                ok, why, gold_now = _purchase_went_through(
                    recorder, lambda: getGold(session, city)[0], gold_now, cost)
                if not ok:
                    failed += 1
                    logger.warning("[wine-buy] compra NÃO confirmada: %d vinho @%d a %s (%s) — %s",
                                   amt, price, offer["jugadorAComprar"], offer["ciudadDestino"], why)
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
    if failed:
        note += " (%d compra(s) não confirmada(s) pelo jogo)" % failed
    _write_wine_buy_status({"dryRun": dry, "deficit": deficit, "bought": bought,
                            "spent": spent, "avgPrice": avg, "cheapest": cheapest,
                            "gold": gold, "goldFloor": gold_floor, "note": note,
                            "critical": critical, "buys": buys[:20], "topCities": detail[:8],
                            "failedBuys": failed})
    logger.info("[wine-buy] %s: %d vinho por %d ouro (défice %d, preço médio %s)",
                "dry-run" if dry else "comprado", bought, spent, deficit, avg)
    try:
        import telegram_notifier as _tg
        _tg.clear_wine_buy_blocked()       # got past both brakes → re-arm their alerts
        if bought > 0:
            _tg.notify_wine_bought(bought, spent, avg, buys, dry)
    except Exception:
        pass


def _notify_buy_blocked(reason, detail):
    try:
        from telegram_notifier import notify_wine_buy_blocked
        notify_wine_buy_blocked(reason, detail)
    except Exception:
        pass
