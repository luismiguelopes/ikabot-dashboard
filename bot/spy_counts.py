#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""Spy-count persistence layer.

Self-contained slice extracted from espionage_manager.py (P11.4): the on-disk
spy_counts.json cache (load/save), the per-city safehouse fetch+parse, and the
public getter. These depend only on external modules (empire_utils,
espionage_parsers, ikabot runtime), so they move cleanly with no circular import
back into espionage_manager. The orchestration layer (fetch_spy_counts,
count_in_field_by_city) stays in espionage_manager because it is entangled with
the missions store and safehouse sync.
"""

import json
import os

from empire_utils import LOGS_DIR, logger
from espionage_parsers import _parse_safehouse_page

SPY_COUNTS_PATH = os.path.join(LOGS_DIR, "spy_counts.json")


def _load_spy_counts():
    try:
        with open(SPY_COUNTS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"lastUpdated": 0, "byCityId": {}}


def _save_spy_counts(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(SPY_COUNTS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _fetch_city_spy_counts(session, city_id, city_name, position):
    """
    GET the safehouse AJAX view and parse spy counts from the changeView HTML.
    The response changeView[1][1] contains the full safehouse HTML with all counters.
    Returns (counts_dict, html_str), or (None, "") on error.
    """
    import ikabot.config as ikabot_config

    url = (
        f"view=safehouse&cityId={city_id}&position={position}"
        f"&backgroundView=city&currentCityId={city_id}"
        f"&actionRequest={ikabot_config.actionRequest}&ajax=1"
    )
    try:
        resp = session.get(url)
        resp_data = json.loads(resp, strict=False)
    except Exception as e:
        logger.error("[espionage] GET safehouse %s falhou: %s", city_name, e)
        return None, ""

    # Refresh CSRF token
    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "updateGlobalData":
            tok = entry[1].get("actionRequest") if isinstance(entry[1], dict) else None
            if tok:
                ikabot_config.actionRequest = tok
            break

    # changeView[1][1] contains the full safehouse building HTML with spy stats
    html_content = ""
    for entry in resp_data:
        if isinstance(entry, list) and entry[0] == "changeView":
            inner = entry[1]
            if isinstance(inner, list) and len(inner) > 1 and isinstance(inner[1], str):
                html_content = inner[1]
            break

    if not html_content:
        logger.warning("[espionage] safehouse %s: sem HTML no changeView (tipos: %s)",
                       city_name, [e[0] if isinstance(e, list) else e for e in resp_data[:6]])
        return None, ""

    counts = _parse_safehouse_page(html_content, city_name)
    counts["cityName"] = city_name
    return counts, html_content


def get_spy_counts():
    return _load_spy_counts()
