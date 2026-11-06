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


# ── Fair ship split (water-filling) ────────────────────────────────────────────

def test_fair_ship_split_serves_small_cities_in_full():
    # One rich city, two small: the small ones are served fully and the rich city
    # soaks up the rest — no ship wasted when there is slack.
    assert tm._fair_ship_split([300, 10, 10], 338) == [300, 10, 10]


def test_fair_ship_split_spreads_when_fleet_scarce():
    # Three equally hungry cities, too few ships: spread evenly instead of the first
    # city grabbing everything.
    grant = tm._fair_ship_split([300, 300, 300], 338)
    assert sum(grant) == 338
    assert max(grant) - min(grant) <= 1          # even to within one ship
    assert all(g > 0 for g in grant)             # every city gets a slice


def test_fair_ship_split_never_exceeds_need_or_supply():
    assert tm._fair_ship_split([5, 0, 2], 100) == [5, 0, 2]   # capped to need
    assert sum(tm._fair_ship_split([10, 10], 4)) == 4         # capped to supply
    assert tm._fair_ship_split([0, 0], 50) == [0, 0]          # nothing wanted
    assert tm._fair_ship_split([3, 3], 0) == [0, 0]           # nothing available


def _run_consolidation_multi(monkeypatch, tmp_path, stocks, ships, cap):
    """Drive process_consolidation with several surplus-rich source cities sharing a
    scarce freighter pool; return list of (city_name, total_sent) dispatches."""
    import queue_processor as qp
    monkeypatch.setattr(tm, "CONSOLIDATE_SETTINGS_PATH", str(tmp_path / "cs.json"))
    monkeypatch.setattr(tm, "CONSOLIDATE_STATE_PATH", str(tmp_path / "st.json"))
    monkeypatch.setattr(tm, "OWN_CITIES_PATH", str(tmp_path / "own.json"))
    monkeypatch.setattr(tm.random, "randint", lambda a, b: 0)

    with open(tmp_path / "cs.json", "w") as f:
        json.dump({"enabled": True, "destCityId": "99", "destCityName": "Dest",
                   "intervalHours": 6, "minSendTotal": 1000, "shipType": "freighters",
                   "respectDestCap": False}, f)
    own = [{"cityId": 99, "name": "Dest", "x": 1, "y": 1, "islandId": "7"}]
    for i, name in enumerate(stocks):
        own.append({"cityId": i + 1, "name": name, "x": 2, "y": 2, "islandId": "8"})
    with open(tmp_path / "own.json", "w") as f:
        json.dump(own, f)

    monkeypatch.setattr(qp, "_load_resources_json",
                        lambda: {name: {"Wood": amt} for name, amt in stocks.items()})
    monkeypatch.setattr(qp, "_load_empire_json", lambda: {})
    monkeypatch.setattr(qp, "_calc_city_reserved", lambda *a: [0, 0, 0, 0, 0])
    monkeypatch.setattr(qp, "_load_queue", lambda: {"queues": {}})
    monkeypatch.setattr(qp, "_get_resource_buffer", lambda: [0, 0, 0, 0, 0])

    import ikabot.helpers.naval as naval
    import ikabot.helpers.pedirInfo as pedir
    monkeypatch.setattr(naval, "getAvailableShips", lambda s: 0, raising=False)
    monkeypatch.setattr(naval, "getAvailableFreighters", lambda s: ships, raising=False)
    monkeypatch.setattr(pedir, "getShipCapacity", lambda s: (5000, cap), raising=False)

    calls = []
    names_by_id = {str(i + 1): name for i, name in enumerate(stocks)}

    def fake_dispatch(session, origin, dest, island, ships_used, send_list, use_freighters=False):
        calls.append((names_by_id.get(str(origin), str(origin)), sum(send_list)))
        return True
    monkeypatch.setattr(qp, "_dispatch_transport", fake_dispatch)

    tm.process_consolidation(session=object(), in_active_hours=True)
    return calls


def test_consolidation_spreads_scarce_fleet_across_cities(monkeypatch, tmp_path):
    """Two rich cities, only 4 freighters (cap 25000): instead of the first city
    taking all 4, each city ships in the same round (fair split)."""
    stocks = {"Rich1": 1_000_000, "Rich2": 1_000_000}
    calls = _run_consolidation_multi(monkeypatch, tmp_path, stocks, ships=4, cap=25000)
    assert len(calls) == 2                       # both cities served this round
    sent_by = dict(calls)
    assert sent_by["Rich1"] == 50000 and sent_by["Rich2"] == 50000  # 2 freighters each


def test_consolidation_fullest_city_first(monkeypatch, tmp_path):
    """With only enough ships for one city, the fullest is served first."""
    stocks = {"Small": 60_000, "Huge": 2_000_000}
    calls = _run_consolidation_multi(monkeypatch, tmp_path, stocks, ships=1, cap=25000)
    assert calls[0][0] == "Huge"                 # fullest relieved first


def test_consolidation_caps_to_dest_headroom_and_skips_resources(monkeypatch, tmp_path):
    """Never overflow the destination: a nearly-full dest only receives its free space,
    and a resource named in skipResources (wine) is never sent."""
    import queue_processor as qp
    monkeypatch.setattr(tm, "CONSOLIDATE_SETTINGS_PATH", str(tmp_path / "cs.json"))
    monkeypatch.setattr(tm, "CONSOLIDATE_STATE_PATH", str(tmp_path / "st.json"))
    monkeypatch.setattr(tm, "OWN_CITIES_PATH", str(tmp_path / "own.json"))
    monkeypatch.setattr(tm.random, "randint", lambda a, b: 0)

    with open(tmp_path / "cs.json", "w") as f:
        json.dump({"enabled": True, "destCityId": "99", "destCityName": "Dest",
                   "intervalHours": 6, "minSendTotal": 1000, "shipType": "freighters",
                   "skipResources": ["Wine"]}, f)
    with open(tmp_path / "own.json", "w") as f:
        json.dump([{"cityId": 99, "name": "Dest", "x": 1, "y": 1, "islandId": "7"},
                   {"cityId": 1,  "name": "Src",  "x": 2, "y": 2, "islandId": "8"}], f)

    # Dest cap 1,000,000 already holding 900,000 wood → only 100,000 free wood; wine full room.
    monkeypatch.setattr(qp, "_load_resources_json", lambda: {
        "Src":  {"Wood": 5000000, "Wine": 5000000},
        "Dest": {"Wood": 900000, "Wine": 0, "storageCapacity": 1000000},
    })
    monkeypatch.setattr(qp, "_load_empire_json", lambda: {})
    monkeypatch.setattr(qp, "_calc_city_reserved", lambda *a: [0, 0, 0, 0, 0])
    monkeypatch.setattr(qp, "_load_queue", lambda: {"queues": {}})
    monkeypatch.setattr(qp, "_get_resource_buffer", lambda: [0, 0, 0, 0, 0])

    import ikabot.helpers.naval as naval
    import ikabot.helpers.pedirInfo as pedir
    monkeypatch.setattr(naval, "getAvailableShips", lambda s: 0, raising=False)
    monkeypatch.setattr(naval, "getAvailableFreighters", lambda s: 1000, raising=False)
    monkeypatch.setattr(pedir, "getShipCapacity", lambda s: (5000, 25000), raising=False)

    sent = []
    def fake_dispatch(session, origin, dest, island, ships, send_list, use_freighters=False):
        sent.append(list(send_list))
        return True
    monkeypatch.setattr(qp, "_dispatch_transport", fake_dispatch)

    tm.process_consolidation(session=object(), in_active_hours=True)

    assert len(sent) == 1
    assert sent[0][0] == 100000   # Wood capped to the destination's free space
    assert sent[0][1] == 0        # Wine never sent (skipResources)


# ── Wine balancer (F9) ────────────────────────────────────────────────────────

def test_wine_settings_defaults_and_save(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "WINE_SETTINGS_PATH", str(tmp_path / "w.json"))
    assert tm.get_wine_settings()["enabled"] is True  # on by default (a wine-out costs population)
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
        "Dry":    {"Wine": 1000,   "wineConsumptionPerHour": 1000, "wineProductionPerHour": 0,
                   "wineRunsOutIn": 1 * 3600},
        # real producer: wineProductionPerHour > 0 (runway -1 alone no longer means producer)
        "Vinery": {"Wine": 500000, "wineConsumptionPerHour": 500, "wineProductionPerHour": 600,
                   "wineRunsOutIn": -1},
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
