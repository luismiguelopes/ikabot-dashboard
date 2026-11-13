#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import html
import json
import os
import re
import time
from urllib.request import urlopen, Request

_SETTINGS_PATH = "/tmp/ikalogs/telegram_settings.json"
# Stock ikabot keeps its own Discord/Telegram config here (menu 21). We read its Discord webhook
# as a fallback so one webhook serves both the stock modules (sendToBot) and our alerts.
_STOCK_GLOBAL_PATH = os.path.expanduser("~/.ikabot/global.json")

# Discord's edge rejects urllib's default User-Agent; any explicit one is accepted.
_USER_AGENT = "ikabot-notifier/1.0"
_HTTP_TIMEOUT = 8

# Severity ladder, lowest first. "activity" = routine, high-volume events (spy failures,
# shipments, scans) — by default only Discord gets them, so Telegram keeps its old volume.
LEVELS = ("activity", "info", "success", "warning", "error", "critical")
DEFAULT_MIN_LEVEL = {"telegram": "info", "discord": "activity"}

# Alert categories — each channel can mute any of them (`telegramMuted` / `discordMuted`).
# A critical alert (incoming attack, bot down) is never muted.
CATEGORIES = ("combat", "farm", "spy", "wine", "transport", "build", "system", "digest")

# Embed colour per severity level.
LEVEL_COLORS = {
    "activity": 0x94A3B8,   # slate
    "info":     0x3B82F6,   # blue
    "success":  0x10B981,   # green
    "warning":  0xF59E0B,   # amber
    "error":    0xEF4444,   # red
    "critical": 0x991B1B,   # dark red
}

# Per-run dedup: avoid re-notifying for the same condition until it clears
_wine_critical_notified: set = set()
_offline_notified: bool = False
_once_keys: set = set()


def _read_settings() -> dict:
    try:
        with open(_SETTINGS_PATH) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _get_credentials():
    """Read bot token and chat ID from settings file, falling back to env vars."""
    d = _read_settings()
    token = str(d.get("botToken", "")).strip()
    chat_id = str(d.get("chatId", "")).strip()
    if token and chat_id:
        return token, chat_id
    return os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")


def _get_discord_webhook() -> str:
    """Our settings → DISCORD_WEBHOOK_URL env → the stock ikabot config (global.json)."""
    url = str(_read_settings().get("discordWebhook", "")).strip()
    if url:
        return url
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if url:
        return url
    try:
        with open(_STOCK_GLOBAL_PATH) as f:
            g = json.load(f)
        for root in (g, g.get("shared", {})):
            url = str((root.get("discord") or {}).get("webhookUrl", "")).strip()
            if url:
                return url
    except Exception:
        pass
    return ""


def _strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def html_to_discord(text: str) -> str:
    """Telegram-HTML (the format every notify_* writes) → Discord markdown."""
    text = re.sub(r"</?b>", "**", text)
    text = re.sub(r"</?i>", "*", text)
    text = re.sub(r"</?code>", "`", text)
    return _strip_tags(text)


def build_discord_payload(text: str, level: str = "info") -> dict:
    """One embed per alert: first line → title, the rest → description, colour by level."""
    lines = text.split("\n")
    title = _strip_tags(lines[0]).strip()[:256]
    description = html_to_discord("\n".join(lines[1:])).strip()[:4096]
    embed = {
        "title": title or "ikabot",
        "color": LEVEL_COLORS.get(level, LEVEL_COLORS["info"]),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "footer": {"text": "ikabot"},
    }
    if description:
        embed["description"] = description
    return {"username": "ikabot", "embeds": [embed]}


def _post_json(url: str, payload: dict) -> None:
    body = json.dumps(payload).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json",
                                           "User-Agent": _USER_AGENT})
    urlopen(req, timeout=_HTTP_TIMEOUT)


def _send_telegram(text: str):
    """True = sent, False = failed, None = not configured."""
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        return None
    try:
        _post_json(f"https://api.telegram.org/bot{token}/sendMessage",
                   {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        return True
    except Exception:
        return False


def _send_discord(text: str, level: str = "info"):
    """True = sent, False = failed, None = not configured."""
    url = _get_discord_webhook()
    if not url:
        return None
    try:
        _post_json(url, build_discord_payload(text, level))
        return True
    except Exception:
        return False


def _rank(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else LEVELS.index("info")


def _channel_wants(channel: str, level: str, category: str = "system", settings=None) -> bool:
    """Per-channel severity floor (`<channel>MinLevel`) and muted categories
    (`<channel>Muted`). Critical alerts always pass the category mute."""
    d = _read_settings() if settings is None else settings
    floor = str(d.get(f"{channel}MinLevel", "") or DEFAULT_MIN_LEVEL[channel])
    if _rank(level) < _rank(floor):
        return False
    muted = d.get(f"{channel}Muted") or []
    if level != "critical" and isinstance(muted, list) and category in muted:
        return False
    return True


def _send(text: str, level: str = "info", category: str = "system", force: bool = False) -> dict:
    """Fan out to every configured channel whose filters the alert clears; one channel failing
    never affects the other or the caller. Returns {channel: True|False|None} (None = not
    configured or filtered out). `force` skips the filters (the UI test button)."""
    d = _read_settings()
    return {
        "telegram": _send_telegram(text)
                    if force or _channel_wants("telegram", level, category, d) else None,
        "discord":  _send_discord(text, level)
                    if force or _channel_wants("discord", level, category, d) else None,
    }


def notify_once(key: str, text: str, level: str = "info", category: str = "system") -> None:
    """Send once per condition: repeats are dropped until clear_once(key) — for states the bot
    re-checks every cycle (gold floor, no ships) so they alert on entry, not on every pass."""
    if key in _once_keys:
        return
    _once_keys.add(key)
    _send(text, level=level, category=category)


def clear_once(key: str) -> None:
    _once_keys.discard(key)


def _esc(s) -> str:
    """Escape game-sourced names (cities, players) for Telegram HTML — a stray '<' or '&'
    in a name made Telegram reject the whole message."""
    return html.escape(str(s if s is not None else "?"), quote=False)


def _pt_int(n: int) -> str:
    """Thousands with '.' like the game UI (72.517)."""
    return f"{int(n):,}".replace(",", ".")


# ── Periodic digest ───────────────────────────────────────────────────────────
# Every alert-worthy event also bumps a counter; maybe_send_digest() (called from the bot's
# ≤60s sleep loop) sends one summary hourly or daily and resets them. Counters live in a JSON
# file next to the settings so a restart doesn't lose the day.
_DIGEST_FIELDS = ("raids", "raidsFailed", "lootTotal", "wineBought", "wineGold", "spiesLost",
                  "spyFailed", "swept", "drained", "builds", "transports", "incoming",
                  "subsystemDown")
DEFAULT_DIGEST = {"digest": "daily", "digestHour": 21}


def _digest_path() -> str:
    return os.path.join(os.path.dirname(_SETTINGS_PATH), "notify_digest.json")


def _load_digest() -> dict:
    try:
        with open(_digest_path()) as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("counts", {})
            d.setdefault("loot", [0, 0, 0, 0, 0])
            return d
    except Exception:
        pass
    return {"since": int(time.time()), "lastSentAt": 0, "counts": {}, "loot": [0, 0, 0, 0, 0]}


def _save_digest(d: dict) -> None:
    path = _digest_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, path)


def _record(loot=None, **incs) -> None:
    """Bump digest counters; never raises (a stats write must not break an alert)."""
    try:
        d = _load_digest()
        for k, v in incs.items():
            d["counts"][k] = int(d["counts"].get(k, 0)) + int(v)
        if loot:
            res = [int(x or 0) for x in (list(loot) + [0] * 5)[:5]]
            d["loot"] = [a + b for a, b in zip(d["loot"], res)]
            d["counts"]["lootTotal"] = int(d["counts"].get("lootTotal", 0)) + sum(res)
        _save_digest(d)
    except Exception:
        pass


def _digest_due(d: dict, settings: dict, now: float) -> bool:
    mode = settings.get("digest", DEFAULT_DIGEST["digest"])
    last = int(d.get("lastSentAt", 0) or 0)
    if mode == "hourly":
        return now - last >= 3600
    if mode == "daily":
        hour = int(settings.get("digestHour", DEFAULT_DIGEST["digestHour"]))
        lt = time.localtime(now)
        sched = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, 0, 0, 0, 0, -1))
        if now < sched:
            sched -= 86400               # today's slot not reached → the last one was yesterday
        return last < sched
    return False


def format_digest(d: dict, now: float) -> str:
    c = d.get("counts", {})
    hours = max(1, round((now - int(d.get("since", now))) / 3600))
    lines = [f"📊 <b>Resumo das últimas {hours}h</b>"]
    if c.get("raids") or c.get("lootTotal"):
        line = f"⚔️ Raids: {c.get('raids', 0)}"
        if c.get("raidsFailed"):
            line += f" ({c['raidsFailed']} falhados)"
        lines.append(line)
        parts = [f"{i} {_pt_int(v)}" for i, v in zip(_LOOT_ICONS, d.get("loot", [])) if v]
        lines.append(f"💰 Saque: <b>{_pt_int(c.get('lootTotal', 0))}</b>"
                     + (f" ({' · '.join(parts)})" if parts else ""))
    if c.get("swept") or c.get("drained"):
        lines.append(f"🛰️ Alvos novos varridos: {c.get('swept', 0)} · drenados: {c.get('drained', 0)}")
    if c.get("spiesLost") or c.get("spyFailed"):
        lines.append(f"🕵️ Espiões perdidos: {c.get('spiesLost', 0)} · missões falhadas: "
                     f"{c.get('spyFailed', 0)}")
    if c.get("wineBought"):
        lines.append(f"🍷 Vinho comprado: {_pt_int(c['wineBought'])} por {_pt_int(c.get('wineGold', 0))} ouro")
    if c.get("builds"):
        lines.append(f"🏗️ Construções concluídas: {c['builds']}")
    if c.get("transports"):
        lines.append(f"🚢 Transportes enviados: {c['transports']}")
    if c.get("incoming"):
        lines.append(f"🚨 Ataques recebidos: {c['incoming']}")
    if c.get("subsystemDown"):
        lines.append(f"🟠 Falhas de subsistema: {c['subsystemDown']}")
    if len(lines) == 1:
        lines.append("Sem actividade registada.")
    return "\n".join(lines)


def maybe_send_digest(now: float = None) -> bool:
    """Send the summary if its slot is due; returns True when sent. The first call only
    arms the schedule (no digest straight after a fresh install/restart)."""
    now = time.time() if now is None else now
    try:
        settings = _read_settings()
        d = _load_digest()
        if not d.get("lastSentAt"):
            d["lastSentAt"] = int(now)
            _save_digest(d)
            return False
        if not _digest_due(d, settings, now):
            return False
        empty = not any(int(v or 0) for v in d.get("counts", {}).values())
        if not (empty and settings.get("digest") == "hourly"):   # quiet hours: skip, daily: always
            _send(format_digest(d, now), level="info", category="digest")
        _save_digest({"since": int(now), "lastSentAt": int(now), "counts": {},
                      "loot": [0, 0, 0, 0, 0]})
        return True
    except Exception:
        return False


# ── Alerts ────────────────────────────────────────────────────────────────────

def notify_started(cycle: int) -> None:
    _send(f"🤖 <b>Ikabot iniciado</b> — ciclo #{cycle}", category="system")


def notify_construction_done(city: str, building: str, level: int) -> None:
    _record(builds=1)
    _send(f"🏗️ <b>Construção concluída</b>\n{_esc(city)} — {_esc(building)} nível {level}",
          level="success", category="build")


def notify_transport_error(city: str, resource: str, origin: str) -> None:
    _send(f"⚠️ <b>Erro de transporte</b>\n{_esc(city)} ← {_esc(resource)} de {_esc(origin)}",
          level="warning", category="transport")


def notify_wine_critical(city: str, hours_left: float) -> None:
    global _wine_critical_notified
    if city in _wine_critical_notified:
        return
    _wine_critical_notified.add(city)
    _send(f"🍷 <b>Vinho crítico</b>\n{_esc(city)} — {hours_left:.1f}h restantes",
          level="warning", category="wine")


def clear_wine_critical(city: str) -> None:
    _wine_critical_notified.discard(city)


def notify_attack_dispatched(origin: str, target_city: str, player: str, mission: str) -> None:
    _record(raids=1)
    icon = "⚓" if mission == "fleet" else "⚔️"
    _send(f"{icon} <b>Ataque lançado</b>\n{_esc(origin)} → {_esc(target_city)} ({_esc(player)})",
          category="combat")


def notify_attack_failed(target_city: str, player: str, attempts: int) -> None:
    _record(raidsFailed=1)
    _send(f"❌ <b>Ataque falhou</b>\n{_esc(target_city)} ({_esc(player)}) — "
          f"removido da fila após {attempts} tentativas", level="error", category="combat")


def notify_attack_incoming(origin: str, target_city: str, eta_mins: int,
                           troops: int, fleets: int) -> None:
    _record(incoming=1)
    parts = []
    if troops:
        parts.append(f"{troops} tropas")
    if fleets:
        parts.append(f"{fleets} navios")
    detail = " · ".join(parts) if parts else "movimento hostil"
    _send(f"🚨 <b>Ataque a chegar!</b>\n{_esc(origin)} → {_esc(target_city)}\n"
          f"chega em ~{eta_mins} min · {detail}", level="critical", category="combat")


def notify_farm_blocked(target_city: str, player: str, combat_ships: int) -> None:
    _send(f"⚠️ <b>Farm bloqueado</b>\n{_esc(target_city)} ({_esc(player)}) tem {combat_ships} "
          f"navios de combate (não fogem ao bloqueio) — alvo saltado, verifica manualmente",
          level="warning", category="farm")


def notify_farm_drained(target_city: str, player: str, loot: int) -> None:
    _record(drained=1)
    _send(f"🏁 <b>Alvo drenado</b>\n{_esc(target_city)} ({_esc(player)}) — saque caiu para "
          f"{_pt_int(loot)} abaixo do mínimo. Desactivado do farm; a passar ao próximo da fila.",
          category="farm")


def notify_farm_active(target_city: str, player: str) -> None:
    _send(f"🟢 <b>Alvo já não inactivo</b>\n{_esc(target_city)} ({_esc(player)}) deixou de estar "
          f"inactivo — desactivado do farm (já não é seguro atacar às cegas).",
          level="warning", category="farm")


def notify_farm_waiting_reserve(free_raw: int, reserve: int, floor: int) -> None:
    """The wine ship reserve is the only thing holding the farm back: once per episode."""
    notify_once("farm-reserve",
                f"⛵ <b>Farm à espera de navios</b>\n{free_raw} navios livres, mas {reserve} estão "
                f"reservados ao vinho — sobram {max(0, free_raw - reserve)} (< {floor} para uma "
                f"raid). Ataque adiado até os navios regressarem.", level="info", category="farm")


def clear_farm_waiting_reserve() -> None:
    clear_once("farm-reserve")


_LOOT_ICONS = ("🪵", "🍷", "🪨", "💎", "🌋")   # wood, wine, marble, crystal, sulfur


def format_returned_loot(from_city: str, from_player: str, to_city: str, resources,
                         coords=None, arrival_ts: int = 0) -> str:
    """Telegram text for plunder on its way home. Names the plundered CITY, its owner and the
    island coordinates (the old message only had the player name where the place belonged),
    with the per-resource breakdown and the arrival time."""
    res = [int(x or 0) for x in (list(resources or []) + [0] * 5)[:5]]
    where = _esc(from_city or "?")
    if from_player:
        where += f" ({_esc(from_player)})"
    if coords and coords[0] is not None and coords[1] is not None:
        where += f" [{coords[0]}:{coords[1]}]"
    parts = [f"{icon} {_pt_int(v)}" for icon, v in zip(_LOOT_ICONS, res) if v > 0]
    lines = ["💰 <b>Saque a caminho de casa</b>",
             f"{where} → {_esc(to_city or '?')}",
             " · ".join(parts) if parts else "sem recursos",
             f"Total: <b>{_pt_int(sum(res))}</b>"]
    if arrival_ts:
        lines[-1] += f" · chega às {time.strftime('%H:%M', time.localtime(int(arrival_ts)))}"
    return "\n".join(lines)


def notify_returned_loot(from_city: str, from_player: str, to_city: str, resources,
                         coords=None, arrival_ts: int = 0) -> None:
    _record(loot=resources)
    _send(format_returned_loot(from_city, from_player, to_city, resources, coords, arrival_ts),
          level="success", category="farm")


def notify_subsystem_down(subsystem: str, consecutive: int, error: str) -> None:
    _record(subsystemDown=1)
    _send(f"🟠 <b>Subsistema em falha</b>\n<code>{_esc(subsystem)}</code> falhou {consecutive}× "
          f"seguidas — o bot está vivo mas este módulo não está a fazer nada.\n"
          f"Último erro: {_esc(error)}", level="error", category="system")


def notify_subsystem_recovered(subsystem: str) -> None:
    _send(f"🟢 <b>Subsistema recuperado</b>\n<code>{_esc(subsystem)}</code> voltou a funcionar.",
          level="success", category="system")


def notify_bot_fatal() -> None:
    _send("💥 <b>Bot terminou (fatal)</b> — a sessão do jogo desistiu (re-login/rede esgotados). "
          "O container deve reiniciar sozinho (healthcheck + autoheal); confirma se persiste.",
          level="critical", category="system")


def notify_bot_offline(minutes: int) -> None:
    global _offline_notified
    if _offline_notified:
        return
    _offline_notified = True
    _send(f"🔴 <b>Bot offline</b> — sem actividade há {minutes} minutos",
          level="critical", category="system")


def clear_bot_offline() -> None:
    global _offline_notified
    _offline_notified = False


def notify_spy_failed(target_city: str, player: str, error: str, spies_lost: bool) -> None:
    if spies_lost:
        _record(spiesLost=1)
        _send(f"🕵️ <b>Espiões perdidos</b>\n{_esc(target_city)} ({_esc(player)}) — {_esc(error)}",
              level="warning", category="spy")
    else:
        _record(spyFailed=1)
        _send(f"🕵️ <b>Missão de espionagem falhou</b>\n{_esc(target_city)} ({_esc(player)}) — "
              f"{_esc(error)}", level="activity", category="spy")


def notify_target_swept(target_city: str, player: str, fleet_target: bool) -> None:
    _record(swept=1)
    verdict = ("frota detectada — só bloqueio/ataque com navios" if fleet_target
               else "porto limpo — pronto para atacar")
    _send(f"🛰️ <b>Alvo novo varrido</b>\n{_esc(target_city)} ({_esc(player)}) — {verdict}",
          level="info", category="farm")


def notify_wine_bought(bought: int, spent: int, avg_price, buys, dry_run: bool) -> None:
    if not dry_run:
        _record(wineBought=bought, wineGold=spent)
    lines = [f"• {_pt_int(b['amount'])} @{b['price']} de {_esc(b['seller'])} → {_esc(b['toCity'])}"
             for b in (buys or [])[:8]]
    title = "🍷 <b>Compra de vinho (simulação)</b>" if dry_run else "🍷 <b>Vinho comprado</b>"
    body = f"{_pt_int(bought)} vinho por {_pt_int(spent)} ouro · preço médio {avg_price}"
    _send("\n".join([title, body] + lines), level="activity" if dry_run else "success",
          category="wine")


def notify_wine_buy_blocked(reason: str, detail: str = "") -> None:
    """Brake state (gold floor, no ships): once on entry, again only after it clears."""
    text = f"🍷 <b>Comprador de vinho travado</b>\n{_esc(reason)}"
    if detail:
        text += f" — {_esc(detail)}"
    notify_once(f"wine-buy:{reason}", text, level="warning", category="wine")


def clear_wine_buy_blocked() -> None:
    for k in [k for k in _once_keys if k.startswith("wine-buy:")]:
        _once_keys.discard(k)


def notify_wine_balanced(shipments) -> None:
    """One message per balancer pass: [(src, dest, amount, ships), ...]."""
    if not shipments:
        return
    total = sum(int(a) for _, _, a, _ in shipments)
    lines = [f"• {_esc(s)} → {_esc(d)}: {_pt_int(a)} ({n} navios)" for s, d, a, n in shipments[:10]]
    _send("\n".join([f"🍷 <b>Vinho redistribuído</b>\n{_pt_int(total)} vinho em "
                     f"{len(shipments)} envio(s)"] + lines), level="activity", category="wine")


def notify_transport_sent(origin: str, dest: str, summary: str) -> None:
    _record(transports=1)
    _send(f"🚢 <b>Transporte enviado</b>\n{_esc(origin)} → {_esc(dest)}: {_esc(summary)}",
          level="activity", category="transport")


def notify_consolidation_done(dest: str, summary: str) -> None:
    _send(f"📦 <b>Consolidação concluída</b>\n→ {_esc(dest)}: {_esc(summary)}",
          level="activity", category="transport")


def notify_world_scan_done(players: int) -> None:
    _send(f"🗺️ <b>World scan concluído</b>\n{_pt_int(players)} jogadores actualizados",
          level="activity", category="system")
