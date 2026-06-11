#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import random
import sys
import time
from decimal import Decimal, getcontext

getcontext().prec = 30

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from empire_utils import LOGS_DIR, MAX_HISTORY_LINES, EMPIRE_SCAN_STATUS_PATH, lm, logger, with_retry

from ikabot.config import materials_names_english, materials_names_tec
from ikabot.helpers.getJson import getCity
from ikabot.config import actionRequest


def _trim_history(path):
    """Keep only the last MAX_HISTORY_LINES lines in history.jsonl."""
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        if len(lines) > MAX_HISTORY_LINES:
            with open(path, "w") as f:
                f.writelines(lines[-MAX_HISTORY_LINES:])
    except Exception:
        pass


def _collect_movements(session, city_id):
    """Fetch military/fleet movements from the military advisor endpoint."""
    try:
        url = (
            "view=militaryAdvisor&oldView=city&oldBackgroundView=city"
            "&backgroundView=city&currentCityId={}&actionRequest={}&ajax=1".format(
                city_id, actionRequest
            )
        )
        resp = with_retry(lambda: session.post(url), attempts=3, delay=30, label="movements")
        data = json.loads(resp, strict=False)
        movements_raw = data[1][1][2]["viewScriptParams"]["militaryAndFleetMovements"]
        time_now = int(float(data[0][1]["time"]))

        movements = []
        for m in movements_raw:
            time_left = int(float(m["eventTime"])) - time_now
            arrival_ts = int(float(m["eventTime"]))
            is_returning = m["event"].get("isFleetReturning", False)

            entry = {
                "origin": "{} ({})".format(
                    m["origin"]["name"], m["origin"]["avatarName"]
                ),
                "destination": "{} ({})".format(
                    m["target"]["name"], m["target"]["avatarName"]
                ),
                "direction": "<-" if is_returning else "->",
                "mission": m["event"].get("missionText", ""),
                "timeLeft": max(time_left, 0),
                "arrivalTime": arrival_ts,
                "isHostile": bool(m.get("isHostile", False)),
                "isOwn": bool(m.get("isOwnArmyOrFleet", False)),
                "isSameAlliance": bool(m.get("isSameAlliance", False)),
                "resources": [],
            }

            if not entry["isHostile"] and "resources" in m:
                for resource in m["resources"]:
                    amount_str = resource.get("amount", "0")
                    css = resource.get("cssClass", "")
                    tradegood = css.split()[-1] if css else "unknown"
                    if tradegood in materials_names_tec:
                        idx = materials_names_tec.index(tradegood)
                        tradegood = materials_names_english[idx]
                    entry["resources"].append(
                        {"resource": tradegood, "amount": amount_str}
                    )

            if entry["isHostile"] and "army" in m:
                entry["troops"] = m["army"].get("amount", 0)
                entry["fleets"] = m["fleet"].get("amount", 0)

            movements.append(entry)

        return movements
    except Exception:
        logger.warning(lm("movements_error"), exc_info=True)
        return []


def _write_scan_status(status, phase, progress, total, message=""):
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(EMPIRE_SCAN_STATUS_PATH, "w") as f:
            json.dump({"status": status, "phase": phase, "progress": progress, "total": total, "message": message}, f)
    except Exception:
        pass


def collect_city_data(session, ids, cities):
    """Per-city data collection loop. Returns (status_summary, formatted_empire, resources_data)
    and writes own_cities.json."""
    from ikabot.config import materials_names

    _write_scan_status("running", "cities", 0, len(ids), "")

    total_resources = [0] * len(materials_names)
    total_production = [0] * len(materials_names)
    total_wine_consumption = 0
    total_housing_space = 0
    total_citizens = 0
    available_ships = 0
    total_ships = 0
    total_gold = 0
    total_gold_production = 0

    empire_data = {}
    resources_data = {}
    building_names = set()
    own_cities_list = []

    for id in random.sample(ids, len(ids)):
        time.sleep(random.randint(2, 7))

        try:
            html      = with_retry(lambda: session.get("view=city&cityId={}".format(id)),
                                   attempts=3, delay=30, label="city {}".format(id))
            city_data = getCity(html)

            time.sleep(random.randint(2, 6))
            raw       = with_retry(lambda: session.get("view=updateGlobalData&ajax=1", noIndex=True),
                                   attempts=3, delay=30, label="globalData {}".format(id))
            json_data = json.loads(raw, strict=False)[0][1]["headerData"]
        except Exception:
            logger.error("city %s failed after 3 attempts — skipping", id, exc_info=True)
            continue

        if json_data["relatedCity"]["owncity"] != 1:
            continue

        wood = Decimal(json_data["resourceProduction"])
        good = Decimal(json_data["tradegoodProduction"])
        typeGood = int(float(json_data["producedTradegood"]))
        total_production[0] += wood * 3600
        total_production[typeGood] += good * 3600
        total_wine_consumption += float(json_data["wineSpendings"]) / 2

        housing_space = int(float(json_data["currentResources"]["population"]))
        citizens = int(float(json_data["currentResources"]["citizens"]))
        total_housing_space += housing_space
        total_citizens += citizens

        total_resources[0] += float(json_data["currentResources"]["resource"])
        total_resources[1] += float(json_data["currentResources"]["1"])
        total_resources[2] += float(json_data["currentResources"]["2"])
        total_resources[3] += float(json_data["currentResources"]["3"])
        total_resources[4] += float(json_data["currentResources"]["4"])

        available_ships = int(float(json_data["freeTransporters"]))
        total_ships = int(float(json_data["maxTransporters"]))

        total_gold = int(Decimal(json_data["gold"]))
        total_gold_production = int(
            Decimal(
                json_data["scientistsUpkeep"]
                + json_data["income"]
                + json_data["upkeep"]
            )
        )

        city_name = city_data.get("cityName", city_data.get("name", "Unknown"))
        island_x = int(float(city_data.get("islandXCoord", city_data.get("x", 0)) or 0))
        island_y = int(float(city_data.get("islandYCoord", city_data.get("y", 0)) or 0))
        own_cities_list.append({
            "name": city_name, "cityId": id, "x": island_x, "y": island_y,
            "islandId": str(city_data.get("islandId", "")),
        })
        logger.info(lm("city_done", city=city_name))
        _write_scan_status("running", "cities", len(own_cities_list), len(ids), city_name)

        storage_capacity = int(float(city_data.get("storageCapacity") or 0))
        wine_consumption_hr = int(float(city_data.get("wineConsumptionPerHour") or 0) / 2)
        wine_production_hr = int(good * 3600) if typeGood == 1 else 0

        city_resources = {}
        for i, resource in enumerate(materials_names_english):
            city_resources[resource] = city_data["availableResources"][i]

        city_resources["storageCapacity"] = storage_capacity
        city_resources["wineConsumptionPerHour"] = wine_consumption_hr
        city_resources["wineProductionPerHour"] = wine_production_hr

        if wine_consumption_hr > 0:
            net_wine_per_sec = (wine_production_hr - wine_consumption_hr) / 3600
            if net_wine_per_sec >= 0:
                city_resources["wineRunsOutIn"] = -1
            else:
                wine_available = city_resources["Wine"]
                city_resources["wineRunsOutIn"] = int(
                    wine_available / abs(net_wine_per_sec)
                )
        else:
            city_resources["wineRunsOutIn"] = -1

        resources_data[city_name] = city_resources

        city_buildings = {}
        construction_ends = int(float(city_data.get("endUpgradeTime") or 0))
        safehouse_slot = None

        if "position" in city_data:
            for b in city_data["position"]:
                if b["name"] != "empty":
                    building_names.add(b["name"])
                    level = str(b.get("level", ""))
                    if b.get("isBusy"):
                        level += "+"
                    city_buildings[b["name"]] = level
                # detect safehouse slot by building identifier (en) or display name (pt)
                if safehouse_slot is None:
                    bname = b.get("name", "").lower()
                    btype = b.get("building", "").lower()
                    if "espionagem" in bname or "safehouse" in btype:
                        safehouse_slot = b.get("position")

        city_buildings["_constructionEnds"] = construction_ends
        empire_data[city_name] = city_buildings

        # patch safehousePosition into own_cities_list entry added just above
        own_cities_list[-1]["safehousePosition"] = safehouse_slot

    status_summary = {
        "ships": {
            "available": int(available_ships),
            "total": int(total_ships),
        },
        "resources": {
            "available": [int(r) for r in total_resources],
            "production": [int(p) for p in total_production],
        },
        "housing": {
            "space": int(total_housing_space),
            "citizens": int(total_citizens),
        },
        "gold": {
            "total": int(total_gold),
            "production": int(total_gold_production),
        },
        "wine_consumption": int(total_wine_consumption),
    }

    formatted_empire = {}
    for city_name, buildings in empire_data.items():
        formatted_empire[city_name] = {"_constructionEnds": buildings.get("_constructionEnds", 0)}
        for bn in building_names:
            formatted_empire[city_name][bn] = buildings.get(bn, "")

    with open(os.path.join(LOGS_DIR, "own_cities.json"), "w") as f:
        json.dump(own_cities_list, f)

    return status_summary, formatted_empire, resources_data


def _parse_unit_tab(html, css_class):
    """Parse a cityMilitary tab HTML. css_class is 'army' or 'fleet'."""
    import re
    if css_class == "army":
        html = html.split('<div class="fleet')[0]
    id_names = re.findall(
        rf'<div class="{css_class} (.*?)">\s*<div class="tooltip">(.*?)<\/div>', html
    )
    amounts = re.findall(r"<td>(.*?)\s*</td>", html)
    units = {}
    for i in range(min(len(id_names), len(amounts))):
        raw = amounts[i].replace(",", "").replace(".", "").replace("-", "0").strip()
        try:
            amount = int(raw)
        except ValueError:
            amount = 0
        uid   = id_names[i][0].lstrip("_")
        uname = id_names[i][1]
        units[uid] = {"name": uname, "amount": amount}
    return units


def _collect_military_data(session):
    """Fetch troops + fleet per city and write military.json. Gated to run at most once every 8 hours."""
    military_path = os.path.join(LOGS_DIR, "military.json")
    try:
        with open(os.path.join(LOGS_DIR, "own_cities.json")) as f:
            own_cities = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return

    result = {}
    for city_info in random.sample(own_cities, len(own_cities)):
        city_id   = city_info.get("cityId")
        city_name = city_info.get("name", "")
        if not city_id:
            continue
        time.sleep(random.randint(3, 8))
        try:
            base_params = {
                "view":           "cityMilitary",
                "cityId":         city_id,
                "backgroundView": "city",
                "currentCityId":  city_id,
                "actionRequest":  actionRequest,
                "ajax":           "1",
            }

            # Troops tab
            params = dict(base_params, activeTab="tabUnits", currentTab="multiTab1")
            resp      = session.post(params=params)
            resp_data = json.loads(resp, strict=False)
            troops    = _parse_unit_tab(resp_data[1][1][1], "army")

            # Fleet tab
            time.sleep(random.randint(3, 8))
            params = dict(base_params, activeTab="tabFleet", currentTab="multiTab2")
            resp      = session.post(params=params)
            resp_data = json.loads(resp, strict=False)
            fleet     = _parse_unit_tab(resp_data[1][1][1], "fleet")

            result[city_name] = {"cityId": str(city_id), "troops": troops, "fleet": fleet}
            logger.info("[military] %s: %d tropa(s), %d frota(s)",
                        city_name, len(troops), len(fleet))
        except Exception:
            logger.warning("[military] erro %s", city_name, exc_info=True)

    if result:
        try:
            with open(military_path, "w") as f:
                json.dump({"lastUpdated": int(time.time()), "byCityName": result}, f, indent=2)
        except Exception:
            logger.error("[military] erro ao escrever military.json", exc_info=True)


def finalize_empire_cycle(session, ids, status_summary, formatted_empire, resources_data):
    """Collect movements and write all empire JSON files + history."""
    time.sleep(random.randint(5, 10))
    movements = _collect_movements(session, ids[0])

    os.makedirs(LOGS_DIR, exist_ok=True)

    # Collect military data when stale (>8 h) to keep attack modal current
    _mil_path = os.path.join(LOGS_DIR, "military.json")
    _mil_age  = (time.time() - os.path.getmtime(_mil_path)) if os.path.exists(_mil_path) else float("inf")
    if _mil_age > 8 * 3600:
        _collect_military_data(session)

    with open(os.path.join(LOGS_DIR, "statusSummary.json"), "w") as f:
        json.dump(status_summary, f, indent=4)

    with open(os.path.join(LOGS_DIR, "empire.json"), "w") as f:
        json.dump(formatted_empire, f, indent=4)

    with open(os.path.join(LOGS_DIR, "resources.json"), "w") as f:
        json.dump(resources_data, f, indent=4)

    with open(os.path.join(LOGS_DIR, "movements.json"), "w") as f:
        json.dump(movements, f, indent=4)

    ts = int(time.time())
    try:
        from db_manager import save_empire_snapshot, insert_history
        save_empire_snapshot(ts, formatted_empire, resources_data, status_summary)
        insert_history(ts, status_summary, resources_data)
    except Exception:
        logger.error("[db] insert_history error", exc_info=True)
        history_path = os.path.join(LOGS_DIR, "history.jsonl")
        history_entry = {"timestamp": ts, **status_summary}
        with open(history_path, "a") as f:
            f.write(json.dumps(history_entry) + "\n")
        _trim_history(history_path)

    _write_scan_status("done", "cities", 0, 0, "")


def refresh_movements(session, first_city_id):
    """Re-fetch movements.json after transport dispatch so arrival ETAs are visible."""
    time.sleep(random.randint(5, 10))
    movements = _collect_movements(session, first_city_id)
    with open(os.path.join(LOGS_DIR, "movements.json"), "w") as f:
        json.dump(movements, f, indent=4)
