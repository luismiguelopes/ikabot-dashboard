"""
P13.43: the plunder and blockade forms as the game really sent them (captured live on
2026-11-16, names/ids/tokens replaced), instead of hand-written snippets.

What these protect: the upkeep fields and the function name the dispatch copies from the
form, and the travel times the farm uses to time the troops behind the blockade.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _name in ("ikabot", "ikabot.config", "ikabot.helpers", "ikabot.helpers.naval"):
    sys.modules.setdefault(_name, types.ModuleType(_name))
_cfg = sys.modules["ikabot.config"]
for _attr, _val in (("actionRequest", "TEST"), ("materials_names_english", []),
                    ("materials_names_tec", []), ("materials_names", [])):
    if not hasattr(_cfg, _attr):
        setattr(_cfg, _attr, _val)
sys.modules.setdefault("telegram_notifier", types.ModuleType("telegram_notifier"))

import attack_manager as am

_FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
_ARMY_IDS = {"302", "303", "304", "305", "308", "309", "312", "319"}
_FLEET_IDS = {"213", "215", "216", "218"}


def _raw(name):
    with open(os.path.join(_FIX, name), encoding="utf-8") as f:
        return f.read()


class _GameSession:
    """Answers a form request with the captured form, records every other POST."""
    def __init__(self, form):
        self.form, self.sent = _raw(form), []

    def post(self, params=None, **k):
        if (params or {}).get("view"):
            return self.form
        self.sent.append(params)
        return "RESP"


def _quiet(monkeypatch):
    monkeypatch.setattr(am.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(am, "save_capture", lambda *a, **k: None)
    monkeypatch.setattr(am, "_change_to_origin_city", lambda *a, **k: None)
    monkeypatch.setattr(am, "_parse_attack_feedback", lambda *a, **k: True)
    monkeypatch.setattr(am, "_cap_to_available_ships", lambda req, session=None, reserve=0: int(req))


def test_fixtures_carry_no_real_names_or_tokens():
    for name in ("plunder_form.json", "blockade_form.json"):
        raw = _raw(name)
        assert "0000000000000000000000000000test" in raw
        assert "Origem" in raw and "Alvo" in raw and "Dono" in raw


def test_plunder_form_upkeep_and_function(monkeypatch):
    _quiet(monkeypatch)
    upkeep, fn = am._fetch_plunder_form(_GameSession("plunder_form.json"), _cfg, "1", "99107")
    assert set(upkeep) == _ARMY_IDS
    assert all(v.isdigit() for v in upkeep.values())
    assert (upkeep["303"], upkeep["302"]) == ("3", "4")
    assert fn == "sendArmyPlunderSea"


def test_blockade_form_upkeep_function_and_view(monkeypatch):
    _quiet(monkeypatch)
    upkeep, fn, view = am._fetch_blockade_form(_GameSession("blockade_form.json"), _cfg, "1", "99103")
    assert set(upkeep) == _FLEET_IDS
    assert (upkeep["216"], upkeep["215"], upkeep["213"]) == ("45", "50", "20")
    assert (fn, view) == ("sendFleetOnBlockade", "blockade")


def test_journey_times_come_from_the_call_not_the_function_definition():
    """The page holds `function missionController(freeTrans, transporterCapacity, …)` BEFORE
    the call `new missionController(266, 620, 6692, …)`. The parser matched the definition and
    read three unrelated digits further down the script as the transport time."""
    transport, units = am._parse_journey_times(_raw("plunder_form.json"))
    assert transport == 6692
    assert set(units) == _ARMY_IDS and set(units.values()) == {6692}
    transport, units = am._parse_journey_times(_raw("blockade_form.json"))
    assert transport == 14484
    assert units == {"213": 10863, "215": 14484, "216": 10863, "218": 7243}


def test_troop_and_fleet_journeys_from_the_real_forms(monkeypatch):
    _quiet(monkeypatch)
    assert am.fetch_troop_journey(_GameSession("plunder_form.json"), _cfg, "1", "99107") == 6692
    s = _GameSession("blockade_form.json")
    assert am.fetch_fleet_journey(s, _cfg, "1", "99103", ["s216"]) == 10863     # the loadout's pace
    assert am.fetch_fleet_journey(s, _cfg, "1", "99103") == 14484               # slowest of all
    assert am.fetch_fleet_journey(s, _cfg, "1", "99103", ["s299"]) == 14484     # unknown id → all


def test_troop_journey_is_never_shorter_than_the_slowest_unit(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(am, "_parse_journey_times", lambda raw: (600, {"303": 900}))
    assert am.fetch_troop_journey(_GameSession("plunder_form.json"), _cfg, "1", "2") == 900
    monkeypatch.setattr(am, "_parse_journey_times", lambda raw: (None, {"303": 900}))
    assert am.fetch_troop_journey(_GameSession("plunder_form.json"), _cfg, "1", "2") == 900
    monkeypatch.setattr(am, "_parse_journey_times", lambda raw: (None, {}))
    assert am.fetch_troop_journey(_GameSession("plunder_form.json"), _cfg, "1", "2") is None


def test_plunder_payload_built_from_the_real_form(monkeypatch):
    _quiet(monkeypatch)
    s = _GameSession("plunder_form.json")
    ok = am._send_army_plunder(s, "1", "99107", "707", {"s303": 140, "s305": 22, "s319": 140}, 266)
    assert ok is True
    (p,) = s.sent
    assert p["function"] == "sendArmyPlunderSea" and p["templateView"] == "plunder"
    assert (p["destinationCityId"], p["islandId"], p["transporter"]) == ("99107", "707", 266)
    for uid in _ARMY_IDS:                                   # every unit the form offers
        assert f"cargo_army_{uid}_upkeep" in p and f"cargo_army_{uid}" in p
    assert (p["cargo_army_303"], p["cargo_army_305"], p["cargo_army_319"]) == (140, 22, 140)
    assert sum(p[f"cargo_army_{u}"] for u in _ARMY_IDS) == 302     # nothing else rides along
    assert not any(k.startswith("cargo_army_s") for k in p)


def test_blockade_payload_built_from_the_real_form(monkeypatch):
    _quiet(monkeypatch)
    s = _GameSession("blockade_form.json")
    assert am._send_fleet_blockade(s, "1", "99103", "703", {"s216": 40}) is True
    (p,) = s.sent
    assert p["function"] == "sendFleetOnBlockade" and p["templateView"] == "blockade"
    for uid in _FLEET_IDS:
        assert f"cargo_fleet_{uid}_upkeep" in p
    assert p["cargo_fleet_216"] == 40
    assert sum(p[f"cargo_fleet_{u}"] for u in _FLEET_IDS) == 40
    assert "transporter" not in p
