"""
Movements collector on a REAL militaryAdvisor response (tests/fixtures/military_advisor.json,
captured 2026-11-14, names replaced): an own transport, a pillage coming home with loot, the
blockade fleet of the same raid coming home, plus one hand-made variant of the pillage with an
empty hold.
"""
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("telegram_notifier", types.ModuleType("telegram_notifier"))

import db_manager
import empire_collector as ec

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "military_advisor.json")


class _Session:
    def __init__(self, fail=False):
        self.fail = fail
    def post(self, *a, **k):
        if self.fail:
            raise RuntimeError("rede em baixo")
        with open(_FIXTURE, encoding="utf-8") as f:
            return f.read()


def _env(monkeypatch, tmp_path):
    monkeypatch.setattr(db_manager, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(db_manager, "_LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "_DB_INIT_DONE", False)
    monkeypatch.setattr(ec, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(ec, "save_capture", lambda *a, **k: None)
    monkeypatch.setattr(ec, "_load_alert_settings", lambda: {"returnEnabled": False, "incomingEnabled": False})
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)


def test_movements_carry_city_ids_and_mission_class(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    mv = ec._collect_movements(_Session(), "30817")
    assert [m["missionClass"] for m in mv] == ["transport", "plunder", "blockade", "plunder"]
    loot = mv[1]
    assert (loot["direction"], loot["isOwn"]) == ("<-", True)
    assert (loot["originCityId"], loot["targetCityId"]) == ("30817", "28208")
    assert loot["destination"] == "Alvo 3 (Dono C)"


def test_loot_return_is_logged_with_the_target_city_id(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    ec._collect_movements(_Session(), "30817")
    rows = {r["from_city_id"]: r for r in db_manager.get_loot_log()}
    assert (rows["28208"]["wood"], rows["28208"]["wine"]) == (19775, 22455)


def test_empty_pillage_return_is_recorded_but_blockade_return_is_not(monkeypatch, tmp_path):
    """The blockade fleet of the Alvo 3 raid also comes home with no cargo — that must not
    count as "the raid on Alvo 3 came back empty". Only the empty PILLAGE (Alvo 9) does."""
    _env(monkeypatch, tmp_path)
    ec._collect_movements(_Session(), "30817")
    rows = db_manager.get_loot_log()
    empties = [r for r in rows if r["wood"] + r["wine"] + r["marble"] + r["crystal"] + r["sulfur"] == 0]
    assert [r["from_city_id"] for r in empties] == ["99001"]
    assert len(rows) == 2
    ec._collect_movements(_Session(), "30817")           # seen again → not duplicated
    assert len(db_manager.get_loot_log()) == 2


def test_failed_read_returns_none_and_keeps_the_previous_file(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    path = tmp_path / "movements.json"
    path.write_text(json.dumps([{"isOwn": True, "direction": "->", "destination": "X (Y)"}]))
    assert ec._collect_movements(_Session(fail=True), "30817") is None
    assert ec.refresh_movements(_Session(fail=True), "30817") is False
    assert json.loads(path.read_text())[0]["destination"] == "X (Y)"      # not wiped to []
    assert ec.refresh_movements(_Session(), "30817") is True
    assert len(json.loads(path.read_text())) == 4


# ── P13.15: a city whose read failed keeps its previous data, marked as old ─────

def _prev_snapshot(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setattr(ec, "LOGS_DIR", str(tmp_path))
    (tmp_path / "own_cities.json").write_text(_json.dumps([
        {"name": "Polis", "cityId": 7, "x": 41, "y": 43, "islandId": "9", "safehousePosition": 8},
        {"name": "Desire", "cityId": 8, "x": 41, "y": 43, "islandId": "9", "safehousePosition": 3}]))
    (tmp_path / "resources.json").write_text(_json.dumps(
        {"Polis": {"Wine": 5000, "wineRunsOutIn": 7200}, "Desire": {"Wine": 1}}))
    (tmp_path / "empire.json").write_text(_json.dumps(
        {"Polis": {"_constructionEnds": 0, "Academia": "20", "Espionagem": "32"}}))


def test_failed_city_keeps_its_previous_data(tmp_path, monkeypatch):
    _prev_snapshot(tmp_path, monkeypatch)
    cities = [{"name": "Desire", "cityId": 8}]
    resources, empire, names = {"Desire": {"Wine": 9}}, {"Desire": {"Taberna": "5"}}, {"Taberna"}

    stale = ec._carry_over_failed_cities([7], cities, resources, empire, names)

    polis = next(c for c in cities if c["cityId"] == 7)
    assert polis["stale"] is True and polis["safehousePosition"] == 8
    assert stale == {"Polis": polis["staleSince"]} and polis["staleSince"] > 0
    assert resources["Polis"]["Wine"] == 5000 and resources["Desire"]["Wine"] == 9
    assert empire["Polis"]["Academia"] == "20" and {"Academia", "Espionagem"} <= names
    assert "_constructionEnds" not in names


def test_second_failure_keeps_the_original_stale_date_and_unknown_city_is_skipped(tmp_path, monkeypatch):
    import json as _json
    _prev_snapshot(tmp_path, monkeypatch)
    prev = _json.loads((tmp_path / "own_cities.json").read_text())
    prev[0].update(stale=True, staleSince=1234)
    (tmp_path / "own_cities.json").write_text(_json.dumps(prev))
    cities, resources, empire = [], {}, {}
    stale = ec._carry_over_failed_cities([7, 999], cities, resources, empire, set())
    assert stale == {"Polis": 1234} and [c["cityId"] for c in cities] == [7]
    assert ec._carry_over_failed_cities([], cities, resources, empire, set()) == {}
