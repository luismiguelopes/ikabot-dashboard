"""
F4.b parsers: real travel times from the attack forms, and the enemy-fleet-return window
from the spy-on-movements report. Fixtures mirror the real game responses.
Run with: python -m pytest tests/ -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import attack_manager as am
import espionage_manager as em


# ── Travel-time parser (blockade / plunder form JS) ─────────────────────────────
# Mirrors the AJAX response shape: escaped \" and \n, missionController(...) + sliders.

PLUNDER_FORM = (
    r'...new missionController(\n  337,\n  620,\n  6729,\n  null,\n  0,\n  90,\n  true);\n'
    r'create_slider({ id: \"slider_304\", textfield: \"cargo_army_304\" });\n'
    r'var s = ikariam.controller.sliders[\"slider_304\"];\n s.weight = 5;\n s.unitJourneyTime = 6729;\n'
    r'create_slider({ id: \"slider_305\", textfield: \"cargo_army_305\" });\n'
    r'var s = ikariam.controller.sliders[\"slider_305\"];\n s.weight = 30;\n s.unitJourneyTime = 6729;\n'
)

BLOCKADE_FORM = (
    r'...new missionController(\n  0,\n  620,\n  25232,\n  0,\n  0,\n  90,\n  true);\n'
    r'create_slider({ id: \"slider_216\", textfield: \"cargo_fleet_216\" });\n'
    r'var s = ikariam.controller.sliders[\"slider_216\"];\n s.unitJourneyTime = 12616;\n'
    r'create_slider({ id: \"slider_218\", textfield: \"cargo_fleet_218\" });\n'
    r'var s = ikariam.controller.sliders[\"slider_218\"];\n s.unitJourneyTime = 8411;\n'
    r'create_slider({ id: \"slider_219\", textfield: \"cargo_fleet_219\" });\n'
    r'var s = ikariam.controller.sliders[\"slider_219\"];\n s.unitJourneyTime = 25232;\n'
)


def test_parse_journey_times_plunder():
    transport, units = am._parse_journey_times(PLUNDER_FORM)
    assert transport == 6729
    assert units == {"304": 6729, "305": 6729}


def test_parse_journey_times_blockade():
    transport, units = am._parse_journey_times(BLOCKADE_FORM)
    assert transport == 25232
    assert units == {"216": 12616, "218": 8411, "219": 25232}


def test_fleet_journey_picks_slowest_of_selected(monkeypatch):
    monkeypatch.setattr(am, "_fetch_form_raw", lambda *a, **k: BLOCKADE_FORM)
    # only steam rams (216) → 12616; with the slow balloon carrier (219) → 25232
    assert am.fetch_fleet_journey(None, None, "o", "t", fleet_unit_ids=["216"]) == 12616
    assert am.fetch_fleet_journey(None, None, "o", "t", fleet_unit_ids=["s216", "s219"]) == 25232
    # no list → max over all ships
    assert am.fetch_fleet_journey(None, None, "o", "t") == 25232


def test_troop_journey_uses_transport_time(monkeypatch):
    monkeypatch.setattr(am, "_fetch_form_raw", lambda *a, **k: PLUNDER_FORM)
    assert am.fetch_troop_journey(None, None, "o", "t") == 6729


def test_journey_parser_robust_to_missing():
    assert am._parse_journey_times("garbage") == (None, {})
    assert am._parse_journey_times("") == (None, {})


# ── Movement report parser (spy on movements, mission 7) ─────────────────────────

MOVEMENT_REPORT = """
<table>
<tr><th>Cidade alvo</th><th>Tempo de partida</th><th>Tempo de chegada</th><th>Acção</th><th>Quantidade</th></tr>
<tr><td>&#916; The Rock &#916;</td><td>17.06.2026 20:39:00</td><td>17.06.2026 22:31:35</td><td>Pilhar</td><td>168</td></tr>
<tr><td>&#916; The Rock &#916;</td><td>17.06.2026 21:51:13</td><td>18.06.2026 1:51:13</td><td>Defender porto(Voltar)</td><td>140</td></tr>
</table>
"""

EMPTY_REPORT = "<div>Neste momento não existem movimentos de frotas!</div>"


def test_parse_fleet_movements_rows():
    movs = em.parse_fleet_movements(MOVEMENT_REPORT)
    assert len(movs) == 2
    pilhar = [m for m in movs if m["action"] == "Pilhar"][0]
    assert pilhar["qty"] == 168
    voltar = [m for m in movs if "Voltar" in m["action"]][0]
    assert voltar["qty"] == 140
    assert voltar["arrival"] > voltar["departure"]


def test_enemy_fleet_clean_window():
    # enemy fled at 21:51:13 (17th), returns 01:51:13 (18th) → 4h clean window
    window = em.enemy_fleet_clean_window_secs(MOVEMENT_REPORT)
    assert window == 4 * 3600


def test_clean_window_filters_by_city():
    assert em.enemy_fleet_clean_window_secs(MOVEMENT_REPORT, "The Rock") == 4 * 3600
    assert em.enemy_fleet_clean_window_secs(MOVEMENT_REPORT, "Some Other City") is None


def test_empty_movement_report():
    assert em.parse_fleet_movements(EMPTY_REPORT) == []
    assert em.enemy_fleet_clean_window_secs(EMPTY_REPORT) is None
