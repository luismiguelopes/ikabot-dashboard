#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
from decimal import *

from ikabot.config import *
from ikabot.helpers.getJson import getCity
from ikabot.helpers.gui import *
from ikabot.helpers.market import getGold
from ikabot.helpers.naval import *
from ikabot.helpers.pedirInfo import *
from ikabot.helpers.resources import *
from ikabot.helpers.varios import *

getcontext().prec = 30

import time

LOGS_DIR = "/tmp/ikalogs/"
UPDATE_INTERVAL = int(os.getenv("EMPIRE_UPDATE_INTERVAL", 3600))
# Maximum history lines kept in history.jsonl (~90 days at 1h interval)
MAX_HISTORY_LINES = 2160


def _collect_movements(session, city_id):
    """Fetch military/fleet movements from the military advisor endpoint."""
    try:
        url = (
            "view=militaryAdvisor&oldView=city&oldBackgroundView=city"
            "&backgroundView=city&currentCityId={}&actionRequest={}&ajax=1".format(
                city_id, actionRequest
            )
        )
        resp = session.post(url)
        data = json.loads(resp, strict=False)
        movements_raw = data[1][1][2]["viewScriptParams"]["militaryAndFleetMovements"]
        time_now = int(data[0][1]["time"])

        movements = []
        for m in movements_raw:
            time_left = int(m["eventTime"]) - time_now
            arrival_ts = int(m["eventTime"])
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

            # Cargo details for non-hostile movements
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

            # Troop/fleet counts for hostile
            if entry["isHostile"] and "army" in m:
                entry["troops"] = m["army"].get("amount", 0)
                entry["fleets"] = m["fleet"].get("amount", 0)

            movements.append(entry)

        return movements
    except Exception:
        import traceback
        print("      -> Aviso: não foi possível recolher movimentos:", traceback.format_exc())
        return []


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


def empireFunction(session, event, stdin_fd, predetermined_input):
    """
    Parameters
    ----------
    session : ikabot.web.session.Session
    event : multiprocessing.Event
    stdin_fd: int
    predetermined_input : multiprocessing.managers.SyncManager.list
    """

    event.set()

    print("\n[+] Empire Function arrancada em Segundo Plano!")
    print("[+] Extrai dados do império silenciosamente a cada {} segundos...\n".format(UPDATE_INTERVAL))

    while True:
        try:
            print(f"[{time.strftime('%H:%M:%S')}] A atualizar ficheiros JSON do Imperio...")
            (ids, cities) = getIdsOfCities(session)

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

            for id in ids:
                time.sleep(7)

                html = session.get("view=city&cityId={}".format(id))
                city_data = getCity(html)

                data = session.get("view=updateGlobalData&ajax=1", noIndex=True)
                json_data = json.loads(data, strict=False)
                json_data = json_data[0][1]["headerData"]

                if json_data["relatedCity"]["owncity"] != 1:
                    continue

                wood = Decimal(json_data["resourceProduction"])
                good = Decimal(json_data["tradegoodProduction"])
                typeGood = int(json_data["producedTradegood"])
                total_production[0] += wood * 3600
                total_production[typeGood] += good * 3600
                total_wine_consumption += json_data["wineSpendings"]

                housing_space = int(json_data["currentResources"]["population"])
                citizens = int(json_data["currentResources"]["citizens"])
                total_housing_space += housing_space
                total_citizens += citizens

                total_resources[0] += json_data["currentResources"]["resource"]
                total_resources[1] += json_data["currentResources"]["1"]
                total_resources[2] += json_data["currentResources"]["2"]
                total_resources[3] += json_data["currentResources"]["3"]
                total_resources[4] += json_data["currentResources"]["4"]

                available_ships = json_data["freeTransporters"]
                total_ships = json_data["maxTransporters"]

                total_gold = int(Decimal(json_data["gold"]))
                total_gold_production = int(
                    Decimal(
                        json_data["scientistsUpkeep"]
                        + json_data["income"]
                        + json_data["upkeep"]
                    )
                )

                city_name = city_data.get("cityName", city_data.get("name", "Unknown"))
                print(f"      -> Sucesso: Cidade {city_name} extraída.")

                # ── Resources + extra city data ──────────────────────────────
                storage_capacity = int(city_data.get("storageCapacity", 0))
                wine_consumption_hr = int(city_data.get("wineConsumptionPerHour", 0))
                wine_production_hr = int(good * 3600) if typeGood == 1 else 0

                city_resources = {}
                for i, resource in enumerate(materials_names_english):
                    city_resources[resource] = city_data["availableResources"][i]

                # Storage fill % per resource (0–100)
                city_resources["storageCapacity"] = storage_capacity
                city_resources["wineConsumptionPerHour"] = wine_consumption_hr
                city_resources["wineProductionPerHour"] = wine_production_hr

                # Time until wine runs out (seconds); -1 = infinite (produces surplus)
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

                # ── Buildings + construction end time ────────────────────────
                city_buildings = {}
                construction_ends = int(city_data.get("endUpgradeTime", 0) or 0)

                if "position" in city_data:
                    for b in city_data["position"]:
                        if b["name"] != "empty":
                            building_names.add(b["name"])
                            level = str(b.get("level", ""))
                            if b.get("isBusy"):
                                level += "+"
                            city_buildings[b["name"]] = level

                city_buildings["_constructionEnds"] = construction_ends
                empire_data[city_name] = city_buildings

            # ── Global status ────────────────────────────────────────────────
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

            # ── empire.json: normalise building columns ───────────────────────
            formatted_empire = {}
            for city_name, buildings in empire_data.items():
                formatted_empire[city_name] = {"_constructionEnds": buildings.get("_constructionEnds", 0)}
                for bn in building_names:
                    formatted_empire[city_name][bn] = buildings.get(bn, "")

            # ── Ship movements ───────────────────────────────────────────────
            movements = _collect_movements(session, ids[0])

            # ── Write JSON files ─────────────────────────────────────────────
            if not os.path.exists(LOGS_DIR):
                os.makedirs(LOGS_DIR)

            with open(os.path.join(LOGS_DIR, "statusSummary.json"), "w") as f:
                json.dump(status_summary, f, indent=4)

            with open(os.path.join(LOGS_DIR, "empire.json"), "w") as f:
                json.dump(formatted_empire, f, indent=4)

            with open(os.path.join(LOGS_DIR, "resources.json"), "w") as f:
                json.dump(resources_data, f, indent=4)

            with open(os.path.join(LOGS_DIR, "movements.json"), "w") as f:
                json.dump(movements, f, indent=4)

            # ── Append to history.jsonl ──────────────────────────────────────
            history_path = os.path.join(LOGS_DIR, "history.jsonl")
            history_entry = {"timestamp": int(time.time()), **status_summary}
            with open(history_path, "a") as f:
                f.write(json.dumps(history_entry) + "\n")
            _trim_history(history_path)

            print("[+] Ciclo de atualização Terminado com sucesso!")
            time.sleep(UPDATE_INTERVAL)

        except Exception:
            import traceback
            print("Erro durante extracção de dados:", traceback.format_exc())
            time.sleep(180)
