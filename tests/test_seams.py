"""
P13.44 (2) and (4): the seams that had only been tested one side at a time.

(2) movements collector ↔ farm. A raid's fate is read from what the collector SAW. With the
    real collector and a real captured military-advisor page:
      • a failed read leaves movements.json alone and the farm decides nothing on it;
      • a return seen with loot releases the target normally;
      • a pillage seen coming home EMPTY — and only that — makes it a fleet target.
(4) Two writers on the same store at the same time (bot and dashboard are separate processes;
    threads on separate connections exercise the same locking and merge).
"""
import json
import os
import sys
import threading
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("telegram_notifier", types.ModuleType("telegram_notifier"))

import db_manager
import empire_collector as ec
import farm_manager as fm
import tests.test_farm as base

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "military_advisor.json")


_FIXTURE_ARRIVAL = 1794690448          # when the two pillage returns in the fixture dock


class _Game:
    """The military advisor: down, or answering with the captured page."""
    def __init__(self):
        self.down = True

    def post(self, *a, **k):
        if self.down:
            raise RuntimeError("rede em baixo")
        with open(_FIXTURE, encoding="utf-8") as f:
            return f.read()


def _raid_out(monkeypatch, tmp_path, city_id, name):
    """A farm target whose raid is due home a minute ago; movements.json is 20 minutes old.
    The raid left two hours before the returns in the captured page dock (the collector dates
    a return by its arrival)."""
    base._setup_db(tmp_path)
    now = int(time.time())
    left = _FIXTURE_ARRIVAL - 7200
    db_manager.farm_add({"targetCityId": city_id, "targetCityName": name})
    db_manager.farm_update(city_id, {"state": "ATTACKING", "attack_return_at": now - 60,
                                     "last_attack_at": left, "swept_at": left - 1800,
                                     "is_fleet_target": 0})
    db_manager.log_attack({"ts": left + 100, "originCity": "Home", "targetCity": name,
                           "targetCityId": city_id, "missionType": "army", "source": "farm",
                           "units": {"s303": 10}, "transporters": 20, "success": True})
    real_refresh = ec.refresh_movements
    base._common_patches(monkeypatch, tmp_path)
    monkeypatch.setattr(ec, "refresh_movements", real_refresh)          # the REAL collector
    monkeypatch.setattr(ec, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(ec, "save_capture", lambda *a, **k: None)
    monkeypatch.setattr(ec, "_load_alert_settings",
                        lambda: {"returnEnabled": False, "incomingEnabled": False})
    monkeypatch.setattr(ec.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(fm.process_farm_targets, "_atk_mv_refresh", 0, raising=False)
    path = tmp_path / "movements.json"
    path.write_text(json.dumps([{"isOwn": False, "direction": "->", "destination": "Z (W)"}]))
    old = time.time() - 20 * 60
    os.utime(path, (old, old))
    return path, now


def _pass(monkeypatch, game):
    monkeypatch.setattr(fm.process_farm_targets, "_atk_mv_refresh", 0, raising=False)
    fm.process_farm_targets(session=game, in_active_hours=True)


def test_failed_movements_read_decides_nothing_then_a_seen_return_releases_the_target(
        monkeypatch, tmp_path):
    path, now = _raid_out(monkeypatch, tmp_path, "28208", "Alvo 3")
    before = path.read_text()
    game = _Game()

    _pass(monkeypatch, game)                                  # the read fails
    assert path.read_text() == before                         # file untouched, not emptied
    t = db_manager.farm_get("28208")
    assert t["state"] == "ATTACKING"                          # still waiting for the raid
    assert not t["is_fleet_target"] and t["swept_at"] > 0     # no verdict on missing data
    assert t["attack_return_at"] > now                        # looks again in a few minutes
    assert db_manager.get_loot_log() == []

    game.down = False                                         # the read works again
    db_manager.farm_update("28208", {"attack_return_at": now - 60})
    _pass(monkeypatch, game)
    assert len(json.loads(path.read_text())) == 4
    t = db_manager.farm_get("28208")
    assert t["state"] == "IDLE" and t["next_action"] == "attack"     # loot seen → next round
    assert not t["is_fleet_target"] and t["swept_at"] > 0


def test_only_an_empty_pillage_seen_by_the_collector_makes_a_fleet_target(monkeypatch, tmp_path):
    _, now = _raid_out(monkeypatch, tmp_path, "99001", "Alvo 9")
    game = _Game()
    game.down = False
    _pass(monkeypatch, game)
    t = db_manager.farm_get("99001")
    assert t["state"] == "IDLE" and t["next_action"] == "spy" and t["is_fleet_target"] == 1


# ── (4) concurrent writers ───────────────────────────────────────────────────────

def _run_threads(workers):
    errors = []

    def guarded(fn):
        def run():
            try:
                fn()
            except Exception as e:                # pragma: no cover - reported below
                errors.append(repr(e))
        return run
    threads = [threading.Thread(target=guarded(w)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []


def test_many_writers_on_the_mission_store_lose_nothing(monkeypatch, tmp_path):
    base._setup_db(tmp_path)
    n, rounds = 6, 15
    db_manager.missions_save({"missions": [{"id": "m%d" % i, "targetCityId": str(i), "state": "X",
                                            "n": 0} for i in range(n)]})

    def writer(i):
        def run():
            for r in range(1, rounds + 1):
                data = db_manager.missions_load()
                mine = next(m for m in data["missions"] if m["id"] == "m%d" % i)
                mine["n"] = r                             # its own mission…
                mine["w%d" % i] = r
                if r == rounds:                           # …and, at the end, a new one
                    data["missions"].append({"id": "new%d" % i, "state": "NEW"})
                time.sleep(0.001)                         # hold the stale copy a moment
                db_manager.missions_save(data)
        return run

    _run_threads([writer(i) for i in range(n)])
    final = {m["id"]: m for m in db_manager.missions_load()["missions"]}
    assert len(final) == 2 * n
    for i in range(n):
        assert final["m%d" % i]["n"] == rounds and final["m%d" % i]["w%d" % i] == rounds
        assert final["new%d" % i]["state"] == "NEW"


def test_many_writers_on_the_building_queue_lose_nothing(monkeypatch, tmp_path):
    base._setup_db(tmp_path)
    monkeypatch.setattr(db_manager, "_touch_queue_file", lambda *a, **k: None, raising=False)
    db_manager.save_queue({"enabled": True, "inProgress": {}, "transportErrors": {}, "queues": {}})
    n, rounds = 5, 8

    def writer(i):
        def run():
            city = "Cidade%d" % i
            for r in range(rounds):
                q = db_manager.load_queue()
                q["queues"].setdefault(city, []).append(
                    {"building": "Edificio%d" % r, "targetLevel": r + 1, "addedAt": r})
                time.sleep(0.001)
                db_manager.save_queue(q)
        return run

    _run_threads([writer(i) for i in range(n)])
    final = db_manager.load_queue()["queues"]
    for i in range(n):
        assert [x["building"] for x in final["Cidade%d" % i]] == ["Edificio%d" % r for r in range(rounds)]
