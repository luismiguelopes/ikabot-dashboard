"""
Tests for config schema validation (P5.8): unknown keys (typos) and type mismatches are
flagged instead of being silently swallowed into defaults.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import empire_utils as eu


def _point_logs_at(monkeypatch, tmp_path):
    monkeypatch.setattr(eu, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(eu, "CONFIG_WARNINGS_PATH", str(tmp_path / "config_warnings.json"))


def _write(tmp_path, name, data):
    with open(tmp_path / name, "w") as f:
        json.dump(data, f)


def test_clean_config_has_no_warnings(monkeypatch, tmp_path):
    _point_logs_at(monkeypatch, tmp_path)
    _write(tmp_path, "farm_settings.json",
           {"army": {"s303": 50}, "spyAgents": 2, "shipReserveEnabled": True,
            "reserveHorizonMin": 45, "earlyRespyEnabled": True})
    assert eu.validate_configs() == {}


def test_unknown_key_is_flagged(monkeypatch, tmp_path):
    _point_logs_at(monkeypatch, tmp_path)
    _write(tmp_path, "farm_settings.json", {"spyAgent": 2})   # typo: missing trailing 's'
    warnings = eu.validate_configs()
    assert "farm_settings.json" in warnings
    assert any("spyAgent" in w for w in warnings["farm_settings.json"])


def test_type_mismatch_is_flagged(monkeypatch, tmp_path):
    _point_logs_at(monkeypatch, tmp_path)
    _write(tmp_path, "auto_attack_settings.json", {"minLootTotal": "lots"})  # str, expected int
    warnings = eu.validate_configs()
    assert any("minLootTotal" in w for w in warnings["auto_attack_settings.json"])


def test_bool_not_accepted_for_int_field(monkeypatch, tmp_path):
    _point_logs_at(monkeypatch, tmp_path)
    _write(tmp_path, "espionage_settings.json", {"garrisonThresholdTotal": True})
    warnings = eu.validate_configs()
    assert "espionage_settings.json" in warnings


def test_warnings_written_to_file(monkeypatch, tmp_path):
    _point_logs_at(monkeypatch, tmp_path)
    _write(tmp_path, "telegram_settings.json", {"botToken": "x", "chatId": "y", "oops": 1})
    eu.validate_configs()
    with open(tmp_path / "config_warnings.json") as f:
        saved = json.load(f)
    assert "telegram_settings.json" in saved


def test_missing_files_are_skipped(monkeypatch, tmp_path):
    _point_logs_at(monkeypatch, tmp_path)
    assert eu.validate_configs() == {}     # nothing on disk → nothing to warn about
