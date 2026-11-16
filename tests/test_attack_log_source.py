"""
The attack history must say who launched each attack. Every dispatch used to be logged as
"manual", so the dashboard showed the farm's own raids as manual attacks. Farm items are the
only ones flagged `respectWineReserve` (manual UI attacks are not), so that flag names the source.
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


def _logged_source(monkeypatch, item, **kw):
    seen = {}
    fake_db = types.ModuleType("db_manager")
    fake_db.log_attack = lambda entry: seen.update(entry)
    monkeypatch.setitem(sys.modules, "db_manager", fake_db)
    am._log_attack_attempt(item, True, **kw)
    return seen["source"]


def test_farm_item_is_logged_as_farm(monkeypatch):
    assert _logged_source(monkeypatch, {"targetCityName": "X", "respectWineReserve": 1}) == "farm"


def test_ui_item_is_logged_as_manual(monkeypatch):
    assert _logged_source(monkeypatch, {"targetCityName": "X"}) == "manual"


def test_explicit_source_wins(monkeypatch):
    item = {"targetCityName": "X", "respectWineReserve": 1}
    assert _logged_source(monkeypatch, item, source="manual") == "manual"
