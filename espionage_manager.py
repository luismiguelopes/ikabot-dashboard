#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import os
import random
import time
import uuid

from empire_utils import LOGS_DIR, logger

SPY_MISSIONS_PATH          = os.path.join(LOGS_DIR, "spy_missions.json")
SPY_DISPATCH_QUEUE_PATH    = os.path.join(LOGS_DIR, "spy_dispatch_queue.json")
SPY_COUNTS_PATH            = os.path.join(LOGS_DIR, "spy_counts.json")
OWN_CITIES_PATH            = os.path.join(LOGS_DIR, "own_cities.json")
ESPIONAGE_SETTINGS_PATH    = os.path.join(LOGS_DIR, "espionage_settings.json")

MISSION_WAREHOUSE = 5
MISSION_GARRISON  = 6

_DEFAULT_GARRISON_THRESHOLD_TOTAL = 50000


def _load_espionage_settings():
    try:
        with open(ESPIONAGE_SETTINGS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"garrisonThresholdTotal": _DEFAULT_GARRISON_THRESHOLD_TOTAL}


def _check_garrison_threshold(resources, settings):
    """Sum of all resources must reach garrisonThresholdTotal."""
    if not resources:
        return False
    total = sum(resources.values())
    return total >= settings.get("garrisonThresholdTotal", _DEFAULT_GARRISON_THRESHOLD_TOTAL)


PLAYER_MARKS_JSON_PATH = os.path.join(LOGS_DIR, "player_marks.json")
WORLD_SCAN_JSON_PATH   = os.path.join(LOGS_DIR, "world_scan.json")


def _auto_mark_ignored(city_id, player_name, island_x, island_y, note):
    """Mark a city as 'ignorar' in player_marks.json (and db if available).
    Looks up playerId from world_scan.json using city_id."""
    try:
        player_id = None
        try:
            with open(WORLD_SCAN_JSON_PATH) as f:
                scan = json.load(f)
            for p in scan.get("players", []):
                if str(p.get("cityId")) == str(city_id):
                    player_id = str(p["playerId"])
                    break
        except Exception:
            pass
        if not player_id:
            return

        mark_key = f"{player_id}_{island_x}_{island_y}"
        now = int(time.time())
        try:
            from db_manager import DbManager
            db = DbManager()
            db.save_mark(mark_key, player_id, str(island_x), str(island_y), "ignorar", note)
            return
        except Exception:
            pass
        marks = {}
        if os.path.exists(PLAYER_MARKS_JSON_PATH):
            with open(PLAYER_MARKS_JSON_PATH) as f:
                marks = json.load(f)
        existing = marks.get(mark_key, {})
        marks[mark_key] = {
            "status": "ignorar", "note": note,
            "updatedAt": now, "actions": existing.get("actions", []),
        }
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(PLAYER_MARKS_JSON_PATH, "w") as f:
            json.dump(marks, f, indent=2)
        logger.info("[espionage] auto-ignorar %s (%s) — %s", player_name, city_id, note)
    except Exception:
        logger.warning("[espionage] _auto_mark_ignored falhou", exc_info=True)


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
    # O HTML do jogo não tem linha explícita de "disponíveis" — inDefense é o campo correcto
    # para espiões livres ("a trabalhar na defesa" = na cidade, disponíveis para dispatch)

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


def _parse_active_spy_missions(html):
    """
    Parse active spy deployments from safehouse overview HTML.
    Returns list of {cityId, x, y, cityName, state, countdown_secs}.
    state: 'WAITING_AT_CITY' | 'TRAVELING'
    """
    import re
    if not html:
        return []

    STATIONED = re.compile(r'esperam\s+novas\s+ordens', re.IGNORECASE)
    TRAVELING = re.compile(r'est[aá]\s+a\s+caminho', re.IGNORECASE)
    COUNTDOWN = re.compile(
        r'Chegada\s*(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?(?:(\d+)\s*s)?',
        re.IGNORECASE
    )

    # Split into TR-level chunks; fall back to DIV if no TR boundaries
    chunks = re.split(r'(?=<tr[\s>])', html, flags=re.IGNORECASE)
    if len(chunks) <= 2:
        chunks = re.split(r'(?=<div[\s>])', html, flags=re.IGNORECASE)

    results = []
    for chunk in chunks:
        is_stationed = bool(STATIONED.search(chunk))
        is_traveling = bool(TRAVELING.search(chunk))
        if not is_stationed and not is_traveling:
            continue

        state = 'WAITING_AT_CITY' if is_stationed else 'TRAVELING'

        x = y = city_id = city_name = None
        xm = re.search(r'xcoord=(\d+)', chunk, re.IGNORECASE)
        ym = re.search(r'ycoord=(\d+)', chunk, re.IGNORECASE)
        cm = re.search(r'selectCity=(\d+)', chunk, re.IGNORECASE)
        if xm:
            x = int(xm.group(1))
        if ym:
            y = int(ym.group(1))
        if cm:
            city_id = cm.group(1)

        if x is None and city_id is None:
            logger.debug("[espionage] activa: chunk sem coords — a saltar")
            continue

        link_m = re.search(
            r'<a\s[^>]*(?:xcoord|selectCity)[^>]*>(.*?)</a>',
            chunk, re.DOTALL | re.IGNORECASE
        )
        if link_m:
            inner = re.sub(r'<br\s*/?>', ' ', link_m.group(1), flags=re.IGNORECASE)
            inner = re.sub(r'<[^>]+>', '', inner)
            inner = re.sub(r'\s+', ' ', inner.replace('&nbsp;', ' ')).strip()
            bracket = re.search(r'\[\s*\d+\s*:\s*\d+\s*\]', inner)
            city_name = inner[:bracket.start()].strip() if bracket else inner or None

        countdown_secs = None
        if is_traveling:
            cm2 = COUNTDOWN.search(chunk)
            if cm2 and any(cm2.groups()):
                h    = int(cm2.group(1) or 0)
                mins = int(cm2.group(2) or 0)
                secs = int(cm2.group(3) or 0)
                total = h * 3600 + mins * 60 + secs
                countdown_secs = total if total > 0 else None

        results.append({
            "cityId":         city_id,
            "x":              x,
            "y":              y,
            "cityName":       city_name,
            "state":          state,
            "countdown_secs": countdown_secs,
        })
        logger.debug("[espionage] activa: %s x=%s y=%s cityId=%s countdown=%s",
                     state, x, y, city_id, countdown_secs)

    if results:
        logger.info("[espionage] %d espião(ões) activo(s) detectado(s) no safehouse", len(results))
    return results


def _sync_active_spy_missions(active_entries, origin_city_id):
    """
    Reconcile active spy deployments (from safehouse HTML) with spy_missions.json.
    - TRAVELING missions that appear as WAITING_AT_CITY → transition state.
    - Deployed spies unknown to the bot → create synthetic mission.
    """
    if not active_entries:
        return

    data     = _load_missions()
    missions = data.get("missions", [])
    changed  = False
    now      = int(time.time())

    for entry in active_entries:
        ex     = entry.get("x")
        ey     = entry.get("y")
        ecid   = entry.get("cityId")
        estate = entry.get("state")

        match_idx = None
        for idx, m in enumerate(missions):
            if m.get("state") not in ("TRAVELING", "WAITING_AT_CITY"):
                continue
            if str(m.get("originCityId", "")) != str(origin_city_id):
                continue
            if ecid and str(m.get("targetCityId", "")) == str(ecid):
                match_idx = idx
                break
            if ex is not None and ey is not None:
                if m.get("islandX") == ex and m.get("islandY") == ey:
                    match_idx = idx
                    break

        if match_idx is not None:
            m = missions[match_idx]
            if estate == "WAITING_AT_CITY" and m.get("state") == "TRAVELING":
                missions[match_idx]["state"]     = "WAITING_AT_CITY"
                missions[match_idx]["arrivedAt"] = now
                if not missions[match_idx].get("executeAfter"):
                    missions[match_idx]["executeAfter"] = now + random.randint(5, 15) * 60
                logger.info("[espionage] sync: %s→WAITING_AT_CITY (%s)",
                            m.get("targetCityName", "?"), m.get("targetPlayerName", "?"))
                changed = True
            elif estate == "TRAVELING" and m.get("state") == "TRAVELING":
                countdown = entry.get("countdown_secs")
                if countdown and not missions[match_idx].get("executeAfter"):
                    arrival_ts = now + countdown
                    missions[match_idx]["executeAfter"] = arrival_ts + random.randint(5, 15) * 60
                    logger.info("[espionage] sync: countdown para %s: +%dm",
                                m.get("targetCityName", "?"), countdown // 60)
                    changed = True
        else:
            # Espião manualmente despachado — criar missão sintética
            if estate == "WAITING_AT_CITY":
                execute_after = now + random.randint(5, 15) * 60
            else:
                countdown = entry.get("countdown_secs")
                execute_after = (now + countdown + random.randint(5, 15) * 60) if countdown else None

            missions.append({
                "originCityId":           str(origin_city_id),
                "targetCityId":           ecid or "",
                "targetIslandId":         "",
                "targetPlayerName":       "",
                "targetCityName":         entry.get("cityName") or "",
                "islandX":                ex,
                "islandY":                ey,
                "numAgents":              0,
                "state":                  estate,
                "safehousePosition":      None,
                "spySessionId":           None,
                "dispatchedAt":           now,
                "arrivedAt":              now if estate == "WAITING_AT_CITY" else None,
                "executeAfter":           execute_after,
                "executedAt":             None,
                "missionType":            None,
                "result":                 None,
                "syntheticFromSafehouse": True,
            })
            logger.info("[espionage] sync: espião manual detectado → %s [%s:%s] estado=%s",
                        entry.get("cityName") or "?", ex, ey, estate)
            changed = True

    if changed:
        data["missions"] = missions
        _save_missions(data)


def _fetch_city_spy_counts(session, city_id, city_name, position):
    """
    GET the safehouse AJAX view and parse spy counts from the changeView HTML.
    The response changeView[1][1] contains the full safehouse HTML with all counters.
    Returns (counts_dict, html_str), or (None, "") on error.
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
        return None, ""

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
        return None, ""

    counts = _parse_safehouse_page(html_content, city_name)
    counts["cityName"] = city_name
    return counts, html_content


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

        counts, html_content = _fetch_city_spy_counts(session, city_id, city_name, position)
        if counts is None:
            counts = {"cityName": city_name, "available": None, "inDefense": None,
                      "inTraining": None, "deployed": None, "trainable": None}
        else:
            active = _parse_active_spy_missions(html_content)
            if active:
                _sync_active_spy_missions(active, city_id)
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
    settings = _load_espionage_settings()
    if not settings.get("processingEnabled", True):
        logger.info("[espionage] processamento de espias desactivado — a ignorar dispatch queue")
        return
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

        # Verificar se já há espião em trânsito ou à espera nesta cidade-alvo
        target_cid = str(item["targetCityId"])
        target_x   = item.get("islandX")
        target_y   = item.get("islandY")
        active_missions = _load_missions().get("missions", [])
        already_active = any(
            m.get("state") in ("TRAVELING", "WAITING_AT_CITY")
            and str(m.get("targetCityId", "")) == target_cid
            for m in active_missions
        )
        if already_active:
            logger.info("[espionage] espião já activo para %s (%s) — dispatch ignorado",
                        item["targetPlayerName"], item["targetCityName"])
            continue

        # Pre-check: inDefense = espiões na cidade, disponíveis para dispatch.
        # available pode ser None se o parser não o calculou — usar inDefense como fallback.
        city_counts  = spy_data.get(origin_id, {})
        in_defense   = city_counts.get("inDefense")
        available    = city_counts.get("available")
        dispatchable = in_defense if in_defense is not None else available
        if dispatchable is not None and dispatchable < num_agents:
            error = f"Espiões insuficientes: {dispatchable} na cidade, {num_agents} pedidos"
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
        if ok:
            # Decrementar em memória para que o pre-check funcione correctamente
            # nos dispatches seguintes da mesma batch (spy_data carregado uma vez)
            entry = spy_data.setdefault(origin_id, {})
            for key in ("inDefense", "available"):
                if entry.get(key) is not None:
                    entry[key] = max(0, entry[key] - num_agents)
        else:
            _append_failed_mission(item, result)
            logger.warning("[espionage] dispatch falhou → guardado como FAILED para %s: %s",
                           item["targetPlayerName"], result)
            # type=11 = sem espiões; actualizar cache em disco e em memória
            if "type=10" not in result and "11" in result:
                counts_data = _load_spy_counts()
                entry = counts_data.setdefault("byCityId", {}).setdefault(origin_id, {})
                entry["inDefense"] = 0
                entry["available"] = 0
                _save_spy_counts(counts_data)
                spy_data = counts_data["byCityId"]
                logger.info("[espionage] spy_counts invalidados para cidade %s após type=11", origin_id)

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

    # Mudar para a cidade de origem antes do dispatch (estabelece contexto de sessão)
    try:
        session.post(params={
            "action":          "header",
            "function":        "changeCurrentCity",
            "actionRequest":   ikabot_config.actionRequest,
            "oldView":         "city",
            "cityId":          str(origin_city_id),
            "backgroundView":  "city",
            "currentCityId":   str(origin_city_id),
            "ajax":            "1",
        })
        time.sleep(random.randint(2, 5))
    except Exception:
        pass

    params = {
        "action": "Espionage",
        "function": "sendSpy",
        "tab": "tabSafehouse",
        "destinationCityId": target_city_id,
        "cityId": origin_city_id,
        "islandId": target_island_id,
        "backgroundView": "city",
        "currentCityId": origin_city_id,
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
            feedback_types = []
            for entry in resp_data:
                if isinstance(entry, list) and entry[0] == "provideFeedback":
                    fb_list = entry[1] if isinstance(entry[1], list) else [entry[1]]
                    feedback_types = [fb.get("type") if isinstance(fb, dict) else fb for fb in fb_list]
            logger.warning("[espionage] dispatch falhou — provideFeedback types=%s raw: %s",
                           feedback_types, resp[:400])
            return False, f"Servidor rejeitou o dispatch (sem type=10; tipos recebidos: {feedback_types})"
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

    # Fetch missions view immediately to read the arrival countdown
    if safehouse_pos is not None:
        try:
            time.sleep(random.randint(3, 7))
            _, missions_html = _fetch_spy_missions_view(
                session, origin_city_id, target_city_id, safehouse_pos)
            countdown_secs = _parse_arrival_countdown(missions_html)
            if countdown_secs is not None:
                arrival_ts = int(time.time()) + countdown_secs
                jitter = random.randint(5, 15) * 60
                mission["executeAfter"] = arrival_ts + jitter
                logger.info("[espionage] chegada de %s em ~%dm → executar em %dm total",
                            target_city_name, countdown_secs // 60,
                            (countdown_secs + jitter) // 60)
            else:
                logger.debug("[espionage] countdown não encontrado na HTML — usará polling normal")
        except Exception as e:
            logger.debug("[espionage] fetch pós-dispatch falhou: %s", e)

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


def _parse_arrival_countdown(html):
    """
    Parse 'Chegada Xh Ym Zs' countdown from spyMissions HTML.
    Returns seconds as int, or None if not found.
    Formats seen: '02m 56s', '1h 23m', '45s', '1h 23m 10s'
    """
    import re
    if not html:
        return None
    m = re.search(
        r'Chegada\s*'
        r'(?:(\d+)\s*h\s*)?'
        r'(?:(\d+)\s*m\s*)?'
        r'(?:(\d+)\s*s)?',
        html, re.IGNORECASE
    )
    if not m or not any(m.groups()):
        return None
    h = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    secs = int(m.group(3) or 0)
    total = h * 3600 + mins * 60 + secs
    return total if total > 0 else None


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


_RESOURCE_ALT_MAP = {
    "material de construção": "wood",
    "material de constru":    "wood",
    "madeira":                "wood",
    "vinho":                  "wine",
    "mármore":                "marble",
    "marmore":                "marble",
    "cristal":                "glass",
    "enxofre":                "sulfur",
}


def _alt_to_resource_key(alt_text):
    normalized = alt_text.lower().strip()
    for k, v in _RESOURCE_ALT_MAP.items():
        if normalized == k or k in normalized:
            return v
    return None


def _parse_reports_from_html(html):
    """
    Parse all espionage reports embedded in the safehouse reports tab HTML.
    Returns dict {report_id: parsed_data}. All report content is present in the initial
    page load for both read and unread reports — no per-report AJAX call needed.
    """
    import re
    results = {}
    if not html:
        return results

    # Each report occupies a consecutive pair of TR rows:
    #   <tr id="messageID" class="espionageReports [bold]"> — header (bold = unread)
    #   <tr id="tbl_mailID" class="report [invisible]">     — detail with full resource/garrison table
    # Split the HTML at each header row so each chunk covers one full report.
    splits = list(re.finditer(r'(?=<tr[^>]+id=["\']message(\d+)["\'])', html, re.IGNORECASE))
    if not splits:
        logger.debug("[espionage] _parse_reports_from_html: nenhum relatório encontrado no HTML")
        return results

    for k, split in enumerate(splits):
        report_id = split.group(1)
        start = split.start()
        end = splits[k + 1].start() if k + 1 < len(splits) else len(html)
        chunk = html[start:end]

        header_m = re.search(
            r'<tr[^>]+id=["\']message' + re.escape(report_id) + r'["\'][^>]*class=["\']([^"\']+)["\']',
            chunk, re.IGNORECASE)
        is_unread = bool(header_m and "bold" in header_m.group(1))

        owner_m = re.search(r'class=["\']targetOwner[^"\']*["\'][^>]*>(.*?)</td>',
                            chunk, re.DOTALL | re.IGNORECASE)
        target_owner = re.sub(r'<[^>]+>', '', owner_m.group(1)).strip() if owner_m else None

        # City cell — extract from href (most reliable) then fall back to link text
        city_m = re.search(r'class=["\']targetCity[^"\']*["\'][^>]*>.*?<a\s([^>]*)>(.*?)</a>',
                           chunk, re.DOTALL | re.IGNORECASE)
        target_city = island_x = island_y = None
        target_city_id_from_report = None
        if city_m:
            attrs = city_m.group(1)
            # xcoord/ycoord from href
            xm = re.search(r'xcoord=(\d+)', attrs, re.IGNORECASE)
            ym = re.search(r'ycoord=(\d+)', attrs, re.IGNORECASE)
            cm = re.search(r'selectCity=(\d+)', attrs, re.IGNORECASE)
            if xm and ym:
                island_x = int(xm.group(1))
                island_y = int(ym.group(1))
            if cm:
                target_city_id_from_report = cm.group(1)
            # City name from link text
            city_inner = re.sub(r'<br\s*/?>', ' ', city_m.group(2), flags=re.IGNORECASE)
            city_text  = re.sub(r'<[^>]+>', '', city_inner)
            city_text  = re.sub(r'\s+', ' ', city_text).strip()
            # Strip trailing coord bracket from display name
            bracket = re.search(r'\[\s*\d+\s*:\s*\d+\s*\]', city_text)
            target_city = city_text[:bracket.start()].strip() if bracket else city_text
            # Fallback: parse coords from text if href didn't have them
            if island_x is None:
                coord_m = re.search(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]', city_text)
                if coord_m:
                    island_x = int(coord_m.group(1))
                    island_y = int(coord_m.group(2))

        success = bool(re.search(r'completada com sucesso|completed successfully',
                                 chunk, re.IGNORECASE))

        # Detect arrival-only notification ("O teu espião chegou a X")
        is_arrival = bool(re.search(
            r'o teu espi[aã]o chegou\b|your spy (?:has )?arrived',
            chunk, re.IGNORECASE))

        resources = {}
        res_table_m = re.search(
            r'<table[^>]+class=["\'][^"\']*resourcesTable[^"\']*["\'][^>]*>(.*?)</table>',
            chunk, re.DOTALL | re.IGNORECASE)
        if res_table_m:
            for row_m in re.finditer(
                r'<img[^>]+alt=["\']([^"\']+)["\'].*?'
                r'<td[^>]+class=["\'][^"\']*count[^"\']*["\'][^>]*>([\d.,\s]+)</td>',
                res_table_m.group(1), re.DOTALL | re.IGNORECASE
            ):
                key = _alt_to_resource_key(row_m.group(1))
                if key:
                    count_str = row_m.group(2).replace('.', '').replace(',', '').strip()
                    try:
                        resources[key] = int(count_str)
                    except ValueError:
                        pass

        troops = None
        if re.search(r'Tropas\s+em\b|Frotas\s+em\b', chunk, re.IGNORECASE):
            # Keep {} for empty garrison — distinguishes "garrison checked, no troops" from "not a garrison report"
            troops = _parse_garrison_troops(chunk)

        results[report_id] = {
            "reportId":       report_id,
            "isUnread":       is_unread,
            "isArrival":      is_arrival,
            "targetOwner":    target_owner,
            "targetCityName": target_city,
            "targetCityId":   target_city_id_from_report,
            "islandX":        island_x,
            "islandY":        island_y,
            "success":        success,
            "resources":      resources if resources else None,
            "troops":         troops,
            "reportedAt":     int(time.time()),
        }

    logger.debug("[espionage] _parse_reports_from_html: %d relatório(s) encontrado(s)", len(results))
    return results


def _fetch_all_reports(session, origin_city_id, position):
    """
    GET safehouse reports tab once and return all parsed report data {report_id: data}.
    The page HTML already contains full content for every report (read and unread alike).
    """
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
        return {}

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

    if not html:
        logger.warning("[espionage] reports tab: sem HTML no changeView")
        return {}

    return _parse_reports_from_html(html)


def _parse_garrison_troops(html):
    """
    Parse the table-structured garrison report HTML.
    Format: header row (Quartel/Estaleiro + unit names),
            data row (Tropas/Frotas em CITY + counts or "-")
    Returns {unit_name: count} for all non-zero units.
    """
    import re
    troops = {}
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
    current_headers = []
    for row in rows:
        cells_raw = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL | re.IGNORECASE)
        cells = []
        for c in cells_raw:
            text = re.sub(r'<[^>]+>', '', c).replace('\xa0', ' ').strip()
            text = re.sub(r'\s+', ' ', text).strip()
            if not text:
                # Unit icons render name in title="" — e.g. <div class="army hoplite" title="Hoplita">
                title_m = re.search(r'\btitle=["\']([^"\']+)["\']', c, re.IGNORECASE)
                if title_m:
                    text = title_m.group(1).strip()
            cells.append(text)
        if not cells:
            continue
        first = cells[0]
        if first in ('Quartel', 'Estaleiro'):
            current_headers = cells[1:]
        elif first.startswith('Tropas em') or first.startswith('Frotas em'):
            values = cells[1:]
            for i, val in enumerate(values):
                if i >= len(current_headers):
                    break
                unit_name = current_headers[i].strip()
                if not unit_name or val in ('-', '', 'Nenhuma unidade disponível.'):
                    continue
                try:
                    count = int(val.replace('.', '').replace(',', ''))
                    if count > 0:
                        troops[unit_name] = troops.get(unit_name, 0) + count
                except ValueError:
                    pass
    return troops




# ── Phase 2: public state machine functions ───────────────────────────────────

def check_spy_arrivals(session):
    """TRAVELING → WAITING_AT_CITY for missions whose spy has arrived at target."""
    data = _load_missions()
    missions = data.get("missions", [])
    changed = False
    now = time.time()

    for i, m in enumerate(missions):
        if m.get("state") != "TRAVELING":
            continue

        execute_after = m.get("executeAfter")

        if execute_after:
            # Arrival time known from post-dispatch fetch — skip polling until close to execute time.
            # Check 2 min before execution to confirm spy is there and get session ID.
            if now < execute_after - 120:
                continue
        else:
            # No arrival time known — fall back to polling after minimum 20 min
            if now - m.get("dispatchedAt", 0) < 1200:
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
            missions[i]["arrivedAt"] = int(now)
            missions[i]["safehousePosition"] = position
            missions[i]["spySessionId"] = spy_id
            # Keep existing executeAfter if already set (from post-dispatch fetch);
            # otherwise assign a fresh random delay now
            if not execute_after:
                missions[i]["executeAfter"] = int(now) + random.randint(5, 15) * 60
            logger.info("[espionage] espiões chegaram a %s (spy_id=%s) — executar em %dmin",
                        m["targetCityName"], spy_id,
                        max(0, (missions[i]["executeAfter"] - int(now)) // 60))
            changed = True
        elif now - m.get("dispatchedAt", 0) > 43200:  # 12h no arrival → failed
            missions[i]["state"] = "FAILED"
            missions[i]["error"] = "Sem chegada detectada após 12h — possivelmente capturado"
            logger.warning("[espionage] %s: sem chegada após 12h → FAILED", m["targetCityName"])
            changed = True
        elif execute_after and now >= execute_after - 120:
            # Expected arrival time passed but spy not found — refresh countdown
            countdown = _parse_arrival_countdown(html or "")
            if countdown:
                new_eta = int(now) + countdown
                jitter = random.randint(5, 15) * 60
                missions[i]["executeAfter"] = new_eta + jitter
                logger.info("[espionage] %s ainda em viagem — chegada actualizada: +%dm",
                            m["targetCityName"], (new_eta + jitter - int(now)) // 60)
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
            missions[i]["state"] = "EXECUTING_WAREHOUSE"
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
    """EXECUTING_WAREHOUSE → WAITING_FOR_GARRISON or DONE/FAILED."""
    data = _load_missions()
    missions = data.get("missions", [])
    changed = False
    now = int(time.time())

    for i, m in enumerate(missions):
        if m.get("state") not in ("EXECUTING", "EXECUTING_WAREHOUSE"):
            continue
        if now - m.get("executedAt", 0) < random.randint(60, 300):
            continue

        origin_id = str(m["originCityId"])
        position = m.get("safehousePosition") or _get_city_safehouse_position(origin_id)
        if not position:
            continue

        time.sleep(random.randint(5, 15))
        reports = _fetch_all_reports(session, origin_id, position)

        if not reports:
            continue

        matched = False
        target     = (m.get("targetCityName") or "").lower()
        target_cid = str(m.get("targetCityId", ""))
        for rid in sorted(reports.keys(), key=lambda x: int(x), reverse=True)[:20]:
            report = reports[rid]
            if not report.get("resources"):
                continue
            report_cid = report.get("targetCityId")
            if report_cid and target_cid:
                if str(report_cid) != target_cid:
                    continue
            else:
                found = (report.get("targetCityName") or "").lower()
                if target and found and target[:6] not in found and found[:6] not in target:
                    continue

            missions[i]["result"] = report

            if report.get("success"):
                settings  = _load_espionage_settings()
                resources = report.get("resources") or {}
                if _check_garrison_threshold(resources, settings):
                    delay_min = random.randint(1, 5)
                    missions[i]["state"] = "WAITING_FOR_GARRISON"
                    missions[i]["garrisonExecuteAfter"] = now + delay_min * 60
                    missions[i]["garrisonExecutedAt"]   = None
                    missions[i]["garrisonResult"]       = None
                    logger.info("[espionage] armazém %s → recursos=%s — threshold atingido, garrison em %dmin",
                                m["targetCityName"], resources, delay_min)
                else:
                    missions[i]["state"] = "DONE"
                    logger.info("[espionage] armazém %s → recursos=%s — threshold não atingido, DONE",
                                m["targetCityName"], resources)
                    total = sum(resources.values())
                    note = "Abaixo do threshold de saque (recursos: {:,})".format(total)
                    # Recall spy before auto-ignoring
                    _origin_id = str(m.get("originCityId", ""))
                    _position  = m.get("safehousePosition") or _get_city_safehouse_position(_origin_id)
                    if _origin_id and _position:
                        _rq = _load_recall_queue()
                        _rq.setdefault("pending", []).append({
                            "targetCityId": str(m.get("targetCityId", "")),
                            "originCityId": _origin_id,
                            "position":     _position,
                            "cityName":     m.get("targetCityName", ""),
                            "queuedAt":     int(time.time()),
                        })
                        _save_recall_queue(_rq)
                        logger.info("[espionage] recall queued → %s (threshold não atingido)", m["targetCityName"])
                    _auto_mark_ignored(
                        m.get("targetCityId"), m.get("targetPlayerName", ""),
                        m.get("islandX"), m.get("islandY"), note,
                    )
            else:
                missions[i]["state"] = "FAILED"
                missions[i]["error"] = "Missão de espionagem falhou"
                logger.info("[espionage] armazém %s → falhou", m["targetCityName"])

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


def execute_garrison_missions(session):
    """WAITING_FOR_GARRISON → EXECUTING_GARRISON after delay."""
    data = _load_missions()
    missions = data.get("missions", [])
    changed = False
    now = int(time.time())

    for i, m in enumerate(missions):
        if m.get("state") != "WAITING_FOR_GARRISON":
            continue
        if now < m.get("garrisonExecuteAfter", now + 1):
            continue

        origin_id = str(m["originCityId"])
        position = m.get("safehousePosition") or _get_city_safehouse_position(origin_id)
        if not position:
            continue

        time.sleep(random.randint(10, 25))
        spy_count, html = _fetch_spy_missions_view(session, origin_id, m["targetCityId"], position)

        if not spy_count:
            # Spy left before garrison — keep warehouse result, mark DONE
            missions[i]["state"] = "DONE"
            logger.info("[espionage] %s: espião regressou antes da garrison — DONE (só armazém)",
                        m["targetCityName"])
            changed = True
            continue

        spy_id = _parse_spy_session_id(html) or m.get("spySessionId")

        time.sleep(random.randint(5, 15))
        ok = _execute_spy_mission(
            session, origin_id, m["targetCityId"], position,
            spy_id, m.get("numAgents", 1), MISSION_GARRISON,
        )

        if ok:
            missions[i]["state"] = "EXECUTING_GARRISON"
            missions[i]["garrisonExecutedAt"] = now
            missions[i]["spySessionId"] = spy_id
            logger.info("[espionage] missão garrison executada → %s", m["targetCityName"])
        else:
            missions[i]["state"] = "DONE"
            missions[i]["garrisonResult"] = {"error": "executeMission garrison rejeitado"}
            logger.warning("[espionage] %s: garrison rejeitada → DONE com só armazém", m["targetCityName"])
        changed = True

    if changed:
        data["missions"] = missions
        _save_missions(data)


def collect_garrison_results(session):
    """EXECUTING_GARRISON → DONE: fetch and parse garrison reports."""
    data = _load_missions()
    missions = data.get("missions", [])
    changed = False
    now = int(time.time())

    for i, m in enumerate(missions):
        if m.get("state") != "EXECUTING_GARRISON":
            continue
        if now - m.get("garrisonExecutedAt", 0) < random.randint(60, 300):
            continue

        origin_id = str(m["originCityId"])
        position = m.get("safehousePosition") or _get_city_safehouse_position(origin_id)
        if not position:
            continue

        time.sleep(random.randint(5, 15))
        reports = _fetch_all_reports(session, origin_id, position)

        if not reports:
            continue

        matched = False
        target     = (m.get("targetCityName") or "").lower()
        target_cid = str(m.get("targetCityId", ""))
        for rid in sorted(reports.keys(), key=lambda x: int(x), reverse=True)[:20]:
            report = reports[rid]
            if report.get("troops") is None:
                continue  # None = not a garrison report (warehouse report); {} = garrison with no troops
            report_cid = report.get("targetCityId")
            if report_cid and target_cid:
                if str(report_cid) != target_cid:
                    continue
            else:
                found = (report.get("targetCityName") or "").lower()
                if target and found and target[:6] not in found and found[:6] not in target:
                    continue
            missions[i]["state"] = "DONE"
            missions[i]["garrisonResult"] = report
            logger.info("[espionage] garrison %s → tropas=%s",
                        m["targetCityName"], report.get("troops"))
            matched = True
            changed = True
            break

        if not matched and now - m.get("garrisonExecutedAt", 0) > 7200:
            missions[i]["state"] = "DONE"
            missions[i]["garrisonResult"] = {"error": "Relatório garrison não encontrado após 2h"}
            logger.warning("[espionage] %s: relatório garrison ausente após 2h → DONE com só armazém",
                           m["targetCityName"])
            changed = True

    if changed:
        data["missions"] = missions
        _save_missions(data)


ATTACK_QUEUE_PATH = os.path.join(LOGS_DIR, "attack_queue.json")


def _load_attack_queue():
    try:
        with open(ATTACK_QUEUE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"pending": []}


def _save_attack_queue(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(ATTACK_QUEUE_PATH, "w") as f:
        json.dump(data, f, indent=2)


def has_pending_attacks():
    try:
        return bool(_load_attack_queue().get("pending"))
    except Exception:
        return False


def _dispatch_attack(session, item):
    """POST deployArmy to attack a player city."""
    import ikabot.config as ikabot_config

    params = {
        "action":            "transportOperations",
        "function":          "deployArmy",
        "actionRequest":     ikabot_config.actionRequest,
        "islandId":          str(item["islandId"]),
        "destinationCityId": str(item["targetCityId"]),
        "deploymentType":    "army",
        "backgroundView":    "city",
        "currentCityId":     str(item["originCityId"]),
        "templateView":      "deployment",
        "transporter":       int(item.get("transporters", 0)),
        "ajax":              1,
    }
    for unit_id, count in item.get("units", {}).items():
        params[f"cargo_army_{unit_id}"] = int(count)

    try:
        resp      = session.post(params=params)
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
        logger.warning("[attack] deployArmy sem type=10 — raw: %.300s", resp)
        return False
    except Exception as e:
        logger.error("[attack] dispatch exception: %s", e)
        return False


def process_attack_queue(session, in_active_hours=True):
    """Dispatch pending attacks during active hours with random delays."""
    if not in_active_hours:
        return

    q = _load_attack_queue()
    pending = q.get("pending", [])
    if not pending:
        return

    remaining = []
    dispatched = 0
    for item in pending:
        if int(time.time()) < item.get("dispatchAfter", 0):
            remaining.append(item)
            continue

        if dispatched > 0:
            delay = random.randint(30, 90)
            logger.info("[attack] aguardar %ds antes do próximo ataque", delay)
            time.sleep(delay)

        ok = _dispatch_attack(session, item)
        dispatched += 1
        if ok:
            logger.info("[attack] ataque despachado → %s (%s)",
                        item.get("targetPlayerName"), item.get("targetCityName"))
        else:
            logger.warning("[attack] dispatch falhou para %s — removido da fila",
                           item.get("targetPlayerName"))

    q["pending"] = remaining
    _save_attack_queue(q)


def force_warehouse_mission(target_city_id):
    """Force warehouse inspection for a city.
    - WAITING_AT_CITY → reset executeAfter to now so it runs on next cycle.
    - No active mission → add a new dispatch queue item from world scan data.
    """
    data     = _load_missions()
    missions = data.get("missions", [])

    for i, m in enumerate(missions):
        if m.get("state") == "WAITING_AT_CITY" and str(m.get("targetCityId", "")) == str(target_city_id):
            missions[i]["executeAfter"] = int(time.time()) - 1
            data["missions"] = missions
            _save_missions(data)
            logger.info("[espionage] force-warehouse %s — executeAfter resetado", m.get("targetCityName"))
            return

    # No active mission — look up city in world_scan and add to dispatch queue
    try:
        with open(WORLD_SCAN_JSON_PATH) as f:
            scan = json.load(f)
        city = next((p for p in scan.get("players", []) if str(p.get("cityId")) == str(target_city_id)), None)
        if not city:
            logger.warning("[espionage] force-warehouse: cidade %s não encontrada no world scan", target_city_id)
            return
        queue = _load_dispatch_queue()
        queue.setdefault("pending", []).append({
            "targetCityId":     str(target_city_id),
            "targetPlayerName": city.get("playerName", ""),
            "targetCityName":   city.get("cityName", ""),
            "targetIslandId":   str(city.get("islandId", "")),
            "islandX":          city.get("islandX"),
            "islandY":          city.get("islandY"),
            "numAgents":        1,
            "numDecoys":        0,
            "queuedAt":         int(time.time()),
            "forceWarehouse":   True,
        })
        _save_dispatch_queue(queue)
        logger.info("[espionage] force-warehouse %s — adicionado à fila de dispatch", city.get("cityName"))
    except Exception:
        logger.warning("[espionage] force_warehouse_mission falhou", exc_info=True)


RECALL_QUEUE_PATH = os.path.join(LOGS_DIR, "spy_recall_queue.json")


def _load_recall_queue():
    try:
        with open(RECALL_QUEUE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"pending": []}


def _save_recall_queue(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(RECALL_QUEUE_PATH, "w") as f:
        json.dump(data, f, indent=2)


def recall_spy_mission(target_city_id):
    """Queue a recall for a spy stationed at target_city_id.
    Looks up origin city and safehouse position from the active mission.
    The actual game API call is made by _process_recall_queue on the next bot wake-up."""
    data     = _load_missions()
    missions = data.get("missions", [])
    queued   = False
    for i, m in enumerate(missions):
        if m.get("state") in ("TRAVELING", "WAITING_AT_CITY") and str(m.get("targetCityId", "")) == str(target_city_id):
            missions[i]["state"]     = "RECALLED"
            missions[i]["recalledAt"] = int(time.time())
            # Queue the actual game server call
            origin_id = str(m.get("originCityId", ""))
            position  = m.get("safehousePosition") or _get_city_safehouse_position(origin_id)
            if origin_id and position:
                q = _load_recall_queue()
                q.setdefault("pending", []).append({
                    "targetCityId": str(target_city_id),
                    "originCityId": origin_id,
                    "position":     position,
                    "cityName":     m.get("targetCityName", ""),
                    "queuedAt":     int(time.time()),
                })
                _save_recall_queue(q)
                queued = True
            logger.info("[espionage] recall %s — RECALLED%s", m.get("targetCityName"),
                        ", recall game request queued" if queued else " (sem origin/position)")
    data["missions"] = missions
    _save_missions(data)


def _process_recall_queue(session):
    """Send retreat requests to the game server for all pending recalls."""
    import ikabot.config as ikabot_config
    q = _load_recall_queue()
    pending = q.get("pending", [])
    if not pending:
        return
    remaining = []
    for item in pending:
        time.sleep(random.randint(3, 8))
        try:
            url = (
                "view=spyMissions&targetCityId={}&retreat=1&position={}"
                "&currentCityId={}&activeTab=tabSafehouse&backgroundView=city"
                "&templateView=safehouse&actionRequest={}&ajax=1".format(
                    item["targetCityId"], item["position"],
                    item["originCityId"], ikabot_config.actionRequest,
                )
            )
            resp = session.get(url)
            try:
                parsed = json.loads(resp, strict=False)
                # Game returns errors in the response body — check for known error keys
                error_entry = next(
                    (e for e in parsed if isinstance(e, list) and e[0] in ("error", "errorCode")),
                    None
                )
                if error_entry:
                    logger.warning("[espionage] recall recusado pelo servidor para %s: %s",
                                   item.get("cityName"), error_entry)
                    remaining.append(item)
                else:
                    logger.info("[espionage] recall aceite pelo servidor: %s", item.get("cityName"))
            except Exception:
                logger.info("[espionage] recall enviado (resposta não parseável): %s", item.get("cityName"))
        except Exception:
            logger.warning("[espionage] recall falhou para %s", item.get("cityName"), exc_info=True)
            remaining.append(item)
    q["pending"] = remaining
    _save_recall_queue(q)


def process_spy_cycle(session):
    """Progress all spy mission state machines. Called once per bot cycle."""
    for label, fn in [
        ("process_recall_queue",      _process_recall_queue),
        ("check_spy_arrivals",        check_spy_arrivals),
        ("execute_waiting_missions",  execute_waiting_missions),
        ("collect_mission_results",   collect_mission_results),
        ("execute_garrison_missions", execute_garrison_missions),
        ("collect_garrison_results",  collect_garrison_results),
    ]:
        try:
            fn(session)
        except Exception:
            logger.warning("[espionage] %s falhou", label, exc_info=True)


# ── Phase 4: Auto-attack waves ────────────────────────────────────────────────

AUTO_ATTACK_WAVES_PATH    = os.path.join(LOGS_DIR, "auto_attack_waves.json")
AUTO_ATTACK_SETTINGS_PATH = os.path.join(LOGS_DIR, "auto_attack_settings.json")
MILITARY_JSON_PATH        = os.path.join(LOGS_DIR, "military.json")

_NAVAL_UNIT_NAMES = {
    "navio de guerra", "steam giant", "navio a vapor", "ram ship", "galley",
    "trireme", "mortar ship", "balloon ship", "catapult ship",
    "náu de guerra", "navios de guerra",
}

_DEFAULT_AUTO_ATTACK_SETTINGS = {
    "enabled":                False,
    "minLootTotal":           50000,
    "lootPerWave":            195000,
    "battleDelayFewMins":     30,
    "battleDelayMedMins":     60,
    "battleDelayManyMins":    120,
    "maxEnemyShipsToEngage":  20,
}


def _load_auto_attack_settings():
    try:
        with open(AUTO_ATTACK_SETTINGS_PATH) as f:
            s = json.load(f)
            for k, v in _DEFAULT_AUTO_ATTACK_SETTINGS.items():
                s.setdefault(k, v)
            return s
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULT_AUTO_ATTACK_SETTINGS)


def _save_auto_attack_settings(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(AUTO_ATTACK_SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _load_auto_attack_waves():
    try:
        with open(AUTO_ATTACK_WAVES_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"waves": []}


def _save_auto_attack_waves(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(AUTO_ATTACK_WAVES_PATH, "w") as f:
        json.dump(data, f, indent=2)


def get_auto_attack_waves():
    return _load_auto_attack_waves()


def get_auto_attack_settings():
    return _load_auto_attack_settings()


def save_auto_attack_settings(data):
    _save_auto_attack_settings(data)


def _enemy_fleet_count(garrison_troops):
    """Count naval units in enemy garrison troops dict {unit_name: count}."""
    if not garrison_troops:
        return 0
    total = 0
    for name, count in garrison_troops.items():
        if any(nav in name.lower() for nav in _NAVAL_UNIT_NAMES):
            total += count
    return total


def _estimate_battle_delay_mins(enemy_ships, settings):
    if enemy_ships == 0:
        return 0
    if enemy_ships <= 3:
        return settings.get("battleDelayFewMins", 30)
    if enemy_ships <= 10:
        return settings.get("battleDelayMedMins", 60)
    return settings.get("battleDelayManyMins", 120)


def _determine_attack_tier(garrison_troops):
    """Tier 0=empty, Tier 1=troops only, Tier 2=has naval units."""
    if not garrison_troops:
        return 0
    if _enemy_fleet_count(garrison_troops) > 0:
        return 2
    if any(v > 0 for v in garrison_troops.values()):
        return 1
    return 0


def _calc_travel_secs(origin_x, origin_y, target_x, target_y):
    if origin_x == target_x and origin_y == target_y:
        return 600
    return math.ceil(1200 * math.sqrt((origin_x - target_x) ** 2 + (origin_y - target_y) ** 2))


def _get_best_origin_city(target_x, target_y, military_data, needs_fleet=False):
    """Closest own city with troops (and fleet if needs_fleet). Returns (name, id, x, y) or None."""
    try:
        with open(OWN_CITIES_PATH) as f:
            own_cities = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    by_city   = (military_data or {}).get("byCityName", {})
    best      = None
    best_dist = float("inf")

    for city in own_cities:
        name = city.get("name", "")
        cid  = str(city.get("cityId", ""))
        cx   = city.get("x", 0)
        cy   = city.get("y", 0)

        mil    = by_city.get(name, {})
        troops = mil.get("troops", {})
        fleet  = mil.get("fleet", {})

        if not any(v.get("amount", 0) > 0 for v in troops.values()):
            continue
        if needs_fleet and not any(v.get("amount", 0) > 0 for v in fleet.values()):
            continue

        dist = _calc_travel_secs(cx, cy, target_x, target_y)
        if dist < best_dist:
            best_dist = dist
            best = (name, cid, cx, cy)

    return best


def _build_fleet_units(city_name, military_data):
    fleet = (military_data or {}).get("byCityName", {}).get(city_name, {}).get("fleet", {})
    return {uid: v["amount"] for uid, v in fleet.items() if v.get("amount", 0) > 0}


def _build_troop_units(city_name, military_data):
    troops = (military_data or {}).get("byCityName", {}).get(city_name, {}).get("troops", {})
    return {uid: v["amount"] for uid, v in troops.items() if v.get("amount", 0) > 0}


def _calc_transporters(loot_amount, ship_capacity):
    if ship_capacity <= 0:
        return 10
    return math.ceil(loot_amount / ship_capacity)


def _record_skipped(waves_data, mission_key, mission, reason):
    waves_data["waves"].append({
        "id":               uuid.uuid4().hex[:8],
        "sourceMissionKey": mission_key,
        "targetPlayerName": mission.get("targetPlayerName"),
        "targetCityId":     str(mission.get("targetCityId", "")),
        "targetIslandId":   str(mission.get("targetIslandId", "")),
        "islandX":          mission.get("islandX"),
        "islandY":          mission.get("islandY"),
        "state":            "AUTO_SKIPPED",
        "tier":             None,
        "wavePlans":        [],
        "createdAt":        int(time.time()),
        "skippedReason":    reason,
    })


def evaluate_auto_attacks(session):
    """
    For each DONE mission with garrisonResult not yet evaluated, decide whether to attack
    and build a wave plan in auto_attack_waves.json.
    """
    settings = _load_auto_attack_settings()
    if not settings.get("enabled", False):
        return

    missions_data = _load_missions()
    waves_data    = _load_auto_attack_waves()
    existing_keys = {w.get("sourceMissionKey") for w in waves_data.get("waves", [])}

    ship_capacity = 400
    try:
        from ikabot.helpers.pedirInfo import getShipCapacity
        cap, _ = getShipCapacity(session)
        if cap > 0:
            ship_capacity = cap
    except Exception:
        logger.warning("[auto-attack] getShipCapacity falhou — usando %d", ship_capacity)

    military_data = None
    try:
        with open(MILITARY_JSON_PATH) as f:
            military_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("[auto-attack] military.json não disponível — a saltar evaluate")
        return

    changed = False
    for m in missions_data.get("missions", []):
        if m.get("state") != "DONE":
            continue
        if not m.get("garrisonResult"):
            continue

        mission_key = f"{m['targetCityId']}_{m['islandX']}_{m['islandY']}"
        if mission_key in existing_keys:
            continue

        resources   = (m.get("result") or {}).get("resources") or {}
        garrison    = (m.get("garrisonResult") or {}).get("troops") or {}
        total_loot  = sum(resources.values())
        min_loot    = settings.get("minLootTotal", 50000)

        if total_loot < min_loot:
            reason = f"Botim insuficiente: {total_loot} < {min_loot}"
            logger.info("[auto-attack] %s → SKIPPED: %s", m["targetPlayerName"], reason)
            _record_skipped(waves_data, mission_key, m, reason)
            existing_keys.add(mission_key)
            changed = True
            continue

        tier        = _determine_attack_tier(garrison)
        enemy_ships = _enemy_fleet_count(garrison)
        max_engage  = settings.get("maxEnemyShipsToEngage", 20)

        if enemy_ships > max_engage:
            reason = f"Frota inimiga demasiado grande: {enemy_ships} > máximo {max_engage}"
            logger.info("[auto-attack] %s → SKIPPED: %s", m["targetPlayerName"], reason)
            _record_skipped(waves_data, mission_key, m, reason)
            existing_keys.add(mission_key)
            changed = True
            continue

        target_x = m.get("islandX", 0)
        target_y = m.get("islandY", 0)
        origin   = _get_best_origin_city(target_x, target_y, military_data, needs_fleet=(tier == 2))

        if not origin:
            reason = "Sem cidade de origem com tropas" + (" e frota" if tier == 2 else "")
            logger.warning("[auto-attack] %s → SKIPPED: %s", m["targetPlayerName"], reason)
            _record_skipped(waves_data, mission_key, m, reason)
            existing_keys.add(mission_key)
            changed = True
            continue

        origin_name, origin_id, origin_x, origin_y = origin
        travel_secs       = _calc_travel_secs(origin_x, origin_y, target_x, target_y)
        battle_delay_secs = _estimate_battle_delay_mins(enemy_ships, settings) * 60
        # Troops move ~50% faster than combat ships (speed 60 vs 40)
        troop_travel_secs = int(travel_secs * 2 / 3)
        army_extra_delay  = battle_delay_secs + travel_secs - troop_travel_secs

        loot_per_wave = settings.get("lootPerWave", 195000)
        num_waves     = max(1, math.ceil(total_loot / loot_per_wave))
        troop_units   = _build_troop_units(origin_name, military_data)
        fleet_units   = _build_fleet_units(origin_name, military_data) if tier == 2 else {}

        wave_plans    = []
        now           = int(time.time())
        prev_return   = now + random.randint(5, 20) * 60

        for wn in range(1, num_waves + 1):
            dispatch_after = prev_return if wn > 1 else now + random.randint(5, 20) * 60
            if wn > 1:
                dispatch_after += random.randint(15, 60) * 60

            wave_loot    = min(loot_per_wave, total_loot - (wn - 1) * loot_per_wave)
            transporters = _calc_transporters(wave_loot, ship_capacity)

            if tier == 2:
                fleet_dispatch_ts = dispatch_after
                army_dispatch_ts  = fleet_dispatch_ts + army_extra_delay
            else:
                fleet_dispatch_ts = None
                army_dispatch_ts  = dispatch_after

            return_ts = army_dispatch_ts + troop_travel_secs * 2

            wave_plans.append({
                "waveNum":            wn,
                "originCityId":       origin_id,
                "originCityName":     origin_name,
                "fleetUnits":         fleet_units,
                "troopUnits":         troop_units,
                "transporters":       transporters,
                "fleetDispatchAfter": fleet_dispatch_ts,
                "armyDispatchAfter":  army_dispatch_ts,
                "fleetDispatchedAt":  None,
                "armyDispatchedAt":   None,
                "estimatedReturnAt":  return_ts,
                "status":             "PENDING",
            })
            prev_return = return_ts

        waves_data["waves"].append({
            "id":               uuid.uuid4().hex[:8],
            "sourceMissionKey": mission_key,
            "targetPlayerName": m.get("targetPlayerName"),
            "targetCityId":     str(m.get("targetCityId", "")),
            "targetIslandId":   str(m.get("targetIslandId", "")),
            "islandX":          target_x,
            "islandY":          target_y,
            "state":            "PENDING",
            "tier":             tier,
            "wavePlans":        wave_plans,
            "createdAt":        int(time.time()),
            "skippedReason":    None,
        })
        existing_keys.add(mission_key)
        changed = True
        logger.info("[auto-attack] plano criado para %s: tier=%d, %d vaga(s), botim total=%d",
                    m["targetPlayerName"], tier, num_waves, total_loot)

    if changed:
        _save_auto_attack_waves(waves_data)


def _dispatch_fleet_attack(session, origin_id, target_id, island_id, fleet_units):
    """POST deployFleet to destroy enemy naval presence. Returns True on success."""
    import ikabot.config as ikabot_config

    params = {
        "action":            "transportOperations",
        "function":          "deployFleet",
        "actionRequest":     ikabot_config.actionRequest,
        "islandId":          str(island_id),
        "destinationCityId": str(target_id),
        "deploymentType":    "fleet",
        "backgroundView":    "city",
        "currentCityId":     str(origin_id),
        "templateView":      "deployment",
        "ajax":              1,
    }
    for unit_id, count in fleet_units.items():
        params[f"cargo_fleet_{unit_id}"] = int(count)

    try:
        resp      = session.post(params=params)
        resp_data = json.loads(resp, strict=False)

        for entry in resp_data:
            if isinstance(entry, list) and entry[0] == "updateGlobalData":
                tok = entry[1].get("actionRequest") if isinstance(entry[1], dict) else None
                if tok:
                    ikabot_config.actionRequest = tok
                break

        for entry in resp_data:
            if isinstance(entry, list) and entry[0] == "provideFeedback":
                if isinstance(entry[1], list):
                    for fb in entry[1]:
                        if isinstance(fb, dict) and fb.get("type") == 10:
                            return True
        logger.warning("[auto-attack] deployFleet sem type=10 — raw: %.300s", resp)
        return False
    except Exception as e:
        logger.error("[auto-attack] deployFleet exception: %s", e)
        return False


def _dispatch_army_wave(session, origin_id, target_id, island_id, troop_units, transporters):
    """POST deployArmy for a pillage wave. Returns True on success."""
    import ikabot.config as ikabot_config

    params = {
        "action":            "transportOperations",
        "function":          "deployArmy",
        "actionRequest":     ikabot_config.actionRequest,
        "islandId":          str(island_id),
        "destinationCityId": str(target_id),
        "deploymentType":    "army",
        "backgroundView":    "city",
        "currentCityId":     str(origin_id),
        "templateView":      "deployment",
        "transporter":       int(transporters),
        "ajax":              1,
    }
    for unit_id, count in troop_units.items():
        params[f"cargo_army_{unit_id}"] = int(count)

    try:
        resp      = session.post(params=params)
        resp_data = json.loads(resp, strict=False)

        for entry in resp_data:
            if isinstance(entry, list) and entry[0] == "updateGlobalData":
                tok = entry[1].get("actionRequest") if isinstance(entry[1], dict) else None
                if tok:
                    ikabot_config.actionRequest = tok
                break

        for entry in resp_data:
            if isinstance(entry, list) and entry[0] == "provideFeedback":
                if isinstance(entry[1], list):
                    for fb in entry[1]:
                        if isinstance(fb, dict) and fb.get("type") == 10:
                            return True
        logger.warning("[auto-attack] deployArmy sem type=10 — raw: %.300s", resp)
        return False
    except Exception as e:
        logger.error("[auto-attack] deployArmy exception: %s", e)
        return False


def process_auto_attack_waves(session, in_active_hours=True):
    """Dispatch pending attack wave plans: fleet (tier 2) then army."""
    if not in_active_hours:
        return

    settings = _load_auto_attack_settings()
    if not settings.get("enabled", False):
        return

    waves_data = _load_auto_attack_waves()
    now        = int(time.time())
    changed    = False

    for pi, plan in enumerate(waves_data.get("waves", [])):
        if plan.get("state") not in ("PENDING", "IN_PROGRESS"):
            continue

        tier = plan.get("tier", 0)

        for wi, wave in enumerate(plan.get("wavePlans", [])):
            status = wave.get("status")

            if status == "PENDING":
                fleet_after = wave.get("fleetDispatchAfter")
                army_after  = wave.get("armyDispatchAfter", 0)

                if tier == 2 and fleet_after and now >= fleet_after and not wave.get("fleetDispatchedAt"):
                    ok = _dispatch_fleet_attack(
                        session, wave["originCityId"],
                        plan["targetCityId"], plan["targetIslandId"],
                        wave["fleetUnits"],
                    )
                    if ok:
                        waves_data["waves"][pi]["wavePlans"][wi]["fleetDispatchedAt"] = now
                        waves_data["waves"][pi]["wavePlans"][wi]["status"] = "FLEET_DISPATCHED"
                        waves_data["waves"][pi]["state"] = "IN_PROGRESS"
                        logger.info("[auto-attack] frota despachada → %s vaga %d",
                                    plan["targetPlayerName"], wave["waveNum"])
                    else:
                        waves_data["waves"][pi]["wavePlans"][wi]["status"] = "FAILED"
                        waves_data["waves"][pi]["state"] = "FAILED"
                    changed = True
                    time.sleep(random.randint(30, 60))
                    break

                elif (tier != 2 or not fleet_after) and now >= army_after:
                    ok = _dispatch_army_wave(
                        session, wave["originCityId"],
                        plan["targetCityId"], plan["targetIslandId"],
                        wave["troopUnits"], wave["transporters"],
                    )
                    if ok:
                        waves_data["waves"][pi]["wavePlans"][wi]["armyDispatchedAt"] = now
                        waves_data["waves"][pi]["wavePlans"][wi]["status"] = "ARMY_DISPATCHED"
                        waves_data["waves"][pi]["state"] = "IN_PROGRESS"
                        logger.info("[auto-attack] tropas despachadas → %s vaga %d",
                                    plan["targetPlayerName"], wave["waveNum"])
                    else:
                        waves_data["waves"][pi]["wavePlans"][wi]["status"] = "FAILED"
                        waves_data["waves"][pi]["state"] = "FAILED"
                    changed = True
                    time.sleep(random.randint(30, 60))
                    break

            elif status == "FLEET_DISPATCHED":
                army_after = wave.get("armyDispatchAfter", 0)
                if now >= army_after:
                    ok = _dispatch_army_wave(
                        session, wave["originCityId"],
                        plan["targetCityId"], plan["targetIslandId"],
                        wave["troopUnits"], wave["transporters"],
                    )
                    if ok:
                        waves_data["waves"][pi]["wavePlans"][wi]["armyDispatchedAt"] = now
                        waves_data["waves"][pi]["wavePlans"][wi]["status"] = "ARMY_DISPATCHED"
                        logger.info("[auto-attack] tropas pós-frota → %s vaga %d",
                                    plan["targetPlayerName"], wave["waveNum"])
                    else:
                        waves_data["waves"][pi]["wavePlans"][wi]["status"] = "FAILED"
                        waves_data["waves"][pi]["state"] = "FAILED"
                    changed = True
                    time.sleep(random.randint(30, 60))
                    break

            elif status == "ARMY_DISPATCHED":
                if now >= wave.get("estimatedReturnAt", now + 1):
                    waves_data["waves"][pi]["wavePlans"][wi]["status"] = "DONE"
                    changed = True

        # Recalculate plan state after processing waves
        wave_statuses = [w.get("status") for w in plan.get("wavePlans", [])]
        if "FAILED" in wave_statuses and waves_data["waves"][pi]["state"] not in ("FAILED",):
            waves_data["waves"][pi]["state"] = "FAILED"
            changed = True
        elif wave_statuses and all(s == "DONE" for s in wave_statuses):
            waves_data["waves"][pi]["state"] = "DONE"
            logger.info("[auto-attack] todas as vagas concluídas → %s", plan["targetPlayerName"])
            changed = True

    if changed:
        _save_auto_attack_waves(waves_data)


# ── Import existing safehouse reports ─────────────────────────────────────────

def import_existing_reports(session):
    """
    Fetch all existing espionage reports from the safehouse and import them as
    synthetic DONE missions. Warehouse and garrison reports for the same city are
    merged into a single mission with garrisonResult populated.
    """
    try:
        with open(OWN_CITIES_PATH) as f:
            own_cities = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("[espionage] import_existing_reports: own_cities.json não encontrado")
        return

    origin = next(
        (c for c in own_cities if c.get("safehousePosition") is not None),
        None,
    )
    if origin is None:
        logger.warning("[espionage] import_existing_reports: nenhuma cidade com safehouse")
        return

    city_id  = str(origin.get("cityId", ""))
    position = origin["safehousePosition"]
    delay = random.randint(2, 5)
    logger.info("[espionage] aguardar %ds antes de buscar relatórios (%s)", delay, origin.get("name", ""))
    time.sleep(delay)
    all_reports = _fetch_all_reports(session, city_id, position)
    logger.info("[espionage] %d relatório(s) encontrado(s)", len(all_reports))

    if not all_reports:
        logger.info("[espionage] import_existing_reports: nenhum relatório encontrado")
        return

    world_scan_path = os.path.join(LOGS_DIR, "world_scan.json")
    try:
        with open(world_scan_path) as f:
            world_scan = json.load(f)
        scan_players = world_scan.get("players", [])
    except (FileNotFoundError, json.JSONDecodeError):
        scan_players = []

    scan_lookup: dict = {}
    for p in scan_players:
        key = (p.get("playerName", "").lower(), p.get("islandX"), p.get("islandY"))
        scan_lookup.setdefault(key, []).append(p)

    missions_data = _load_missions()

    # Remove previously imported synthetic missions that have no useful intel
    before = len(missions_data.get("missions", []))
    missions_data["missions"] = [
        m for m in missions_data.get("missions", [])
        if not (
            m.get("importedFromReport")
            and m.get("state") == "DONE"
            and not (m.get("result") or {}).get("resources")
            and not (m.get("result") or {}).get("troops")
            and not m.get("garrisonResult")
        )
    ]
    removed = before - len(missions_data["missions"])
    if removed:
        logger.info("[espionage] import: %d missão(ões) sintética(s) sem intel removida(s)", removed)

    # Latest DONE reportedAt per targetCityId
    latest_done_ts: dict = {}
    for m in missions_data.get("missions", []):
        if m.get("state") == "DONE" and m.get("targetCityId"):
            cid = m["targetCityId"]
            ts = (m.get("result") or {}).get("reportedAt", m.get("dispatchedAt", 0))
            if ts > latest_done_ts.get(cid, 0):
                latest_done_ts[cid] = ts

    n_failed  = 0
    n_no_data = 0
    n_no_scan = 0
    n_no_cid  = 0

    # ── Pass 1: resolve city ID for every valid report ──────────────────────────
    # resolved: list of (target_city_id, island_id_str, report)
    resolved = []
    for report in all_reports.values():
        if not report.get("success"):
            n_failed += 1
            continue
        if report.get("isArrival"):
            n_failed += 1
            continue
        target_owner = report.get("targetOwner")
        island_x     = report.get("islandX")
        island_y     = report.get("islandY")
        if not target_owner or island_x is None or island_y is None:
            n_no_data += 1
            continue

        target_city_id   = report.get("targetCityId") or ""
        city_name_report = report.get("targetCityName", "")
        island_id_str    = ""

        if not target_city_id:
            key = (target_owner.lower(), island_x, island_y)
            candidates = scan_lookup.get(key, [])
            if not candidates:
                n_no_scan += 1
                continue
            matched = next(
                (c for c in candidates if c.get("cityName", "").lower() == (city_name_report or "").lower()),
                candidates[0]
            )
            target_city_id = str(matched.get("cityId", ""))
            island_id_str  = str(matched.get("islandId", ""))
            if not target_city_id:
                n_no_cid += 1
                continue
        else:
            key = (target_owner.lower(), island_x, island_y)
            candidates = scan_lookup.get(key, [])
            if candidates:
                island_id_str = str(candidates[0].get("islandId", ""))

        resolved.append((target_city_id, island_id_str, report))

    # ── Pass 2: group by city — keep latest warehouse + latest garrison ─────────
    # warehouse: reports with resources; garrison: reports where troops is not None
    warehouse_by_city: dict = {}  # city_id → (island_id_str, report)
    garrison_by_city:  dict = {}  # city_id → report

    for target_city_id, island_id_str, report in resolved:
        reported_at = report.get("reportedAt", 0)
        if report.get("troops") is not None:
            # garrison report (troops={} means empty garrison, still a valid report)
            existing = garrison_by_city.get(target_city_id)
            if existing is None or reported_at > existing.get("reportedAt", 0):
                garrison_by_city[target_city_id] = report
        else:
            # warehouse report
            existing = warehouse_by_city.get(target_city_id)
            if existing is None or reported_at > existing[1].get("reportedAt", 0):
                warehouse_by_city[target_city_id] = (island_id_str, report)

    # ── Pass 3: build one synthetic mission per city ────────────────────────────
    all_city_ids = set(warehouse_by_city) | set(garrison_by_city)
    imported = 0
    skipped  = 0

    for target_city_id in all_city_ids:
        w_entry  = warehouse_by_city.get(target_city_id)
        g_report = garrison_by_city.get(target_city_id)

        if w_entry:
            island_id_str, w_report = w_entry
            base_report = w_report
        else:
            # garrison-only city — use garrison report as base
            island_id_str = ""
            base_report   = g_report

        reported_at = max(
            w_entry[1].get("reportedAt", 0) if w_entry else 0,
            g_report.get("reportedAt", 0)   if g_report else 0,
        ) or int(time.time())

        if reported_at <= latest_done_ts.get(target_city_id, 0):
            skipped += 1
            continue

        res    = (w_entry[1].get("resources") if w_entry else None)
        troops = g_report.get("troops") if g_report else None  # None or {} or {unit: count}

        if res and troops is not None:
            mtype = "warehouse+garrison"
        elif res:
            mtype = "warehouse"
        else:
            mtype = "garrison"

        garrison_result = None
        if g_report is not None:
            garrison_result = {
                "troops":         troops,
                "targetCityName": g_report.get("targetCityName", base_report.get("targetCityName", "")),
                "reportedAt":     g_report.get("reportedAt", reported_at),
            }

        synthetic = {
            "originCityId":       None,
            "targetCityId":       target_city_id,
            "targetIslandId":     island_id_str,
            "targetPlayerName":   base_report.get("targetOwner", ""),
            "targetCityName":     base_report.get("targetCityName", ""),
            "islandX":            base_report.get("islandX"),
            "islandY":            base_report.get("islandY"),
            "numAgents":          0,
            "state":              "DONE",
            "dispatchedAt":       reported_at,
            "arrivedAt":          reported_at,
            "executeAfter":       reported_at,
            "missionType":        mtype,
            "result": {
                "success":        True,
                "targetCityName": base_report.get("targetCityName", ""),
                "resources":      res or {},
                "reportedAt":     reported_at,
            },
            "garrisonResult":     garrison_result,
            "importedFromReport": True,
        }

        # Replace any older synthetic DONE for this city
        missions_data["missions"] = [
            m for m in missions_data["missions"]
            if not (m.get("targetCityId") == target_city_id
                    and m.get("state") == "DONE"
                    and m.get("importedFromReport"))
        ]
        missions_data["missions"].append(synthetic)
        latest_done_ts[target_city_id] = reported_at
        imported += 1

    _save_missions(missions_data)
    logger.info(
        "[espionage] import_existing_reports: %d importado(s), %d ignorado(s) "
        "(falhados=%d, sem_coords=%d, fora_scan=%d, sem_cityId=%d)",
        imported, skipped, n_failed, n_no_data, n_no_scan, n_no_cid,
    )
