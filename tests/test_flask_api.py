"""
P6.12: tests for the Flask API (ikabot_gui/app.py) — the endpoints whose logic lives in
the Flask layer itself (thresholds, settings merge, marks, activity aggregation, farm
unignore, SPA serving). Uses app.test_client() with every file path pointed at tmp.
"""
import json
import os
import sys
import time
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Stub telegram_notifier before anything imports it
_tg_stub = types.ModuleType("telegram_notifier")
sys.modules.setdefault("telegram_notifier", _tg_stub)

# Import the REAL db_manager (repo root) before app.py prepends ikabot_gui/ to sys.path:
# that dir holds 0-byte db_manager.py/telegram_notifier.py docker mountpoint artifacts,
# and the sys.modules cache is what keeps app.py's own import bound to the real module.
import db_manager

sys.path.insert(0, os.path.join(_ROOT, "ikabot_gui"))
import app as flask_app


def _client(monkeypatch, tmp_path):
    """Point every path constant the tested endpoints use at tmp, plus a fresh DB."""
    db_manager.DB_PATH = str(tmp_path / "test.db")
    db_manager._LOGS_DIR = str(tmp_path)
    db_manager._DB_INIT_DONE = False
    monkeypatch.setattr(flask_app, "_db", db_manager)
    monkeypatch.setattr(flask_app, "LOGS_DIR", str(tmp_path))
    for const in ("ALERT_THRESHOLDS_PATH", "ESPIONAGE_SETTINGS_PATH",
                  "WORLD_SCAN_JSON_PATH", "PLAYER_MARKS_JSON_PATH",
                  "TRAVEL_CALIBRATION_PATH"):
        monkeypatch.setattr(flask_app, const,
                            str(tmp_path / os.path.basename(getattr(flask_app, const))))
    flask_app.app.config["TESTING"] = True
    return flask_app.app.test_client()


# ── /api/alert-thresholds (P6.4) ─────────────────────────────────────────────

def test_alert_thresholds_defaults_then_roundtrip(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    d = c.get("/api/alert-thresholds").get_json()
    assert d["configured"] is False and d["wineWarning"] == 8

    c.post("/api/alert-thresholds", json={"wineWarning": 15, "wineCritical": 3,
                                          "storageWarning": 90})
    d = c.get("/api/alert-thresholds").get_json()
    assert d["configured"] is True
    assert (d["wineWarning"], d["wineCritical"], d["storageWarning"]) == (15, 3, 90)


def test_alert_thresholds_bad_values_fall_back(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post("/api/alert-thresholds", json={"wineWarning": "abc", "storageWarning": -5})
    d = c.get("/api/alert-thresholds").get_json()
    assert d["wineWarning"] == 8        # unparsable → default
    assert d["storageWarning"] == 0     # negative → clamped


# ── /api/espionage/settings (minLootTotal moved here on auto-attack retirement) ──

def test_espionage_settings_roundtrip_with_min_loot(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    d = c.get("/api/espionage/settings").get_json()
    assert d["minLootTotal"] == 50000   # default present even without a file

    c.post("/api/espionage/settings", json={"garrisonThresholdTotal": 12000,
                                            "minLootTotal": 60000})
    d = c.get("/api/espionage/settings").get_json()
    assert d["garrisonThresholdTotal"] == 12000 and d["minLootTotal"] == 60000

    # partial POST must not clobber the other key
    c.post("/api/espionage/settings", json={"garrisonThresholdTotal": 15000})
    d = c.get("/api/espionage/settings").get_json()
    assert d["garrisonThresholdTotal"] == 15000 and d["minLootTotal"] == 60000


# ── /api/travel-calibration (P6.7) ───────────────────────────────────────────

def test_travel_calibration_empty_then_served(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/api/travel-calibration").get_json() == {}
    (tmp_path / "travel_calibration.json").write_text(
        json.dumps({"troop": {"ratio": 0.85, "samples": 4}}))
    d = c.get("/api/travel-calibration").get_json()
    assert d["troop"]["ratio"] == 0.85


# ── /api/activity (P6.8) ─────────────────────────────────────────────────────

def test_activity_aggregates_queues_flags_and_log(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    db_manager.queue_add("attack", {"targetCityName": "Alvo", "queuedAt": 111,
                                    "dispatchAfter": int(time.time()) + 600})
    (tmp_path / ".force_world_scan").touch()
    db_manager.log_attack({"originCity": "Base", "targetCity": "Alvo",
                           "targetPlayer": "X", "missionType": "army",
                           "source": "manual", "units": {}, "success": True})
    d = c.get("/api/activity").get_json()
    assert [p["label"] for p in d["pending"]] == ["Alvo"]
    assert [f["kind"] for f in d["flags"]] == ["world_scan"]
    assert d["recent"][0]["target_city"] == "Alvo" and d["recent"][0]["success"] is True


# ── /api/world-scan/mark + farm re-enable unignore ───────────────────────────

def _seed_scan(tmp_path, city_id="100", player_id="77", x=40, y=50):
    scan = {"players": [{"playerId": player_id, "cityId": city_id, "playerName": "P",
                         "cityName": "C", "islandX": x, "islandY": y,
                         "state": "inactive"}]}
    (tmp_path / "world_scan.json").write_text(json.dumps(scan))


def test_mark_post_saves_to_db(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post("/api/world-scan/mark", json={"playerId": "77", "islandX": 40,
                                             "islandY": 50, "status": "ignorar",
                                             "note": "teste"})
    assert r.get_json()["ok"] is True
    assert db_manager.get_all_marks()["77_40_50"]["status"] == "ignorar"


def test_farm_reenable_clears_ignore_mark(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed_scan(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "C",
                         "islandX": 40, "islandY": 50, "islandId": "7"})
    db_manager.farm_update("100", {"enabled": 0})
    db_manager.save_mark("77_40_50", "77", "40", "50", "ignorar", "Drenado pelo farm")

    r = c.post("/api/farm/update", json={"targetCityId": "100", "enabled": True})
    assert r.get_json()["ok"] is True
    assert db_manager.get_all_marks()["77_40_50"]["status"] == "novo"
    assert db_manager.farm_get("100")["enabled"] is True


def test_farm_reenable_keeps_other_marks(monkeypatch, tmp_path):
    """Only 'ignorar' marks are cleared — an 'alvo' mark must survive a re-enable."""
    c = _client(monkeypatch, tmp_path)
    _seed_scan(tmp_path)
    db_manager.farm_add({"targetCityId": "100", "targetCityName": "C",
                         "islandX": 40, "islandY": 50, "islandId": "7"})
    db_manager.save_mark("77_40_50", "77", "40", "50", "alvo", "importante")
    c.post("/api/farm/update", json={"targetCityId": "100", "enabled": True})
    assert db_manager.get_all_marks()["77_40_50"]["status"] == "alvo"


# ── SPA serving (P6.11) ──────────────────────────────────────────────────────

def test_spa_serving_and_fallback(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>SPA</html>")
    (dist / "app.js").write_text("js")
    monkeypatch.setattr(flask_app, "FRONTEND_DIST", str(dist))

    assert b"SPA" in c.get("/").data
    assert c.get("/app.js").data == b"js"
    assert b"SPA" in c.get("/mundo").data            # SPA route → index fallback
    assert c.get("/api/nao-existe").status_code == 404
