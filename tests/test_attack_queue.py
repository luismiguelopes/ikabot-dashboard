"""
Unit tests for the SQLite-backed shared queues (attack / spy dispatch / recall):
- db_manager.queue_add / queue_items / queue_remove + JSON migration
- has_due_attacks vs has_pending_attacks (busy-loop guard in smart_sleep)
- process_attack_queue: per-item removal, retry with backoff, no save-back race
Run with: python -m pytest tests/ -v
"""
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub telegram_notifier so dispatch notifications never leave the test run
_tg_stub = types.ModuleType("telegram_notifier")
_tg_stub.notify_attack_dispatched = lambda *a, **k: None
_tg_stub.notify_attack_failed = lambda *a, **k: None
sys.modules["telegram_notifier"] = _tg_stub

import db_manager
import attack_manager as am
import espionage_manager as em


def _setup_db(tmp_path):
    db_manager.DB_PATH = str(tmp_path / "test.db")
    db_manager._LOGS_DIR = str(tmp_path)
    db_manager._DB_INIT_DONE = False


def _add_attacks(items):
    for it in items:
        db_manager.queue_add("attack", it)


# ── db_manager shared queue primitives ────────────────────────────────────────

def test_queue_add_assigns_id_and_items_roundtrip(tmp_path):
    _setup_db(tmp_path)
    item_id = db_manager.queue_add("attack", {"targetCityId": "9", "queuedAt": 1})
    assert item_id
    items = db_manager.queue_items("attack")
    assert len(items) == 1
    assert items[0]["id"] == item_id
    assert items[0]["targetCityId"] == "9"


def test_queue_add_replaces_by_id(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("attack", {"id": "x1", "retries": 0})
    db_manager.queue_add("attack", {"id": "x1", "retries": 2})
    items = db_manager.queue_items("attack")
    assert len(items) == 1
    assert items[0]["retries"] == 2


def test_queue_remove(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("attack", {"id": "a"})
    db_manager.queue_add("attack", {"id": "b"})
    assert db_manager.queue_remove("attack", ["a"]) == 1
    assert db_manager.queue_remove("attack", ["inexistente"]) == 0
    assert [it["id"] for it in db_manager.queue_items("attack")] == ["b"]


def test_queues_are_isolated_by_name(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("attack", {"id": "a"})
    db_manager.queue_add("spy_recall", {"id": "r"})
    assert len(db_manager.queue_items("attack")) == 1
    assert len(db_manager.queue_items("spy_recall")) == 1
    db_manager.queue_remove("attack", ["a"])
    assert len(db_manager.queue_items("spy_recall")) == 1


def test_migration_imports_legacy_json_and_renames(tmp_path):
    _setup_db(tmp_path)
    legacy = tmp_path / "attack_queue.json"
    with open(legacy, "w") as f:
        json.dump({"pending": [{"id": "old1", "targetCityId": "5"},
                               {"targetCityId": "6", "queuedAt": 2}]}, f)
    items = db_manager.queue_items("attack")  # init_db triggers migration
    ids = {it["id"] for it in items}
    assert "old1" in ids and len(items) == 2
    assert all(it.get("id") for it in items)  # legacy item without id got one
    assert not legacy.exists()
    assert (tmp_path / "attack_queue.json.migrated").exists()


# ── has_due_attacks ───────────────────────────────────────────────────────────

def test_has_due_attacks_false_for_future_only(tmp_path):
    _setup_db(tmp_path)
    _add_attacks([{"id": "a1", "dispatchAfter": int(time.time()) + 3600}])
    assert am.has_pending_attacks() is True
    assert am.has_due_attacks() is False


def test_has_due_attacks_true_when_due(tmp_path):
    _setup_db(tmp_path)
    _add_attacks([
        {"id": "a1", "dispatchAfter": int(time.time()) - 5},
        {"id": "a2", "dispatchAfter": int(time.time()) + 3600},
    ])
    assert am.has_due_attacks() is True


def test_has_due_attacks_false_when_empty(tmp_path):
    _setup_db(tmp_path)
    assert am.has_pending_attacks() is False
    assert am.has_due_attacks() is False


# ── process_attack_queue ──────────────────────────────────────────────────────

def test_future_items_left_untouched(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    _add_attacks([{"id": "fut", "dispatchAfter": int(time.time()) + 3600}])
    dispatched = []
    monkeypatch.setattr(am, "_dispatch_attack",
                        lambda s, i: dispatched.append(i["id"]) or True)

    am.process_attack_queue(session=None, in_active_hours=True)

    assert dispatched == []
    assert [it["id"] for it in db_manager.queue_items("attack")] == ["fut"]


def test_due_item_dispatched_and_removed(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    now = int(time.time())
    _add_attacks([
        {"id": "due1", "dispatchAfter": now - 10,
         "targetPlayerName": "P", "targetCityName": "C"},
        {"id": "fut1", "dispatchAfter": now + 3600},
    ])
    dispatched = []
    monkeypatch.setattr(am, "_dispatch_attack",
                        lambda s, i: dispatched.append(i["id"]) or True)

    am.process_attack_queue(session=None, in_active_hours=True)

    assert dispatched == ["due1"]
    assert {it["id"] for it in db_manager.queue_items("attack")} == {"fut1"}


def test_items_added_during_dispatch_survive(monkeypatch, tmp_path):
    """Race fix: an attack queued by Flask while the bot is mid-dispatch must survive."""
    _setup_db(tmp_path)
    now = int(time.time())
    _add_attacks([{"id": "due1", "dispatchAfter": now - 10,
                   "targetPlayerName": "P", "targetCityName": "C"}])

    def fake_dispatch(session, item):
        db_manager.queue_add("attack", {"id": "new1", "dispatchAfter": now + 60})
        return True

    monkeypatch.setattr(am, "_dispatch_attack", fake_dispatch)
    am.process_attack_queue(session=None, in_active_hours=True)

    assert {it["id"] for it in db_manager.queue_items("attack")} == {"new1"}


def test_failed_dispatch_is_rescheduled(monkeypatch, tmp_path):
    """First failure: item stays with retries=1 and a future dispatchAfter."""
    _setup_db(tmp_path)
    now = int(time.time())
    _add_attacks([{"id": "due1", "dispatchAfter": now - 10,
                   "targetPlayerName": "P", "targetCityName": "C"}])
    monkeypatch.setattr(am, "_dispatch_attack", lambda s, i: False)

    am.process_attack_queue(session=None, in_active_hours=True)

    items = db_manager.queue_items("attack")
    assert len(items) == 1
    assert items[0]["id"] == "due1"
    assert items[0]["retries"] == 1
    assert items[0]["dispatchAfter"] > now


def test_failed_dispatch_removed_after_third_attempt(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    now = int(time.time())
    _add_attacks([{"id": "due1", "dispatchAfter": now - 10, "retries": 2,
                   "targetPlayerName": "P", "targetCityName": "C"}])
    monkeypatch.setattr(am, "_dispatch_attack", lambda s, i: False)

    am.process_attack_queue(session=None, in_active_hours=True)

    assert db_manager.queue_items("attack") == []


# ── attack_log (F1 — histórico de ataques) ────────────────────────────────────

def test_log_attack_roundtrip(tmp_path):
    _setup_db(tmp_path)
    db_manager.log_attack({
        "originCity": "Baphomet", "targetCity": "AlvoCity", "targetPlayer": "JogadorX",
        "islandX": 43, "islandY": 57, "missionType": "army", "targetType": "enemy",
        "source": "manual", "units": {"303": 100}, "transporters": 50, "success": True,
    })
    db_manager.log_attack({
        "originCity": "Baphomet", "targetCity": "OutraCity", "targetPlayer": "JogadorY",
        "missionType": "fleet", "success": False, "error": "types=[11]",
    })
    log = db_manager.get_attack_log()
    assert len(log) == 2
    assert log[0]["target_city"] == "OutraCity"      # newest first
    assert log[0]["success"] is False
    assert log[0]["error"] == "types=[11]"
    assert log[1]["units"] == {"303": 100}
    assert log[1]["success"] is True


def test_get_attack_log_filter_by_target(tmp_path):
    _setup_db(tmp_path)
    db_manager.log_attack({"targetCity": "AlvoCity", "targetPlayer": "JogadorX", "success": True})
    db_manager.log_attack({"targetCity": "OutraCity", "targetPlayer": "JogadorY", "success": True})
    assert len(db_manager.get_attack_log(target="alvo")) == 1
    assert len(db_manager.get_attack_log(target="jogador")) == 2
    assert db_manager.get_attack_log(target="nada") == []


def test_process_attack_queue_writes_log(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    now = int(time.time())
    _add_attacks([{"id": "due1", "dispatchAfter": now - 10, "missionType": "army",
                   "originCityName": "Baphomet", "targetCityName": "AlvoCity",
                   "targetPlayerName": "JogadorX", "units": {"303": 10}}])
    monkeypatch.setattr(am, "_dispatch_attack", lambda s, i: True)

    am.process_attack_queue(session=None, in_active_hours=True)

    log = db_manager.get_attack_log()
    assert len(log) == 1
    assert log[0]["origin_city"] == "Baphomet"
    assert log[0]["target_player"] == "JogadorX"
    assert log[0]["source"] == "manual"
    assert log[0]["success"] is True


def test_failed_attempt_logged_with_error(monkeypatch, tmp_path):
    _setup_db(tmp_path)
    now = int(time.time())
    _add_attacks([{"id": "due1", "dispatchAfter": now - 10,
                   "targetPlayerName": "P", "targetCityName": "C"}])

    def fake_fail(session, item):
        am._last_feedback_text = "O jogador neste momento está inactivo"
        return False

    monkeypatch.setattr(am, "_dispatch_attack", fake_fail)
    am.process_attack_queue(session=None, in_active_hours=True)

    log = db_manager.get_attack_log()
    assert len(log) == 1
    assert log[0]["success"] is False
    assert "inactivo" in log[0]["error"]


# ── has_due_recalls ───────────────────────────────────────────────────────────

def test_has_due_recalls_true_without_next_attempt(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("spy_recall", {"originCityId": "1", "targetCityId": "2"})
    assert em.has_due_recalls() is True


def test_has_due_recalls_false_when_waiting_retry(tmp_path):
    _setup_db(tmp_path)
    db_manager.queue_add("spy_recall", {
        "originCityId": "1", "targetCityId": "2",
        "nextAttemptAfter": int(time.time()) + 600,
    })
    assert em.has_due_recalls() is False


def test_has_due_recalls_false_when_empty(tmp_path):
    _setup_db(tmp_path)
    assert em.has_due_recalls() is False


# ── P5.4: auto-attack wave plans in the SQLite shared_queue (no more JSON race) ──

def test_auto_attack_waves_sqlite_roundtrip(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    monkeypatch.setattr(am, "AUTO_ATTACK_WAVES_PATH", str(tmp_path / "nope.json"))  # no legacy file
    am._wave_upsert({"id": "w1", "state": "PENDING", "targetCityName": "X"})
    am._wave_upsert({"id": "w2", "state": "PENDING", "targetCityName": "Y"})
    assert {w["id"] for w in am._load_auto_attack_waves()["waves"]} == {"w1", "w2"}

    # upsert same id → replace, not duplicate
    am._wave_upsert({"id": "w1", "state": "DONE", "targetCityName": "X"})
    waves = am._load_auto_attack_waves()["waves"]
    assert len(waves) == 2
    assert next(w for w in waves if w["id"] == "w1")["state"] == "DONE"

    # cancel via the same primitive the UI uses → per-item removal
    db_manager.queue_remove("auto_attack_waves", ["w1"])
    assert {w["id"] for w in am._load_auto_attack_waves()["waves"]} == {"w2"}


# ── Auto-attack SKIPPED: poor targets are hidden from the inactives list ─────────

def test_auto_attack_skip_ignores_only_poor_targets(monkeypatch, tmp_path):
    """'Botim insuficiente' skips also auto-ignore the target (it's just noise in the
    inactives list); rich targets skipped for fleet size stay visible."""
    _setup_db(tmp_path)
    mil = tmp_path / "military.json"
    mil.write_text(json.dumps({"byCityName": {}}))
    monkeypatch.setattr(am, "MILITARY_JSON_PATH", str(mil))
    monkeypatch.setattr(am, "_load_auto_attack_settings",
                        lambda: {"enabled": True, "minLootTotal": 50000,
                                 "maxEnemyShipsToEngage": 20})
    monkeypatch.setattr(am, "_load_auto_attack_waves", lambda: {"waves": []})
    skipped = []
    monkeypatch.setattr(am, "_wave_upsert", lambda plan: skipped.append(plan))
    ignored = []
    monkeypatch.setattr(em, "_auto_mark_ignored", lambda *a, **k: ignored.append(a))
    # (getShipCapacity import fails in the test env → evaluate falls back to the default)

    poor = {"state": "DONE", "targetCityId": "10", "targetCityName": "Pobre",
            "targetPlayerName": "Zé", "targetIslandId": "7", "islandX": 40, "islandY": 50,
            "result": {"resources": {"wood": 20000}}, "garrisonResult": {"troops": {}}}
    rich_fleet = {"state": "DONE", "targetCityId": "20", "targetCityName": "Rica",
                  "targetPlayerName": "Rui", "targetIslandId": "8", "islandX": 41, "islandY": 51,
                  "result": {"resources": {"wood": 900000}},
                  "garrisonResult": {"troops": {"Trirreme": 30}}}
    # a disabled (drained) farm target still belongs to the farm → fully off-limits here
    farmed = {"state": "DONE", "targetCityId": "30", "targetCityName": "Drenada",
              "targetPlayerName": "Ana", "targetIslandId": "9", "islandX": 42, "islandY": 52,
              "result": {"resources": {"wood": 800000}}, "garrisonResult": {"troops": {}}}
    db_manager.farm_add({"targetCityId": "30", "targetCityName": "Drenada",
                         "islandX": 42, "islandY": 52, "islandId": "9"})
    db_manager.farm_update("30", {"enabled": 0})
    monkeypatch.setattr(em, "_load_missions", lambda: {"missions": [poor, rich_fleet, farmed]})

    am.evaluate_auto_attacks(session=object())

    assert [w["state"] for w in skipped] == ["AUTO_SKIPPED", "AUTO_SKIPPED"]
    assert {w["targetCityId"] for w in skipped} == {"10", "20"}   # "30" never evaluated
    assert len(ignored) == 1                      # only the poor target is hidden
    assert ignored[0][0] == "10" and "Botim" in ignored[0][4]
