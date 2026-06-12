"""
Unit tests for espionage_manager HTML parsers and pure helpers.
Fixtures replicate the real game HTML structures (Portuguese locale).
Run with: python -m pytest tests/ -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import espionage_manager as em


# ── _parse_safehouse_page ─────────────────────────────────────────────────────

_SAFEHOUSE_HTML = """
<div id="safehouse"><p>
Tens 25 espiões. 10 estão em uso, 15 estão a trabalhar na defesa
e 0 esperam por treino.</p>
<p>Podes treinar 40 espiões adicionais.</p></div>
"""


def test_safehouse_counts():
    counts = em._parse_safehouse_page(_SAFEHOUSE_HTML, "Cidade")
    assert counts["deployed"] == 10
    assert counts["inDefense"] == 15
    assert counts["inTraining"] == 0
    assert counts["trainable"] == 40


def test_safehouse_empty_html():
    counts = em._parse_safehouse_page("", "Cidade")
    assert all(v is None for v in counts.values())


# ── _parse_arrival_countdown ──────────────────────────────────────────────────

def test_countdown_full():
    assert em._parse_arrival_countdown("Chegada 1h 23m 10s") == 3600 + 23 * 60 + 10


def test_countdown_minutes_seconds():
    assert em._parse_arrival_countdown("Chegada 02m 56s") == 2 * 60 + 56


def test_countdown_seconds_only():
    assert em._parse_arrival_countdown("Chegada 45s") == 45


def test_countdown_absent():
    assert em._parse_arrival_countdown("sem contagem aqui") is None
    assert em._parse_arrival_countdown("") is None


# ── _parse_spy_session_id ─────────────────────────────────────────────────────

def test_spy_session_id_input_name_first():
    assert em._parse_spy_session_id('<input name="spy" value="12345"/>') == "12345"


def test_spy_session_id_value_first():
    assert em._parse_spy_session_id('<input value="777" name="spy">') == "777"


def test_spy_session_id_json_style():
    assert em._parse_spy_session_id('{"spy": 4242}') == "4242"


def test_spy_session_id_absent():
    assert em._parse_spy_session_id("<div>nada</div>") is None


# ── _parse_garrison_troops ────────────────────────────────────────────────────

_GARRISON_HTML = """
<table>
<tr><th>Quartel</th>
    <td><div class="army hoplite" title="Hoplita"></div></td>
    <td><div class="army steamgiant" title="Gigante a Vapor"></div></td>
    <td><div class="army slinger" title="Fundeiro"></div></td></tr>
<tr><td>Tropas em ALVO</td><td>1.250</td><td>30</td><td>-</td></tr>
<tr><th>Estaleiro</th>
    <td><div class="fleet ram" title="Aríete a vapor"></div></td></tr>
<tr><td>Frotas em ALVO</td><td>12</td></tr>
</table>
"""


def test_garrison_troops_parsed_with_thousands_and_dashes():
    troops = em._parse_garrison_troops(_GARRISON_HTML)
    assert troops["Hoplita"] == 1250
    assert troops["Gigante a Vapor"] == 30
    assert "Fundeiro" not in troops          # '-' = none
    assert troops["Aríete a vapor"] == 12


def test_garrison_empty_returns_empty_dict():
    assert em._parse_garrison_troops("<table></table>") == {}


# ── _parse_reports_from_html ──────────────────────────────────────────────────

_REPORTS_HTML = """
<tr id="message101" class="espionageReports bold">
  <td class="targetOwner">JogadorX</td>
  <td class="targetCity"><a href="?view=island&xcoord=43&ycoord=57&selectCity=9911">AlvoCity [43:57]</a></td>
</tr>
<tr id="tbl_mail101" class="report invisible">
  <td>A missão de espionagem foi completada com sucesso.
  <table class="resourcesTable">
    <tr><td><img alt="Madeira"/></td><td class="count">120.500</td></tr>
    <tr><td><img alt="Vinho"/></td><td class="count">8.000</td></tr>
    <tr><td><img alt="Cristal"/></td><td class="count">3.200</td></tr>
  </table></td>
</tr>
<tr id="message102" class="espionageReports">
  <td class="targetOwner">JogadorY</td>
  <td class="targetCity"><a href="?view=island&xcoord=10&ycoord=20">OutraCity [10:20]</a></td>
</tr>
<tr id="tbl_mail102" class="report">
  <td>O teu espião chegou a OutraCity.</td>
</tr>
"""


def test_reports_parse_success_with_resources():
    reports = em._parse_reports_from_html(_REPORTS_HTML)
    r = reports["101"]
    assert r["isUnread"] is True
    assert r["targetOwner"] == "JogadorX"
    assert r["targetCityName"] == "AlvoCity"
    assert r["targetCityId"] == "9911"
    assert (r["islandX"], r["islandY"]) == (43, 57)
    assert r["success"] is True
    # Cristal na UI = glass nas chaves técnicas
    assert r["resources"] == {"wood": 120500, "wine": 8000, "glass": 3200}


def test_reports_arrival_notification_flagged():
    reports = em._parse_reports_from_html(_REPORTS_HTML)
    r = reports["102"]
    assert r["isUnread"] is False
    assert r["isArrival"] is True
    assert r["success"] is False
    assert r["resources"] is None


def test_reports_empty_html():
    assert em._parse_reports_from_html("") == {}


# ── _parse_active_spy_missions ────────────────────────────────────────────────

_ACTIVE_MISSIONS_HTML = """
<tr><td><a href="?view=island&xcoord=43&ycoord=57&selectCity=9911">AlvoCity [43:57]</a>
    Os teus espiões esperam novas ordens.</td></tr>
<tr><td><a href="?view=island&xcoord=10&ycoord=20&selectCity=8822">OutraCity [10:20]</a>
    O teu espião está a caminho. Chegada 12m 30s</td></tr>
"""


def test_active_missions_stationed_and_traveling():
    entries = em._parse_active_spy_missions(_ACTIVE_MISSIONS_HTML)
    assert len(entries) == 2
    stationed = next(e for e in entries if e["state"] == "WAITING_AT_CITY")
    traveling = next(e for e in entries if e["state"] == "TRAVELING")
    assert stationed["cityId"] == "9911"
    assert stationed["cityName"] == "AlvoCity"
    assert traveling["cityId"] == "8822"
    assert traveling["countdown_secs"] == 12 * 60 + 30


# ── _check_garrison_threshold ─────────────────────────────────────────────────

def test_garrison_threshold():
    settings = {"garrisonThresholdTotal": 50000}
    assert em._check_garrison_threshold({"wood": 30000, "wine": 25000}, settings) is True
    assert em._check_garrison_threshold({"wood": 10000}, settings) is False
    assert em._check_garrison_threshold({}, settings) is False
    assert em._check_garrison_threshold(None, settings) is False
