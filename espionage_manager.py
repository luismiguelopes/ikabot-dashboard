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

MISSION_WAREHOUSE = 5
MISSION_GARRISON  = 6


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

    safehouse_pos = None
    try:
        with open(OWN_CITIES_PATH) as f:
            _cities = json.load(f)
        for _c in _cities:
            if str(_c.get("cityId")) == str(origin_city_id):
                safehouse_pos = _c.get("safehousePosition")
                break
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    mission = {
        "originCityId":      str(origin_city_id),
        "targetCityId":      str(target_city_id),
        "targetIslandId":    str(target_island_id),
        "targetPlayerName":  target_player_name,
        "targetCityName":    target_city_name,
        "islandX":           island_x,
        "islandY":           island_y,
        "numAgents":         num_agents,
        "state":             "TRAVELING",
        "safehousePosition": safehouse_pos,
        "spySessionId":      None,
        "dispatchedAt":      int(time.time()),
        "arrivedAt":         None,
        "executeAfter":      None,
        "executedAt":        None,
        "missionType":       None,
        "result":            None,
    }

    data = _load_missions()
    data["missions"].append(mission)
    _save_missions(data)

    logger.info("[espionage] %d espião(s) despachado(s) → %s (%s)",
                num_agents, target_player_name, target_city_name)
    return True, mission


# ── Phase 2: spy state machine helpers ───────────────────────────────────────

def _get_city_safehouse_position(city_id):
    try:
        with open(OWN_CITIES_PATH) as f:
            cities = json.load(f)
        for c in cities:
            if str(c.get("cityId")) == str(city_id):
                return c.get("safehousePosition")
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def _fetch_spy_missions_view(session, origin_city_id, target_city_id, position):
    """
    GET view=spyMissions for origin→target.
    Returns (spy_count, html) where spy_count = agents from origin waiting at target.
    Returns (None, None) on error.
    """
    import ikabot.config as ikabot_config
    url = (
        f"view=spyMissions&targetCityId={target_city_id}&position={position}"
        f"&activeTab=tabSafehouse&backgroundView=city&currentCityId={origin_city_id}"
        f"&templateView=safehouse&actionRequest={ikabot_config.actionRequest}&ajax=1"
    )
    try:
        resp = session.get(url)
        resp_data = json.loads(resp, strict=False)
    except Exception as e:
        logger.error("[espionage] GET spyMissions %s→%s falhou: %s", origin_city_id, target_city_id, e)
        return None, None

    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "updateGlobalData":
            tok = entry[1].get("actionRequest") if isinstance(entry[1], dict) else None
            if tok:
                ikabot_config.actionRequest = tok
            break

    html = ""
    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "changeView":
            inner = entry[1]
            if isinstance(inner, list) and len(inner) > 1 and isinstance(inner[1], str):
                html = inner[1]
            break

    spy_count = 0
    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "updateTemplateData":
            td = entry[1]
            if isinstance(td, dict):
                val = td.get(f"js_spyCount_{origin_city_id}")
                if val is not None:
                    try:
                        spy_count = int(str(val))
                    except (ValueError, TypeError):
                        pass
            break

    return spy_count, html


def _parse_spy_session_id(html):
    """Try multiple patterns to extract the spy session ID from spyMissions HTML."""
    import re
    if not html:
        return None
    for pat in [
        r'name=["\']spy["\']\s+value=["\'](\d+)["\']',
        r'value=["\'](\d+)["\']\s+name=["\']spy["\']',
        r'"spy"\s*:\s*(\d+)',
        r"'spy'\s*:\s*(\d+)",
        r'\bspy\b\s*=\s*(\d+)',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _execute_spy_mission(session, origin_city_id, target_city_id, position,
                         spy_session_id, num_agents, mission_type, num_decoys=0):
    """POST executeMission. Returns True on success (provideFeedback type=10)."""
    import ikabot.config as ikabot_config
    params = {
        "action":           "Espionage",
        "function":         "executeMission",
        "tab":              "tabSafehouse",
        "targetCity":       target_city_id,
        "cityId":           origin_city_id,
        "islandId":         origin_city_id,
        "mission":          mission_type,
        f"spies[{origin_city_id}][agents]":  num_agents,
        f"spies[{origin_city_id}][decoys]":  num_decoys,
        "payCityId":        origin_city_id,
        "position":         position,
        "targetCityId":     target_city_id,
        "activeTab":        "tabSafehouse",
        "backgroundView":   "city",
        "currentCityId":    origin_city_id,
        "templateView":     "spyMissions",
        "actionRequest":    ikabot_config.actionRequest,
        "ajax":             1,
    }
    if spy_session_id:
        params["spy"] = spy_session_id

    try:
        resp = session.post(params=params)
        resp_data = json.loads(resp, strict=False)

        for entry in resp_data:
            if isinstance(entry, list) and entry[0] == "updateGlobalData":
                tok = entry[1].get("actionRequest") if isinstance(entry[1], dict) else None
                if tok:
                    ikabot_config.actionRequest = tok
                break

        for entry in resp_data:
            if isinstance(entry, list) and entry[0] == "provideFeedback":
                feedback = entry[1]
                if isinstance(feedback, list):
                    for fb in feedback:
                        if isinstance(fb, dict) and fb.get("type") == 10:
                            return True
        logger.warning("[espionage] executeMission tipo=%d sem type=10 — raw: %s",
                       mission_type, resp[:300])
        return False
    except Exception as e:
        logger.error("[espionage] executeMission exception: %s", e)
        return False


def _fetch_report_ids(session, origin_city_id, position):
    """GET safehouse reports tab. Returns list of report ID strings (newest first)."""
    import re
    import ikabot.config as ikabot_config
    url = (
        f"view=safehouse&activeTab=tabReports&cityId={origin_city_id}&position={position}"
        f"&backgroundView=city&currentCityId={origin_city_id}"
        f"&templateView=safehouse&actionRequest={ikabot_config.actionRequest}&ajax=1"
    )
    try:
        resp = session.get(url)
        resp_data = json.loads(resp, strict=False)
    except Exception as e:
        logger.error("[espionage] GET reports tab falhou: %s", e)
        return []

    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "updateGlobalData":
            tok = entry[1].get("actionRequest") if isinstance(entry[1], dict) else None
            if tok:
                ikabot_config.actionRequest = tok
            break

    ids = []
    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "updateTemplateData":
            td = entry[1]
            if isinstance(td, dict):
                for key in td:
                    m = re.match(r'^js_available_(\d+)$', key)
                    if m:
                        ids.append(m.group(1))
            break
    # Higher IDs are newer reports
    ids.sort(key=lambda x: int(x), reverse=True)
    return ids


def _parse_report_html(html, report_id):
    """Parse spy report HTML. Returns {reportId, success, targetCityName, resources}."""
    import re

    text = re.sub(r'<[^>]+>', ' ', html)
    text = text.replace('&nbsp;', ' ').replace(' ', ' ')
    text = re.sub(r'\s+', ' ', text).strip()

    success = bool(re.search(r'completada com sucesso|completed successfully', text, re.IGNORECASE))

    target_city = None
    m = re.search(r'Recursos\s+em\s+([\w\s\-\']+)\s+Miss', text, re.IGNORECASE)
    if m:
        target_city = m.group(1).strip()

    resources = {}
    for pat, key in [
        (r'Material\s+de\s+constru[çc][aã]o\s+([\d.,]+)', 'wood'),
        (r'Vinho\s+([\d.,]+)', 'wine'),
        (r'M[aá]rmore\s+([\d.,]+)', 'marble'),
        (r'Cristal\s+([\d.,]+)', 'crystal'),
        (r'Enxofre\s+([\d.,]+)', 'sulfur'),
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).replace('.', '').replace(',', '')
            try:
                resources[key] = int(val)
            except ValueError:
                pass

    return {
        "reportId":       report_id,
        "success":        success,
        "targetCityName": target_city,
        "resources":      resources if resources else None,
        "reportedAt":     int(time.time()),
    }


def _fetch_and_parse_report(session, report_id):
    """GET markReportAsRead for a report, parse HTML, return result dict or None."""
    import ikabot.config as ikabot_config
    url = (
        f"action=Espionage&function=markReportAsRead&id={report_id}"
        f"&actionRequest={ikabot_config.actionRequest}&ajax=1"
    )
    try:
        resp = session.get(url)
        resp_data = json.loads(resp, strict=False)
    except Exception as e:
        logger.error("[espionage] markReportAsRead %s falhou: %s", report_id, e)
        return None

    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "updateGlobalData":
            tok = entry[1].get("actionRequest") if isinstance(entry[1], dict) else None
            if tok:
                ikabot_config.actionRequest = tok
            break

    html = ""
    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "changeView":
            inner = entry[1]
            if isinstance(inner, list) and len(inner) > 1 and isinstance(inner[1], str):
                html = inner[1]
            break

    return _parse_report_html(html, report_id) if html else None


# ── Phase 2: public state machine functions ───────────────────────────────────

def check_spy_arrivals(session):
    """TRAVELING → WAITING_AT_CITY for missions whose spy has arrived at target."""
    data = _load_missions()
    missions = data.get("missions", [])
    changed = False

    for i, m in enumerate(missions):
        if m.get("state") != "TRAVELING":
            continue
        if time.time() - m.get("dispatchedAt", 0) < 1200:  # min 20 min
            continue

        origin_id = str(m["originCityId"])
        position = m.get("safehousePosition") or _get_city_safehouse_position(origin_id)
        if not position:
            continue

        time.sleep(random.randint(5, 15))
        spy_count, html = _fetch_spy_missions_view(session, origin_id, m["targetCityId"], position)

        if spy_count is None:
            continue

        if spy_count > 0:
            spy_id = _parse_spy_session_id(html)
            missions[i]["state"] = "WAITING_AT_CITY"
            missions[i]["arrivedAt"] = int(time.time())
            missions[i]["safehousePosition"] = position
            missions[i]["spySessionId"] = spy_id
            missions[i]["executeAfter"] = int(time.time()) + random.randint(10, 45) * 60
            logger.info("[espionage] espiões chegaram a %s (spy_id=%s) — executar em %dmin",
                        m["targetCityName"], spy_id,
                        (missions[i]["executeAfter"] - int(time.time())) // 60)
            changed = True
        elif time.time() - m.get("dispatchedAt", 0) > 43200:  # 12h no arrival → failed
            missions[i]["state"] = "FAILED"
            missions[i]["error"] = "Sem chegada detectada após 12h — possivelmente capturado"
            logger.warning("[espionage] %s: sem chegada após 12h → FAILED", m["targetCityName"])
            changed = True

    if changed:
        data["missions"] = missions
        _save_missions(data)


def execute_waiting_missions(session):
    """WAITING_AT_CITY → EXECUTING: execute warehouse inspection after executeAfter."""
    data = _load_missions()
    missions = data.get("missions", [])
    changed = False
    now = int(time.time())

    for i, m in enumerate(missions):
        if m.get("state") != "WAITING_AT_CITY":
            continue
        if now < m.get("executeAfter", now + 1):
            continue

        origin_id = str(m["originCityId"])
        position = m.get("safehousePosition") or _get_city_safehouse_position(origin_id)
        if not position:
            continue

        time.sleep(random.randint(10, 25))
        spy_count, html = _fetch_spy_missions_view(session, origin_id, m["targetCityId"], position)

        if not spy_count:
            missions[i]["state"] = "FAILED"
            missions[i]["error"] = "Espião não encontrado ao tentar executar — possivelmente detectado"
            logger.warning("[espionage] %s: espião desapareceu → FAILED", m["targetCityName"])
            changed = True
            continue

        spy_id = _parse_spy_session_id(html) or m.get("spySessionId")

        time.sleep(random.randint(5, 15))
        ok = _execute_spy_mission(
            session, origin_id, m["targetCityId"], position,
            spy_id, m.get("numAgents", 1), MISSION_WAREHOUSE,
        )

        if ok:
            missions[i]["state"] = "EXECUTING"
            missions[i]["executedAt"] = now
            missions[i]["missionType"] = "warehouse"
            missions[i]["spySessionId"] = spy_id
            logger.info("[espionage] missão armazém executada → %s", m["targetCityName"])
        else:
            missions[i]["state"] = "FAILED"
            missions[i]["error"] = "executeMission rejeitado pelo servidor"
        changed = True

    if changed:
        data["missions"] = missions
        _save_missions(data)


def collect_mission_results(session):
    """EXECUTING → DONE/FAILED: fetch and parse reports from safehouse reports tab."""
    data = _load_missions()
    missions = data.get("missions", [])
    changed = False
    now = int(time.time())

    for i, m in enumerate(missions):
        if m.get("state") != "EXECUTING":
            continue
        if now - m.get("executedAt", 0) < 300:  # wait 5 min after execution
            continue

        origin_id = str(m["originCityId"])
        position = m.get("safehousePosition") or _get_city_safehouse_position(origin_id)
        if not position:
            continue

        time.sleep(random.randint(5, 15))
        report_ids = _fetch_report_ids(session, origin_id, position)

        matched = False
        for rid in report_ids[:5]:
            time.sleep(random.randint(3, 8))
            report = _fetch_and_parse_report(session, rid)
            if not report:
                continue
            # Match report to mission by target city name
            target = (m.get("targetCityName") or "").lower()
            found  = (report.get("targetCityName") or "").lower()
            if target and found and target[:6] not in found and found[:6] not in target:
                continue
            missions[i]["state"] = "DONE" if report.get("success") else "FAILED"
            if not report.get("success"):
                missions[i]["error"] = "Missão de espionagem falhou"
            missions[i]["result"] = report
            logger.info("[espionage] relatório %s → %s success=%s recursos=%s",
                        rid, m["targetCityName"], report.get("success"), report.get("resources"))
            matched = True
            changed = True
            break

        if not matched and now - m.get("executedAt", 0) > 7200:
            missions[i]["state"] = "FAILED"
            missions[i]["error"] = "Relatório não encontrado após 2h"
            logger.warning("[espionage] %s: relatório ausente após 2h → FAILED", m["targetCityName"])
            changed = True

    if changed:
        data["missions"] = missions
        _save_missions(data)


def process_spy_cycle(session):
    """Progress all spy mission state machines. Called once per bot cycle."""
    for label, fn in [
        ("check_spy_arrivals",      check_spy_arrivals),
        ("execute_waiting_missions", execute_waiting_missions),
        ("collect_mission_results",  collect_mission_results),
    ]:
        try:
            fn(session)
        except Exception:
            logger.warning("[espionage] %s falhou", label, exc_info=True)
