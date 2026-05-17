#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import random
import re
import time

from empire_utils import LOGS_DIR, logger

SPY_MISSIONS_PATH       = os.path.join(LOGS_DIR, "spy_missions.json")
SPY_DISPATCH_QUEUE_PATH = os.path.join(LOGS_DIR, "spy_dispatch_queue.json")
SPY_COUNTS_PATH         = os.path.join(LOGS_DIR, "spy_counts.json")


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
        return {"lastUpdated": 0, "counts": {}}


def _save_spy_counts(counts_by_city_id):
    os.makedirs(LOGS_DIR, exist_ok=True)
    data = _load_spy_counts()
    data["lastUpdated"] = int(time.time())
    data["counts"].update(counts_by_city_id)
    with open(SPY_COUNTS_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ── Safehouse pre-check ───────────────────────────────────────────────────────

def _fetch_available_spies(session, origin_city_id):
    """
    Open the safehouse tab for origin_city_id and parse available agent count.
    Returns int or None if count cannot be determined.
    Also refreshes ikabot_config.actionRequest from the response.
    """
    import ikabot.config as ikabot_config

    delay = random.randint(3, 8)
    logger.info("[espionage] waiting %ds before safehouse check (city %s)", delay, origin_city_id)
    time.sleep(delay)

    params = {
        "view": "safehouse",
        "cityId": origin_city_id,
        "backgroundView": "city",
        "currentCityId": origin_city_id,
        "tab": "tabSafehouse",
        "actionRequest": ikabot_config.actionRequest,
        "ajax": 1,
    }

    try:
        resp = session.post(params=params)
        resp_data = json.loads(resp, strict=False)
    except Exception as e:
        logger.error("[espionage] safehouse fetch failed for city %s: %s", origin_city_id, e)
        return None

    # Refresh CSRF token
    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "updateGlobalData":
            new_token = entry[1].get("actionRequest") if isinstance(entry[1], dict) else None
            if new_token:
                ikabot_config.actionRequest = new_token
            break

    # Collect all text from the response to search for agent count
    all_text = ""
    for entry in resp_data:
        if isinstance(entry, list) and len(entry) >= 2:
            if entry[0] == "changeView" and isinstance(entry[1], list):
                for part in entry[1]:
                    if isinstance(part, str):
                        all_text += part
            elif entry[0] == "updateTemplateData" and isinstance(entry[1], dict):
                all_text += json.dumps(entry[1])

    if not all_text:
        logger.warning("[espionage] safehouse response has no text content for city %s", origin_city_id)
        return None

    # Log first 800 chars so we can identify the agent count pattern
    logger.info("[espionage] safehouse content (city %s) [first 800]: %s",
                origin_city_id, all_text[:800])

    # Try known patterns (we'll refine these after seeing the logs)
    patterns = [
        r'(\d+)\s+agente[s]?\s+disponíve',         # "X agentes disponíveis"
        r'agente[s]?\s+disponíve[is]+\D{0,20}(\d+)',
        r'disponíve[is]+\D{0,20}(\d+)\s+agente',
        r'"availableAgents"\s*:\s*(\d+)',
        r'available[Aa]gents["\s:]+(\d+)',
        r'"agents"\s*:\s*(\d+)',
        r'agentsAvailable["\s:]+(\d+)',
        r'spiesAvailable["\s:]+(\d+)',
        r'(\d+)\s+espi[ãa][o]?\s+disponíve',
    ]
    for pattern in patterns:
        m = re.search(pattern, all_text, re.IGNORECASE)
        if m:
            count = int(m.group(1))
            logger.info("[espionage] city %s: %d agents available (pattern: %s)",
                        origin_city_id, count, pattern)
            return count

    logger.warning("[espionage] could not parse agent count for city %s — "
                   "check the [first 800] log above to identify the right pattern",
                   origin_city_id)
    return None


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
    Called from smart_sleep. For each pending spy dispatch:
      1. Pre-check available agents at origin city (GET safehouse).
      2. Skip with FAILED if not enough agents.
      3. Dispatch if OK.
    Clears the queue regardless of outcome.
    """
    q = _load_dispatch_queue()
    pending = q.get("pending", [])
    if not pending:
        return

    counts_to_save = {}

    for i, item in enumerate(pending):
        if i > 0:
            delay = random.randint(15, 35)
            logger.info("[espionage] waiting %ds before next dispatch", delay)
            time.sleep(delay)

        origin_id = str(item["originCityId"])
        num_agents = item.get("numAgents", 1)

        # Pre-check: how many agents are available?
        available = _fetch_available_spies(session, origin_id)
        if available is not None:
            counts_to_save[origin_id] = available

        if available is not None and available < num_agents:
            error_msg = (f"Sem agentes suficientes em cidade {origin_id} "
                         f"({available} disponíveis, {num_agents} necessários)")
            logger.warning("[espionage] %s — skipping dispatch to %s",
                           error_msg, item["targetPlayerName"])
            _append_failed_mission(item, error_msg)
            continue

        ok, result = _dispatch_spy(
            session,
            origin_city_id=item["originCityId"],
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
            logger.warning("[espionage] dispatch failed → saved as FAILED for %s: %s",
                           item["targetPlayerName"], result)
        else:
            # Decrement local count so next dispatch in same batch uses updated estimate
            if available is not None:
                counts_to_save[origin_id] = max(0, available - num_agents)

    if counts_to_save:
        _save_spy_counts(counts_to_save)

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

        # Always refresh the CSRF token from the response
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
            logger.warning("[espionage] dispatch failed — raw: %s", resp[:300])
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

    logger.info("[espionage] %d spy(s) dispatched → %s (%s)",
                num_agents, target_player_name, target_city_name)
    return True, mission
