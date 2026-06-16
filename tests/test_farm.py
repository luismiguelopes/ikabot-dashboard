"""
Tests for target farming (F4): db_manager farm CRUD + farm_manager state machine.
Run with: python -m pytest tests/ -v
"""
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub telegram for attack_manager import chain
if "telegram_notifier" not in sys.modules:
    _tg = types.ModuleType("telegram_notifier")
    _tg.notify_attack_dispatched = lambda *a, **k: None
    _tg.notify_attack_failed = lambda *a, **k: None
    sys.modules["telegram_notifier"] = _tg

import db_manager
import farm_manager as fm


def _setup_db(tmp_path):
    db_manager.DB_PATH = str(tmp_path / "farm.db")
    db_manager._LOGS_DIR = str(tmp_path)
    db_manager._DB_INIT_DONE = False


# ── db CRUD ───────────────────────────────────────────────────────────────────

def test_farm_add_list_get(tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "AlvoCity",
                         "targetPlayer": "X", "islandId": "7", "islandX": 40, "islandY": 50,
                         "intervalHours": 6, "minLoot": 30000})
    lst = db_manager.farm_list()
    assert len(lst) == 1
    t = db_manager.farm_get("100")
    assert t["target_city_name"] == "AlvoCity"
    assert t["interval_hours"] == 6
    assert t["enabled"] is True
    assert t["state"] == "IDLE"


def test_farm_add_idempotent_keeps_stats(tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "A", "intervalHours": 6})
    db_manager.farm_update("100", {"total_raids": 5, "state": "ATTACKING"})
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "A2", "intervalHours": 9})
    t = db_manager.farm_get("100")
    assert t["target_city_name"] == "A2"      # identity/config refreshed
    assert t["interval_hours"] == 9
    assert t["total_raids"] == 5              # stats preserved
    assert t["state"] == "ATTACKING"          # runtime state preserved


def test_farm_remove(tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "A"})
    assert db_manager.farm_remove("100") == 1
    assert db_manager.farm_list() == []


# ── state machine ─────────────────────────────────────────────────────────────

def _common_patches(monkeypatch, tmp_path, missions=None):
    """Patch farm_manager's external data sources for a controlled run."""
    import espionage_manager as em
    import attack_manager as am
    monkeypatch.setattr(em, "OWN_CITIES_PATH", str(tmp_path / "own.json"))
    monkeypatch.setattr(em, "SPY_COUNTS_PATH", str(tmp_path / "spy.json"))
    monkeypatch.setattr(am, "OWN_CITIES_PATH", str(tmp_path / "own.json"))
    monkeypatch.setattr(am, "MILITARY_JSON_PATH", str(tmp_path / "mil.json"))
    with open(tmp_path / "own.json", "w") as f:
        json.dump([{"cityId": 1, "name": "Home", "x": 41, "y": 50,
                    "safehousePosition": 3, "islandId": "8"}], f)
    with open(tmp_path / "spy.json", "w") as f:
        json.dump({"byCityId": {"1": {"inDefense": 5}}}, f)
    with open(tmp_path / "mil.json", "w") as f:
        json.dump({"byCityName": {"Home": {"troops": {"s303": {"name": "Hoplite", "amount": 200}},
                                            "fleet": {}}}}, f)
    monkeypatch.setattr(em, "_load_missions", lambda: {"missions": missions or []})
    monkeypatch.setattr(em, "SPY_MISSIONS_PATH", str(tmp_path / "missions.json"))  # isolate saves
    monkeypatch.setattr(fm, "MOVEMENTS_PATH", str(tmp_path / "movements.json"))  # isolate
    monkeypatch.setattr(fm, "_free_ships", lambda s: 50)  # ships available by default
    import empire_utils
    monkeypatch.setattr(empire_utils, "is_paused", lambda: False)
    # capture queue_add into a list
    added = []
    monkeypatch.setattr(db_manager, "queue_add", lambda q, item: added.append((q, item)) or "id")
    # getShipCapacity stub
    import ikabot.helpers.pedirInfo as pedir
    monkeypatch.setattr(pedir, "getShipCapacity", lambda s: (5000, 25000), raising=False)
    return added


def test_idle_enqueues_spy_when_due(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000})
    db_manager.farm_update("100", {"next_run_at": 0})   # due now
    added = _common_patches(monkeypatch, tmp_path)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["spy_dispatch"]
    assert added[0][1]["targetCityId"] == "100"
    assert db_manager.farm_get("100")["state"] == "SPYING"


def test_spy_dispatch_uses_configured_agent_count(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "islandX": 40, "islandY": 50,
                         "islandId": "7"})
    db_manager.farm_update("100", {"next_run_at": 0})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "get_farm_spy_agents", lambda: 4)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    spy = next(it for q, it in added if q == "spy_dispatch")
    assert spy["numAgents"] == 4


def test_idle_waits_until_due(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo"})
    db_manager.farm_update("100", {"next_run_at": int(time.time()) + 9999})
    added = _common_patches(monkeypatch, tmp_path)

    fm.process_farm_targets(session=object(), in_active_hours=True)
    assert added == []
    assert db_manager.farm_get("100")["state"] == "IDLE"


def test_spying_with_good_loot_enqueues_attack(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000, "maxEnemyShips": 0})
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": 1000})
    missions = [{
        "state": "DONE", "targetCityId": "100",
        "result": {"resources": {"wood": 50000, "marble": 40000}, "reportedAt": 2000},
        "garrisonResult": {"troops": {}},
    }]
    added = _common_patches(monkeypatch, tmp_path, missions=missions)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["attack"]
    item = added[0][1]
    assert item["missionType"] == "army" and item["targetType"] == "enemy"
    assert item["transporters"] >= 1
    t = db_manager.farm_get("100")
    assert t["state"] == "ATTACKING"
    assert t["total_raids"] == 1
    assert t["last_loot"] == 90000


def test_farm_army_loadout_caps_to_available(monkeypatch, tmp_path):
    """With a configured loadout, send min(loadout, available) per unit — not all troops."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000, "maxEnemyShips": 0})
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": 1000})
    missions = [{"state": "DONE", "targetCityId": "100",
                 "result": {"resources": {"wood": 90000}, "reportedAt": 2000},
                 "garrisonResult": {"troops": {}}}]
    added = _common_patches(monkeypatch, tmp_path, missions=missions)
    # loadout asks 50 hoplites (city has 200) and 999 of a unit it doesn't have
    monkeypatch.setattr(fm, "get_farm_army", lambda: {"s303": 50, "s999": 999})

    fm.process_farm_targets(session=object(), in_active_hours=True)

    army_items = [it for q, it in added if q == "attack" and it["missionType"] == "army"]
    assert len(army_items) == 1
    units = army_items[0]["units"]
    assert units == {"s303": 50}     # capped to loadout; missing unit dropped


def test_spying_low_loot_reschedules(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "minLoot": 100000})
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": 1000})
    missions = [{"state": "DONE", "targetCityId": "100",
                 "result": {"resources": {"wood": 5000}, "reportedAt": 2000},
                 "garrisonResult": {"troops": {}}}]
    added = _common_patches(monkeypatch, tmp_path, missions=missions)

    fm.process_farm_targets(session=object(), in_active_hours=True)
    assert added == []                                   # no attack
    assert db_manager.farm_get("100")["state"] == "IDLE"  # back to idle


def test_attacking_returns_to_idle_after_return(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "intervalHours": 8})
    db_manager.farm_update("100", {"state": "ATTACKING", "attack_return_at": 1})  # already returned
    _common_patches(monkeypatch, tmp_path)

    fm.process_farm_targets(session=object(), in_active_hours=True)
    t = db_manager.farm_get("100")
    assert t["state"] == "IDLE"
    assert t["next_run_at"] > int(time.time())


def test_spying_success_sets_respy_baseline(monkeypatch, tmp_path):
    """A spy-based attack resets raids_since_spy to 1 and records intel for direct raids."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000, "maxEnemyShips": 0})
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": 1000})
    missions = [{"state": "DONE", "targetCityId": "100",
                 "result": {"resources": {"wood": 80000}, "reportedAt": 2000},
                 "garrisonResult": {"troops": {}}}]
    _common_patches(monkeypatch, tmp_path, missions=missions)

    fm.process_farm_targets(session=object(), in_active_hours=True)
    t = db_manager.farm_get("100")
    assert t["state"] == "ATTACKING"
    assert t["raids_since_spy"] == 1
    assert t["last_enemy_ships"] == 0
    assert t["last_transporters"] >= 1


def test_direct_attack_without_respy(monkeypatch, tmp_path):
    """IDLE with next_action=attack and safe intel attacks directly, no spy enqueued."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "next_action": "attack",
                                   "last_loot": 70000, "last_enemy_ships": 0, "raids_since_spy": 1})
    added = _common_patches(monkeypatch, tmp_path)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["attack"]   # no spy_dispatch
    t = db_manager.farm_get("100")
    assert t["state"] == "ATTACKING"
    assert t["raids_since_spy"] == 2              # incremented


def test_return_triggers_respy_when_due(monkeypatch, tmp_path):
    """After return, re-spy when raids_since_spy reached respy_every; else attack directly."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "respyEvery": 3})
    _common_patches(monkeypatch, tmp_path)

    # rss below threshold → next_action 'attack'
    db_manager.farm_update("100", {"state": "ATTACKING", "attack_return_at": 1,
                                   "raids_since_spy": 1, "last_enemy_ships": 0})
    fm.process_farm_targets(session=object(), in_active_hours=True)
    t = db_manager.farm_get("100")
    assert t["state"] == "IDLE" and t["next_action"] == "attack"
    assert t["next_run_at"] > int(time.time())

    # rss at threshold → next_action 'spy'
    db_manager.farm_update("100", {"state": "ATTACKING", "attack_return_at": 1,
                                   "raids_since_spy": 3, "last_enemy_ships": 0})
    fm.process_farm_targets(session=object(), in_active_hours=True)
    assert db_manager.farm_get("100")["next_action"] == "spy"


def test_has_due_farm(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo"})
    import espionage_manager as em
    monkeypatch.setattr(em, "_load_missions", lambda: {"missions": []})

    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": int(time.time()) + 9999})
    assert fm.has_due_farm() is False
    db_manager.farm_update("100", {"next_run_at": 0})
    assert fm.has_due_farm() is True
    db_manager.farm_update("100", {"state": "ATTACKING", "attack_return_at": int(time.time()) + 9999})
    assert fm.has_due_farm() is False


def test_reexecute_stationed_spy_resets_done(monkeypatch, tmp_path):
    import espionage_manager as em
    monkeypatch.setattr(em, "SPY_MISSIONS_PATH", str(tmp_path / "m.json"))
    em._save_missions({"missions": [{
        "targetCityId": "100", "originCityId": "1", "safehousePosition": 3, "state": "DONE",
        "result": {"resources": {"wood": 1}}, "garrisonResult": {"troops": {}}, "targetCityName": "Alvo",
    }]})
    assert em.reexecute_stationed_spy("100", fast=True) is True
    m = em._load_missions()["missions"][0]
    assert m["state"] == "WAITING_AT_CITY" and m["fast"] is True and m["result"] is None


def test_reexecute_stationed_spy_skips_synthetic(monkeypatch, tmp_path):
    import espionage_manager as em
    monkeypatch.setattr(em, "SPY_MISSIONS_PATH", str(tmp_path / "m.json"))
    em._save_missions({"missions": [{"targetCityId": "100", "originCityId": None, "state": "DONE"}]})
    assert em.reexecute_stationed_spy("100") is False   # imported report → no real spy


def test_reexecute_stationed_spy_active_no_dispatch(monkeypatch, tmp_path):
    import espionage_manager as em
    monkeypatch.setattr(em, "SPY_MISSIONS_PATH", str(tmp_path / "m.json"))
    em._save_missions({"missions": [{"targetCityId": "100", "originCityId": "1",
                                     "safehousePosition": 3, "state": "WAITING_FOR_GARRISON"}]})
    assert em.reexecute_stationed_spy("100") is True    # mid-mission → caller waits, no dispatch


def test_farm_reuses_stationed_spy_instead_of_dispatch(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "islandX": 40,
                         "islandY": 50, "islandId": "7"})
    db_manager.farm_update("100", {"next_run_at": 0, "next_action": "spy"})
    stationed = [{"targetCityId": "100", "originCityId": "1", "safehousePosition": 3,
                  "state": "DONE", "targetCityName": "Alvo"}]
    added = _common_patches(monkeypatch, tmp_path, missions=stationed)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == []   # no spy_dispatch — reused the stationed spy
    assert db_manager.farm_get("100")["state"] == "SPYING"


def test_no_ships_schedules_for_real_return(monkeypatch, tmp_path):
    """With 0 free ships, the next attempt is scheduled for the fleet's real return time
    (from movements), not a blind random delay."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Δ The Rock Δ",
                         "targetPlayer": "Cap Almighty", "islandX": 40, "islandY": 50, "islandId": "7"})
    now = int(time.time())
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "next_action": "attack",
                                   "last_loot": 80000, "last_enemy_ships": 0})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_free_ships", lambda s: 0)               # ships out
    import empire_collector as ec
    monkeypatch.setattr(ec, "refresh_movements", lambda *a, **k: None)  # no real HTTP
    arrival = now + 3600
    with open(tmp_path / "movements.json", "w") as f:
        json.dump([{"isOwn": True, "direction": "<-", "arrivalTime": arrival,
                    "origin": "Baphomet (Vempire)",
                    "destination": "Δ The Rock Δ (Cap Almighty)"}], f)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == []     # no attack enqueued
    t = db_manager.farm_get("100")
    assert t["state"] == "IDLE"
    # scheduled around the real arrival (+ up to 90s buffer), not a 5-15min guess
    assert arrival <= t["next_run_at"] <= arrival + 120


def test_paused_does_nothing(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo"})
    db_manager.farm_update("100", {"next_run_at": 0})
    added = _common_patches(monkeypatch, tmp_path)
    import empire_utils
    monkeypatch.setattr(empire_utils, "is_paused", lambda: True)

    fm.process_farm_targets(session=object(), in_active_hours=True)
    assert added == []
    assert db_manager.farm_get("100")["state"] == "IDLE"
