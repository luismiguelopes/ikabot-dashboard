"""
Unit tests for espionage_manager attack-queue handling (P0 fixes):
- has_due_attacks vs has_pending_attacks (busy-loop guard in smart_sleep)
- process_attack_queue only saves when something was dispatched
- merge-on-save: items queued by Flask during the dispatch loop are never lost
Run with: python -m pytest tests/ -v
"""
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub telegram_notifier so dispatch notifications never leave the test run
_tg_stub = types.ModuleType("telegram_notifier")
_tg_stub.notify_attack_dispatched = lambda *a, **k: None
_tg_stub.notify_attack_failed = lambda *a, **k: None
sys.modules["telegram_notifier"] = _tg_stub

import espionage_manager as em


def _setup_queue(monkeypatch, tmp_path, items):
    qpath = str(tmp_path / "attack_queue.json")
    monkeypatch.setattr(em, "ATTACK_QUEUE_PATH", qpath)
    with open(qpath, "w") as f:
        json.dump({"pending": items}, f)
    return qpath


# ── has_due_attacks ───────────────────────────────────────────────────────────

def test_has_due_attacks_false_for_future_only(monkeypatch, tmp_path):
    _setup_queue(monkeypatch, tmp_path, [
        {"id": "a1", "dispatchAfter": int(time.time()) + 3600},
    ])
    assert em.has_pending_attacks() is True
    assert em.has_due_attacks() is False


def test_has_due_attacks_true_when_due(monkeypatch, tmp_path):
    _setup_queue(monkeypatch, tmp_path, [
        {"id": "a1", "dispatchAfter": int(time.time()) - 5},
        {"id": "a2", "dispatchAfter": int(time.time()) + 3600},
    ])
    assert em.has_due_attacks() is True


def test_has_due_attacks_false_when_empty(monkeypatch, tmp_path):
    _setup_queue(monkeypatch, tmp_path, [])
    assert em.has_pending_attacks() is False
    assert em.has_due_attacks() is False


# ── _queue_item_key ───────────────────────────────────────────────────────────

def test_queue_item_key_prefers_id():
    assert em._queue_item_key({"id": "abc", "originCityId": "1"}) == "abc"


def test_queue_item_key_fallback_without_id():
    item = {"originCityId": "1", "targetCityId": "2", "queuedAt": 123}
    assert em._queue_item_key(item) == "1_2_123"


def test_queue_item_key_fallback_uses_added_at():
    item = {"originCityId": "1", "targetCityId": "2", "addedAt": 456}
    assert em._queue_item_key(item) == "1_2_456"


# ── process_attack_queue ──────────────────────────────────────────────────────

def test_no_save_when_nothing_due(monkeypatch, tmp_path):
    """Future-only queue must not be rewritten (was the busy-loop disk churn)."""
    _setup_queue(monkeypatch, tmp_path, [
        {"id": "fut", "dispatchAfter": int(time.time()) + 3600},
    ])
    saves = []
    monkeypatch.setattr(em, "_save_attack_queue", lambda d: saves.append(d))
    monkeypatch.setattr(em, "_dispatch_attack", lambda s, i: True)

    em.process_attack_queue(session=None, in_active_hours=True)
    assert saves == []


def test_due_item_dispatched_and_removed(monkeypatch, tmp_path):
    now = int(time.time())
    qpath = _setup_queue(monkeypatch, tmp_path, [
        {"id": "due1", "dispatchAfter": now - 10,
         "targetPlayerName": "P", "targetCityName": "C"},
        {"id": "fut1", "dispatchAfter": now + 3600},
    ])
    dispatched = []
    monkeypatch.setattr(em, "_dispatch_attack",
                        lambda s, i: dispatched.append(i["id"]) or True)

    em.process_attack_queue(session=None, in_active_hours=True)

    assert dispatched == ["due1"]
    with open(qpath) as f:
        ids = {it["id"] for it in json.load(f)["pending"]}
    assert ids == {"fut1"}


def test_items_added_during_dispatch_survive(monkeypatch, tmp_path):
    """Race fix: Flask queues a new attack while the bot is mid-dispatch —
    the final save must keep it instead of overwriting the whole file."""
    now = int(time.time())
    qpath = _setup_queue(monkeypatch, tmp_path, [
        {"id": "due1", "dispatchAfter": now - 10,
         "targetPlayerName": "P", "targetCityName": "C"},
    ])

    def fake_dispatch(session, item):
        with open(qpath) as f:
            q = json.load(f)
        q["pending"].append({"id": "new1", "dispatchAfter": now + 60})
        with open(qpath, "w") as f:
            json.dump(q, f)
        return True

    monkeypatch.setattr(em, "_dispatch_attack", fake_dispatch)
    em.process_attack_queue(session=None, in_active_hours=True)

    with open(qpath) as f:
        ids = {it["id"] for it in json.load(f)["pending"]}
    assert ids == {"new1"}


def test_failed_dispatch_is_rescheduled(monkeypatch, tmp_path):
    """First failure: item stays in the queue with retries=1 and a future dispatchAfter."""
    now = int(time.time())
    qpath = _setup_queue(monkeypatch, tmp_path, [
        {"id": "due1", "dispatchAfter": now - 10,
         "targetPlayerName": "P", "targetCityName": "C"},
    ])
    monkeypatch.setattr(em, "_dispatch_attack", lambda s, i: False)

    em.process_attack_queue(session=None, in_active_hours=True)

    with open(qpath) as f:
        items = json.load(f)["pending"]
    assert len(items) == 1
    assert items[0]["id"] == "due1"
    assert items[0]["retries"] == 1
    assert items[0]["dispatchAfter"] > now


def test_failed_dispatch_removed_after_third_attempt(monkeypatch, tmp_path):
    now = int(time.time())
    qpath = _setup_queue(monkeypatch, tmp_path, [
        {"id": "due1", "dispatchAfter": now - 10, "retries": 2,
         "targetPlayerName": "P", "targetCityName": "C"},
    ])
    monkeypatch.setattr(em, "_dispatch_attack", lambda s, i: False)

    em.process_attack_queue(session=None, in_active_hours=True)

    with open(qpath) as f:
        assert json.load(f)["pending"] == []


# ── has_due_recalls ───────────────────────────────────────────────────────────

def _setup_recall_queue(monkeypatch, tmp_path, items):
    rpath = str(tmp_path / "spy_recall_queue.json")
    monkeypatch.setattr(em, "RECALL_QUEUE_PATH", rpath)
    with open(rpath, "w") as f:
        json.dump({"pending": items}, f)
    return rpath


def test_has_due_recalls_true_without_next_attempt(monkeypatch, tmp_path):
    _setup_recall_queue(monkeypatch, tmp_path, [
        {"originCityId": "1", "targetCityId": "2", "queuedAt": 1},
    ])
    assert em.has_due_recalls() is True


def test_has_due_recalls_false_when_waiting_retry(monkeypatch, tmp_path):
    _setup_recall_queue(monkeypatch, tmp_path, [
        {"originCityId": "1", "targetCityId": "2", "queuedAt": 1,
         "nextAttemptAfter": int(time.time()) + 600},
    ])
    assert em.has_due_recalls() is False


def test_has_due_recalls_false_when_empty(monkeypatch, tmp_path):
    _setup_recall_queue(monkeypatch, tmp_path, [])
    assert em.has_due_recalls() is False
