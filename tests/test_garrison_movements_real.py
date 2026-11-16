"""Garrison and fleet-movements reports as the game really sends them
(tests/fixtures/spy_garrison_movements.html — taken 2026-11-16 from the live game, names
replaced). Two things the hand-written samples never showed:

  • the unit header's name sits on the <th title="…"> tag itself; the "Quartel" icon inside
    carries only an alt. Only the first table of each arm was read (by accident, through the
    wrapping row), so the units of the 2nd and 3rd land tables were filed under the names of
    the 1st — 15 cooks and 15 doctors read as 15 spearmen and 15 swordsmen;
  • the dates of a movements report are on the SERVER's clock (one hour ahead of Lisbon).
    Read as local time, a returning enemy fleet was believed to be away one hour longer than
    it was, and unescorted troops were sent into the gap (empty return, 16/11).
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot"))

import espionage_parsers as ep

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures",
                        "spy_garrison_movements.html")


def _chunks():
    with open(_FIXTURE, encoding="utf-8") as f:
        return ep.split_report_chunks(f.read())


def _server(y, mo, d, h, mi, s=0):
    return int(datetime(y, mo, d, h, mi, s, tzinfo=ZoneInfo("Europe/Berlin")).timestamp())


# ── garrison ─────────────────────────────────────────────────────────────────

def test_real_garrison_names_every_land_table_by_its_own_header():
    sections = ep._parse_garrison_sections(_chunks()["900002"])
    assert sections["army"] == {"Cozinheiro": 15, "Médico": 15}


def test_real_garrison_fleet_section():
    sections = ep._parse_garrison_sections(_chunks()["900002"])
    assert sections["fleet"] == {"Lança-foguetes": 5, "Submergível": 13, "Porta-balões": 4}


def test_header_without_a_readable_name_does_not_inherit_the_previous_table():
    """A unit the parser cannot name is kept as unknown — never filed under the previous
    table's names, never dropped (an unnamed ship is still a ship in the harbour)."""
    html = """<table>
    <tr><th title="Quartel"><img alt="Quartel"/></th><th title="Hoplita"><img/></th></tr>
    <tr><td>Tropas em ALVO</td><td>7</td></tr>
    <tr><th title="Quartel"><img alt="Quartel"/></th><th><img/></th></tr>
    <tr><td>Tropas em ALVO</td><td>9</td></tr></table>"""
    assert ep._parse_garrison_sections(html)["army"] == {"Hoplita": 7, ep._UNKNOWN_UNIT: 9}


def test_unnamed_ship_still_counts_as_a_ship():
    html = """<table>
    <tr><th title="Estaleiro"><img/></th><th><img/></th></tr>
    <tr><td>Frotas em ALVO</td><td>3</td><td>2</td></tr></table>"""
    assert ep._parse_garrison_sections(html)["fleet"] == {ep._UNKNOWN_SHIP: 5}


# ── movements ────────────────────────────────────────────────────────────────

def test_real_movements_report_rows():
    movs = ep.parse_fleet_movements(_chunks()["900001"])
    assert len(movs) == 1
    assert movs[0]["target"] == "CIDADE ALVO"
    assert movs[0]["action"] == "Pilhar" and movs[0]["qty"] == 80


def test_movement_times_are_on_the_server_clock(monkeypatch):
    """Whatever the container's own timezone, '16.11.2026 17:03:47' is 16:03:47 UTC."""
    import time
    for tz in ("Europe/Lisbon", "UTC", "America/Sao_Paulo"):
        monkeypatch.setenv("TZ", tz)
        time.tzset()
        movs = ep.parse_fleet_movements(_chunks()["900001"])
        assert movs[0]["departure"] == _server(2026, 11, 16, 16, 45, 39)
        assert movs[0]["arrival"] == _server(2026, 11, 16, 17, 3, 47)
    monkeypatch.undo()
    time.tzset()


def test_enemy_return_is_not_an_hour_late(monkeypatch):
    """The 16/11 case: blockade landed 10:09 Lisbon, the fleet is back 14:09 Lisbon — the
    report says 15:09 (server clock). The bot believed 15:09 Lisbon and sent troops at 13:12
    that landed at 14:50."""
    import time
    monkeypatch.setenv("TZ", "Europe/Lisbon")
    time.tzset()
    try:
        import espionage_manager as em
        html = ("<table><tr><td>Alvo</td><td>16.11.2026 11:09:00</td><td>16.11.2026 15:09:00</td>"
                "<td>Defender porto(Voltar)</td><td>40</td></tr></table>")
        now = int(datetime(2026, 11, 16, 12, 44, tzinfo=ZoneInfo("Europe/Lisbon")).timestamp())
        eta = em._enemy_return_from_movements(html, "Alvo", now)
        assert eta == int(datetime(2026, 11, 16, 14, 9, tzinfo=ZoneInfo("Europe/Lisbon")).timestamp())
    finally:
        monkeypatch.undo()
        time.tzset()
