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

from empire_utils import LOGS_DIR, LAST_ALIVE_JSON_PATH, UPDATE_INTERVAL, FORCE_EMPIRE_FLAG, FORCE_MOVEMENTS_FLAG, WINE_CRITICAL_NOTIFY_SECS, lm
from empire_collector import collect_city_data, finalize_empire_cycle, refresh_movements
from costs_collector import should_update_building_costs, collect_building_costs
from scan_collector import should_update_world_scan, collect_world_scan
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

    print(lm("empire_start_1"))
    print(lm("empire_start_2", interval=UPDATE_INTERVAL))

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
            do_full = ids is None or (now >= last_full_cycle_time + UPDATE_INTERVAL + next_full_jitter)

            # ── Queue-only wake-up ───────────────────────────────────────────
            if not do_full:
                if ids and os.path.exists(FORCE_MOVEMENTS_FLAG):
                    try:
                        os.remove(FORCE_MOVEMENTS_FLAG)
                    except Exception:
                        pass
                    refresh_movements(session, ids[0])
                if ids and has_building_queue():
                    print(lm("queue_wake", ts=time.strftime('%H:%M:%S')))
                    if process_building_queue(session, ids, cities):
                        print(lm("queue_movements_refresh"))
                        refresh_movements(session, ids[0])
                smart_sleep(last_full_cycle_time, next_full_jitter)
                continue

            # ── Full empire data cycle ───────────────────────────────────────
            print(lm("cycle_start", ts=time.strftime('%H:%M:%S')))
            (ids, cities) = getIdsOfCities(session)

            status_summary, formatted_empire, resources_data = collect_city_data(session, ids, cities)

            if should_update_building_costs():
                collect_building_costs(session, ids)
            elif should_update_world_scan():
                collect_world_scan(session)

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

            print(lm("cycle_done"))
            last_full_cycle_time = time.time()
            next_full_jitter = random.randint(-300, 300)

            # ── Building queue (after full cycle) ────────────────────────────
            if has_building_queue():
                if process_building_queue(session, ids, cities):
                    print(lm("queue_movements_refresh"))
                    refresh_movements(session, ids[0])

            smart_sleep(last_full_cycle_time, next_full_jitter)

        except Exception:
            import traceback
            print(lm("cycle_error"), traceback.format_exc())
            time.sleep(180)
