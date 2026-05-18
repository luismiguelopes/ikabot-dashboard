#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import random
import time

from empire_utils import LOGS_DIR, logger

SPY_MISSIONS_PATH       = os.path.join(LOGS_DIR, "spy_missions.json")
SPY_DISPATCH_QUEUE_PATH = os.path.join(LOGS_DIR, "spy_dispatch_queue.json")
SPY_COUNTS_PATH         = os.path.join(LOGS_DIR, "spy_counts.json")
OWN_CITIES_PATH         = os.path.join(LOGS_DIR, "own_cities.json")


# ── Persistence helpers ───────────────────────────────────────────────────────

def _load_missions():
    try:
        with open(SPY_MISSIONS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"missions": []}


def _save_missions(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(SPY_MISSIONS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _load_dispatch_queue():
    try:
        with open(SPY_DISPATCH_QUEUE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"pending": []}


def _save_dispatch_queue(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(SPY_DISPATCH_QUEUE_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _load_spy_counts():
    try:
        with open(SPY_COUNTS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"lastUpdated": 0, "byCityId": {}}


def _save_spy_counts(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(SPY_COUNTS_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ── Safehouse HTML parsing ────────────────────────────────────────────────────

def _parse_safehouse_page(html, city_name):
    """
    Parse spy counts from the full safehouse page HTML (non-AJAX).
    Strips HTML tags first so regex works on clean text regardless of markup.
    Returns a dict with keys: available, inDefense, inTraining, deployed, trainable.
    """
    import re

    counts = {
        "available":  None,
        "inDefense":  None,
        "inTraining": None,
        "deployed":   None,
        "trainable":  None,
    }

    if not html:
        return counts

    # Strip tags and decode HTML entities for reliable matching
    text = re.sub(r'<[^>]+>', ' ', html)
    text = text.replace('&nbsp;', ' ').replace(' ', ' ')
    text = re.sub(r'\s+', ' ', text)

    # "24 estão em uso" → deployed on missions
    m = re.search(r'(\d+)\s+est[aã]o?\s+em\s+uso', text, re.IGNORECASE)
    if m:
        counts["deployed"] = int(m.group(1))

    # "15 estão a trabalhar na defesa" → defense assignment
    m = re.search(r'(\d+)\s+est[aã]o?\s+a\s+trabalhar\s+na\s+defesa', text, re.IGNORECASE)
    if m:
        counts["inDefense"] = int(m.group(1))

    # "1 esperam por treino" → agents in training queue
    m = re.search(r'(\d+)\s+esperam?\s+por\s+treino', text, re.IGNORECASE)
    if m:
        counts["inTraining"] = int(m.group(1))

    # "Podes treinar 40" → remaining capacity
    m = re.search(r'[Pp]odes\s+treinar\s+(\d+)', text, re.IGNORECASE)
    if m:
        counts["trainable"] = int(m.group(1))

    # "X disponíveis" → stationed agents (if shown directly)
    m = re.search(r'(\d+)\s+(?:espi[oõ]es?\s+)?dispon[ií]veis?', text, re.IGNORECASE)
    if m:
        counts["available"] = int(m.group(1))

    # derive available from known values when not shown directly:
    # available = total_trained - inDefense - deployed - inTraining
    # total_trained is not directly available; compute when all three are known
    if counts["available"] is None and None not in (
        counts["deployed"], counts["inDefense"], counts["inTraining"]
    ):
        # log relevant text to find total_trained pattern if needed later
        logger.debug("[espionage] %s: deployed=%s defense=%s training=%s — available desconhecido",
                     city_name, counts["deployed"], counts["inDefense"], counts["inTraining"])

    # log relevant text snippet when inDefense or deployed are still missing
    if counts["inDefense"] is None or counts["deployed"] is None:
        keywords = ("treino", "defesa", "uso", "dispon", "espião", "espioes", "agente")
        snippet = " | ".join(
            seg.strip() for seg in re.split(r'[.!?\n]', text)
            if any(kw in seg.lower() for kw in keywords)
        )[:500]
        logger.warning("[espionage] safehouse %s: faltam inDefense/deployed. Texto relevante: %s",
                       city_name, snippet or "(nenhum)")

    return counts


def _fetch_city_spy_counts(session, city_id, city_name, position):
    """
    GET the safehouse AJAX view and parse spy counts from the changeView HTML.
    The response changeView[1][1] contains the full safehouse HTML with all counters.
    Returns parsed counts dict, or None on error.
    """
    import ikabot.config as ikabot_config

    url = (
        f"view=safehouse&cityId={city_id}&position={position}"
        f"&backgroundView=city&currentCityId={city_id}"
        f"&actionRequest={ikabot_config.actionRequest}&ajax=1"
    )
    try:
        resp = session.get(url)
        resp_data = json.loads(resp, strict=False)
    except Exception as e:
        logger.error("[espionage] GET safehouse %s falhou: %s", city_name, e)
        return None

    # Refresh CSRF token
    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "updateGlobalData":
            tok = entry[1].get("actionRequest") if isinstance(entry[1], dict) else None
            if tok:
                ikabot_config.actionRequest = tok
            break

    # changeView[1][1] contains the full safehouse building HTML with spy stats
    html_content = ""
    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "changeView":
            inner = entry[1]
            if isinstance(inner, list) and len(inner) > 1 and isinstance(inner[1], str):
                html_content = inner[1]
            break

    if not html_content:
        logger.warning("[espionage] safehouse %s: sem HTML no changeView (tipos: %s)",
                       city_name, [e[0] if isinstance(e, list) else e for e in resp_data[:6]])
        return None

    counts = _parse_safehouse_page(html_content, city_name)
    counts["cityName"] = city_name
    return counts


# ── Public: fetch spy counts for all cities ───────────────────────────────────

def fetch_spy_counts(session):
    """
    Fetch spy counts from the safehouse view for every city that has a safehouse.
    Reads safehouse position from own_cities.json (written by empire_collector).
    Saves results to spy_counts.json.
    """
    try:
        with open(OWN_CITIES_PATH) as f:
            cities = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("[espionage] own_cities.json não encontrado — a saltar fetch_spy_counts")
        return

    results = {}
    first = True
    for city in cities:
        city_id   = str(city.get("cityId", ""))
        city_name = city.get("name", "")
        position  = city.get("safehousePosition")

        if position is None:
            logger.info("[espionage] %s sem posição de espionagem — a saltar", city_name)
            continue

        if not first:
            delay = random.randint(5, 15)
            logger.info("[espionage] aguardar %ds antes de consultar safehouse de %s", delay, city_name)
            time.sleep(delay)
        else:
            time.sleep(random.randint(3, 8))
        first = False

        counts = _fetch_city_spy_counts(session, city_id, city_name, position)
        if counts is None:
            counts = {"cityName": city_name, "available": None, "inDefense": None,
                      "inTraining": None, "deployed": None, "trainable": None}
        logger.info("[espionage] safehouse %s: %s", city_name,
                    {k: v for k, v in counts.items() if k != "cityName"})
        results[city_id] = counts

    data = {"lastUpdated": int(time.time()), "byCityId": results}
    _save_spy_counts(data)
    logger.info("[espionage] spy_counts.json atualizado para %d cidade(s)", len(results))


# ── In-field count (fallback when spy_counts.json is stale) ──────────────────

def count_in_field_by_city():
    """Return {city_id_str: num_agents} for all TRAVELING missions."""
    data = _load_missions()
    counts: dict[str, int] = {}
    for m in data.get("missions", []):
        if m.get("state") == "TRAVELING":
            cid = str(m.get("originCityId", ""))
            counts[cid] = counts.get(cid, 0) + m.get("numAgents", 0)
    return counts


# ── Public API ────────────────────────────────────────────────────────────────

def get_missions():
    return _load_missions()


def get_spy_counts():
    return _load_spy_counts()


def has_pending_dispatch():
    """Return True if Flask queued at least one spy dispatch."""
    try:
        return bool(_load_dispatch_queue().get("pending"))
    except Exception:
        return False


def process_dispatch_queue(session):
    """
    Called from smart_sleep. Dispatches all pending spy missions.
    Does a safehouse pre-check (if position data is available) to verify
    there are enough agents before sending.
    """
    q = _load_dispatch_queue()
    pending = q.get("pending", [])
    if not pending:
        return

    # Load cached spy counts for pre-check
    spy_data = _load_spy_counts().get("byCityId", {})

    for i, item in enumerate(pending):
        if i > 0:
            delay = random.randint(15, 35)
            logger.info("[espionage] aguardar %ds antes do próximo dispatch", delay)
            time.sleep(delay)

        origin_id  = str(item["originCityId"])
        num_agents = int(item.get("numAgents", 1))

        # Pre-check: inDefense = agents stationed at city, available for dispatch
        city_counts = spy_data.get(origin_id, {})
        available   = city_counts.get("inDefense")
        if available is not None and available < num_agents:
            error = f"Espiões insuficientes: {available} em defesa, {num_agents} pedidos"
            logger.warning("[espionage] pre-check falhou para %s: %s",
                           item["targetPlayerName"], error)
            _append_failed_mission(item, error)
            continue

        ok, result = _dispatch_spy(
            session,
            origin_city_id=origin_id,
            target_city_id=item["targetCityId"],
            target_island_id=item["islandId"],
            target_player_name=item["targetPlayerName"],
            target_city_name=item["targetCityName"],
            island_x=item["islandX"],
            island_y=item["islandY"],
            num_agents=num_agents,
            num_decoys=item.get("numDecoys", 0),
        )
        if not ok:
            _append_failed_mission(item, result)
            logger.warning("[espionage] dispatch falhou → guardado como FAILED para %s: %s",
                           item["targetPlayerName"], result)

    q["pending"] = []
    _save_dispatch_queue(q)


def _append_failed_mission(item, error):
    failed = {
        "originCityId":     str(item["originCityId"]),
        "targetCityId":     str(item["targetCityId"]),
        "targetIslandId":   str(item["islandId"]),
        "targetPlayerName": item["targetPlayerName"],
        "targetCityName":   item["targetCityName"],
        "islandX":          item["islandX"],
        "islandY":          item["islandY"],
        "numAgents":        item.get("numAgents", 1),
        "state":            "FAILED",
        "error":            error,
        "dispatchedAt":     int(time.time()),
        "arrivedAt":        None,
        "executeAfter":     None,
        "missionType":      None,
        "result":           None,
    }
    data = _load_missions()
    data["missions"].append(failed)
    _save_missions(data)


def _dispatch_spy(session, origin_city_id, target_city_id, target_island_id,
                  target_player_name, target_city_name, island_x, island_y,
                  num_agents=1, num_decoys=0):
    """
    Dispatch spies from origin_city_id to target_city_id.
    Returns (True, mission_dict) on success, (False, error_str) on failure.
    """
    import ikabot.config as ikabot_config

    params = {
        "action": "Espionage",
        "function": "sendSpy",
        "tab": "tabSafehouse",
        "destinationCityId": target_city_id,
        "cityId": target_island_id,
        "islandId": target_island_id,
        "backgroundView": "island",
        "currentIslandId": target_island_id,
        "templateView": "sendSpy",
        "actionRequest": ikabot_config.actionRequest,
        "ajax": 1,
        f"spies[{origin_city_id}][agents]": num_agents,
        f"spies[{origin_city_id}][decoys]": num_decoys,
    }

    try:
        resp = session.post(params=params)
        resp_data = json.loads(resp, strict=False)

        # Refresh CSRF token from response
        for entry in resp_data:
            if isinstance(entry, list) and entry[0] == "updateGlobalData":
                new_token = entry[1].get("actionRequest") if isinstance(entry[1], dict) else None
                if new_token:
                    ikabot_config.actionRequest = new_token
                break

        success = False
        for entry in resp_data:
            if isinstance(entry, list) and entry[0] == "provideFeedback":
                feedback = entry[1]
                if isinstance(feedback, list):
                    for fb in feedback:
                        if isinstance(fb, dict) and fb.get("type") == 10:
                            success = True
                            break
        if not success:
            logger.warning("[espionage] dispatch falhou — raw: %s", resp[:300])
            return False, "Servidor rejeitou o dispatch (sem type=10)"
    except Exception as e:
        logger.error("[espionage] dispatch exception: %s", e)
        return False, str(e)

    mission = {
        "originCityId":     str(origin_city_id),
        "targetCityId":     str(target_city_id),
        "targetIslandId":   str(target_island_id),
        "targetPlayerName": target_player_name,
        "targetCityName":   target_city_name,
        "islandX":          island_x,
        "islandY":          island_y,
        "numAgents":        num_agents,
        "state":            "TRAVELING",
        "dispatchedAt":     int(time.time()),
        "arrivedAt":        None,
        "executeAfter":     None,
        "missionType":      None,
        "result":           None,
    }

    data = _load_missions()
    data["missions"].append(mission)
    _save_missions(data)

    logger.info("[espionage] %d espião(s) despachado(s) → %s (%s)",
                num_agents, target_player_name, target_city_name)
    return True, mission
