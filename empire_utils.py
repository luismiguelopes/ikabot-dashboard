#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import contextlib
import json
import logging
import logging.handlers
import os
import random
import re
import time

LOGS_DIR = "/tmp/ikalogs/"
LOG_FILE_PATH = os.path.join(LOGS_DIR, "bot.log")
PAUSE_PATH    = os.path.join(LOGS_DIR, "pause.json")


def _setup_logger():
    _log = logging.getLogger("ikabot")
    if not _log.handlers:
        _handler = logging.StreamHandler()
        _handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        ))
        _log.addHandler(_handler)
        # File handler (bounded) so the dashboard can tail the bot log (F10).
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            _fh = logging.handlers.RotatingFileHandler(
                LOG_FILE_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
            _fh.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            _log.addHandler(_fh)
        except Exception:
            pass
        _log.setLevel(logging.INFO)
        _log.propagate = False
    # Silence ikabot's internal HTTP/session debug noise
    for _noisy in ("ikabot.web", "ikabot.web.session", "ikabot.helpers"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)
    return _log


logger = _setup_logger()


def is_paused():
    """Global pause (F11): when True the bot keeps collecting data but launches no
    new actions — building constructions, transports/consolidation and combat
    dispatches. Toggled from the dashboard via pause.json on the shared volume."""
    try:
        with open(PAUSE_PATH) as f:
            return bool(json.load(f).get("paused", False))
    except Exception:
        return False


QUEUE_JSON_PATH           = os.path.join(LOGS_DIR, "building_queue.json")
QUEUE_SETTINGS_PATH       = os.path.join(LOGS_DIR, "queue_settings.json")
LAST_ALIVE_JSON_PATH      = os.path.join(LOGS_DIR, "last_alive.json")
EMPIRE_SCAN_STATUS_PATH   = os.path.join(LOGS_DIR, "empire_scan_status.json")
FORCE_EMPIRE_FLAG         = os.path.join(LOGS_DIR, ".force_empire_update")
FORCE_QUEUE_FLAG          = os.path.join(LOGS_DIR, ".force_queue_check")
FORCE_MOVEMENTS_FLAG      = os.path.join(LOGS_DIR, ".force_movements_update")
FORCE_IMPORT_REPORTS_FLAG = os.path.join(LOGS_DIR, ".force_import_reports")
FORCE_MILITARY_FLAG       = os.path.join(LOGS_DIR, ".force_military_update")
SCAN_CHECKPOINT_PATH      = os.path.join(LOGS_DIR, "world_scan_checkpoint.json")


def _parse_duration(value, default):
    """Converte string de duração (ex: '3h', '2d', '30m') ou segundos inteiros para segundos."""
    if value is None:
        return default
    value = str(value).strip().lower()
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(d|h|m|s)?', value)
    if not match:
        return default
    amount, unit = float(match.group(1)), match.group(2) or 's'
    multipliers = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}
    return int(amount * multipliers[unit])


UPDATE_INTERVAL                 = _parse_duration(os.getenv("EMPIRE_UPDATE_INTERVAL"), 3600)
MAX_HISTORY_LINES               = 2160
BUILDING_COSTS_UPDATE_INTERVAL  = _parse_duration(os.getenv("BUILDING_COSTS_UPDATE_INTERVAL"), 3 * 24 * 3600)
WORLD_SCAN_UPDATE_INTERVAL      = _parse_duration(os.getenv("WORLD_SCAN_UPDATE_INTERVAL"), 7 * 24 * 3600)
WORLD_SCAN_RADIUS               = int(os.getenv("WORLD_SCAN_RADIUS", 10))
LOG_LANG                        = os.getenv("LOG_LANG", "en")


def _parse_active_hours(value):
    """Parse 'H-H' string into (start_hour, end_hour). Returns (0, 24) if unset/invalid."""
    if not value:
        return 0, 24
    try:
        parts = str(value).strip().split('-')
        start, end = int(parts[0]), int(parts[1])
        if 0 <= start < end <= 24:
            return start, end
    except Exception:
        pass
    return 0, 24


ACTIVE_HOURS_START, ACTIVE_HOURS_END = _parse_active_hours(os.getenv("QUEUE_ACTIVE_HOURS"))
SCAN_ACTIVE_HOURS_START, SCAN_ACTIVE_HOURS_END = _parse_active_hours(os.getenv("SCAN_ACTIVE_HOURS", ""))
SCAN_NIGHT_INTERVAL = _parse_duration(os.getenv("SCAN_NIGHT_INTERVAL", "4h"), 4 * 3600)
WINE_CRITICAL_NOTIFY_SECS = _parse_duration(os.getenv("WINE_CRITICAL_NOTIFY_HOURS", "2h"), 7200)

_LM = {
    "own_cities_missing": {
        "en": "[world_scan] own_cities.json not found, waiting for next cycle...",
        "pt": "[world_scan] own_cities.json não encontrado, a aguardar próximo ciclo...",
    },
    "world_scan_start": {
        "en": "[{ts}] World scan started (radius={radius})...",
        "pt": "[{ts}] World scan iniciado (raio={radius})...",
    },
    "scan_status_shallow": {
        "en": "Scanning map...",
        "pt": "A escanear mapa...",
    },
    "scan_status_quadrant": {
        "en": "Map ({x_min}-{x_max},{y_min}-{y_max})...",
        "pt": "Mapa ({x_min}-{x_max},{y_min}-{y_max})...",
    },
    "scan_islands_count": {
        "en": "[world_scan] {n} islands to scan within radius {radius}...",
        "pt": "[world_scan] {n} ilhas a escanear no raio {radius}...",
    },
    "scan_shallow_complete": {
        "en": "[world_scan] Shallow scan done — {n} islands queued for incremental deep scan",
        "pt": "[world_scan] Shallow scan concluído — {n} ilhas em fila para deep scan incremental",
    },
    "scan_status_deep": {
        "en": "Scanning {n} islands...",
        "pt": "A escanear {n} ilhas...",
    },
    "scan_island_pause": {
        "en": "      -> Pause {pause}s | Island {i}/{total} ({x},{y})...",
        "pt": "      -> Pausa {pause}s | Ilha {i}/{total} ({x},{y})...",
    },
    "scan_island_done": {
        "en": "      Island {i}/{total} ({x},{y}) processed",
        "pt": "      Ilha {i}/{total} ({x},{y}) processada",
    },
    "scan_island_error": {
        "en": "      -> Error on island {id}: {err}",
        "pt": "      -> Erro na ilha {id}: {err}",
    },
    "scan_status_done": {
        "en": "Done: {n} inactive/vacation players found",
        "pt": "Concluído: {n} inactivos/férias encontrados",
    },
    "scan_done": {
        "en": "[world_scan] Done: {n} inactive/vacation players found.",
        "pt": "[world_scan] Concluído: {n} inactivos/férias encontrados.",
    },
    "scan_error": {
        "en": "World scan error:",
        "pt": "Erro no world scan:",
    },
    "scan_status_error": {
        "en": "Error during scan",
        "pt": "Erro durante o scan",
    },
    "costs_start": {
        "en": "[{ts}] Starting building cost extraction (human mode)...",
        "pt": "[{ts}] A iniciar extração de custos de edificios (modo humano)...",
    },
    "costs_city_pause": {
        "en": "      -> Pause {pause}s before next city...",
        "pt": "      -> Pausa de {pause}s antes de próxima cidade...",
    },
    "costs_city_start": {
        "en": "      -> Costs: {city}...",
        "pt": "      -> Custos: {city}...",
    },
    "costs_city_done": {
        "en": "      -> Success: {city} — {n} buildings with costs extracted.",
        "pt": "      -> Sucesso: {city} — {n} edificios com custos extraídos.",
    },
    "costs_city_error": {
        "en": "      -> Error extracting costs for city {id}:",
        "pt": "      -> Erro ao extrair custos de cidade {id}:",
    },
    "costs_done": {
        "en": "[{ts}] Building cost extraction done!",
        "pt": "[{ts}] Extração de custos de edificios concluída!",
    },
    "costs_error": {
        "en": "Error in cost extraction:",
        "pt": "Erro na extração de custos:",
    },
    "movements_error": {
        "en": "      -> Warning: could not collect movements:",
        "pt": "      -> Aviso: não foi possível recolher movimentos:",
    },
    "empire_start_1": {
        "en": "\n[+] Empire Function started in background!",
        "pt": "\n[+] Empire Function arrancada em Segundo Plano!",
    },
    "empire_start_2": {
        "en": "[+] Silently collecting empire data every {interval} seconds...\n",
        "pt": "[+] Extrai dados do império silenciosamente a cada {interval} segundos...\n",
    },
    "cycle_start": {
        "en": "[{ts}] Updating empire JSON files...",
        "pt": "[{ts}] A atualizar ficheiros JSON do Imperio...",
    },
    "city_done": {
        "en": "      -> Success: City {city} extracted.",
        "pt": "      -> Sucesso: Cidade {city} extraída.",
    },
    "cycle_done": {
        "en": "[+] Update cycle completed successfully!",
        "pt": "[+] Ciclo de atualização Terminado com sucesso!",
    },
    "cycle_error": {
        "en": "Error during data extraction:",
        "pt": "Erro durante extracção de dados:",
    },
    "queue_cycle_start": {
        "en": "[{ts}] Processing building queue...",
        "pt": "[{ts}] A processar fila de construção...",
    },
    "queue_city_not_found": {
        "en": "      -> Queue: city '{city}' not found in session, skipping.",
        "pt": "      -> Fila: cidade '{city}' não encontrada na sessão, a ignorar.",
    },
    "queue_building_not_found": {
        "en": "      -> Queue [{city}]: building '{building}' not found, removing from queue.",
        "pt": "      -> Fila [{city}]: edifício '{building}' não encontrado, a remover da fila.",
    },
    "queue_max_level": {
        "en": "      -> Queue [{city}]: {building} already at max level, removing from queue.",
        "pt": "      -> Fila [{city}]: {building} já está no nível máximo, a remover da fila.",
    },
    "queue_target_reached": {
        "en": "      -> Queue [{city}]: {building} reached target level {level}, removing from queue.",
        "pt": "      -> Fila [{city}]: {building} atingiu nível alvo {level}, a remover da fila.",
    },
    "queue_no_resources": {
        "en": "      -> Queue [{city}]: {building} — insufficient resources, will retry next cycle.",
        "pt": "      -> Fila [{city}]: {building} — recursos insuficientes, tenta no próximo ciclo.",
    },
    "queue_city_busy": {
        "en": "      -> Queue [{city}]: construction already in progress, skipping.",
        "pt": "      -> Fila [{city}]: construção já em curso, a saltar.",
    },
    "queue_prestage": {
        "en": "      -> Queue [{city}]: pre-staging resources for next item ({building}) while busy.",
        "pt": "      -> Fila [{city}]: a pré-posicionar recursos para o próximo item ({building}) durante a obra.",
    },
    "queue_started": {
        "en": "      -> Queue [{city}]: started {building} {from_lv} → {to_lv}.",
        "pt": "      -> Fila [{city}]: iniciada construção {building} {from_lv} → {to_lv}.",
    },
    "queue_start_failed": {
        "en": "      -> Queue [{city}]: failed to start {building} (server rejected).",
        "pt": "      -> Fila [{city}]: falhou ao iniciar {building} (servidor recusou).",
    },
    "queue_construction_done": {
        "en": "      -> Queue [{city}]: {building} construction completed.",
        "pt": "      -> Fila [{city}]: construção de {building} concluída.",
    },
    "queue_no_citizens": {
        "en": "      -> Queue [{city}]: {building} — no free citizens, will retry next cycle.",
        "pt": "      -> Fila [{city}]: {building} — sem cidadãos livres, tenta no próximo ciclo.",
    },
    "queue_attempting": {
        "en": "      -> Queue [{city}]: attempting {building} lv{lv} (type={btype}, pos={pos}, canUpgrade={can}, citizens={cit})",
        "pt": "      -> Fila [{city}]: a tentar {building} lv{lv} (tipo={btype}, pos={pos}, canUpgrade={can}, cidadãos={cit})",
    },
    "queue_post_resp": {
        "en": "      -> Queue [{city}]: POST response: {resp}",
        "pt": "      -> Fila [{city}]: resposta POST: {resp}",
    },
    "queue_done": {
        "en": "[+] Building queue cycle done.",
        "pt": "[+] Ciclo da fila de construção concluído.",
    },
    "queue_stale_cleanup": {
        "en": "      -> inProgress entry for {city} ({building}) has no queue items and ETA passed — removing.",
        "pt": "      -> inProgress de {city} ({building}) sem itens na fila e ETA expirado — a remover.",
    },
    "queue_wake": {
        "en": "[{ts}] Queue wake-up: checking constructions...",
        "pt": "[{ts}] Acordei para a fila de construção: a verificar construções...",
    },
    "queue_sleep_until": {
        "en": "      -> Next construction ETA: {eta}. Sleeping {mins} min.",
        "pt": "      -> Próxima construção prevista: {eta}. A dormir {mins} min.",
    },
    "cycle_sleep": {
        "en": "[+] Sleeping {mins} min until next empire cycle.",
        "pt": "[+] A dormir {mins} min até ao próximo ciclo do império.",
    },
    "queue_no_cost_data": {
        "en": "      -> Queue [{city}]: no cost data for {building}, retrying next cycle.",
        "pt": "      -> Fila [{city}]: sem dados de custos para {building}, tenta no próximo ciclo.",
    },
    "queue_transport_missing": {
        "en": "      -> Queue [{city}]: {building} — missing: {missing}",
        "pt": "      -> Fila [{city}]: {building} — faltam: {missing}",
    },
    "queue_transport_waiting": {
        "en": "      -> Queue [{city}]: resources in transit, waiting for arrival.",
        "pt": "      -> Fila [{city}]: recursos a caminho, a aguardar chegada.",
    },
    "queue_no_ships": {
        "en": "      -> Queue [{city}]: no ships available, retrying next cycle.",
        "pt": "      -> Fila [{city}]: sem navios disponíveis, tenta no próximo ciclo.",
    },
    "queue_no_surplus": {
        "en": "      -> Queue [{city}]: no surplus in other cities to send.",
        "pt": "      -> Fila [{city}]: sem excedentes noutras cidades para enviar.",
    },
    "queue_transport_sent": {
        "en": "      -> Queue [{city}]: sent {amount} {resource} from {origin} ({ships} ships).",
        "pt": "      -> Fila [{city}]: enviou {amount} {resource} de {origin} ({ships} navios).",
    },
    "queue_transport_sent_bundle": {
        "en": "      -> Queue [{city}]: sent {resources} from {origin} ({ships} ships).",
        "pt": "      -> Fila [{city}]: enviou {resources} de {origin} ({ships} navios).",
    },
    "queue_freighter_sent": {
        "en": "      -> Queue [{city}]: freighters — sent {resources} from {origin} ({ships} freighters).",
        "pt": "      -> Fila [{city}]: cargueiros — enviou {resources} de {origin} ({ships} cargueiros).",
    },
    "queue_freighter_failed": {
        "en": "      -> Queue [{city}]: freighter dispatch from {origin} rejected by server.",
        "pt": "      -> Fila [{city}]: despacho de cargueiro de {origin} recusado pelo servidor.",
    },
    "queue_transport_failed": {
        "en": "      -> Queue [{city}]: transport from {origin} rejected by server.",
        "pt": "      -> Fila [{city}]: transporte de {origin} recusado pelo servidor.",
    },
    "queue_outside_hours": {
        "en": "      -> Queue: outside active hours ({start}h–{end}h), skipping actions.",
        "pt": "      -> Fila: fora das horas activas ({start}h–{end}h), a saltar acções.",
    },
    "queue_sleep_until_hours": {
        "en": "[+] Outside active hours. Sleeping {mins} min until {start}h.",
        "pt": "[+] Fora das horas activas. A dormir {mins} min até às {start}h.",
    },
    "queue_movements_refresh": {
        "en": "      -> Transport dispatched — refreshing movements for ETA tracking.",
        "pt": "      -> Transporte enviado — a actualizar movimentos para rastreio de ETA.",
    },
    "scan_outside_hours": {
        "en": "[+] Outside scan hours ({start}h–{end}h). Sleeping {mins} min (night interval).",
        "pt": "[+] Fora das horas de scan ({start}h–{end}h). A dormir {mins} min (intervalo nocturno).",
    },
}


def lm(key, **kwargs):
    """Return log message in current LOG_LANG (fallback to English)."""
    msg = _LM[key].get(LOG_LANG, _LM[key]["en"])
    return msg.format(**kwargs) if kwargs else msg


def with_retry(fn, attempts=3, delay=30, label="", retryable=None):
    """Call fn(), retrying up to `attempts` times on exception with `delay` s between tries.
    `retryable`: tuple of exception types to retry (default None = all exceptions).
    Non-retryable exceptions are re-raised immediately without consuming attempts."""
    import time as _time
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if retryable is not None and not isinstance(exc, retryable):
                raise
            last_exc = exc
            if i < attempts - 1:
                logger.warning("[retry] %s: %s — retrying in %ss (%d/%d)",
                               label, exc, delay, i + 1, attempts - 1)
                _time.sleep(delay)
    raise last_exc


# ── Subsystem health (P5.2): make silent failures visible ───────────────────────
# ~150 `except Exception` swallow errors across the bot, so it can be "alive but useless"
# (a dispatch failing every cycle, a parser returning {} after a game HTML change). Each
# subsystem records success/failure here; N consecutive failures raise a Telegram alert
# (once), cleared on recovery. Flask reads health.json to surface it in the UI.
HEALTH_JSON_PATH = os.path.join(LOGS_DIR, "health.json")
_HEALTH_ALERT_THRESHOLD = 3


def _load_health():
    try:
        with open(HEALTH_JSON_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_health(data):
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(HEALTH_JSON_PATH, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def record_success(subsystem):
    """Mark a subsystem's cycle successful: reset its failure streak and, if it had alerted
    as down, send a recovery notification."""
    data = _load_health()
    rec = data.get(subsystem, {})
    was_alerted = bool(rec.get("alerted"))
    rec.update({"consecutiveFailures": 0, "lastSuccessAt": int(time.time()),
                "lastError": None, "alerted": False})
    data[subsystem] = rec
    _save_health(data)
    if was_alerted:
        try:
            from telegram_notifier import notify_subsystem_recovered
            notify_subsystem_recovered(subsystem)
        except Exception:
            pass


def record_failure(subsystem, error):
    """Increment a subsystem's failure streak; alert once when it reaches the threshold."""
    data = _load_health()
    rec = data.get(subsystem, {})
    streak = int(rec.get("consecutiveFailures", 0)) + 1
    rec.update({"consecutiveFailures": streak, "lastError": str(error)[:300],
                "lastFailureAt": int(time.time()),
                "totalFailures": int(rec.get("totalFailures", 0)) + 1})
    should_alert = streak >= _HEALTH_ALERT_THRESHOLD and not rec.get("alerted")
    if should_alert:
        rec["alerted"] = True
    data[subsystem] = rec
    _save_health(data)
    if should_alert:
        try:
            from telegram_notifier import notify_subsystem_down
            notify_subsystem_down(subsystem, streak, str(error)[:200])
        except Exception:
            pass


@contextlib.contextmanager
def health_guard(subsystem, swallow=True):
    """Wrap a subsystem's work and record success/failure for observability. Swallows the
    exception by default (so the other subsystems still run); `swallow=False` re-raises after
    recording (the full empire cycle, where failure must abort the iteration). Never swallows
    SystemExit/KeyboardInterrupt — those are fatal and handled by the main loop (P5.1)."""
    try:
        yield
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as exc:
        logger.warning("[%s] falhou", subsystem, exc_info=True)
        record_failure(subsystem, f"{type(exc).__name__}: {exc}")
        if not swallow:
            raise
    else:
        record_success(subsystem)


# ── Central anti-detection throttle (P5.3) ──────────────────────────────────────
# Rule #1: every game request needs a delay. That was enforced by scattered time.sleep()
# calls — easy to forget on a new code path. ThrottledSession wraps the game session so
# EVERY get/post is guaranteed a minimum spacing from the previous one: a floor, not an
# additive sleep. Where local code already slept (5-15s) the elapsed time already exceeds the
# floor → no extra wait; where a path forgot, the floor (≈1.5-3.5s) still applies. Set
# IKABOT_NO_THROTTLE=1 to disable (escape hatch if it ever interferes in-game).
_THROTTLE_MIN_INTERVAL = 1.5   # seconds; minimum gap between any two game requests
_THROTTLE_JITTER = 2.0         # random 0..this added on top of the minimum


class ThrottledSession:
    """Transparent proxy over an ikabot Session enforcing a minimum spacing between game
    requests. Every non-get/post attribute is delegated to the wrapped session."""

    def __init__(self, inner, min_interval=_THROTTLE_MIN_INTERVAL, jitter=_THROTTLE_JITTER):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_min_interval", min_interval)
        object.__setattr__(self, "_jitter", jitter)
        object.__setattr__(self, "_last_request", 0.0)

    def _throttle(self):
        floor = self._min_interval + random.uniform(0, self._jitter)
        elapsed = time.time() - self._last_request
        if elapsed < floor:
            time.sleep(floor - elapsed)
        object.__setattr__(self, "_last_request", time.time())

    def get(self, *args, **kwargs):
        self._throttle()
        return self._inner.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        self._throttle()
        return self._inner.post(*args, **kwargs)

    def __getattr__(self, name):
        # only reached when `name` isn't found normally → delegate to the wrapped session
        return getattr(object.__getattribute__(self, "_inner"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_inner"), name, value)


def throttle_session(session):
    """Wrap a session so all downstream game I/O is rate-limited. Idempotent; honours the
    IKABOT_NO_THROTTLE escape hatch."""
    if os.getenv("IKABOT_NO_THROTTLE") == "1" or isinstance(session, ThrottledSession):
        return session
    return ThrottledSession(session)


# ── Config schema validation (P5.8) ─────────────────────────────────────────────
# Settings loaders fall back to defaults on any error, so a typo'd key (e.g. "spyAgent"
# instead of "spyAgents") is silently ignored — the bot uses the default and the user never
# knows their setting did nothing. validate_configs() checks the known config files against
# their authoritative schemas (the keys the Flask writers actually produce) and warns on
# unknown keys / wrong types, surfacing it in the log, config_warnings.json and the UI.
CONFIG_WARNINGS_PATH = os.path.join(LOGS_DIR, "config_warnings.json")

_CONFIG_SCHEMAS = {
    "farm_settings.json": {
        "army": dict, "fleet": dict, "spyAgents": int, "shipReserveEnabled": bool,
        "reserveHorizonMin": int, "earlyRespyEnabled": bool,
    },
    "auto_attack_settings.json": {
        "enabled": bool, "minLootTotal": int, "lootPerWave": int, "battleDelayFewMins": int,
        "battleDelayMedMins": int, "battleDelayManyMins": int, "maxEnemyShipsToEngage": int,
    },
    "espionage_settings.json": {"garrisonThresholdTotal": int, "processingEnabled": bool},
    "world_scan_settings.json": {"enabled": bool},
    "telegram_settings.json": {"botToken": str, "chatId": str},
}


def _type_ok(value, expected):
    if expected is int:                 # bool is an int subclass — keep them distinct
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is bool:
        return isinstance(value, bool)
    return isinstance(value, expected)


def validate_configs():
    """Check known config files against their schemas. Returns {filename: [warnings]}, logs
    each warning and writes config_warnings.json for the dashboard."""
    warnings = {}
    for fname, schema in _CONFIG_SCHEMAS.items():
        path = os.path.join(LOGS_DIR, fname)
        try:
            with open(path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        file_warnings = []
        for key, value in data.items():
            if key not in schema:
                file_warnings.append(f"chave desconhecida '{key}' — typo? (ignorada, usa-se o default)")
            elif not _type_ok(value, schema[key]):
                file_warnings.append(
                    f"'{key}' é {type(value).__name__}, esperado {schema[key].__name__}")
        if file_warnings:
            warnings[fname] = file_warnings
            for w in file_warnings:
                logger.warning("[config] %s: %s", fname, w)
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(CONFIG_WARNINGS_PATH, "w") as f:
            json.dump(warnings, f)
    except Exception:
        pass
    return warnings

