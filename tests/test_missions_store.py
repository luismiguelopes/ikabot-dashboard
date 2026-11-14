"""
P13.11: spy missions live in SQLite (one row each) and are MERGED on save.

Before, spy_missions.json was rewritten whole by the bot (which holds the list in memory for
minutes while it works) and by the dashboard (on a click): the last save erased the other's
change, and a read that caught the file mid-write came back empty and was then saved.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_manager


def _db(monkeypatch, tmp_path):
    monkeypatch.setattr(db_manager, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(db_manager, "_LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "_DB_INIT_DONE", False)


def _seed(n=2):
    db_manager.missions_save({"missions": [
        {"targetCityId": str(100 + i), "state": "WAITING_AT_CITY", "executeAfter": 500}
        for i in range(n)]})
    return db_manager.missions_load()


def _by_target():
    return {m["targetCityId"]: m for m in db_manager.missions_load()["missions"]}


def test_roundtrip_keeps_order_and_assigns_ids(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    data = _seed(3)
    assert [m["targetCityId"] for m in data["missions"]] == ["100", "101", "102"]
    assert len({m["id"] for m in data["missions"]}) == 3


def test_bot_and_dashboard_changing_different_missions_both_survive(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    bot = _seed()                                   # bot loads, then works for minutes
    gui = db_manager.missions_load()                # dashboard: "force warehouse" on mission 101
    gui["missions"][1]["executeAfter"] = 1
    db_manager.missions_save(gui)
    bot["missions"][0]["state"] = "EXECUTING_WAREHOUSE"
    db_manager.missions_save(bot)                   # stale copy of mission 101 inside
    got = _by_target()
    assert got["100"]["state"] == "EXECUTING_WAREHOUSE"
    assert got["101"]["executeAfter"] == 1          # used to be reverted to 500


def test_same_mission_different_fields_are_merged(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    bot = _seed(1)
    gui = db_manager.missions_load()
    gui["missions"][0]["executeAfter"] = 1          # dashboard touches one field…
    db_manager.missions_save(gui)
    bot["missions"][0]["spySessionId"] = "SID"      # …the bot another
    db_manager.missions_save(bot)
    m = _by_target()["100"]
    assert (m["executeAfter"], m["spySessionId"]) == (1, "SID")


def test_mission_added_meanwhile_is_not_deleted_by_a_stale_save(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    bot = _seed(1)
    other = db_manager.missions_load()
    other["missions"].append({"targetCityId": "999", "state": "TRAVELING"})
    db_manager.missions_save(other)
    bot["missions"][0]["state"] = "DONE"
    db_manager.missions_save(bot)
    assert set(_by_target()) == {"100", "999"}


def test_removed_by_caller_is_deleted_and_not_resurrected(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    bot = _seed(2)
    pruner = db_manager.missions_load()
    pruner["missions"] = pruner["missions"][:1]     # prunes mission 101
    db_manager.missions_save(pruner)
    bot["missions"][1]["state"] = "DONE"            # stale edit of the pruned one
    db_manager.missions_save(bot)
    assert set(_by_target()) == {"100"}


def test_failed_read_cannot_wipe_the_store(monkeypatch, tmp_path):
    """espionage_manager._load_missions returns an empty list + EMPTY snapshot when the read
    fails; saving that must delete nothing (the old code wrote the empty list to disk)."""
    _db(monkeypatch, tmp_path)
    _seed(2)
    db_manager.missions_save({"missions": [], "_base": {}})
    assert len(db_manager.missions_load()["missions"]) == 2


def test_legacy_json_is_imported_once_and_renamed(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    legacy = tmp_path / "spy_missions.json"
    legacy.write_text(json.dumps({"missions": [{"targetCityId": "7", "state": "DONE"},
                                               {"targetCityId": "8", "state": "FAILED"}]}))
    assert [m["targetCityId"] for m in db_manager.missions_load()["missions"]] == ["7", "8"]
    assert not legacy.exists() and (tmp_path / "spy_missions.json.migrated").exists()


def test_half_written_legacy_file_is_left_for_the_next_start(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path)
    legacy = tmp_path / "spy_missions.json"
    legacy.write_text('{"missions": [{"targetCit')
    assert db_manager.missions_load()["missions"] == []
    assert legacy.exists()                          # not renamed, nothing imported
