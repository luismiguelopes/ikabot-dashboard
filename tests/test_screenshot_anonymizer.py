"""The README screenshot anonymizer must never let a real name through."""
import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "tools" / "screenshots" / "anonymize.py"
_spec = importlib.util.spec_from_file_location("screenshot_anonymize", _PATH)
anonymize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(anonymize)

DATA = {
    "empireData": {"Homeport": {"Academia": "30", "Armazém": "32"},
                   "Dryport": {"Academia": "28", "Armazém": "30"}},
    "resourcesData": {"Homeport": {"Crystal": 3160, "Wine": 100},
                      "Dryport": {"Crystal": 10, "Wine": 5}},
}
MILITARY = {"byCityName": {"Homeport": {"troops": {"s303": {"name": "Hoplita", "count": 5}},
                                        "fleet": {}}}}
MOVEMENTS = [
    {"origin": "Homeport (PlayerReal)", "destination": "target A (TARGET PLAYER)",
     "isOwn": True},
]
OTHERS = [
    {"players": [{"playerName": "TARGET PLAYER", "cityName": "target A",
                  "islandName": "Realisle", "allyTag": "ABCD", "islandX": 50, "islandY": 1},
                 {"playerName": "Crystal", "cityName": "wine"}]},
    {"telegram": {"botToken": "123:secret", "chatId": "42"}},
]


def _anon(**kw):
    kw.setdefault("scale", 0.5)
    a = anonymize.Anonymizer(**kw)
    a.seed(DATA, MILITARY, MOVEMENTS, OTHERS)
    return a


def _dump(o):
    return json.dumps(o, ensure_ascii=False)


def test_own_cities_and_player_get_fictional_names():
    a = _anon()
    out = a.transform(MOVEMENTS)
    assert out[0]["origin"] == f"{a.map['Homeport']} ({anonymize.OWN_PLAYER_FAKE})"
    assert a.own_player == "PlayerReal"
    assert set(a.transform(DATA)["empireData"]) == {a.map["Homeport"], a.map["Dryport"]}


def test_no_real_name_survives_in_any_payload():
    a = _anon()
    for payload in (DATA, MILITARY, MOVEMENTS, *OTHERS):
        text = _dump(a.transform(payload))
        assert not a.leaks(text)
        for real in ("Homeport", "Dryport", "PlayerReal", "TARGET PLAYER", "target A",
                     "Realisle"):
            assert real not in text


def test_resource_keys_survive_and_quantities_are_scaled():
    a = _anon()
    city = a.transform(DATA)["resourcesData"][a.map["Homeport"]]
    # a player called "Crystal" must not rename the crystal resource
    assert city == {"Crystal": 1580, "Wine": 50}


def test_ids_times_and_small_numbers_are_not_scaled():
    a = _anon()
    out = a.transform({"cityId": 30825, "arrivalTime": 1795703989, "timeLeft": 4000,
                       "lastUpdatedTs": 1795700000, "count": 26, "gold": 13000000,
                       "amount": "12.850"})
    assert out == {"cityId": 30825, "arrivalTime": 1795703989, "timeLeft": 4000,
                   "lastUpdatedTs": 1795700000, "count": 26, "gold": 6500000,
                   "amount": "6.425"}


def test_game_terms_are_shown_in_english():
    a = _anon()
    out = a.transform(DATA)
    assert set(out["empireData"][a.map["Homeport"]]) == {"Academy", "Warehouse"}
    unit = a.transform(MILITARY)["byCityName"][a.map["Homeport"]]["troops"]["s303"]
    assert unit["name"] == "Hoplite"
    assert a.text("Pilhar (em curso)") == "Pillage (underway)"
    assert a.text("Mercado Negro") == "Black Market"


def test_own_cities_beyond_the_cap_are_left_out():
    a = _anon(keep_cities=1)
    assert a.dropped == {"Homeport"}           # sorted: Dryport is kept
    out = a.transform(DATA)
    assert list(out["empireData"]) == [a.map["Dryport"]]
    rows = a.transform([{"cityName": "Homeport"}, {"cityName": "Dryport"}])
    assert rows == [{"cityName": a.map["Dryport"]}]


def test_coordinates_alliances_and_secrets():
    a = _anon()
    player = a.transform(OTHERS[0])["players"][0]
    assert (player["islandX"], player["islandY"]) == (a.coord(50), a.coord(1))
    assert player["islandX"] != 50 and 1 <= player["islandX"] <= 100
    assert player["allyTag"] != "ABCD" and player["allyTag"].isupper()
    assert a.text("at [50:1]") == f"at [{a.coord(50)}:{a.coord(1)}]"
    tg = a.transform(OTHERS[1])["telegram"]
    assert tg == {"botToken": "", "chatId": ""}


def test_names_inside_free_text_are_replaced_whole_word_only():
    a = _anon()
    assert a.text("Raid on target A done") == f"Raid on {a.map['target A']} done"
    assert a.text("Homeports") == "Homeports"


def test_same_real_name_maps_to_same_fake_and_fakes_are_unique():
    a = _anon()
    fakes = list(a.map.values())
    assert len(fakes) == len(set(fakes))
    assert not set(fakes) & set(a.map)
