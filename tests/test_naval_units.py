"""
Naval-unit recognition for enemy garrison reports. The garrison spy returns ARMY and FLEET
units in one flat dict, with several land/naval name collisions — these must be counted
correctly. Run with: python -m pytest tests/ -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import attack_manager as am

# Every naval unit in the game (PT names) — all must count as fleet.
NAVAL = [
    "Lança-Chamas", "Aríete a vapor", "Trirreme", "Barco Balista", "Barco Catapulta",
    "Barco Morteiro", "Lança-foguetes", "Submergível", "Lancha rápida", "Porta-balões",
    "Reparador",
]

# Every land unit (PT names) — none may count as fleet, including the collision cases.
LAND = [
    "Hoplita", "Gigante a Vapor", "Lanceiro", "Espadachim", "Fundeiro", "Arqueiro",
    "Fuzileiro", "Aríete", "Catapulta", "Morteiro", "Giracóptero", "Balão-bombardeiro",
    "Cozinheiro", "Médico",
]


def test_each_naval_unit_counts():
    for name in NAVAL:
        assert am._enemy_fleet_count({name: 7}) == 7, f"{name} should count as naval"


def test_no_land_unit_counts():
    for name in LAND:
        assert am._enemy_fleet_count({name: 7}) == 0, f"{name} must NOT count as naval"


def test_land_naval_collisions():
    # land vs naval pairs that share a stem
    assert am._enemy_fleet_count({"Aríete": 10}) == 0
    assert am._enemy_fleet_count({"Aríete a vapor": 10}) == 10
    assert am._enemy_fleet_count({"Gigante a Vapor": 10}) == 0   # land, not "ariete a vapor"
    assert am._enemy_fleet_count({"Catapulta": 5}) == 0
    assert am._enemy_fleet_count({"Barco Catapulta": 5}) == 5
    assert am._enemy_fleet_count({"Morteiro": 3}) == 0
    assert am._enemy_fleet_count({"Barco Morteiro": 3}) == 3
    assert am._enemy_fleet_count({"Balão-bombardeiro": 4}) == 0
    assert am._enemy_fleet_count({"Porta-balões": 4}) == 4


def test_mixed_garrison_counts_only_fleet():
    garrison = {
        "Hoplita": 100, "Aríete": 5, "Catapulta": 2, "Gigante a Vapor": 8,  # land
        "Lancha rápida": 48, "Aríete a vapor": 10, "Barco Catapulta": 3,    # naval
    }
    assert am._enemy_fleet_count(garrison) == 48 + 10 + 3


def test_the_rock_case():
    # Δ The Rock Δ: 48 fast boats — the F4.b test target
    assert am._enemy_fleet_count({"Lancha rápida": 48}) == 48


def test_accent_insensitive():
    # accent-stripped names (some report encodings) still match
    assert am._enemy_fleet_count({"Submergivel": 2}) == 2
    assert am._enemy_fleet_count({"Ariete a vapor": 2}) == 2


def test_empty_and_none():
    assert am._enemy_fleet_count({}) == 0
    assert am._enemy_fleet_count(None) == 0


# ── Fleet classification: flee (lancha/reparador) vs combat (everything else naval) ──

def test_classify_empty():
    assert am._classify_enemy_fleet({}) == (0, 0)
    assert am._classify_enemy_fleet(None) == (0, 0)


def test_classify_flee_only():
    # The Rock: lanchas + reparadores → all flee, zero combat → F4.b applies
    combat, flee = am._classify_enemy_fleet({"Lancha rápida": 48, "Reparador": 92})
    assert combat == 0 and flee == 140


def test_classify_combat_present():
    # any real warship → counts as combat → farm must skip + alert
    combat, flee = am._classify_enemy_fleet({"Lancha rápida": 48, "Aríete a vapor": 5})
    assert combat == 5 and flee == 48


def test_classify_ignores_land_units():
    combat, flee = am._classify_enemy_fleet(
        {"Hoplita": 100, "Gigante a Vapor": 8, "Lancha rápida": 10})
    assert combat == 0 and flee == 10


def test_classify_only_combat():
    combat, flee = am._classify_enemy_fleet({"Trirreme": 3, "Barco Morteiro": 2})
    assert combat == 5 and flee == 0
