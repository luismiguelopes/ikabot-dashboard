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
