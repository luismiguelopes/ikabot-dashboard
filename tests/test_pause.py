"""
Tests for the global pause (F11): is_paused() and the processor guards.
Run with: python -m pytest tests/ -v
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import empire_utils
import db_manager
import attack_manager as am
import transport_manager as tm


def _setup(tmp_path, paused):
    pause_path = str(tmp_path / "pause.json")
    empire_utils.PAUSE_PATH = pause_path
    if paused is not None:
        with open(pause_path, "w") as f:
            json.dump({"paused": paused}, f)


def test_is_paused_default_false(tmp_path):
    empire_utils.PAUSE_PATH = str(tmp_path / "nope.json")
    assert empire_utils.is_paused() is False


def test_is_paused_true(tmp_path):
    _setup(tmp_path, True)
    assert empire_utils.is_paused() is True


def test_is_paused_false(tmp_path):
    _setup(tmp_path, False)
    assert empire_utils.is_paused() is False


def test_attack_queue_skipped_when_paused(monkeypatch, tmp_path):
    _setup(tmp_path, True)
    db_manager.DB_PATH = str(tmp_path / "t.db")
    db_manager._LOGS_DIR = str(tmp_path)
    db_manager._DB_INIT_DONE = False
    db_manager.queue_add("attack", {"id": "a1", "dispatchAfter": int(time.time()) - 10})
    called = []
    monkeypatch.setattr(am, "_dispatch_attack", lambda s, i: called.append(1) or True)

    am.process_attack_queue(session=None, in_active_hours=True)
    assert called == []  # paused → no dispatch
    # item still in the queue, untouched
    assert len(db_manager.queue_items("attack")) == 1


def test_transport_queue_skipped_when_paused(monkeypatch, tmp_path):
    _setup(tmp_path, True)
    db_manager.DB_PATH = str(tmp_path / "t2.db")
    db_manager._LOGS_DIR = str(tmp_path)
    db_manager._DB_INIT_DONE = False
    db_manager.queue_add("transport", {"id": "t1", "dispatchAfter": int(time.time()) - 10})
    called = []
    monkeypatch.setattr(tm, "_dispatch_scheduled_transport",
                        lambda s, i: called.append(1) or (True, None))

    tm.process_transport_queue(session=None, in_active_hours=True)
    assert called == []


def test_attack_queue_runs_when_not_paused(monkeypatch, tmp_path):
    _setup(tmp_path, False)
    db_manager.DB_PATH = str(tmp_path / "t3.db")
    db_manager._LOGS_DIR = str(tmp_path)
    db_manager._DB_INIT_DONE = False
    db_manager.queue_add("attack", {"id": "a1", "dispatchAfter": int(time.time()) - 10,
                                    "targetPlayerName": "P", "targetCityName": "C"})
    called = []
    monkeypatch.setattr(am, "_dispatch_attack", lambda s, i: called.append(1) or True)

    am.process_attack_queue(session=None, in_active_hours=True)
    assert called == [1]
    assert db_manager.queue_items("attack") == []
