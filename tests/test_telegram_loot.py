import importlib.util
import os
import time

# Other test modules stub "telegram_notifier" in sys.modules (so no alert leaves a test run);
# load the REAL module from its file under a private name so this test is order-independent.
_spec = importlib.util.spec_from_file_location(
    "_real_telegram_notifier",
    os.path.join(os.path.dirname(__file__), "..", "bot", "telegram_notifier.py"))
tn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tn)


def test_loot_message_names_city_player_and_island():
    """The loot alert used to read 'Gates of Midian ← RxDxR' — the player name where the
    plundered place belonged. It must name the city, its owner and the island coordinates."""
    msg = tn.format_returned_loot("Castle-M", "RxDxR", "Gates of Midian",
                                  [72517, 22844, 72407, 886, 37979], coords=(46, 37))
    assert "Castle-M (RxDxR) [46:37] → Gates of Midian" in msg
    assert "🪵 72.517" in msg and "🍷 22.844" in msg and "🪨 72.407" in msg
    assert "💎 886" in msg and "🌋 37.979" in msg
    assert "Total: <b>206.633</b>" in msg


def test_loot_message_skips_empty_resources_and_unknown_coords():
    msg = tn.format_returned_loot("Tróia 3", "MARCOS LIMA", "Baphomet", [1000, 0, 0, 0, 0])
    assert "Tróia 3 (MARCOS LIMA) → Baphomet" in msg
    assert "🍷" not in msg and "[" not in msg.split("\n")[1]


def test_loot_message_shows_arrival_time():
    ts = int(time.mktime((2026, 11, 10, 16, 24, 0, 0, 0, -1)))
    msg = tn.format_returned_loot("A", "B", "C", [1, 0, 0, 0, 0], arrival_ts=ts)
    assert "chega às 16:24" in msg
