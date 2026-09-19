#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import random
import sys
import time

# Ensure sibling modules in the same directory are importable
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from empire_utils import (
    LOGS_DIR, LAST_ALIVE_JSON_PATH, UPDATE_INTERVAL,
    SCAN_ACTIVE_HOURS_START, SCAN_ACTIVE_HOURS_END, SCAN_NIGHT_INTERVAL,
    FORCE_EMPIRE_FLAG, FORCE_MOVEMENTS_FLAG, WINE_CRITICAL_NOTIFY_SECS, lm, logger,
    health_guard, throttle_session, record_success, record_failure,
    validate_configs, migrate_legacy_configs,
)
from empire_collector import collect_city_data, finalize_empire_cycle, refresh_movements
from costs_collector import should_update_building_costs, collect_building_costs
from scan_collector import should_start_scan, collect_shallow_scan
from queue_processor import has_building_queue, process_building_queue, smart_sleep

from ikabot.helpers.pedirInfo import getIdsOfCities


def empireFunction(session, event, stdin_fd, predetermined_input):
    """
    Parameters
    ----------
    session : ikabot.web.session.Session
    event : multiprocessing.Event
    stdin_fd: int
    predetermined_input : multiprocessing.managers.SyncManager.list
    """

    event.set()

    # P5.3: route all downstream game I/O through one rate-limiter (floor between requests).
    session = throttle_session(session)

    # P5.8: migrate superseded config keys, then surface mistyped/unknown ones (else silent).
    try:
        migrate_legacy_configs()
        validate_configs()
    except Exception:
        pass

    logger.info(lm("empire_start_1"))
    logger.info(lm("empire_start_2", interval=UPDATE_INTERVAL))

    ids = None
    cities = None
    last_full_cycle_time = 0
    next_full_jitter = 0
    cycle_count = 0

    try:
        from telegram_notifier import notify_started
        notify_started(1)
    except Exception:
        pass

    while True:
        try:
            cycle_count += 1
            try:
                os.makedirs(LOGS_DIR, exist_ok=True)
                with open(LAST_ALIVE_JSON_PATH, "w") as f:
                    json.dump({"lastAlive": int(time.time()), "cycle": cycle_count}, f)
            except Exception:
                pass

            # P6.3: daily SQLite backup to the host-mounted dir (no-op if already done today
            # or the mount is missing). Local file copy — no game I/O, no throttle involved.
            try:
                from db_manager import backup_db
                backup_db()
            except Exception:
                pass

            now = time.time()
            if os.path.exists(FORCE_EMPIRE_FLAG):
                try:
                    os.remove(FORCE_EMPIRE_FLAG)
                except Exception:
                    pass
                ids = None

            in_scan_hours = (
                SCAN_ACTIVE_HOURS_START == 0 and SCAN_ACTIVE_HOURS_END == 24
            ) or (SCAN_ACTIVE_HOURS_START <= time.localtime().tm_hour < SCAN_ACTIVE_HOURS_END)

            if in_scan_hours:
                effective_interval = UPDATE_INTERVAL + next_full_jitter
            else:
                effective_interval = SCAN_NIGHT_INTERVAL + random.randint(-600, 600)

            do_full = ids is None or (now >= last_full_cycle_time + effective_interval)

            # ── Queue-only wake-up ───────────────────────────────────────────
            if not do_full:
                if ids and os.path.exists(FORCE_MOVEMENTS_FLAG):
                    try:
                        os.remove(FORCE_MOVEMENTS_FLAG)
                    except Exception:
                        pass
                    refresh_movements(session, ids[0])
                if ids and has_building_queue():
                    logger.debug(lm("queue_wake", ts=time.strftime('%H:%M:%S')))
                    if process_building_queue(session, ids, cities):
                        logger.info(lm("queue_movements_refresh"))
                        refresh_movements(session, ids[0])
                if in_scan_hours:
                    with health_guard("espionage"):
                        from espionage_manager import process_spy_cycle
                        process_spy_cycle(session)
                    with health_guard("attack"):
                        from attack_manager import process_attack_queue
                        process_attack_queue(session, in_active_hours=True)
                smart_sleep(last_full_cycle_time, next_full_jitter, session)
                continue

            # ── Full empire data cycle ───────────────────────────────────────
            if not in_scan_hours:
                _night_mins = round(effective_interval / 60)
                logger.info(lm("scan_outside_hours",
                               start=SCAN_ACTIVE_HOURS_START, end=SCAN_ACTIVE_HOURS_END,
                               mins=_night_mins))

            logger.debug(lm("cycle_start", ts=time.strftime('%H:%M:%S')))
            _cycle_t0 = time.time()
            time.sleep(random.randint(3, 10))
            (ids, cities) = getIdsOfCities(session)

            status_summary, formatted_empire, resources_data = collect_city_data(session, ids, cities)

            finalize_empire_cycle(session, ids, status_summary, formatted_empire, resources_data)
            record_success("empire")

            try:
                from telegram_notifier import notify_wine_critical, clear_wine_critical
                for city_name, city_res in resources_data.items():
                    t = city_res.get("wineRunsOutIn", -1)
                    if t != -1 and 0 < t < WINE_CRITICAL_NOTIFY_SECS:
                        notify_wine_critical(city_name, t / 3600)
                    else:
                        clear_wine_critical(city_name)
            except Exception:
                pass

            logger.info(lm("cycle_done", n=len(ids), mins=round((time.time() - _cycle_t0) / 60)))
            last_full_cycle_time = time.time()
            next_full_jitter = random.randint(-300, 300)

            # ── Building queue (before scans — never blocked by long scans) ──
            with health_guard("building"):
                if has_building_queue():
                    if process_building_queue(session, ids, cities):
                        logger.info(lm("queue_movements_refresh"))
                        refresh_movements(session, ids[0])

            # ── Espionage / attacks / farm (income — first claim on trade ships) ──
            # Runs BEFORE internal logistics so the farm reserves its ships before
            # consolidation/wine/transports get a turn (which now yield to the reserve).
            # Each subsystem is guarded separately (P5.2) so one failing doesn't hide the
            # others and its failure streak is tracked for the health monitor.
            if in_scan_hours:
                with health_guard("espionage"):
                    from espionage_manager import fetch_spy_counts, process_spy_cycle
                    fetch_spy_counts(session)
                    process_spy_cycle(session)
                with health_guard("attack"):
                    from attack_manager import process_attack_queue
                    process_attack_queue(session, in_active_hours=in_scan_hours)
                with health_guard("farm"):
                    from farm_manager import process_farm_targets
                    process_farm_targets(session, in_active_hours=in_scan_hours)

            # ── Scheduled transports + consolidation (yield trade ships to the farm) ──
            if in_scan_hours:
                with health_guard("transport"):
                    from transport_manager import (
                        process_transport_queue, process_consolidation,
                        process_wine_balancer, process_wine_buyer,
                    )
                    process_transport_queue(session, in_active_hours=True)
                    process_consolidation(session, in_active_hours=True)
                    process_wine_buyer(session, in_active_hours=True)      # replenish from market
                    process_wine_balancer(session, in_active_hours=True)   # then spread it

            # ── Background scans (only during active hours) ───────────────────
            if in_scan_hours:
                with health_guard("scan"):
                    if should_update_building_costs():
                        collect_building_costs(session, ids)
                    elif should_start_scan():
                        collect_shallow_scan(session)
                    else:
                        from scan_collector import process_watchlist
                        process_watchlist(session, in_active_hours=True)

            smart_sleep(last_full_cycle_time, next_full_jitter, session)

        except (SystemExit, KeyboardInterrupt):
            # Fatal: the game session gave up (re-login/network exhausted → sys.exit) or a
            # manual stop. Alert loudly before dying so it's attributed immediately, not 30 min
            # later via the offline watchdog. With the container healthcheck + autoheal, the
            # worker's death restarts the whole container, recovering automatically.
            try:
                from telegram_notifier import notify_bot_fatal
                notify_bot_fatal()
            except Exception:
                pass
            raise
        except Exception as exc:
            logger.error(lm("cycle_error"), exc_info=True)
            record_failure("empire", f"{type(exc).__name__}: {exc}")
            time.sleep(random.randint(120, 300))
