"""
Tests for the watchlist re-scan (F7): only islands of 'alvo'-marked players are
re-scanned and refreshed in world_scan.json.
Run with: python -m pytest tests/ -v
"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub ikabot.helpers.getJson so scan_collector imports standalone
for mod in ["ikabot", "ikabot.helpers", "ikabot.helpers.getJson"]:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)
if not hasattr(sys.modules["ikabot.helpers.getJson"], "getIsland"):
    sys.modules["ikabot.helpers.getJson"].getIsland = lambda html: {}

import scan_collector as sc
import db_manager
import empire_utils


import pytest


@pytest.fixture(autouse=True)
def _restore_globals():
    """_setup and a few tests assign module globals directly; put them back, or the fake
    get_all_marks / is_paused stay in force for every test that runs afterwards (P13.45)."""
    saved = [(mod, name, getattr(mod, name)) for mod, names in (
        (sc, ("WATCHLIST_SETTINGS_PATH", "WATCHLIST_STATE_PATH", "_WORLD_SCAN_PATH",
              "SCAN_CHECKPOINT_PATH", "_scan_one_island")),
        (empire_utils, ("is_paused",)),
        (db_manager, ("get_all_marks",)),
    ) for name in names]
    yield
    for mod, name, value in saved:
        setattr(mod, name, value)


def _setup(tmp_path, settings, marks, world_scan):
    sc.WATCHLIST_SETTINGS_PATH = str(tmp_path / "ws.json")
    sc.WATCHLIST_STATE_PATH    = str(tmp_path / "wstate.json")
    sc._WORLD_SCAN_PATH        = str(tmp_path / "world_scan.json")
    sc.SCAN_CHECKPOINT_PATH    = str(tmp_path / "checkpoint.json")  # absent → no full scan
    with open(sc.WATCHLIST_SETTINGS_PATH, "w") as f:
        json.dump(settings, f)
    with open(sc._WORLD_SCAN_PATH, "w") as f:
        json.dump(world_scan, f)
    empire_utils.is_paused = lambda: False
    db_manager.get_all_marks = lambda: marks


def test_settings_defaults_and_save(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "WATCHLIST_SETTINGS_PATH", str(tmp_path / "ws.json"))
    assert sc.get_watchlist_settings()["enabled"] is False
    saved = sc.save_watchlist_settings({"enabled": True, "intervalHours": 6})
    assert saved == {"enabled": True, "intervalHours": 6}
    assert sc.get_watchlist_settings()["enabled"] is True


def test_settings_read_junk_and_out_of_range_values(tmp_path, monkeypatch):
    p = tmp_path / "ws.json"
    monkeypatch.setattr(sc, "WATCHLIST_SETTINGS_PATH", str(p))
    p.write_text(json.dumps({"enabled": True, "intervalHours": "abc"}))
    assert sc.get_watchlist_settings() == {"enabled": True, "intervalHours": 12}
    p.write_text(json.dumps({"enabled": True, "intervalHours": 500}))
    assert sc.get_watchlist_settings()["intervalHours"] == 168
    p.write_text("{broken")
    assert sc.get_watchlist_settings() == {"enabled": False, "intervalHours": 12}
    # a save keeps what it is not sent
    sc.save_watchlist_settings({"enabled": False, "intervalHours": 6})
    assert sc.save_watchlist_settings({"enabled": True}) == {"enabled": True, "intervalHours": 6}


def test_disabled_does_nothing(tmp_path):
    _setup(tmp_path, {"enabled": False, "intervalHours": 12}, {}, {"players": [], "islands": []})
    calls = []
    sc._scan_one_island = lambda *a, **k: calls.append(1) or None
    sc.process_watchlist(session=object(), in_active_hours=True)
    assert calls == []


def test_rescans_only_marked_islands(tmp_path, monkeypatch):
    world = {
        "lastUpdated": 1, "ownCities": [{"name": "Home", "x": 40, "y": 50}],
        "islands": [
            {"islandId": "111", "x": 40, "y": 50, "resourceType": 1},   # marked 'alvo'
            {"islandId": "222", "x": 60, "y": 70, "resourceType": 2},   # not marked
        ],
        "players": [
            {"playerId": "9", "islandId": "111", "playerName": "Old", "state": "inactive", "islandX": 40, "islandY": 50},
            {"playerId": "5", "islandId": "222", "playerName": "Other", "state": "inactive", "islandX": 60, "islandY": 70},
        ],
    }
    marks = {"9_40_50": {"status": "alvo", "island_x": "40", "island_y": "50", "player_id": "9"}}
    _setup(tmp_path, {"enabled": True, "intervalHours": 12}, marks, world)

    scanned = []
    def fake_scan(session, island_id, x, y, own_cities, resource_type=0):
        scanned.append(str(island_id))
        return ({"islandId": str(island_id), "x": x, "y": y, "resourceType": resource_type},
                [{"playerId": "9", "islandId": str(island_id), "playerName": "Reactivated",
                  "state": "inactive", "islandX": x, "islandY": y}])
    monkeypatch.setattr(sc, "_scan_one_island", fake_scan)

    sc.process_watchlist(session=object(), in_active_hours=True)

    assert scanned == ["111"]            # only the marked island
    with open(sc._WORLD_SCAN_PATH) as f:
        out = json.load(f)
    # island 111's player refreshed; island 222 untouched
    p111 = [p for p in out["players"] if p["islandId"] == "111"]
    p222 = [p for p in out["players"] if p["islandId"] == "222"]
    assert len(p111) == 1 and p111[0]["playerName"] == "Reactivated"
    assert len(p222) == 1 and p222[0]["playerName"] == "Other"


def test_respects_interval(tmp_path, monkeypatch):
    import time
    world = {"players": [], "islands": [{"islandId": "111", "x": 40, "y": 50}]}
    marks = {"9_40_50": {"status": "alvo", "island_x": "40", "island_y": "50"}}
    _setup(tmp_path, {"enabled": True, "intervalHours": 12}, marks, world)
    with open(sc.WATCHLIST_STATE_PATH, "w") as f:
        json.dump({"lastRun": int(time.time()) - 60}, f)   # 1 min ago < 12h
    scanned = []
    monkeypatch.setattr(sc, "_scan_one_island", lambda *a, **k: scanned.append(1) or None)
    sc.process_watchlist(session=object(), in_active_hours=True)
    assert scanned == []


# ── Editable world-scan radius ────────────────────────────────────────────────

def test_scan_radius_reads_setting_with_env_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(sc, "WORLD_SCAN_RADIUS", 10)
    settings = tmp_path / "world_scan_settings.json"
    assert sc._scan_radius() == 10                          # no file → env default
    settings.write_text('{"enabled": true, "radius": 22}')
    assert sc._scan_radius() == 22                          # configured value wins
    settings.write_text('{"radius": 999}')
    assert sc._scan_radius() == 60                          # clamped to the maximum
    settings.write_text('{"radius": 0}')
    assert sc._scan_radius() == 1                           # clamped to the minimum
    settings.write_text('{"radius": "abc"}')
    assert sc._scan_radius() == 10                          # junk → env default
    settings.write_text("not json")
    assert sc._scan_radius() == 10


# ── P13.16: a running scan is laid over the previous one; failed islands are retried ──

def _scan_env(tmp_path, monkeypatch, queue, prev_players, prev_islands, results):
    """results: {island_id: (island_entry, players) | None | [first, second, ...]}"""
    monkeypatch.setattr(sc, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(sc, "SCAN_CHECKPOINT_PATH", str(tmp_path / "checkpoint.json"))
    monkeypatch.setattr(sc.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(sc, "_write_scan_status", lambda *a, **k: None)
    monkeypatch.setattr(db_manager, "save_scan_timestamp", lambda ts: None, raising=False)
    (tmp_path / "world_scan_prev.json").write_text(json.dumps(
        {"players": prev_players, "islands": prev_islands}))
    cp = {"startedAt": 1, "ownCities": [{"name": "Home", "x": 1, "y": 1}],
          "islandsQueue": queue, "totalIslands": len(queue), "radius": 5,
          "players": [], "islands": []}
    (tmp_path / "checkpoint.json").write_text(json.dumps(cp))
    calls = []

    def fake_one(session, island_id, x, y, own, resource_type=0):
        calls.append(str(island_id))
        r = results[str(island_id)]
        if isinstance(r, list):
            r = r.pop(0)
        return r
    monkeypatch.setattr(sc, "_scan_one_island", fake_one)
    return calls


def _isl(i):
    return {"id": i, "x": 1, "y": 2, "name": "I%s" % i, "resource_type": 1, "players": 3}


def _entry(i, city):
    return ({"islandId": str(i), "islandName": "I%s" % i},
            [{"islandId": str(i), "cityId": city, "state": "inactive"}])


def _published(tmp_path):
    return json.loads((tmp_path / "world_scan.json").read_text())


def test_running_scan_keeps_previous_entries_of_islands_not_yet_read(tmp_path, monkeypatch):
    prev_players = [{"islandId": "1", "cityId": "old1"}, {"islandId": "2", "cityId": "old2"}]
    prev_islands = [{"islandId": "1"}, {"islandId": "2"}]
    _scan_env(tmp_path, monkeypatch, [_isl(1), _isl(2)], prev_players, prev_islands,
              {"1": _entry(1, "new1"), "2": _entry(2, "new2")})

    assert sc.scan_next_island(None) is True
    mid = _published(tmp_path)
    assert mid["scanInProgress"] is True
    assert sorted(p["cityId"] for p in mid["players"]) == ["new1", "old2"]   # nothing vanished

    assert sc.scan_next_island(None) is False
    end = _published(tmp_path)
    assert end["scanInProgress"] is False
    assert sorted(p["cityId"] for p in end["players"]) == ["new1", "new2"]


def test_failed_island_is_retried_then_keeps_its_previous_entries(tmp_path, monkeypatch):
    prev_players = [{"islandId": "1", "cityId": "old1"}, {"islandId": "9", "cityId": "gone"}]
    calls = _scan_env(tmp_path, monkeypatch, [_isl(1), _isl(2)], prev_players,
                      [{"islandId": "1"}, {"islandId": "9"}],
                      {"1": [None, None], "2": _entry(2, "new2")})
    while sc.scan_next_island(None):
        pass
    assert calls == ["1", "2", "1"]                       # went back to the end of the queue once
    end = _published(tmp_path)
    assert end["failedIslands"] == ["1"]
    # island 1 keeps what we knew; island 9 (no longer in range) is dropped
    assert sorted(p["cityId"] for p in end["players"]) == ["new2", "old1"]
    assert sorted(i["islandId"] for i in end["islands"]) == ["1", "2"]


def test_island_that_recovers_on_retry_is_not_marked_failed(tmp_path, monkeypatch):
    _scan_env(tmp_path, monkeypatch, [_isl(1)], [{"islandId": "1", "cityId": "old1"}], [],
              {"1": [None, _entry(1, "new1")]})
    while sc.scan_next_island(None):
        pass
    end = _published(tmp_path)
    assert end["failedIslands"] == [] and [p["cityId"] for p in end["players"]] == ["new1"]
