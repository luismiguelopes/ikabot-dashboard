#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from urllib.request import urlopen, Request

_SETTINGS_PATH = "/tmp/ikalogs/telegram_settings.json"

# Per-run dedup: avoid re-notifying for the same condition until it clears
_wine_critical_notified: set = set()
_offline_notified: bool = False


def _get_credentials():
    """Read bot token and chat ID from settings file, falling back to env vars."""
    try:
        with open(_SETTINGS_PATH) as f:
            d = json.load(f)
        token = d.get("botToken", "").strip()
        chat_id = d.get("chatId", "").strip()
        if token and chat_id:
            return token, chat_id
    except Exception:
        pass
    return os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")


def _send(text: str) -> None:
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        return
    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req  = Request(url, data=body, headers={"Content-Type": "application/json"})
        urlopen(req, timeout=10)
    except Exception:
        pass


def notify_started(cycle: int) -> None:
    _send(f"🤖 <b>Ikabot iniciado</b> — ciclo #{cycle}")


def notify_construction_done(city: str, building: str, level: int) -> None:
    _send(f"🏗️ <b>Construção concluída</b>\n{city} — {building} nível {level}")


def notify_transport_error(city: str, resource: str, origin: str) -> None:
    _send(f"⚠️ <b>Erro de transporte</b>\n{city} ← {resource} de {origin}")


def notify_wine_critical(city: str, hours_left: float) -> None:
    global _wine_critical_notified
    if city in _wine_critical_notified:
        return
    _wine_critical_notified.add(city)
    _send(f"🍷 <b>Vinho crítico</b>\n{city} — {hours_left:.1f}h restantes")


def clear_wine_critical(city: str) -> None:
    _wine_critical_notified.discard(city)


def notify_bot_offline(minutes: int) -> None:
    global _offline_notified
    if _offline_notified:
        return
    _offline_notified = True
    _send(f"🔴 <b>Bot offline</b> — sem actividade há {minutes} minutos")


def clear_bot_offline() -> None:
    global _offline_notified
    _offline_notified = False
