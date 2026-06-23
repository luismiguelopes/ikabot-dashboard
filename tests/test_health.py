"""
Tests for the subsystem health monitor (P5.2): failure streaks, threshold alert (once),
recovery alert, and the health_guard context manager.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import empire_utils as eu


def _fake_tg(monkeypatch):
    """Inject a fake telegram_notifier so the lazy imports inside record_* resolve to it."""
    calls = {"down": [], "rec": []}
    fake = types.ModuleType("telegram_notifier")
    fake.notify_subsystem_down = lambda *a: calls["down"].append(a)
    fake.notify_subsystem_recovered = lambda *a: calls["rec"].append(a)
    monkeypatch.setitem(sys.modules, "telegram_notifier", fake)
    return calls


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(eu, "HEALTH_JSON_PATH", str(tmp_path / "health.json"))


def test_failure_streak_alerts_once_at_threshold(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    calls = _fake_tg(monkeypatch)
    for _ in range(2):
        eu.record_failure("espionage", "boom")
    assert calls["down"] == []                       # below threshold (3) → no alert
    eu.record_failure("espionage", "boom")           # 3rd → alert
    assert len(calls["down"]) == 1
    eu.record_failure("espionage", "boom")           # 4th → still just one alert
    assert len(calls["down"]) == 1
    rec = eu._load_health()["espionage"]
    assert rec["consecutiveFailures"] == 4
    assert rec["totalFailures"] == 4
    assert rec["alerted"] is True


def test_success_resets_and_sends_recovery(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    calls = _fake_tg(monkeypatch)
    for _ in range(3):
        eu.record_failure("attack", "boom")          # trips the alert
    assert len(calls["down"]) == 1
    eu.record_success("attack")
    assert len(calls["rec"]) == 1                     # recovery alert
    rec = eu._load_health()["attack"]
    assert rec["consecutiveFailures"] == 0
    assert rec["alerted"] is False
    assert rec["lastError"] is None


def test_success_without_prior_alert_is_quiet(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    calls = _fake_tg(monkeypatch)
    eu.record_failure("farm", "boom")                # one failure, no alert yet
    eu.record_success("farm")
    assert calls["rec"] == []                         # nothing to recover from → no spam


def test_health_guard_records_success(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _fake_tg(monkeypatch)
    with eu.health_guard("scan"):
        pass
    assert eu._load_health()["scan"]["consecutiveFailures"] == 0
    assert eu._load_health()["scan"]["lastSuccessAt"] > 0


def test_health_guard_swallows_and_records(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _fake_tg(monkeypatch)
    with eu.health_guard("transport"):               # must NOT raise
        raise ValueError("kaput")
    assert eu._load_health()["transport"]["consecutiveFailures"] == 1


def test_health_guard_noswallow_reraises(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _fake_tg(monkeypatch)
    import pytest
    with pytest.raises(ValueError):
        with eu.health_guard("empire", swallow=False):
            raise ValueError("kaput")
    assert eu._load_health()["empire"]["consecutiveFailures"] == 1


def test_health_guard_lets_systemexit_through(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _fake_tg(monkeypatch)
    import pytest
    with pytest.raises(SystemExit):
        with eu.health_guard("espionage"):
            raise SystemExit("fatal")
    # fatal errors are not recorded as a subsystem failure (handled by the main loop)
    assert "espionage" not in eu._load_health()
