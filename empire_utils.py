#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import re


def _setup_logger():
    _log = logging.getLogger("ikabot")
    if not _log.handlers:
        _handler = logging.StreamHandler()
        _handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        ))
        _log.addHandler(_handler)
        _log.setLevel(logging.INFO)
        _log.propagate = False
    # Silence ikabot's internal HTTP/session debug noise
    for _noisy in ("ikabot.web", "ikabot.web.session", "ikabot.helpers"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)
    return _log


logger = _setup_logger()

LOGS_DIR = "/tmp/ikalogs/"
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
