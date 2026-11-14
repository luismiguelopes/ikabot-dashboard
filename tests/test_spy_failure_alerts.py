"""F15 phase 2: _save_missions alerts once per mission that newly turns FAILED."""
import json
import sys
import time
import types

import db_manager
import espionage_manager as em


def test_alerts_only_on_new_failed_transitions(monkeypatch, tmp_path):
    monkeypatch.setattr(db_manager, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(db_manager, "_LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(db_manager, "_DB_INIT_DONE", False)
    monkeypatch.setattr(em, "LOGS_DIR", str(tmp_path))
    seen = []
    stub = types.ModuleType("telegram_notifier")
    stub.notify_spy_failed = lambda city, player, err, lost: seen.append((city, lost))
    monkeypatch.setitem(sys.modules, "telegram_notifier", stub)

    base = {"originCityId": "1", "targetCityName": "T", "targetPlayerName": "P"}
    a = dict(base, targetCityId="10", dispatchedAt=int(time.time()) - 100, state="TRAVELING")
    b = dict(base, targetCityId="11", dispatchedAt=int(time.time()) - 200, state="FAILED", error="old")
    db_manager.missions_save({"missions": [a, b]})     # the store as it was before this save

    data = em._load_missions()
    data["missions"][0].update(state="FAILED",
                               error="Sem chegada detectada após 3h — possivelmente capturado")
    em._save_missions(data)
    assert seen == [("T", True)]          # b was already FAILED → no repeat

    em._save_missions(em._load_missions())
    assert seen == [("T", True)]          # saving again doesn't re-alert
