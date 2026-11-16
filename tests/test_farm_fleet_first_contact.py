"""
Targets with ships in port can now be added to the farm from the Targets page (they used to be
addable only from the Combat search). This pins what the farm does with such a target from the
very first contact, on a real shared_queue:

  • nothing sails before a complete live triple sweep (warehouse + garrison + movements);
  • ships in port → the blockade goes first and the troops wait for it;
  • the blockade never grows beyond the loadout set in the farm settings: when that loadout is
    not at the origin the raid waits — it used to fall back to the origin's WHOLE fleet;
  • a raid that cannot leave does not re-scout the port every few minutes while it waits.
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
import espionage_manager as em
import farm_manager as fm
import tests.test_farm as base


def _sweep(now, *, garrison=None, fleet=None, movements="clean"):
    m = {"state": "DONE", "targetCityId": "100", "originCityId": "1", "needMovements": True,
         "executedAt": now - 100,
         "result": {"resources": {"wood": 90000}, "reportedAt": now - 100},
         "garrisonResult": {"success": True, "troops": garrison or {}, "reportedAt": now - 80},
         "movementsResult": {"enemyReturnAt": None}, "movementsExecutedAt": now - 60}
    if fleet is not None:
        m["garrisonResult"]["fleet"] = fleet
    if movements is None:
        m["movementsResult"] = None
    elif movements != "clean":
        m["movementsResult"] = {"enemyReturnAt": movements}
    return m


def _run(monkeypatch, tmp_path, *, missions, state="SPYING", farm_fleet=None, own_fleet=None,
         target=None):
    """A target just added from the Targets page (never swept, not yet a fleet target)."""
    base._setup_db(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "Alvo", "islandX": 41,
                         "islandY": 43, "islandId": "7", "minLoot": 30000})
    now = int(time.time())
    fields = {"state": state, "spy_dispatched_at": now - 200 if state == "SPYING" else 0}
    fields.update(target or {})
    db_manager.farm_update("100", fields)
    real_queue_add = db_manager.queue_add
    base._common_patches(monkeypatch, tmp_path, missions=missions)
    monkeypatch.setattr(db_manager, "queue_add", real_queue_add)
    monkeypatch.setattr(fm, "_confirm_inactive", lambda s, t: True)
    monkeypatch.setattr(fm, "_free_ships", lambda s: 500)
    monkeypatch.setattr(fm, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(fm, "FARM_SETTINGS_PATH", str(tmp_path / "farm_settings.json"))
    with open(tmp_path / "farm_settings.json", "w") as f:
        json.dump({"fleet": farm_fleet or {}}, f)
    with open(tmp_path / "mil.json", "w") as f:
        json.dump({"byCityName": {"Home": {
            "troops": {"s303": {"name": "Hoplite", "amount": 200}},
            "fleet": {u: {"name": u, "amount": n} for u, n in (own_fleet or {}).items()}}}}, f)
    monkeypatch.setattr(em, "reexecute_stationed_spy", lambda *a, **k: False)
    monkeypatch.setattr(am, "fetch_fleet_journey", lambda *a, **k: 3600, raising=False)
    monkeypatch.setattr(am, "fetch_troop_journey", lambda *a, **k: 1200, raising=False)
    fm.process_farm_targets(session=object(), in_active_hours=True)
    return ({it["missionType"]: it for it in db_manager.queue_items("attack")},
            db_manager.farm_get("100"))


LANCHAS = {"Lancha rápida": 2}


def test_new_target_starts_with_the_triple_sweep_and_queues_no_attack(monkeypatch, tmp_path):
    q, t = _run(monkeypatch, tmp_path, missions=[], state="IDLE", own_fleet={"s216": 78})
    assert q == {}
    (spy,) = db_manager.queue_items("spy_dispatch")
    assert spy["needGarrison"] is True and spy["needMovements"] is True
    assert t["state"] == "SPYING"


def test_ships_in_port_on_first_contact_blockade_first_troops_wait(monkeypatch, tmp_path):
    now = int(time.time())
    q, t = _run(monkeypatch, tmp_path, missions=[_sweep(now, garrison=LANCHAS)],
                farm_fleet={"s216": 40}, own_fleet={"s216": 78, "s213": 32})
    assert set(q) == {"fleet", "army"}
    assert q["fleet"]["units"] == {"s216": 40}             # the configured loadout, nothing else
    assert q["army"]["waitsForFleet"] == q["fleet"]["id"]
    assert q["fleet"]["dispatchAfter"] < q["army"]["dispatchAfter"]
    assert t["is_fleet_target"] == 1 and t["swept_at"] > 0


def test_ships_in_port_but_no_movements_leg_sends_nothing(monkeypatch, tmp_path):
    now = int(time.time())
    q, t = _run(monkeypatch, tmp_path, missions=[_sweep(now, garrison=LANCHAS, movements=None)],
                farm_fleet={"s216": 40}, own_fleet={"s216": 78})
    assert q == {}
    assert t["state"] == "IDLE" and t["next_action"] == "spy" and t["swept_at"] == 0


def test_combat_ships_in_port_are_never_raided_by_default(monkeypatch, tmp_path):
    now = int(time.time())
    q, t = _run(monkeypatch, tmp_path, missions=[_sweep(now, garrison={"Trirreme": 3})],
                farm_fleet={"s216": 40}, own_fleet={"s216": 78})
    assert q == {}
    assert t["state"] == "IDLE" and t["is_fleet_target"] == 1


def test_configured_blockade_away_never_falls_back_to_the_whole_fleet(monkeypatch, tmp_path):
    """The 40 rams are out on another blockade; the origin still holds every other warship.
    It used to send ALL of them."""
    now = int(time.time())
    q, t = _run(monkeypatch, tmp_path, missions=[_sweep(now, garrison=LANCHAS)],
                farm_fleet={"s216": 40}, own_fleet={"s213": 32, "s215": 36, "s218": 10})
    assert q == {}
    assert t["state"] == "IDLE"


def test_token_blockade_below_half_the_loadout_waits(monkeypatch, tmp_path):
    now = int(time.time())
    q, _ = _run(monkeypatch, tmp_path, missions=[_sweep(now, garrison=LANCHAS)],
                farm_fleet={"s216": 40}, own_fleet={"s216": 10, "s213": 32})
    assert q == {}


def test_most_of_the_loadout_is_enough(monkeypatch, tmp_path):
    now = int(time.time())
    q, _ = _run(monkeypatch, tmp_path, missions=[_sweep(now, garrison=LANCHAS)],
                farm_fleet={"s216": 40}, own_fleet={"s216": 30, "s213": 32})
    assert q["fleet"]["units"] == {"s216": 30}


def test_no_blockade_loadout_set_sends_the_whole_origin_fleet(monkeypatch, tmp_path):
    """Documented legacy behaviour (the settings card says so): with no loadout the blockade
    is everything the origin has."""
    now = int(time.time())
    q, _ = _run(monkeypatch, tmp_path, missions=[_sweep(now, garrison=LANCHAS)],
                farm_fleet={}, own_fleet={"s216": 78, "s213": 32})
    assert q["fleet"]["units"] == {"s216": 78, "s213": 32}


def test_no_combat_fleet_anywhere_sends_no_troops(monkeypatch, tmp_path):
    now = int(time.time())
    q, t = _run(monkeypatch, tmp_path, missions=[_sweep(now, garrison=LANCHAS)],
                farm_fleet={}, own_fleet={})
    assert q == {}
    assert t["state"] == "IDLE"


def test_a_raid_that_cannot_leave_does_not_rescout_the_port_within_minutes(monkeypatch, tmp_path):
    """Ships in port → the next round re-scouts. With the blockade fleet away the retry used
    to come back in 5-15 min, every time with a fresh triple sweep, for as long as it took."""
    now = int(time.time())
    _, t = _run(monkeypatch, tmp_path, missions=[_sweep(now, garrison=LANCHAS)],
                farm_fleet={"s216": 40}, own_fleet={})
    assert t["next_run_at"] >= now + 30 * 60 - 5


def test_manual_sweep_showing_ships_is_not_reused_as_the_first_scout():
    now = int(time.time())
    t = {"target_city_id": "100", "is_fleet_target": 0}
    assert fm._recent_full_sweep([_sweep(now)], t, now) is not None
    assert fm._recent_full_sweep([_sweep(now, garrison=LANCHAS)], t, now) is None
    assert fm._recent_full_sweep([_sweep(now, fleet={"Navio qualquer": 1})], t, now) is None
    assert fm._recent_full_sweep([_sweep(now, movements=now + 3600)], t, now) is None
