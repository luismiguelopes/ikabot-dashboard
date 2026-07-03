"""
Behavioural (characterisation) tests for the spy mission state machine in
espionage_manager. These pin the CURRENT transitions so the planned split can be done
safely — they test orchestration (state transitions), not HTML parsing (covered by
test_espionage_parsers.py), by stubbing the I/O helpers at their seams.

State machine:
  TRAVELING → WAITING_AT_CITY → EXECUTING_WAREHOUSE → (WAITING_FOR_GARRISON →
  EXECUTING_GARRISON →) DONE      (FAILED on detection/timeout)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import espionage_manager as em


def _patch(monkeypatch, missions):
    """In-memory mission store + no real sleeps + a safehouse position for every city."""
    holder = {"missions": missions}
    monkeypatch.setattr(em, "_load_missions", lambda: holder)
    monkeypatch.setattr(em, "_save_missions", lambda d: holder.update(d))
    monkeypatch.setattr(em.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(em, "_get_city_safehouse_position", lambda cid: 3)
    monkeypatch.setattr(em, "_is_farm_target", lambda cid: False)  # no real DB access
    return holder


def _mission(**kw):
    m = {"originCityId": "1", "targetCityId": "100", "targetCityName": "Alvo",
         "targetPlayerName": "Inimigo", "islandX": 40, "islandY": 50,
         "numAgents": 1, "safehousePosition": 3, "spySessionId": "SID"}
    m.update(kw)
    return m


def _now():
    return int(em.time.time())


# ── check_spy_arrivals: TRAVELING → WAITING_AT_CITY / FAILED ────────────────────

def test_arrival_waits_until_eta(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="TRAVELING", executeAfter=_now() + 9999)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("não devia consultar")))
    em.check_spy_arrivals(session=object())
    assert h["missions"][0]["state"] == "TRAVELING"   # not yet near ETA → no fetch


def test_arrival_promotes_to_waiting(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="TRAVELING", dispatchedAt=_now() - 2000)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (1, "<html>"))
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "NEWSID")
    em.check_spy_arrivals(session=object())
    m = h["missions"][0]
    assert m["state"] == "WAITING_AT_CITY"
    assert m["spySessionId"] == "NEWSID"
    assert m["executeAfter"] > _now()


def test_arrival_fails_after_12h(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="TRAVELING", dispatchedAt=_now() - 50000)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (0, ""))
    em.check_spy_arrivals(session=object())
    assert h["missions"][0]["state"] == "FAILED"


# ── execute_waiting_missions: WAITING_AT_CITY → EXECUTING_WAREHOUSE / FAILED ─────

def test_execute_warehouse_success(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="WAITING_AT_CITY", executeAfter=_now() - 10)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (1, "<html>"))
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "SID")
    monkeypatch.setattr(em, "_execute_spy_mission", lambda *a, **k: True)
    em.execute_waiting_missions(session=object())
    m = h["missions"][0]
    assert m["state"] == "EXECUTING_WAREHOUSE"
    assert m["missionType"] == "warehouse"
    assert m["collectAfter"] > 0


def test_execute_waiting_before_eta_noop(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="WAITING_AT_CITY", executeAfter=_now() + 9999)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("cedo demais")))
    em.execute_waiting_missions(session=object())
    assert h["missions"][0]["state"] == "WAITING_AT_CITY"


def test_execute_spy_gone_fails(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="WAITING_AT_CITY", executeAfter=_now() - 10)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (0, ""))
    em.execute_waiting_missions(session=object())
    assert h["missions"][0]["state"] == "FAILED"


def test_execute_rejected_fails(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="WAITING_AT_CITY", executeAfter=_now() - 10)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (1, "<html>"))
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "SID")
    monkeypatch.setattr(em, "_execute_spy_mission", lambda *a, **k: False)
    em.execute_waiting_missions(session=object())
    assert h["missions"][0]["state"] == "FAILED"


# ── collect_mission_results: EXECUTING_WAREHOUSE → WAITING_FOR_GARRISON/DONE/FAILED

def _warehouse_report(loot, success=True):
    return {"1": {"resources": {"wood": loot}, "success": success,
                   "targetCityId": "100", "targetCityName": "Alvo"}}


def test_collect_high_loot_goes_to_garrison(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="EXECUTING_WAREHOUSE", collectAfter=_now() - 1,
                                      needGarrison=True)])
    monkeypatch.setattr(em, "_load_espionage_settings", lambda: {"garrisonThresholdTotal": 50000})
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k: _warehouse_report(90000))
    em.collect_mission_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "WAITING_FOR_GARRISON"
    assert m["result"]["resources"] == {"wood": 90000}


def test_collect_warehouse_only_goes_done(monkeypatch):
    """needGarrison=False (safe farm target): high loot ends DONE without a garrison step."""
    h = _patch(monkeypatch, [_mission(state="EXECUTING_WAREHOUSE", collectAfter=_now() - 1,
                                      needGarrison=False)])
    monkeypatch.setattr(em, "_load_espionage_settings", lambda: {"garrisonThresholdTotal": 50000})
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k: _warehouse_report(90000))
    em.collect_mission_results(session=object())
    assert h["missions"][0]["state"] == "DONE"


def test_collect_low_loot_done_and_recalls(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="EXECUTING_WAREHOUSE", collectAfter=_now() - 1,
                                      needGarrison=True)])
    monkeypatch.setattr(em, "_load_espionage_settings", lambda: {"garrisonThresholdTotal": 50000})
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k: _warehouse_report(1000))
    recalls = []
    monkeypatch.setattr(em, "_queue_recall", lambda item: recalls.append(item))
    monkeypatch.setattr(em, "_auto_mark_ignored", lambda *a, **k: None)
    em.collect_mission_results(session=object())
    assert h["missions"][0]["state"] == "DONE"
    assert len(recalls) == 1                       # spy recalled before ignoring


def test_collect_midband_loot_closed_and_ignored(monkeypatch):
    """Non-farm target between garrisonThresholdTotal and minLootTotal: not worth a garrison
    mission — closed as DONE, spy recalled, target auto-hidden from the inactives list."""
    h = _patch(monkeypatch, [_mission(state="EXECUTING_WAREHOUSE", collectAfter=_now() - 1,
                                      needGarrison=True)])
    monkeypatch.setattr(em, "_load_espionage_settings",
                        lambda: {"garrisonThresholdTotal": 10000, "minLootTotal": 50000})
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k: _warehouse_report(30000))
    recalls, ignored = [], []
    monkeypatch.setattr(em, "_queue_recall", lambda item: recalls.append(item))
    monkeypatch.setattr(em, "_auto_mark_ignored", lambda *a, **k: ignored.append(a))
    em.collect_mission_results(session=object())
    assert h["missions"][0]["state"] == "DONE"
    assert len(recalls) == 1 and len(ignored) == 1


def test_collect_midband_farm_target_still_gets_garrison(monkeypatch):
    """Farm targets are exempt from the minLootTotal bar (the farm runs its own per-target
    min_loot) — a mid-band report still proceeds to the garrison step."""
    h = _patch(monkeypatch, [_mission(state="EXECUTING_WAREHOUSE", collectAfter=_now() - 1,
                                      needGarrison=True)])
    monkeypatch.setattr(em, "_is_farm_target", lambda cid: True)
    monkeypatch.setattr(em, "_load_espionage_settings",
                        lambda: {"garrisonThresholdTotal": 10000, "minLootTotal": 50000})
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k: _warehouse_report(30000))
    em.collect_mission_results(session=object())
    assert h["missions"][0]["state"] == "WAITING_FOR_GARRISON"


def test_collect_failed_report(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="EXECUTING_WAREHOUSE", collectAfter=_now() - 1)])
    monkeypatch.setattr(em, "_load_espionage_settings", lambda: {"garrisonThresholdTotal": 50000})
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k: _warehouse_report(90000, success=False))
    em.collect_mission_results(session=object())
    assert h["missions"][0]["state"] == "FAILED"


def test_collect_missing_report_times_out(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="EXECUTING_WAREHOUSE", collectAfter=_now() - 1,
                                      executedAt=_now() - 8000)])
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k: {"1": {"resources": {},
                        "targetCityId": "999"}})  # no matching report
    em.collect_mission_results(session=object())
    assert h["missions"][0]["state"] == "FAILED"


# ── execute_garrison_missions: WAITING_FOR_GARRISON → EXECUTING_GARRISON / DONE ──

def test_garrison_executes(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="WAITING_FOR_GARRISON", garrisonExecuteAfter=_now() - 1)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (1, "<html>"))
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "SID")
    monkeypatch.setattr(em, "_execute_spy_mission", lambda *a, **k: True)
    em.execute_garrison_missions(session=object())
    assert h["missions"][0]["state"] == "EXECUTING_GARRISON"


def test_garrison_spy_gone_keeps_warehouse(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="WAITING_FOR_GARRISON", garrisonExecuteAfter=_now() - 1)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (0, ""))
    em.execute_garrison_missions(session=object())
    assert h["missions"][0]["state"] == "DONE"        # warehouse result kept


def test_garrison_rejected_done_with_warehouse(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="WAITING_FOR_GARRISON", garrisonExecuteAfter=_now() - 1)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (1, "<html>"))
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "SID")
    monkeypatch.setattr(em, "_execute_spy_mission", lambda *a, **k: False)
    em.execute_garrison_missions(session=object())
    m = h["missions"][0]
    assert m["state"] == "DONE"
    assert m["garrisonResult"]["error"]


# ── collect_garrison_results: EXECUTING_GARRISON → DONE ──────────────────────────

def test_collect_garrison_done(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="EXECUTING_GARRISON", garrisonCollectAfter=_now() - 1)])
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k:
                        {"1": {"troops": {"s303": 12}, "targetCityId": "100", "targetCityName": "Alvo"}})
    em.collect_garrison_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "DONE"
    assert m["garrisonResult"]["troops"] == {"s303": 12}


def test_collect_garrison_empty_is_done(monkeypatch):
    """An empty garrison ({}) is a valid result (no troops) — distinct from None (not a report)."""
    h = _patch(monkeypatch, [_mission(state="EXECUTING_GARRISON", garrisonCollectAfter=_now() - 1)])
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k:
                        {"1": {"troops": {}, "targetCityId": "100", "targetCityName": "Alvo"}})
    em.collect_garrison_results(session=object())
    assert h["missions"][0]["state"] == "DONE"
    assert h["missions"][0]["garrisonResult"]["troops"] == {}


def test_collect_garrison_times_out(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="EXECUTING_GARRISON", garrisonCollectAfter=_now() - 1,
                                      garrisonExecutedAt=_now() - 8000)])
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k:
                        {"1": {"troops": None}})  # warehouse report, not garrison
    em.collect_garrison_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "DONE"
    assert "não encontrado" in m["garrisonResult"]["error"]


# ── process_spy_cycle: resilience (one failing step doesn't stop the rest) ───────

def test_cycle_isolates_step_failures(monkeypatch):
    _patch(monkeypatch, [])
    calls = []
    monkeypatch.setattr(em, "_process_recall_queue", lambda s: calls.append("recall"))
    def _boom(s):
        calls.append("arrivals")
        raise RuntimeError("falha simulada")
    monkeypatch.setattr(em, "check_spy_arrivals", _boom)
    monkeypatch.setattr(em, "execute_waiting_missions", lambda s: calls.append("waiting"))
    monkeypatch.setattr(em, "collect_mission_results", lambda s: calls.append("collect"))
    monkeypatch.setattr(em, "execute_garrison_missions", lambda s: calls.append("garrison_exec"))
    monkeypatch.setattr(em, "collect_garrison_results", lambda s: calls.append("garrison_collect"))
    em.process_spy_cycle(session=object())
    # the failing step ran and raised, but every later step still ran
    assert calls == ["recall", "arrivals", "waiting", "collect", "garrison_exec", "garrison_collect"]
