"""
Tests for the farm ship reservation: internal logistics must leave enough trade ships
free for any imminent farm raid. Run with: python -m pytest tests/ -v
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import farm_manager as fm


def _setup(monkeypatch, tmp_path, targets, queue=None, settings=None):
    settings = settings if settings is not None else {}
    path = tmp_path / "farm_settings.json"
    with open(path, "w") as f:
        json.dump(settings, f)
    monkeypatch.setattr(fm, "FARM_SETTINGS_PATH", str(path))
    # _enabled_targets / _pending_plunder_transporters import db_manager lazily
    import db_manager
    monkeypatch.setattr(db_manager, "farm_list", lambda: targets)
    monkeypatch.setattr(db_manager, "queue_items", lambda q: (queue or []) if q == "attack" else [])


def test_no_targets_no_queue(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, [])
    assert fm.farm_ship_reserve() == 0


def test_due_target_reserves_its_transporters(monkeypatch, tmp_path):
    now = int(time.time())
    _setup(monkeypatch, tmp_path, [
        {"enabled": True, "state": "IDLE", "next_run_at": now - 10, "last_transporters": 7},
    ])
    assert fm.farm_ship_reserve(now) == 7


def test_attacking_target_not_reserved(monkeypatch, tmp_path):
    now = int(time.time())
    _setup(monkeypatch, tmp_path, [
        {"enabled": True, "state": "ATTACKING", "next_run_at": now - 10, "last_transporters": 9},
    ])
    assert fm.farm_ship_reserve(now) == 0   # ships already out on the raid


def test_future_target_beyond_horizon_not_reserved(monkeypatch, tmp_path):
    now = int(time.time())
    _setup(monkeypatch, tmp_path, [
        {"enabled": True, "state": "IDLE",
         "next_run_at": now + 3 * 3600, "last_transporters": 5},
    ])
    assert fm.farm_ship_reserve(now) == 0   # due in 3h, horizon is 45 min


def test_unknown_transporters_uses_floor(monkeypatch, tmp_path):
    now = int(time.time())
    _setup(monkeypatch, tmp_path, [
        {"enabled": True, "state": "IDLE", "next_run_at": now - 10, "last_transporters": 0},
    ])
    assert fm.farm_ship_reserve(now) == fm._MIN_RESERVE_PER_TARGET


def test_pending_plunder_counted(monkeypatch, tmp_path):
    now = int(time.time())
    _setup(monkeypatch, tmp_path, [], queue=[
        {"missionType": "army", "transporters": 4, "dispatchAfter": now},
        {"missionType": "fleet", "transporters": 0, "dispatchAfter": now},   # no ships
        {"missionType": "army", "transporters": 6, "dispatchAfter": now + 10 * 3600},  # too far
    ])
    assert fm.farm_ship_reserve(now) == 4


def test_disabled_setting_returns_zero(monkeypatch, tmp_path):
    now = int(time.time())
    _setup(monkeypatch, tmp_path, [
        {"enabled": True, "state": "IDLE", "next_run_at": now - 10, "last_transporters": 7},
    ], settings={"shipReserveEnabled": False})
    assert fm.farm_ship_reserve(now) == 0


def test_apply_ship_reserve_caps_and_floors(monkeypatch, tmp_path):
    now = int(time.time())
    _setup(monkeypatch, tmp_path, [
        {"enabled": True, "state": "IDLE", "next_run_at": now - 10, "last_transporters": 5},
    ])
    # 8 available, 5 reserved → 3 usable
    assert fm.apply_ship_reserve(8, "test", now) == 3
    # reserve exceeds availability → never negative
    assert fm.apply_ship_reserve(3, "test", now) == 0


def test_multiple_due_targets_sum(monkeypatch, tmp_path):
    now = int(time.time())
    _setup(monkeypatch, tmp_path, [
        {"enabled": True, "state": "IDLE", "next_run_at": now - 10, "last_transporters": 3},
        {"enabled": True, "state": "IDLE", "next_run_at": now + 20 * 60, "last_transporters": 2},
        {"enabled": True, "state": "ATTACKING", "next_run_at": now, "last_transporters": 9},
    ])
    assert fm.farm_ship_reserve(now) == 5   # 3 + 2, ATTACKING skipped
