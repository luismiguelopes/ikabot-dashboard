#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""F14 — autonomous spy training.

Keeps every safehouse topped up to its capacity (or to a fixed per-city target) by issuing
the game's own `buildSpy` order — the form on the safehouse tab:

    action=Espionage  function=buildSpy  cityId  position  textfield_spy=<n>

Cost per spy is gold + crystal (150 / 40 at the time of writing; read from the page so a
change in the game is picked up). Brakes mirror the wine buyer: a global gold floor, a
per-city crystal floor (default 0 — the consolidation buffer exists for spies) ON TOP of what
the building queue has reserved, a per-pass cap and a
minimum interval between passes. `dryRun` (default on) plans from the counts the bot already
fetched and sends nothing to the game.

Counts come from spy_counts.json, refreshed by fetch_spy_counts() right before this runs in
the same cycle — `freeSlots` (empty slots) and `orderMax` (the train slider's max) are what
the game itself says may be trained now, so no extra page load is needed per order.
"""

import json
import os
import random
import time

from empire_utils import LOGS_DIR, logger
from empire_utils import atomic_write_json

SPY_BUILD_SETTINGS_PATH = os.path.join(LOGS_DIR, "spy_build_settings.json")
SPY_BUILD_STATUS_PATH   = os.path.join(LOGS_DIR, "spy_build_status.json")
_SPY_COUNTS_PATH        = os.path.join(LOGS_DIR, "spy_counts.json")
_OWN_CITIES_PATH        = os.path.join(LOGS_DIR, "own_cities.json")
_STATUS_SUMMARY_PATH    = os.path.join(LOGS_DIR, "statusSummary.json")

DEFAULT_SPY_BUILD_SETTINGS = {
    "enabled":         True,     # on, but…
    "dryRun":          True,     # …only plans until a supervised live order validates it
    "targetPerCity":   0,        # 0 = fill to the safehouse capacity; N = keep N per city
    "goldFloor":       200000,   # never let gold drop below this
    "crystalFloor":    0,        # per city, on top of building-queue reservations. 0 on purpose:
                                 # consolidation leaves a 5000 crystal buffer in every city
                                 # precisely so spies can be trained from it
    "maxPerPass":      60,       # spies ordered per pass, all cities together
    "intervalMinutes": 60,       # min gap between passes (a human doesn't train every cycle)
    "maxCountsAgeMinutes": 30,   # never plan from a stale safehouse read
}
GOLD_PER_SPY    = 150
CRYSTAL_PER_SPY = 40



def load_settings():
    s = dict(DEFAULT_SPY_BUILD_SETTINGS)
    try:
        with open(SPY_BUILD_SETTINGS_PATH) as f:
            d = json.load(f)
        if isinstance(d, dict):
            s.update({k: d[k] for k in DEFAULT_SPY_BUILD_SETTINGS if k in d})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return s


def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_status(status, now=None):
    try:
        status["at"] = int(time.time() if now is None else now)
        atomic_write_json(SPY_BUILD_STATUS_PATH, status, indent=2)
    except Exception:
        pass


def _city_need(c, target):
    """Spies to order for one city: empty slots (fill mode) or the gap to `target`, capped by
    what the game's train slider allows right now."""
    cap  = int(c.get("trainable") or 0)
    free = int(c.get("freeSlots") or 0)
    if cap <= 0 or free <= 0:
        return 0
    want = free if target <= 0 else max(0, min(target, cap) - (cap - free))
    order_max = c.get("orderMax")
    if order_max is not None:
        want = min(want, int(order_max))
    return max(0, want)


def plan_spy_builds(counts, own_cities, resources, reserved, gold, settings,
                    gold_per_spy=GOLD_PER_SPY, crystal_per_spy=CRYSTAL_PER_SPY):
    """Pure planner. Returns (orders, notes):
    orders = [{cityId, name, position, amount, gold, crystal}], biggest need first;
    notes  = {cityName: why it got less than it needs} for the status/UI."""
    target = int(settings.get("targetPerCity", 0) or 0)
    gold_budget = max(0, int(gold) - int(settings["goldFloor"]))
    left = int(settings["maxPerPass"])
    by_id = {str(c.get("cityId")): c for c in own_cities}
    wants = []
    for cid, c in (counts or {}).items():
        city = by_id.get(str(cid))
        if not city or city.get("safehousePosition") is None:
            continue
        need = _city_need(c, target)
        if need > 0:
            wants.append((need, str(cid), city))
    wants.sort(key=lambda w: -w[0])

    orders, notes = [], {}
    for need, cid, city in wants:
        name = city.get("name", cid)
        if left <= 0:
            notes[name] = "limite por passagem"
            continue
        crystal = int((resources.get(name) or {}).get("Crystal", 0) or 0)
        spare_crystal = crystal - int(reserved.get(name, 0)) - int(settings["crystalFloor"])
        limits = {"limite por passagem": left,
                  "cristal no piso": max(0, spare_crystal) // crystal_per_spy,
                  "ouro no piso": gold_budget // gold_per_spy}
        n = min(need, *limits.values())
        if n < need:
            notes[name] = f"{n}/{need} — {min(limits, key=limits.get)}"
        if n <= 0:
            continue
        orders.append({"cityId": cid, "name": name, "position": city["safehousePosition"],
                       "amount": n, "gold": n * gold_per_spy, "crystal": n * crystal_per_spy})
        gold_budget -= n * gold_per_spy
        left -= n
    return orders, notes


def _crystal_reserved():
    """Crystal ('glass', index 3) the building queue has claimed per city."""
    try:
        from queue_processor import (_load_queue, _load_empire_json, _calc_city_reserved)
        from db_manager import get_building_costs
        queues = _load_queue().get("queues", {})
        empire = _load_empire_json()
        costs = get_building_costs()
        return {name: int(_calc_city_reserved(name, queues, empire, costs)[3])
                for name in queues}
    except Exception:
        return {}


def _feedback(resp_data):
    """(ok, text) from a game AJAX response; refreshes the CSRF token on the way."""
    import ikabot.config as ikabot_config
    ok, texts = False, []
    for entry in resp_data:
        if not isinstance(entry, list) or not entry:
            continue
        if entry[0] == "updateGlobalData" and isinstance(entry[1], dict):
            tok = entry[1].get("actionRequest")
            if tok:
                ikabot_config.actionRequest = tok
        if entry[0] == "provideFeedback":
            for fb in (entry[1] if isinstance(entry[1], list) else [entry[1]]):
                if isinstance(fb, dict):
                    if fb.get("type") == 10:
                        ok = True
                    texts.append(str(fb.get("text") or fb.get("locakey") or ""))
    return ok, " | ".join(t for t in texts if t)


def _order_spies(session, order):
    """Switch to the city, then submit the safehouse buildSpy form. Returns (ok, reason)."""
    import ikabot.config as ikabot_config
    cid = order["cityId"]
    try:
        session.post(params={
            "action": "header", "function": "changeCurrentCity",
            "actionRequest": ikabot_config.actionRequest, "oldView": "city",
            "cityId": cid, "backgroundView": "city", "currentCityId": cid, "ajax": "1",
        })
        time.sleep(random.randint(2, 5))
        resp = session.post(params={
            "action": "Espionage", "function": "buildSpy",
            "cityId": cid, "position": str(order["position"]),
            "textfield_spy": str(order["amount"]),
            "backgroundView": "city", "currentCityId": cid, "templateView": "safehouse",
            "actionRequest": ikabot_config.actionRequest, "ajax": "1",
        })
        ok, text = _feedback(json.loads(resp, strict=False))
        return ok, text or "sem feedback do servidor"
    except Exception as e:
        return False, f"erro: {e}"


def process_spy_builder(session, in_active_hours=True, now=None, force_preview=False):
    """One pass of the spy trainer. Called right after fetch_spy_counts() in the cycle.
    `force_preview` (UI button): plan now in dry-run from the cached counts — no game
    request, ignores enabled/interval/active hours, no alert, doesn't reset the interval."""
    now = time.time() if now is None else now
    settings = load_settings()
    if not force_preview:
        if not settings["enabled"] or not in_active_hours:
            return
        try:
            from empire_utils import is_paused
            if is_paused():
                return
        except Exception:
            pass
        last_pass = int(_load_json(SPY_BUILD_STATUS_PATH, {}).get("lastPassAt", 0) or 0)
        if now - last_pass < int(settings["intervalMinutes"]) * 60:
            return

    data = _load_json(_SPY_COUNTS_PATH, {})
    age_min = (now - int(data.get("lastUpdated", 0) or 0)) / 60
    if age_min > int(settings["maxCountsAgeMinutes"]) and not force_preview:
        logger.info("[spy-build] contagens dos espiões com %dmin — a saltar", age_min)
        return

    dry = bool(settings["dryRun"]) or force_preview
    prev_pass = int(_load_json(SPY_BUILD_STATUS_PATH, {}).get("lastPassAt", 0) or 0)
    summary = _load_json(_STATUS_SUMMARY_PATH, {})
    gold = int(((summary.get("gold") or {}).get("total")) or 0)
    orders, notes = plan_spy_builds(data.get("byCityId", {}), _load_json(_OWN_CITIES_PATH, []),
                                    _load_json(os.path.join(LOGS_DIR, "resources.json"), {}),
                                    _crystal_reserved(), gold, settings)
    free_total = sum(int(c.get("freeSlots") or 0) for c in data.get("byCityId", {}).values())

    done, failed = [], []
    for i, o in enumerate(orders):
        if dry:
            logger.info("[spy-build][dry] treinaria %d espião(ões) em %s (%d ouro, %d cristal)",
                        o["amount"], o["name"], o["gold"], o["crystal"])
            done.append(o)
            continue
        if i:
            time.sleep(random.randint(10, 25))
        ok, reason = _order_spies(session, o)
        if ok:
            logger.info("[spy-build] %d espião(ões) em treino em %s (%d ouro, %d cristal)",
                        o["amount"], o["name"], o["gold"], o["crystal"])
            done.append(o)
        else:
            logger.warning("[spy-build] treino recusado em %s: %s", o["name"], reason)
            failed.append(dict(o, reason=reason))

    _write_status({"dryRun": dry, "preview": force_preview, "countsAgeMinutes": int(age_min),
                   "lastPassAt": prev_pass if force_preview else int(now),
                   "gold": gold, "freeSlots": free_total,
                   "ordered": sum(o["amount"] for o in done),
                   "spentGold": sum(o["gold"] for o in done),
                   "spentCrystal": sum(o["crystal"] for o in done),
                   "orders": done, "failed": failed, "notes": notes}, now=now)
    if (done or failed) and not force_preview:
        try:
            from telegram_notifier import notify_spies_trained
            notify_spies_trained(done, failed, dry)
        except Exception:
            pass
