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
