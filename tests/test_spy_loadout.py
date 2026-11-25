"""Spy loadout from the game's own odds (agents + decoys), resuming a sweep at the failed leg,
skipping the warehouse on inactive fleet targets and the movements leg when ships are in port."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import espionage_manager as em

# Numbers from a real spyMissions view (inactive target, safehouse 20, 20 defending spies).
PARAMS = {
    "targetFreeSpies": 20, "targetCityLevel": 21, "targetSafehouseLevel": "20",
    "isTargetInactive": True, "remainingRisk": 0, "targetGovFactor": 0,
    "cEspionageMinChance": 5, "cEspionageMaxChance": 95, "cEspionageMaxSuccessChance": 99,
    "cSpyRiskReductionFactorInactivity": 10, "cSpyRiskReductionFactorNoSafehouse": 2,
    "cEspionageDecoyRiskREduction": 10, "cEspionageMinDecoyRisk": 2, "cEspionageBasicDecoyRisk": 5,
    "cTradegoodWine": 1, "cTradegoodSulfur": 4, "cGold": 5, "cEspionageDecoy": 301,
    "missionData": {
        "5": {"gold": 150, "riskBefore": 60, "riskAfter": 15, "riskPerSpy": 6, "successChance": 30,
              "301": {"5": 100}},
        "6": {"gold": 120, "riskBefore": 70, "riskAfter": 20, "riskPerSpy": 6, "successChance": 55,
              "301": {"1": 70}},
        "7": {"gold": 50, "riskBefore": 50, "riskAfter": 22, "riskPerSpy": 2, "successChance": 20,
              "301": {"4": 100}},
    },
}


def _now():
    return int(time.time())


# ── The game's formula ───────────────────────────────────────────────────────────

def test_spy_odds_match_the_mission_window():
    s, r = em.spy_odds(PARAMS, 5, 1)
    assert round(r, 1) == 11.8 and round(s) == 26          # warehouse, 1 agent
    s, r = em.spy_odds(PARAMS, 5, 4)
    assert round(s) == 67                                  # the bot's old 4 agents
    s, r = em.spy_odds(PARAMS, 7, 1)
    assert round(s) == 18                                  # movements: worst odds of all
    s, r = em.spy_odds(PARAMS, 6, 4, decoys=1)
    assert round(r, 1) == 2.8 and round(s) == 93           # one decoy almost removes the risk


def test_active_target_risk_is_not_divided():
    active = dict(PARAMS, isTargetInactive=False)
    s, r = em.spy_odds(active, 5, 4)
    assert r == 95 and round(s) == 5


def test_spy_odds_unknown_mission():
    assert em.spy_odds(PARAMS, 99, 1) is None
    assert em.spy_odds({}, 5, 1) is None


def test_plan_reaches_target_with_fewest_spies():
    n, d, s, _ = em.plan_spy_loadout(PARAMS, 6, 10, 90, 2)
    assert (n, d) == (4, 1) and s >= 90                    # garrison
    n, d, s, _ = em.plan_spy_loadout(PARAMS, 5, 10, 90, 2)
    assert n + d <= 10 and d >= 1 and s >= 90              # warehouse needs a decoy


def test_plan_best_effort_when_target_unreachable():
    n, d, s, _ = em.plan_spy_loadout(PARAMS, 7, 10, 90, 2)
    assert n + d <= 10 and s < 90
    for nn in range(1, 11):                                # nothing in the pool does better
        for dd in range(0, min(2, 10 - nn) + 1):
            assert em.spy_odds(PARAMS, 7, nn, dd)[0] <= s


def test_plan_without_decoys_and_tiny_pool():
    n, d, _, _ = em.plan_spy_loadout(PARAMS, 6, 10, 90, 0)
    assert d == 0
    assert em.plan_spy_loadout(PARAMS, 5, 1, 90, 2)[:2] == (1, 0)
    assert em.plan_spy_loadout(PARAMS, 5, 0, 90, 2) is None


def test_plan_never_exceeds_the_pool():
    for pool in range(1, 12):
        for mid in (5, 6, 7):
            n, d, _, _ = em.plan_spy_loadout(PARAMS, mid, pool, 99, 3)
            assert 1 <= n and n + d <= pool


def test_parse_view_params_from_response():
    resp = [["updateGlobalData", {}],
            ["updateTemplateData", {"js_spyCount_1": "3",
                                    "load_js": {"filepath": "x.js", "params": json.dumps(PARAMS)}}]]
    assert em._parse_view_params(resp)["targetFreeSpies"] == 20
    assert em._parse_view_params([["updateTemplateData", {"js_spyCount_1": "3"}]]) is None


# ── Decoy budget ────────────────────────────────────────────────────────────────

def _resources(tmp_path, monkeypatch, gold, wine=100000, sulfur=100000):
    with open(tmp_path / "own.json", "w") as f:
        json.dump([{"cityId": "1", "name": "Home"}], f)
    with open(tmp_path / "resources.json", "w") as f:
        json.dump({"Home": {"Wine": wine, "Sulfur": sulfur, "wineConsumptionPerHour": 100}}, f)
    with open(tmp_path / "statusSummary.json", "w") as f:
        json.dump({"gold": {"total": gold}}, f)
    monkeypatch.setattr(em, "OWN_CITIES_PATH", str(tmp_path / "own.json"))
    monkeypatch.setattr(em, "LOGS_DIR", str(tmp_path))


def test_decoys_paid_within_floors(tmp_path, monkeypatch):
    _resources(tmp_path, monkeypatch, gold=50150)
    assert em._decoys_affordable("1", PARAMS, 5, 2) == 1          # 100 gold each above 50k floor
    _resources(tmp_path, monkeypatch, gold=10**6, wine=2400 + 70)
    assert em._decoys_affordable("1", PARAMS, 6, 2) == 1          # keeps 24h of wine
    _resources(tmp_path, monkeypatch, gold=10**6, sulfur=0)
    assert em._decoys_affordable("1", PARAMS, 7, 2) == 0


def test_decoys_unknown_resources_means_none(tmp_path, monkeypatch):
    monkeypatch.setattr(em, "OWN_CITIES_PATH", str(tmp_path / "missing.json"))
    assert em._decoys_affordable("1", PARAMS, 5, 2) == 0


# ── Wiring into the legs ────────────────────────────────────────────────────────

def _patch(monkeypatch, missions):
    holder = {"missions": missions}
    monkeypatch.setattr(em, "_load_missions", lambda: holder)
    monkeypatch.setattr(em, "_save_missions", lambda d: holder.update(d))
    monkeypatch.setattr(em.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(em, "_get_city_safehouse_position", lambda cid: 3)
    monkeypatch.setattr(em, "_is_farm_target", lambda cid: False)
    monkeypatch.setattr(em, "_report_state", {"max": 0, "at": em.time.time(), "loaded": True})
    monkeypatch.setattr(em, "_save_report_state", lambda: None)
    return holder


def _mission(**kw):
    m = {"originCityId": "1", "targetCityId": "100", "targetCityName": "Alvo",
         "targetPlayerName": "Inimigo", "islandX": 40, "islandY": 50,
         "numAgents": 10, "safehousePosition": 3, "spySessionId": "SID"}
    m.update(kw)
    return m


def test_warehouse_leg_sends_planned_agents_and_decoys(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="WAITING_AT_CITY", executeAfter=_now() - 10)])

    def view(*a, **k):
        em._view_params[("1", "100")] = PARAMS
        return 10, "<html>"
    monkeypatch.setattr(em, "_fetch_spy_missions_view", view)
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "SID")
    monkeypatch.setattr(em, "_decoys_affordable", lambda o, p, mt, w: w)
    sent = []
    monkeypatch.setattr(em, "_execute_spy_mission",
                        lambda s, o, t, p, sid, n, mt, num_decoys=0: (sent.append((n, num_decoys)),
                                                                     (True, "ok"))[1])
    em.execute_waiting_missions(session=object())
    (n, d), = sent
    assert d >= 1 and n + d <= 10
    assert h["missions"][0]["state"] == "EXECUTING_WAREHOUSE"


def test_leg_without_odds_falls_back_to_capped_agents(monkeypatch):
    em._view_params.clear()
    h = _patch(monkeypatch, [_mission(state="WAITING_AT_CITY", executeAfter=_now() - 10,
                                      numAgents=4)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view", lambda *a, **k: (2, "<html>"))
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "SID")
    sent = []
    monkeypatch.setattr(em, "_execute_spy_mission",
                        lambda s, o, t, p, sid, n, mt, num_decoys=0: (sent.append((n, num_decoys)),
                                                                     (True, "ok"))[1])
    em.execute_waiting_missions(session=object())
    assert sent == [(2, 0)]
    assert h["missions"][0]["state"] == "EXECUTING_WAREHOUSE"


# ── Resume at the failed leg ────────────────────────────────────────────────────

def _done(**kw):
    now = _now()
    base = dict(state="DONE", dispatchedAt=now - 600, executedAt=now - 600,
                result={"success": True, "resources": {"wood": 900000}, "reportedAt": now - 590})
    base.update(kw)
    return _mission(**base)


def test_resume_redoes_only_the_failed_garrison(monkeypatch):
    h = _patch(monkeypatch, [_done(garrisonResult={"success": False, "error": "falhou"})])
    assert em.reexecute_stationed_spy("100", need_garrison=True, need_movements=True)
    m = h["missions"][0]
    assert m["state"] == "WAITING_FOR_GARRISON"
    assert m["result"]["resources"] == {"wood": 900000}       # warehouse kept
    assert m["garrisonResult"] is None and m["garrisonExecuteAfter"] > 0


def test_resume_redoes_only_the_movements(monkeypatch):
    now = _now()
    h = _patch(monkeypatch, [_done(garrisonResult={"success": True, "troops": {}, "reportedAt": now - 500},
                                   movementsResult=None)])
    assert em.reexecute_stationed_spy("100", need_garrison=True, need_movements=True)
    m = h["missions"][0]
    assert m["state"] == "WAITING_FOR_MOVEMENTS"
    assert m["garrisonResult"]["success"] is True and m["movementsExecuteAfter"] > 0


def test_stale_legs_restart_from_the_warehouse(monkeypatch):
    old = _now() - em._LEG_REUSE_MAX_AGE - 60
    h = _patch(monkeypatch, [_done(executedAt=old,
                                   result={"success": True, "resources": {"wood": 1}, "reportedAt": old})])
    assert em.reexecute_stationed_spy("100", need_garrison=True, need_movements=True)
    m = h["missions"][0]
    assert m["state"] == "WAITING_AT_CITY" and m["result"] is None


def test_rearm_without_warehouse_starts_at_garrison(monkeypatch):
    old = _now() - em._LEG_REUSE_MAX_AGE - 60
    h = _patch(monkeypatch, [_done(executedAt=old,
                                   result={"success": True, "resources": {"wood": 1}, "reportedAt": old})])
    assert em.reexecute_stationed_spy("100", need_garrison=True, need_movements=True,
                                      need_warehouse=False)
    m = h["missions"][0]
    assert m["state"] == "WAITING_FOR_GARRISON"
    assert m["result"] is None and m["needWarehouse"] is False


def test_worn_down_pool_is_not_reused(monkeypatch):
    _patch(monkeypatch, [_done(numAgents=1)])
    assert em.reexecute_stationed_spy("100", min_agents=5) is False


def test_fresh_spies_without_warehouse_go_straight_to_garrison(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="WAITING_AT_CITY", executeAfter=_now() - 10,
                                      needWarehouse=False, needGarrison=True)])
    monkeypatch.setattr(em, "_fetch_spy_missions_view",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("sem pedido aqui")))
    em.execute_waiting_missions(session=object())
    m = h["missions"][0]
    assert m["state"] == "WAITING_FOR_GARRISON" and m["garrisonExecuteAfter"] <= _now()


# ── Movements only when the port is empty ───────────────────────────────────────

def test_ships_in_port_skip_the_movements_leg(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="EXECUTING_GARRISON", garrisonCollectAfter=_now() - 1,
                                      needMovements=True)])
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k: {"1": {
        "troops": {}, "fleet": {"Navio Reparador": 3}, "success": True,
        "targetCityId": "100", "targetCityName": "Alvo"}})
    em.collect_garrison_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "DONE"
    assert m["movementsResult"]["enemyReturnAt"] is None
    assert m["movementsResult"]["skipped"] == "shipsInPort"


def test_empty_port_still_runs_the_movements_leg(monkeypatch):
    h = _patch(monkeypatch, [_mission(state="EXECUTING_GARRISON", garrisonCollectAfter=_now() - 1,
                                      needMovements=True)])
    monkeypatch.setattr(em, "_fetch_all_reports", lambda *a, **k: {"1": {
        "troops": {}, "fleet": {}, "success": True, "targetCityId": "100", "targetCityName": "Alvo"}})
    em.collect_garrison_results(session=object())
    assert h["missions"][0]["state"] == "WAITING_FOR_MOVEMENTS"


# ── Movements floor and worn pools ──────────────────────────────────────────────

def _movements_leg(monkeypatch, stationed, settings):
    h = _patch(monkeypatch, [_mission(state="WAITING_FOR_MOVEMENTS",
                                      movementsExecuteAfter=_now() - 10, numAgents=stationed)])

    def view(*a, **k):
        em._view_params[("1", "100")] = PARAMS
        return stationed, "<html>"
    monkeypatch.setattr(em, "_fetch_spy_missions_view", view)
    monkeypatch.setattr(em, "_parse_spy_session_id", lambda html: "SID")
    monkeypatch.setattr(em, "_decoys_affordable", lambda o, p, mt, w: 0)      # no sulfur
    monkeypatch.setattr(em, "_load_espionage_settings", lambda: settings)
    monkeypatch.setattr(em, "_report_baseline", lambda *a, **k: 0)
    sent = []
    monkeypatch.setattr(em, "_execute_spy_mission",
                        lambda s, o, t, p, sid, n, mt, num_decoys=0: (sent.append((n, num_decoys)),
                                                                     (True, "ok"))[1])
    em.execute_movements_missions(session=object())
    return h["missions"][0], sent


def test_movements_below_the_floor_are_not_run(monkeypatch):
    m, sent = _movements_leg(monkeypatch, 2, {"spyMinMovementsSuccess": 60})
    assert sent == []
    assert m["state"] == "DONE" and m["movementsSkipped"] == "low_odds"
    assert m.get("movementsResult") is None


def test_movements_floor_zero_always_runs(monkeypatch):
    m, sent = _movements_leg(monkeypatch, 2, {"spyMinMovementsSuccess": 0})
    assert len(sent) == 1 and m["state"] == "EXECUTING_MOVEMENTS"
    assert m["legOdds"]["7"]["stationed"] == 2


def _parked_after_movements(**kw):
    now = _now()
    return _done(garrisonResult={"success": True, "troops": {}, "reportedAt": now - 500},
                 movementsResult=None, **kw)


def test_shrunk_pool_below_target_is_not_reused(monkeypatch):
    em._view_params.clear()
    _patch(monkeypatch, [_parked_after_movements(
        numAgents=5, legOdds={"7": {"success": 49, "stationed": 10}})])
    assert em.reexecute_stationed_spy("100", need_garrison=True, need_movements=True) is False


def test_shrunk_pool_reused_when_the_odds_still_hold(monkeypatch):
    em._view_params.clear()
    em._view_params[("1", "100")] = PARAMS
    monkeypatch.setattr(em, "_decoys_affordable", lambda o, p, mt, w: w)
    h = _patch(monkeypatch, [_done(garrisonResult={"success": False, "error": "falhou"},
                                   numAgents=8, legOdds={"6": {"success": 93, "stationed": 10}})])
    assert em.reexecute_stationed_spy("100", need_garrison=True, need_movements=True)
    assert h["missions"][0]["state"] == "WAITING_FOR_GARRISON"


def test_low_odds_pool_reused_only_once_the_origin_pays_decoys(monkeypatch):
    m = _parked_after_movements(movementsSkipped="low_odds")
    _patch(monkeypatch, [m])
    monkeypatch.setattr(em, "decoys_affordable", lambda o, mt, w: 0)
    assert em.reexecute_stationed_spy("100", need_garrison=True, need_movements=True) is False
    monkeypatch.setattr(em, "decoys_affordable", lambda o, mt, w: w)
    assert em.reexecute_stationed_spy("100", need_garrison=True, need_movements=True)
    assert m["state"] == "WAITING_FOR_MOVEMENTS"


def test_decoys_affordable_uses_default_costs_without_a_view(tmp_path, monkeypatch):
    em._view_params.clear()
    _resources(tmp_path, monkeypatch, gold=10**6, sulfur=150)
    assert em.decoys_affordable("1", 7, 2) == 1                   # 100 sulfur each
