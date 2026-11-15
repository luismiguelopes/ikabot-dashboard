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


# ── P13.24: when a queue-only wake needs the building pass ───────────────────────
# The pass opens the city view of every city with queued items; it used to run on every wake
# of the main loop, even one for a farm or spy ETA.

import pytest


def _queue(in_progress=None, queues=None, enabled=True):
    return {"enabled": enabled,
            "queues": queues if queues is not None else
            {"Polis": [{"id": 1, "building": "Academy", "targetLevel": 20}]},
            "inProgress": in_progress or {}}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(qp, "_build_pass", {"at": 0, "sig": None})


def _passed(data, at):
    qp._build_pass.update(at=at, sig=qp._queue_signature(data))


def test_farm_wake_with_everything_building_skips_the_pass():
    q = _queue(in_progress={"Polis": {"building": "Academy", "eta": 5000}})
    _passed(q, at=1000)
    assert qp.building_pass_due("farm", q, now=1200) is False
    assert qp.building_pass_due("spy", q, now=4000) is False


def test_finished_construction_makes_it_due_once():
    q = _queue(in_progress={"Polis": {"building": "Academy", "eta": 5000}})
    _passed(q, at=1000)
    assert qp.building_pass_due("farm", q, now=5001) is True
    _passed(q, at=5002)                      # the pass ran; the same old ETA is not due again
    assert qp.building_pass_due("farm", q, now=5100) is False


def test_dashboard_edit_and_first_run_are_due():
    q = _queue(in_progress={"Polis": {"building": "Academy", "eta": 5000}})
    assert qp.building_pass_due("farm", q, now=1200) is True          # never ran yet
    _passed(q, at=1000)
    q["queues"]["Polis"].append({"id": 2, "building": "Tavern", "targetLevel": 9})
    assert qp.building_pass_due("farm", q, now=1200) is True


def test_forced_and_transport_wakes_are_due():
    q = _queue(in_progress={"Polis": {"building": "Academy", "eta": 5000}})
    _passed(q, at=1000)
    for reason in ("force_queue", "transport", "construction"):
        assert qp.building_pass_due(reason, q, now=1001) is True


def test_city_waiting_for_resources_is_retried_on_a_cadence():
    q = _queue()                             # queued, nothing under construction
    _passed(q, at=1000)
    assert qp.building_pass_due("farm", q, now=1000 + qp._BUILD_RETRY_SECS - 1) is False
    assert qp.building_pass_due("farm", q, now=1000 + qp._BUILD_RETRY_SECS) is True


def test_empty_or_disabled_queue_is_never_due():
    assert qp.building_pass_due("force_queue", _queue(queues={}), now=10) is False
    assert qp.building_pass_due("force_queue", _queue(enabled=False), now=10) is False


def test_pass_that_raises_is_still_noted(monkeypatch):
    q = _queue()
    monkeypatch.setattr(qp, "_load_queue", lambda: q)

    def boom(*a):
        raise RuntimeError("x")
    monkeypatch.setattr(qp, "process_building_queue", boom)
    with pytest.raises(RuntimeError):
        qp.run_building_pass(None, [], {})
    assert qp._build_pass["at"] > 0 and qp._build_pass["sig"] == qp._queue_signature(q)
    assert qp.building_pass_due("farm", q) is False       # not retried on the very next wake


def _quiet_sleep(monkeypatch, tmp_path, queue, farm_eta=None):
    """smart_sleep with nothing due and every flag absent; the first real sleep ends the test."""
    monkeypatch.setattr(qp, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(qp, "_load_queue", lambda: queue)
    monkeypatch.setattr(qp, "_get_next_spy_eta", lambda: None)
    monkeypatch.setattr(qp, "_in_scan_hours", lambda: False)
    monkeypatch.setattr(qp, "_in_active_hours", lambda: True)
    monkeypatch.setattr(qp, "_build_pass", {"at": qp.time.time(), "sig": None})
    import farm_manager
    monkeypatch.setattr(farm_manager, "next_farm_eta", lambda: farm_eta)
    for flag in ("FORCE_EMPIRE_FLAG", "FORCE_QUEUE_FLAG", "FORCE_MOVEMENTS_FLAG",
                 "FORCE_IMPORT_REPORTS_FLAG", "FORCE_MILITARY_FLAG", "FORCE_COSTS_FLAG",
                 "FORCE_WINE_BUY_FLAG"):
        monkeypatch.setattr(qp, flag, str(tmp_path / ("no_" + flag)))
    slept = []
    clock = {"t": qp.time.time()}
    monkeypatch.setattr(qp.time, "time", lambda: clock["t"])

    def fake_sleep(secs):
        slept.append(secs)
        clock["t"] += secs
    monkeypatch.setattr(qp.time, "sleep", fake_sleep)
    return slept, clock


def test_smart_sleep_reports_why_it_woke(monkeypatch, tmp_path):
    """P13.24: the main loop needs the reason to skip the building pass on a farm/spy wake."""
    q = {"queues": {}, "inProgress": {}, "enabled": True}
    slept, clock = _quiet_sleep(monkeypatch, tmp_path, q, farm_eta=None)
    assert qp.smart_sleep(clock["t"], 0, session=None) == "full"

    slept, clock = _quiet_sleep(monkeypatch, tmp_path, q)
    import farm_manager
    monkeypatch.setattr(farm_manager, "next_farm_eta", lambda: clock["t"] + 300)
    start = clock["t"]
    assert qp.smart_sleep(start, 0, session=None) == "farm"
    assert 300 <= clock["t"] - start <= 300 + 70 + 60

    q2 = {"queues": {"Polis": [{"id": 1, "building": "Academy", "targetLevel": 9}]},
          "inProgress": {"Polis": {"building": "Academy", "eta": 0}}, "enabled": True}
    slept, clock = _quiet_sleep(monkeypatch, tmp_path, q2)
    q2["inProgress"]["Polis"]["eta"] = clock["t"] + 120
    monkeypatch.setattr(farm_manager, "next_farm_eta", lambda: clock["t"] + 900)
    assert qp.smart_sleep(clock["t"], 0, session=None) == "construction"


def test_smart_sleep_retries_waiting_cities_and_force_flag(monkeypatch, tmp_path):
    q = {"queues": {"Polis": [{"id": 1, "building": "Academy", "targetLevel": 9}]},
         "inProgress": {}, "enabled": True}
    slept, clock = _quiet_sleep(monkeypatch, tmp_path, q)
    start = clock["t"]
    assert qp.smart_sleep(start, 0, session=None) == "retry"
    assert abs((clock["t"] - start) - qp._BUILD_RETRY_SECS) <= 60

    slept, clock = _quiet_sleep(monkeypatch, tmp_path, q)
    flag = tmp_path / "force_queue"
    flag.write_text("")
    monkeypatch.setattr(qp, "FORCE_QUEUE_FLAG", str(flag))
    assert qp.smart_sleep(clock["t"], 0, session=None) == "force_queue"
    assert not flag.exists()
