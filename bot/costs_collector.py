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

from empire_utils import LOGS_DIR, BUILDING_COSTS_UPDATE_INTERVAL, lm, logger

from ikabot.config import materials_names_tec
from ikabot.helpers.getJson import getCity
from ikabot.config import actionRequest


def should_update_building_costs():
    flag = os.path.join(LOGS_DIR, ".force_costs_update")
    if os.path.exists(flag):
        os.remove(flag)
        return True
    try:
        from db_manager import costs_last_updated
        last_ts = costs_last_updated()
        if last_ts:
            return time.time() - last_ts > BUILDING_COSTS_UPDATE_INTERVAL
    except Exception:
        pass
    costs_path = os.path.join(LOGS_DIR, "building_costs.json")
    if not os.path.exists(costs_path):
        return True
    return time.time() - os.path.getmtime(costs_path) > BUILDING_COSTS_UPDATE_INTERVAL


def _get_costs_reduction(session, city_id):
    """Returns costs_reduction factor (1 - pct/100) as Decimal. Result cached in session."""
    sessionData = session.getSessionData()
    if "reduccion_inv_max" in sessionData:
        return Decimal("0.86")

    time.sleep(random.randint(2, 6))
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


def _levels_of(city):
    """{display name: (building type, level to price from)} for a city's upgradable buildings.
    A building under construction counts as already one level up. Several buildings with the
    same name (warehouses) share one entry at the LOWEST level, so every instance's next
    level is covered (the last one read used to win)."""
    out = {}
    for b in city.get("position", []):
        if b.get("name") == "empty" or b.get("isMaxLevel"):
            continue
        level = int(b["level"]) + (1 if b.get("isBusy") else 0)
        prev = out.get(b["name"])
        if prev is None or level < prev[1]:
            out[b["name"]] = (b["building"], level)
    return out


def _parse_cost_table(html_costs, icon_material):
    """{level: {material: amount}} from one building's cost page — the amounts as the game
    shows them (research discount applied, no city discount)."""
    icons = re.findall(r'<th class="costs"><img src="(.*?)\.png"/></th>', html_costs)[:-1]
    materials = [icon_material("https:" + i + ".png") for i in icons]
    rows = re.findall(r'<td class="level">\d+</td>(?:\s+<td class="costs">.*?</td>)+', html_costs)
    table = {}
    for row in rows:
        lv = int(re.search(r'"level">(\d+)</td>', row).group(1))
        raw = re.findall(r'<td class="costs"><div.*>([\d,\.\s\xa0]*)</div></div></td>', row)
        costs = {}
        for i, value in enumerate(raw):
            if i >= len(materials):
                break
            digits = re.sub(r"[^\d]", "", value)
            if digits and int(digits):
                costs[materials[i]] = int(digits)
        table[lv] = costs
    return table


def _city_costs_from_table(table, current_level, costs_reduction, city_reducers):
    """{str(level): {wood, wine, marble, glass, sulfur}} for the levels above current_level,
    with this city's reducer buildings applied on top of the table's amounts."""
    out = {}
    for lv, costs in table.items():
        if lv <= current_level:
            continue
        row = {"wood": 0, "wine": 0, "marble": 0, "glass": 0, "sulfur": 0}
        for j, tec in enumerate(materials_names_tec):
            val = costs.get(tec)
            if not val:
                continue
            real = Decimal(val)
            original = real / costs_reduction
            real -= original * (Decimal(city_reducers[j]) / Decimal(100))
            row[tec] = math.ceil(real)
        out[str(lv)] = row
    return out


def _fetch_cost_tables(session, city, types, state, icon_material):
    """Read the cost page of each building type in `types` with `city` as the current city.
    Returns {type: table}. The index page with the links is read for THIS city: the table
    the game returns is a window around the level the building has in the city the index was
    opened from (about 3 levels below to 46 above — seen live 2026-11-15), so an index from
    another city gives a window around the wrong level. state carries the research discount,
    which is the same for the whole run."""
    time.sleep(random.randint(15, 30))
    session.get("view=city&cityId={}".format(city["id"]))        # make it the current city
    time.sleep(random.randint(3, 8))
    detail_url = (
        "view=buildingDetail&buildingId=0&helpId=1&backgroundView=city"
        "&currentCityId={}&templateView=ikipedia&actionRequest={}&ajax=1"
    ).format(city["id"], actionRequest)
    index = json.loads(session.post(detail_url), strict=False)[1][1][1]
    if state.get("reduction") is None:
        state["reduction"] = _get_costs_reduction(session, city["id"])
    tables = {}
    for btype in types:
        regex = (
            r'<div class="(?:selected)? button_building '
            + re.escape(btype)
            + r'"\s*onmouseover="\$\(this\)\.addClass\(\'hover\'\);"'
            r' onmouseout="\$\(this\)\.removeClass\(\'hover\'\);"\s*'
            r'onclick="ajaxHandlerCall\(\'\?(.*?)\'\);'
        )
        match = re.search(regex, index)
        if not match:
            continue
        time.sleep(random.randint(5, 15))
        cost_url = (
            match.group(1)
            + "backgroundView=city&currentCityId={}&templateView=buildingDetail&actionRequest={}&ajax=1".format(
                city["id"], actionRequest)
        )
        try:
            html_costs = json.loads(session.post(cost_url), strict=False)[1][1][1]
            tables[btype] = _parse_cost_table(html_costs, icon_material)
        except Exception:
            logger.warning("[costs] tabela de custos de %s ilegível", btype, exc_info=True)
    return tables


def collect_building_costs(session, ids):
    """Fetch upgrade costs for all non-max buildings. Runs every 3 days.

    The amounts in the game's cost table belong to the building TYPE (checked live: 14,528
    values read this way matched the per-city ones, none differed): only the reducer buildings
    differ per city, and those are applied here. So each type is read once instead of once per
    building per city (~260 requests and 40+ minutes). The table is a window from about 3
    levels below the building to 46 above, so it is read from the city where the type is
    LOWEST — that window holds every city's next levels unless they are more than ~45 apart; a
    city whose next level is not on it gets a read of its own. A city that could not be read
    keeps its previous costs (the save used to wipe everything first)."""
    try:
        from ikabot.function.constructionList import getCostsReducers, checkhash

        logger.info(lm("costs_start", ts=time.strftime('%H:%M:%S')))
        icons = {}

        def icon_material(url):          # one image download per icon, not per table cell
            if url not in icons:
                icons[url] = checkhash(url)
            return icons[url]

        # 1. every city's buildings and levels
        cities, failed_ids = {}, []
        for city_id in random.sample(ids, len(ids)):
            pause = random.randint(15, 30)
            logger.debug(lm("costs_city_pause", pause=pause))
            time.sleep(pause)
            try:
                city = getCity(session.get("view=city&cityId={}".format(city_id)))
                cities[city_id] = city
                logger.debug(lm("costs_city_start", city=city.get("cityName", city.get("name", "?"))))
            except Exception:
                failed_ids.append(city_id)
                logger.error(lm("costs_city_error", id=city_id), exc_info=True)
        if not cities:
            logger.warning("[costs] nenhuma cidade lida — custos anteriores mantidos")
            return
        levels = {cid: _levels_of(c) for cid, c in cities.items()}

        # 2. each type once, from the city where it is lowest
        best = {}                                   # type → (level, city id)
        for cid, lv in levels.items():
            for btype, level in lv.values():
                if btype not in best or level < best[btype][0]:
                    best[btype] = (level, cid)
        by_city = {}
        for btype, (_lv, cid) in best.items():
            by_city.setdefault(cid, []).append(btype)
        state, tables = {}, {}
        for cid in sorted(by_city, key=lambda c: -len(by_city[c])):
            try:
                tables.update(_fetch_cost_tables(session, cities[cid], by_city[cid], state, icon_material))
            except Exception:
                logger.error(lm("costs_city_error", id=cid), exc_info=True)

        # 3. cities whose next level is not on the shared table read their own
        own_tables = {}
        for cid, lv in levels.items():
            missing = [btype for btype, level in lv.values()
                       if btype in tables and (level + 1) not in tables[btype]]
            if missing:
                try:
                    got = _fetch_cost_tables(session, cities[cid], missing, state, icon_material)
                    own_tables[cid] = got
                except Exception:
                    logger.error(lm("costs_city_error", id=cid), exc_info=True)

        # 4. apply each city's reducers
        all_costs = {}
        reduction = state.get("reduction") or Decimal(1)
        for cid, city in cities.items():
            city_name = city.get("cityName", city.get("name", "Unknown"))
            reducers = getCostsReducers(city)
            city_costs = {}
            for name, (btype, level) in levels[cid].items():
                table = own_tables.get(cid, {}).get(btype) or tables.get(btype)
                if not table:
                    continue
                level_costs = _city_costs_from_table(table, level, reduction, reducers)
                if level_costs:
                    city_costs[name] = {"currentLevel": level, "costs": level_costs}
            all_costs[city_name] = city_costs
            logger.debug(lm("costs_city_done", city=city_name, n=len(city_costs)))

        # 5. a city that could not be read (or got nothing) keeps what it had
        try:
            from db_manager import get_building_costs
            previous = get_building_costs().get("cities", {})
        except Exception:
            previous = {}
        for name, old in previous.items():
            if old and not all_costs.get(name) and (failed_ids or name in all_costs):
                all_costs[name] = old
                logger.warning("[costs] %s: custos não actualizados neste ciclo — mantidos os anteriores", name)

        costs_data = {"lastUpdated": int(time.time()), "cities": all_costs}
        from db_manager import save_building_costs
        save_building_costs(costs_data)

        logger.info(lm("costs_done", ts=time.strftime('%H:%M:%S')))

    except Exception:
        logger.error(lm("costs_error"), exc_info=True)
