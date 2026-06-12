"""
Unit tests for the SQLite-backed shared queues (attack / spy dispatch / recall):
- db_manager.queue_add / queue_items / queue_remove + JSON migration
- has_due_attacks vs has_pending_attacks (busy-loop guard in smart_sleep)
- process_attack_queue: per-item removal, retry with backoff, no save-back race
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

import db_manager
import attack_manager as am
import espionage_manager as em


def _setup_db(tmp_path):
    db_manager.DB_PATH = str(tmp_path / "test.db")
    db_manager._LOGS_DIR = str(tmp_path)
    db_manager._DB_INIT_DONE = False


def _add_attacks(items):
    for it in items:
        db_manager.queue_add("attack", it)


# ── db_manager shared queue primitives ────────────────────────────────────────

def test_queue_add_assigns_id_and_items_roundtrip(tmp_path):
    _setup_db(tmp_path)
    item_id = db_manager.queue_add("attack", {"targetCityId": "9", "queuedAt": 1})
    assert item_id
    items = db_manager.queue_items("attack")
    assert len(items) == 1
    assert items[0]["id"] == item_id
    assert items[0]["targetCityId"] == "9"


def test_queue_add_replaces_by_id(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("attack", {"id": "x1", "retries": 0})
    db_manager.queue_add("attack", {"id": "x1", "retries": 2})
    items = db_manager.queue_items("attack")
    assert len(items) == 1
    assert items[0]["retries"] == 2


def test_queue_remove(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("attack", {"id": "a"})
    db_manager.queue_add("attack", {"id": "b"})
    assert db_manager.queue_remove("attack", ["a"]) == 1
    assert db_manager.queue_remove("attack", ["inexistente"]) == 0
    assert [it["id"] for it in db_manager.queue_items("attack")] == ["b"]


def test_queues_are_isolated_by_name(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("attack", {"id": "a"})
    db_manager.queue_add("spy_recall", {"id": "r"})
    assert len(db_manager.queue_items("attack")) == 1
    assert len(db_manager.queue_items("spy_recall")) == 1
    db_manager.queue_remove("attack", ["a"])
    assert len(db_manager.queue_items("spy_recall")) == 1


def test_migration_imports_legacy_json_and_renames(tmp_path):
    _setup_db(tmp_path)
    legacy = tmp_path / "attack_queue.json"
    with open(legacy, "w") as f:
        json.dump({"pending": [{"id": "old1", "targetCityId": "5"},
                               {"targetCityId": "6", "queuedAt": 2}]}, f)
    items = db_manager.queue_items("attack")  # init_db triggers migration
    ids = {it["id"] for it in items}
    assert "old1" in ids and len(items) == 2
    assert all(it.get("id") for it in items)  # legacy item without id got one
    assert not legacy.exists()
    assert (tmp_path / "attack_queue.json.migrated").exists()


# ── has_due_attacks ───────────────────────────────────────────────────────────

def test_has_due_attacks_false_for_future_only(tmp_path):
    _setup_db(tmp_path)
    _add_attacks([{"id": "a1", "dispatchAfter": int(time.time()) + 3600}])
    assert am.has_pending_attacks() is True
    assert am.has_due_attacks() is False


def test_has_due_attacks_true_when_due(tmp_path):
    _setup_db(tmp_path)
    _add_attacks([
        {"id": "a1", "dispatchAfter": int(time.time()) - 5},
        {"id": "a2", "dispatchAfter": int(time.time()) + 3600},
    ])
    assert am.has_due_attacks() is True


def test_has_due_attacks_false_when_empty(tmp_path):
    _setup_db(tmp_path)
    assert am.has_pending_attacks() is False
    assert am.has_due_attacks() is False


# ── process_attack_queue ──────────────────────────────────────────────────────

def test_future_items_left_untouched(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    _add_attacks([{"id": "fut", "dispatchAfter": int(time.time()) + 3600}])
    dispatched = []
    monkeypatch.setattr(am, "_dispatch_attack",
                        lambda s, i: dispatched.append(i["id"]) or True)

    am.process_attack_queue(session=None, in_active_hours=True)

    assert dispatched == []
    assert [it["id"] for it in db_manager.queue_items("attack")] == ["fut"]


def test_due_item_dispatched_and_removed(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    now = int(time.time())
    _add_attacks([
        {"id": "due1", "dispatchAfter": now - 10,
         "targetPlayerName": "P", "targetCityName": "C"},
        {"id": "fut1", "dispatchAfter": now + 3600},
    ])
    dispatched = []
    monkeypatch.setattr(am, "_dispatch_attack",
                        lambda s, i: dispatched.append(i["id"]) or True)

    am.process_attack_queue(session=None, in_active_hours=True)

    assert dispatched == ["due1"]
    assert {it["id"] for it in db_manager.queue_items("attack")} == {"fut1"}


def test_items_added_during_dispatch_survive(monkeypatch, tmp_path):
    """Race fix: an attack queued by Flask while the bot is mid-dispatch must survive."""
    _setup_db(tmp_path)
    now = int(time.time())
    _add_attacks([{"id": "due1", "dispatchAfter": now - 10,
                   "targetPlayerName": "P", "targetCityName": "C"}])

    def fake_dispatch(session, item):
        db_manager.queue_add("attack", {"id": "new1", "dispatchAfter": now + 60})
        return True

    monkeypatch.setattr(am, "_dispatch_attack", fake_dispatch)
    am.process_attack_queue(session=None, in_active_hours=True)

    assert {it["id"] for it in db_manager.queue_items("attack")} == {"new1"}


def test_failed_dispatch_is_rescheduled(monkeypatch, tmp_path):
    """First failure: item stays with retries=1 and a future dispatchAfter."""
    _setup_db(tmp_path)
    now = int(time.time())
    _add_attacks([{"id": "due1", "dispatchAfter": now - 10,
                   "targetPlayerName": "P", "targetCityName": "C"}])
    monkeypatch.setattr(am, "_dispatch_attack", lambda s, i: False)

    am.process_attack_queue(session=None, in_active_hours=True)

    items = db_manager.queue_items("attack")
    assert len(items) == 1
    assert items[0]["id"] == "due1"
    assert items[0]["retries"] == 1
    assert items[0]["dispatchAfter"] > now


def test_failed_dispatch_removed_after_third_attempt(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    now = int(time.time())
    _add_attacks([{"id": "due1", "dispatchAfter": now - 10, "retries": 2,
                   "targetPlayerName": "P", "targetCityName": "C"}])
    monkeypatch.setattr(am, "_dispatch_attack", lambda s, i: False)

    am.process_attack_queue(session=None, in_active_hours=True)

    assert db_manager.queue_items("attack") == []


# ── has_due_recalls ───────────────────────────────────────────────────────────

def test_has_due_recalls_true_without_next_attempt(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("spy_recall", {"originCityId": "1", "targetCityId": "2"})
    assert em.has_due_recalls() is True


def test_has_due_recalls_false_when_waiting_retry(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("spy_recall", {
        "originCityId": "1", "targetCityId": "2",
        "nextAttemptAfter": int(time.time()) + 600,
    })
    assert em.has_due_recalls() is False


def test_has_due_recalls_false_when_empty(tmp_path):
    _setup_db(tmp_path)
    assert em.has_due_recalls() is False
