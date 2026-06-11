"""
Unit tests for empire_collector._parse_unit_tab.
The cityMilitary response always contains BOTH sections (army then fleet) regardless
of the activeTab requested. Regression: fleet units were being paired with the army
count cells (first N <td>s of the page), e.g. Lança-Chamas showing the Hoplita count.
Run with: python -m pytest tests/ -v
"""
import os
import sys
import types

# ── Stub out ikabot imports so tests run without the full ikabot package ──────
for mod in [
    "ikabot", "ikabot.config", "ikabot.helpers", "ikabot.helpers.getJson",
]:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

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
if not hasattr(sys.modules["ikabot.helpers.getJson"], "getCity"):
    sys.modules["ikabot.helpers.getJson"].getCity = lambda html: {}

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from empire_collector import _parse_unit_tab


# Mirrors the real structure: army divs + army count row, then fleet divs + count row.
_CITY_MILITARY_HTML = """
<div class="army s303"><div class="tooltip">Hoplita</div></div>
<div class="army s302"><div class="tooltip">Espadachim</div></div>
<div class="army s301"><div class="tooltip">Fundeiro</div></div>
<table><tr><td>290</td><td>55</td><td>-</td></tr></table>
<div class="fleet s211"><div class="tooltip">Lança-Chamas</div></div>
<div class="fleet s210"><div class="tooltip">Trirreme</div></div>
<table><tr><td> 12</td><td> 7</td></tr></table>
"""


def test_army_counts_come_from_army_section():
    troops = _parse_unit_tab(_CITY_MILITARY_HTML, "army")
    assert troops["s303"] == {"name": "Hoplita", "amount": 290}
    assert troops["s302"] == {"name": "Espadachim", "amount": 55}
    assert troops["s301"] == {"name": "Fundeiro", "amount": 0}  # '-' → 0


def test_fleet_counts_come_from_fleet_section_not_army():
    fleet = _parse_unit_tab(_CITY_MILITARY_HTML, "fleet")
    # Regression: before the fix this returned amount=290 (the Hoplita count)
    assert fleet["s211"] == {"name": "Lança-Chamas", "amount": 12}
    assert fleet["s210"] == {"name": "Trirreme", "amount": 7}


def test_fleet_missing_section_returns_empty():
    army_only = '<div class="army s303"><div class="tooltip">Hoplita</div></div><td>5</td>'
    assert _parse_unit_tab(army_only, "fleet") == {}
