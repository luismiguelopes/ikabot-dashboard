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

from empire_utils import LOGS_DIR, WORLD_SCAN_RADIUS, WORLD_SCAN_UPDATE_INTERVAL, lm

from ikabot.helpers.getJson import getIsland


def should_update_world_scan():
    flag = os.path.join(LOGS_DIR, ".force_world_scan")
    if os.path.exists(flag):
        os.remove(flag)
        return True
    scan_path = os.path.join(LOGS_DIR, "world_scan.json")
    if not os.path.exists(scan_path):
        return True
    return time.time() - os.path.getmtime(scan_path) > WORLD_SCAN_UPDATE_INTERVAL


def _write_scan_status(status, phase, progress, total, message):
    path = os.path.join(LOGS_DIR, "world_scan_status.json")
    with open(path, "w") as f:
        json.dump({
            "status": status,
            "phase": phase,
            "progress": progress,
            "total": total,
            "message": message,
            "updatedAt": int(time.time()),
        }, f)


def _dist(x1, y1, x2, y2):
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


def collect_world_scan(session):
    """Scan nearby islands for inactive/vacation players. Runs every 7 days."""
    try:
        own_cities_path = os.path.join(LOGS_DIR, "own_cities.json")
        if not os.path.exists(own_cities_path):
            print(lm("own_cities_missing"))
            return
        with open(own_cities_path) as f:
            own_cities = json.load(f)
        if not own_cities:
            return

        print(lm("world_scan_start", ts=time.strftime('%H:%M:%S'), radius=WORLD_SCAN_RADIUS))
        _write_scan_status("running", "shallow_scan", 0, 4, lm("scan_status_shallow"))

        shallow_islands = []
        quadrants = [
            ("0", "50", "0", "50"),
            ("50", "100", "0", "50"),
            ("0", "50", "50", "100"),
            ("50", "100", "50", "100"),
        ]
        for i, (x_min, x_max, y_min, y_max) in enumerate(quadrants):
            _write_scan_status("running", "shallow_scan", i + 1, 4,
                lm("scan_status_quadrant", x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max))
            time.sleep(random.randint(2, 5))
            data = session.post(
                f"action=WorldMap&function=getJSONArea&x_min={x_min}&x_max={x_max}&y_min={y_min}&y_max={y_max}"
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

        print(lm("scan_islands_count", n=len(islands_to_scan), radius=WORLD_SCAN_RADIUS))
        _write_scan_status("running", "deep_scan", 0, len(islands_to_scan),
            lm("scan_status_deep", n=len(islands_to_scan)))

        inactive_players = []
        islands_summary = []
        for i, island in enumerate(islands_to_scan):
            pause = random.randint(15, 30)
            print(lm("scan_island_pause", pause=pause, i=i+1, total=len(islands_to_scan), x=island['x'], y=island['y']))
            time.sleep(pause)

            try:
                html = session.get("view=island&islandId=" + str(island["id"]))
                island_data = getIsland(html)

                nearest = min(own_cities,
                    key=lambda c: _dist(island["x"], island["y"], c["x"], c["y"]))
                nearest_dist = _dist(island["x"], island["y"], nearest["x"], nearest["y"])

                cities_list = island_data.get("cities", [])
                free_slots = sum(1 for c in cities_list if c.get("type") == "empty")
                islands_summary.append({
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
                    inactive_players.append({
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

                _write_scan_status("running", "deep_scan", i + 1, len(islands_to_scan),
                    lm("scan_island_done", i=i+1, total=len(islands_to_scan), x=island['x'], y=island['y']))

            except Exception as e:
                print(lm("scan_island_error", id=island['id'], err=e))
                continue

        scan_path = os.path.join(LOGS_DIR, "world_scan.json")
        if os.path.exists(scan_path):
            with open(scan_path, "rb") as src:
                with open(os.path.join(LOGS_DIR, "world_scan_prev.json"), "wb") as dst:
                    dst.write(src.read())

        result = {
            "lastUpdated": int(time.time()),
            "scanRadius":  WORLD_SCAN_RADIUS,
            "ownCities":   own_cities,
            "players":     inactive_players,
            "islands":     islands_summary,
        }
        with open(scan_path, "w") as f:
            json.dump(result, f, indent=2)

        _write_scan_status("idle", "done", len(islands_to_scan), len(islands_to_scan),
            lm("scan_status_done", n=len(inactive_players)))
        print(lm("scan_done", n=len(inactive_players)))

    except Exception:
        import traceback
        print(lm("scan_error"), traceback.format_exc())
        _write_scan_status("error", "error", 0, 0, lm("scan_status_error"))
