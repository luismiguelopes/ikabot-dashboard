"""
P13.44: the farm, the attack queue and the dispatcher run TOGETHER on a real shared_queue.

Every earlier farm test replaced queue_add with a list, and every attack-queue test fed items
by hand — nothing exercised the seam between the two, which is where a raid's two waves
(blockade + troops), deferrals and cancellations interact. Only the game POST itself
(_dispatch_attack / the senders) is faked here.
"""
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("telegram_notifier", types.ModuleType("telegram_notifier"))

import attack_manager as am
import db_manager
import farm_manager as fm
import tests.test_farm as base        # reuse the shared patches (not its fake queue)


def _world(monkeypatch, tmp_path, *, garrison, free_ships=500, fleet=True, total_ships=None):
    base._setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "islandX": 41, "islandY": 43,
                         "islandId": "7", "minLoot": 30000, "maxEnemyShips": 0, "fleetLeadMin": 5})
    db_manager.farm_update("100", {"state": "SPYING", "swept_at": 1, "spy_dispatched_at": 1000,
                                   "is_fleet_target": 1})
    missions = [{"state": "DONE", "targetCityId": "100", "needMovements": True,
                 "result": {"resources": {"wood": 90000}, "reportedAt": 2000},
                 "garrisonResult": {"success": True, "troops": garrison},
                 "movementsResult": {"enemyReturnAt": None}}]
    real_queue_add = db_manager.queue_add
    base._common_patches(monkeypatch, tmp_path, missions=missions)
    monkeypatch.setattr(db_manager, "queue_add", real_queue_add)        # the REAL queue
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: True)
    monkeypatch.setattr(fm, "_free_ships", lambda s: free_ships)
    monkeypatch.setattr(fm, "LOGS_DIR", str(tmp_path))
    if total_ships:
        with open(tmp_path / "statusSummary.json", "w") as f:
            json.dump({"ships": {"total": total_ships, "available": free_ships}}, f)
    if fleet:
        with open(tmp_path / "mil.json", "w") as f:
            json.dump({"byCityName": {"Home": {
                "troops": {"s303": {"name": "Hoplite", "amount": 200}},
                "fleet": {"s210": {"name": "Ram", "amount": 10}}}}}, f)
    monkeypatch.setattr(am, "fetch_fleet_journey", lambda *a, **k: 3600, raising=False)
    monkeypatch.setattr(am, "fetch_troop_journey", lambda *a, **k: 1200, raising=False)
    monkeypatch.setattr(am.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(am, "_log_attack_attempt", lambda *a, **k: None)
    fm.process_farm_targets(session=object(), in_active_hours=True)
    return {it["missionType"]: it for it in db_manager.queue_items("attack")}


def _dispatcher(monkeypatch, outcomes):
    """Fake the game POST: outcomes maps missionType → list of results, consumed in order."""
    sent = []

    def fake(session, item):
        res = outcomes[item["missionType"]].pop(0)
        sent.append((item["missionType"], res))
        return res
    monkeypatch.setattr(am, "_dispatch_attack", fake)
    return sent


def test_farm_queues_a_coupled_wave(monkeypatch, tmp_path):
    q = _world(monkeypatch, tmp_path, garrison={"Lancha rápida": 2})
    assert set(q) == {"fleet", "army"}
    assert q["army"]["waitsForFleet"] == q["fleet"]["id"]
    assert (q["army"]["fleetTravel"], q["army"]["troopTravel"], q["army"]["fleetLead"]) == (3600, 1200, 300)
    assert db_manager.farm_get("100")["state"] == "ATTACKING"


def test_troops_are_released_and_retimed_when_the_blockade_leaves(monkeypatch, tmp_path):
    _world(monkeypatch, tmp_path, garrison={"Lancha rápida": 2})
    sent = _dispatcher(monkeypatch, {"fleet": [True], "army": []})
    before = int(time.time())
    am.process_attack_queue(session=object())
    assert sent == [("fleet", True)]                       # the army did NOT go in the same pass
    (army,) = db_manager.queue_items("attack")
    assert army["missionType"] == "army" and not army["waitsForFleet"]
    # lands fleetLead after the fleet: leaves at now + 3600 + 300 − 1200
    assert before + 2700 <= army["dispatchAfter"] <= before + 2700 + 5
    assert not am.has_due_attacks()


def test_blockade_retry_holds_the_troops(monkeypatch, tmp_path):
    q = _world(monkeypatch, tmp_path, garrison={"Lancha rápida": 2})
    sent = _dispatcher(monkeypatch, {"fleet": [False], "army": []})
    am.process_attack_queue(session=object())
    assert sent == [("fleet", False)]
    items = {it["missionType"]: it for it in db_manager.queue_items("attack")}
    assert items["army"]["waitsForFleet"] == q["fleet"]["id"]     # still held
    assert items["fleet"]["retries"] == 1
    assert not am.has_due_attacks()                               # nothing to do until the retry


def test_dropped_blockade_cancels_the_troops_and_frees_the_target(monkeypatch, tmp_path):
    """The old behaviour: the army kept its schedule and sailed alone into the port."""
    _world(monkeypatch, tmp_path, garrison={"Lancha rápida": 2})
    sent = _dispatcher(monkeypatch, {"fleet": [False, False, False], "army": []})
    for _ in range(3):
        for it in db_manager.queue_items("attack"):                # make every retry due now
            if it["missionType"] == "fleet":
                db_manager.queue_add("attack", dict(it, dispatchAfter=0))
        am.process_attack_queue(session=object())
    assert [s for s in sent if s[0] == "army"] == []
    if db_manager.queue_items("attack"):                           # orphan handled next pass
        assert am.has_due_attacks()
        am.process_attack_queue(session=object())
    assert db_manager.queue_items("attack") == []
    t = db_manager.farm_get("100")
    assert t["state"] == "IDLE" and t["next_action"] == "spy"


def test_deferred_army_is_not_requeued_by_the_farm(monkeypatch, tmp_path):
    """Clean port → a single army wave. The dispatcher defers it (not enough ships). The farm,
    seeing no movement, must keep waiting on the queued wave — not queue a second raid."""
    q = _world(monkeypatch, tmp_path, garrison={}, fleet=False)
    assert set(q) == {"army"} and not q["army"].get("waitsForFleet")
    _dispatcher(monkeypatch, {"army": [am._DEFER]})
    db_manager.queue_add("attack", dict(q["army"], dispatchAfter=0))
    am.process_attack_queue(session=object())
    (army,) = db_manager.queue_items("attack")
    assert army["deferrals"] == 1

    db_manager.farm_update("100", {"last_attack_at": int(time.time()) - 1800,
                                   "attack_return_at": int(time.time()) - 5})
    fm.process_farm_targets(session=object(), in_active_hours=True)
    assert len(db_manager.queue_items("attack")) == 1
    assert db_manager.farm_get("100")["state"] == "ATTACKING"


def test_raid_waits_when_free_ships_are_below_the_floor(monkeypatch, tmp_path):
    """90k loot / 5000 per ship = 18 ships; with a 600-ship fleet the floor is 9 → 5 free is
    not enough, the farm keeps the intel and retries when ships are back."""
    q = _world(monkeypatch, tmp_path, garrison={}, fleet=False, free_ships=5, total_ships=600)
    assert q == {}
    t = db_manager.farm_get("100")
    assert t["state"] == "IDLE" and t["next_action"] == "attack"


def test_army_item_carries_the_ship_floor_and_the_sender_enforces_it(monkeypatch, tmp_path):
    q = _world(monkeypatch, tmp_path, garrison={}, fleet=False, free_ships=500, total_ships=600)
    assert (q["army"]["transporters"], q["army"]["minTransporters"]) == (18, 9)
    monkeypatch.setattr(am, "_cap_to_available_ships", lambda req, s=None, reserve=0: 4)
    posted = []
    monkeypatch.setattr(am, "_change_to_origin_city", lambda *a, **k: posted.append("city"))
    res = am._send_army_plunder(object(), "1", "100", "7", {"s303": 10}, 18, min_transporters=9)
    assert res is am._DEFER and posted == []              # no request sent to the game


def test_failure_without_feedback_does_not_inherit_a_previous_vacation_text(monkeypatch, tmp_path):
    """A network error has no game feedback. It used to reuse the LAST rejection text, so an
    earlier "player on vacation" made this unrelated failure drop the item on the spot."""
    q = _world(monkeypatch, tmp_path, garrison={}, fleet=False)
    monkeypatch.setattr(am, "_last_feedback_text", "O jogador está de férias")
    _dispatcher(monkeypatch, {"army": [False]})
    db_manager.queue_add("attack", dict(q["army"], dispatchAfter=0))
    am.process_attack_queue(session=object())
    (army,) = db_manager.queue_items("attack")
    assert army["retries"] == 1                            # retried, not treated as vacation
