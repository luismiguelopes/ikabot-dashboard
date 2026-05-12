#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from urllib.request import urlopen, Request
from urllib.error import URLError

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# Per-run dedup: avoid re-notifying for the same city until condition clears
_wine_critical_notified: set = set()


def _send(text: str) -> None:
    if not _BOT_TOKEN or not _CHAT_ID:
        return
    try:
        url  = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"
        body = json.dumps({"chat_id": _CHAT_ID, "text": text, "parse_mode": "HTML"}).encode()
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
