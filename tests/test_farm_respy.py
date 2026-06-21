"""
Tests for the pipelined re-spy (scout while troops return) and the next-round-needs-spy
decision. Run with: python -m pytest tests/ -v
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import farm_manager as fm


def _settings(monkeypatch, tmp_path, settings):
    path = tmp_path / "farm_settings.json"
    with open(path, "w") as f:
        json.dump(settings, f)
    monkeypatch.setattr(fm, "FARM_SETTINGS_PATH", str(path))


def _targets(monkeypatch, targets):
    import db_manager
    monkeypatch.setattr(db_manager, "farm_list", lambda: targets)


# ── _next_round_needs_spy ──────────────────────────────────────────────────────

def test_needs_spy_when_cadence_due():
    assert fm._next_round_needs_spy({"raids_since_spy": 3, "respy_every": 3}) is True
    assert fm._next_round_needs_spy({"raids_since_spy": 4, "respy_every": 3}) is True


def test_no_spy_between_cadence():
    assert fm._next_round_needs_spy({"raids_since_spy": 1, "respy_every": 3}) is False


def test_needs_spy_when_target_had_fleet():
    # even mid-cadence, a target that ever showed ships must be re-scouted
    assert fm._next_round_needs_spy(
        {"raids_since_spy": 1, "respy_every": 3, "last_enemy_ships": 2}) is True


def test_needs_spy_for_known_fleet_target():
    # a fleet-target (fleet flees & returns) must always re-scout, even with 0 ships now
    assert fm._next_round_needs_spy(
        {"raids_since_spy": 1, "respy_every": 3, "last_enemy_ships": 0,
         "is_fleet_target": 1}) is True


# ── early_respy_enabled ─────────────────────────────────────────────────────────

def test_early_respy_default_on(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, {})
    assert fm.early_respy_enabled() is True


def test_early_respy_kill_switch(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, {"earlyRespyEnabled": False})
    assert fm.early_respy_enabled() is False


# ── has_due_farm / next_farm_eta early-respy window ─────────────────────────────

def test_attacking_due_in_early_respy_window(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, {})
    now = int(time.time())
    ra = now + 60   # troops dock in 60s — inside the 5-min early-respy lead
    _targets(monkeypatch, [{
        "enabled": True, "state": "ATTACKING", "attack_return_at": ra,
        "respy_launched_at": 0, "raids_since_spy": 3, "respy_every": 3,
        "target_city_id": "1",
    }])
    assert fm.has_due_farm() is True


def test_attacking_not_due_before_window(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, {})
    now = int(time.time())
    ra = now + 30 * 60   # 30 min out — well before the 5-min lead window
    _targets(monkeypatch, [{
        "enabled": True, "state": "ATTACKING", "attack_return_at": ra,
        "respy_launched_at": 0, "raids_since_spy": 3, "respy_every": 3,
        "target_city_id": "1",
    }])
    assert fm.has_due_farm() is False


def test_attacking_no_early_respy_when_not_a_spy_round(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, {})
    now = int(time.time())
    ra = now + 60
    _targets(monkeypatch, [{
        "enabled": True, "state": "ATTACKING", "attack_return_at": ra,
        "respy_launched_at": 0, "raids_since_spy": 1, "respy_every": 3,
        "last_enemy_ships": 0, "target_city_id": "1",
    }])
    assert fm.has_due_farm() is False   # direct-attack round, no scout needed


def test_attacking_kill_switch_disables_early_window(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, {"earlyRespyEnabled": False})
    now = int(time.time())
    ra = now + 60
    _targets(monkeypatch, [{
        "enabled": True, "state": "ATTACKING", "attack_return_at": ra,
        "respy_launched_at": 0, "raids_since_spy": 3, "respy_every": 3,
        "target_city_id": "1",
    }])
    assert fm.has_due_farm() is False


def test_next_farm_eta_pulls_in_for_early_respy(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, {})
    now = int(time.time())
    ra = now + 30 * 60
    _targets(monkeypatch, [{
        "enabled": True, "state": "ATTACKING", "attack_return_at": ra,
        "respy_launched_at": 0, "raids_since_spy": 3, "respy_every": 3,
        "target_city_id": "1",
    }])
    eta = fm.next_farm_eta()
    # wakes ~_EARLY_RESPY_LEAD before the return, not at the return itself
    assert abs(eta - (ra - fm._EARLY_RESPY_LEAD)) <= 1


def test_next_farm_eta_uses_return_once_respy_launched(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, {})
    now = int(time.time())
    ra = now + 30 * 60
    _targets(monkeypatch, [{
        "enabled": True, "state": "ATTACKING", "attack_return_at": ra,
        "respy_launched_at": now - 60, "raids_since_spy": 3, "respy_every": 3,
        "target_city_id": "1",
    }])
    assert fm.next_farm_eta() == ra   # already launched → wake at the dock time
