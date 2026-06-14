#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Combat dispatch for the ikabot empire loop, split out of espionage_manager:
- manual attack queue (shared_queue "attack" in SQLite, fed by the Flask UI)
- player pillage (sendArmyPlunderSea), naval attack (sendFleetOnBlockade) and
  own-city stationing (deployArmy/deployFleet)
- auto-attack wave planning and dispatch
Spy missions, recalls and report parsing live in espionage_manager.
"""

import json
import math
import os
import random
import time
import uuid

from empire_utils import LOGS_DIR, logger

OWN_CITIES_PATH = os.path.join(LOGS_DIR, "own_cities.json")

ATTACK_QUEUE = "attack"


def _attack_queue_items():
    try:
        from db_manager import queue_items
        return queue_items(ATTACK_QUEUE)
    except Exception:
        logger.error("[attack] leitura da fila falhou", exc_info=True)
        return []


def has_pending_attacks():
    return bool(_attack_queue_items())


def has_due_attacks():
    """True only if at least one pending attack has reached its dispatchAfter time.
    smart_sleep must use this (not has_pending_attacks) — otherwise a future-scheduled
    attack makes the wait loop spin without sleeping until the attack is due."""
    try:
        now = int(time.time())
        return any(int(it.get("dispatchAfter", 0)) <= now
                   for it in _attack_queue_items())
    except Exception:
        return False




def _fetch_plunder_upkeep(session, ikabot_config, origin_id, target_id):
    """Fetch the plunder form for a player city.
    Returns dict of {unit_id: upkeep_str} using the IDs the game expects (e.g. '303', not 's303')."""
    import re
    try:
        raw = session.post(params={
            "view":              "plunder",
            "isMission":         "1",
            "destinationCityId": str(target_id),
            "backgroundView":    "city",
            "currentCityId":     str(origin_id),
            "actionRequest":     ikabot_config.actionRequest,
            "ajax":              1,
        })
        time.sleep(random.randint(2, 5))
        upkeep = {}
        for m in re.finditer(r'name=\\"cargo_army_([^\\]+)_upkeep\\"[^>]*value=\\"([^\\"]*)\\"', raw):
            upkeep[m.group(1)] = m.group(2)
        logger.info("[attack] plunder form: %d tipo(s) de unidade", len(upkeep))
        return upkeep
    except Exception as e:
        logger.warning("[attack] _fetch_plunder_upkeep falhou: %s", e)
        return {}


def _fetch_deployment_upkeep(session, ikabot_config, origin_id, target_id, deployment, cargo_prefix):
    """Fetch the deployment form to get unit upkeep values required by the game.
    Returns dict of {unit_id: upkeep_str} for all unit types present in the form."""
    import re
    try:
        raw = session.post(params={
            "view":             "deployment",
            "deploymentType":   deployment,
            "destinationCityId": str(target_id),
            "backgroundView":   "city",
            "currentCityId":    str(origin_id),
            "actionRequest":    ikabot_config.actionRequest,
            "ajax":             1,
        })
        time.sleep(random.randint(2, 5))
        # The response is a raw JSON string; HTML quotes are escaped as \"
        upkeep = {}
        for m in re.finditer(
            r'name=\\"' + re.escape(cargo_prefix) + r'_([^\\]+)_upkeep\\"[^>]*value=\\"([^\\"]*)\\"',
            raw
        ):
            upkeep[m.group(1)] = m.group(2)
        logger.info("[attack] deployment form: %d tipo(s) de unidade com upkeep", len(upkeep))
        return upkeep
    except Exception:
        logger.warning("[attack] falha ao obter deployment form — a continuar sem upkeep", exc_info=True)
        return {}


def _change_to_origin_city(session, ikabot_config, origin_id):
    """Switch session context to the origin city before any dispatch — without this
    the game responds with activeTab:"" and the dispatch fails."""
    try:
        session.post(params={
            "action":         "header",
            "function":       "changeCurrentCity",
            "actionRequest":  ikabot_config.actionRequest,
            "oldView":        "city",
            "cityId":         str(origin_id),
            "backgroundView": "city",
            "currentCityId":  str(origin_id),
            "ajax":           "1",
        })
        time.sleep(random.randint(3, 7))
    except Exception:
        pass


# Last rejection text from the game — read by _log_attack_attempt right after a dispatch
_last_feedback_text = ""


def _parse_attack_feedback(resp, function, ikabot_config):
    """Parse an attack POST response: refresh CSRF token, return True on type=10.
    Logs the game's feedback text on rejection for diagnosability."""
    global _last_feedback_text
    resp_data = json.loads(resp, strict=False)

    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "updateGlobalData":
            tok = entry[1].get("actionRequest") if isinstance(entry[1], dict) else None
            if tok:
                ikabot_config.actionRequest = tok
            break

    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "provideFeedback":
            fb_list = entry[1] if isinstance(entry[1], list) else [entry[1]]
            types = [fb.get("type") if isinstance(fb, dict) else fb for fb in fb_list]
            if 10 in types:
                _last_feedback_text = ""
                return True
            texts = [fb.get("text", "") for fb in fb_list if isinstance(fb, dict)]
            _last_feedback_text = " | ".join(t for t in texts if t) or f"types={types}"
            logger.warning("[attack] %s recusado types=%s — %s", function, types,
                           _last_feedback_text)
            return False
    _last_feedback_text = "sem provideFeedback na resposta"
    logger.warning("[attack] %s sem provideFeedback — raw: %.400s", function, resp)
    return False


def _log_attack_attempt(item, ok, source="manual"):
    """Persist one dispatch attempt in the attack_log table (F1 — attack history)."""
    try:
        from db_manager import log_attack
        log_attack({
            "originCity":   item.get("originCityName") or str(item.get("originCityId", "")),
            "targetCity":   item.get("targetCityName", ""),
            "targetPlayer": item.get("targetPlayerName", ""),
            "islandX":      item.get("islandX"),
            "islandY":      item.get("islandY"),
            "missionType":  item.get("missionType", "army"),
            "targetType":   item.get("targetType", "enemy"),
            "source":       source,
            "units":        item.get("units"),
            "transporters": item.get("transporters", 0),
            "success":      ok,
            "error":        None if ok else (_last_feedback_text or "dispatch falhou"),
        })
    except Exception:
        logger.warning("[attack] registo no attack_log falhou", exc_info=True)


def _cap_to_available_ships(requested, session=None):
    """transporter > available ships → server rejects with type=11. Cap it.
    Prefers a LIVE count from the game at dispatch time — statusSummary.json can be
    up to an empire cycle (~1h) stale, and ships busy at scheduling time may be back."""
    requested = int(requested)
    available = None
    if session is not None:
        try:
            from ikabot.helpers.naval import getAvailableShips
            available = int(getAvailableShips(session))
            time.sleep(random.randint(2, 5))
        except Exception:
            available = None
    if available is None:
        try:
            with open(os.path.join(LOGS_DIR, "statusSummary.json")) as _f:
                available = int(json.load(_f).get("ships", {}).get("available", requested))
        except Exception:
            available = requested
    capped = min(requested, available)
    if capped < requested:
        logger.info("[attack] transporters limitados a %d (pedidos %d, livres %d)",
                    capped, requested, available)
    return capped


def _send_army_plunder(session, origin_id, target_id, island_id, units, transporters):
    """Player pillage via sendArmyPlunderSea. deployArmy does NOT work here — it only
    stations troops in own/allied cities. Accepts unit IDs with or without the CSS
    's' prefix (military.json stores 's303', the game API expects '303').
    Returns True on success (provideFeedback type=10)."""
    import ikabot.config as ikabot_config

    origin_id = str(origin_id)
    _change_to_origin_city(session, ikabot_config, origin_id)

    # Upkeep values are mandatory — the server rejects the POST without them
    upkeep_map = _fetch_plunder_upkeep(session, ikabot_config, origin_id, target_id)

    capped = _cap_to_available_ships(transporters, session)

    units_api = {(uid[1:] if uid.startswith("s") else uid): int(cnt)
                 for uid, cnt in units.items()}

    params = {
        "action":            "transportOperations",
        "function":          "sendArmyPlunderSea",
        "actionRequest":     ikabot_config.actionRequest,
        "islandId":          str(island_id),
        "destinationCityId": str(target_id),
        "backgroundView":    "city",
        "currentCityId":     origin_id,
        "templateView":      "plunder",
        "transporter":       capped,
        "ajax":              1,
    }
    # All unit types from form with upkeep (0 for units not being sent)
    for uid, upkeep in upkeep_map.items():
        params[f"cargo_army_{uid}_upkeep"] = upkeep
        params[f"cargo_army_{uid}"] = units_api.get(uid, 0)
    # Override with user selections (handles units not in form)
    for uid, cnt in units_api.items():
        params[f"cargo_army_{uid}"] = cnt

    logger.info("[attack] sendArmyPlunderSea %s → %s: %d unidade(s), transporter=%d",
                origin_id, target_id, sum(units_api.values()), capped)
    try:
        resp = session.post(params=params)
        return _parse_attack_feedback(resp, "sendArmyPlunderSea", ikabot_config)
    except Exception as e:
        logger.error("[attack] sendArmyPlunderSea exception: %s", e, exc_info=True)
        return False


def _fetch_blockade_form(session, ikabot_config, origin_id, target_id):
    """Fetch the naval-attack (port blockade) form for a player city.
    Tries candidate view names and extracts upkeep values plus the real function name
    from the form itself — same self-discovery approach that found sendArmyPlunderSea.
    Returns (upkeep_dict, function_name_or_None, view_used)."""
    import re
    for view in ("blockade", "blockadeHarbour"):
        try:
            raw = session.post(params={
                "view":              view,
                "isMission":         "1",
                "destinationCityId": str(target_id),
                "backgroundView":    "city",
                "currentCityId":     str(origin_id),
                "actionRequest":     ikabot_config.actionRequest,
                "ajax":              1,
            })
            time.sleep(random.randint(2, 5))
        except Exception as e:
            logger.warning("[attack] _fetch_blockade_form(%s) falhou: %s", view, e)
            continue

        upkeep = {}
        for m in re.finditer(r'name=\\"cargo_fleet_([^\\]+)_upkeep\\"[^>]*value=\\"([^\\"]*)\\"', raw):
            upkeep[m.group(1)] = m.group(2)
        fn_m = re.search(r'name=\\"function\\"[^>]*value=\\"(\w+)\\"', raw)
        fn = fn_m.group(1) if fn_m else None

        if upkeep or fn:
            logger.info("[attack] blockade form (view=%s): %d tipo(s) de unidade, function=%s",
                        view, len(upkeep), fn)
            return upkeep, fn, view

        # Diagnostic: log the form's input names so the real API can be identified
        inputs = re.findall(r'name=\\"([^\\"]+)\\"', raw)[:40]
        logger.info("[attack] blockade form (view=%s) sem campos esperados — inputs: %s",
                    view, inputs)
    return {}, None, "blockade"


def _send_fleet_blockade(session, origin_id, target_id, island_id, units):
    """Naval attack (port blockade) against a player city. deployFleet does NOT work
    here — it only stations ships in own/allied cities. The function name is taken
    from the form when present (expected sendFleetBlockadeSea).
    Returns True on success (provideFeedback type=10)."""
    import ikabot.config as ikabot_config

    origin_id = str(origin_id)
    _change_to_origin_city(session, ikabot_config, origin_id)

    upkeep_map, form_fn, view = _fetch_blockade_form(session, ikabot_config, origin_id, target_id)
    function = form_fn or "sendFleetBlockadeSea"

    units_api = {(uid[1:] if uid.startswith("s") else uid): int(cnt)
                 for uid, cnt in units.items()}

    params = {
        "action":            "transportOperations",
        "function":          function,
        "actionRequest":     ikabot_config.actionRequest,
        "islandId":          str(island_id),
        "destinationCityId": str(target_id),
        "backgroundView":    "city",
        "currentCityId":     origin_id,
        "templateView":      view,
        "ajax":              1,
    }
    for uid, upkeep in upkeep_map.items():
        params[f"cargo_fleet_{uid}_upkeep"] = upkeep
        params[f"cargo_fleet_{uid}"] = units_api.get(uid, 0)
    for uid, cnt in units_api.items():
        params[f"cargo_fleet_{uid}"] = cnt

    logger.info("[attack] %s %s → %s: %d unidade(s) naval(is)",
                function, origin_id, target_id, sum(units_api.values()))
    try:
        resp = session.post(params=params)
        return _parse_attack_feedback(resp, function, ikabot_config)
    except Exception as e:
        logger.error("[attack] %s exception: %s", function, e, exc_info=True)
        return False


def _send_deploy(session, origin_id, target_id, island_id, units, transporters, kind):
    """Station troops/ships in an OWN (or allied) city via deployArmy/deployFleet.
    Unlike the plunder/blockade forms, the deployment form uses the CSS-style unit
    IDs (s303), so unit IDs are passed through unchanged.
    Returns True on success (provideFeedback type=10)."""
    import ikabot.config as ikabot_config

    origin_id    = str(origin_id)
    function     = "deployArmy" if kind == "army" else "deployFleet"
    cargo_prefix = "cargo_army" if kind == "army" else "cargo_fleet"

    _change_to_origin_city(session, ikabot_config, origin_id)
    upkeep_map = _fetch_deployment_upkeep(
        session, ikabot_config, origin_id, target_id, kind, cargo_prefix)

    params = {
        "action":            "transportOperations",
        "function":          function,
        "actionRequest":     ikabot_config.actionRequest,
        "islandId":          str(island_id),
        "destinationCityId": str(target_id),
        "deploymentType":    kind,
        "backgroundView":    "city",
        "currentCityId":     origin_id,
        "templateView":      "deployment",
        "ajax":              1,
    }
    if kind == "army":
        params["transporter"] = _cap_to_available_ships(transporters, session)

    for uid, upkeep in upkeep_map.items():
        params[f"{cargo_prefix}_{uid}_upkeep"] = upkeep
        params[f"{cargo_prefix}_{uid}"] = int(units.get(uid, 0))
    for uid, cnt in units.items():
        params[f"{cargo_prefix}_{uid}"] = int(cnt)

    logger.info("[attack] %s %s → %s: %d unidade(s)",
                function, origin_id, target_id, sum(int(c) for c in units.values()))
    try:
        resp = session.post(params=params)
        return _parse_attack_feedback(resp, function, ikabot_config)
    except Exception as e:
        logger.error("[attack] %s exception: %s", function, e, exc_info=True)
        return False


def _dispatch_attack(session, item):
    """Dispatch a combat movement.
    Enemy city: army → sendArmyPlunderSea, fleet → port blockade.
    Own city:   deployArmy/deployFleet (stationing)."""
    origin_id    = str(item["originCityId"])
    mission_type = item.get("missionType", "army")
    target_type  = item.get("targetType", "enemy")

    if target_type == "own":
        logger.info("[attack] a estacionar %s → cidade própria %s",
                    mission_type, item.get("targetCityName"))
        return _send_deploy(session, origin_id, item["targetCityId"],
                            item["islandId"], item.get("units", {}),
                            item.get("transporters", 0), mission_type)

    if mission_type == "army":
        logger.info("[attack] a despachar army → %s (%s)",
                    item.get("targetCityName"), item.get("targetPlayerName"))
        return _send_army_plunder(session, origin_id, item["targetCityId"],
                                  item["islandId"], item.get("units", {}),
                                  item.get("transporters", 0))

    logger.info("[attack] a despachar fleet → %s (%s)",
                item.get("targetCityName"), item.get("targetPlayerName"))
    return _send_fleet_blockade(session, origin_id, item["targetCityId"],
                                item["islandId"], item.get("units", {}))


def process_attack_queue(session, in_active_hours=True):
    """Dispatch attacks whose dispatchAfter has been reached.
    Each item is removed from (or rescheduled in) the SQLite queue immediately after
    being handled, so items queued by Flask mid-loop are untouched — no save-back race."""
    if not in_active_hours:
        return
    from empire_utils import is_paused
    if is_paused():
        logger.info("[pause] em pausa — fila de ataques ignorada")
        return

    pending = _attack_queue_items()
    if not pending:
        return

    try:
        from db_manager import queue_add, queue_remove
    except Exception:
        logger.error("[attack] db_manager indisponível — fila não processada", exc_info=True)
        return

    dispatched = 0
    for item in pending:
        if int(time.time()) < item.get("dispatchAfter", 0):
            continue

        if dispatched > 0:
            delay = random.randint(30, 90)
            logger.info("[attack] aguardar %ds antes do próximo ataque", delay)
            time.sleep(delay)

        ok = _dispatch_attack(session, item)
        dispatched += 1
        _log_attack_attempt(item, ok)
        if ok:
            queue_remove(ATTACK_QUEUE, [item.get("id")])
            logger.info("[attack] ataque despachado → %s (%s)",
                        item.get("targetPlayerName"), item.get("targetCityName"))
            try:
                from telegram_notifier import notify_attack_dispatched
                notify_attack_dispatched(item.get("originCityName", "?"),
                                         item.get("targetCityName", "?"),
                                         item.get("targetPlayerName", "?"),
                                         item.get("missionType", "army"))
            except Exception:
                pass
        else:
            retries = item.get("retries", 0) + 1
            if retries >= 3:
                queue_remove(ATTACK_QUEUE, [item.get("id")])
                logger.warning("[attack] dispatch falhou %d vezes para %s — removido da fila",
                               retries, item.get("targetPlayerName"))
                try:
                    from telegram_notifier import notify_attack_failed
                    notify_attack_failed(item.get("targetCityName", "?"),
                                         item.get("targetPlayerName", "?"), retries)
                except Exception:
                    pass
            else:
                retry_mins = random.randint(5, 15)
                queue_add(ATTACK_QUEUE, dict(item, retries=retries,
                          dispatchAfter=int(time.time()) + retry_mins * 60))
                logger.warning("[attack] dispatch falhou para %s (tentativa %d/3) — "
                               "nova tentativa em %d min",
                               item.get("targetPlayerName"), retries, retry_mins)


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

    from espionage_manager import _load_missions
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
            "targetCityName":   m.get("targetCityName", ""),
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
    """Naval strike to clear the enemy port before an army wave. Uses the blockade
    mission — deployFleet only stations ships in own/allied cities."""
    return _send_fleet_blockade(session, origin_id, target_id, island_id, fleet_units)


def _dispatch_army_wave(session, origin_id, target_id, island_id, troop_units, transporters):
    """Pillage wave against a player city. Uses sendArmyPlunderSea — deployArmy only
    stations troops in own/allied cities and the server rejects it for attacks."""
    return _send_army_plunder(session, origin_id, target_id, island_id,
                              troop_units, transporters)


def _log_wave_attempt(plan, wave, mission_type, ok):
    """attack_log entry for an auto-attack wave dispatch."""
    _log_attack_attempt({
        "originCityName":   wave.get("originCityName"),
        "originCityId":     wave.get("originCityId"),
        "targetCityName":   plan.get("targetCityName", ""),
        "targetPlayerName": plan.get("targetPlayerName", ""),
        "islandX":          plan.get("islandX"),
        "islandY":          plan.get("islandY"),
        "missionType":      mission_type,
        "units":            wave.get("fleetUnits" if mission_type == "fleet" else "troopUnits"),
        "transporters":     wave.get("transporters", 0) if mission_type == "army" else 0,
    }, ok, source="auto")


def process_auto_attack_waves(session, in_active_hours=True):
    """Dispatch pending attack wave plans: fleet (tier 2) then army."""
    if not in_active_hours:
        return
    from empire_utils import is_paused
    if is_paused():
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
                    _log_wave_attempt(plan, wave, "fleet", ok)
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
                    _log_wave_attempt(plan, wave, "army", ok)
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
                    _log_wave_attempt(plan, wave, "army", ok)
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
