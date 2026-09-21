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
    # Real-time form fetches / movement refresh: stub so attacks don't hit the network or sleep
    monkeypatch.setattr(am, "fetch_troop_journey", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(am, "fetch_fleet_journey", lambda *a, **k: None, raising=False)
    import empire_collector
    monkeypatch.setattr(empire_collector, "refresh_movements", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(empire_collector, "refresh_city_military", lambda *a, **k: None, raising=False)
    import empire_utils
    monkeypatch.setattr(empire_utils, "is_paused", lambda: False)
    # No real anti-detection sleeps in tests; live-check memo must not leak between tests
    monkeypatch.setattr(fm.time, "sleep", lambda *a, **k: None)
    fm._inactive_memo.clear()
    # capture queue_add into a list
    added = []
    monkeypatch.setattr(db_manager, "queue_add", lambda q, item: added.append((q, item)) or "id")
    # getShipCapacity stub
    import ikabot.helpers.pedirInfo as pedir
    monkeypatch.setattr(pedir, "getShipCapacity", lambda s: (5000, 25000), raising=False)
    return added


# ── pure queue (prioritise by loot/hour, drain one, then disable) ───────────────

def test_round_trip_and_priority():
    # real troop time known → round trip = ×2; loot/sec ranks targets
    rich_near = {"last_loot": 400000, "last_troop_journey": 2000}   # 400k / 4000s
    poor_far  = {"last_loot": 400000, "last_troop_journey": 8000}   # 400k / 16000s
    assert fm._round_trip_secs(rich_near) == 4000
    assert fm._priority_score(rich_near) > fm._priority_score(poor_far)
    # no journey yet → default round trip; no loot → score 0
    assert fm._round_trip_secs({}) == fm._DEFAULT_ROUND_TRIP
    assert fm._priority_score({"last_loot": 0}) == 0


def test_queue_head_picks_best_loot_per_hour():
    a = {"target_city_id": "1", "state": "IDLE", "last_loot": 100000, "last_troop_journey": 2000}
    b = {"target_city_id": "2", "state": "IDLE", "last_loot": 500000, "last_troop_journey": 2000}
    c = {"target_city_id": "3", "state": "IDLE", "last_loot": 90000,  "last_troop_journey": 2000}
    assert fm._queue_head([a, b, c])["target_city_id"] == "2"


def test_queue_head_prefers_active_target():
    a = {"target_city_id": "1", "state": "IDLE", "last_loot": 999999, "last_troop_journey": 2000}
    b = {"target_city_id": "2", "state": "ATTACKING", "last_loot": 1, "last_troop_journey": 2000}
    # b is mid-cycle (ships committed) → it stays the head even with lower priority
    assert fm._queue_head([a, b])["target_city_id"] == "2"


def test_queue_processes_only_head(monkeypatch, tmp_path):
    """Two IDLE targets due now: only the higher loot/hour one is worked this round."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Pobre", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000})
    db_manager.farm_add({"targetCityId": "200", "targetCityName": "Rico", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000})
    db_manager.farm_update("100", {"next_run_at": 0, "last_loot": 100000, "last_troop_journey": 2000})
    db_manager.farm_update("200", {"next_run_at": 0, "last_loot": 500000, "last_troop_journey": 2000})
    added = _common_patches(monkeypatch, tmp_path)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    # only the rich target was scouted; the poor one stays IDLE, untouched
    assert [q for q, _ in added] == ["spy_dispatch"]
    assert added[0][1]["targetCityId"] == "200"
    assert db_manager.farm_get("200")["state"] == "SPYING"
    assert db_manager.farm_get("100")["state"] == "IDLE"


def test_drained_target_is_disabled(monkeypatch, tmp_path):
    """A ready report below min_loot disables the target for good (and would alert),
    and hides it from the inactives list via an 'ignorar' mark."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 50000})
    now = int(time.time())
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": now - 60})
    report = [{"state": "DONE", "targetCityId": "100", "targetCityName": "Alvo",
               "result": {"resources": {"wood": 10000}}, "garrisonResult": {"troops": {}},
               "executedAt": now}]
    added = _common_patches(monkeypatch, tmp_path, missions=report)
    drained = []
    import telegram_notifier as tg
    tg.notify_farm_drained = lambda *a, **k: drained.append(a)
    ignored = []
    import espionage_manager as em
    monkeypatch.setattr(em, "_auto_mark_ignored", lambda *a, **k: ignored.append(a))

    fm.process_farm_targets(session=object(), in_active_hours=True)

    t = db_manager.farm_get("100")
    assert t["enabled"] is False          # disabled for good
    assert [q for q, _ in added] == []    # no attack
    assert len(drained) == 1              # alerted
    assert len(ignored) == 1              # hidden from the inactives list
    assert ignored[0][0] == "100" and "Drenado" in ignored[0][4]


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


def test_spying_stuck_head_released(monkeypatch, tmp_path):
    """P7.2: a SPYING head with no report, no failure and no in-flight mission (dispatch
    silently never took) is released to IDLE past the grace window — so the queue advances
    instead of blocking on it for the full 6h timeout."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "minLoot": 50000})
    # dispatched well past the stuck grace, and no missions at all for the target
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": now - fm._SPY_STUCK_GRACE - 60})
    added = _common_patches(monkeypatch, tmp_path, missions=[])

    fm.process_farm_targets(session=object(), in_active_hours=True)
    t = db_manager.farm_get("100")
    assert t["state"] == "IDLE"                 # head released
    assert t["next_run_at"] > now              # scheduled for a short retry
    assert added == []                          # no attack


def test_spying_live_mission_not_released(monkeypatch, tmp_path):
    """An in-flight spy (a live, non-terminal mission) must keep the head in SPYING even
    past the grace window — the stuck-release only fires when the mission is truly gone."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "minLoot": 50000})
    disp = now - fm._SPY_STUCK_GRACE - 60
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": disp})
    missions = [{"state": "TRAVELING", "targetCityId": "100", "dispatchedAt": disp}]
    _common_patches(monkeypatch, tmp_path, missions=missions)

    fm.process_farm_targets(session=object(), in_active_hours=True)
    assert db_manager.farm_get("100")["state"] == "SPYING"   # still waiting, not released


def test_next_farm_eta_schedules_spying_backstop(monkeypatch, tmp_path):
    """P7.2: next_farm_eta must return a wake for a SPYING head (grace deadline) instead of
    None, so smart_sleep re-evaluates a possibly-stuck head at a bounded time."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "minLoot": 50000})
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": now})
    eta = fm.next_farm_eta()
    assert eta is not None
    assert eta == now + fm._SPY_STUCK_GRACE     # grace deadline while still within grace


def test_spying_live_mission_not_aborted_before_backstop(monkeypatch, tmp_path):
    """P7.1: a still-live/executing mission past the OLD 6h wall-clock (e.g. after downtime)
    must NOT be aborted — that used to orphan the in-flight report (the Polis case). It stays
    SPYING and waits for the espionage machine to finish it."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "minLoot": 50000})
    disp = now - 7 * 3600                                   # 7h: past old 6h, under 13h backstop
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": disp})
    missions = [{"state": "EXECUTING_WAREHOUSE", "targetCityId": "100", "dispatchedAt": disp}]
    _common_patches(monkeypatch, tmp_path, missions=missions)

    fm.process_farm_targets(session=object(), in_active_hours=True)
    assert db_manager.farm_get("100")["state"] == "SPYING"   # not aborted — report preserved


def test_spying_live_mission_released_by_backstop(monkeypatch, tmp_path):
    """P7.1: the 13h last-resort backstop still frees a head if a mission stays 'live' beyond
    the espionage machine's own 12h termination, so the queue can never freeze permanently."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "minLoot": 50000})
    disp = now - 14 * 3600                                  # 14h: past the 13h backstop
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": disp})
    missions = [{"state": "TRAVELING", "targetCityId": "100", "dispatchedAt": disp}]
    _common_patches(monkeypatch, tmp_path, missions=missions)

    fm.process_farm_targets(session=object(), in_active_hours=True)
    assert db_manager.farm_get("100")["state"] == "IDLE"     # backstop released the head


def test_attacking_returns_to_idle_after_return(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "intervalHours": 8})
    db_manager.farm_update("100", {"state": "ATTACKING", "attack_return_at": 1})  # already returned
    _common_patches(monkeypatch, tmp_path)

    fm.process_farm_targets(session=object(), in_active_hours=True)
    t = db_manager.farm_get("100")
    assert t["state"] == "IDLE"
    assert t["next_run_at"] > int(time.time())


def test_attacking_unblocks_when_troops_home_despite_estimate(monkeypatch, tmp_path):
    """An overshooting attack_return_at must not block the queue: with no movement in flight to
    the target and grace passed, the troops are home → transition out of ATTACKING."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "respyEvery": 3})
    db_manager.farm_update("100", {"state": "ATTACKING", "attack_return_at": now + 9000,
                                   "last_attack_at": now - 1800, "raids_since_spy": 1,
                                   "last_enemy_ships": 0})
    _common_patches(monkeypatch, tmp_path)   # MOVEMENTS_PATH isolated → no raid in flight

    fm.process_farm_targets(session=object(), in_active_hours=True)
    assert db_manager.farm_get("100")["state"] != "ATTACKING"   # unblocked


def test_attacking_waits_while_raid_in_flight(monkeypatch, tmp_path):
    """If a movement to the target is still in flight, keep waiting (don't false-unblock)."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "respyEvery": 3})
    db_manager.farm_update("100", {"state": "ATTACKING", "attack_return_at": now + 9000,
                                   "last_attack_at": now - 1800, "raids_since_spy": 1})
    _common_patches(monkeypatch, tmp_path)
    with open(tmp_path / "movements.json", "w") as f:
        json.dump([{"isOwn": True, "direction": "->", "destination": "Alvo", "origin": "Home"}], f)

    fm.process_farm_targets(session=object(), in_active_hours=True)
    assert db_manager.farm_get("100")["state"] == "ATTACKING"   # still out → keep waiting


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


def test_fleet_target_respies_not_direct(monkeypatch, tmp_path):
    """A fleet target (is_fleet_target=1, e.g. The Rock) NEVER direct-attacks: even when due,
    it re-spies first so troops are never sent into a fleet that flew off and returned."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "The Rock", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "next_action": "attack",
                                   "last_loot": 70000, "last_enemy_ships": 0, "raids_since_spy": 1,
                                   "last_spy_at": 1000, "is_fleet_target": 1})
    added = _common_patches(monkeypatch, tmp_path)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["spy_dispatch"]   # re-spied, did NOT attack directly
    spy = added[0][1]
    assert spy["needGarrison"] is True                 # fleet target → full scout
    assert db_manager.farm_get("100")["state"] == "SPYING"


def test_first_contact_always_full_scout(monkeypatch, tmp_path):
    """A never-scouted target (last_spy_at=0) does a FULL scout — never a blind direct raid,
    never warehouse-only — so the first contact always learns the fleet/garrison state."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Novo", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000})
    db_manager.farm_update("100", {"next_run_at": 0, "last_loot": 70000})  # loot but never spied
    added = _common_patches(monkeypatch, tmp_path)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["spy_dispatch"]
    assert added[0][1]["needGarrison"] is True
    assert db_manager.farm_get("100")["state"] == "SPYING"


def test_safe_target_attacks_directly(monkeypatch, tmp_path):
    """A safe target (is_fleet_target=0, already scouted, rss below respy_every) raids directly
    without spending a scout, advancing raids_since_spy."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Seguro", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000, "respyEvery": 3})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_loot": 70000,
                                   "last_enemy_ships": 0, "raids_since_spy": 1, "last_spy_at": 1000,
                                   "is_fleet_target": 0})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: True)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["attack"]            # direct raid, no scout
    assert added[0][1]["missionType"] == "army"
    t = db_manager.farm_get("100")
    assert t["state"] == "ATTACKING"
    assert t["raids_since_spy"] == 2                       # advanced toward the next periodic scout
    assert t["total_raids"] == 1


def test_safe_periodic_respy_is_warehouse_only(monkeypatch, tmp_path):
    """When raids_since_spy reaches respy_every, a safe target re-scouts — but warehouse-only
    (needGarrison=False), and re-confirms the owner is still inactive."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Seguro", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000, "respyEvery": 3})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_loot": 70000,
                                   "last_enemy_ships": 0, "raids_since_spy": 3, "last_spy_at": 1000,
                                   "is_fleet_target": 0})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: True)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["spy_dispatch"]
    assert added[0][1]["needGarrison"] is False           # warehouse-only re-scout
    assert db_manager.farm_get("100")["state"] == "SPYING"


def test_uncertain_inactivity_forces_full_scout(monkeypatch, tmp_path):
    """P5.5: if inactivity can't be confirmed (stale scan + island fetch failed → None),
    escalate to a full garrison scout instead of a blind warehouse-only re-scout."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Seguro", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000, "respyEvery": 3})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_loot": 70000,
                                   "last_enemy_ships": 0, "raids_since_spy": 3, "last_spy_at": 1000,
                                   "is_fleet_target": 0})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: None)   # can't tell

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["spy_dispatch"]
    assert added[0][1]["needGarrison"] is True       # escalated to full scout, not warehouse-only
    assert db_manager.farm_get("100")["state"] == "SPYING"


def test_drained_by_real_return_respies_not_direct(monkeypatch, tmp_path):
    """A safe target whose troops came back with < min_loot is re-spied to confirm drainage,
    not direct-attacked on the stale scouted last_loot (the 5k-return / 268k-last_loot bug)."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Pais da Grama", "islandX": 40,
                         "islandY": 50, "islandId": "7", "minLoot": 50000, "respyEvery": 3})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_loot": 268638,
                                   "last_enemy_ships": 0, "raids_since_spy": 1, "last_spy_at": 1000,
                                   "is_fleet_target": 0, "last_attack_at": now - 100})
    db_manager.log_loot({"ts": now - 10, "fromCity": "Pais da Grama", "fromPlayer": "Pacheco III",
                         "toCity": "Baphomet", "resources": [3000, 2101, 0, 0, 0], "returnKey": "k1"})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: True)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["spy_dispatch"]      # re-spied, did NOT attack directly
    assert db_manager.farm_get("100")["state"] == "SPYING"


def test_healthy_real_return_still_direct_attacks(monkeypatch, tmp_path):
    """A real return still above min_loot keeps the fast direct-attack path (no needless scout)."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Pais da Grama", "islandX": 40,
                         "islandY": 50, "islandId": "7", "minLoot": 50000, "respyEvery": 3})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_loot": 268638,
                                   "last_enemy_ships": 0, "raids_since_spy": 1, "last_spy_at": 1000,
                                   "is_fleet_target": 0, "last_attack_at": now - 100})
    db_manager.log_loot({"ts": now - 10, "fromCity": "Pais da Grama", "fromPlayer": "Pacheco III",
                         "toCity": "Baphomet", "resources": [100000, 0, 0, 0, 0], "returnKey": "k1"})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: True)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["attack"]            # still direct — target still rich
    assert db_manager.farm_get("100")["state"] == "ATTACKING"


def test_no_free_troops_reschedules_not_doomed_attack(monkeypatch, tmp_path):
    """Origin with no free troops (still returning / cache lagging) → reschedule a short retry,
    not a doomed dispatch the server rejects with 'no units selected'."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Seguro", "islandX": 40,
                         "islandY": 50, "islandId": "7", "minLoot": 50000, "respyEvery": 3})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_loot": 200000,
                                   "last_enemy_ships": 0, "raids_since_spy": 1, "last_spy_at": 1000,
                                   "is_fleet_target": 0, "last_attack_at": now - 100})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: True)
    with open(tmp_path / "mil.json", "w") as f:        # origin has no troops available now
        json.dump({"byCityName": {"Home": {"troops": {}, "fleet": {}}}}, f)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert added == []                                  # neither attack nor scout enqueued
    t = db_manager.farm_get("100")
    assert t["state"] == "IDLE" and t["next_run_at"] > now   # rescheduled for a retry


def test_early_respy_warehouse_only_for_safe_target(monkeypatch, tmp_path):
    """The pipelined re-scout fired while troops return is warehouse-only for a safe target."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Seguro", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000, "respyEvery": 3})
    now = int(time.time())
    db_manager.farm_update("100", {"state": "ATTACKING", "attack_return_at": now + 60,
                                   "respy_launched_at": 0, "raids_since_spy": 3, "last_spy_at": 1000,
                                   "last_enemy_ships": 0, "is_fleet_target": 0})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: True)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["spy_dispatch"]
    assert added[0][1]["needGarrison"] is False
    assert db_manager.farm_get("100")["respy_launched_at"] > 0


def test_direct_raid_blocked_when_owner_active(monkeypatch, tmp_path):
    """Live inactivity check runs immediately before EVERY direct raid: owner active again →
    target disabled + alert, no attack goes out even though all raid gates were green."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Seguro", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000, "respyEvery": 3})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_loot": 70000,
                                   "last_enemy_ships": 0, "raids_since_spy": 1, "last_spy_at": 1000,
                                   "is_fleet_target": 0})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: False)
    alerted = []
    import telegram_notifier as tg
    monkeypatch.setattr(tg, "notify_farm_active", lambda *a, **k: alerted.append(a), raising=False)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert added == []
    assert db_manager.farm_get("100")["enabled"] is False
    assert len(alerted) == 1


def test_direct_raid_unconfirmed_escalates_to_scout(monkeypatch, tmp_path):
    """If the live check can't tell (island fetch + scan both failed → None), the direct raid
    is NOT sent blind — the round escalates to a full garrison scout instead."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Seguro", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000, "respyEvery": 3})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_loot": 70000,
                                   "last_enemy_ships": 0, "raids_since_spy": 1, "last_spy_at": 1000,
                                   "is_fleet_target": 0})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: None)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["spy_dispatch"]      # scout instead of blind attack
    assert added[0][1]["needGarrison"] is True
    assert db_manager.farm_get("100")["state"] == "SPYING"


def test_first_contact_checks_inactivity_too(monkeypatch, tmp_path):
    """The live inactivity check now also gates FIRST-contact scouts: an owner who is active
    at the coordinates disables the target before a single spy is spent."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Novo", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_spy_at": 0})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: False)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert added == []                                    # no spy wasted on an active player
    assert db_manager.farm_get("100")["enabled"] is False


def test_report_attack_blocked_when_owner_active(monkeypatch, tmp_path):
    """Even with a fresh good report in hand, the launch is re-gated by the live check:
    owner active again → disable, no attack."""
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
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: False)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert added == []
    assert db_manager.farm_get("100")["enabled"] is False


def test_reactivated_target_is_disabled(monkeypatch, tmp_path):
    """If the inactivity re-check finds the owner active again, the target is disabled (no raid,
    no scout) and an alert fires — a safe target can only turn unsafe by reactivating."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Seguro", "islandX": 40, "islandY": 50,
                         "islandId": "7", "minLoot": 30000, "respyEvery": 3})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_loot": 70000,
                                   "last_enemy_ships": 0, "raids_since_spy": 3, "last_spy_at": 1000,
                                   "is_fleet_target": 0})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: False)
    alerted = []
    import telegram_notifier as tg
    monkeypatch.setattr(tg, "notify_farm_active", lambda *a, **k: alerted.append(a), raising=False)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert added == []                                    # no scout, no attack
    assert db_manager.farm_get("100")["enabled"] is False
    assert len(alerted) == 1


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
    """A ready report with 0 free ships schedules the next attempt for the fleet's real
    return (from movements), not a blind random delay (SPYING-eval path)."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Δ The Rock Δ",
                         "targetPlayer": "Cap Almighty", "islandX": 40, "islandY": 50, "islandId": "7"})
    now = int(time.time())
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": now - 60})
    report = [{"state": "DONE", "targetCityId": "100", "targetCityName": "Δ The Rock Δ",
               "result": {"resources": {"wood": 80000}}, "garrisonResult": {"troops": {}},
               "executedAt": now}]
    added = _common_patches(monkeypatch, tmp_path, missions=report)
    monkeypatch.setattr(fm, "_free_ships", lambda s: 0)               # ships out
    import empire_collector as ec
    monkeypatch.setattr(ec, "refresh_movements", lambda *a, **k: None)  # no real HTTP
    arrival = now + 3600
    with open(tmp_path / "movements.json", "w") as f:
        json.dump([{"isOwn": True, "direction": "<-", "arrivalTime": arrival,
                    "origin": "Baphomet (Vempire)",
                    "destination": "Δ The Rock Δ (Cap Almighty)"}], f)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == []     # no attack enqueued (no ships)
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


def test_bounced_return_forces_garrison_respy(monkeypatch, tmp_path):
    """Troops home with NO registered loot → suspected naval bounce (a warship docked since
    the last scout) → full garrison re-scout, not another blind 6h raid (Vinhedo B case)."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Vinhedo B"})
    db_manager.farm_update("100", {"state": "ATTACKING", "attack_return_at": now - 10,
                                   "last_attack_at": now - 7200, "raids_since_spy": 1,
                                   "last_enemy_ships": 0, "is_fleet_target": 0})
    _common_patches(monkeypatch, tmp_path)   # loot_log stays empty → bounce signal

    fm.process_farm_targets(session=object(), in_active_hours=True)

    t = db_manager.farm_get("100")
    assert t["state"] == "IDLE" and t["next_action"] == "spy"
    assert t["is_fleet_target"]              # next scout reads the port (full garrison)


def test_return_with_loot_relaunches_attack(monkeypatch, tmp_path):
    """A raid that actually brought loot home keeps the normal cadence (no bounce path)."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Vinhedo B", "respyEvery": 3})
    db_manager.farm_update("100", {"state": "ATTACKING", "attack_return_at": now - 10,
                                   "last_attack_at": now - 7200, "raids_since_spy": 1,
                                   "last_enemy_ships": 0, "is_fleet_target": 0})
    db_manager.log_loot({"ts": now - 60, "fromCity": "Vinhedo B", "fromPlayer": "J",
                         "toCity": "Home", "resources": [100000, 50000, 0, 0, 0],
                         "returnKey": "r1"})
    _common_patches(monkeypatch, tmp_path)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    t = db_manager.farm_get("100")
    assert t["state"] == "IDLE" and t["next_action"] == "attack"
    assert not t["is_fleet_target"]


def test_weak_combat_fleet_engaged_with_blockade(monkeypatch, tmp_path):
    """Combat ships within max_enemy_ships are ENGAGED — blockade wave first, troops delayed
    by a sea-battle margin — never ignored: unescorted transports lose any sea fight."""
    _setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Vinhedo B", "islandX": 40,
                         "islandY": 50, "islandId": "7", "minLoot": 50000, "maxEnemyShips": 3})
    db_manager.farm_update("100", {"state": "SPYING", "spy_dispatched_at": 1000})
    missions = [{"state": "DONE", "targetCityId": "100",
                 "result": {"resources": {"wood": 288962}, "reportedAt": 2000},
                 "garrisonResult": {"troops": {"Cozinheiro": 10, "Médico": 10, "Trirreme": 2}}}]
    added = _common_patches(monkeypatch, tmp_path, missions=missions)
    with open(tmp_path / "mil.json", "w") as f:
        json.dump({"byCityName": {"Home": {
            "troops": {"s303": {"name": "Hoplite", "amount": 200}},
            "fleet":  {"s216": {"name": "Aríete a vapor", "amount": 12}}}}}, f)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    fleet_items = [it for q, it in added if q == "attack" and it["missionType"] == "fleet"]
    army_items  = [it for q, it in added if q == "attack" and it["missionType"] == "army"]
    assert len(fleet_items) == 1 and len(army_items) == 1
    # troops launch late enough to land only after the blockade FOUGHT the combat ships
    assert (army_items[0]["dispatchAfter"] - fleet_items[0]["dispatchAfter"]
            >= fm._SEA_BATTLE_MARGIN_SECS)
    t = db_manager.farm_get("100")
    assert t["state"] == "ATTACKING" and t["is_fleet_target"]


def test_vacation_target_skipped_not_attacked(monkeypatch, tmp_path):
    """A vacation-mode owner can't be attacked (game refuses): the raid is skipped, the
    target stays enabled but is pushed ~24h ahead so the queue advances."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Férias", "islandX": 40,
                         "islandY": 50, "islandId": "7", "minLoot": 30000, "respyEvery": 3})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_loot": 70000,
                                   "last_enemy_ships": 0, "raids_since_spy": 1, "last_spy_at": 1000,
                                   "is_fleet_target": 0})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: "vacation")

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert added == []                                    # no attack, no scout
    t = db_manager.farm_get("100")
    assert t["enabled"] is True                           # NOT disabled — vacation ends
    assert t["next_run_at"] >= now + 23 * 3600            # pushed ~24h


def test_queue_head_prefers_due_targets():
    """A rich target rescheduled into the future (vacation skip) must not block a due one."""
    future = int(time.time()) + 3600
    rich_skipped = {"target_city_id": "1", "state": "IDLE", "last_loot": 999999,
                    "last_troop_journey": 2000, "next_run_at": future}
    poor_due     = {"target_city_id": "2", "state": "IDLE", "last_loot": 50000,
                    "last_troop_journey": 2000, "next_run_at": 0}
    assert fm._queue_head([rich_skipped, poor_due])["target_city_id"] == "2"
    # nothing due → best score again (ETA scheduling picks the soonest wake)
    poor_due["next_run_at"] = future + 100
    assert fm._queue_head([rich_skipped, poor_due])["target_city_id"] == "1"


def test_attack_queue_vacation_fails_fast(monkeypatch, tmp_path):
    """The game's 'está de férias' rejection removes the item on the FIRST failure (no
    3-retry loop) and pushes the matching farm target 24h ahead."""
    import attack_manager as am
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "38319", "targetCityName": "Java", "islandX": 40,
                         "islandY": 50, "islandId": "7", "minLoot": 30000})
    db_manager.farm_update("38319", {"state": "ATTACKING", "next_run_at": 0})
    item = {"id": "i1", "targetCityId": "38319", "targetPlayerName": "K", "dispatchAfter": 0}
    removed = []
    monkeypatch.setattr(am, "_attack_queue_items", lambda: [item])
    monkeypatch.setattr(am, "_dispatch_attack", lambda s, it: False)
    monkeypatch.setattr(am, "_log_attack_attempt", lambda *a, **k: None)
    monkeypatch.setattr(db_manager, "queue_remove", lambda q, ids: removed.extend(ids))
    monkeypatch.setattr(db_manager, "queue_add", lambda q, it: (_ for _ in ()).throw(
        AssertionError("não devia reagendar — férias é falha definitiva")))
    import empire_utils
    monkeypatch.setattr(empire_utils, "is_paused", lambda: False)
    am._last_feedback_text = "O jogador neste momento está de férias"

    am.process_attack_queue(session=object(), in_active_hours=True)

    assert removed == ["i1"]                              # removed on 1st failure
    t = db_manager.farm_get("38319")
    assert t["state"] == "IDLE" and t["next_run_at"] >= now + 23 * 3600


def test_drained_by_estimate_respies_even_if_last_return_healthy(monkeypatch, tmp_path):
    """F1 cumulative path: the last raid still returned >= min_loot, but we've already taken
    most of the scouted warehouse, so the ESTIMATE is below the bar → re-spy, not one more
    wasteful raid (this is what the last-return-only check missed)."""
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Pais da Grama", "islandX": 40,
                         "islandY": 50, "islandId": "7", "minLoot": 50000, "respyEvery": 5})
    db_manager.farm_update("100", {"state": "IDLE", "next_run_at": 0, "last_loot": 268000,
                                   "last_enemy_ships": 0, "raids_since_spy": 1, "last_spy_at": 1000,
                                   "is_fleet_target": 0, "last_attack_at": now - 100})
    # four healthy returns since the scout summing to 260k → est = 8k (< 50k); newest is 60k (healthy)
    for i, amt in enumerate([70000, 70000, 60000, 60000]):
        db_manager.log_loot({"ts": now - 40 + i, "fromCity": "Pais da Grama", "fromPlayer": "P",
                             "toCity": "Baphomet", "resources": [amt, 0, 0, 0, 0], "returnKey": "k%d" % i})
    added = _common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: True)

    fm.process_farm_targets(session=object(), in_active_hours=True)

    assert [q for q, _ in added] == ["spy_dispatch"]      # re-spied, did NOT attack directly
    assert db_manager.farm_get("100")["state"] == "SPYING"
