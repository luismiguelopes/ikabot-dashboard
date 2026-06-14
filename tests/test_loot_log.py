"""
Tests for the loot log (F1.b) — db_manager.log_loot / get_loot_log / get_loot_stats.
Run with: python -m pytest tests/ -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_manager


def _setup(tmp_path):
    db_manager.DB_PATH = str(tmp_path / "loot.db")
    db_manager._LOGS_DIR = str(tmp_path)
    db_manager._DB_INIT_DONE = False


def test_log_and_get_loot(tmp_path):
    _setup(tmp_path)
    db_manager.log_loot({
        "ts": 1000, "fromCity": "AlvoCity", "fromPlayer": "JogadorX", "toCity": "Baphomet",
        "resources": [50000, 0, 12000, 0, 3000], "returnKey": "k1",
    })
    log = db_manager.get_loot_log()
    assert len(log) == 1
    assert log[0]["from_player"] == "JogadorX"
    assert log[0]["wood"] == 50000
    assert log[0]["marble"] == 12000


def test_dedup_by_return_key(tmp_path):
    _setup(tmp_path)
    entry = {"ts": 1000, "fromPlayer": "X", "resources": [1000, 0, 0, 0, 0], "returnKey": "same"}
    db_manager.log_loot(entry)
    db_manager.log_loot(entry)  # same return seen again next cycle → ignored
    assert len(db_manager.get_loot_log()) == 1


def test_loot_stats_aggregates_by_player(tmp_path):
    _setup(tmp_path)
    db_manager.log_loot({"ts": 1, "fromPlayer": "X", "resources": [10000, 0, 0, 0, 0], "returnKey": "a"})
    db_manager.log_loot({"ts": 5, "fromPlayer": "X", "resources": [0, 0, 5000, 0, 0], "returnKey": "b"})
    db_manager.log_loot({"ts": 3, "fromPlayer": "Y", "resources": [2000, 0, 0, 0, 0], "returnKey": "c"})
    stats = db_manager.get_loot_stats()
    assert stats[0]["from_player"] == "X"          # sorted by total desc
    assert stats[0]["total"] == 15000
    assert stats[0]["raids"] == 2
    assert stats[0]["last_ts"] == 5
    assert stats[1]["from_player"] == "Y"
    assert stats[1]["total"] == 2000


def test_loot_log_filter_by_target(tmp_path):
    _setup(tmp_path)
    db_manager.log_loot({"ts": 1, "fromCity": "AlvoCity", "fromPlayer": "X", "resources": [1, 0, 0, 0, 0], "returnKey": "a"})
    db_manager.log_loot({"ts": 2, "fromCity": "Outra", "fromPlayer": "Y", "resources": [1, 0, 0, 0, 0], "returnKey": "b"})
    assert len(db_manager.get_loot_log(target="alvo")) == 1
    assert len(db_manager.get_loot_log(target="outra")) == 1
    assert db_manager.get_loot_log(target="zzz") == []
