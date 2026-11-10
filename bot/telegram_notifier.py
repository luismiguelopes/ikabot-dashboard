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


def notify_attack_dispatched(origin: str, target_city: str, player: str, mission: str) -> None:
    icon = "⚓" if mission == "fleet" else "⚔️"
    _send(f"{icon} <b>Ataque lançado</b>\n{origin} → {target_city} ({player})")


def notify_attack_failed(target_city: str, player: str, attempts: int) -> None:
    _send(f"❌ <b>Ataque falhou</b>\n{target_city} ({player}) — "
          f"removido da fila após {attempts} tentativas")


def notify_attack_incoming(origin: str, target_city: str, eta_mins: int,
                           troops: int, fleets: int) -> None:
    parts = []
    if troops:
        parts.append(f"{troops} tropas")
    if fleets:
        parts.append(f"{fleets} navios")
    detail = " · ".join(parts) if parts else "movimento hostil"
    _send(f"🚨 <b>Ataque a chegar!</b>\n{origin} → {target_city}\n"
          f"chega em ~{eta_mins} min · {detail}")


def notify_farm_blocked(target_city: str, player: str, combat_ships: int) -> None:
    _send(f"⚠️ <b>Farm bloqueado</b>\n{target_city} ({player}) tem {combat_ships} navios de "
          f"combate (não fogem ao bloqueio) — alvo saltado, verifica manualmente")


def notify_farm_drained(target_city: str, player: str, loot: int) -> None:
    _send(f"🏁 <b>Alvo drenado</b>\n{target_city} ({player}) — saque caiu para {loot:,} "
          f"abaixo do mínimo. Desactivado do farm; a passar ao próximo da fila.")


def notify_farm_active(target_city: str, player: str) -> None:
    _send(f"🟢 <b>Alvo já não inactivo</b>\n{target_city} ({player}) deixou de estar inactivo "
          f"— desactivado do farm (já não é seguro atacar às cegas).")


_LOOT_ICONS = ("🪵", "🍷", "🪨", "💎", "🌋")   # wood, wine, marble, crystal, sulfur


def _pt_int(n: int) -> str:
    """Thousands with '.' like the game UI (72.517)."""
    return f"{int(n):,}".replace(",", ".")


def format_returned_loot(from_city: str, from_player: str, to_city: str, resources,
                         coords=None, arrival_ts: int = 0) -> str:
    """Telegram text for plunder on its way home. Names the plundered CITY, its owner and the
    island coordinates (the old message only had the player name where the place belonged),
    with the per-resource breakdown and the arrival time."""
    import time as _time
    res = [int(x or 0) for x in (list(resources or []) + [0] * 5)[:5]]
    where = from_city or "?"
    if from_player:
        where += f" ({from_player})"
    if coords and coords[0] is not None and coords[1] is not None:
        where += f" [{coords[0]}:{coords[1]}]"
    parts = [f"{icon} {_pt_int(v)}" for icon, v in zip(_LOOT_ICONS, res) if v > 0]
    lines = ["💰 <b>Saque a caminho de casa</b>",
             f"{where} → {to_city or '?'}",
             " · ".join(parts) if parts else "sem recursos",
             f"Total: <b>{_pt_int(sum(res))}</b>"]
    if arrival_ts:
        lines[-1] += f" · chega às {_time.strftime('%H:%M', _time.localtime(int(arrival_ts)))}"
    return "\n".join(lines)


def notify_returned_loot(from_city: str, from_player: str, to_city: str, resources,
                         coords=None, arrival_ts: int = 0) -> None:
    _send(format_returned_loot(from_city, from_player, to_city, resources, coords, arrival_ts))


def notify_subsystem_down(subsystem: str, consecutive: int, error: str) -> None:
    _send(f"🟠 <b>Subsistema em falha</b>\n<code>{subsystem}</code> falhou {consecutive}× "
          f"seguidas — o bot está vivo mas este módulo não está a fazer nada.\n"
          f"Último erro: {error}")


def notify_subsystem_recovered(subsystem: str) -> None:
    _send(f"🟢 <b>Subsistema recuperado</b>\n<code>{subsystem}</code> voltou a funcionar.")


def notify_bot_fatal() -> None:
    _send("💥 <b>Bot terminou (fatal)</b> — a sessão do jogo desistiu (re-login/rede esgotados). "
          "O container deve reiniciar sozinho (healthcheck + autoheal); confirma se persiste.")


def notify_bot_offline(minutes: int) -> None:
    global _offline_notified
    if _offline_notified:
        return
    _offline_notified = True
    _send(f"🔴 <b>Bot offline</b> — sem actividade há {minutes} minutos")


def clear_bot_offline() -> None:
    global _offline_notified
    _offline_notified = False
