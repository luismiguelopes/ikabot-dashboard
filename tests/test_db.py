"""
Unit tests for db_manager CRUD operations.
Uses a temporary SQLite DB so nothing touches the real /tmp/ikalogs/ikabot.db.
Run with: python -m pytest tests/ -v
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_manager

# ── Redirect DB to a temp file for isolation ─────────────────────────────────

def _setup_tmp_db(tmp_path):
    db_manager.DB_PATH = os.path.join(tmp_path, "test.db")
    db_manager._LOGS_DIR = tmp_path
    db_manager._DB_INIT_DONE = False


# ── Empire snapshot ───────────────────────────────────────────────────────────

def test_save_and_get_empire_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        ts = int(time.time())
        empire    = {"Lisboa": {"Academia": "12", "_constructionEnds": 0}}
        resources = {"Lisboa": {"Wood": 50000, "Wine": 30000, "wineRunsOutIn": 7200}}
        status    = {"gold": {"total": 100000, "production": 5000}}

        db_manager.save_empire_snapshot(ts, empire, resources, status)
        result = db_manager.get_empire_snapshot()

        assert result is not None
        written_at, emp, res, stat = result
        assert written_at == ts
        assert emp["Lisboa"]["Academia"] == "12"
        assert res["Lisboa"]["Wine"] == 30000
        assert stat["gold"]["total"] == 100000


def test_get_empire_snapshot_returns_none_when_empty():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        result = db_manager.get_empire_snapshot()
        assert result is None


def test_save_empire_snapshot_overwrites():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        db_manager.save_empire_snapshot(1, {"A": {}}, {"A": {}}, {})
        db_manager.save_empire_snapshot(2, {"B": {}}, {"B": {}}, {})
        result = db_manager.get_empire_snapshot()
        written_at, emp, _, _ = result
        assert written_at == 2
        assert "B" in emp


# ── History ───────────────────────────────────────────────────────────────────

def _make_status():
    return {
        "gold":            {"total": 500000, "production": 10000},
        "ships":           {"available": 100, "total": 200},
        "housing":         {"space": 5000, "citizens": 4000},
        "resources":       {"available": [100, 200, 300, 400, 500], "production": [10, 0, 20, 0, 0]},
        "wine_consumption": 150,
    }

def _make_resources():
    return {
        "Lisboa": {
            "Wood": 10000, "Wine": 5000, "Marble": 3000, "Crystal": 0, "Sulfur": 0,
            "wineRunsOutIn": 3600,
        }
    }


def test_insert_and_get_history_empire():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        ts = int(time.time())
        db_manager.insert_history(ts, _make_status(), _make_resources())
        rows = db_manager.get_history(days=7)
        assert len(rows) == 1
        assert rows[0]["gold"] == 500000
        assert rows[0]["wine_consumption"] == 150


def test_insert_and_get_history_city():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        ts = int(time.time())
        db_manager.insert_history(ts, _make_status(), _make_resources())
        rows = db_manager.get_history(days=7, city="Lisboa")
        assert len(rows) == 1
        assert rows[0]["wood"] == 10000
        assert rows[0]["wine"] == 5000
        assert rows[0]["wine_runs_out"] == 3600


def test_get_history_cities():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        res = {"Lisboa": {"Wood": 1, "Wine": 2, "Marble": 0, "Crystal": 0, "Sulfur": 0, "wineRunsOutIn": -1},
               "Porto":  {"Wood": 3, "Wine": 4, "Marble": 0, "Crystal": 0, "Sulfur": 0, "wineRunsOutIn": -1}}
        db_manager.insert_history(int(time.time()), _make_status(), res)
        cities = db_manager.get_history_cities()
        assert "Lisboa" in cities
        assert "Porto" in cities


# ── Marks ─────────────────────────────────────────────────────────────────────

def test_save_and_get_mark():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        db_manager.save_mark("12345_10_20", "12345", 10, 20, "alvo", "bom alvo")
        marks = db_manager.get_all_marks()
        assert "12345_10_20" in marks
        assert marks["12345_10_20"]["status"] == "alvo"
        assert marks["12345_10_20"]["note"] == "bom alvo"


def test_append_action():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        db_manager.save_mark("99_1_2", "99", 1, 2, "novo", "")
        db_manager.append_action("99_1_2", "99", 1, 2, "Enviado espião")
        db_manager.append_action("99_1_2", "99", 1, 2, "Ataque planeado")
        mark = db_manager.get_mark_with_actions("99_1_2")
        assert len(mark["actions"]) == 2
        assert mark["actions"][0]["text"] == "Enviado espião"


def test_save_mark_preserves_actions():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        db_manager.save_mark("1_1_1", "1", 1, 1, "novo", "nota inicial")
        db_manager.append_action("1_1_1", "1", 1, 1, "Acção 1")
        db_manager.save_mark("1_1_1", "1", 1, 1, "visto", "nota actualizada")
        mark = db_manager.get_mark_with_actions("1_1_1")
        assert mark["status"] == "visto"
        assert len(mark["actions"]) == 1  # action preserved


# ── Queue ─────────────────────────────────────────────────────────────────────

def _sample_queue():
    return {
        "enabled": True,
        "queues": {
            "Lisboa": [{"building": "Academia", "targetLevel": 15, "addedAt": 1000}]
        },
        "inProgress": {},
        "transportErrors": {},
    }


def test_save_and_load_queue():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        q = _sample_queue()
        db_manager.save_queue(q)
        loaded = db_manager.load_queue()
        assert loaded["enabled"] is True
        assert "Lisboa" in loaded["queues"]
        assert loaded["queues"]["Lisboa"][0]["building"] == "Academia"
        assert loaded["queues"]["Lisboa"][0]["targetLevel"] == 15


def test_queue_enabled_flag():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        q = _sample_queue()
        q["enabled"] = False
        db_manager.save_queue(q)
        loaded = db_manager.load_queue()
        assert loaded["enabled"] is False


def test_queue_in_progress():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        q = _sample_queue()
        q["inProgress"]["Lisboa"] = {
            "building": "Academia", "position": 3,
            "fromLevel": 14, "toLevel": 15,
            "startedAt": 1000, "eta": 2000,
        }
        db_manager.save_queue(q)
        loaded = db_manager.load_queue()
        ip = loaded["inProgress"]["Lisboa"]
        assert ip["building"] == "Academia"
        assert ip["eta"] == 2000


def test_queue_transport_errors():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        q = _sample_queue()
        q["transportErrors"]["Porto"] = {"failedAt": 999, "origin": "Lisboa", "resource": "wood"}
        db_manager.save_queue(q)
        loaded = db_manager.load_queue()
        assert "Porto" in loaded["transportErrors"]
        assert loaded["transportErrors"]["Porto"]["resource"] == "wood"
