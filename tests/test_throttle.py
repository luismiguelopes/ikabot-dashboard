"""
Tests for the central anti-detection throttle (P5.3): ThrottledSession enforces a minimum
spacing between game requests, transparently delegating everything else to the wrapped session.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import empire_utils as eu


class _FakeSession:
    def __init__(self):
        self.calls = []
        self.attr = 42
    def get(self, *a, **k):
        self.calls.append(("get", a, k))
        return "GET_OK"
    def post(self, *a, **k):
        self.calls.append(("post", a, k))
        return "POST_OK"
    def setStatus(self, msg):
        self.calls.append(("setStatus", msg))
        return "status_set"


def _fake_clock(monkeypatch, start=1000.0):
    """Deterministic clock: sleep advances time; random jitter = 0 so floor == min_interval."""
    clock = [start]
    sleeps = []
    monkeypatch.setattr(eu.time, "time", lambda: clock[0])
    def _sleep(s):
        sleeps.append(s)
        clock[0] += s
    monkeypatch.setattr(eu.time, "sleep", _sleep)
    monkeypatch.setattr(eu.random, "uniform", lambda a, b: 0)
    return clock, sleeps


def test_get_post_delegate_and_return(monkeypatch):
    _fake_clock(monkeypatch)
    inner = _FakeSession()
    s = eu.ThrottledSession(inner)
    assert s.get("view=city") == "GET_OK"
    assert s.post(params={"x": 1}) == "POST_OK"
    assert inner.calls[0][0] == "get" and inner.calls[1][0] == "post"


def test_attribute_passthrough(monkeypatch):
    _fake_clock(monkeypatch)
    inner = _FakeSession()
    s = eu.ThrottledSession(inner)
    assert s.attr == 42                       # read delegates to inner
    assert s.setStatus("hi") == "status_set"  # method delegates
    s.newattr = "abc"                         # write delegates to inner
    assert inner.newattr == "abc"


def test_throttle_enforces_spacing(monkeypatch):
    clock, sleeps = _fake_clock(monkeypatch)
    inner = _FakeSession()
    s = eu.ThrottledSession(inner, min_interval=1.5, jitter=0)
    s.get("a")                       # first call: elapsed huge (last=0) → no sleep
    assert sleeps == []
    s.get("b")                       # immediate second call → must wait the floor
    assert sleeps == [1.5]


def test_throttle_no_wait_when_already_spaced(monkeypatch):
    clock, sleeps = _fake_clock(monkeypatch)
    inner = _FakeSession()
    s = eu.ThrottledSession(inner, min_interval=1.5, jitter=0)
    s.get("a")
    clock[0] += 10                   # 10s already elapsed (a real local sleep happened)
    s.get("b")
    assert sleeps == []              # floor already satisfied → no extra sleep


def test_throttle_session_idempotent(monkeypatch):
    monkeypatch.delenv("IKABOT_NO_THROTTLE", raising=False)
    inner = _FakeSession()
    once = eu.throttle_session(inner)
    twice = eu.throttle_session(once)
    assert isinstance(once, eu.ThrottledSession)
    assert twice is once             # wrapping a wrapped session returns it unchanged


def test_request_writes_heartbeat(monkeypatch, tmp_path):
    """Every game request refreshes last_alive.json so long work phases (building costs, world
    scan) don't let the container healthcheck false-restart the bot mid-work."""
    import json
    clock, _ = _fake_clock(monkeypatch)
    monkeypatch.setattr(eu, "LAST_ALIVE_JSON_PATH", str(tmp_path / "last_alive.json"))
    s = eu.ThrottledSession(_FakeSession())
    s.get("view=city")
    with open(tmp_path / "last_alive.json") as f:
        assert json.load(f)["lastAlive"] == int(clock[0])


def test_escape_hatch_disables_wrapping(monkeypatch):
    monkeypatch.setenv("IKABOT_NO_THROTTLE", "1")
    inner = _FakeSession()
    assert eu.throttle_session(inner) is inner
