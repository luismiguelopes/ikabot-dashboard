#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Combat dispatch for the ikabot empire loop, split out of espionage_manager:
- manual attack queue (shared_queue "attack" in SQLite, fed by the Flask UI)
- player pillage (sendArmyPlunderSea), naval attack (sendFleetOnBlockade) and
  own-city stationing (deployArmy/deployFleet)
- shared targeting helpers (origin picking, travel estimate, fleet classification)
  used by farm_manager
Spy missions, recalls and report parsing live in espionage_manager.
"""

import json
import math
import os
import random
import time
import unicodedata

from empire_utils import LOGS_DIR, logger

OWN_CITIES_PATH = os.path.join(LOGS_DIR, "own_cities.json")

ATTACK_QUEUE = "attack"

# _dispatch_attack outcome when the attack can't go out yet (no free ships) — not a
# failure, so the queue reschedules it instead of counting a retry.
_DEFER = "defer"


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




def _parse_journey_times(form_raw):
    """Parse real travel times out of a blockade/plunder form response (F4.b).

    The form's JS exposes `new missionController(freeTrans, capacity, transportJourneyTime, …)`
    and, per unit, `…sliders["slider_<id>"] … s.unitJourneyTime = <secs>`. All values are
    one-way seconds. Returns (transport_journey_secs|None, {unit_id: journey_secs}).
    Robust to the AJAX escaping (\\" and \\n) since it keys off digits, not quotes."""
    import re
    transport = None
    m = re.search(r'missionController\((?:\D*?\d+){2}\D*?(\d+)', form_raw)
    if m:
        transport = int(m.group(1))
    units = {}
    for blk in re.split(r'create_slider', form_raw)[1:]:
        sid = re.search(r'slider_(\d+)', blk)
        jt  = re.search(r'unitJourneyTime\s*=\s*(\d+)', blk)
        if sid and jt:
            units[sid.group(1)] = int(jt.group(1))
    return transport, units


def _fetch_form_raw(session, ikabot_config, view, origin_id, target_id):
    """POST a mission form (plunder/blockade) and return the raw response, or '' on error."""
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
        return raw or ""
    except Exception as e:
        logger.warning("[attack] fetch form view=%s falhou: %s", view, e)
        return ""


def fetch_fleet_journey(session, ikabot_config, origin_id, target_id, fleet_unit_ids=None):
    """Real one-way travel time (secs) of a blockade fleet from origin to target, read from
    the blockade form. With fleet_unit_ids, returns the max journey among those ships (the
    slowest one sets the pace); else the max over all ships. None if it can't be read."""
    _t, units = _parse_journey_times(_fetch_form_raw(session, ikabot_config, "blockade", origin_id, target_id))
    if not units:
        return None
    ids = [str(u[1:] if str(u).startswith("s") else u) for u in (fleet_unit_ids or [])]
    relevant = [units[i] for i in ids if i in units] or list(units.values())
    return max(relevant) if relevant else None


def fetch_troop_journey(session, ikabot_config, origin_id, target_id):
    """Real one-way travel time (secs) of a sea pillage (troops on trade ships) from origin
    to target, read from the plunder form's transportJourneyTime. None if unreadable."""
    transport, units = _parse_journey_times(_fetch_form_raw(session, ikabot_config, "plunder", origin_id, target_id))
    if transport:
        return transport
    return max(units.values()) if units else None


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
    Returns True on success, False on rejection, or _DEFER when there are no free ships
    (the previous raid's transporters haven't returned yet)."""
    import ikabot.config as ikabot_config

    origin_id = str(origin_id)

    # Sea pillage needs transporters; with none free the POST is doomed (type=11). Bail
    # out before the form fetch so it can be retried once the ships are back.
    capped = _cap_to_available_ships(transporters, session)
    if int(transporters) > 0 and capped <= 0:
        logger.info("[attack] sendArmyPlunderSea adiado — 0 navios livres (a regressar)")
        return _DEFER

    _change_to_origin_city(session, ikabot_config, origin_id)

    # Upkeep values are mandatory — the server rejects the POST without them
    upkeep_map = _fetch_plunder_upkeep(session, ikabot_config, origin_id, target_id)

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

        # No free ships yet — not a failure; reschedule (no attack_log, no retry count).
        # Capped so a permanently grounded fleet doesn't keep an item forever.
        if ok is _DEFER:
            deferrals = item.get("deferrals", 0) + 1
            if deferrals > 12:
                queue_remove(ATTACK_QUEUE, [item.get("id")])
                logger.warning("[attack] %s adiado %d vezes (sem navios) — removido da fila",
                               item.get("targetPlayerName"), deferrals)
            else:
                wait_min = random.randint(5, 15)
                queue_add(ATTACK_QUEUE, dict(item, deferrals=deferrals,
                          dispatchAfter=int(time.time()) + wait_min * 60))
                logger.info("[attack] %s adiado (sem navios) — nova tentativa em %d min",
                            item.get("targetPlayerName"), wait_min)
            continue

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


# ── Shared targeting helpers (used by farm_manager) ──────────────────────────

MILITARY_JSON_PATH        = os.path.join(LOGS_DIR, "military.json")

# Naval (fleet) unit name keywords, accent-stripped lowercase. A garrison spy report
# returns ARMY and FLEET units in one flat dict, and several names collide between the
# two arms (land Aríete vs naval Aríete a vapor; land Catapulta/Morteiro vs naval Barco
# Catapulta/Morteiro; land Gigante a Vapor vs naval Aríete a vapor; land Balão-bombardeiro
# vs naval Porta-balões). Each keyword below is chosen to match ONLY its naval unit and
# never a land unit — e.g. "ariete a vapor" (not "ariete"), "barco catapulta" (not
# "catapulta"), "porta-bal" (not "balao"). Matching is substring over the accent-stripped
# name (see _strip_accents), so these stay robust to accent/encoding differences.
_NAVAL_UNIT_NAMES = {
    "chamas",          # Lança-Chamas
    "ariete a vapor",  # Aríete a vapor   (NOT "ariete" → land Aríete)
    "trirreme",        # Trirreme
    "balista",         # Barco Balista
    "barco catapulta", # Barco Catapulta  (NOT "catapulta" → land Catapulta)
    "barco morteiro",  # Barco Morteiro   (NOT "morteiro" → land Morteiro)
    "foguetes",        # Lança-foguetes
    "submergivel",     # Submergível
    "lancha",          # Lancha rápida    (flees — non-combat front line)
    "porta-bal",       # Porta-balões     (NOT "balao" → land Balão-bombardeiro)
    "reparador",       # Reparador        (flees — support)
}


def _strip_accents(s):
    """Lowercase and drop diacritics so naval-name matching is accent/encoding robust."""
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower())
                   if unicodedata.category(c) != 'Mn')




def _enemy_fleet_count(garrison_troops):
    """Count naval units in an enemy garrison dict {unit_name: count}. The dict mixes army
    and fleet; only true naval units (collision-safe keywords) are counted."""
    if not garrison_troops:
        return 0
    total = 0
    for name, count in garrison_troops.items():
        norm = _strip_accents(name)
        if any(nav in norm for nav in _NAVAL_UNIT_NAMES):
            total += count
    return total


# Naval units that do NOT fight a blockade — they flee and disperse (then return hours
# later). A small combat fleet drives them off; everything else naval actually fights.
_FLEE_SHIP_NAMES = {"lancha", "reparador"}


def _classify_enemy_fleet(garrison_troops):
    """Split an enemy garrison's NAVAL units into (combat_ships, flee_ships) counts.
    flee_ships = lancha rápida / reparador (run from a blockade); combat_ships = every other
    warship (fights). Land units are ignored. Drives the F4.b decision:
      combat_ships > 0  → too dangerous, skip + alert
      else flee_ships>0 → blockade (drive them off) then pillage
      else              → troops only."""
    combat = flee = 0
    for name, count in (garrison_troops or {}).items():
        norm = _strip_accents(name)
        if not any(nav in norm for nav in _NAVAL_UNIT_NAMES):
            continue  # land unit
        if any(f in norm for f in _FLEE_SHIP_NAMES):
            flee += count
        else:
            combat += count
    return combat, flee



def _calc_travel_secs(origin_x, origin_y, target_x, target_y):
    if origin_x == target_x and origin_y == target_y:
        return 600
    return math.ceil(1200 * math.sqrt((origin_x - target_x) ** 2 + (origin_y - target_y) ** 2))


def _get_best_origin_city(target_x, target_y, military_data, needs_fleet=False,
                          required_units=None):
    """Closest own city with troops (and fleet if needs_fleet). Returns (name, id, x, y) or None.
    If required_units (a set of unit ids) is given, the city must have at least one of
    those specific units in stock — so a fixed farm loadout isn't launched from a city
    that can't actually field it."""
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

        if required_units:
            if not any(troops.get(uid, {}).get("amount", 0) > 0 for uid in required_units):
                continue
        elif not any(v.get("amount", 0) > 0 for v in troops.values()):
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

