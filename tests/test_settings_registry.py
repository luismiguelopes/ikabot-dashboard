"""
P13.30 (rest): farm, espionage, world scan and alert settings are declared once in the shared
registry. These tests pin that the move changed NO behaviour on the bot side: every reader
returns what it returned before, for the stored values that matter (absent, valid, junk,
out of range).
"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("telegram_notifier", types.ModuleType("telegram_notifier"))

import empire_collector as ec
import empire_utils
import espionage_manager as em
import farm_manager as fm
import scan_collector as sc
import settings_registry as reg


def _farm(monkeypatch, tmp_path, data):
    p = tmp_path / "farm_settings.json"
    if data is None:
        if p.exists():
            p.unlink()
    else:
        p.write_text(data if isinstance(data, str) else json.dumps(data))
    monkeypatch.setattr(fm, "FARM_SETTINGS_PATH", str(p))


def _farm_readers():
    return {
        "army": fm.get_farm_army(), "fleet": fm.get_farm_fleet(),
        "spyAgents": fm.get_farm_spy_agents(), "minShipFraction": fm._min_ship_fraction(),
        "demote": fm._fleet_demote_after(), "earlyRespy": fm.early_respy_enabled(),
        "earlyAge": fm._early_report_max_age_secs(), "fresh": fm._spy_freshness_secs(),
        "reserve": fm._reserve_settings(),
    }


_FARM_DEFAULT_READS = {
    "army": {}, "fleet": {}, "spyAgents": 10, "minShipFraction": 0.5, "demote": 3,
    "earlyRespy": True, "earlyAge": 7200, "fresh": 86400, "reserve": (True, 45),
}


def test_farm_readers_with_no_file_or_a_broken_one_use_the_old_defaults(monkeypatch, tmp_path):
    for data in (None, "not json", {}):
        _farm(monkeypatch, tmp_path, data)
        assert _farm_readers() == _FARM_DEFAULT_READS
    assert fm._load_farm_settings().get("lootCapPerRaid") == 0


def test_farm_readers_return_the_stored_values(monkeypatch, tmp_path):
    _farm(monkeypatch, tmp_path, {
        "army": {"s303": 140, "s305": 0}, "fleet": {"s216": 40}, "spyAgents": 4,
        "minShipFraction": 0.25, "fleetDemoteAfterSweeps": 0, "earlyRespyEnabled": False,
        "earlyReportMaxAgeMins": 30, "spyFreshnessHours": 6.5, "lootCapPerRaid": 300000,
        "shipReserveEnabled": False, "reserveHorizonMin": 15})
    assert _farm_readers() == {
        "army": {"s303": 140}, "fleet": {"s216": 40}, "spyAgents": 4, "minShipFraction": 0.25,
        "demote": 0, "earlyRespy": False, "earlyAge": 1800, "fresh": int(6.5 * 3600),
        "reserve": (False, 15)}
    monkeypatch.setattr(fm, "_trade_fleet_size", lambda: None)
    assert fm.per_raid_loot_cap() == 300000


def test_farm_readers_survive_junk_and_out_of_range_values(monkeypatch, tmp_path):
    _farm(monkeypatch, tmp_path, {
        "army": {"s303": "x"}, "fleet": {"s216": "x"}, "spyAgents": 0, "minShipFraction": 7,
        "fleetDemoteAfterSweeps": -2, "earlyReportMaxAgeMins": 1, "spyFreshnessHours": -1,
        "reserveHorizonMin": -5})
    r = _farm_readers()
    assert r["army"] == {} and r["fleet"] == {}
    assert r["spyAgents"] == 1                  # never below one spy
    assert r["minShipFraction"] == 1.0          # clamped to 0..1
    assert r["demote"] == 0                     # never negative (0 = old ratchet)
    assert r["earlyAge"] == 600                 # never under 10 minutes
    assert r["fresh"] == 0                      # ≤ 0 turns the freshness guard off
    assert r["reserve"] == (True, 0)
    _farm(monkeypatch, tmp_path, {"spyAgents": "abc", "minShipFraction": "abc",
                                  "spyFreshnessHours": "abc", "earlyReportMaxAgeMins": "abc"})
    r = _farm_readers()
    assert (r["spyAgents"], r["minShipFraction"], r["fresh"], r["earlyAge"]) == (10, 0.5, 86400, 7200)


def test_unknown_farm_keys_are_kept_on_load(monkeypatch, tmp_path):
    _farm(monkeypatch, tmp_path, {"somethingElse": 1})
    assert fm._load_farm_settings()["somethingElse"] == 1


def test_espionage_readers(monkeypatch, tmp_path):
    p = tmp_path / "espionage_settings.json"
    monkeypatch.setattr(em, "ESPIONAGE_SETTINGS_PATH", str(p))

    def reads():
        s = em._load_espionage_settings()
        return (s.get("processingEnabled", True), em._check_garrison_threshold({"wood": 50000}, s),
                em._min_loot_total(s), em._ignore_expiry_days(s), em._ignore_permanent_after(s),
                em._mission_retention_secs())
    assert reads() == (True, True, 50000, 60, 4, 30 * 86400)          # no file
    p.write_text(json.dumps({"processingEnabled": False, "garrisonThresholdTotal": 60000,
                             "minLootTotal": 12000, "ignoreExpiryDays": 45,
                             "ignorePermanentAfter": 2, "missionRetentionDays": 7}))
    assert reads() == (False, False, 12000, 45, 2, 7 * 86400)
    p.write_text(json.dumps({"missionRetentionDays": 0}))
    assert reads()[5] == 86400                                        # never under a day


def test_world_scan_readers(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(sc, "WORLD_SCAN_RADIUS", 14)
    p = tmp_path / "world_scan_settings.json"
    assert (sc._world_scan_enabled(), sc._scan_radius()) == (True, 14)
    p.write_text(json.dumps({"enabled": False, "radius": 22}))
    assert (sc._world_scan_enabled(), sc._scan_radius()) == (False, 22)
    p.write_text(json.dumps({"radius": 999}))
    assert (sc._world_scan_enabled(), sc._scan_radius()) == (True, 60)


def test_alert_readers(monkeypatch, tmp_path):
    p = tmp_path / "alert_settings.json"
    monkeypatch.setattr(ec, "ALERT_SETTINGS_PATH", str(p))
    assert ec._load_alert_settings() == {"incomingEnabled": True, "returnEnabled": True,
                                         "checkMinutes": 0}
    p.write_text(json.dumps({"returnEnabled": False, "checkMinutes": 30}))
    assert ec._load_alert_settings() == {"incomingEnabled": True, "returnEnabled": False,
                                         "checkMinutes": 30}
    p.write_text(json.dumps({"checkMinutes": "abc"}))
    assert ec._load_alert_settings()["checkMinutes"] == 0


def test_the_validation_schemas_come_from_the_registry():
    for name in ("farm", "espionage", "world_scan", "alerts", "alert_thresholds"):
        spec = reg.SPECS[name]
        assert empire_utils._CONFIG_SCHEMAS[spec["file"]] == reg.schema(name)
    farm = reg.schema("farm")
    assert farm["army"] is dict and farm["minShipFraction"] is float
    assert farm["spyFreshnessHours"] is float           # 6.5 h is a valid setting
    # read by the bot for years but missing from the old hand-written schema → a user who set
    # it got an "unknown key" warning
    assert "missionRetentionDays" in reg.schema("espionage")


def test_registry_update_merges_units_and_floats(tmp_path):
    p = str(tmp_path / "farm_settings.json")
    reg.update("farm", {"army": {"s303": 140, "s305": 0}, "spyAgents": 4}, p)
    s = reg.update("farm", {"spyFreshnessHours": "12.5", "minShipFraction": 3,
                            "fleet": "junk", "lootCapPerRaid": -1}, p)
    assert s["army"] == {"s303": 140} and s["spyAgents"] == 4      # untouched by the 2nd save
    assert s["spyFreshnessHours"] == 12.5 and s["minShipFraction"] == 1.0
    assert s["fleet"] == {} and s["lootCapPerRaid"] == 0
    assert json.load(open(p))["spyFreshnessHours"] == 12.5


def test_world_scan_default_radius_follows_the_env(monkeypatch):
    monkeypatch.setenv("WORLD_SCAN_RADIUS", "18")
    assert reg.defaults("world_scan")["radius"] == 18
    monkeypatch.setenv("WORLD_SCAN_RADIUS", "999")
    assert reg.defaults("world_scan")["radius"] == 60
    monkeypatch.setenv("WORLD_SCAN_RADIUS", "abc")
    assert reg.defaults("world_scan")["radius"] == 10
