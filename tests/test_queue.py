"""
Unit tests for queue_processor pure functions.
Run with: python -m pytest tests/ -v
"""
import math
import sys
import os
import types

# ── Stub out ikabot imports so tests run without the full ikabot package ──────
for mod in [
    "ikabot", "ikabot.config", "ikabot.helpers", "ikabot.helpers.getJson",
    "ikabot.helpers.naval", "ikabot.helpers.pedirInfo",
    "ikabot.function", "ikabot.function.constructionList",
]:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

# Provide the constants empire_utils needs from ikabot.config
sys.modules["ikabot.config"].materials_names_english = [
    "Wood", "Wine", "Marble", "Crystal", "Sulfur"
]
sys.modules["ikabot.config"].materials_names_tec = [
    "wood", "wine", "marble", "glass", "sulfur"
]
sys.modules["ikabot.config"].materials_names = [
    "Madeira", "Vinho", "Mármore", "Cristal", "Enxofre"
]
sys.modules["ikabot.config"].actionRequest = "TEST"

sys.modules["ikabot.helpers.getJson"].getCity   = lambda html: {}
sys.modules["ikabot.helpers.getJson"].getIsland  = lambda html: {}
sys.modules["ikabot.helpers.naval"].getAvailableShips      = lambda s: 10
sys.modules["ikabot.helpers.naval"].getAvailableFreighters = lambda s: 0
sys.modules["ikabot.helpers.pedirInfo"].getShipCapacity    = lambda s: (5000, 25000)
sys.modules["ikabot.function.constructionList"].expandBuilding     = lambda *a, **k: None
sys.modules["ikabot.function.constructionList"].getCostsReducers   = lambda *a: [0]*5
sys.modules["ikabot.function.constructionList"].checkhash          = lambda x: "wood"
sys.modules["ikabot.function.constructionList"].getResourcesNeeded = lambda *a: None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import only the pure functions we can test without a live session
from queue_processor import _build_send_list


# ── _build_send_list ──────────────────────────────────────────────────────────

def test_build_send_list_exact_fit():
    surplus   = [10000, 0, 5000, 0, 0]
    remaining = [10000, 0, 5000, 0, 0]
    send, ships = _build_send_list(surplus, remaining, ship_cap=5000, ships_available=10)
    assert send == [10000, 0, 5000, 0, 0]
    assert ships == 3  # ceil(15000/5000)


def test_build_send_list_rounds_up_to_thousand():
    # to_send = min(surplus, remaining) = 7500 → ceil(7500/1000)*1000 = 8000
    # but then capped at surplus (7500) → stays 7500 (no rounding down past surplus)
    surplus   = [8000, 0, 0, 0, 0]
    remaining = [7500, 0, 0, 0, 0]
    send, ships = _build_send_list(surplus, remaining, ship_cap=5000, ships_available=10)
    assert send[0] % 1000 == 0
    assert send[0] >= 7000


def test_build_send_list_capacity_constrained():
    surplus   = [50000, 0, 0, 0, 0]
    remaining = [50000, 0, 0, 0, 0]
    send, ships = _build_send_list(surplus, remaining, ship_cap=5000, ships_available=3)
    assert ships == 3
    assert sum(send) <= 3 * 5000


def test_build_send_list_nothing_to_send():
    surplus   = [0, 0, 0, 0, 0]
    remaining = [5000, 0, 0, 0, 0]
    send, ships = _build_send_list(surplus, remaining, ship_cap=5000, ships_available=5)
    assert ships == 0
    assert sum(send) == 0


def test_build_send_list_caps_at_remaining():
    surplus   = [20000, 0, 0, 0, 0]
    remaining = [3000, 0, 0, 0, 0]
    send, ships = _build_send_list(surplus, remaining, ship_cap=5000, ships_available=10)
    assert send[0] <= surplus[0]
    assert send[0] >= remaining[0]  # rounds up, not down past remaining


def test_build_send_list_multi_resource():
    surplus   = [5000, 0, 5000, 0, 2000]
    remaining = [5000, 0, 5000, 0, 2000]
    send, ships = _build_send_list(surplus, remaining, ship_cap=5000, ships_available=10)
    assert send[0] == 5000
    assert send[2] == 5000
    assert send[4] == 2000
    assert ships == math.ceil(12000 / 5000)


# ── Missing resources calculation (inline, mirrors queue_processor logic) ─────

def _calc_missing(cost, available, buf):
    """Mirrors the missing calculation in _try_transport."""
    return [max(0, cost[i] + (buf[i] if cost[i] > 0 else 0) - available[i]) for i in range(5)]


def test_missing_no_wine_cost_ignores_wine_buffer():
    cost      = [10000, 0, 5000, 0, 0]    # wall — no wine needed
    available = [15000, 20000, 3000, 0, 0]
    buf       = [0, 30000, 0, 0, 0]       # 30k wine buffer
    missing   = _calc_missing(cost, available, buf)
    assert missing[1] == 0, "wine buffer must not trigger transport when construction costs 0 wine"
    assert missing[2] == 2000  # marble is short


def test_missing_wine_cost_applies_buffer():
    cost      = [0, 5000, 0, 0, 0]        # something that costs wine
    available = [0, 28000, 0, 0, 0]
    buf       = [0, 30000, 0, 0, 0]
    missing   = _calc_missing(cost, available, buf)
    # needs 5000 + 30000 buffer − 28000 available = 7000
    assert missing[1] == 7000


def test_missing_all_available():
    cost      = [10000, 5000, 3000, 0, 0]
    available = [50000, 50000, 50000, 0, 0]
    buf       = [5000, 5000, 5000, 0, 0]
    missing   = _calc_missing(cost, available, buf)
    assert missing == [0, 0, 0, 0, 0]


def test_need_transport_only_for_used_resources():
    cost_check = [10000, 0, 0, 0, 0]
    avail      = [50000, 10000, 0, 0, 0]  # plenty of wood, wine below 30k buffer
    buf        = [0, 30000, 0, 0, 0]
    # wine has cost=0, so buffer check on wine must NOT trigger transport
    need = any(cost_check[i] > 0 and avail[i] - cost_check[i] < buf[i] for i in range(5))
    assert need is False  # wood fine (50k-10k=40k ≥ 0), wine skipped (cost=0)
    # if wood also has a buffer and wood becomes short
    buf2   = [5000, 30000, 0, 0, 0]
    avail2 = [12000, 10000, 0, 0, 0]
    need2 = any(cost_check[i] > 0 and avail2[i] - cost_check[i] < buf2[i] for i in range(5))
    assert need2 is True  # 12000 - 10000 = 2000 < 5000 buffer


# ── with_retry ────────────────────────────────────────────────────────────────

from empire_utils import with_retry


def test_with_retry_succeeds_on_first_try():
    calls = []
    def fn():
        calls.append(1)
        return "ok"
    result = with_retry(fn, attempts=3, delay=0)
    assert result == "ok"
    assert len(calls) == 1


def test_with_retry_retries_on_failure():
    calls = []
    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("transient")
        return "ok"
    result = with_retry(fn, attempts=3, delay=0)
    assert result == "ok"
    assert len(calls) == 3


def test_with_retry_raises_after_exhausting():
    def fn():
        raise ValueError("permanent")
    try:
        with_retry(fn, attempts=2, delay=0)
        assert False, "should have raised"
    except ValueError:
        pass
