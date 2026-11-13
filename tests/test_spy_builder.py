"""F14: autonomous spy training — planner brakes and the pass orchestration."""
import json
import sys
import time
import types

import spy_builder as sb

S = dict(sb.DEFAULT_SPY_BUILD_SETTINGS)
OWN = [{"cityId": "1", "name": "A", "safehousePosition": 8},
       {"cityId": "2", "name": "B", "safehousePosition": 5},
       {"cityId": "3", "name": "C", "safehousePosition": None}]
RICH = {"A": {"Crystal": 100000}, "B": {"Crystal": 100000}, "C": {"Crystal": 100000}}


def _c(cap=40, free=30, d=5, out=5, order_max=None):
    return {"trainable": cap, "freeSlots": free, "inDefense": d, "deployed": out,
            "orderMax": free if order_max is None else order_max}


def test_fill_mode_orders_every_free_slot_biggest_first():
    orders, notes = sb.plan_spy_builds({"1": _c(free=10), "2": _c(free=30)}, OWN, RICH, {},
                                       10**7, S)
    assert [(o["name"], o["amount"]) for o in orders] == [("B", 30), ("A", 10)]
    assert orders[0]["gold"] == 30 * 150 and orders[0]["crystal"] == 30 * 40
    assert notes == {}


def test_city_without_safehouse_or_free_slots_is_skipped():
    orders, _ = sb.plan_spy_builds({"1": _c(free=0), "3": _c(free=40)}, OWN, RICH, {}, 10**7, S)
    assert orders == []


def test_target_mode_only_fills_the_gap():
    s = dict(S, targetPerCity=20)
    # cap 40, 30 free → 10 exist → gap 10; city B already has 35 → nothing
    orders, _ = sb.plan_spy_builds({"1": _c(free=30), "2": _c(free=5)}, OWN, RICH, {}, 10**7, s)
    assert [(o["name"], o["amount"]) for o in orders] == [("A", 10)]


def test_order_max_from_the_slider_caps_the_order():
    orders, _ = sb.plan_spy_builds({"1": _c(free=30, order_max=12)}, OWN, RICH, {}, 10**7, S)
    assert orders[0]["amount"] == 12


def test_gold_floor_brake():
    gold = S["goldFloor"] + 150 * 7 + 100        # room for 7 spies
    orders, notes = sb.plan_spy_builds({"1": _c(free=30), "2": _c(free=20)}, OWN, RICH, {},
                                       gold, S)
    assert sum(o["amount"] for o in orders) == 7
    assert notes["A"] == "7/30 — ouro no piso" and notes["B"] == "0/20 — ouro no piso"


def test_crystal_floor_counts_building_queue_reservations():
    res = {"A": {"Crystal": S["crystalFloor"] + 1000 + 40 * 3}}
    orders, notes = sb.plan_spy_builds({"1": _c(free=30)}, OWN, res, {"A": 1000}, 10**7, S)
    assert orders[0]["amount"] == 3 and notes["A"] == "3/30 — cristal no piso"


def test_per_pass_cap_spreads_over_passes():
    s = dict(S, maxPerPass=35)
    orders, notes = sb.plan_spy_builds({"1": _c(free=30), "2": _c(free=30)}, OWN, RICH, {},
                                       10**7, s)
    assert sum(o["amount"] for o in orders) == 35
    assert "limite por passagem" in notes["B"]


def _env(monkeypatch, tmp_path, settings=None, counts_age=60):
    for name, attr in (("spy_build_settings.json", "SPY_BUILD_SETTINGS_PATH"),
                       ("spy_build_status.json", "SPY_BUILD_STATUS_PATH"),
                       ("spy_counts.json", "_SPY_COUNTS_PATH"),
                       ("own_cities.json", "_OWN_CITIES_PATH"),
                       ("statusSummary.json", "_STATUS_SUMMARY_PATH")):
        monkeypatch.setattr(sb, attr, str(tmp_path / name))
    monkeypatch.setattr(sb, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(sb, "_crystal_reserved", lambda: {})
    monkeypatch.setattr(sb.time, "sleep", lambda s: None)
    if settings is not None:
        (tmp_path / "spy_build_settings.json").write_text(json.dumps(settings))
    (tmp_path / "spy_counts.json").write_text(json.dumps(
        {"lastUpdated": int(time.time()) - counts_age, "byCityId": {"1": _c(free=4)}}))
    (tmp_path / "own_cities.json").write_text(json.dumps(OWN))
    (tmp_path / "resources.json").write_text(json.dumps(RICH))
    (tmp_path / "statusSummary.json").write_text(json.dumps({"gold": {"total": 10**7}}))
    seen = []
    stub = types.ModuleType("telegram_notifier")
    stub.notify_spies_trained = lambda done, failed, dry: seen.append((done, failed, dry))
    monkeypatch.setitem(sys.modules, "telegram_notifier", stub)
    return seen


def test_dry_run_sends_nothing_to_the_game(monkeypatch, tmp_path):
    seen = _env(monkeypatch, tmp_path)
    monkeypatch.setattr(sb, "_order_spies", lambda *a: (_ for _ in ()).throw(AssertionError))
    sb.process_spy_builder(session=None)
    st = json.loads((tmp_path / "spy_build_status.json").read_text())
    assert st["dryRun"] is True and st["ordered"] == 4
    assert seen[0][2] is True and seen[0][0][0]["amount"] == 4


def test_live_pass_orders_and_respects_interval(monkeypatch, tmp_path):
    seen = _env(monkeypatch, tmp_path, settings={"dryRun": False})
    calls = []
    monkeypatch.setattr(sb, "_order_spies", lambda session, o: (calls.append(o), (True, "ok"))[1])
    sb.process_spy_builder(session=object())
    assert [c["amount"] for c in calls] == [4]
    sb.process_spy_builder(session=object())           # within intervalMinutes → no-op
    assert len(calls) == 1
    assert seen[0][2] is False


def test_refused_order_is_reported(monkeypatch, tmp_path):
    seen = _env(monkeypatch, tmp_path, settings={"dryRun": False})
    monkeypatch.setattr(sb, "_order_spies", lambda session, o: (False, "Sem cristal"))
    sb.process_spy_builder(session=object())
    st = json.loads((tmp_path / "spy_build_status.json").read_text())
    assert st["ordered"] == 0 and st["failed"][0]["reason"] == "Sem cristal"
    assert seen[0][1][0]["reason"] == "Sem cristal"


def test_stale_counts_disabled_or_inactive_hours_do_nothing(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, counts_age=3600)
    sb.process_spy_builder(session=None)
    assert not (tmp_path / "spy_build_status.json").exists()
    _env(monkeypatch, tmp_path, settings={"enabled": False})
    sb.process_spy_builder(session=None)
    assert not (tmp_path / "spy_build_status.json").exists()
    _env(monkeypatch, tmp_path)
    sb.process_spy_builder(session=None, in_active_hours=False)
    assert not (tmp_path / "spy_build_status.json").exists()


def test_feedback_parses_success_and_refreshes_token(monkeypatch):
    cfg = types.ModuleType("ikabot.config")
    cfg.actionRequest = "old"
    ika = types.ModuleType("ikabot")
    ika.config = cfg
    monkeypatch.setitem(sys.modules, "ikabot", ika)
    monkeypatch.setitem(sys.modules, "ikabot.config", cfg)
    ok, text = sb._feedback([["updateGlobalData", {"actionRequest": "new"}],
                             ["provideFeedback", [{"type": 10, "text": "Treino iniciado"}]]])
    assert ok and text == "Treino iniciado" and cfg.actionRequest == "new"
    ok, text = sb._feedback([["provideFeedback", [{"type": 11, "text": "Sem recursos"}]]])
    assert not ok and text == "Sem recursos"


def test_preview_plans_dry_even_when_live_and_keeps_the_interval(monkeypatch, tmp_path):
    seen = _env(monkeypatch, tmp_path, settings={"dryRun": False, "enabled": False},
                counts_age=99999)
    monkeypatch.setattr(sb, "_order_spies", lambda *a: (_ for _ in ()).throw(AssertionError))
    sb.process_spy_builder(session=None, force_preview=True)
    st = json.loads((tmp_path / "spy_build_status.json").read_text())
    assert st["dryRun"] is True and st["preview"] is True and st["ordered"] == 4
    assert st["lastPassAt"] == 0 and seen == []          # no alert, interval untouched
