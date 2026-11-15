"""
P13.25: building costs are read once per building TYPE (from the city where it is highest),
not once per building per city; each city's reducer buildings are applied locally.
"""
import json
import os
import sys
import types
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("telegram_notifier", types.ModuleType("telegram_notifier"))

import costs_collector as cc
import db_manager

_MATERIALS = ["wood", "wine", "marble", "glass", "sulfur"]


def _table_html(first, last, base):
    """A cost page listing levels first..last: wood = base*level, marble = 2*base*level."""
    head = ('<th class="costs"><img src="//cdn/wood.png"/></th>'
            '<th class="costs"><img src="//cdn/marble.png"/></th>'
            '<th class="costs"><img src="//cdn/time.png"/></th>')
    rows = "".join(
        '<td class="level">%d</td>\n <td class="costs"><div class="x"><div>%s</div></div></td>'
        '\n <td class="costs"><div class="x"><div>%s</div></div></td>'
        % (lv, "{:,}".format(base * lv), "{:,}".format(2 * base * lv))
        for lv in range(first, last + 1))
    return head + rows


def _index_html(types_):
    return "".join(
        '<div class=" button_building %s" onmouseover="$(this).addClass(\'hover\');" '
        'onmouseout="$(this).removeClass(\'hover\');" '
        'onclick="ajaxHandlerCall(\'?view=buildingDetail&buildingId=%s&\');' % (t, t)
        for t in types_)


class _Session:
    """Fake game. Like the real one, the cost table is a window around the level the building
    has in the city whose index page was opened last: [level - 3, level + 10]."""
    def __init__(self, cities):
        self.cities, self.current, self.index_city, self.posts = cities, None, None, []

    def getSessionData(self):
        return {"reduccion_inv_max": True}            # research discount 14% → factor 0.86

    def get(self, url=""):
        self.current = int(url.split("cityId=")[1])
        return self.current

    def post(self, url):
        self.posts.append((self.current, url))
        if "buildingId=0" in url:
            self.index_city = self.current
            return json.dumps([0, ["changeView", ["buildingDetail", _index_html(["academy", "tavern"])]]])
        btype = url.split("buildingId=")[1].split("&")[0]
        level = min(b["level"] for b in self.cities[self.index_city]["position"] if b["building"] == btype)
        return json.dumps([0, ["changeView", ["buildingDetail",
                           _table_html(max(1, level - 3), level + 10, 100 if btype == "academy" else 7)]]])


def _city(cid, name, academy, tavern, carpentry=0):
    pos = [{"name": "Academia", "building": "academy", "level": academy},
           {"name": "Taberna", "building": "tavern", "level": tavern},
           {"name": "empty", "building": "empty", "level": 0}]
    if carpentry:
        pos.append({"name": "Carpintaria", "building": "carpentering", "level": carpentry,
                    "isMaxLevel": True})
    return {"id": cid, "cityName": name, "position": pos}


def _run(monkeypatch, cities, previous=None, fail=()):
    session = _Session(cities)
    saved = {}

    def get_city(cid):
        if cid in fail:
            raise RuntimeError("city view failed")
        return cities[cid]
    monkeypatch.setattr(cc, "getCity", get_city)
    monkeypatch.setattr(cc.time, "sleep", lambda *a, **k: None)
    stock = types.ModuleType("ikabot.function.constructionList")

    def reducers(city):
        r = [0] * 5
        for b in city["position"]:
            if b["building"] == "carpentering":
                r[0] = b["level"]
        return r
    stock.getCostsReducers = reducers
    downloads = []

    def checkhash(url):
        downloads.append(url)
        return url.rsplit("/", 1)[1].split(".")[0]
    stock.checkhash = checkhash
    monkeypatch.setitem(sys.modules, "ikabot.function.constructionList", stock)
    monkeypatch.setattr(db_manager, "save_building_costs", lambda d: saved.update(d))
    monkeypatch.setattr(db_manager, "get_building_costs", lambda: {"cities": previous or {}})
    cc.collect_building_costs(session, list(cities) + list(fail))
    return session, saved.get("cities"), downloads


def test_each_type_is_read_once_from_the_city_where_it_is_lowest(monkeypatch):
    cities = {1: _city(1, "A", academy=5, tavern=20), 2: _city(2, "B", academy=12, tavern=13),
              3: _city(3, "C", academy=7, tavern=19)}
    session, costs, downloads = _run(monkeypatch, cities)
    table_reads = [(cid, u.split("buildingId=")[1].split("&")[0]) for cid, u in session.posts
                   if "buildingId=0" not in u]
    assert sorted(table_reads) == [(1, "academy"), (2, "tavern")]      # 2 reads, not 6
    assert len(downloads) == 2                                         # icons resolved once each
    # every city has its NEXT level, priced from the shared table
    for name, c in (("A", cities[1]), ("B", cities[2]), ("C", cities[3])):
        for b in c["position"][:2]:
            assert str(b["level"] + 1) in costs[name][b["name"]]["costs"], (name, b["name"])
    assert costs["B"]["Academia"]["currentLevel"] == 12
    assert costs["A"]["Academia"]["costs"]["6"] == {"wood": 600, "wine": 0, "marble": 1200,
                                                    "glass": 0, "sulfur": 0}
    assert costs["C"]["Taberna"]["costs"]["20"]["wood"] == 140


def test_city_reducers_are_applied_per_city(monkeypatch):
    cities = {1: _city(1, "A", academy=5, tavern=1, carpentry=20), 2: _city(2, "B", academy=5, tavern=1)}
    _s, costs, _d = _run(monkeypatch, cities)
    plain = costs["B"]["Academia"]["costs"]["6"]["wood"]
    reduced = costs["A"]["Academia"]["costs"]["6"]["wood"]
    assert plain == 600
    # shown 600 already has the 14% research discount; the carpenter takes 20% of the original
    import math
    assert reduced == math.ceil(Decimal(600) - Decimal(600) / Decimal("0.86") * Decimal("0.20"))
    assert costs["A"]["Academia"]["costs"]["6"]["marble"] == 1200      # carpenter is wood only


def test_city_beyond_the_shared_window_reads_its_own(monkeypatch):
    """The window read from the lowest city reaches 10 levels up here: a city further than
    that does not find its next level on it and reads the table from its own index."""
    cities = {1: _city(1, "A", academy=5, tavern=1), 2: _city(2, "B", academy=30, tavern=1)}
    session, costs, _d = _run(monkeypatch, cities)
    academy_reads = [cid for cid, u in session.posts if "buildingId=academy" in u]
    assert academy_reads == [1, 2]
    assert "6" in costs["A"]["Academia"]["costs"] and "31" in costs["B"]["Academia"]["costs"]


def test_unread_city_keeps_its_previous_costs(monkeypatch):
    cities = {1: _city(1, "A", academy=5, tavern=1)}
    old = {"Gone": {"Academia": {"currentLevel": 3, "costs": {"4": {"wood": 1}}}}}
    _s, costs, _d = _run(monkeypatch, cities, previous=old, fail=(9,))
    assert costs["Gone"] == old["Gone"] and "A" in costs
    # nothing failed → a city no longer ours is not carried over
    _s, costs, _d = _run(monkeypatch, cities, previous=old)
    assert "Gone" not in costs
