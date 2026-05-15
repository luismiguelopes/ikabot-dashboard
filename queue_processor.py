#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import os
import random
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from empire_utils import (
    LOGS_DIR, QUEUE_JSON_PATH, QUEUE_SETTINGS_PATH, UPDATE_INTERVAL,
    ACTIVE_HOURS_START, ACTIVE_HOURS_END, FORCE_EMPIRE_FLAG, FORCE_QUEUE_FLAG, FORCE_MOVEMENTS_FLAG, lm,
)

from ikabot.helpers.getJson import getCity
from ikabot.config import actionRequest


_RESOURCES_ENG = ['Wood', 'Wine', 'Marble', 'Crystal', 'Sulfur']


# ── Queue persistence ─────────────────────────────────────────────────────────

def _load_queue():
    try:
        from db_manager import load_queue
        return load_queue()
    except Exception:
        return {"queues": {}, "inProgress": {}, "transportErrors": {}, "enabled": True}


def _save_queue(data):
    from db_manager import save_queue
    save_queue(data)


def has_building_queue(data=None):
    if data is None:
        data = _load_queue()
    if not data.get("enabled", True):
        return False
    return any(len(items) > 0 for items in data.get("queues", {}).values())


# ── Sleep scheduling ──────────────────────────────────────────────────────────

def _get_next_construction_eta(data=None):
    """Return the earliest construction completion timestamp across all in-progress cities, or None."""
    if data is None:
        data = _load_queue()
    etas = [
        entry["eta"]
        for entry in data.get("inProgress", {}).values()
        if entry.get("eta", 0) > time.time()
    ]
    return min(etas) if etas else None


def _get_next_transport_eta(data=None):
    """Return earliest arrival timestamp for own transports heading to cities with pending queue items, or None."""
    if data is None:
        data = _load_queue()
    pending_cities = {name for name, items in data.get("queues", {}).items() if items}
    if not pending_cities:
        return None
    path = os.path.join(LOGS_DIR, "movements.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            movements = json.load(f)
    except Exception:
        return None
    now = time.time()
    etas = []
    for m in movements:
        if not m.get("isOwn") or m.get("direction") != "->":
            continue
        dest = m.get("destination", "")
        for city_name in pending_cities:
            if dest.startswith(city_name + " ("):
                arrival = m.get("arrivalTime", 0)
                if arrival > now:
                    etas.append(arrival)
                break
    return min(etas) if etas else None


def _load_queue_settings():
    """Load active hours and resource buffer from queue_settings.json.
    Falls back to building_queue.json for backwards compatibility."""
    if os.path.exists(QUEUE_SETTINGS_PATH):
        try:
            with open(QUEUE_SETTINGS_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    data = _load_queue()
    return {k: data[k] for k in ("activeHours", "resourceBuffer") if k in data}


def _get_active_hours():
    """Return (start, end) from queue_settings.json, falling back to env var."""
    settings = _load_queue_settings()
    ah = settings.get("activeHours")
    if ah and isinstance(ah, dict):
        try:
            s, e = int(ah.get("start", ACTIVE_HOURS_START)), int(ah.get("end", ACTIVE_HOURS_END))
            if 0 <= s < e <= 24:
                return s, e
        except (ValueError, TypeError):
            pass
    return ACTIVE_HOURS_START, ACTIVE_HOURS_END


def _get_resource_buffer():
    """Return [wood,wine,marble,glass,sulfur] minimum reserves from queue_settings.json."""
    settings = _load_queue_settings()
    buf = settings.get("resourceBuffer")
    if isinstance(buf, list) and len(buf) == 5:
        try:
            return [max(0, int(b)) for b in buf]
        except (ValueError, TypeError):
            pass
    return [0, 0, 0, 0, 0]




def _in_active_hours():
    """Return True if current local hour is within the active hours window."""
    start, end = _get_active_hours()
    if start == 0 and end == 24:
        return True
    return start <= time.localtime().tm_hour < end


def _secs_until_active():
    """Seconds until the active hours window opens. Returns 0 if already active."""
    if _in_active_hours():
        return 0
    start, _ = _get_active_hours()
    t = time.localtime()
    h, m, s = t.tm_hour, t.tm_min, t.tm_sec
    if h < start:
        return (start - h) * 3600 - m * 60 - s
    return (24 - h + start) * 3600 - m * 60 - s


def smart_sleep(last_full_cycle_time, next_full_jitter):
    """Sleep until the next full empire cycle, next construction ETA, or next transport arrival, whichever is soonest."""
    next_full_at = last_full_cycle_time + UPDATE_INTERVAL + next_full_jitter
    q = _load_queue()  # single load — reused by all helpers below
    construction_eta = _get_next_construction_eta(q)
    transport_eta = _get_next_transport_eta(q)

    eta = None
    if construction_eta:
        eta = construction_eta
    if transport_eta:
        eta = min(eta, transport_eta) if eta else transport_eta

    if eta and _in_active_hours():
        wake_for_queue = eta + random.randint(3, 8) * 60
        sleep_secs = max(60, min(next_full_at, wake_for_queue) - time.time())
        if wake_for_queue < next_full_at:
            eta_str = time.strftime('%H:%M:%S', time.localtime(eta))
            print(lm("queue_sleep_until", eta=eta_str, mins=round(sleep_secs / 60)))
    else:
        sleep_secs = max(60, next_full_at - time.time())
        # Se há itens em queue mas sem ETA conhecido, acorda em 30 min para re-tentar
        if has_building_queue(q) and _in_active_hours():
            sleep_secs = min(sleep_secs, 1800)

    if not _in_active_hours():
        secs_to_open = _secs_until_active()
        if 0 < secs_to_open < sleep_secs:
            sleep_secs = secs_to_open + random.randint(1, 5) * 60
            print(lm("queue_sleep_until_hours", mins=round(sleep_secs / 60),
                      start=_get_active_hours()[0]))

    print(lm("cycle_sleep", mins=round(sleep_secs / 60)))
    wake_at = int(time.time() + sleep_secs)
    try:
        with open(os.path.join(LOGS_DIR, "next_cycle.json"), "w") as f:
            json.dump({"nextCycleAt": wake_at}, f)
    except Exception:
        pass
    end_time = time.time() + sleep_secs
    while time.time() < end_time:
        if os.path.exists(FORCE_EMPIRE_FLAG):
            break
        if os.path.exists(FORCE_QUEUE_FLAG):
            try:
                os.remove(FORCE_QUEUE_FLAG)
            except Exception:
                pass
            break
        if os.path.exists(FORCE_MOVEMENTS_FLAG):
            break
        time.sleep(min(60, end_time - time.time()))


# ── Cost helpers ──────────────────────────────────────────────────────────────

def _get_upgrade_cost_from_cache(city_name, building_name, current_level):
    """Return [wood,wine,marble,glass,sulfur] for the next level."""
    try:
        from db_manager import get_city_building_cost
        entry = get_city_building_cost(city_name, building_name, current_level + 1)
        if entry:
            return [entry.get(k, 0) for k in ("wood", "wine", "marble", "glass", "sulfur")]
    except Exception:
        pass
    return None


def _get_in_transit_to(city_name):
    """Return [wood,wine,marble,glass,sulfur] of own fleets already heading to city_name."""
    path = os.path.join(LOGS_DIR, "movements.json")
    if not os.path.exists(path):
        return [0, 0, 0, 0, 0]
    try:
        with open(path) as f:
            movements = json.load(f)
    except Exception:
        return [0, 0, 0, 0, 0]
    totals = [0, 0, 0, 0, 0]
    for m in movements:
        if not m.get("isOwn") or m.get("direction") != "->":
            continue
        if not m.get("destination", "").startswith(city_name + " ("):
            continue
        for r in m.get("resources", []):
            res_name = r.get("resource", "")
            if res_name not in _RESOURCES_ENG:
                continue
            try:
                amount = int(str(r.get("amount", "0")).replace(",", "").replace(".", ""))
            except ValueError:
                continue
            totals[_RESOURCES_ENG.index(res_name)] += amount
    return totals


def _load_resources_json():
    path = os.path.join(LOGS_DIR, "resources.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _load_empire_json():
    path = os.path.join(LOGS_DIR, "empire.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _get_total_upgrade_cost(costs_cache, city_name, building_name, from_level, to_level):
    """Sum building_costs.json entries for all levels from_level+1 through to_level."""
    bdata = costs_cache.get("cities", {}).get(city_name, {}).get(building_name)
    if not bdata:
        return None
    total = [0, 0, 0, 0, 0]
    found = False
    for lv in range(from_level + 1, to_level + 1):
        entry = bdata.get("costs", {}).get(str(lv))
        if entry:
            found = True
            for j, k in enumerate(("wood", "wine", "marble", "glass", "sulfur")):
                total[j] += entry.get(k, 0)
    return total if found else None


def _calc_city_reserved(city_name, queues, empire, costs_cache):
    """Return [wood,wine,marble,glass,sulfur] reserved for ALL pending queue items of city_name."""
    reserved = [0, 0, 0, 0, 0]
    for item in queues.get(city_name, []):
        bname = item["building"]
        target_lv = item.get("targetLevel", 0)
        val = str(empire.get(city_name, {}).get(bname, "0")).replace("+", "")
        cur_lv = int(val) if val.isdigit() else 0
        if target_lv <= cur_lv:
            continue
        cost = _get_total_upgrade_cost(costs_cache, city_name, bname, cur_lv, target_lv)
        if cost:
            for i in range(5):
                reserved[i] += cost[i]
    return reserved


# ── Transport dispatch ────────────────────────────────────────────────────────

_FREIGHTER_THRESHOLD_WAVES = 8  # use freighters only when total need exceeds this many transporter ship-loads


def _dispatch_transport(session, origin_city_id, dest_city_id, island_id, ships, send_list, use_freighters=False):
    """Fire one transport dispatch. Returns True on server success (type=10), False otherwise."""
    html = session.get()
    current_city = getCity(html)
    curr_id = current_city["id"]

    session.post(params={
        "action": "header",
        "function": "changeCurrentCity",
        "actionRequest": actionRequest,
        "oldView": "city",
        "cityId": str(origin_city_id),
        "backgroundView": "city",
        "currentCityId": str(curr_id),
        "ajax": "1",
    })
    time.sleep(random.randint(3, 7))

    data = {
        "action": "transportOperations",
        "function": "loadTransportersWithFreight",
        "destinationCityId": str(dest_city_id),
        "islandId": str(island_id),
        "oldView": "", "position": "", "avatar2Name": "", "city2Name": "",
        "type": "", "activeTab": "",
        "transportDisplayPrice": "0", "premiumTransporter": "0",
        "capacity": "5", "max_capacity": "5", "jetPropulsion": "0",
        "backgroundView": "city",
        "currentCityId": str(origin_city_id),
        "templateView": "transport",
        "currentTab": "tabSendTransporter",
        "actionRequest": actionRequest,
        "ajax": "1",
    }
    if use_freighters:
        data["usedFreightersShips"] = str(ships)
        data["transporters"] = "0"
    else:
        data["transporters"] = str(ships)

    for i, amount in enumerate(send_list):
        if amount > 0:
            key = "cargo_resource" if i == 0 else "cargo_tradegood{:d}".format(i)
            data[key] = str(amount)

    resp = session.post(params=data)
    try:
        return json.loads(resp, strict=False)[3][1][0]["type"] == 10
    except Exception:
        return False


def _build_send_list(surplus, remaining, ship_cap, ships_available):
    """Build a send_list (5 resources) and ships_to_use from surplus and remaining need.
    Returns (send_list, ships_to_use) where send_list sums to 0 if nothing can be sent."""
    send_list = [0, 0, 0, 0, 0]
    for i in range(5):
        if remaining[i] == 0 or surplus[i] == 0:
            continue
        to_send = min(surplus[i], remaining[i])
        to_send = math.ceil(to_send / 1000) * 1000
        to_send = min(to_send, surplus[i])
        if to_send > 0:
            send_list[i] = to_send

    total = sum(send_list)
    if total == 0:
        return send_list, 0

    ships_needed = math.ceil(total / ship_cap)
    ships_to_use = min(ships_available, ships_needed)

    if ships_to_use < ships_needed:
        # Capacity-constrained: fill available capacity across resources in order
        capacity = ships_to_use * ship_cap
        scaled = [0, 0, 0, 0, 0]
        for i in range(5):
            if send_list[i] == 0 or capacity <= 0:
                continue
            fits = min(send_list[i], capacity)
            fits = (fits // 1000) * 1000
            scaled[i] = fits
            capacity -= fits
        send_list = scaled
        total = sum(scaled)

    return send_list, ships_to_use


def _try_transport(session, city_name, city_id, city_data, next_item, target_b, queues, name_to_id, transport_errors=None):
    """Dispatch missing resources from surplus cities toward city_name.
    One bundled fleet per source city (all resources in one dispatch).
    Freighters used as a fallback only when total need is very large.
    Returns True if at least one transport was successfully dispatched."""
    from ikabot.helpers.naval import getAvailableShips, getAvailableFreighters
    from ikabot.helpers.pedirInfo import getShipCapacity

    building_name = next_item["building"]
    current_level = target_b["level"]

    costs_cache = {}
    try:
        from db_manager import get_building_costs
        costs_cache = get_building_costs()
    except Exception:
        pass

    cost = _get_total_upgrade_cost(costs_cache, city_name, building_name,
                                   current_level, current_level + 1)
    if cost is None:
        print(lm("queue_no_cost_data", city=city_name, building=building_name))
        try:
            from ikabot.function.constructionList import getResourcesNeeded
            cost = getResourcesNeeded(session, city_data, target_b, current_level, current_level + 1)
        except Exception:
            import traceback
            print(traceback.format_exc())
            return False
        if cost is None or cost == [-1, -1, -1, -1, -1]:
            return False

    available = city_data.get("availableResources", [0] * 5)
    buf = _get_resource_buffer()
    missing = [max(0, cost[i] + (buf[i] if cost[i] > 0 else 0) - available[i]) for i in range(5)]
    if all(m == 0 for m in missing):
        return False

    in_transit = _get_in_transit_to(city_name)
    net_missing = [max(0, missing[i] - in_transit[i]) for i in range(5)]

    missing_desc = ", ".join(
        "{} {}".format(net_missing[i], _RESOURCES_ENG[i])
        for i in range(5) if net_missing[i] > 0
    )
    print(lm("queue_transport_missing", city=city_name, building=building_name,
              missing=missing_desc or "0"))

    if all(m == 0 for m in net_missing):
        print(lm("queue_transport_waiting", city=city_name))
        return False

    ships_available = getAvailableShips(session)
    if ships_available == 0:
        print(lm("queue_no_ships", city=city_name))
        return False

    ship_cap, freighter_cap = getShipCapacity(session)
    total_need = sum(net_missing)

    all_resources = _load_resources_json()
    empire = _load_empire_json()

    sources = []
    for src_name, src_id in name_to_id.items():
        if src_name == city_name:
            continue
        src_res = all_resources.get(src_name, {})
        src_avail = [src_res.get(_RESOURCES_ENG[i], 0) for i in range(5)]
        reserved = _calc_city_reserved(src_name, queues, empire, costs_cache)
        surplus = [max(0, src_avail[i] - reserved[i] - buf[i]) for i in range(5)]
        if any(s > 0 for s in surplus):
            sources.append((src_name, src_id, surplus))

    sources.sort(key=lambda x: sum(x[2]), reverse=True)

    if not sources:
        print(lm("queue_no_surplus", city=city_name))
        return False

    island_id = city_data.get("islandId", "")
    first_route = True
    dispatched = False
    remaining = list(net_missing)
    used_sources = set()

    # ── Transporter pass: one bundled fleet per source city ───────────────────
    for src_name, src_id, surplus in sources:
        if ships_available == 0 or all(r == 0 for r in remaining):
            break

        send_list, ships_to_use = _build_send_list(surplus, remaining, ship_cap, ships_available)
        if sum(send_list) == 0:
            continue

        if not first_route:
            time.sleep(random.randint(12, 30))
        first_route = False

        success = _dispatch_transport(session, src_id, city_id, island_id,
                                      ships_to_use, send_list)
        if success:
            dispatched = True
            used_sources.add(src_name)
            for i in range(5):
                remaining[i] = max(0, remaining[i] - send_list[i])
                surplus[i] = max(0, surplus[i] - send_list[i])
            ships_available -= ships_to_use
            if transport_errors is not None:
                transport_errors.pop(city_name, None)
            sent_desc = ", ".join(
                "{} {}".format(send_list[i], _RESOURCES_ENG[i])
                for i in range(5) if send_list[i] > 0
            )
            print(lm("queue_transport_sent_bundle", city=city_name, resources=sent_desc,
                      origin=src_name, ships=ships_to_use))
        else:
            failed_resource = next((_RESOURCES_ENG[i] for i in range(5) if send_list[i] > 0), "?")
            if transport_errors is not None:
                transport_errors[city_name] = {
                    "failedAt": int(time.time()),
                    "origin": src_name,
                    "resource": failed_resource,
                }
            try:
                from telegram_notifier import notify_transport_error
                notify_transport_error(city_name, failed_resource, src_name)
            except Exception:
                pass
            print(lm("queue_transport_failed", city=city_name, origin=src_name))

    # ── Freighter pass: only when total need is very large ────────────────────
    # Skip if total need is small — transporter waves are faster (8 min vs 2h40m)
    if total_need > ship_cap * _FREIGHTER_THRESHOLD_WAVES and sum(remaining) > 0:
        try:
            freighters_available = getAvailableFreighters(session)
        except Exception:
            freighters_available = 0

        if freighters_available > 0 and freighter_cap > 0:
            # Prefer source cities that haven't dispatched transporters this cycle (avoid port queue)
            freighter_sources = [s for s in sources if s[0] not in used_sources]
            for src_name, src_id, surplus in freighter_sources:
                if all(r == 0 for r in remaining):
                    break

                send_list, freighters_to_use = _build_send_list(
                    surplus, remaining, freighter_cap, freighters_available
                )
                if sum(send_list) == 0:
                    continue

                if not first_route:
                    time.sleep(random.randint(12, 30))
                first_route = False

                success = _dispatch_transport(session, src_id, city_id, island_id,
                                              freighters_to_use, send_list, use_freighters=True)
                if success:
                    dispatched = True
                    for i in range(5):
                        remaining[i] = max(0, remaining[i] - send_list[i])
                    sent_desc = ", ".join(
                        "{} {}".format(send_list[i], _RESOURCES_ENG[i])
                        for i in range(5) if send_list[i] > 0
                    )
                    print(lm("queue_freighter_sent", city=city_name, resources=sent_desc,
                              origin=src_name, ships=freighters_to_use))
                else:
                    print(lm("queue_freighter_failed", city=city_name, origin=src_name))
                break  # one freighter fleet per cycle

    return dispatched


# ── Main queue processor ──────────────────────────────────────────────────────

def process_building_queue(session, ids, cities):
    """Process one queue cycle. Returns True if any transport was dispatched."""
    print(lm("queue_cycle_start", ts=time.strftime('%H:%M:%S')))
    data = _load_queue()
    if not data.get("enabled", True):
        return False
    queues = data.get("queues", {})
    in_progress = data.get("inProgress", {})
    transport_errors = data.setdefault("transportErrors", {})
    transport_errors_snapshot = dict(transport_errors)
    changed = False
    dispatched_any = False

    name_to_id = {cities[cid]["name"]: cid for cid in ids if cid in cities}

    first_city = True
    for city_name in random.sample(list(queues.keys()), len(queues)):
        items = queues[city_name]
        if not items:
            continue

        city_id = name_to_id.get(city_name)
        if not city_id:
            print(lm("queue_city_not_found", city=city_name))
            continue

        if not first_city:
            time.sleep(random.randint(15, 30))
        first_city = False

        html = session.get("view=city&cityId={}".format(city_id))
        city_data = getCity(html)

        # ── Check if tracked in-progress construction has completed ──────────
        ip = in_progress.get(city_name)
        if ip:
            ip_pos = ip.get("position")
            if ip_pos is not None and ip_pos < len(city_data["position"]):
                still_busy = bool(city_data["position"][ip_pos].get("isBusy"))
            else:
                still_busy = any(
                    b.get("isBusy") and b["name"] == ip["building"]
                    for b in city_data["position"]
                )
            if not still_busy:
                print(lm("queue_construction_done", city=city_name, building=ip["building"]))
                try:
                    from telegram_notifier import notify_construction_done
                    notify_construction_done(city_name, ip["building"], ip.get("toLevel", ip.get("fromLevel", 0) + 1))
                except Exception:
                    pass
                if items and items[0]["building"] == ip["building"]:
                    still_below = any(
                        b["name"] == items[0]["building"] and b["level"] < items[0]["targetLevel"]
                        for b in city_data["position"]
                    )
                    if not still_below:
                        items.pop(0)
                del in_progress[city_name]
                changed = True

        if not items:
            continue

        # ── Skip if any construction is already running ──────────────────────
        if any(b.get("isBusy") for b in city_data["position"]):
            if city_name not in in_progress:
                busy_b = next((b for b in city_data["position"] if b.get("isBusy")), None)
                if busy_b and items:
                    in_progress[city_name] = {
                        "building": busy_b.get("name") or items[0]["building"],
                        "position": busy_b["position"],
                        "fromLevel": busy_b.get("level", 0),
                        "toLevel": busy_b.get("level", 0) + 1,
                        "startedAt": int(time.time()),
                        "eta": int(busy_b.get("completed", 0)),
                    }
                    changed = True
            print(lm("queue_city_busy", city=city_name))
            continue

        # ── Try to start the next item ────────────────────────────────────────
        next_item = items[0]
        candidates = [
            b for b in city_data["position"]
            if b["name"] == next_item["building"]
            and not b.get("isMaxLevel")
            and b["level"] < next_item["targetLevel"]
        ]
        target_b = min(candidates, key=lambda b: b["level"]) if candidates else None

        if target_b is None:
            # No candidate: building absent, already at/above target, or all instances at max level
            all_instances = [b for b in city_data["position"] if b["name"] == next_item["building"]]
            if not all_instances:
                print(lm("queue_building_not_found", city=city_name, building=next_item["building"]))
            elif all(b.get("isMaxLevel") for b in all_instances):
                print(lm("queue_max_level", city=city_name, building=next_item["building"]))
            else:
                print(lm("queue_target_reached", city=city_name, building=next_item["building"], level=next_item["targetLevel"]))
            items.pop(0)
            changed = True
            continue

        # ── Determine if transport is needed (server + buffer check) ─────────
        need_transport = target_b.get("canUpgrade") is False
        if not need_transport:
            buf = _get_resource_buffer()
            if any(b > 0 for b in buf):
                cost_check = _get_upgrade_cost_from_cache(city_name, next_item["building"], target_b["level"])
                if cost_check is not None:
                    avail_check = city_data.get("availableResources", [0] * 5)
                    if any(cost_check[i] > 0 and avail_check[i] - cost_check[i] < buf[i] for i in range(5)):
                        need_transport = True

        if need_transport:
            if _in_active_hours():
                if _try_transport(session, city_name, city_id, city_data, next_item,
                                  target_b, queues, name_to_id, transport_errors):
                    dispatched_any = True
            else:
                _ah_s, _ah_e = _get_active_hours()
                print(lm("queue_outside_hours", start=_ah_s, end=_ah_e))
            continue

        if city_data.get("freeCitizens", 1) == 0:
            print(lm("queue_no_citizens", city=city_name, building=next_item["building"]))
            continue

        if not _in_active_hours():
            _ah_s, _ah_e = _get_active_hours()
            print(lm("queue_outside_hours", start=_ah_s, end=_ah_e))
            continue

        # ── Fire the upgrade POST ─────────────────────────────────────────────
        print(lm("queue_attempting", city=city_name, building=next_item["building"],
                  lv=target_b["level"], btype=target_b["building"], pos=target_b["position"],
                  can=target_b.get("canUpgrade"), cit=city_data.get("freeCitizens")))

        from ikabot.function.constructionList import expandBuilding as _expandBuilding
        target_for_expand = dict(target_b)
        target_for_expand["upgradeTo"] = target_b["level"] + 1
        _expandBuilding(session, city_id, target_for_expand, False)

        time.sleep(random.randint(1, 4))
        html2 = session.get("view=city&cityId={}".format(city_id))
        city2 = getCity(html2)
        pos_idx = target_b["position"]
        started = False
        if pos_idx < len(city2["position"]):
            b = city2["position"][pos_idx]
            if b.get("isBusy"):
                in_progress[city_name] = {
                    "building": next_item["building"],
                    "position": pos_idx,
                    "fromLevel": target_b["level"],
                    "toLevel": target_b["level"] + 1,
                    "startedAt": int(time.time()),
                    "eta": int(b.get("completed", 0)),
                }
                started = True
                changed = True
                print(lm("queue_started", city=city_name, building=next_item["building"],
                          from_lv=target_b["level"], to_lv=target_b["level"] + 1))

        if not started:
            print(lm("queue_start_failed", city=city_name, building=next_item["building"]))
            b_diag = city2["position"][pos_idx] if pos_idx < len(city2["position"]) else {}
            print("      -> [diag] pos={} após POST: level={}, canUpgrade={}, isMaxLevel={}, isBusy={}, building={}".format(
                pos_idx, b_diag.get("level"), b_diag.get("canUpgrade"),
                b_diag.get("isMaxLevel"), b_diag.get("isBusy"), b_diag.get("building")))
            next_item["failedAttempts"] = next_item.get("failedAttempts", 0) + 1
            changed = True
            if next_item["failedAttempts"] >= 5:
                print("      -> [aviso] {} tentativas falhadas consecutivas para {}. A remover da fila.".format(
                    next_item["failedAttempts"], next_item["building"]))
                items.pop(0)

    if changed or transport_errors != transport_errors_snapshot:
        data["queues"] = queues
        data["inProgress"] = in_progress
        _save_queue(data)

    print(lm("queue_done"))
    return dispatched_any
