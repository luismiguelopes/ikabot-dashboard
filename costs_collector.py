#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import os
import random
import re
import sys
import time
from decimal import Decimal, getcontext

getcontext().prec = 30

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from empire_utils import LOGS_DIR, BUILDING_COSTS_UPDATE_INTERVAL, lm

from ikabot.config import materials_names_tec
from ikabot.helpers.getJson import getCity
from ikabot.helpers.varios import actionRequest


def should_update_building_costs():
    flag = os.path.join(LOGS_DIR, ".force_costs_update")
    if os.path.exists(flag):
        os.remove(flag)
        return True
    costs_path = os.path.join(LOGS_DIR, "building_costs.json")
    if not os.path.exists(costs_path):
        return True
    return time.time() - os.path.getmtime(costs_path) > BUILDING_COSTS_UPDATE_INTERVAL


def _get_costs_reduction(session, city_id):
    """Returns costs_reduction factor (1 - pct/100) as Decimal. Result cached in session."""
    sessionData = session.getSessionData()
    if "reduccion_inv_max" in sessionData:
        return Decimal("0.86")

    url = (
        "view=noViewChange&researchType=economy&backgroundView=city"
        "&currentCityId={}&templateView=researchAdvisor&actionRequest={}&ajax=1"
    ).format(city_id, actionRequest)
    rta = session.post(url)
    rta = json.loads(rta, strict=False)
    studies = json.loads(rta[2][1]["new_js_params"], strict=False)["currResearchType"]

    pct = 0
    for study in studies:
        if studies[study]["liClass"] != "explored":
            continue
        link = studies[study]["aHref"]
        if "2020" in link:
            pct += 2
        elif "2060" in link:
            pct += 4
        elif "2100" in link:
            pct += 8

    if pct == 14:
        sessionData["reduccion_inv_max"] = True
        session.setSessionData(sessionData)

    return Decimal(1) - Decimal(pct) / Decimal(100)


def collect_building_costs(session, ids):
    """Fetch upgrade costs for all non-max buildings. Runs every 3 days."""
    try:
        from ikabot.function.constructionList import getCostsReducers, checkhash

        print(lm("costs_start", ts=time.strftime('%H:%M:%S')))
        all_costs = {}

        for city_id in ids:
            pause = random.randint(15, 30)
            print(lm("costs_city_pause", pause=pause))
            time.sleep(pause)

            try:
                html = session.get("view=city&cityId={}".format(city_id))
                city = getCity(html)
                city_name = city.get("cityName", city.get("name", "Unknown"))
                print(lm("costs_city_start", city=city_name))

                detail_url = (
                    "view=buildingDetail&buildingId=0&helpId=1&backgroundView=city"
                    "&currentCityId={}&templateView=ikipedia&actionRequest={}&ajax=1"
                ).format(city["id"], actionRequest)
                building_html = json.loads(session.post(detail_url), strict=False)[1][1][1]

                costs_reduction = _get_costs_reduction(session, city["id"])
                costs_reductions = getCostsReducers(city)

                city_costs = {}
                for building in city["position"]:
                    if building["name"] == "empty" or building.get("isMaxLevel"):
                        continue

                    time.sleep(random.randint(5, 15))

                    current_level = building["level"]
                    if building.get("isBusy"):
                        current_level += 1

                    regex = (
                        r'<div class="(?:selected)? button_building '
                        + re.escape(building["building"])
                        + r'"\s*onmouseover="\$\(this\)\.addClass\(\'hover\'\);"'
                        r' onmouseout="\$\(this\)\.removeClass\(\'hover\'\);"\s*'
                        r'onclick="ajaxHandlerCall\(\'\?(.*?)\'\);'
                    )
                    match = re.search(regex, building_html)
                    if not match:
                        continue

                    cost_url = (
                        match.group(1)
                        + "backgroundView=city&currentCityId={}&templateView=buildingDetail&actionRequest={}&ajax=1".format(
                            city["id"], actionRequest
                        )
                    )

                    try:
                        html_costs = json.loads(session.post(cost_url), strict=False)[1][1][1]
                    except Exception:
                        continue

                    resources_types = re.findall(
                        r'<th class="costs"><img src="(.*?)\.png"/></th>', html_costs
                    )[:-1]

                    rows = re.findall(
                        r'<td class="level">\d+</td>(?:\s+<td class="costs">.*?</td>)+',
                        html_costs,
                    )

                    level_costs = {}
                    for row in rows:
                        lv = int(re.search(r'"level">(\d+)</td>', row).group(1))
                        if lv <= current_level:
                            continue

                        raw_costs = re.findall(
                            r'<td class="costs"><div.*>([\d,\.\s\xa0]*)</div></div></td>', row
                        )
                        raw_costs = [v.replace("\xa0", "").replace(" ", "") for v in raw_costs]

                        row_cost = {"wood": 0, "wine": 0, "marble": 0, "glass": 0, "sulfur": 0}
                        for i, raw in enumerate(raw_costs):
                            if i >= len(resources_types):
                                break
                            resource_type = checkhash("https:" + resources_types[i] + ".png")
                            val = raw.replace(",", "").replace(".", "")
                            val = 0 if val == "" else int(val)
                            if val == 0:
                                continue
                            for j, tec in enumerate(materials_names_tec):
                                if resource_type == tec:
                                    real = Decimal(val)
                                    original = real / costs_reduction
                                    real -= original * (Decimal(costs_reductions[j]) / Decimal(100))
                                    row_cost[tec] = math.ceil(real)
                                    break

                        level_costs[str(lv)] = row_cost

                    if level_costs:
                        city_costs[building["name"]] = {
                            "currentLevel": current_level,
                            "costs": level_costs,
                        }

                all_costs[city_name] = city_costs
                print(lm("costs_city_done", city=city_name, n=len(city_costs)))

            except Exception:
                import traceback
                print(lm("costs_city_error", id=city_id), traceback.format_exc())

        costs_path = os.path.join(LOGS_DIR, "building_costs.json")
        with open(costs_path, "w") as f:
            json.dump({"lastUpdated": int(time.time()), "cities": all_costs}, f, indent=4)

        print(lm("costs_done", ts=time.strftime('%H:%M:%S')))

    except Exception:
        import traceback
        print(lm("costs_error"), traceback.format_exc())
