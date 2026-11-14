"""
F1: the farm must predict a target's drainage from real returns and stop before the
wasteful last raid. _estimated_warehouse = scouted last_loot minus loot brought home
since that scout, so a drained target reads below min_loot and gets re-scouted instead
of raided on stale intel.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("telegram_notifier", types.ModuleType("telegram_notifier"))

import db_manager
import farm_manager as fm


def _row(ts, city, total):
    return {"ts": ts, "from_city": city, "wood": total, "wine": 0,
            "marble": 0, "crystal": 0, "sulfur": 0}


def test_returned_since_scout_counts_only_raids_after_the_scout(monkeypatch):
    rows = [
        _row(200, "Target", 15000),   # after scout → counts
        _row(150, "Target", 30000),   # after scout → counts
        _row(50,  "Target", 99999),   # before scout → excluded
        _row(300, "Other",  99999),   # wrong city  → excluded
    ]
    monkeypatch.setattr(db_manager, "get_loot_log", lambda limit=30, target=None: rows)
    t = {"last_spy_at": 100, "target_city_name": "Target"}
    assert fm._returned_since_scout(t) == 45000


def test_returned_since_scout_zero_without_scout(monkeypatch):
    monkeypatch.setattr(db_manager, "get_loot_log", lambda limit=30, target=None: [_row(200, "Target", 9)])
    assert fm._returned_since_scout({"last_spy_at": 0, "target_city_name": "Target"}) == 0


def test_estimated_warehouse_subtracts_looted(monkeypatch):
    monkeypatch.setattr(db_manager, "get_loot_log",
                        lambda limit=30, target=None: [_row(200, "Target", 45000)])
    t = {"last_spy_at": 100, "target_city_name": "Target", "last_loot": 200000}
    assert fm._estimated_warehouse(t) == 155000        # 200k scouted − 45k taken


def test_estimated_warehouse_never_negative(monkeypatch):
    monkeypatch.setattr(db_manager, "get_loot_log",
                        lambda limit=30, target=None: [_row(200, "Target", 45000)])
    t = {"last_spy_at": 100, "target_city_name": "Target", "last_loot": 20000}
    assert fm._estimated_warehouse(t) == 0             # drained past empty → clamped


def test_estimated_warehouse_equals_scouted_when_fresh(monkeypatch):
    """Right after a scout (no returns yet) the estimate is exactly the scouted warehouse."""
    monkeypatch.setattr(db_manager, "get_loot_log", lambda limit=30, target=None: [])
    t = {"last_spy_at": 100, "target_city_name": "Target", "last_loot": 268000}
    assert fm._estimated_warehouse(t) == 268000


def test_drained_target_reads_below_min_loot(monkeypatch):
    """The F1 case: scouted loot still looks rich (268k) but we've taken 250k, so the
    estimate (18k) is below a 50k bar — the raid gate must see it as drained."""
    monkeypatch.setattr(db_manager, "get_loot_log",
                        lambda limit=30, target=None: [_row(200, "Target", 250000)])
    t = {"last_spy_at": 100, "target_city_name": "Target", "last_loot": 268000}
    est = fm._estimated_warehouse(t)
    assert est == 18000 and est < 50000


# ── Exact target matching (ids, not name substrings) ────────────────────────────
# "Castle-V" is a substring of "Castle-VII", and one player owns several targets: matching
# by substring / by player made a target adopt another target's loot and return time.

def test_loot_of_a_longer_named_sibling_is_not_counted(monkeypatch):
    rows = [dict(_row(200, "Castle-VII", 207000), from_player="RxDxR"),
            dict(_row(210, "Castle-VIII", 150000), from_player="RxDxR")]
    monkeypatch.setattr(db_manager, "get_loot_log", lambda limit=30, target=None: rows)
    t = {"target_city_id": "5", "target_city_name": "Castle-V", "target_player": "RxDxR",
         "last_spy_at": 100, "last_attack_at": 100}
    assert fm._returned_since_scout(t) == 0
    assert fm._recent_return_loot(t) is None


def test_loot_row_with_city_id_matches_by_id_only(monkeypatch):
    rows = [dict(_row(200, "Renamed", 1000), from_city_id="5"),       # same id, renamed city
            dict(_row(210, "Castle-V", 5000), from_city_id="99")]     # same name, other city
    monkeypatch.setattr(db_manager, "get_loot_log", lambda limit=30, target=None: rows)
    t = {"target_city_id": "5", "target_city_name": "Castle-V", "last_spy_at": 100}
    assert fm._returned_since_scout(t) == 1000


def test_same_name_other_player_is_not_counted(monkeypatch):
    rows = [dict(_row(200, "Polis", 9000), from_player="Copinho")]
    monkeypatch.setattr(db_manager, "get_loot_log", lambda limit=30, target=None: rows)
    t = {"target_city_id": "7", "target_city_name": "Polis", "target_player": "Darkness",
         "last_spy_at": 100}
    assert fm._returned_since_scout(t) == 0


def _movements(monkeypatch, tmp_path, rows):
    import json
    path = tmp_path / "movements.json"
    path.write_text(json.dumps(rows))
    monkeypatch.setattr(fm, "MOVEMENTS_PATH", str(path))


def test_return_eta_ignores_other_targets_of_the_same_player(monkeypatch, tmp_path):
    _movements(monkeypatch, tmp_path, [
        {"isOwn": True, "direction": "<-", "arrivalTime": 500,
         "origin": "Home (Me)", "destination": "Tróia 5 (MARCOS LIMA)"},
    ])
    t3 = {"target_city_id": "3", "target_city_name": "Tróia 3", "target_player": "MARCOS LIMA"}
    t5 = {"target_city_id": "5", "target_city_name": "Tróia 5", "target_player": "MARCOS LIMA"}
    assert fm._real_return_eta(t3) is None
    assert fm._raid_in_flight(t3) is False
    assert fm._real_return_eta(t5) == 500
    assert fm._raid_in_flight(t5) is True


def test_movement_city_id_wins_over_names(monkeypatch, tmp_path):
    _movements(monkeypatch, tmp_path, [
        {"isOwn": True, "direction": "<-", "arrivalTime": 700, "targetCityId": "8",
         "origin": "Home (Me)", "destination": "Castle-V (RxDxR)"},
    ])
    assert fm._real_return_eta({"target_city_id": "5", "target_city_name": "Castle-V",
                                "target_player": "RxDxR"}) is None
    assert fm._real_return_eta({"target_city_id": "8", "target_city_name": "Old name",
                                "target_player": "RxDxR"}) == 700


def test_attack_was_sent_ignores_a_sibling_dispatch(monkeypatch):
    rows = [{"ts": 1000, "success": 1, "target_city": "Castle-VII", "target_player": "RxDxR",
             "target_city_id": "7"}]
    monkeypatch.setattr(db_manager, "get_attack_log", lambda limit=50, target=None: rows)
    t = {"target_city_id": "5", "target_city_name": "Castle-V", "target_player": "RxDxR",
         "last_attack_at": 1000}
    assert fm._attack_was_sent(t) is False
    assert fm._attack_was_sent(dict(t, target_city_id="7", target_city_name="Castle-VII")) is True


def test_logs_store_the_city_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(db_manager, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(db_manager, "_LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "_DB_INIT_DONE", False)
    db_manager.log_loot({"ts": 1, "fromCity": "X", "fromCityId": "42", "fromPlayer": "P",
                         "resources": [1, 0, 0, 0, 0], "returnKey": "k"})
    db_manager.log_attack({"targetCity": "X", "targetCityId": "42", "success": True})
    assert db_manager.get_loot_log()[0]["from_city_id"] == "42"
    assert db_manager.get_attack_log()[0]["target_city_id"] == "42"


def test_renamed_city_and_siblings_against_the_real_log(tmp_path, monkeypatch):
    """Through the real DB (no stub): a renamed city is still found by id, and a flood of
    same-prefix sibling rows cannot push the target's own row out of the window."""
    monkeypatch.setattr(db_manager, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(db_manager, "_LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "_DB_INIT_DONE", False)
    db_manager.log_loot({"ts": 200, "fromCity": "Renamed", "fromCityId": "5", "fromPlayer": "RxDxR",
                         "resources": [1000, 0, 0, 0, 0], "returnKey": "own"})
    for i in range(40):
        db_manager.log_loot({"ts": 300 + i, "fromCity": "Castle-VII", "fromCityId": "7",
                             "fromPlayer": "RxDxR", "resources": [9, 0, 0, 0, 0],
                             "returnKey": "sib%d" % i})
    db_manager.log_attack({"ts": 150, "targetCity": "Renamed", "targetCityId": "5",
                           "targetPlayer": "RxDxR", "success": True})
    t = {"target_city_id": "5", "target_city_name": "Castle-V", "target_player": "RxDxR",
         "last_spy_at": 100, "last_attack_at": 150}
    assert fm._returned_since_scout(t) == 1000
    assert fm._recent_return_loot(t) == 1000
    assert fm._attack_was_sent(t) is True
