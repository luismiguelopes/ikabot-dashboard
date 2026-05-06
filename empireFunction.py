#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import os
import random
import re
import json
from decimal import *

from ikabot.config import *
from ikabot.helpers.getJson import getCity, getIsland
from ikabot.helpers.gui import *
from ikabot.helpers.market import getGold
from ikabot.helpers.naval import *
from ikabot.helpers.pedirInfo import *
from ikabot.helpers.resources import *
from ikabot.helpers.varios import *

getcontext().prec = 30

import time

LOGS_DIR = "/tmp/ikalogs/"
QUEUE_JSON_PATH = os.path.join(LOGS_DIR, "building_queue.json")

def _parse_duration(value, default):
    """Converte string de duração (ex: '3h', '2d', '30m') ou segundos inteiros para segundos."""
    if value is None:
        return default
    value = str(value).strip().lower()
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(d|h|m|s)?', value)
    if not match:
        return default
    amount, unit = float(match.group(1)), match.group(2) or 's'
    multipliers = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}
    return int(amount * multipliers[unit])

UPDATE_INTERVAL = _parse_duration(os.getenv("EMPIRE_UPDATE_INTERVAL"), 3600)
# Maximum history lines kept in history.jsonl (~90 days at 1h interval)
MAX_HISTORY_LINES = 2160
BUILDING_COSTS_UPDATE_INTERVAL = _parse_duration(os.getenv("BUILDING_COSTS_UPDATE_INTERVAL"), 3 * 24 * 3600)
WORLD_SCAN_UPDATE_INTERVAL = _parse_duration(os.getenv("WORLD_SCAN_UPDATE_INTERVAL"), 7 * 24 * 3600)
WORLD_SCAN_RADIUS = int(os.getenv("WORLD_SCAN_RADIUS", 10))
LOG_LANG = os.getenv("LOG_LANG", "en")

_LM = {
    "own_cities_missing": {
        "en": "[world_scan] own_cities.json not found, waiting for next cycle...",
        "pt": "[world_scan] own_cities.json não encontrado, a aguardar próximo ciclo...",
    },
    "world_scan_start": {
        "en": "[{ts}] World scan started (radius={radius})...",
        "pt": "[{ts}] World scan iniciado (raio={radius})...",
    },
    "scan_status_shallow": {
        "en": "Scanning map...",
        "pt": "A escanear mapa...",
    },
    "scan_status_quadrant": {
        "en": "Map ({x_min}-{x_max},{y_min}-{y_max})...",
        "pt": "Mapa ({x_min}-{x_max},{y_min}-{y_max})...",
    },
    "scan_islands_count": {
        "en": "[world_scan] {n} islands to scan within radius {radius}...",
        "pt": "[world_scan] {n} ilhas a escanear no raio {radius}...",
    },
    "scan_status_deep": {
        "en": "Scanning {n} islands...",
        "pt": "A escanear {n} ilhas...",
    },
    "scan_island_pause": {
        "en": "      -> Pause {pause}s | Island {i}/{total} ({x},{y})...",
        "pt": "      -> Pausa {pause}s | Ilha {i}/{total} ({x},{y})...",
    },
    "scan_island_done": {
        "en": "      Island {i}/{total} ({x},{y}) processed",
        "pt": "      Ilha {i}/{total} ({x},{y}) processada",
    },
    "scan_island_error": {
        "en": "      -> Error on island {id}: {err}",
        "pt": "      -> Erro na ilha {id}: {err}",
    },
    "scan_status_done": {
        "en": "Done: {n} inactive/vacation players found",
        "pt": "Concluído: {n} inactivos/férias encontrados",
    },
    "scan_done": {
        "en": "[world_scan] Done: {n} inactive/vacation players found.",
        "pt": "[world_scan] Concluído: {n} inactivos/férias encontrados.",
    },
    "scan_error": {
        "en": "World scan error:",
        "pt": "Erro no world scan:",
    },
    "scan_status_error": {
        "en": "Error during scan",
        "pt": "Erro durante o scan",
    },
    "costs_start": {
        "en": "[{ts}] Starting building cost extraction (human mode)...",
        "pt": "[{ts}] A iniciar extração de custos de edificios (modo humano)...",
    },
    "costs_city_pause": {
        "en": "      -> Pause {pause}s before next city...",
        "pt": "      -> Pausa de {pause}s antes de próxima cidade...",
    },
    "costs_city_start": {
        "en": "      -> Costs: {city}...",
        "pt": "      -> Custos: {city}...",
    },
    "costs_city_done": {
        "en": "      -> Success: {city} — {n} buildings with costs extracted.",
        "pt": "      -> Sucesso: {city} — {n} edificios com custos extraídos.",
    },
    "costs_city_error": {
        "en": "      -> Error extracting costs for city {id}:",
        "pt": "      -> Erro ao extrair custos de cidade {id}:",
    },
    "costs_done": {
        "en": "[{ts}] Building cost extraction done!",
        "pt": "[{ts}] Extração de custos de edificios concluída!",
    },
    "costs_error": {
        "en": "Error in cost extraction:",
        "pt": "Erro na extração de custos:",
    },
    "movements_error": {
        "en": "      -> Warning: could not collect movements:",
        "pt": "      -> Aviso: não foi possível recolher movimentos:",
    },
    "empire_start_1": {
        "en": "\n[+] Empire Function started in background!",
        "pt": "\n[+] Empire Function arrancada em Segundo Plano!",
    },
    "empire_start_2": {
        "en": "[+] Silently collecting empire data every {interval} seconds...\n",
        "pt": "[+] Extrai dados do império silenciosamente a cada {interval} segundos...\n",
    },
    "cycle_start": {
        "en": "[{ts}] Updating empire JSON files...",
        "pt": "[{ts}] A atualizar ficheiros JSON do Imperio...",
    },
    "city_done": {
        "en": "      -> Success: City {city} extracted.",
        "pt": "      -> Sucesso: Cidade {city} extraída.",
    },
    "cycle_done": {
        "en": "[+] Update cycle completed successfully!",
        "pt": "[+] Ciclo de atualização Terminado com sucesso!",
    },
    "cycle_error": {
        "en": "Error during data extraction:",
        "pt": "Erro durante extracção de dados:",
    },
    "queue_cycle_start": {
        "en": "[{ts}] Processing building queue...",
        "pt": "[{ts}] A processar fila de construção...",
    },
    "queue_city_not_found": {
        "en": "      -> Queue: city '{city}' not found in session, skipping.",
        "pt": "      -> Fila: cidade '{city}' não encontrada na sessão, a ignorar.",
    },
    "queue_building_not_found": {
        "en": "      -> Queue [{city}]: building '{building}' not found, removing from queue.",
        "pt": "      -> Fila [{city}]: edifício '{building}' não encontrado, a remover da fila.",
    },
    "queue_max_level": {
        "en": "      -> Queue [{city}]: {building} already at max level, removing from queue.",
        "pt": "      -> Fila [{city}]: {building} já está no nível máximo, a remover da fila.",
    },
    "queue_target_reached": {
        "en": "      -> Queue [{city}]: {building} reached target level {level}, removing from queue.",
        "pt": "      -> Fila [{city}]: {building} atingiu nível alvo {level}, a remover da fila.",
    },
    "queue_no_resources": {
        "en": "      -> Queue [{city}]: {building} — insufficient resources, will retry next cycle.",
        "pt": "      -> Fila [{city}]: {building} — recursos insuficientes, tenta no próximo ciclo.",
    },
    "queue_city_busy": {
        "en": "      -> Queue [{city}]: construction already in progress, skipping.",
        "pt": "      -> Fila [{city}]: construção já em curso, a saltar.",
    },
    "queue_started": {
        "en": "      -> Queue [{city}]: started {building} {from_lv} → {to_lv}.",
        "pt": "      -> Fila [{city}]: iniciada construção {building} {from_lv} → {to_lv}.",
    },
    "queue_start_failed": {
        "en": "      -> Queue [{city}]: failed to start {building} (server rejected).",
        "pt": "      -> Fila [{city}]: falhou ao iniciar {building} (servidor recusou).",
    },
    "queue_construction_done": {
        "en": "      -> Queue [{city}]: {building} construction completed.",
        "pt": "      -> Fila [{city}]: construção de {building} concluída.",
    },
    "queue_no_citizens": {
        "en": "      -> Queue [{city}]: {building} — no free citizens, will retry next cycle.",
        "pt": "      -> Fila [{city}]: {building} — sem cidadãos livres, tenta no próximo ciclo.",
    },
    "queue_attempting": {
        "en": "      -> Queue [{city}]: attempting {building} lv{lv} (type={btype}, pos={pos}, canUpgrade={can}, citizens={cit})",
        "pt": "      -> Fila [{city}]: a tentar {building} lv{lv} (tipo={btype}, pos={pos}, canUpgrade={can}, cidadãos={cit})",
    },
    "queue_post_resp": {
        "en": "      -> Queue [{city}]: POST response: {resp}",
        "pt": "      -> Fila [{city}]: resposta POST: {resp}",
    },
    "queue_done": {
        "en": "[+] Building queue cycle done.",
        "pt": "[+] Ciclo da fila de construção concluído.",
    },
    "queue_wake": {
        "en": "[{ts}] Queue wake-up: checking constructions...",
        "pt": "[{ts}] Acordei para a fila de construção: a verificar construções...",
    },
    "queue_sleep_until": {
        "en": "      -> Next construction ETA: {eta}. Sleeping {mins} min.",
        "pt": "      -> Próxima construção prevista: {eta}. A dormir {mins} min.",
    },
    "cycle_sleep": {
        "en": "[+] Sleeping {mins} min until next empire cycle.",
        "pt": "[+] A dormir {mins} min até ao próximo ciclo do império.",
    },
}


def lm(key, **kwargs):
    """Return log message in current LOG_LANG (fallback to English)."""
    msg = _LM[key].get(LOG_LANG, _LM[key]["en"])
    return msg.format(**kwargs) if kwargs else msg


def _should_update_building_costs():
    flag = os.path.join(LOGS_DIR, ".force_costs_update")
    if os.path.exists(flag):
        os.remove(flag)
        return True
    costs_path = os.path.join(LOGS_DIR, "building_costs.json")
    if not os.path.exists(costs_path):
        return True
    return time.time() - os.path.getmtime(costs_path) > BUILDING_COSTS_UPDATE_INTERVAL


def _should_update_world_scan():
    flag = os.path.join(LOGS_DIR, ".force_world_scan")
    if os.path.exists(flag):
        os.remove(flag)
        return True
    scan_path = os.path.join(LOGS_DIR, "world_scan.json")
    if not os.path.exists(scan_path):
        return True
    return time.time() - os.path.getmtime(scan_path) > WORLD_SCAN_UPDATE_INTERVAL


def _write_scan_status(status, phase, progress, total, message):
    path = os.path.join(LOGS_DIR, "world_scan_status.json")
    with open(path, "w") as f:
        json.dump({
            "status": status,
            "phase": phase,
            "progress": progress,
            "total": total,
            "message": message,
            "updatedAt": int(time.time()),
        }, f)


def _dist(x1, y1, x2, y2):
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


# ── Building queue (Phase 1) ─────────────────────────────────────────────────

def _load_queue():
    if not os.path.exists(QUEUE_JSON_PATH):
        return {"queues": {}, "inProgress": {}}
    with open(QUEUE_JSON_PATH) as f:
        return json.load(f)


def _save_queue(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(QUEUE_JSON_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _has_building_queue():
    data = _load_queue()
    return any(len(items) > 0 for items in data.get("queues", {}).values())


def _get_next_construction_eta():
    """Return the earliest construction completion timestamp across all in-progress cities, or None."""
    data = _load_queue()
    etas = [
        entry["eta"]
        for entry in data.get("inProgress", {}).values()
        if entry.get("eta", 0) > time.time()
    ]
    return min(etas) if etas else None


def _smart_sleep(last_full_cycle_time, next_full_jitter):
    """Sleep until the next full empire cycle or the next construction ETA, whichever comes first."""
    next_full_at = last_full_cycle_time + UPDATE_INTERVAL + next_full_jitter
    eta = _get_next_construction_eta()

    if eta:
        # Wake up 3–8 min after construction ends to start the next level
        wake_for_queue = eta + random.randint(3, 8) * 60
        sleep_secs = max(60, min(next_full_at, wake_for_queue) - time.time())
        if wake_for_queue < next_full_at:
            eta_str = time.strftime('%H:%M:%S', time.localtime(eta))
            print(lm("queue_sleep_until", eta=eta_str, mins=round(sleep_secs / 60)))
    else:
        sleep_secs = max(60, next_full_at - time.time())

    print(lm("cycle_sleep", mins=round(sleep_secs / 60)))
    time.sleep(sleep_secs)


def _process_building_queue(session, ids, cities):
    print(lm("queue_cycle_start", ts=time.strftime('%H:%M:%S')))
    data = _load_queue()
    queues = data.get("queues", {})
    in_progress = data.get("inProgress", {})
    changed = False

    # Build city name → id map
    name_to_id = {cities[cid]["name"]: cid for cid in ids if cid in cities}

    first_city = True
    for city_name, items in list(queues.items()):
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
            # Use stored position index when available (more reliable than name when isBusy).
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
                # Advance queue: remove item if target level reached
                if items and items[0]["building"] == ip["building"]:
                    b_done = (city_data["position"][ip_pos]
                              if ip_pos is not None and ip_pos < len(city_data["position"])
                              else next((b for b in city_data["position"] if b["name"] == items[0]["building"]), None))
                    if b_done and b_done.get("level", 0) >= items[0]["targetLevel"]:
                        items.pop(0)
                del in_progress[city_name]
                changed = True

        if not items:
            continue

        # ── Skip if any construction is already running in this city ─────────
        if any(b.get("isBusy") for b in city_data["position"]):
            # Sync inProgress if we're not tracking it yet
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
        target_b = next((b for b in city_data["position"] if b["name"] == next_item["building"]), None)

        if target_b is None:
            print(lm("queue_building_not_found", city=city_name, building=next_item["building"]))
            items.pop(0)
            changed = True
            continue

        if target_b.get("isMaxLevel"):
            print(lm("queue_max_level", city=city_name, building=next_item["building"]))
            items.pop(0)
            changed = True
            continue

        if target_b["level"] >= next_item["targetLevel"]:
            print(lm("queue_target_reached", city=city_name, building=next_item["building"], level=next_item["targetLevel"]))
            items.pop(0)
            changed = True
            continue

        if target_b.get("canUpgrade") is False:
            print(lm("queue_no_resources", city=city_name, building=next_item["building"]))
            continue

        if city_data.get("freeCitizens", 1) == 0:
            print(lm("queue_no_citizens", city=city_name, building=next_item["building"]))
            continue

        # ── Fire the upgrade POST via expandBuilding (same path as constructionList) ──
        print(lm("queue_attempting", city=city_name, building=next_item["building"],
                  lv=target_b["level"], btype=target_b["building"], pos=target_b["position"],
                  can=target_b.get("canUpgrade"), cit=city_data.get("freeCitizens")))

        from ikabot.function.constructionList import expandBuilding as _expandBuilding
        target_for_expand = dict(target_b)
        target_for_expand["upgradeTo"] = target_b["level"] + 1
        _expandBuilding(session, city_id, target_for_expand, False)

        # ── Verify it started ─────────────────────────────────────────────────
        time.sleep(2)
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

    if changed:
        data["queues"] = queues
        data["inProgress"] = in_progress
        _save_queue(data)

    print(lm("queue_done"))


def _collect_world_scan(session):
    """Background thread: scan nearby islands for inactive/vacation players weekly."""
    try:
        own_cities_path = os.path.join(LOGS_DIR, "own_cities.json")
        if not os.path.exists(own_cities_path):
            print(lm("own_cities_missing"))
            return
        with open(own_cities_path) as f:
            own_cities = json.load(f)
        if not own_cities:
            return

        print(lm("world_scan_start", ts=time.strftime('%H:%M:%S'), radius=WORLD_SCAN_RADIUS))
        _write_scan_status("running", "shallow_scan", 0, 4, lm("scan_status_shallow"))

        # Phase 1: Shallow scan — 4 API calls covering the full 100x100 map
        shallow_islands = []
        quadrants = [
            ("0", "50", "0", "50"),
            ("50", "100", "0", "50"),
            ("0", "50", "50", "100"),
            ("50", "100", "50", "100"),
        ]
        for i, (x_min, x_max, y_min, y_max) in enumerate(quadrants):
            _write_scan_status("running", "shallow_scan", i + 1, 4,
                lm("scan_status_quadrant", x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max))
            data = session.post(
                f"action=WorldMap&function=getJSONArea&x_min={x_min}&x_max={x_max}&y_min={y_min}&y_max={y_max}"
            )
            for x, val in json.loads(data)["data"].items():
                for y, val2 in val.items():
                    shallow_islands.append({
                        "x": int(x), "y": int(y),
                        "id": val2[0], "name": val2[1],
                        "resource_type": val2[2],
                        "players": int(val2[7]),
                    })
            time.sleep(random.randint(2, 5))

        # Phase 2: Keep only non-empty islands within WORLD_SCAN_RADIUS of any own city
        seen_ids = set()
        islands_to_scan = []
        for island in shallow_islands:
            if not island["players"] or island["id"] in seen_ids:
                continue
            for city in own_cities:
                if _dist(island["x"], island["y"], city["x"], city["y"]) <= WORLD_SCAN_RADIUS:
                    seen_ids.add(island["id"])
                    islands_to_scan.append(island)
                    break

        print(lm("scan_islands_count", n=len(islands_to_scan), radius=WORLD_SCAN_RADIUS))
        _write_scan_status("running", "deep_scan", 0, len(islands_to_scan),
            lm("scan_status_deep", n=len(islands_to_scan)))

        # Phase 3: Deep scan — one getIsland request per filtered island
        inactive_players = []
        islands_summary = []
        for i, island in enumerate(islands_to_scan):
            pause = random.randint(15, 30)
            print(lm("scan_island_pause", pause=pause, i=i+1, total=len(islands_to_scan), x=island['x'], y=island['y']))
            time.sleep(pause)

            try:
                html = session.get("view=island&islandId=" + str(island["id"]))
                island_data = getIsland(html)

                nearest = min(own_cities,
                    key=lambda c: _dist(island["x"], island["y"], c["x"], c["y"]))
                nearest_dist = _dist(island["x"], island["y"], nearest["x"], nearest["y"])

                # ── Island summary (for colonisation tab) ──────────────────
                cities_list = island_data.get("cities", [])
                free_slots = sum(1 for c in cities_list if c.get("type") == "empty")
                islands_summary.append({
                    "islandId":       str(island["id"]),
                    "islandName":     island_data.get("name", island.get("name", "")),
                    "x":              island["x"],
                    "y":              island["y"],
                    "resourceType":   int(island["resource_type"]) if island.get("resource_type") else 0,
                    "woodLevel":      island_data.get("resourceLevel", ""),
                    "luxuryLevel":    island_data.get("tradegoodLevel", ""),
                    "wonder":         island_data.get("wonderName", ""),
                    "wonderLevel":    island_data.get("wonderLevel", ""),
                    "freeSlots":      free_slots,
                    "totalSlots":     len(cities_list),
                    "hasOwnCity":     bool(island_data.get("isOwnCityOnIsland", False)),
                    "nearestOwnCity": nearest["name"],
                    "distance":       round(nearest_dist, 1),
                })

                # ── Inactive / vacation players ────────────────────────────
                avatar_scores = island_data.get("avatarScores", {})
                for city_slot in cities_list:
                    if city_slot.get("type") == "empty":
                        continue
                    state = city_slot.get("state", "")
                    if state not in ("inactive", "vacation"):
                        continue
                    owner_name = city_slot.get("ownerName", "")
                    if not owner_name:
                        continue

                    owner_id = str(city_slot.get("ownerId", city_slot.get("Id", "")))
                    scores_raw = avatar_scores.get(owner_id, {})
                    inactive_players.append({
                        "playerId":       owner_id,
                        "playerName":     owner_name,
                        "allyTag":        city_slot.get("ownerAllyTag", city_slot.get("AllyTag", "")),
                        "state":          state,
                        "cityName":       city_slot.get("name", ""),
                        "islandName":     island_data.get("name", island.get("name", "")),
                        "islandX":        island["x"],
                        "islandY":        island["y"],
                        "nearestOwnCity": nearest["name"],
                        "distance":       round(nearest_dist, 1),
                        "scores": {
                            "building": scores_raw.get("building_score_main", "0"),
                            "research": scores_raw.get("research_score_main", "0"),
                            "army":     scores_raw.get("army_score_main", "0"),
                            "trader":   scores_raw.get("trader_score_secondary", "0"),
                            "rank":     scores_raw.get("place", ""),
                        },
                    })

                _write_scan_status("running", "deep_scan", i + 1, len(islands_to_scan),
                    lm("scan_island_done", i=i+1, total=len(islands_to_scan), x=island['x'], y=island['y']))

            except Exception as e:
                print(lm("scan_island_error", id=island['id'], err=e))
                continue

        # Backup previous scan before overwriting (used for new-inactive detection)
        scan_path = os.path.join(LOGS_DIR, "world_scan.json")
        if os.path.exists(scan_path):
            with open(scan_path, "rb") as src:
                with open(os.path.join(LOGS_DIR, "world_scan_prev.json"), "wb") as dst:
                    dst.write(src.read())

        result = {
            "lastUpdated": int(time.time()),
            "scanRadius":  WORLD_SCAN_RADIUS,
            "ownCities":   own_cities,
            "players":     inactive_players,
            "islands":     islands_summary,
        }
        with open(scan_path, "w") as f:
            json.dump(result, f, indent=2)

        _write_scan_status("idle", "done", len(islands_to_scan), len(islands_to_scan),
            lm("scan_status_done", n=len(inactive_players)))
        print(lm("scan_done", n=len(inactive_players)))

    except Exception:
        import traceback
        print(lm("scan_error"), traceback.format_exc())
        _write_scan_status("error", "error", 0, 0, lm("scan_status_error"))


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


def _collect_building_costs(session, ids):
    """Background thread: fetch upgrade costs for all non-max buildings every 3 days."""
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

                # 1 request per city: shared building detail HTML for all buildings
                detail_url = (
                    "view=buildingDetail&buildingId=0&helpId=1&backgroundView=city"
                    "&currentCityId={}&templateView=ikipedia&actionRequest={}&ajax=1"
                ).format(city["id"], actionRequest)
                building_html = json.loads(session.post(detail_url), strict=False)[1][1][1]

                # 1 request per city (cached in session after first): research reduction
                costs_reduction = _get_costs_reduction(session, city["id"])

                # From city data (no request): special building cost reducers
                costs_reductions = getCostsReducers(city)

                city_costs = {}
                for building in city["position"]:
                    if building["name"] == "empty" or building.get("isMaxLevel"):
                        continue

                    time.sleep(random.randint(5, 15))

                    current_level = building["level"]
                    if building.get("isBusy"):
                        current_level += 1

                    # Find this building's cost URL within the shared HTML
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

                    # Column headers identify which resource each cost column belongs to
                    resources_types = re.findall(
                        r'<th class="costs"><img src="(.*?)\.png"/></th>', html_costs
                    )[:-1]

                    # Parse every level row from the cost table
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
        print(lm("movements_error"), traceback.format_exc())
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

    print(lm("empire_start_1"))
    print(lm("empire_start_2", interval=UPDATE_INTERVAL))

    ids = None
    cities = None
    last_full_cycle_time = 0
    next_full_jitter = 0

    while True:
        try:
            now = time.time()
            do_full = ids is None or (now >= last_full_cycle_time + UPDATE_INTERVAL + next_full_jitter)

            # ── Queue-only wake-up ───────────────────────────────────────────
            if not do_full:
                if ids and _has_building_queue():
                    print(lm("queue_wake", ts=time.strftime('%H:%M:%S')))
                    _process_building_queue(session, ids, cities)
                _smart_sleep(last_full_cycle_time, next_full_jitter)
                continue

            # ── Full empire data cycle ───────────────────────────────────────
            print(lm("cycle_start", ts=time.strftime('%H:%M:%S')))
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
            own_cities_list = []

            for id in ids:
                time.sleep(random.randint(5, 15))

                html = session.get("view=city&cityId={}".format(id))
                city_data = getCity(html)

                time.sleep(random.randint(2, 6))
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
                island_x = int(city_data.get("islandXCoord", city_data.get("x", 0)) or 0)
                island_y = int(city_data.get("islandYCoord", city_data.get("y", 0)) or 0)
                own_cities_list.append({"name": city_name, "x": island_x, "y": island_y})
                print(lm("city_done", city=city_name))

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

            # ── Own cities coords (for world scan proximity filter) ──────────
            with open(os.path.join(LOGS_DIR, "own_cities.json"), "w") as f:
                json.dump(own_cities_list, f)

            # ── Building costs (sequential, every 3 days) ────────────────────
            if _should_update_building_costs():
                _collect_building_costs(session, ids)

            # ── World scan (sequential, every 7 days) ────────────────────────
            elif _should_update_world_scan():
                _collect_world_scan(session)

            # ── Ship movements ───────────────────────────────────────────────
            time.sleep(random.randint(5, 10))
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

            print(lm("cycle_done"))
            last_full_cycle_time = time.time()
            next_full_jitter = random.randint(-300, 300)

            # ── Building queue (after full cycle) ────────────────────────────
            if _has_building_queue():
                _process_building_queue(session, ids, cities)

            _smart_sleep(last_full_cycle_time, next_full_jitter)

        except Exception:
            import traceback
            print(lm("cycle_error"), traceback.format_exc())
            time.sleep(180)
