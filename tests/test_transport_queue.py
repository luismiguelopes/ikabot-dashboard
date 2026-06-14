"""
Unit tests for transport_manager (scheduled transports + consolidation helpers).
Run with: python -m pytest tests/ -v
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_manager
import transport_manager as tm


def _setup_db(tmp_path):
    db_manager.DB_PATH = str(tmp_path / "test.db")
    db_manager._LOGS_DIR = str(tmp_path)
    db_manager._DB_INIT_DONE = False


# ── has_due_transports ────────────────────────────────────────────────────────

def test_has_due_transports_false_for_future_only(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("transport", {"id": "t1", "dispatchAfter": int(time.time()) + 3600})
    assert tm.has_pending_transports() is True
    assert tm.has_due_transports() is False


def test_has_due_transports_true_when_due(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("transport", {"id": "t1", "dispatchAfter": int(time.time()) - 5})
    assert tm.has_due_transports() is True


def test_has_due_transports_false_when_empty(tmp_path):
    _setup_db(tmp_path)
    assert tm.has_due_transports() is False


# ── process_transport_queue ───────────────────────────────────────────────────

def test_due_transport_dispatched_and_removed(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.queue_add("transport", {
        "id": "t1", "dispatchAfter": now - 10,
        "originCityName": "A", "destCityName": "B",
    })
    db_manager.queue_add("transport", {"id": "fut", "dispatchAfter": now + 3600})
    sent = []
    monkeypatch.setattr(tm, "_dispatch_scheduled_transport",
                        lambda s, i: (sent.append(i["id"]) or True, None))

    tm.process_transport_queue(session=None, in_active_hours=True)

    assert sent == ["t1"]
    assert {it["id"] for it in db_manager.queue_items("transport")} == {"fut"}


def test_failed_transport_rescheduled_then_removed(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    now = int(time.time())
    db_manager.queue_add("transport", {
        "id": "t1", "dispatchAfter": now - 10,
        "originCityName": "A", "destCityName": "B",
    })
    monkeypatch.setattr(tm, "_dispatch_scheduled_transport",
                        lambda s, i: (False, "sem navios livres"))

    tm.process_transport_queue(session=None, in_active_hours=True)
    items = db_manager.queue_items("transport")
    assert len(items) == 1 and items[0]["retries"] == 1
    assert items[0]["dispatchAfter"] > now

    # third failure → removed
    db_manager.queue_add("transport", dict(items[0], retries=2, dispatchAfter=now - 5))
    tm.process_transport_queue(session=None, in_active_hours=True)
    assert db_manager.queue_items("transport") == []


def test_outside_active_hours_does_nothing(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("transport", {"id": "t1", "dispatchAfter": 0})
    called = []
    monkeypatch.setattr(tm, "_dispatch_scheduled_transport",
                        lambda s, i: (called.append(1) or True, None))
    tm.process_transport_queue(session=None, in_active_hours=False)
    assert called == []


# ── Consolidation helpers ─────────────────────────────────────────────────────

def test_calc_surplus_respects_buffer_and_reserved():
    avail    = [10000, 5000, 8000, 0, 3000]
    buffer   = [2000, 2000, 2000, 2000, 2000]
    reserved = [1000, 0, 9000, 0, 0]
    assert tm._calc_surplus(avail, buffer, reserved) == [7000, 3000, 0, 0, 1000]


def test_consolidate_settings_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "CONSOLIDATE_SETTINGS_PATH", str(tmp_path / "cs.json"))
    s = tm.get_consolidate_settings()
    assert s["enabled"] is False
    assert s["intervalHours"] == 6
    assert s["shipType"] == "transporters"


def test_consolidate_settings_backfills_shiptype(tmp_path, monkeypatch):
    """Settings saved before F12.shipType existed must still get the default."""
    monkeypatch.setattr(tm, "CONSOLIDATE_SETTINGS_PATH", str(tmp_path / "cs.json"))
    with open(tmp_path / "cs.json", "w") as f:
        json.dump({"enabled": True, "destCityId": "5", "intervalHours": 3}, f)
    s = tm.get_consolidate_settings()
    assert s["shipType"] == "transporters"
    assert s["destCityId"] == "5"


def _run_consolidation(monkeypatch, tmp_path, ship_type):
    """Drive process_consolidation with a single surplus-rich source city and
    stubbed game helpers; return the list of (use_freighters, total) dispatches."""
    import queue_processor as qp
    monkeypatch.setattr(tm, "CONSOLIDATE_SETTINGS_PATH", str(tmp_path / "cs.json"))
    monkeypatch.setattr(tm, "CONSOLIDATE_STATE_PATH", str(tmp_path / "st.json"))
    monkeypatch.setattr(tm, "OWN_CITIES_PATH", str(tmp_path / "own.json"))
    monkeypatch.setattr(tm.random, "randint", lambda a, b: 0)  # no real sleeps

    with open(tmp_path / "cs.json", "w") as f:
        json.dump({"enabled": True, "destCityId": "99", "destCityName": "Dest",
                   "intervalHours": 6, "minSendTotal": 1000, "shipType": ship_type}, f)
    with open(tmp_path / "own.json", "w") as f:
        json.dump([{"cityId": 99, "name": "Dest", "x": 1, "y": 1, "islandId": "7"},
                   {"cityId": 1,  "name": "Src",  "x": 2, "y": 2, "islandId": "8"}], f)

    # Surplus far larger than one ship-load so a freighter pass has leftover to send
    monkeypatch.setattr(qp, "_load_resources_json", lambda: {"Src": {"Wood": 100000}})
    monkeypatch.setattr(qp, "_load_empire_json", lambda: {})
    monkeypatch.setattr(qp, "_calc_city_reserved", lambda *a: [0, 0, 0, 0, 0])
    monkeypatch.setattr(qp, "_load_queue", lambda: {"queues": {}})
    monkeypatch.setattr(qp, "_get_resource_buffer", lambda: [0, 0, 0, 0, 0])

    import ikabot.helpers.naval as naval
    import ikabot.helpers.pedirInfo as pedir
    monkeypatch.setattr(naval, "getAvailableShips", lambda s: 2, raising=False)
    monkeypatch.setattr(naval, "getAvailableFreighters", lambda s: 2, raising=False)
    monkeypatch.setattr(pedir, "getShipCapacity", lambda s: (5000, 25000), raising=False)

    calls = []
    def fake_dispatch(session, origin, dest, island, ships, send_list, use_freighters=False):
        calls.append((use_freighters, sum(send_list)))
        return True
    monkeypatch.setattr(qp, "_dispatch_transport", fake_dispatch)

    tm.process_consolidation(session=object(), in_active_hours=True)
    return calls


def test_consolidation_transporters_only(monkeypatch, tmp_path):
    calls = _run_consolidation(monkeypatch, tmp_path, "transporters")
    assert len(calls) == 1
    assert calls[0][0] is False  # use_freighters


def test_consolidation_freighters_only(monkeypatch, tmp_path):
    calls = _run_consolidation(monkeypatch, tmp_path, "freighters")
    assert len(calls) == 1
    assert calls[0][0] is True


def test_consolidation_both_does_two_passes(monkeypatch, tmp_path):
    calls = _run_consolidation(monkeypatch, tmp_path, "both")
    assert [c[0] for c in calls] == [False, True]  # transporters first, then freighters


# ── Wine balancer (F9) ────────────────────────────────────────────────────────

def test_wine_settings_defaults_and_save(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "WINE_SETTINGS_PATH", str(tmp_path / "w.json"))
    assert tm.get_wine_settings()["enabled"] is False
    saved = tm.save_wine_settings({"enabled": True, "thresholdHours": 10, "targetHours": 60})
    assert saved["thresholdHours"] == 10 and saved["targetHours"] == 60
    assert tm.get_wine_settings()["enabled"] is True


def test_wine_target_not_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "WINE_SETTINGS_PATH", str(tmp_path / "w.json"))
    saved = tm.save_wine_settings({"enabled": True, "thresholdHours": 24, "targetHours": 10})
    assert saved["targetHours"] >= saved["thresholdHours"]  # clamped up to threshold


def test_wine_balancer_ships_wine_to_needy(monkeypatch, tmp_path):
    """Needy city (low runway) gets wine from a self-sufficient city."""
    monkeypatch.setattr(tm, "WINE_SETTINGS_PATH", str(tmp_path / "w.json"))
    monkeypatch.setattr(tm, "OWN_CITIES_PATH", str(tmp_path / "own.json"))
    monkeypatch.setattr(tm.random, "randint", lambda a, b: 0)
    tm.save_wine_settings({"enabled": True, "thresholdHours": 12, "targetHours": 48})
    with open(tmp_path / "own.json", "w") as f:
        json.dump([{"cityId": 1, "name": "Dry",   "islandId": "5"},
                   {"cityId": 2, "name": "Vinery", "islandId": "6"}], f)

    import queue_processor as qp
    monkeypatch.setattr(qp, "_load_resources_json", lambda: {
        "Dry":    {"Wine": 1000,   "wineConsumptionPerHour": 1000, "wineRunsOutIn": 1 * 3600},
        "Vinery": {"Wine": 500000, "wineConsumptionPerHour": 500,  "wineRunsOutIn": -1},
    })
    import ikabot.helpers.naval as naval
    import ikabot.helpers.pedirInfo as pedir
    monkeypatch.setattr(naval, "getAvailableShips", lambda s: 100, raising=False)
    monkeypatch.setattr(pedir, "getShipCapacity", lambda s: (5000, 25000), raising=False)

    calls = []
    def fake_dispatch(session, origin, dest, island, ships, send_list, use_freighters=False):
        calls.append((str(origin), str(dest), send_list[1]))
        return True
    monkeypatch.setattr(qp, "_dispatch_transport", fake_dispatch)

    tm.process_wine_balancer(session=object(), in_active_hours=True)

    assert len(calls) == 1
    origin, dest, wine_amt = calls[0]
    assert origin == "2" and dest == "1"   # Vinery → Dry
    # Dry needs 1000*48 - 1000 = 47000 wine; capped by ships (100*5000) so full deficit
    assert wine_amt == 47000


def test_wine_balancer_noop_when_no_needy(monkeypatch, tmp_path):
    monkeypatch.setattr(tm, "WINE_SETTINGS_PATH", str(tmp_path / "w.json"))
    monkeypatch.setattr(tm, "OWN_CITIES_PATH", str(tmp_path / "own.json"))
    tm.save_wine_settings({"enabled": True, "thresholdHours": 12, "targetHours": 48})
    with open(tmp_path / "own.json", "w") as f:
        json.dump([{"cityId": 1, "name": "A", "islandId": "5"}], f)
    import queue_processor as qp
    monkeypatch.setattr(qp, "_load_resources_json", lambda: {
        "A": {"Wine": 999999, "wineConsumptionPerHour": 100, "wineRunsOutIn": -1},
    })
    calls = []
    monkeypatch.setattr(qp, "_dispatch_transport",
                        lambda *a, **k: calls.append(1) or True)
    tm.process_wine_balancer(session=object(), in_active_hours=True)
    assert calls == []


def test_consolidation_skips_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(tm, "CONSOLIDATE_SETTINGS_PATH", str(tmp_path / "cs.json"))
    with open(tmp_path / "cs.json", "w") as f:
        json.dump({"enabled": False, "destCityId": "1"}, f)
    # would explode on session=None if it proceeded past the guards
    tm.process_consolidation(session=None, in_active_hours=True)


def test_consolidation_respects_interval(monkeypatch, tmp_path):
    monkeypatch.setattr(tm, "CONSOLIDATE_SETTINGS_PATH", str(tmp_path / "cs.json"))
    monkeypatch.setattr(tm, "CONSOLIDATE_STATE_PATH", str(tmp_path / "st.json"))
    with open(tmp_path / "cs.json", "w") as f:
        json.dump({"enabled": True, "destCityId": "99", "intervalHours": 6}, f)
    with open(tmp_path / "st.json", "w") as f:
        json.dump({"lastRun": int(time.time()) - 60, "lastSent": {}}, f)
    # lastRun 1 min ago < 6h interval → returns before touching the session
    tm.process_consolidation(session=None, in_active_hours=True)
