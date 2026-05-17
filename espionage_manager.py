#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import random
import time

from empire_utils import LOGS_DIR, logger

SPY_MISSIONS_PATH       = os.path.join(LOGS_DIR, "spy_missions.json")
SPY_DISPATCH_QUEUE_PATH = os.path.join(LOGS_DIR, "spy_dispatch_queue.json")


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


# ── Public API ────────────────────────────────────────────────────────────────

def get_missions():
    return _load_missions()


def has_pending_dispatch():
    """Return True if Flask queued at least one spy dispatch."""
    try:
        return bool(_load_dispatch_queue().get("pending"))
    except Exception:
        return False


def process_dispatch_queue(session):
    """
    Called from smart_sleep. Reads spy_dispatch_queue.json, dispatches each
    pending spy, and clears the queue. Writes results to spy_missions.json.
    """
    q = _load_dispatch_queue()
    pending = q.get("pending", [])
    if not pending:
        return

    for i, item in enumerate(pending):
        if i > 0:
            delay = random.randint(15, 35)
            logger.info("[espionage] waiting %ds before next dispatch", delay)
            time.sleep(delay)

        ok, result = _dispatch_spy(
            session,
            origin_city_id=item["originCityId"],
            target_city_id=item["targetCityId"],
            target_island_id=item["islandId"],
            target_player_name=item["targetPlayerName"],
            target_city_name=item["targetCityName"],
            island_x=item["islandX"],
            island_y=item["islandY"],
            num_agents=item.get("numAgents", 1),
            num_decoys=item.get("numDecoys", 0),
        )
        if not ok:
            failed_mission = {
                "originCityId":     str(item["originCityId"]),
                "targetCityId":     str(item["targetCityId"]),
                "targetIslandId":   str(item["islandId"]),
                "targetPlayerName": item["targetPlayerName"],
                "targetCityName":   item["targetCityName"],
                "islandX":          item["islandX"],
                "islandY":          item["islandY"],
                "numAgents":        item.get("numAgents", 1),
                "state":            "FAILED",
                "error":            result,
                "dispatchedAt":     int(time.time()),
                "arrivedAt":        None,
                "executeAfter":     None,
                "missionType":      None,
                "result":           None,
            }
            data = _load_missions()
            data["missions"].append(failed_mission)
            _save_missions(data)
            logger.warning("[espionage] dispatch failed → saved as FAILED for %s: %s",
                           item["targetPlayerName"], result)

    q["pending"] = []
    _save_dispatch_queue(q)


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

        # Always refresh the CSRF token from the response before checking success
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
