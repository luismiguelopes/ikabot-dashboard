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


# ── process_recall_unused_flag: mass recall sweep of unused stationed spies ──────

def _sweep_setup(monkeypatch, tmp_path, missions, entries, farm_ids=frozenset()):
    """Wire the sweep's seams: flag file, own cities, safehouse fetch/parse, queues."""
    h = _patch(monkeypatch, missions)
    flag = tmp_path / ".force_recall_unused"
    flag.touch()
    monkeypatch.setattr(em, "FORCE_RECALL_UNUSED_FLAG", str(flag))
    own = tmp_path / "own.json"
    own.write_text('[{"cityId": "1", "name": "Home", "safehousePosition": 3}]')
    monkeypatch.setattr(em, "OWN_CITIES_PATH", str(own))
    monkeypatch.setattr(em, "_enabled_farm_target_ids", lambda: set(farm_ids))
    monkeypatch.setattr(em, "_fetch_city_spy_counts", lambda *a, **k: ({}, "<html>"))
    monkeypatch.setattr(em, "_parse_active_spy_missions", lambda html: entries)
    monkeypatch.setattr(em, "_recall_queue_items", lambda: [])
    queued = []
    monkeypatch.setattr(em, "_queue_recall", lambda item: queued.append(item) or True)
    return h, flag, queued


def test_sweep_recalls_only_unused(monkeypatch, tmp_path):
    """Stationed spies are recalled EXCEPT enabled farm targets, targets with a mission in
    progress, and spies still travelling; the swept DONE mission is marked RECALLED."""
    missions = [
        _mission(state="DONE", targetCityId="200", numAgents=2, spySessionId="S200"),
        _mission(state="EXECUTING_WAREHOUSE", targetCityId="400"),
    ]
    entries = [
        {"cityId": "200", "cityName": "Ocioso",   "state": "WAITING_AT_CITY"},
        {"cityId": "300", "cityName": "FarmAlvo", "state": "WAITING_AT_CITY"},
        {"cityId": "400", "cityName": "EmMissao", "state": "WAITING_AT_CITY"},
        {"cityId": "500", "cityName": "AViajar",  "state": "TRAVELING"},
    ]
    h, flag, queued = _sweep_setup(monkeypatch, tmp_path, missions, entries, farm_ids={"300"})

    em.process_recall_unused_flag(session=object())

    assert [q["targetCityId"] for q in queued] == ["200"]   # only the idle one
    assert queued[0]["numAgents"] == 2                       # enriched from the mission record
    assert queued[0]["spySessionId"] == "S200"
    assert h["missions"][0]["state"] == "RECALLED"
    assert h["missions"][1]["state"] == "EXECUTING_WAREHOUSE"   # untouched
    assert not flag.exists()                                 # single sweep per press


def test_sweep_staggers_batches(monkeypatch, tmp_path):
    """Recalls beyond the batch size get a future nextAttemptAfter — no request bursts."""
    n = em._RECALL_SWEEP_BATCH + 5
    entries = [{"cityId": str(1000 + i), "cityName": f"C{i}", "state": "WAITING_AT_CITY"}
               for i in range(n)]
    _, _, queued = _sweep_setup(monkeypatch, tmp_path, [], entries)

    em.process_recall_unused_flag(session=object())

    assert len(queued) == n
    first_batch  = queued[:em._RECALL_SWEEP_BATCH]
    second_batch = queued[em._RECALL_SWEEP_BATCH:]
    assert all(q["nextAttemptAfter"] == 0 for q in first_batch)          # goes out now
    now = _now()
    assert all(q["nextAttemptAfter"] >= now + em._RECALL_SWEEP_SPACING_SECS
               for q in second_batch)                                     # spaced window


def test_sweep_skips_targets_already_pending(monkeypatch, tmp_path):
    """A target already in the recall queue (e.g. double press) is not queued twice."""
    entries = [{"cityId": "200", "cityName": "Ocioso", "state": "WAITING_AT_CITY"}]
    _, _, queued = _sweep_setup(monkeypatch, tmp_path, [], entries)
    monkeypatch.setattr(em, "_recall_queue_items", lambda: [{"targetCityId": "200"}])

    em.process_recall_unused_flag(session=object())

    assert queued == []


def test_sweep_recalls_synthetic_waiting_spies(monkeypatch, tmp_path):
    """Synthetic WAITING_AT_CITY missions (safehouse sync of manually dispatched spies)
    are NOT 'in progress' — they are the idle spies the sweep exists to recall; the
    record is marked RECALLED so the pipeline won't fire a mission on a homebound spy.
    A REAL (pipeline-dispatched) WAITING_AT_CITY mission still counts as busy."""
    missions = [
        _mission(state="WAITING_AT_CITY", targetCityId="200", numAgents=3,
                 syntheticFromSafehouse=True),
        _mission(state="WAITING_AT_CITY", targetCityId="400"),   # real pipeline mission
    ]
    entries = [
        {"cityId": "200", "cityName": "Ocioso",   "state": "WAITING_AT_CITY", "numAgents": 3},
        {"cityId": "400", "cityName": "EmMissao", "state": "WAITING_AT_CITY", "numAgents": 1},
    ]
    h, _, queued = _sweep_setup(monkeypatch, tmp_path, missions, entries)

    em.process_recall_unused_flag(session=object())

    assert [q["targetCityId"] for q in queued] == ["200"]
    assert queued[0]["numAgents"] == 3
    assert h["missions"][0]["state"] == "RECALLED"
    assert h["missions"][1]["state"] == "WAITING_AT_CITY"   # real mission untouched


def test_sync_does_not_duplicate_known_stationed_spies(monkeypatch):
    """A stationed spy whose mission progressed past WAITING (EXECUTING/DONE) is already
    known — the safehouse sync must NOT create a duplicate synthetic entry for it (seen
    live: every counts refresh added one more synthetic, each firing a warehouse mission)."""
    h = _patch(monkeypatch, [
        _mission(state="EXECUTING_WAREHOUSE", targetCityId="200"),
        _mission(state="DONE", targetCityId="300"),
    ])
    em._sync_active_spy_missions(
        [{"cityId": "200", "x": 1, "y": 2, "cityName": "A", "state": "WAITING_AT_CITY"},
         {"cityId": "300", "x": 3, "y": 4, "cityName": "B", "state": "WAITING_AT_CITY"},
         {"cityId": "400", "x": 5, "y": 6, "cityName": "C", "state": "WAITING_AT_CITY"}],
        origin_city_id="1")
    states = [(m.get("targetCityId"), m.get("state")) for m in h["missions"]]
    assert len(h["missions"]) == 3                       # only the truly unknown 400 added
    assert ("400", "WAITING_AT_CITY") in states
    assert h["missions"][2].get("syntheticFromSafehouse") is True
