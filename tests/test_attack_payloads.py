"""
Golden-file tests for the POST payloads that SPEND troops/ships (P5.7):
sendArmyPlunderSea, sendFleetBlockadeSea (blockade) and deployArmy/deployFleet.

These are the highest-consequence requests in the bot — a regression in the unit-id strip,
the mandatory upkeep fields or the transporter cap costs a real army in-game. The tests pin
the exact params dict by stubbing the form-fetch helpers (the "captured form") and the
session, so any drift in payload construction fails here, not on the battlefield.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stubs so attack_manager's lazy `import ikabot.config` and telegram imports resolve even when
# this file runs before the other test modules that set them up.
for _name in ("ikabot", "ikabot.config"):
    sys.modules.setdefault(_name, types.ModuleType(_name))
_cfg = sys.modules["ikabot.config"]
for _attr, _val in (("actionRequest", "TEST"), ("materials_names_english", []),
                    ("materials_names_tec", []), ("materials_names", [])):
    if not hasattr(_cfg, _attr):
        setattr(_cfg, _attr, _val)
sys.modules.setdefault("telegram_notifier", types.ModuleType("telegram_notifier"))
for _fn in ("notify_attack_dispatched", "notify_attack_failed"):
    if not hasattr(sys.modules["telegram_notifier"], _fn):
        setattr(sys.modules["telegram_notifier"], _fn, lambda *a, **k: None)

import attack_manager as am


class _CaptureSession:
    def __init__(self):
        self.params = None
    def post(self, params=None, **k):
        self.params = params
        return "RESP"
    def get(self, *a, **k):
        return ""


def _common(monkeypatch):
    """Neutralise everything except payload construction."""
    monkeypatch.setattr(am, "_change_to_origin_city", lambda *a, **k: None)
    monkeypatch.setattr(am, "_parse_attack_feedback", lambda *a, **k: True)
    monkeypatch.setattr(am, "_cap_to_available_ships", lambda req, session=None: int(req))


def test_army_plunder_payload(monkeypatch):
    _common(monkeypatch)
    # Captured plunder form: 3 unit types, upkeep mandatory. 315 is offered but not sent.
    monkeypatch.setattr(am, "_fetch_plunder_upkeep",
                        lambda *a, **k: {"303": "5", "304": "3", "315": "0"})
    s = _CaptureSession()

    ok = am._send_army_plunder(s, origin_id=1, target_id=20477, island_id=30816,
                               units={"s303": 168, "s304": 0}, transporters=337)
    assert ok is True
    p = s.params
    # core fields
    assert p["function"] == "sendArmyPlunderSea"
    assert p["templateView"] == "plunder"
    assert p["action"] == "transportOperations"
    assert p["destinationCityId"] == "20477"
    assert p["islandId"] == "30816"
    assert p["currentCityId"] == "1"
    assert p["transporter"] == 337                      # transporter cap applied
    # 's' prefix stripped; sent unit carries its count + mandatory upkeep
    assert p["cargo_army_303"] == 168
    assert p["cargo_army_303_upkeep"] == "5"
    # form unit not sent is zero-filled (still needs its upkeep field)
    assert p["cargo_army_315"] == 0
    assert p["cargo_army_315_upkeep"] == "0"
    # no un-stripped key leaked through
    assert "cargo_army_s303" not in p


def test_fleet_blockade_payload(monkeypatch):
    _common(monkeypatch)
    # Form self-discovers the real function name and the cargo_fleet_* upkeep fields.
    monkeypatch.setattr(am, "_fetch_blockade_form",
                        lambda *a, **k: ({"401": "2", "402": "0"}, "sendFleetBlockadeSea", "blockade"))
    s = _CaptureSession()

    ok = am._send_fleet_blockade(s, origin_id=1, target_id=20477, island_id=30816,
                                 units={"s401": 10})
    assert ok is True
    p = s.params
    assert p["function"] == "sendFleetBlockadeSea"      # taken from the form
    assert p["templateView"] == "blockade"
    assert p["cargo_fleet_401"] == 10
    assert p["cargo_fleet_401_upkeep"] == "2"
    assert p["cargo_fleet_402"] == 0
    assert "transporter" not in p                       # blockade carries no transporters
    assert "cargo_fleet_s401" not in p                  # 's' stripped


def test_deploy_army_keeps_css_unit_ids(monkeypatch):
    _common(monkeypatch)
    # Deployment form uses the CSS-style ids (s303) and they are NOT stripped (unlike plunder).
    monkeypatch.setattr(am, "_fetch_deployment_upkeep", lambda *a, **k: {"s303": "5"})
    s = _CaptureSession()

    ok = am._send_deploy(s, origin_id=1, target_id=999, island_id=30816,
                         units={"s303": 50}, transporters=20, kind="army")
    assert ok is True
    p = s.params
    assert p["function"] == "deployArmy"
    assert p["deploymentType"] == "army"
    assert p["templateView"] == "deployment"
    assert p["transporter"] == 20
    assert p["cargo_army_s303"] == 50                   # CSS id kept (NOT stripped to 303)
    assert p["cargo_army_s303_upkeep"] == "5"
    assert "cargo_army_303" not in p


def test_deploy_fleet_has_no_transporter(monkeypatch):
    _common(monkeypatch)
    monkeypatch.setattr(am, "_fetch_deployment_upkeep", lambda *a, **k: {"s401": "1"})
    s = _CaptureSession()

    ok = am._send_deploy(s, origin_id=1, target_id=999, island_id=30816,
                         units={"s401": 5}, transporters=0, kind="fleet")
    assert ok is True
    p = s.params
    assert p["function"] == "deployFleet"
    assert p["cargo_fleet_s401"] == 5
    assert "transporter" not in p                       # only army deployment needs ships
