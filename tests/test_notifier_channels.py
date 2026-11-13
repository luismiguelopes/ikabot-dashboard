"""F15 phase 1: the notifier fans every alert out to Telegram AND Discord, each channel
isolated from the other, with Discord embeds coloured by severity."""
import importlib.util
import json
import os

_spec = importlib.util.spec_from_file_location(
    "_real_notifier_channels",
    os.path.join(os.path.dirname(__file__), "..", "bot", "telegram_notifier.py"))
tn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tn)

HOOK = "https://discord.com/api/webhooks/123/abc-DEF_9"


def _setup(monkeypatch, tmp_path, settings=None, stock=None, env=None):
    sp = tmp_path / "telegram_settings.json"
    if settings is not None:
        sp.write_text(json.dumps(settings))
    gp = tmp_path / "global.json"
    if stock is not None:
        gp.write_text(json.dumps(stock))
    monkeypatch.setattr(tn, "_SETTINGS_PATH", str(sp))
    monkeypatch.setattr(tn, "_STOCK_GLOBAL_PATH", str(gp))
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    sent = []
    monkeypatch.setattr(tn, "_post_json", lambda url, payload: sent.append((url, payload)))
    return sent


def test_fans_out_to_both_channels(monkeypatch, tmp_path):
    sent = _setup(monkeypatch, tmp_path,
                  settings={"botToken": "T", "chatId": "1", "discordWebhook": HOOK})
    res = tn._send("🚨 <b>Ataque a chegar!</b>\nA → B", level="critical")
    assert res == {"telegram": True, "discord": True}
    urls = [u for u, _ in sent]
    assert urls[0] == "https://api.telegram.org/botT/sendMessage" and urls[1] == HOOK
    assert sent[0][1]["parse_mode"] == "HTML"


def test_unconfigured_channels_are_none_and_send_nothing(monkeypatch, tmp_path):
    sent = _setup(monkeypatch, tmp_path)
    assert tn._send("x") == {"telegram": None, "discord": None}
    assert sent == []


def test_one_channel_failing_does_not_block_the_other(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path,
           settings={"botToken": "T", "chatId": "1", "discordWebhook": HOOK})
    calls = []

    def flaky(url, payload):
        calls.append(url)
        if "telegram" in url:
            raise OSError("telegram down")
    monkeypatch.setattr(tn, "_post_json", flaky)
    assert tn._send("<b>x</b>") == {"telegram": False, "discord": True}
    assert len(calls) == 2


def test_discord_webhook_falls_back_to_env_then_stock_config(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, stock={"discord": {"webhookUrl": "https://stock"}})
    assert tn._get_discord_webhook() == "https://stock"
    _setup(monkeypatch, tmp_path, stock={"discord": {"webhookUrl": "https://stock"}},
           env={"DISCORD_WEBHOOK_URL": "https://env"})
    assert tn._get_discord_webhook() == "https://env"
    _setup(monkeypatch, tmp_path, settings={"discordWebhook": "https://ours"},
           stock={"discord": {"webhookUrl": "https://stock"}},
           env={"DISCORD_WEBHOOK_URL": "https://env"})
    assert tn._get_discord_webhook() == "https://ours"


def test_discord_embed_title_description_and_colour():
    msg = tn.format_returned_loot("Castle-M", "RxDxR", "Gates", [1000, 0, 0, 0, 0])
    p = tn.build_discord_payload(msg, "success")
    e = p["embeds"][0]
    assert e["title"] == "💰 Saque a caminho de casa"
    assert "**1.000**" in e["description"] and "<b>" not in e["description"]
    assert e["color"] == tn.LEVEL_COLORS["success"]
    assert e["timestamp"].endswith("Z")


def test_discord_converts_code_and_unescapes_entities():
    p = tn.build_discord_payload("🟠 <b>Falha</b>\n<code>farm</code> &amp; mais", "error")
    assert p["embeds"][0]["description"] == "`farm` & mais"
    assert p["embeds"][0]["color"] == tn.LEVEL_COLORS["error"]


def test_unknown_level_defaults_to_info():
    assert tn.build_discord_payload("x", "nope")["embeds"][0]["color"] == tn.LEVEL_COLORS["info"]


def test_notifiers_tag_their_severity(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(tn, "_send", lambda text, level="info": seen.append(level))
    tn.notify_attack_incoming("A", "B", 5, 10, 0)
    tn.notify_subsystem_down("farm", 3, "boom")
    tn.notify_returned_loot("A", "B", "C", [1, 0, 0, 0, 0])
    tn.notify_started(1)
    assert seen == ["critical", "error", "success", "info"]
