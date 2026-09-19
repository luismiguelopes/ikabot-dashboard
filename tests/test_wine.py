"""
Wine balancer source selection: producers (runway ∞) first; in empires with NO wine
producers (every city a net consumer — the live case), cities whose runway exceeds
donorReserveHours lend the surplus above it.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "telegram_notifier" not in sys.modules:
    sys.modules["telegram_notifier"] = types.ModuleType("telegram_notifier")

import transport_manager as tm


def _run(monkeypatch, tmp_path, resources, settings=None):
    """Drive process_wine_balancer with every seam stubbed; returns dispatched transports."""
    import json
    import queue_processor as qp
    import farm_manager as fm
    import empire_utils
    import ikabot.helpers.naval as naval
    import ikabot.helpers.pedirInfo as pedir

    own = [{"name": n, "cityId": i + 1, "islandId": "9"} for i, n in enumerate(resources)]
    own_path = tmp_path / "own.json"
    own_path.write_text(json.dumps(own))
    monkeypatch.setattr(tm, "OWN_CITIES_PATH", str(own_path))

    st = {"enabled": True, "thresholdHours": 12, "targetHours": 48, "donorReserveHours": 96}
    st.update(settings or {})
    monkeypatch.setattr(tm, "get_wine_settings", lambda: st)
    monkeypatch.setattr(empire_utils, "is_paused", lambda: False)
    monkeypatch.setattr(qp, "_load_resources_json", lambda: resources)
    monkeypatch.setattr(naval, "getAvailableShips", lambda s: 50, raising=False)
    monkeypatch.setattr(pedir, "getShipCapacity", lambda s: (5000, 25000), raising=False)
    monkeypatch.setattr(fm, "apply_ship_reserve", lambda ships, label, now=None: ships)
    monkeypatch.setattr(tm.time, "sleep", lambda *a, **k: None)

    sent = []
    def _dispatch(session, src_id, dest_id, island, ships, res):
        sent.append({"src": src_id, "dest": dest_id, "wine": res[1]})
        return True
    monkeypatch.setattr(qp, "_dispatch_transport", _dispatch)

    tm.process_wine_balancer(session=object(), in_active_hours=True)
    return sent, {c["name"]: c["cityId"] for c in own}


def _city(cons, stock):
    runs_out = -1 if cons == 0 else int(stock / cons * 3600)
    return {"Wine": stock, "wineConsumptionPerHour": cons, "wineRunsOutIn": runs_out}


def test_surplus_donor_feeds_needy_without_producers(monkeypatch, tmp_path):
    """No producers anywhere: the huge-surplus city (runway 2293h) tops up the critical one."""
    resources = {
        "Emperor":   _city(292, 292 * 8),        # ~8h runway → needy
        "Doomentia": _city(335, 335 * 2293),     # massive surplus → donor
        "DeathCrow": _city(272, 272 * 23),       # 23h — neither needy nor donor
    }
    sent, ids = _run(monkeypatch, tmp_path, resources)
    assert len(sent) == 1
    assert sent[0]["src"] == ids["Doomentia"] and sent[0]["dest"] == ids["Emperor"]
    assert sent[0]["wine"] == 292 * 48 - 292 * 8          # topped up to 48h


def test_donor_keeps_its_reserve(monkeypatch, tmp_path):
    """A donor lends only what exceeds donorReserveHours of its own consumption."""
    resources = {
        "Emperor": _city(292, 292 * 8),
        "Gates":   _city(272, 272 * 100),        # 100h runway, floor 96h → spare 4h×272
    }
    sent, _ = _run(monkeypatch, tmp_path, resources)
    assert len(sent) == 1
    assert sent[0]["wine"] == 272 * 4                     # only the surplus above 96h


def test_producer_still_first_choice(monkeypatch, tmp_path):
    """When a real producer exists it is drained before any surplus donor.
    A producer is identified by wineProductionPerHour > 0, not merely runway == -1."""
    resources = {
        "Emperor":  _city(292, 292 * 8),
        "Produtora": {"Wine": 100000, "wineConsumptionPerHour": 50,
                      "wineProductionPerHour": 100, "wineRunsOutIn": -1},
        "Doomentia": _city(335, 335 * 2293),
    }
    sent, ids = _run(monkeypatch, tmp_path, resources)
    assert sent[0]["src"] == ids["Produtora"]


def _emptied(stock):
    """A city that has run dry: it produces no wine and its live consumption reads 0
    only because there is none left to serve (runway therefore -1)."""
    return {"Wine": stock, "wineConsumptionPerHour": 0,
            "wineProductionPerHour": 0, "wineRunsOutIn": -1}


def test_emptied_city_is_topped_up(monkeypatch, tmp_path):
    """An emptied city (cons 0, prod 0, runway -1) is fed, sized from the sister
    cities' median consumption since its own live consumption reads 0."""
    resources = {
        "Emperor":   _emptied(54),               # ran dry
        "Doomentia": _city(335, 335 * 2293),     # big surplus donor (only consumer → median 335)
    }
    sent, ids = _run(monkeypatch, tmp_path, resources)
    assert len(sent) == 1
    assert sent[0]["dest"] == ids["Emperor"] and sent[0]["src"] == ids["Doomentia"]
    assert sent[0]["wine"] == 335 * 48 - 54      # primed to targetHours of the median


def test_emptied_city_never_donates(monkeypatch, tmp_path):
    """A non-consuming city is never used as a source — the old code treated runway -1
    as a 'producer' and could ship away the last drops of an already-dry city."""
    resources = {
        "Vampiria": _city(292, 292 * 8),         # needy, still draining
        "Emperor":  _emptied(5000),              # cons 0, prod 0 — must NOT be drained
    }
    sent, _ = _run(monkeypatch, tmp_path, resources)
    assert sent == []                            # Emperor's wine is protected, not lent out


def test_below_floor_city_never_lends(monkeypatch, tmp_path):
    """A city under the donor floor is untouched even when another city starves."""
    resources = {
        "Emperor":   _city(292, 292 * 8),
        "DeathCrow": _city(272, 272 * 50),       # 50h < floor 96h → not a donor
    }
    sent, _ = _run(monkeypatch, tmp_path, resources)
    assert sent == []
