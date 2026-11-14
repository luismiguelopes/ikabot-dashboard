"""
P13.13: the work steps inside smart_sleep (farm, attacks, spies, transports) used to run in
`except Exception: pass` — a crashing pass left no log and no health record and was retried
every minute in silence. They now go through _run_step / _is_due.
"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("telegram_notifier", types.ModuleType("telegram_notifier"))

import empire_utils as eu
import queue_processor as qp


def _health(monkeypatch, tmp_path):
    path = tmp_path / "health.json"
    monkeypatch.setattr(eu, "HEALTH_JSON_PATH", str(path))
    monkeypatch.setattr(eu, "LOGS_DIR", str(tmp_path))
    return path


def test_failing_step_is_logged_and_counted(monkeypatch, tmp_path, caplog):
    path = _health(monkeypatch, tmp_path)

    def boom():
        raise RuntimeError("rebentou")
    with caplog.at_level("WARNING", logger="ikabot"):
        eu.logger.propagate = True
        try:
            assert qp._run_step("farm", boom) is False
        finally:
            eu.logger.propagate = False
    rec = json.loads(path.read_text())["farm"]
    assert rec["consecutiveFailures"] == 1 and "rebentou" in rec["lastError"]
    assert any("smart_sleep" in r.getMessage() for r in caplog.records)


def test_clean_step_resets_the_streak(monkeypatch, tmp_path):
    path = _health(monkeypatch, tmp_path)
    qp._run_step("farm", lambda: (_ for _ in ()).throw(ValueError("x")))
    assert qp._run_step("farm", lambda: None) is True
    assert json.loads(path.read_text())["farm"]["consecutiveFailures"] == 0


def test_fatal_exits_are_not_swallowed(monkeypatch, tmp_path):
    _health(monkeypatch, tmp_path)
    import pytest
    with pytest.raises(SystemExit):
        qp._run_step("farm", lambda: sys.exit(1))


def test_broken_due_check_means_no_work_but_is_reported(monkeypatch, caplog):
    monkeypatch.setattr(qp._is_due, "_logged", {})
    with caplog.at_level("WARNING", logger="ikabot"):
        eu.logger.propagate = True
        try:
            assert qp._is_due("farm", lambda: 1 / 0) is False
            assert qp._is_due("farm", lambda: 1 / 0) is False      # second one is throttled
        finally:
            eu.logger.propagate = False
    assert sum("verificação" in r.getMessage() for r in caplog.records) == 1
    assert qp._is_due("farm", lambda: True) is True


def test_smart_sleep_survives_a_crashing_farm_pass_and_sleeps(monkeypatch, tmp_path):
    """One loop iteration: the farm is due and blows up → recorded, and the loop goes on to
    its sleep instead of spinning (the old code hid the error; a naive fix would `continue`)."""
    path = _health(monkeypatch, tmp_path)
    monkeypatch.setattr(qp, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(qp, "_load_queue", lambda: {"queues": {}, "inProgress": {}, "enabled": True})
    monkeypatch.setattr(qp, "_get_next_spy_eta", lambda: None)
    monkeypatch.setattr(qp, "_in_scan_hours", lambda: True)
    monkeypatch.setattr(qp, "_in_active_hours", lambda: True)
    monkeypatch.setattr(eu, "is_paused", lambda: False)

    import attack_manager, espionage_manager, farm_manager, scan_collector, transport_manager
    monkeypatch.setattr(farm_manager, "next_farm_eta", lambda: None)
    monkeypatch.setattr(espionage_manager, "has_due_recalls", lambda: False)
    monkeypatch.setattr(espionage_manager, "has_pending_dispatch", lambda: False)
    monkeypatch.setattr(espionage_manager, "has_due_spy_steps", lambda: False)
    monkeypatch.setattr(espionage_manager, "FORCE_RECALL_UNUSED_FLAG", str(tmp_path / "nope"))
    monkeypatch.setattr(attack_manager, "has_due_attacks", lambda: False)
    monkeypatch.setattr(transport_manager, "has_due_transports", lambda: False)
    monkeypatch.setattr(scan_collector, "scan_has_pending", lambda: False)
    monkeypatch.setattr(farm_manager, "has_due_farm", lambda: True)
    calls = []

    def crashing_farm(session, in_active_hours=True):
        calls.append(1)
        raise RuntimeError("farm partiu")
    monkeypatch.setattr(farm_manager, "process_farm_targets", crashing_farm)
    for flag in ("FORCE_EMPIRE_FLAG", "FORCE_QUEUE_FLAG", "FORCE_MOVEMENTS_FLAG",
                 "FORCE_IMPORT_REPORTS_FLAG", "FORCE_MILITARY_FLAG", "FORCE_COSTS_FLAG",
                 "FORCE_WINE_BUY_FLAG"):
        monkeypatch.setattr(qp, flag, str(tmp_path / ("no_" + flag)))

    class _Slept(Exception):
        pass

    def fake_sleep(secs):
        raise _Slept()
    monkeypatch.setattr(qp.time, "sleep", fake_sleep)

    import pytest
    with pytest.raises(_Slept):
        qp.smart_sleep(qp.time.time(), 0, session=object())
    assert calls == [1]                                   # ran once, then reached the sleep
    assert "farm partiu" in json.loads(path.read_text())["farm"]["lastError"]
