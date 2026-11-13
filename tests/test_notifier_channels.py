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
    monkeypatch.setattr(tn, "_send", lambda text, level="info", **kw: seen.append(level))
    tn.notify_attack_incoming("A", "B", 5, 10, 0)
    tn.notify_subsystem_down("farm", 3, "boom")
    tn.notify_returned_loot("A", "B", "C", [1, 0, 0, 0, 0])
    tn.notify_started(1)
    assert seen == ["critical", "error", "success", "info"]


# ── phase 2: per-channel floors, once-dedup, new events ─────────────────────

def test_activity_goes_to_discord_only_by_default(monkeypatch, tmp_path):
    sent = _setup(monkeypatch, tmp_path,
                  settings={"botToken": "T", "chatId": "1", "discordWebhook": HOOK})
    assert tn._send("x", level="activity") == {"telegram": None, "discord": True}
    assert [u for u, _ in sent] == [HOOK]


def test_channel_floor_is_configurable(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, settings={"botToken": "T", "chatId": "1", "discordWebhook": HOOK,
                                            "telegramMinLevel": "activity",
                                            "discordMinLevel": "error"})
    assert tn._send("x", level="activity") == {"telegram": True, "discord": None}
    assert tn._send("x", level="critical") == {"telegram": True, "discord": True}


def test_force_bypasses_floors(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, settings={"botToken": "T", "chatId": "1", "discordWebhook": HOOK,
                                            "telegramMinLevel": "critical"})
    assert tn._send("x", level="activity", force=True) == {"telegram": True, "discord": True}


def test_notify_once_until_cleared(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(tn, "_send", lambda text, level="info", **kw: seen.append(text))
    monkeypatch.setattr(tn, "_once_keys", set())
    tn.notify_wine_buy_blocked("ouro no piso", "1 ouro")
    tn.notify_wine_buy_blocked("ouro no piso", "1 ouro")
    assert len(seen) == 1
    tn.clear_wine_buy_blocked()
    tn.notify_wine_buy_blocked("ouro no piso", "1 ouro")
    assert len(seen) == 2


def test_new_events_escape_game_names(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(tn, "_send", lambda text, level="info", **kw: seen.append((text, level)))
    tn.notify_spy_failed("A<b>&C", "P", "possivelmente capturado", spies_lost=True)
    tn.notify_spy_failed("X", "P", "relatório ausente", spies_lost=False)
    text, level = seen[0]
    assert "A&lt;b&gt;&amp;C" in text and level == "warning"
    assert seen[1][1] == "activity"


def test_wine_messages(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(tn, "_send", lambda text, level="info", **kw: seen.append((text, level)))
    buys = [{"amount": 5000, "price": 12, "seller": "S", "toCity": "C"}]
    tn.notify_wine_bought(5000, 60000, 12.0, buys, dry_run=False)
    tn.notify_wine_bought(5000, 60000, 12.0, buys, dry_run=True)
    tn.notify_wine_balanced([("A", "B", 12000, 3), ("C", "B", 500, 1)])
    tn.notify_wine_balanced([])
    assert seen[0][1] == "success" and "5.000 vinho por 60.000 ouro" in seen[0][0]
    assert seen[1][1] == "activity" and "simulação" in seen[1][0]
    assert len(seen) == 3 and "12.500 vinho em 2 envio(s)" in seen[2][0]


# ── phase 3: categories, escaping, digest, farm reserve ─────────────────────

def test_muted_category_is_dropped_but_critical_still_passes(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, settings={"botToken": "T", "chatId": "1",
                                            "discordWebhook": HOOK,
                                            "telegramMuted": ["combat", "farm"]})
    assert tn._send("x", level="info", category="farm") == {"telegram": None, "discord": True}
    assert tn._send("x", level="critical", category="combat") == {"telegram": True,
                                                                  "discord": True}
    assert tn._send("x", level="info", category="wine")["telegram"] is True


def test_every_alert_names_a_known_category(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    cats = []
    monkeypatch.setattr(tn, "_send", lambda text, level="info", category="system", **kw:
                        cats.append(category))
    monkeypatch.setattr(tn, "_once_keys", set())
    tn.notify_started(1); tn.notify_construction_done("C", "B", 2)
    tn.notify_transport_error("C", "wood", "O"); tn.notify_wine_critical("Cx", 1.0)
    tn.notify_attack_dispatched("O", "T", "P", "army"); tn.notify_attack_failed("T", "P", 3)
    tn.notify_attack_incoming("O", "T", 5, 1, 0); tn.notify_farm_blocked("T", "P", 3)
    tn.notify_farm_drained("T", "P", 10); tn.notify_farm_active("T", "P")
    tn.notify_farm_waiting_reserve(52, 5, 50); tn.notify_returned_loot("A", "B", "C", [1])
    tn.notify_subsystem_down("farm", 3, "e"); tn.notify_subsystem_recovered("farm")
    tn.notify_bot_fatal(); tn.notify_spy_failed("T", "P", "e", True)
    tn.notify_target_swept("T", "P", False); tn.notify_wine_bought(1, 1, 1, [], False)
    tn.notify_wine_buy_blocked("r"); tn.notify_wine_balanced([("A", "B", 1, 1)])
    tn.notify_transport_sent("A", "B", "s"); tn.notify_consolidation_done("B", "s")
    tn.notify_world_scan_done(1)
    assert len(cats) == 23 and set(cats) <= set(tn.CATEGORIES)


def test_old_alerts_escape_game_names(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(tn, "_send", lambda text, **kw: seen.append(text))
    tn.notify_attack_dispatched("A&B", "<Castle>", "P", "army")
    assert "A&amp;B → &lt;Castle&gt;" in seen[0]
    assert "R&amp;D" in tn.format_returned_loot("R&D", "P", "C", [1])


def test_farm_reserve_alert_once_per_episode(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(tn, "_send", lambda text, **kw: seen.append(text))
    monkeypatch.setattr(tn, "_once_keys", set())
    tn.notify_farm_waiting_reserve(52, 5, 50)
    tn.notify_farm_waiting_reserve(53, 5, 50)
    tn.clear_farm_waiting_reserve()
    tn.notify_farm_waiting_reserve(51, 5, 50)
    assert len(seen) == 2 and "52 navios livres" in seen[0] and "sobram 47" in seen[0]


def _ts(h, day=13):
    import time as _t
    return _t.mktime((2026, 11, day, h, 0, 0, 0, 0, -1))


def test_digest_counts_and_sends_daily_then_resets(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, settings={"digest": "daily", "digestHour": 21})
    seen = []
    monkeypatch.setattr(tn, "_send", lambda text, level="info", category="system", **kw:
                        seen.append((text, category)))
    assert tn.maybe_send_digest(now=_ts(9)) is False        # first call only arms
    tn._record(raids=2); tn._record(loot=[100, 0, 0, 0, 50]); tn._record(spiesLost=1)
    assert tn.maybe_send_digest(now=_ts(20)) is False       # before 21h
    assert tn.maybe_send_digest(now=_ts(21) + 60) is True
    text, cat = seen[-1]
    assert cat == "digest" and "Raids: 2" in text and "Saque: <b>150</b>" in text
    assert "Espiões perdidos: 1" in text
    assert tn.maybe_send_digest(now=_ts(22)) is False       # already sent today
    assert tn._load_digest()["counts"] == {}
    assert tn.maybe_send_digest(now=_ts(21, day=14) + 5) is True
    assert "Sem actividade" in seen[-1][0]                  # daily sends even when quiet


def test_digest_hourly_skips_quiet_hours_and_off_never_sends(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, settings={"digest": "hourly"})
    seen = []
    monkeypatch.setattr(tn, "_send", lambda text, **kw: seen.append(text))
    tn.maybe_send_digest(now=_ts(9))
    assert tn.maybe_send_digest(now=_ts(10)) is True and seen == []   # quiet → silent reset
    tn._record(builds=1)
    assert tn.maybe_send_digest(now=_ts(11)) is True and "Construções concluídas: 1" in seen[0]
    _setup(monkeypatch, tmp_path, settings={"digest": "off"})
    monkeypatch.setattr(tn, "_send", lambda text, **kw: seen.append(text))
    tn._record(builds=1)
    assert tn.maybe_send_digest(now=_ts(23)) is False
