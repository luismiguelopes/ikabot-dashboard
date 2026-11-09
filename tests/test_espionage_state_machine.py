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


def test_arrival_fails_after_3h(monkeypatch):
    """A spy not found at the target after 3h of active time was caught/lost: fail it so the
    farm target is released instead of staying stuck in SPYING for the old 12h."""
    h = _patch(monkeypatch, [_mission(state="TRAVELING", dispatchedAt=_now() - 3 * 3600 - 60)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (0, ""))
    em.check_spy_arrivals(session=object())
    assert h["missions"][0]["state"] == "FAILED"
    assert "3h" in h["missions"][0]["error"]


def test_arrival_keeps_waiting_before_3h(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="TRAVELING", dispatchedAt=_now() - 2 * 3600)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (0, ""))
    em.check_spy_arrivals(session=object())
    assert h["missions"][0]["state"] == "TRAVELING"


def test_arrival_timeout_discounts_downtime(monkeypatch):
    """Time the bot spent offline does not count toward the 3h (B7)."""
    now = _now()
    h = _patch(monkeypatch, [_mission(state="TRAVELING", dispatchedAt=now - 5 * 3600)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (0, ""))
    monkeypatch.setattr(em, "active_elapsed", lambda since, n=None: 2 * 3600)   # 3h of the 5h offline
    em.check_spy_arrivals(session=object())
    assert h["missions"][0]["state"] == "TRAVELING"


# ── execute_waiting_missions: WAITING_AT_CITY → EXECUTING_WAREHOUSE / FAILED ─────

def test_execute_warehouse_success(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="WAITING_AT_CITY", executeAfter=_now() - 10)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (1, "<html>"))
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "SID")
    monkeypatch.setattr(em, "_execute_spy_mission", lambda *a, **k: (True, "ok"))
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


def test_execute_rejected_retries_then_fails(monkeypatch):
    """A transient executeMission rejection on a confirmed-stationed spy (spy_count>0)
    must NOT discard it on the first failure: it bounces back to WAITING_AT_CITY for a
    retry, and only gives up to FAILED after _WAREHOUSE_MAX_RETRIES attempts."""
    h = _patch(monkeypatch, [_mission(state="WAITING_AT_CITY", executeAfter=_now() - 10)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (1, "<html>"))
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "SID")
    monkeypatch.setattr(em, "_execute_spy_mission", lambda *a, **k: (False, "rejected"))

    # First rejection: the spy is kept, mission re-armed for a retry (not FAILED).
    em.execute_waiting_missions(session=object())
    assert h["missions"][0]["state"] == "WAITING_AT_CITY"
    assert h["missions"][0]["warehouseRetries"] == 1

    # Keep rejecting until the retry budget is exhausted → FAILED.
    for _ in range(em._WAREHOUSE_MAX_RETRIES):
        h["missions"][0]["executeAfter"] = _now() - 10  # make it due again
        em.execute_waiting_missions(session=object())
    assert h["missions"][0]["state"] == "FAILED"
    assert h["missions"][0]["warehouseRetries"] >= em._WAREHOUSE_MAX_RETRIES


def test_execute_no_feedback_fails_fast(monkeypatch):
    """When the server only re-renders the tab with no feedback at all, the mission did not
    run and retrying the identical call doesn't help — so it fails immediately (no retry
    cycle), without stranding the spy (spy stays stationed, mission stays reusable)."""
    h = _patch(monkeypatch, [_mission(state="WAITING_AT_CITY", executeAfter=_now() - 10)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (1, "<html>"))
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "SID")
    monkeypatch.setattr(em, "_execute_spy_mission", lambda *a, **k: (False, "no_feedback"))
    em.execute_waiting_missions(session=object())
    m = h["missions"][0]
    assert m["state"] == "FAILED"           # no retry loop for a pure re-render
    assert m["warehouseRetries"] == 0


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
    monkeypatch.setattr(em, "_execute_spy_mission", lambda *a, **k: (True, "ok"))
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
    monkeypatch.setattr(em, "_execute_spy_mission", lambda *a, **k: (False, "rejected"))
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


# ── Movements leg (fleet targets): garrison → WAITING_FOR_MOVEMENTS → DONE ───────

def test_collect_garrison_chains_movements_for_fleet_target(monkeypatch):
    """A fleet target (needMovements) does NOT finish on the garrison — it chains a
    spy-on-movements leg to read the enemy fleet's real return ETA."""
    h = _patch(monkeypatch, [_mission(state="EXECUTING_GARRISON", garrisonCollectAfter=_now() - 1,
                                      needMovements=True)])
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k:
                        {"1": {"troops": {"s216": 1}, "targetCityId": "100", "targetCityName": "Alvo"}})
    em.collect_garrison_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "WAITING_FOR_MOVEMENTS"
    assert m["garrisonResult"]["troops"] == {"s216": 1}
    assert m["movementsExecuteAfter"] >= _now()


def test_collect_garrison_without_movements_flag_is_done(monkeypatch):
    """No needMovements → the garrison still finishes the mission (unchanged behaviour)."""
    h = _patch(monkeypatch, [_mission(state="EXECUTING_GARRISON", garrisonCollectAfter=_now() - 1)])
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k:
                        {"1": {"troops": {"s216": 1}, "targetCityId": "100", "targetCityName": "Alvo"}})
    em.collect_garrison_results(session=object())
    assert h["missions"][0]["state"] == "DONE"


def test_execute_movements_runs(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="WAITING_FOR_MOVEMENTS", movementsExecuteAfter=_now() - 1)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (1, "<html>"))
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "SID")
    monkeypatch.setattr(em, "_execute_spy_mission", lambda *a, **k: (True, "ok"))
    em.execute_movements_missions(session=object())
    assert h["missions"][0]["state"] == "EXECUTING_MOVEMENTS"


def test_execute_movements_spy_gone_is_done(monkeypatch):
    """Spy left before the movements scout → finish on the garrison result (no ETA)."""
    h = _patch(monkeypatch, [_mission(state="WAITING_FOR_MOVEMENTS", movementsExecuteAfter=_now() - 1)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (0, ""))
    em.execute_movements_missions(session=object())
    assert h["missions"][0]["state"] == "DONE"


def test_collect_movements_sets_enemy_return_eta(monkeypatch):
    eta = _now() + 2 * 3600
    h = _patch(monkeypatch, [_mission(state="EXECUTING_MOVEMENTS", movementsCollectAfter=_now() - 1)])
    monkeypatch.setattr(em, "_fetch_reports_html", lambda *a, **k: "<movements/>")
    monkeypatch.setattr(em, "_enemy_return_from_movements", lambda html, name, now=None: eta)
    em.collect_movements_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "DONE"
    assert m["movementsResult"] == {"enemyReturnAt": eta}


def test_collect_movements_clean_port_is_done_without_eta(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="EXECUTING_MOVEMENTS", movementsCollectAfter=_now() - 1)])
    monkeypatch.setattr(em, "_fetch_reports_html", lambda *a, **k: "<movements/>")
    monkeypatch.setattr(em, "_enemy_return_from_movements", lambda html, name, now=None: None)
    em.collect_movements_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "DONE"
    assert m["movementsResult"] == {"enemyReturnAt": None}


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
    monkeypatch.setattr(em, "execute_movements_missions", lambda s: calls.append("movements_exec"))
    monkeypatch.setattr(em, "collect_movements_results", lambda s: calls.append("movements_collect"))
    em.process_spy_cycle(session=object())
    # the failing step ran and raised, but every later step still ran
    assert calls == ["recall", "arrivals", "waiting", "collect", "garrison_exec",
                     "garrison_collect", "movements_exec", "movements_collect"]


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
    assert queued[0]["spySessionId"] is None   # read live from the safehouse at send time
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
    monkeypatch.setattr(em, "_recall_queue_items",
                        lambda: [{"targetCityId": "200", "originCityId": "1"}])

    em.process_recall_unused_flag(session=object())

    assert queued == []


def test_sweep_recalls_every_origin_pool_of_a_target(monkeypatch, tmp_path):
    """Spies from two own cities sit at the same target: both pools come home in one press
    (the recall is per origin; keying 'pending' by target alone left the second abroad)."""
    entries = [{"cityId": "200", "cityName": "Ocioso", "state": "WAITING_AT_CITY"}]
    _, _, queued = _sweep_setup(monkeypatch, tmp_path, [], entries)
    own = tmp_path / "own.json"
    own.write_text('[{"cityId": "1", "name": "A", "safehousePosition": 3},'
                   ' {"cityId": "2", "name": "B", "safehousePosition": 4}]')
    em.process_recall_unused_flag(session=object())
    assert sorted(q["originCityId"] for q in queued) == ["1", "2"]


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


# ── reexecute_stationed_spy: reuse a parked spy instead of sending a fresh one ────

def test_reexecute_rearms_a_failed_mission(monkeypatch):
    """A FAILED mission whose spy may still be stationed (real origin + safehouse) is
    re-armed to WAITING_AT_CITY so the next cycle re-checks the safehouse, instead of
    being treated as 'no spy there' and forcing a fresh dispatch."""
    h = _patch(monkeypatch, [_mission(state="FAILED", targetCityId="100",
                                       error="executeMission rejeitado pelo servidor",
                                       result={"success": True}, warehouseRetries=3)])
    assert em.reexecute_stationed_spy("100") is True
    m = h["missions"][0]
    assert m["state"] == "WAITING_AT_CITY"
    assert m["warehouseRetries"] == 0
    assert m["result"] is None and m["error"] is None


def test_reexecute_skips_imported_mission_without_origin(monkeypatch):
    """A synthetic/imported FAILED mission has no real stationed spy — reuse is impossible,
    so the caller must fall through to a fresh dispatch (returns False)."""
    h = _patch(monkeypatch, [_mission(state="FAILED", targetCityId="100", originCityId=None)])
    assert em.reexecute_stationed_spy("100") is False
    assert h["missions"][0]["state"] == "FAILED"


def test_reexecute_waits_when_another_mission_for_target_is_active(monkeypatch):
    """A target can carry several mission objects on one stationed spy. If ANY of them is
    still in flight, re-arming a different DONE/FAILED one would run a concurrent
    executeMission on the one spy, which the game rejects (type=11, seen live on Jardim De
    Cima). The parked mission that appears FIRST in the list must NOT be re-armed while a
    later mission for the same target is still active — reexecute returns True and waits."""
    parked = _mission(state="DONE", targetCityId="100", missionType="warehouse")
    active = _mission(state="EXECUTING_GARRISON", targetCityId="100")
    h = _patch(monkeypatch, [parked, active])          # parked comes first in the list
    assert em.reexecute_stationed_spy("100", need_movements=True) is True
    # The parked mission is left untouched — nothing was re-armed.
    assert h["missions"][0]["state"] == "DONE"
    assert h["missions"][1]["state"] == "EXECUTING_GARRISON"


def test_reexecute_prefers_newest_pool_over_older_ghost(monkeypatch):
    """Tróia 3 (09/11): an old mission listed first in the file must not be re-armed ahead of
    the previous evening's full sweep from another origin — the newest live pool wins."""
    old = _mission(state="DONE", originCityId="1", dispatchedAt=1000)
    new = _mission(state="DONE", originCityId="2", dispatchedAt=5000)
    h = _patch(monkeypatch, [old, new])
    assert em.reexecute_stationed_spy("100") is True
    assert h["missions"][0]["state"] == "DONE"
    assert h["missions"][1]["state"] == "WAITING_AT_CITY"


def test_reexecute_skips_origin_whose_newest_mission_lost_the_spies(monkeypatch):
    """Missions from one origin share one spy pool: a later capture supersedes an older DONE."""
    done_old = _mission(state="DONE", originCityId="1", dispatchedAt=1000)
    caught = _mission(state="FAILED", originCityId="1", dispatchedAt=2000,
                      error="Espião não encontrado ao tentar executar — possivelmente detectado")
    h = _patch(monkeypatch, [done_old, caught])
    assert em.reexecute_stationed_spy("100") is False      # → caller dispatches fresh spies
    assert [m["state"] for m in h["missions"]] == ["DONE", "FAILED"]


def test_reexecute_never_rearms_a_refused_dispatch(monkeypatch):
    """A refused sendSpy never left home — there is no stationed spy to reuse."""
    h = _patch(monkeypatch, [_mission(state="FAILED", dispatchedAt=1000,
                                      error="Servidor rejeitou o dispatch (tipos [11]): x")])
    assert em.reexecute_stationed_spy("100") is False
    assert h["missions"][0]["state"] == "FAILED"


def test_reexecute_still_rearms_missing_report(monkeypatch):
    """A missing report is NOT a capture — the spy may still sit in the safehouse."""
    h = _patch(monkeypatch, [_mission(state="FAILED", dispatchedAt=1000,
                                      error="Relatório não encontrado após 2h")])
    assert em.reexecute_stationed_spy("100") is True
    assert h["missions"][0]["state"] == "WAITING_AT_CITY"


# ── Mission retention: _save_missions prunes old terminal history ───────────────

def test_save_prunes_old_terminal_missions(monkeypatch, tmp_path):
    """_save_missions drops terminal missions older than the retention window but keeps
    in-flight ones, recent terminals, and timestamp-less entries regardless of age."""
    monkeypatch.setattr(em, "SPY_MISSIONS_PATH", str(tmp_path / "m.json"))
    monkeypatch.setattr(em, "_load_espionage_settings", lambda: {"missionRetentionDays": 30})
    now = _now()
    old = now - 40 * 86400
    recent = now - 2 * 86400
    em._save_missions({"missions": [
        _mission(state="DONE", targetCityName="VelhoDone", dispatchedAt=old),
        _mission(state="FAILED", targetCityName="VelhoFailed", executedAt=old),
        _mission(state="RECALLED", targetCityName="VelhoRecalled", arrivedAt=old),
        _mission(state="DONE", targetCityName="RecenteDone", executedAt=recent),
        _mission(state="WAITING_AT_CITY", targetCityName="VivoAntigo", dispatchedAt=old),
        _mission(state="DONE", targetCityName="SemData"),  # no timestamp → kept
    ]})
    names = {m["targetCityName"] for m in em._load_missions()["missions"]}
    assert names == {"RecenteDone", "VivoAntigo", "SemData"}


# ── Live-state coverage & mid-sleep wake-up (Castle, 06/11) ────────────────────

_ALL_NON_TERMINAL = ("TRAVELING", "WAITING_AT_CITY", "EXECUTING", "EXECUTING_WAREHOUSE",
                     "WAITING_FOR_GARRISON", "EXECUTING_GARRISON",
                     "WAITING_FOR_MOVEMENTS", "EXECUTING_MOVEMENTS")


def test_every_in_flight_state_counts_as_live(monkeypatch):
    """A mission mid-sweep must read as live. The movements states were missing, so the farm
    saw a spy between garrison and movements as 'never launched' and restarted the target."""
    for state in _ALL_NON_TERMINAL:
        _patch(monkeypatch, [_mission(state=state, dispatchedAt=_now())])
        assert em.has_live_mission("100", _now() - 60), state


def test_terminal_states_are_not_live(monkeypatch):
    for state in ("DONE", "FAILED", "RECALLED"):
        _patch(monkeypatch, [_mission(state=state, dispatchedAt=_now())])
        assert not em.has_live_mission("100", _now() - 60), state


def test_live_states_cover_every_mission_state_the_machine_writes():
    """Guard against the same omission recurring: every state the machine assigns, other
    than the terminal ones, must be in _LIVE_MISSION_STATES."""
    import re
    src = open(em.__file__, encoding="utf-8").read()
    written = set(re.findall(r'\["state"\]\s*=\s*"([A-Z_]+)"', src))
    terminal = {"DONE", "FAILED", "RECALLED"}
    missing = (written - terminal) - set(em._LIVE_MISSION_STATES)
    assert not missing, f"states written but not treated as live: {sorted(missing)}"


def test_has_due_spy_steps_per_state(monkeypatch):
    now = _now()
    cases = [
        ("WAITING_AT_CITY",       "executeAfter"),
        ("WAITING_FOR_GARRISON",  "garrisonExecuteAfter"),
        ("EXECUTING_WAREHOUSE",   "collectAfter"),
        ("EXECUTING_GARRISON",    "garrisonCollectAfter"),
        ("WAITING_FOR_MOVEMENTS", "movementsExecuteAfter"),
        ("EXECUTING_MOVEMENTS",   "movementsCollectAfter"),
    ]
    for state, field in cases:
        _patch(monkeypatch, [_mission(state=state, **{field: now - 5})])
        assert em.has_due_spy_steps(), f"{state} due"
        _patch(monkeypatch, [_mission(state=state, **{field: now + 300})])
        assert not em.has_due_spy_steps(), f"{state} not yet due"


def test_has_due_spy_steps_ignores_terminal_and_untimed(monkeypatch):
    now = _now()
    _patch(monkeypatch, [_mission(state="DONE", executeAfter=now - 5),
                         _mission(state="TRAVELING", executeAfter=now - 5)])
    assert not em.has_due_spy_steps()


def test_next_spy_eta_includes_movements_legs(monkeypatch):
    """The sleep-wake ETA must see the movements leg too, or the bot sleeps through it."""
    import queue_processor as qp
    now = _now()
    _patch(monkeypatch, [_mission(state="WAITING_FOR_MOVEMENTS", movementsExecuteAfter=now + 40),
                         _mission(state="EXECUTING_MOVEMENTS", movementsCollectAfter=now + 90)])
    assert qp._get_next_spy_eta() == now + 40


# ── Verified full sweep mark (fullSweepAt) ──────────────────────────────────────

def _full(now, **over):
    m = _mission(state="DONE", needMovements=True, movementsResult={"enemyReturnAt": None},
                 movementsExecutedAt=now - 60,
                 result={"resources": {"wood": 5}, "reportedAt": now - 120},
                 garrisonResult={"success": True, "troops": {}, "reportedAt": now - 90})
    m.update(over)
    return m


def test_full_sweep_at_is_the_oldest_leg_of_a_complete_sweep():
    now = _now()
    assert em.full_sweep_at(_full(now)) == now - 120


def test_full_sweep_at_none_unless_every_leg_succeeded():
    now = _now()
    bad = {
        "not DONE":              {"state": "EXECUTING_MOVEMENTS"},
        "no movements asked":    {"needMovements": False},
        "movements never ran":   {"movementsResult": None},
        "garrison failed":       {"garrisonResult": {"success": False, "troops": {}, "reportedAt": now - 90}},
        "garrison unread":       {"garrisonResult": {"success": True, "reportedAt": now - 90}},
        "garrison errored":      {"garrisonResult": {"success": True, "troops": {}, "error": "x", "reportedAt": now - 90}},
        "no warehouse":          {"result": {"reportedAt": now - 120}},
        "imported":              {"importedFromReport": True},
        "no spy origin":         {"originCityId": ""},
        "undated movements":     {"movementsExecutedAt": None},
        "undated warehouse":     {"result": {"resources": {"wood": 5}}},
    }
    for why, over in bad.items():
        assert em.full_sweep_at(_full(now, **over)) is None, why


def test_collect_movements_stamps_full_sweep_when_all_legs_ok(monkeypatch):
    now = _now()
    h = _patch(monkeypatch, [_full(now, state="EXECUTING_MOVEMENTS", movementsResult=None,
                                   movementsCollectAfter=now - 1)])
    monkeypatch.setattr(em, "_fetch_reports_html", lambda *a, **k: "<movements/>")
    monkeypatch.setattr(em, "_enemy_return_from_movements", lambda html, name, now=None: None)
    em.collect_movements_results(session=object())
    assert h["missions"][0]["fullSweepAt"] == now - 120


def test_collect_movements_does_not_stamp_when_garrison_failed(monkeypatch):
    """The movements leg finishing is not enough: a failed garrison read must not earn the mark."""
    now = _now()
    h = _patch(monkeypatch, [_full(now, state="EXECUTING_MOVEMENTS", movementsResult=None,
                                   movementsCollectAfter=now - 1,
                                   garrisonResult={"success": False, "troops": {}, "reportedAt": now - 90})])
    monkeypatch.setattr(em, "_fetch_reports_html", lambda *a, **k: "<movements/>")
    monkeypatch.setattr(em, "_enemy_return_from_movements", lambda html, name, now=None: None)
    em.collect_movements_results(session=object())
    assert h["missions"][0]["state"] == "DONE"
    assert h["missions"][0]["fullSweepAt"] is None


def test_rearming_a_parked_spy_clears_the_mark(monkeypatch):
    """A re-run is a new sweep: the previous run's mark must not survive into it."""
    now = _now()
    h = _patch(monkeypatch, [_full(now, fullSweepAt=now - 120)])
    assert em.reexecute_stationed_spy("100", fast=True, need_garrison=True, need_movements=True)
    assert h["missions"][0]["state"] == "WAITING_AT_CITY"
    assert h["missions"][0]["fullSweepAt"] is None


def test_sweep_keeps_only_the_newest_pool_of_a_farm_target(monkeypatch, tmp_path):
    """A farm target with pools from two origins keeps the newest live one and recalls the
    older idle pool (09/11: 2-11 idle pools per farm target, ~100 spies parked abroad)."""
    missions = [_mission(state="DONE", targetCityId="300", originCityId="1", dispatchedAt=1000),
                _mission(state="DONE", targetCityId="300", originCityId="2", dispatchedAt=5000)]
    entries = [{"cityId": "300", "cityName": "FarmAlvo", "state": "WAITING_AT_CITY"}]
    h, _, queued = _sweep_setup(monkeypatch, tmp_path, missions, entries, farm_ids={"300"})
    (tmp_path / "own.json").write_text(
        '[{"cityId": "1", "name": "A", "safehousePosition": 3},'
        ' {"cityId": "2", "name": "B", "safehousePosition": 4}]')
    em.process_recall_unused_flag(session=object())
    assert [q["originCityId"] for q in queued] == ["1"]
    assert h["missions"][0]["state"] == "RECALLED"
    assert h["missions"][1]["state"] == "DONE"
