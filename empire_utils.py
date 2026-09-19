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
    """Terminal shows LOG_LEVEL+ (default INFO: events only — routine chatter lives at
    DEBUG); bot.log always records DEBUG so nothing is lost for troubleshooting."""
    _log = logging.getLogger("ikabot")
    if not _log.handlers:
        _handler = logging.StreamHandler()
        _handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        ))
        _handler.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
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
            _fh.setLevel(logging.DEBUG)
            _log.addHandler(_fh)
        except Exception:
            pass
        _log.setLevel(logging.DEBUG)
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
FORCE_COSTS_FLAG          = os.path.join(LOGS_DIR, ".force_costs_update")
FORCE_WINE_BUY_FLAG       = os.path.join(LOGS_DIR, ".force_wine_buy")
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
        "en": "World scan started (radius={radius})...",
        "pt": "World scan iniciado (raio={radius})...",
    },
    "scan_status_shallow": {
        "en": "[world_scan] Scanning map...",
        "pt": "[world_scan] A escanear mapa...",
    },
    "scan_status_quadrant": {
        "en": "[world_scan] Map ({x_min}-{x_max},{y_min}-{y_max})...",
        "pt": "[world_scan] Mapa ({x_min}-{x_max},{y_min}-{y_max})...",
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
        "en": "[world_scan] Scanning {n} islands...",
        "pt": "[world_scan] A escanear {n} ilhas...",
    },
    "scan_island_pause": {
        "en": "[world_scan] Pause {pause}s | Island {i}/{total} ({x},{y})...",
        "pt": "[world_scan] Pausa {pause}s | Ilha {i}/{total} ({x},{y})...",
    },
    "scan_island_done": {
        "en": "[world_scan] Island {i}/{total} ({x},{y}) processed",
        "pt": "[world_scan] Ilha {i}/{total} ({x},{y}) processada",
    },
    "scan_island_error": {
        "en": "[world_scan] Error on island {id}: {err}",
        "pt": "[world_scan] Erro na ilha {id}: {err}",
    },
    "scan_status_done": {
        "en": "[world_scan] Done: {n} inactive/vacation players found",
        "pt": "[world_scan] Concluído: {n} inactivos/férias encontrados",
    },
    "scan_done": {
        "en": "[world_scan] Done: {n} inactive/vacation players found.",
        "pt": "[world_scan] Concluído: {n} inactivos/férias encontrados.",
    },
    "scan_error": {
        "en": "[world_scan] World scan error:",
        "pt": "[world_scan] Erro no world scan:",
    },
    "scan_status_error": {
        "en": "[world_scan] Error during scan",
        "pt": "[world_scan] Erro durante o scan",
    },
    "costs_start": {
        "en": "[costs] Starting building cost extraction (human mode)...",
        "pt": "[costs] A iniciar extração de custos de edificios (modo humano)...",
    },
    "costs_city_pause": {
        "en": "[costs] Pause {pause}s before next city...",
        "pt": "[costs] Pausa de {pause}s antes de próxima cidade...",
    },
    "costs_city_start": {
        "en": "[costs] Costs: {city}...",
        "pt": "[costs] Custos: {city}...",
    },
    "costs_city_done": {
        "en": "[costs] Success: {city} — {n} buildings with costs extracted.",
        "pt": "[costs] Sucesso: {city} — {n} edificios com custos extraídos.",
    },
    "costs_city_error": {
        "en": "[costs] Error extracting costs for city {id}:",
        "pt": "[costs] Erro ao extrair custos de cidade {id}:",
    },
    "costs_done": {
        "en": "[costs] Building cost extraction done!",
        "pt": "[costs] Extração de custos de edificios concluída!",
    },
    "costs_error": {
        "en": "[costs] Error in cost extraction:",
        "pt": "[costs] Erro na extração de custos:",
    },
    "movements_error": {
        "en": "[empire] Warning: could not collect movements:",
        "pt": "[empire] Aviso: não foi possível recolher movimentos:",
    },
    "empire_start_1": {
        "en": "[empire] Empire Function started in background!",
        "pt": "[empire] Empire Function arrancada em Segundo Plano!",
    },
    "empire_start_2": {
        "en": "[empire] Silently collecting empire data every {interval} seconds...",
        "pt": "[empire] Extrai dados do império silenciosamente a cada {interval} segundos...",
    },
    "cycle_start": {
        "en": "[empire] Updating empire JSON files...",
        "pt": "[empire] A atualizar ficheiros JSON do Imperio...",
    },
    "city_done": {
        "en": "[empire] Success: City {city} extracted.",
        "pt": "[empire] Sucesso: Cidade {city} extraída.",
    },
    "cycle_done": {
        "en": "[empire] Empire updated: {n} cities ({mins} min)",
        "pt": "[empire] Império actualizado: {n} cidades ({mins} min)",
    },
    "cycle_error": {
        "en": "[empire] Error during data extraction:",
        "pt": "[empire] Erro durante extracção de dados:",
    },
    "queue_cycle_start": {
        "en": "[build] Processing building queue...",
        "pt": "[build] A processar fila de construção...",
    },
    "queue_city_not_found": {
        "en": "[build] city '{city}' not found in session, skipping.",
        "pt": "[build] cidade '{city}' não encontrada na sessão, a ignorar.",
    },
    "queue_building_not_found": {
        "en": "[build] {city}: building '{building}' not found, removing from queue.",
        "pt": "[build] {city}: edifício '{building}' não encontrado, a remover da fila.",
    },
    "queue_max_level": {
        "en": "[build] {city}: {building} already at max level, removing from queue.",
        "pt": "[build] {city}: {building} já está no nível máximo, a remover da fila.",
    },
    "queue_target_reached": {
        "en": "[build] {city}: {building} reached target level {level}, removing from queue.",
        "pt": "[build] {city}: {building} atingiu nível alvo {level}, a remover da fila.",
    },
    "queue_no_resources": {
        "en": "[build] {city}: {building} — insufficient resources, will retry next cycle.",
        "pt": "[build] {city}: {building} — recursos insuficientes, tenta no próximo ciclo.",
    },
    "queue_city_busy": {
        "en": "[build] {city}: construction already in progress, skipping.",
        "pt": "[build] {city}: construção já em curso, a saltar.",
    },
    "queue_prestage": {
        "en": "[build] {city}: pre-staging resources for next item ({building}) while busy.",
        "pt": "[build] {city}: a pré-posicionar recursos para o próximo item ({building}) durante a obra.",
    },
    "queue_started": {
        "en": "[build] {city}: started {building} {from_lv} → {to_lv}.",
        "pt": "[build] {city}: iniciada construção {building} {from_lv} → {to_lv}.",
    },
    "queue_start_failed": {
        "en": "[build] {city}: failed to start {building} (server rejected).",
        "pt": "[build] {city}: falhou ao iniciar {building} (servidor recusou).",
    },
    "queue_construction_done": {
        "en": "[build] {city}: {building} construction completed.",
        "pt": "[build] {city}: construção de {building} concluída.",
    },
    "queue_no_citizens": {
        "en": "[build] {city}: {building} — no free citizens, will retry next cycle.",
        "pt": "[build] {city}: {building} — sem cidadãos livres, tenta no próximo ciclo.",
    },
    "queue_attempting": {
        "en": "[build] {city}: attempting {building} lv{lv} (type={btype}, pos={pos}, canUpgrade={can}, citizens={cit})",
        "pt": "[build] {city}: a tentar {building} lv{lv} (tipo={btype}, pos={pos}, canUpgrade={can}, cidadãos={cit})",
    },
    "queue_post_resp": {
        "en": "[build] {city}: POST response: {resp}",
        "pt": "[build] {city}: resposta POST: {resp}",
    },
    "queue_done": {
        "en": "[build] Building queue cycle done.",
        "pt": "[build] Ciclo da fila de construção concluído.",
    },
    "queue_stale_cleanup": {
        "en": "[build] inProgress entry for {city} ({building}) has no queue items and ETA passed — removing.",
        "pt": "[build] inProgress de {city} ({building}) sem itens na fila e ETA expirado — a remover.",
    },
    "queue_wake": {
        "en": "[build] Queue wake-up: checking constructions...",
        "pt": "[build] Acordei para a fila de construção: a verificar construções...",
    },
    "queue_sleep_until": {
        "en": "[build] Next construction ETA: {eta}. Sleeping {mins} min.",
        "pt": "[build] Próxima construção prevista: {eta}. A dormir {mins} min.",
    },
    "cycle_sleep": {
        "en": "[sleep] Sleeping {mins} min until next empire cycle.",
        "pt": "[sleep] A dormir {mins} min até ao próximo ciclo do império.",
    },
    "queue_no_cost_data": {
        "en": "[build] {city}: no cost data for {building}, retrying next cycle.",
        "pt": "[build] {city}: sem dados de custos para {building}, tenta no próximo ciclo.",
    },
    "queue_transport_missing": {
        "en": "[build] {city}: {building} — missing: {missing}",
        "pt": "[build] {city}: {building} — faltam: {missing}",
    },
    "queue_transport_waiting": {
        "en": "[build] {city}: resources in transit, waiting for arrival.",
        "pt": "[build] {city}: recursos a caminho, a aguardar chegada.",
    },
    "queue_no_ships": {
        "en": "[build] {city}: no ships available, retrying next cycle.",
        "pt": "[build] {city}: sem navios disponíveis, tenta no próximo ciclo.",
    },
    "queue_no_surplus": {
        "en": "[build] {city}: no surplus in other cities to send.",
        "pt": "[build] {city}: sem excedentes noutras cidades para enviar.",
    },
    "queue_transport_sent": {
        "en": "[build] {city}: sent {amount} {resource} from {origin} ({ships} ships).",
        "pt": "[build] {city}: enviou {amount} {resource} de {origin} ({ships} navios).",
    },
    "queue_transport_sent_bundle": {
        "en": "[build] {city}: sent {resources} from {origin} ({ships} ships).",
        "pt": "[build] {city}: enviou {resources} de {origin} ({ships} navios).",
    },
    "queue_freighter_sent": {
        "en": "[build] {city}: freighters — sent {resources} from {origin} ({ships} freighters).",
        "pt": "[build] {city}: cargueiros — enviou {resources} de {origin} ({ships} cargueiros).",
    },
    "queue_freighter_failed": {
        "en": "[build] {city}: freighter dispatch from {origin} rejected by server.",
        "pt": "[build] {city}: despacho de cargueiro de {origin} recusado pelo servidor.",
    },
    "queue_transport_failed": {
        "en": "[build] {city}: transport from {origin} rejected by server.",
        "pt": "[build] {city}: transporte de {origin} recusado pelo servidor.",
    },
    "queue_outside_hours": {
        "en": "[build] outside active hours ({start}h–{end}h), skipping actions.",
        "pt": "[build] fora das horas activas ({start}h–{end}h), a saltar acções.",
    },
    "queue_sleep_until_hours": {
        "en": "[sleep] Outside active hours. Sleeping {mins} min until {start}h.",
        "pt": "[sleep] Fora das horas activas. A dormir {mins} min até às {start}h.",
    },
    "queue_movements_refresh": {
        "en": "[build] Transport dispatched — refreshing movements for ETA tracking.",
        "pt": "[build] Transporte enviado — a actualizar movimentos para rastreio de ETA.",
    },
    "scan_outside_hours": {
        "en": "[sleep] Outside scan hours ({start}h–{end}h). Sleeping {mins} min (night interval).",
        "pt": "[sleep] Fora das horas de scan ({start}h–{end}h). A dormir {mins} min (intervalo nocturno).",
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
        object.__setattr__(self, "_last_beat", 0.0)

    def _heartbeat(self):
        # Every game request proves the bot is alive, so long WORK phases (building costs,
        # world scan — tens of minutes with no smart_sleep) keep last_alive.json fresh and the
        # container healthcheck/autoheal (P5.1) don't false-restart mid-work. Gated to ~15s so
        # request-heavy phases don't hammer the disk. A genuine hang still stops beats → restart.
        now = time.time()
        if now - self._last_beat < 15:
            return
        object.__setattr__(self, "_last_beat", now)
        try:
            with open(LAST_ALIVE_JSON_PATH, "w") as f:
                json.dump({"lastAlive": int(now)}, f)
        except Exception:
            pass

    def _throttle(self):
        floor = self._min_interval + random.uniform(0, self._jitter)
        elapsed = time.time() - self._last_request
        if elapsed < floor:
            time.sleep(floor - elapsed)
        object.__setattr__(self, "_last_request", time.time())
        self._heartbeat()

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
    "espionage_settings.json": {"garrisonThresholdTotal": int, "minLootTotal": int,
                                "processingEnabled": bool},
    "world_scan_settings.json": {"enabled": bool},
    "telegram_settings.json": {"botToken": str, "chatId": str},
}


def _type_ok(value, expected):
    if expected is int:                 # bool is an int subclass — keep them distinct
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is bool:
        return isinstance(value, bool)
    return isinstance(value, expected)


def migrate_legacy_configs():
    """Rewrite config files that still use superseded keys so they stop being silently ignored
    (and stop tripping validate_configs). Run BEFORE validate_configs so the warning clears on
    the same start. Currently: espionage's per-resource `garrisonThresholds` (replaced by the
    single `garrisonThresholdTotal` the code now reads) — the old key was dead config."""
    path = os.path.join(LOGS_DIR, "espionage_settings.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return
    if not (isinstance(data, dict) and "garrisonThresholds" in data):
        return
    legacy = data.pop("garrisonThresholds")   # always drop the dead key
    if "garrisonThresholdTotal" not in data:   # …and seed the total from it only if absent
        try:
            total = sum(int(v) for v in legacy.values()) if isinstance(legacy, dict) else 0
        except (ValueError, TypeError):
            total = 0
        data["garrisonThresholdTotal"] = total or 50000
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("[config] espionage_settings: garrisonThresholds (legado) → "
                    "garrisonThresholdTotal=%d", data["garrisonThresholdTotal"])
    except Exception:
        logger.warning("[config] migração de espionage_settings falhou", exc_info=True)


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

