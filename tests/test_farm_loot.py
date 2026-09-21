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
