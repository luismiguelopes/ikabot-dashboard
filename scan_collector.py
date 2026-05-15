#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import random
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from empire_utils import (
    LOGS_DIR, WORLD_SCAN_RADIUS, WORLD_SCAN_UPDATE_INTERVAL,
    SCAN_CHECKPOINT_PATH, lm, logger,
)

from ikabot.helpers.getJson import getIsland

_FORCE_FLAG = os.path.join(LOGS_DIR, ".force_world_scan")


# ── State helpers ─────────────────────────────────────────────────────────────

def should_start_scan():
    """True if a new world scan should be started.
    Returns False if a scan is already in progress (checkpoint exists)."""
    if os.path.exists(_FORCE_FLAG):
        try:
            os.remove(_FORCE_FLAG)
        except Exception:
            pass
        # Force-restart: discard any in-progress checkpoint
        try:
            os.remove(SCAN_CHECKPOINT_PATH)
        except Exception:
            pass
        return True

    if os.path.exists(SCAN_CHECKPOINT_PATH):
        return False  # scan already in progress — don't start another

    try:
        from db_manager import scan_last_updated
        last_ts = scan_last_updated()
        if last_ts:
            return time.time() - last_ts > WORLD_SCAN_UPDATE_INTERVAL
    except Exception:
        pass
    scan_path = os.path.join(LOGS_DIR, "world_scan.json")
    if not os.path.exists(scan_path):
        return True
    return time.time() - os.path.getmtime(scan_path) > WORLD_SCAN_UPDATE_INTERVAL


def scan_has_pending():
    """True if a deep-scan checkpoint exists with islands still to process."""
    if not os.path.exists(SCAN_CHECKPOINT_PATH):
        return False
    try:
        with open(SCAN_CHECKPOINT_PATH) as f:
            cp = json.load(f)
        return len(cp.get("islandsQueue", [])) > 0
    except Exception:
        return False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _dist(x1, y1, x2, y2):
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def _write_scan_status(status, phase, progress, total, message):
    path = os.path.join(LOGS_DIR, "world_scan_status.json")
    try:
        with open(path, "w") as f:
            json.dump({
                "status":    status,
                "phase":     phase,
                "progress":  progress,
                "total":     total,
                "message":   message,
                "updatedAt": int(time.time()),
            }, f)
    except Exception:
        pass


def _publish_partial(cp):
    """Write current accumulated results to world_scan.json (progressive update)."""
    done = cp["totalIslands"] - len(cp["islandsQueue"])
    scan_path = os.path.join(LOGS_DIR, "world_scan.json")
    try:
        with open(scan_path, "w") as f:
            json.dump({
                "lastUpdated":    int(time.time()),
                "scanRadius":     WORLD_SCAN_RADIUS,
                "ownCities":      cp["ownCities"],
                "players":        cp["players"],
                "islands":        cp["islands"],
                "scanInProgress": True,
                "scanProgress":   {"done": done, "total": cp["totalIslands"]},
            }, f, indent=2)
    except Exception:
        pass


def _finalize_scan(cp):
    """Publish final world_scan.json (no scanInProgress), record timestamp, delete checkpoint."""
    scan_path = os.path.join(LOGS_DIR, "world_scan.json")
    try:
        with open(scan_path, "w") as f:
            json.dump({
                "lastUpdated":    int(time.time()),
                "scanRadius":     WORLD_SCAN_RADIUS,
                "ownCities":      cp["ownCities"],
                "players":        cp["players"],
                "islands":        cp["islands"],
                "scanInProgress": False,
                "scanProgress":   {"done": cp["totalIslands"], "total": cp["totalIslands"]},
            }, f, indent=2)
    except Exception:
        pass

    try:
        from db_manager import save_scan_timestamp
        save_scan_timestamp(int(time.time()))
    except Exception:
        pass

    try:
        os.remove(SCAN_CHECKPOINT_PATH)
    except Exception:
        pass

    n = len(cp["players"])
    _write_scan_status("idle", "done", cp["totalIslands"], cp["totalIslands"],
        lm("scan_status_done", n=n))
    logger.info(lm("scan_done", n=n))


# ── Phase 1: shallow scan ─────────────────────────────────────────────────────

def collect_shallow_scan(session):
    """Run 4 getJSONArea calls to discover islands, then create the deep-scan checkpoint.
    Called once per scan cycle, from the main bot loop (within active hours)."""
    try:
        own_cities_path = os.path.join(LOGS_DIR, "own_cities.json")
        if not os.path.exists(own_cities_path):
            logger.warning(lm("own_cities_missing"))
            return
        with open(own_cities_path) as f:
            own_cities = json.load(f)
        if not own_cities:
            return

        # Save the current world_scan.json as the "previous" scan before anything changes
        scan_path = os.path.join(LOGS_DIR, "world_scan.json")
        if os.path.exists(scan_path):
            try:
                with open(scan_path, "rb") as src:
                    with open(os.path.join(LOGS_DIR, "world_scan_prev.json"), "wb") as dst:
                        dst.write(src.read())
            except Exception:
                pass

        logger.info(lm("world_scan_start", ts=time.strftime('%H:%M:%S'), radius=WORLD_SCAN_RADIUS))
        _write_scan_status("running", "shallow_scan", 0, 4, lm("scan_status_shallow"))

        shallow_islands = []
        quadrants = [
            ("0",  "50",  "0",  "50"),
            ("50", "100", "0",  "50"),
            ("0",  "50",  "50", "100"),
            ("50", "100", "50", "100"),
        ]
        for i, (x_min, x_max, y_min, y_max) in enumerate(quadrants):
            _write_scan_status("running", "shallow_scan", i + 1, 4,
                lm("scan_status_quadrant", x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max))
            time.sleep(random.randint(2, 5))
            data = session.post(
                f"action=WorldMap&function=getJSONArea"
                f"&x_min={x_min}&x_max={x_max}&y_min={y_min}&y_max={y_max}"
            )
            for x, val in json.loads(data)["data"].items():
                for y, val2 in val.items():
                    shallow_islands.append({
                        "x": int(x), "y": int(y),
                        "id": val2[0], "name": val2[1],
                        "resource_type": val2[2],
                        "players": int(val2[7]),
                    })

        seen_ids = set()
        islands_to_scan = []
        for island in shallow_islands:
            if not island["players"] or island["id"] in seen_ids:
                continue
            for city in own_cities:
                if _dist(island["x"], island["y"], city["x"], city["y"]) <= WORLD_SCAN_RADIUS:
                    seen_ids.add(island["id"])
                    islands_to_scan.append(island)
                    break

        logger.info(lm("scan_islands_count", n=len(islands_to_scan), radius=WORLD_SCAN_RADIUS))
        logger.info(lm("scan_shallow_complete", n=len(islands_to_scan)))

        cp = {
            "startedAt":    int(time.time()),
            "ownCities":    own_cities,
            "islandsQueue": islands_to_scan,
            "totalIslands": len(islands_to_scan),
            "players":      [],
            "islands":      [],
        }
        with open(SCAN_CHECKPOINT_PATH, "w") as f:
            json.dump(cp, f)

        _write_scan_status("running", "deep_scan", 0, len(islands_to_scan),
            lm("scan_status_deep", n=len(islands_to_scan)))

    except Exception:
        logger.error(lm("scan_error"), exc_info=True)
        _write_scan_status("error", "error", 0, 0, lm("scan_status_error"))


# ── Phase 2: incremental deep scan ───────────────────────────────────────────

def scan_next_island(session):
    """Process one island from the checkpoint (called from smart_sleep during idle time).
    Includes the anti-detection delay. Returns True if more islands remain, False if done."""
    if not os.path.exists(SCAN_CHECKPOINT_PATH):
        return False

    try:
        with open(SCAN_CHECKPOINT_PATH) as f:
            cp = json.load(f)
    except Exception:
        return False

    islands_queue = cp.get("islandsQueue", [])
    if not islands_queue:
        _finalize_scan(cp)
        return False

    island = islands_queue.pop(0)
    done_count = cp["totalIslands"] - len(islands_queue)

    pause = random.randint(15, 30)
    logger.info(lm("scan_island_pause", pause=pause,
                   i=done_count, total=cp["totalIslands"],
                   x=island["x"], y=island["y"]))
    time.sleep(pause)

    own_cities = cp["ownCities"]

    try:
        html = session.get("view=island&islandId=" + str(island["id"]))
        island_data = getIsland(html)

        nearest = min(own_cities,
            key=lambda c: _dist(island["x"], island["y"], c["x"], c["y"]))
        nearest_dist = _dist(island["x"], island["y"], nearest["x"], nearest["y"])

        cities_list = island_data.get("cities", [])
        free_slots = sum(1 for c in cities_list if c.get("type") == "empty")
        cp["islands"].append({
            "islandId":       str(island["id"]),
            "islandName":     island_data.get("name", island.get("name", "")),
            "x":              island["x"],
            "y":              island["y"],
            "resourceType":   int(island["resource_type"]) if island.get("resource_type") else 0,
            "woodLevel":      island_data.get("resourceLevel", ""),
            "luxuryLevel":    island_data.get("tradegoodLevel", ""),
            "wonder":         island_data.get("wonderName", ""),
            "wonderLevel":    island_data.get("wonderLevel", ""),
            "freeSlots":      free_slots,
            "totalSlots":     len(cities_list),
            "hasOwnCity":     bool(island_data.get("isOwnCityOnIsland", False)),
            "nearestOwnCity": nearest["name"],
            "distance":       round(nearest_dist, 1),
        })

        avatar_scores = island_data.get("avatarScores", {})
        for city_slot in cities_list:
            if city_slot.get("type") == "empty":
                continue
            state = city_slot.get("state", "")
            if state not in ("inactive", "vacation"):
                continue
            owner_name = city_slot.get("ownerName", "")
            if not owner_name:
                continue
            owner_id = str(city_slot.get("ownerId", city_slot.get("Id", "")))
            scores_raw = avatar_scores.get(owner_id, {})
            cp["players"].append({
                "playerId":       owner_id,
                "playerName":     owner_name,
                "allyTag":        city_slot.get("ownerAllyTag", city_slot.get("AllyTag", "")),
                "state":          state,
                "cityName":       city_slot.get("name", ""),
                "islandName":     island_data.get("name", island.get("name", "")),
                "islandX":        island["x"],
                "islandY":        island["y"],
                "nearestOwnCity": nearest["name"],
                "distance":       round(nearest_dist, 1),
                "scores": {
                    "building": scores_raw.get("building_score_main", "0"),
                    "research": scores_raw.get("research_score_main", "0"),
                    "army":     scores_raw.get("army_score_main", "0"),
                    "trader":   scores_raw.get("trader_score_secondary", "0"),
                    "rank":     scores_raw.get("place", ""),
                },
            })

    except Exception as e:
        logger.warning(lm("scan_island_error", id=island["id"], err=e))

    # Persist progress
    cp["islandsQueue"] = islands_queue
    try:
        with open(SCAN_CHECKPOINT_PATH, "w") as f:
            json.dump(cp, f)
    except Exception:
        pass

    # Progressive publish — UI sees new data after each island
    _publish_partial(cp)
    _write_scan_status("running", "deep_scan", done_count, cp["totalIslands"],
        lm("scan_island_done", i=done_count, total=cp["totalIslands"],
           x=island["x"], y=island["y"]))

    if not islands_queue:
        _finalize_scan(cp)
        return False

    return True
