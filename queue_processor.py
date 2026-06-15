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
    ACTIVE_HOURS_START, ACTIVE_HOURS_END,
    SCAN_ACTIVE_HOURS_START, SCAN_ACTIVE_HOURS_END,
    FORCE_EMPIRE_FLAG, FORCE_QUEUE_FLAG, FORCE_MOVEMENTS_FLAG,
    FORCE_IMPORT_REPORTS_FLAG, FORCE_MILITARY_FLAG, lm, logger,
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
    if any(len(items) > 0 for items in data.get("queues", {}).values()):
        return True
    # Also return True for stale inProgress entries (past ETA, no queue items) so the
    # cleanup pass in process_building_queue gets a chance to remove them.
    now = time.time()
    queues = data.get("queues", {})
    for city_name, ip in data.get("inProgress", {}).items():
        if not queues.get(city_name) and ip.get("eta", 0) <= now:
            return True
    return False


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


def _in_scan_hours():
    """Return True if current local hour is within the scan active hours window."""
    if SCAN_ACTIVE_HOURS_START == 0 and SCAN_ACTIVE_HOURS_END == 24:
        return True
    return SCAN_ACTIVE_HOURS_START <= time.localtime().tm_hour < SCAN_ACTIVE_HOURS_END


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


def _get_next_spy_eta():
    """Earliest upcoming spy step ETA — execute AND collect states. Including the collect
    states (report pickup) means reports are fetched promptly instead of waiting for the
    next hourly cycle, which was stalling the spy pipeline ~1h between each step."""
    try:
        from espionage_manager import _load_missions
        etas = []
        now = time.time()
        for m in _load_missions().get("missions", []):
            st = m.get("state")
            if st == "WAITING_AT_CITY" and m.get("executeAfter", 0) > now:
                etas.append(m["executeAfter"])
            elif st == "WAITING_FOR_GARRISON" and m.get("garrisonExecuteAfter", 0) > now:
                etas.append(m["garrisonExecuteAfter"])
            elif st in ("EXECUTING", "EXECUTING_WAREHOUSE") and m.get("collectAfter", 0) > now:
                etas.append(m["collectAfter"])
            elif st == "EXECUTING_GARRISON" and m.get("garrisonCollectAfter", 0) > now:
                etas.append(m["garrisonCollectAfter"])
        return min(etas) if etas else None
    except Exception:
        return None


def smart_sleep(last_full_cycle_time, next_full_jitter, session=None):
    """Sleep until the next full empire cycle, next construction ETA, or next transport arrival, whichever is soonest."""
    next_full_at = last_full_cycle_time + UPDATE_INTERVAL + next_full_jitter
    q = _load_queue()  # single load — reused by all helpers below
    construction_eta = _get_next_construction_eta(q)
    transport_eta = _get_next_transport_eta(q)
    spy_eta = _get_next_spy_eta()
    farm_eta = None
    try:
        from farm_manager import next_farm_eta
        farm_eta = next_farm_eta()
    except Exception:
        pass

    eta = None
    if construction_eta:
        eta = construction_eta
    if transport_eta:
        eta = min(eta, transport_eta) if eta else transport_eta
    if spy_eta:
        eta = min(eta, spy_eta) if eta else spy_eta
    if farm_eta:
        eta = min(eta, farm_eta) if eta else farm_eta

    if eta and _in_active_hours():
        # Wake just after the ETA. The events themselves (spy executeAfter, farm
        # next_run_at, etc.) already carry their own randomised delay, so only a small
        # nudge is needed here — a large jitter would stack on top and make scheduled
        # actions (e.g. a spy due in 13 min) fire 20+ min late.
        wake_for_queue = eta + random.randint(20, 70)
        sleep_secs = max(30, min(next_full_at, wake_for_queue) - time.time())
        if wake_for_queue < next_full_at:
            eta_str = time.strftime('%H:%M:%S', time.localtime(eta))
            logger.info(lm("queue_sleep_until", eta=eta_str, mins=round(sleep_secs / 60)))
    else:
        sleep_secs = max(60, next_full_at - time.time())
        # Se há itens em queue mas sem ETA conhecido, acorda em 30 min para re-tentar
        if has_building_queue(q) and _in_active_hours():
            sleep_secs = min(sleep_secs, 1800)

    if not _in_active_hours():
        secs_to_open = _secs_until_active()
        if 0 < secs_to_open < sleep_secs:
            sleep_secs = secs_to_open + random.randint(1, 5) * 60
            logger.info(lm("queue_sleep_until_hours", mins=round(sleep_secs / 60),
                           start=_get_active_hours()[0]))

    logger.info(lm("cycle_sleep", mins=round(sleep_secs / 60)))
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

        # F6 attack watch: periodically refresh movements so incoming-attack alerts are
        # timely (opt-in via alert_settings.checkMinutes; refresh_movements keeps the
        # anti-detection delay). Without it, alerts only fire on the hourly cycle.
        if session and _in_scan_hours():
            try:
                import json as _json
                from empire_collector import ALERT_SETTINGS_PATH, refresh_movements
                from ikabot.helpers.pedirInfo import getIdsOfCities
                check_min = 0
                try:
                    with open(ALERT_SETTINGS_PATH) as _f:
                        check_min = int(_json.load(_f).get("checkMinutes", 0))
                except Exception:
                    check_min = 0
                if check_min > 0:
                    last_watch = getattr(smart_sleep, "_last_attack_watch", 0)
                    if time.time() - last_watch >= check_min * 60:
                        smart_sleep._last_attack_watch = time.time()
                        _ids, _ = getIdsOfCities(session)
                        refresh_movements(session, _ids[0])
                        continue
            except Exception:
                pass

        # Manual military refresh triggered by Flask UI (military.json has an 8h cache)
        if session and os.path.exists(FORCE_MILITARY_FLAG):
            try:
                os.remove(FORCE_MILITARY_FLAG)
            except Exception:
                pass
            try:
                from empire_collector import _collect_military_data
                _collect_military_data(session)
            except Exception:
                logger.error("military refresh falhou", exc_info=True)
            continue

        # Import existing safehouse reports triggered by Flask UI
        if session and os.path.exists(FORCE_IMPORT_REPORTS_FLAG):
            try:
                os.remove(FORCE_IMPORT_REPORTS_FLAG)
            except Exception:
                pass
            try:
                from espionage_manager import import_existing_reports
                import_existing_reports(session)
            except Exception:
                logger.error("import_existing_reports falhou", exc_info=True)
            continue

        # Pending spy dispatch or recalls queued by the Flask UI — process immediately.
        # has_due_recalls: recalls waiting for a spaced retry must not skip the sleep.
        if session:
            try:
                from espionage_manager import has_pending_dispatch, process_dispatch_queue, has_due_recalls, _process_recall_queue
                if has_due_recalls():
                    _process_recall_queue(session)
                    continue
                if has_pending_dispatch():
                    process_dispatch_queue(session)
                    continue
            except Exception:
                pass

        # Pending scheduled attacks — dispatch as soon as dispatchAfter is reached.
        # has_due_attacks (not has_pending_attacks): a future-scheduled attack must not
        # short-circuit the sleep below, or this loop spins hot until dispatch time.
        # is_paused() must gate the `continue` paths too: a due item the processor
        # refuses to handle while paused would otherwise spin this loop hot.
        from empire_utils import is_paused
        if session and _in_scan_hours() and not is_paused():
            try:
                from attack_manager import has_due_attacks, process_attack_queue
                if has_due_attacks():
                    process_attack_queue(session, in_active_hours=True)
                    continue
            except Exception:
                pass

        # Pending scheduled resource transports (same due-gating as attacks)
        if session and _in_scan_hours() and not is_paused():
            try:
                from transport_manager import has_due_transports, process_transport_queue
                if has_due_transports():
                    process_transport_queue(session, in_active_hours=True)
                    continue
            except Exception:
                pass

        # Target farm (F4) — event-driven: advance any target whose spy/attack/return
        # is due, within ~60s instead of waiting for the next full empire cycle.
        if session and _in_scan_hours() and not is_paused():
            try:
                from farm_manager import has_due_farm, process_farm_targets
                if has_due_farm():
                    process_farm_targets(session, in_active_hours=True)
                    continue
            except Exception:
                pass

        # Opportunistic island scan during idle time — uses the natural sleep
        # variation as an organic source of randomness in batch size
        if session and _in_scan_hours() and (end_time - time.time()) > 50:
            try:
                from scan_collector import scan_has_pending, scan_next_island
                if scan_has_pending():
                    scan_next_island(session)
                    continue  # re-check flags immediately after island scan
            except Exception:
                pass

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
        logger.warning(lm("queue_no_cost_data", city=city_name, building=building_name))
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
    logger.info(lm("queue_transport_missing", city=city_name, building=building_name,
                   missing=missing_desc or "0"))

    if all(m == 0 for m in net_missing):
        logger.info(lm("queue_transport_waiting", city=city_name))
        return False

    ships_available = getAvailableShips(session)
    if ships_available == 0:
        logger.warning(lm("queue_no_ships", city=city_name))
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
        logger.warning(lm("queue_no_surplus", city=city_name))
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
            logger.info(lm("queue_transport_sent_bundle", city=city_name, resources=sent_desc,
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
            logger.warning(lm("queue_transport_failed", city=city_name, origin=src_name))

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
                    logger.info(lm("queue_freighter_sent", city=city_name, resources=sent_desc,
                                   origin=src_name, ships=freighters_to_use))
                else:
                    logger.warning(lm("queue_freighter_failed", city=city_name, origin=src_name))
                break  # one freighter fleet per cycle

    return dispatched


# ── Main queue processor ──────────────────────────────────────────────────────

def _needs_transport_for_buffer(city_name, item, target_b, city_data):
    """True if doing this upgrade now would push some resource below the configured
    buffer — i.e. a top-up transport is warranted even though the server would allow it."""
    buf = _get_resource_buffer()
    if not any(b > 0 for b in buf):
        return False
    cost_check = _get_upgrade_cost_from_cache(city_name, item["building"], target_b["level"])
    if cost_check is None:
        return False
    avail_check = city_data.get("availableResources", [0] * 5)
    return any(cost_check[i] > 0 and avail_check[i] - cost_check[i] < buf[i] for i in range(5))


def process_building_queue(session, ids, cities):
    """Process one queue cycle. Returns True if any transport was dispatched."""
    from empire_utils import is_paused
    if is_paused():
        logger.info("[pause] em pausa — fila de construção ignorada")
        return False
    logger.info(lm("queue_cycle_start", ts=time.strftime('%H:%M:%S')))
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
            logger.warning(lm("queue_city_not_found", city=city_name))
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
                logger.info(lm("queue_construction_done", city=city_name, building=ip["building"]))
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
            logger.info(lm("queue_city_busy", city=city_name))

            # ── F8.b: pre-stage the NEXT queued item while this one builds ──────
            # Construction takes hours during which no resources are moved otherwise.
            # Move what the next item needs now so it can start the moment a slot frees.
            if _in_active_hours():
                busy_names = {b["name"] for b in city_data["position"] if b.get("isBusy")}
                pre_item = next(
                    (it for it in items
                     if it["building"] not in busy_names
                     and any(b["name"] == it["building"] and not b.get("isMaxLevel")
                             and b["level"] < it["targetLevel"]
                             for b in city_data["position"])),
                    None,
                )
                if pre_item:
                    pre_cands = [
                        b for b in city_data["position"]
                        if b["name"] == pre_item["building"]
                        and not b.get("isMaxLevel") and b["level"] < pre_item["targetLevel"]
                    ]
                    pre_target = min(pre_cands, key=lambda b: b["level"])
                    if pre_target.get("canUpgrade") is False or _needs_transport_for_buffer(
                            city_name, pre_item, pre_target, city_data):
                        logger.info(lm("queue_prestage", city=city_name, building=pre_item["building"]))
                        if _try_transport(session, city_name, city_id, city_data, pre_item,
                                          pre_target, queues, name_to_id, transport_errors):
                            dispatched_any = True
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
                logger.warning(lm("queue_building_not_found", city=city_name, building=next_item["building"]))
            elif all(b.get("isMaxLevel") for b in all_instances):
                logger.info(lm("queue_max_level", city=city_name, building=next_item["building"]))
            else:
                logger.info(lm("queue_target_reached", city=city_name, building=next_item["building"], level=next_item["targetLevel"]))
            items.pop(0)
            changed = True
            continue

        # ── Determine if transport is needed (server + buffer check) ─────────
        need_transport = (target_b.get("canUpgrade") is False
                          or _needs_transport_for_buffer(city_name, next_item, target_b, city_data))

        if need_transport:
            if _in_active_hours():
                if _try_transport(session, city_name, city_id, city_data, next_item,
                                  target_b, queues, name_to_id, transport_errors):
                    dispatched_any = True
            else:
                _ah_s, _ah_e = _get_active_hours()
                logger.info(lm("queue_outside_hours", start=_ah_s, end=_ah_e))
            continue

        if city_data.get("freeCitizens", 1) == 0:
            logger.warning(lm("queue_no_citizens", city=city_name, building=next_item["building"]))
            continue

        if not _in_active_hours():
            _ah_s, _ah_e = _get_active_hours()
            logger.info(lm("queue_outside_hours", start=_ah_s, end=_ah_e))
            continue

        # ── Fire the upgrade POST ─────────────────────────────────────────────
        logger.info(lm("queue_attempting", city=city_name, building=next_item["building"],
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
                logger.info(lm("queue_started", city=city_name, building=next_item["building"],
                               from_lv=target_b["level"], to_lv=target_b["level"] + 1))

        if not started:
            logger.warning(lm("queue_start_failed", city=city_name, building=next_item["building"]))
            b_diag = city2["position"][pos_idx] if pos_idx < len(city2["position"]) else {}
            logger.warning("      -> [diag] pos=%s level=%s canUpgrade=%s isMaxLevel=%s isBusy=%s building=%s",
                           pos_idx, b_diag.get("level"), b_diag.get("canUpgrade"),
                           b_diag.get("isMaxLevel"), b_diag.get("isBusy"), b_diag.get("building"))
            next_item["failedAttempts"] = next_item.get("failedAttempts", 0) + 1
            changed = True
            if next_item["failedAttempts"] >= 5:
                logger.warning("      -> [aviso] %d tentativas falhadas consecutivas para %s. A remover da fila.",
                               next_item["failedAttempts"], next_item["building"])
                items.pop(0)

    # Clean up inProgress entries whose ETA has passed but have no matching queue items.
    # This happens when the user clears/removes queue items while a build is running,
    # leaving an inProgress entry that can never be resolved by the main loop above
    # (because `if not items: continue` skips cities with empty queues).
    now = time.time()
    for city_name in list(in_progress.keys()):
        if queues.get(city_name):
            continue  # non-empty queue — main loop already handles this city
        ip = in_progress[city_name]
        if ip.get("eta", 0) <= now:
            logger.info(lm("queue_stale_cleanup", city=city_name, building=ip.get("building", "?")))
            del in_progress[city_name]
            changed = True

    if changed or transport_errors != transport_errors_snapshot:
        data["queues"] = queues
        data["inProgress"] = in_progress
        _save_queue(data)

    logger.info(lm("queue_done"))
    return dispatched_any
