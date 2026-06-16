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

def _world_scan_enabled():
    settings_path = os.path.join(LOGS_DIR, "world_scan_settings.json")
    try:
        with open(settings_path) as f:
            return json.load(f).get("enabled", True)
    except Exception:
        return True


def should_start_scan():
    """True if a new world scan should be started.
    Returns False if a scan is already in progress (checkpoint exists)."""
    if not _world_scan_enabled():
        return False
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
                "cityId":         str(city_slot.get("id", "")),
                "playerName":     owner_name,
                "allyTag":        city_slot.get("ownerAllyTag", city_slot.get("AllyTag", "")),
                "state":          state,
                "cityName":       city_slot.get("name", ""),
                "islandId":       str(island["id"]),
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


# ── Watchlist: periodic re-scan of "alvo"-marked players' islands (F7) ─────────

WATCHLIST_SETTINGS_PATH = os.path.join(LOGS_DIR, "watchlist_settings.json")
WATCHLIST_STATE_PATH    = os.path.join(LOGS_DIR, "watchlist_state.json")
_WORLD_SCAN_PATH        = os.path.join(LOGS_DIR, "world_scan.json")
_DEFAULT_WATCHLIST = {"enabled": False, "intervalHours": 12}


def get_watchlist_settings():
    try:
        with open(WATCHLIST_SETTINGS_PATH) as f:
            s = json.load(f)
        for k, v in _DEFAULT_WATCHLIST.items():
            s.setdefault(k, v)
        return s
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULT_WATCHLIST)


def save_watchlist_settings(data):
    s = {"enabled": bool(data.get("enabled", False)),
         "intervalHours": max(1, min(168, int(data.get("intervalHours", 12))))}
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(WATCHLIST_SETTINGS_PATH, "w") as f:
        json.dump(s, f, indent=2)
    return s


def _scan_one_island(session, island_id, x, y, own_cities, resource_type=0):
    """Scan a single island and return (island_entry, [player_entries]) or None.
    Mirrors the per-island parse used by the full deep scan."""
    try:
        html = session.get("view=island&islandId=" + str(island_id))
        island_data = getIsland(html)
    except Exception as e:
        logger.warning(lm("scan_island_error", id=island_id, err=e))
        return None

    nearest = min(own_cities, key=lambda c: _dist(x, y, c["x"], c["y"])) if own_cities else None
    nearest_dist = _dist(x, y, nearest["x"], nearest["y"]) if nearest else 0
    nearest_name = nearest["name"] if nearest else ""
    cities_list = island_data.get("cities", [])
    free_slots = sum(1 for c in cities_list if c.get("type") == "empty")
    island_entry = {
        "islandId":       str(island_id),
        "islandName":     island_data.get("name", ""),
        "x":              x, "y": y,
        "resourceType":   resource_type,
        "woodLevel":      island_data.get("resourceLevel", ""),
        "luxuryLevel":    island_data.get("tradegoodLevel", ""),
        "wonder":         island_data.get("wonderName", ""),
        "wonderLevel":    island_data.get("wonderLevel", ""),
        "freeSlots":      free_slots,
        "totalSlots":     len(cities_list),
        "hasOwnCity":     bool(island_data.get("isOwnCityOnIsland", False)),
        "nearestOwnCity": nearest_name,
        "distance":       round(nearest_dist, 1),
    }
    avatar_scores = island_data.get("avatarScores", {})
    players = []
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
        sc = avatar_scores.get(owner_id, {})
        players.append({
            "playerId":   owner_id, "cityId": str(city_slot.get("id", "")),
            "playerName": owner_name,
            "allyTag":    city_slot.get("ownerAllyTag", city_slot.get("AllyTag", "")),
            "state":      state, "cityName": city_slot.get("name", ""),
            "islandId":   str(island_id), "islandName": island_data.get("name", ""),
            "islandX":    x, "islandY": y,
            "nearestOwnCity": nearest_name, "distance": round(nearest_dist, 1),
            "scores": {
                "building": sc.get("building_score_main", "0"),
                "research": sc.get("research_score_main", "0"),
                "army":     sc.get("army_score_main", "0"),
                "trader":   sc.get("trader_score_secondary", "0"),
                "rank":     sc.get("place", ""),
            },
        })
    return island_entry, players


def process_watchlist(session, in_active_hours=True):
    """Every intervalHours, re-scan only the islands of players marked 'alvo' and refresh
    their entries in world_scan.json — so reactivations / defence changes are caught
    without the full weekly scan. Skips while a full scan is in progress."""
    if not in_active_hours:
        return
    from empire_utils import is_paused
    if is_paused():
        return
    settings = get_watchlist_settings()
    if not settings.get("enabled"):
        return
    if os.path.exists(SCAN_CHECKPOINT_PATH):
        return  # a full scan is running — don't interfere

    interval = max(1, int(settings.get("intervalHours", 12))) * 3600
    now = int(time.time())
    try:
        with open(WATCHLIST_STATE_PATH) as f:
            last_run = int(json.load(f).get("lastRun", 0))
    except (FileNotFoundError, json.JSONDecodeError):
        last_run = 0
    if now < last_run + interval:
        return

    def _save_state():
        try:
            with open(WATCHLIST_STATE_PATH, "w") as f:
                json.dump({"lastRun": now}, f)
        except Exception:
            pass

    try:
        with open(_WORLD_SCAN_PATH) as f:
            scan = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return

    try:
        from db_manager import get_all_marks
        marks = get_all_marks()
    except Exception:
        marks = {}
    alvo_coords = {(str(m.get("island_x")), str(m.get("island_y")))
                   for m in marks.values() if m.get("status") == "alvo" and m.get("island_x")}
    if not alvo_coords:
        _save_state()
        return

    islands = scan.get("islands", [])
    targets = [isl for isl in islands if (str(isl.get("x")), str(isl.get("y"))) in alvo_coords]
    if not targets:
        _save_state()
        return

    own_cities = scan.get("ownCities", [])
    players    = scan.get("players", [])
    updated = 0
    first = True
    for isl in targets:
        if not first:
            time.sleep(random.randint(15, 30))
        first = False
        res = _scan_one_island(session, isl["islandId"], isl["x"], isl["y"],
                               own_cities, isl.get("resourceType", 0))
        if not res:
            continue
        island_entry, isl_players = res
        iid = str(isl["islandId"])
        players  = [p for p in players if str(p.get("islandId")) != iid] + isl_players
        islands  = [i for i in islands if str(i.get("islandId")) != iid] + [island_entry]
        updated += 1

    scan["players"] = players
    scan["islands"] = islands
    scan["lastUpdated"] = now
    try:
        with open(_WORLD_SCAN_PATH, "w") as f:
            json.dump(scan, f, indent=2)
    except Exception:
        logger.warning("[watchlist] falha ao gravar world_scan.json", exc_info=True)
    _save_state()
    logger.info("[watchlist] %d ilha(s) de alvos re-escaneada(s)", updated)
