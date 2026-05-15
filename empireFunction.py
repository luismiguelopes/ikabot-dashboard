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
                    logger.info(lm("queue_wake", ts=time.strftime('%H:%M:%S')))
                    if process_building_queue(session, ids, cities):
                        logger.info(lm("queue_movements_refresh"))
                        refresh_movements(session, ids[0])
                smart_sleep(last_full_cycle_time, next_full_jitter, session)
                continue

            # ── Full empire data cycle ───────────────────────────────────────
            if not in_scan_hours:
                _night_mins = round(effective_interval / 60)
                logger.info(lm("scan_outside_hours",
                               start=SCAN_ACTIVE_HOURS_START, end=SCAN_ACTIVE_HOURS_END,
                               mins=_night_mins))

            logger.info(lm("cycle_start", ts=time.strftime('%H:%M:%S')))
            time.sleep(random.randint(3, 10))
            (ids, cities) = getIdsOfCities(session)

            status_summary, formatted_empire, resources_data = collect_city_data(session, ids, cities)

            finalize_empire_cycle(session, ids, status_summary, formatted_empire, resources_data)

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

            logger.info(lm("cycle_done"))
            last_full_cycle_time = time.time()
            next_full_jitter = random.randint(-300, 300)

            # ── Building queue (before scans — never blocked by long scans) ──
            if has_building_queue():
                if process_building_queue(session, ids, cities):
                    logger.info(lm("queue_movements_refresh"))
                    refresh_movements(session, ids[0])

            # ── Background scans (only during active hours) ───────────────────
            if in_scan_hours:
                if should_update_building_costs():
                    collect_building_costs(session, ids)
                elif should_start_scan():
                    collect_shallow_scan(session)

            smart_sleep(last_full_cycle_time, next_full_jitter, session)

        except Exception:
            logger.error(lm("cycle_error"), exc_info=True)
            time.sleep(random.randint(120, 300))
