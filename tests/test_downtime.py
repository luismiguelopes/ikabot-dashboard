"""
B7: downtime-aware timeouts. active_elapsed() discounts recorded offline windows from
wall-clock elapsed, so espionage timeouts don't fire on time the bot spent down;
record_startup_downtime() logs the gap when the bot resumes.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import empire_utils as eu


def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(eu, "DOWNTIME_WINDOWS_PATH", str(tmp_path / "dt.json"))
    monkeypatch.setattr(eu, "LAST_ALIVE_JSON_PATH", str(tmp_path / "la.json"))
    eu._dt_cache["windows"] = None
    eu._dt_cache["ts"] = 0.0


def _windows(tmp_path, ws):
    (tmp_path / "dt.json").write_text(json.dumps(ws))


def test_active_elapsed_no_downtime(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    now = 100000
    assert eu.active_elapsed(now - 3600, now) == 3600


def test_active_elapsed_discounts_window_inside(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    now, since = 100000, 100000 - 3600
    _windows(tmp_path, [{"start": since + 600, "end": since + 1200}])   # 600s offline
    assert eu.active_elapsed(since, now) == 3600 - 600


def test_active_elapsed_partial_overlap(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    now, since = 100000, 100000 - 3600
    _windows(tmp_path, [{"start": since - 500, "end": since + 900}])    # only 900s overlaps
    assert eu.active_elapsed(since, now) == 3600 - 900


def test_active_elapsed_window_outside_is_ignored(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    now, since = 100000, 100000 - 3600
    _windows(tmp_path, [{"start": since - 5000, "end": since - 1000},    # entirely before
                        {"start": now + 100, "end": now + 500}])         # entirely after
    assert eu.active_elapsed(since, now) == 3600


def test_active_elapsed_downtime_saves_a_mission(monkeypatch, tmp_path):
    """The Polis case: 12h timeout must not fire when 50h of the 51h elapsed was downtime."""
    _reset(monkeypatch, tmp_path)
    now = 1_000_000
    dispatched = now - 51 * 3600
    _windows(tmp_path, [{"start": dispatched + 3600, "end": dispatched + 51 * 3600}])  # 50h down
    assert eu.active_elapsed(dispatched, now) == 3600          # only 1h of real activity
    assert eu.active_elapsed(dispatched, now) < 43200          # below the 12h timeout


def test_record_startup_downtime_records_gap(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    now = int(time.time())
    (tmp_path / "la.json").write_text(json.dumps({"lastAlive": now - 7200}))   # 2h ago
    eu.record_startup_downtime()
    ws = json.loads((tmp_path / "dt.json").read_text())
    assert len(ws) == 1 and ws[0]["start"] == now - 7200


def test_record_startup_downtime_ignores_small_gap(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    now = int(time.time())
    (tmp_path / "la.json").write_text(json.dumps({"lastAlive": now - 60}))     # 1 min
    eu.record_startup_downtime()
    assert not os.path.exists(str(tmp_path / "dt.json"))
