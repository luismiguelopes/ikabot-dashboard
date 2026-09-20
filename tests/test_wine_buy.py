"""
Wine market buyer (F10): buys wine from player offers to keep the empire stocked,
inside hard guards — price ceiling, gold floor, per-cycle spend cap — and a dry-run
that plans without spending. Roles stay split from the balancer (buy vs. distribute).
"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "telegram_notifier" not in sys.modules:
    sys.modules["telegram_notifier"] = types.ModuleType("telegram_notifier")

import transport_manager as tm


def _offer(seller, city, amount, price):
    return {"jugadorAComprar": seller, "ciudadDestino": city, "amountAvailable": amount,
            "tipo": "wine", "precio": price, "destinationCityId": "9", "cityId": "1",
            "position": "0", "type": "1", "resource": "1"}


def _run(monkeypatch, tmp_path, resources, offers, settings, gold=1_000_000, ships=100):
    import queue_processor as qp
    import farm_manager as fm
    import empire_utils
    import ikabot.helpers.naval as naval
    import ikabot.helpers.pedirInfo as pedir

    calls = []
    # Fake the market/buyResources modules: importing the real ones pulls `requests`
    # (via botComm), absent from the test venv. process_wine_buyer imports these at
    # call time, so injecting them into sys.modules is enough.
    market = types.ModuleType("ikabot.helpers.market")
    market.getCommercialCities = lambda s: [{"id": 1, "name": "C1", "pos": 0, "rango": 5}]
    market.getGold = lambda s, c: (gold, 0)
    buyres = types.ModuleType("ikabot.function.buyResources")
    buyres.getOffers = lambda s, c: list(offers)
    buyres.buy = lambda session, city, offer, amt, ships_av, cap: calls.append((offer["precio"], amt))
    monkeypatch.setitem(sys.modules, "ikabot.helpers.market", market)
    monkeypatch.setitem(sys.modules, "ikabot.function.buyResources", buyres)

    own = [{"name": n, "cityId": i + 1, "islandId": "9"} for i, n in enumerate(resources)]
    own_path = tmp_path / "own.json"
    own_path.write_text(json.dumps(own))
    monkeypatch.setattr(tm, "OWN_CITIES_PATH", str(own_path))
    monkeypatch.setattr(tm, "WINE_BUY_STATUS_PATH", str(tmp_path / "status.json"))

    st = {"enabled": True, "dryRun": False, "targetHours": 72, "refillBelowHours": 48,
          "maxPricePerUnit": 15, "goldFloor": 100000, "maxSpendPerCycle": 200000,
          "ignoreCityIds": []}
    st.update(settings or {})
    monkeypatch.setattr(tm, "get_wine_buy_settings", lambda: st)
    monkeypatch.setattr(empire_utils, "is_paused", lambda: False)
    monkeypatch.setattr(qp, "_load_resources_json", lambda: resources)
    monkeypatch.setattr(pedir, "getShipCapacity", lambda s: (500, 2500), raising=False)
    monkeypatch.setattr(naval, "getAvailableShips", lambda s: ships, raising=False)
    monkeypatch.setattr(fm, "apply_ship_reserve", lambda n, label, now=None: n)
    monkeypatch.setattr(tm, "_set_market_resource", lambda s, c, r: None)
    monkeypatch.setattr(tm.time, "sleep", lambda *a, **k: None)

    tm.process_wine_buyer(session=object(), in_active_hours=True)
    status = json.loads((tmp_path / "status.json").read_text())
    return calls, status


def _city(cons, stock):
    return {"Wine": stock, "wineConsumptionPerHour": cons, "wineProductionPerHour": 0,
            "wineRunsOutIn": -1 if cons == 0 else 1}


def test_dry_run_plans_but_buys_nothing(monkeypatch, tmp_path):
    resources = {"A": _city(300, 0)}                 # needs 300*72 = 21600
    offers = [_offer("Seller", "A", 50000, 8)]
    calls, status = _run(monkeypatch, tmp_path, resources, offers, {"dryRun": True})
    assert calls == []                               # nothing actually bought
    assert status["dryRun"] is True
    assert status["bought"] == 21600                 # full deficit planned
    assert status["spent"] == 21600 * 8


def test_real_buy_within_budget(monkeypatch, tmp_path):
    resources = {"A": _city(300, 0)}                 # deficit 21600
    offers = [_offer("Seller", "A", 50000, 8)]
    calls, status = _run(monkeypatch, tmp_path, resources, offers, {"dryRun": False})
    assert len(calls) == 1 and calls[0] == (8, 21600)
    assert status["spent"] == 21600 * 8 and status["bought"] == 21600


def test_price_ceiling_blocks_expensive_offers(monkeypatch, tmp_path):
    resources = {"A": _city(300, 0)}
    offers = [_offer("Seller", "A", 50000, 40)]      # 40 > ceiling 15
    calls, status = _run(monkeypatch, tmp_path, resources, offers, {"dryRun": False, "maxPricePerUnit": 15})
    assert calls == [] and status["bought"] == 0
    assert "tecto" in status["note"]


def test_gold_floor_is_never_crossed(monkeypatch, tmp_path):
    resources = {"A": _city(300, 0)}                 # deficit 21600 units
    offers = [_offer("Seller", "A", 50000, 8)]
    # gold just 40000 above the floor -> at most 40000/8 = 5000 units
    calls, status = _run(monkeypatch, tmp_path, resources, offers,
                         {"dryRun": False, "goldFloor": 100000}, gold=140000)
    assert status["spent"] <= 40000
    assert status["bought"] == 5000


def test_spend_cap_limits_the_cycle(monkeypatch, tmp_path):
    resources = {"A": _city(300, 0)}
    offers = [_offer("Seller", "A", 50000, 8)]
    calls, status = _run(monkeypatch, tmp_path, resources, offers,
                         {"dryRun": False, "maxSpendPerCycle": 16000})
    assert status["spent"] <= 16000
    assert status["bought"] == 2000                  # 16000 / 8


def test_no_deficit_is_a_noop(monkeypatch, tmp_path):
    resources = {"A": _city(300, 300 * 100)}         # far above 72h target
    offers = [_offer("Seller", "A", 50000, 8)]
    calls, status = _run(monkeypatch, tmp_path, resources, offers, {"dryRun": False})
    assert calls == [] and status["bought"] == 0 and status["deficit"] == 0


def test_deadband_skips_city_above_low_water(monkeypatch, tmp_path):
    """Inside the deadband (stock >= refillBelowHours of consumption): buy nothing,
    even though the city is below the fill target — avoids constant tiny top-ups."""
    resources = {"A": _city(300, 300 * 50)}          # 50h; below target 72 but above refill 48
    offers = [_offer("Seller", "A", 50000, 8)]
    calls, status = _run(monkeypatch, tmp_path, resources, offers,
                         {"dryRun": False, "targetHours": 72, "refillBelowHours": 48})
    assert calls == [] and status["bought"] == 0 and status["deficit"] == 0


def test_deadband_refills_to_target_when_below_low_water(monkeypatch, tmp_path):
    """Once below the low-water mark, buy a full batch up to the target (not just back
    to the low-water mark)."""
    resources = {"A": _city(300, 300 * 40)}          # 40h < refill 48 -> buy up to 72h
    offers = [_offer("Seller", "A", 50000, 8)]
    calls, status = _run(monkeypatch, tmp_path, resources, offers,
                         {"dryRun": False, "targetHours": 72, "refillBelowHours": 48})
    assert status["bought"] == 300 * (72 - 40)       # 9600
    assert len(calls) == 1 and calls[0] == (8, 9600)
