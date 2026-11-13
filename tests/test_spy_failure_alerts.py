"""F15 phase 2: _save_missions alerts once per mission that newly turns FAILED."""
import json
import sys
import time
import types

import espionage_manager as em


def test_alerts_only_on_new_failed_transitions(monkeypatch, tmp_path):
    path = tmp_path / "spy_missions.json"
    monkeypatch.setattr(em, "SPY_MISSIONS_PATH", str(path))
    monkeypatch.setattr(em, "LOGS_DIR", str(tmp_path))
    seen = []
    stub = types.ModuleType("telegram_notifier")
    stub.notify_spy_failed = lambda city, player, err, lost: seen.append((city, lost))
    monkeypatch.setitem(sys.modules, "telegram_notifier", stub)

    base = {"originCityId": "1", "targetCityName": "T", "targetPlayerName": "P"}
    a = dict(base, targetCityId="10", dispatchedAt=int(time.time()) - 100, state="TRAVELING")
    b = dict(base, targetCityId="11", dispatchedAt=int(time.time()) - 200, state="FAILED", error="old")
    path.write_text(json.dumps({"missions": [a, b]}))

    a2 = dict(a, state="FAILED", error="Sem chegada detectada após 3h — possivelmente capturado")
    em._save_missions({"missions": [a2, b]})
    assert seen == [("T", True)]          # b was already FAILED → no repeat

    em._save_missions({"missions": [a2, b]})
    assert seen == [("T", True)]          # saving again doesn't re-alert
