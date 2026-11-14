"""
Parser + collector tests on a REAL capture of the safehouse reports tab
(tests/fixtures/spy_reports_tab.html — taken 2026-11-14 from the live game, names replaced).

Until now every espionage fixture was hand-typed, so nothing pinned the real markup. This
page holds one of each case that matters: a successful warehouse report, the game's explicit
"Missão falhada!" (the report that used to be skipped for two hours), an arrival notice and a
recall report.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import espionage_manager as em
import espionage_parsers as ep

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "spy_reports_tab.html")


def _html():
    with open(_FIXTURE, encoding="utf-8") as f:
        return f.read()


def _reports():
    return ep._parse_reports_from_html(_html())


def test_every_report_row_is_found_with_city_id_and_date():
    reports = _reports()
    assert len(reports) == 10 == len(ep.split_report_chunks(_html()))
    assert all(r["targetCityId"] and r["dateText"] and r["subject"] for r in reports.values())


def test_report_ids_grow_with_time():
    """The id baseline relies on this: a higher id is never an older report."""
    def key(r):
        d, t = r["dateText"].split()
        day, month, year = d.split(".")
        h, mi, s = (int(x) for x in t.split(":"))
        return (int(year), int(month), int(day), h, mi, s)
    reports = _reports()
    ids = sorted(reports, key=int)
    assert [key(reports[i]) for i in ids] == sorted(key(reports[i]) for i in ids)


def test_successful_warehouse_report():
    r = _reports()["358203"]
    assert (r["success"], r["failed"], r["isArrival"]) == (True, False, False)
    assert r["resources"] == {"wood": 15864, "wine": 44, "marble": 18955, "glass": 3537, "sulfur": 3537}
    assert r["troops"] is None and (r["lostAgents"], r["sentAgents"]) == (0, 4)


def test_failed_mission_is_explicit_not_just_missing_success():
    r = _reports()["358300"]
    assert r["failed"] is True and r["success"] is False
    assert r["resources"] is None and r["troops"] is None
    assert (r["lostAgents"], r["sentAgents"]) == (0, 4)
    assert r["subject"].startswith("Recursos em")


def test_arrival_and_recall_are_not_failures():
    reports = _reports()
    arrival, recall = reports["358295"], reports["358208"]
    assert arrival["isArrival"] and not arrival["failed"]
    assert not recall["failed"] and not recall["isArrival"] and recall["resources"] is None
    assert (recall["lostAgents"], recall["sentAgents"]) == (1, 4)      # one agent lost on the way home


# ── collectors against the real page ─────────────────────────────────────────────

def _patch(monkeypatch, missions):
    holder = {"missions": missions}
    monkeypatch.setattr(em, "_load_missions", lambda: holder)
    monkeypatch.setattr(em, "_save_missions", lambda d: holder.update(d))
    monkeypatch.setattr(em.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(em, "_get_city_safehouse_position", lambda cid: 8)
    monkeypatch.setattr(em, "_is_farm_target", lambda cid: True)
    monkeypatch.setattr(em, "_report_state", {"max": 0, "at": em.time.time(), "loaded": True})
    monkeypatch.setattr(em, "_save_report_state", lambda: None)
    monkeypatch.setattr(em, "_fetch_reports_html", lambda *a, **k: _html())
    monkeypatch.setattr(em, "_load_espionage_settings", lambda: {"garrisonThresholdTotal": 30000})
    return holder


def _mission(city_id, name, **kw):
    now = int(em.time.time())
    m = {"originCityId": "30824", "targetCityId": city_id, "targetCityName": name,
         "targetPlayerName": "Dono", "numAgents": 4, "safehousePosition": 8,
         "state": "EXECUTING_WAREHOUSE", "executedAt": now - 60, "collectAfter": now - 1,
         "needGarrison": False}
    m.update(kw)
    return m


def test_game_failed_report_fails_the_mission_at_once(monkeypatch):
    """Alvo 3 (cityId 28208): executed after report 358295; the game answered 358300 'Missão
    falhada!'. The mission must fail NOW (it used to wait 2h, polling), keep the spies as
    reusable (0/4 lost), and never adopt an older report."""
    h = _patch(monkeypatch, [_mission("28208", "Alvo 3", reportBaselineId=358295)])
    em.collect_mission_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "FAILED"
    assert "0/4" in m["error"] and not em._spy_pool_gone(m["error"])
    assert m["result"]["reportId"] == "358300"


def test_all_agents_lost_is_reported_as_spies_gone():
    assert em._spy_pool_gone(em._failed_report_error({"lostAgents": 4, "sentAgents": 4}))
    assert not em._spy_pool_gone(em._failed_report_error({"lostAgents": 1, "sentAgents": 4}))


def test_old_failures_of_the_same_city_do_not_fail_a_newer_execution(monkeypatch):
    """Baseline 358300 = everything on the page predates this execution: keep waiting, with
    the poll backed off — the three earlier failed reports of this city are not ours."""
    h = _patch(monkeypatch, [_mission("28208", "Alvo 3", reportBaselineId=358300)])
    em.collect_mission_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "EXECUTING_WAREHOUSE"
    assert m["collectAfter"] >= int(em.time.time()) + 25 and m["collectMisses"] == 1


def test_real_warehouse_report_is_adopted_when_newer_than_baseline(monkeypatch):
    h = _patch(monkeypatch, [_mission("47480", "Alvo 1", reportBaselineId=358200)])
    em.collect_mission_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "DONE"
    assert sum(m["result"]["resources"].values()) == 41937
    assert m["result"]["dateText"] == "14.11.2026 12:22:51"


def test_without_baseline_an_old_failure_is_not_used_to_fail(monkeypatch):
    """Legacy missions (executed before the baseline existed) keep the old behaviour."""
    h = _patch(monkeypatch, [_mission("28208", "Alvo 3")])
    em.collect_mission_results(session=object())
    assert h["missions"][0]["state"] == "EXECUTING_WAREHOUSE"


def test_failed_garrison_leg_is_not_a_clean_port(monkeypatch):
    now = int(em.time.time())
    h = _patch(monkeypatch, [_mission("28208", "Alvo 3", state="EXECUTING_GARRISON",
                                      garrisonExecutedAt=now - 60, garrisonCollectAfter=now - 1,
                                      garrisonBaselineId=358295)])
    em.collect_garrison_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "DONE"
    g = m["garrisonResult"]
    assert g["success"] is False and g["error"] and "troops" not in g


def test_failed_movements_leg_leaves_the_port_unconfirmed(monkeypatch):
    now = int(em.time.time())
    h = _patch(monkeypatch, [_mission("28208", "Alvo 3", state="EXECUTING_MOVEMENTS",
                                      movementsExecutedAt=now - 60, movementsCollectAfter=now - 1,
                                      movementsBaselineId=358295, needMovements=True)])
    em.collect_movements_results(session=object())
    m = h["missions"][0]
    assert m["state"] == "DONE" and m.get("movementsResult") is None
    assert not m.get("fullSweepAt")
