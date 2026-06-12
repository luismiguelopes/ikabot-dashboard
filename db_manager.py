#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import sqlite3
import time

DB_PATH = "/tmp/ikalogs/ikabot.db"
_LOGS_DIR = "/tmp/ikalogs/"
_DB_INIT_DONE = False
_SCHEMA_VERSION = 5


def _connect():
    os.makedirs(_LOGS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _run_migrations(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = row[0] if row[0] is not None else 0
    if current < 1:
        # v1 = baseline: all tables created by CREATE TABLE IF NOT EXISTS in init_db
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    if current < 2:
        # v2 = scan_last_updated key in empire_meta (no schema change, just a marker)
        conn.execute("INSERT INTO schema_version (version) VALUES (2)")
    if current < 3:
        # v3 = city_order column on queue_items for stable inter-city ordering
        conn.execute("ALTER TABLE queue_items ADD COLUMN city_order INTEGER DEFAULT 0")
        conn.execute("INSERT INTO schema_version (version) VALUES (3)")
    if current < 4:
        # v4 = shared_queue: attack/spy-dispatch/recall queues moved off racy JSON files
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shared_queue (
                queue TEXT NOT NULL,
                item_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at INTEGER,
                PRIMARY KEY (queue, item_id)
            )
        """)
        conn.execute("INSERT INTO schema_version (version) VALUES (4)")
    if current < 5:
        # v5 = attack_log: persistent record of every combat dispatch attempt
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attack_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                origin_city TEXT,
                target_city TEXT,
                target_player TEXT,
                island_x INTEGER,
                island_y INTEGER,
                mission_type TEXT,
                target_type TEXT,
                source TEXT,
                units TEXT,
                transporters INTEGER,
                success INTEGER,
                error TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attack_log_ts ON attack_log(ts)")
        conn.execute("INSERT INTO schema_version (version) VALUES (5)")
    conn.commit()


def init_db():
    global _DB_INIT_DONE
    if _DB_INIT_DONE:
        return
    conn = _connect()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS history (
                ts INTEGER PRIMARY KEY,
                gold REAL,
                gold_production REAL,
                ships_avail INTEGER,
                ships_total INTEGER,
                wine_consumption REAL,
                citizens INTEGER,
                housing_space INTEGER,
                resources_avail TEXT,
                resources_prod TEXT
            );
            CREATE TABLE IF NOT EXISTS history_cities (
                ts INTEGER,
                city TEXT,
                wood INTEGER,
                wine INTEGER,
                marble INTEGER,
                crystal INTEGER,
                sulfur INTEGER,
                wine_runs_out INTEGER,
                PRIMARY KEY (ts, city)
            );
            CREATE INDEX IF NOT EXISTS idx_history_ts ON history(ts);
            CREATE INDEX IF NOT EXISTS idx_history_cities_ts ON history_cities(ts, city);

            CREATE TABLE IF NOT EXISTS marks (
                mark_key TEXT PRIMARY KEY,
                player_id TEXT,
                island_x TEXT,
                island_y TEXT,
                status TEXT DEFAULT 'novo',
                note TEXT DEFAULT '',
                updated_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS mark_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mark_key TEXT,
                ts INTEGER,
                text TEXT,
                FOREIGN KEY (mark_key) REFERENCES marks(mark_key)
            );
            CREATE INDEX IF NOT EXISTS idx_mark_actions_key ON mark_actions(mark_key);

            CREATE TABLE IF NOT EXISTS building_costs (
                city TEXT,
                building TEXT,
                level INTEGER,
                wood INTEGER DEFAULT 0,
                wine INTEGER DEFAULT 0,
                marble INTEGER DEFAULT 0,
                glass INTEGER DEFAULT 0,
                sulfur INTEGER DEFAULT 0,
                PRIMARY KEY (city, building, level)
            );
            CREATE TABLE IF NOT EXISTS building_costs_meta (
                city TEXT,
                building TEXT,
                current_level INTEGER,
                last_updated INTEGER,
                PRIMARY KEY (city, building)
            );
            CREATE TABLE IF NOT EXISTS empire_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS queue_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT,
                building TEXT,
                target_level INTEGER,
                added_at INTEGER,
                position INTEGER,
                failed_attempts INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS queue_in_progress (
                city TEXT PRIMARY KEY,
                building TEXT,
                position INTEGER,
                from_level INTEGER,
                to_level INTEGER,
                started_at INTEGER,
                eta INTEGER
            );
            CREATE TABLE IF NOT EXISTS queue_transport_errors (
                city TEXT PRIMARY KEY,
                failed_at INTEGER,
                origin TEXT,
                resource TEXT
            );
            CREATE TABLE IF NOT EXISTS queue_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        conn.commit()
    finally:
        conn.close()
    conn2 = _connect()
    try:
        _run_migrations(conn2)
    finally:
        conn2.close()
    _DB_INIT_DONE = True
    _migrate_marks()
    _migrate_building_costs()
    _migrate_queue()
    _migrate_shared_queues()


# ── Shared queues (attack, spy dispatch, spy recall) ──────────────────────────
# Single SQLite table replaces the JSON files that both containers wrote without
# locking. Items are JSON payloads keyed by (queue, item_id); processors remove
# items one by one right after handling them, so there is no save-back race.

_SHARED_QUEUE_JSON = {
    "attack":       "attack_queue.json",
    "spy_dispatch": "spy_dispatch_queue.json",
    "spy_recall":   "spy_recall_queue.json",
}


def queue_add(queue, item):
    """Insert/replace one item in a shared queue. Ensures item['id']; returns it."""
    import uuid
    init_db()
    item = dict(item)
    if not item.get("id"):
        item["id"] = uuid.uuid4().hex[:8]
    created = item.get("queuedAt") or item.get("addedAt") or int(time.time())
    conn = _connect()
    try:
        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO shared_queue (queue, item_id, payload, created_at)
                VALUES (?, ?, ?, ?)
            """, (queue, item["id"], json.dumps(item), created))
    finally:
        conn.close()
    return item["id"]


def queue_items(queue):
    """Return all items of a shared queue, oldest first."""
    init_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT payload FROM shared_queue WHERE queue = ? ORDER BY created_at, rowid",
            (queue,)
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["payload"]))
        except Exception:
            pass
    return out


def queue_remove(queue, item_ids):
    """Remove items by id. Returns number of rows deleted."""
    init_db()
    item_ids = [i for i in item_ids if i]
    if not item_ids:
        return 0
    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM shared_queue WHERE queue = ? AND item_id IN ({})".format(
                    ",".join("?" * len(item_ids))),
                (queue, *item_ids),
            )
            return cur.rowcount
    finally:
        conn.close()


# ── Attack log ────────────────────────────────────────────────────────────────

def log_attack(entry):
    """Record one combat dispatch attempt.
    entry keys: ts, originCity, targetCity, targetPlayer, islandX, islandY,
    missionType, targetType, source ('manual'|'auto'), units (dict),
    transporters, success (bool), error (str|None)."""
    init_db()
    conn = _connect()
    try:
        with conn:
            conn.execute("""
                INSERT INTO attack_log
                (ts, origin_city, target_city, target_player, island_x, island_y,
                 mission_type, target_type, source, units, transporters, success, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.get("ts") or int(time.time()),
                entry.get("originCity", ""),
                entry.get("targetCity", ""),
                entry.get("targetPlayer", ""),
                entry.get("islandX"),
                entry.get("islandY"),
                entry.get("missionType", "army"),
                entry.get("targetType", "enemy"),
                entry.get("source", "manual"),
                json.dumps(entry.get("units") or {}),
                int(entry.get("transporters") or 0),
                1 if entry.get("success") else 0,
                entry.get("error"),
            ))
    finally:
        conn.close()


def get_attack_log(limit=100, target=None):
    """Return recent dispatch attempts, newest first. Optional filter by
    target city or player name (substring, case-insensitive)."""
    init_db()
    limit = max(1, min(int(limit), 1000))
    conn = _connect()
    try:
        if target:
            pat = f"%{target.lower()}%"
            rows = conn.execute("""
                SELECT * FROM attack_log
                WHERE lower(target_city) LIKE ? OR lower(target_player) LIKE ?
                ORDER BY ts DESC, id DESC LIMIT ?
            """, (pat, pat, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM attack_log ORDER BY ts DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["units"] = json.loads(d.get("units") or "{}")
        except Exception:
            d["units"] = {}
        d["success"] = bool(d["success"])
        out.append(d)
    return out


def _migrate_shared_queues():
    """One-time import of pending items from the legacy JSON queue files.
    The file is renamed to .migrated afterwards so stale copies of the old code
    cannot resurrect already-processed items."""
    for queue, fname in _SHARED_QUEUE_JSON.items():
        path = os.path.join(_LOGS_DIR, fname)
        if not os.path.exists(path):
            continue
        conn = _connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM shared_queue WHERE queue = ?", (queue,)
            ).fetchone()[0]
        finally:
            conn.close()
        if count == 0:
            try:
                with open(path) as f:
                    pending = json.load(f).get("pending", [])
            except Exception:
                pending = []
            for item in pending:
                try:
                    queue_add(queue, item)
                except Exception:
                    pass
        try:
            os.rename(path, path + ".migrated")
        except Exception:
            pass


# ── Empire snapshot ───────────────────────────────────────────────────────────

def save_empire_snapshot(written_at, empire_data, resources_data, status_summary):
    """Persist current empire state to SQLite so Flask can read without file mtime hacks."""
    init_db()
    conn = _connect()
    try:
        with conn:
            for key, value in (
                ("snapshot_written_at", str(written_at)),
                ("empire_json",         json.dumps(empire_data)),
                ("resources_json",      json.dumps(resources_data)),
                ("status_json",         json.dumps(status_summary)),
            ):
                conn.execute(
                    "INSERT OR REPLACE INTO empire_meta (key, value) VALUES (?, ?)",
                    (key, value),
                )
    finally:
        conn.close()


def get_empire_snapshot():
    """Return (written_at, empire_data, resources_data, status_summary) or None if not found."""
    init_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT key, value FROM empire_meta WHERE key IN "
            "('snapshot_written_at','empire_json','resources_json','status_json')"
        ).fetchall()
    finally:
        conn.close()

    kv = {r["key"]: r["value"] for r in rows}
    if len(kv) < 4:
        return None
    try:
        return (
            int(kv["snapshot_written_at"]),
            json.loads(kv["empire_json"]),
            json.loads(kv["resources_json"]),
            json.loads(kv["status_json"]),
        )
    except Exception:
        return None


# ── History ───────────────────────────────────────────────────────────────────

def insert_history(ts, status_summary, resources_data):
    init_db()
    gold = status_summary.get("gold", {})
    ships = status_summary.get("ships", {})
    housing = status_summary.get("housing", {})
    resources = status_summary.get("resources", {})
    conn = _connect()
    try:
        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO history
                (ts, gold, gold_production, ships_avail, ships_total,
                 wine_consumption, citizens, housing_space, resources_avail, resources_prod)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts,
                gold.get("total", 0), gold.get("production", 0),
                ships.get("available", 0), ships.get("total", 0),
                status_summary.get("wine_consumption", 0),
                housing.get("citizens", 0), housing.get("space", 0),
                json.dumps(resources.get("available", [])),
                json.dumps(resources.get("production", [])),
            ))
            for city, city_data in resources_data.items():
                conn.execute("""
                    INSERT OR REPLACE INTO history_cities
                    (ts, city, wood, wine, marble, crystal, sulfur, wine_runs_out)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ts, city,
                    city_data.get("Wood", 0),
                    city_data.get("Wine", 0),
                    city_data.get("Marble", 0),
                    city_data.get("Crystal", 0),
                    city_data.get("Sulfur", 0),
                    city_data.get("wineRunsOutIn", -1),
                ))
    finally:
        conn.close()


def get_history(days=7, city=None):
    init_db()
    cutoff = int(time.time()) - days * 86400
    conn = _connect()
    try:
        if city:
            rows = conn.execute("""
                SELECT ts, wood, wine, marble, crystal, sulfur, wine_runs_out
                FROM history_cities WHERE city = ? AND ts >= ? ORDER BY ts
            """, (city, cutoff)).fetchall()
            return [dict(r) for r in rows]
        rows = conn.execute("""
            SELECT ts, gold, gold_production, ships_avail, ships_total,
                   wine_consumption, citizens, housing_space, resources_avail, resources_prod
            FROM history WHERE ts >= ? ORDER BY ts
        """, (cutoff,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["resources_avail"] = json.loads(d.get("resources_avail") or "[]")
            d["resources_prod"] = json.loads(d.get("resources_prod") or "[]")
            result.append(d)
        return result
    finally:
        conn.close()


def get_history_cities():
    """Return sorted list of city names that have history data."""
    init_db()
    conn = _connect()
    try:
        rows = conn.execute("SELECT DISTINCT city FROM history_cities ORDER BY city").fetchall()
        return [r["city"] for r in rows]
    finally:
        conn.close()


# ── Player marks ──────────────────────────────────────────────────────────────

def _migrate_marks():
    marks_path = os.path.join(_LOGS_DIR, "player_marks.json")
    if not os.path.exists(marks_path):
        return
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM marks").fetchone()[0]
    finally:
        conn.close()
    if count > 0:
        return
    try:
        with open(marks_path) as f:
            marks = json.load(f)
        conn = _connect()
        try:
            with conn:
                for mk, entry in marks.items():
                    parts = mk.rsplit("_", 2)
                    pid = parts[0] if len(parts) >= 3 else mk
                    ix = parts[1] if len(parts) >= 3 else ""
                    iy = parts[2] if len(parts) >= 3 else ""
                    conn.execute("""
                        INSERT OR IGNORE INTO marks
                        (mark_key, player_id, island_x, island_y, status, note, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (mk, pid, ix, iy,
                          entry.get("status", "novo"),
                          entry.get("note", ""),
                          entry.get("updatedAt", int(time.time()))))
                    for action in entry.get("actions", []):
                        conn.execute("""
                            INSERT INTO mark_actions (mark_key, ts, text) VALUES (?, ?, ?)
                        """, (mk, action.get("ts", 0), action.get("text", "")))
        finally:
            conn.close()
    except Exception:
        pass


def get_all_marks():
    """Return dict {mark_key: {status, note, updatedAt, actions}}."""
    init_db()
    conn = _connect()
    try:
        marks_rows = conn.execute("SELECT * FROM marks").fetchall()
        actions_rows = conn.execute(
            "SELECT mark_key, ts, text FROM mark_actions ORDER BY ts"
        ).fetchall()
    finally:
        conn.close()
    actions_by_key = {}
    for row in actions_rows:
        actions_by_key.setdefault(row["mark_key"], []).append(
            {"ts": row["ts"], "text": row["text"]}
        )
    result = {}
    for row in marks_rows:
        mk = row["mark_key"]
        result[mk] = {
            "status": row["status"],
            "note": row["note"],
            "updatedAt": row["updated_at"],
            "actions": actions_by_key.get(mk, []),
        }
    return result


def save_mark(mark_key, player_id, island_x, island_y, status, note):
    init_db()
    conn = _connect()
    try:
        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO marks
                (mark_key, player_id, island_x, island_y, status, note, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (mark_key, player_id, island_x, island_y, status, note, int(time.time())))
    finally:
        conn.close()


def append_action(mark_key, player_id, island_x, island_y, text):
    init_db()
    ts = int(time.time())
    conn = _connect()
    try:
        with conn:
            conn.execute("""
                INSERT OR IGNORE INTO marks
                (mark_key, player_id, island_x, island_y, status, note, updated_at)
                VALUES (?, ?, ?, ?, 'novo', '', ?)
            """, (mark_key, player_id, island_x, island_y, ts))
            conn.execute(
                "UPDATE marks SET updated_at = ? WHERE mark_key = ?", (ts, mark_key)
            )
            conn.execute(
                "INSERT INTO mark_actions (mark_key, ts, text) VALUES (?, ?, ?)",
                (mark_key, ts, text),
            )
    finally:
        conn.close()


def get_mark_with_actions(mark_key):
    """Return {status, note, updatedAt, actions} or None."""
    init_db()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM marks WHERE mark_key = ?", (mark_key,)).fetchone()
        if not row:
            return None
        actions = conn.execute(
            "SELECT ts, text FROM mark_actions WHERE mark_key = ? ORDER BY ts",
            (mark_key,),
        ).fetchall()
        return {
            "status": row["status"],
            "note": row["note"],
            "updatedAt": row["updated_at"],
            "actions": [{"ts": a["ts"], "text": a["text"]} for a in actions],
        }
    finally:
        conn.close()


# ── Building costs ────────────────────────────────────────────────────────────

def _migrate_building_costs():
    costs_path = os.path.join(_LOGS_DIR, "building_costs.json")
    if not os.path.exists(costs_path):
        return
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM building_costs").fetchone()[0]
    finally:
        conn.close()
    if count > 0:
        return
    try:
        with open(costs_path) as f:
            data = json.load(f)
        _write_building_costs_to_db(data)
    except Exception:
        pass


def _write_building_costs_to_db(data):
    last_updated = data.get("lastUpdated", int(time.time()))
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM building_costs")
            conn.execute("DELETE FROM building_costs_meta")
            conn.execute("""
                INSERT OR REPLACE INTO empire_meta (key, value) VALUES ('costs_last_updated', ?)
            """, (str(last_updated),))
            for city, buildings in data.get("cities", {}).items():
                for building, bdata in buildings.items():
                    cur_lv = bdata.get("currentLevel", 0)
                    conn.execute("""
                        INSERT OR REPLACE INTO building_costs_meta
                        (city, building, current_level, last_updated)
                        VALUES (?, ?, ?, ?)
                    """, (city, building, cur_lv, last_updated))
                    for level_str, costs in bdata.get("costs", {}).items():
                        conn.execute("""
                            INSERT OR REPLACE INTO building_costs
                            (city, building, level, wood, wine, marble, glass, sulfur)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            city, building, int(level_str),
                            costs.get("wood", 0), costs.get("wine", 0),
                            costs.get("marble", 0), costs.get("glass", 0),
                            costs.get("sulfur", 0),
                        ))
    finally:
        conn.close()


def save_building_costs(data):
    """Save full building_costs dict to SQLite."""
    init_db()
    _write_building_costs_to_db(data)


def get_building_costs():
    """Return full building_costs dict (same shape as building_costs.json)."""
    init_db()
    conn = _connect()
    try:
        meta_row = conn.execute(
            "SELECT value FROM empire_meta WHERE key = 'costs_last_updated'"
        ).fetchone()
        last_updated = int(meta_row["value"]) if meta_row else 0
        meta_rows = conn.execute(
            "SELECT city, building, current_level FROM building_costs_meta"
        ).fetchall()
        cost_rows = conn.execute(
            "SELECT city, building, level, wood, wine, marble, glass, sulfur FROM building_costs"
        ).fetchall()
    finally:
        conn.close()
    cities = {}
    for row in meta_rows:
        cities.setdefault(row["city"], {})[row["building"]] = {
            "currentLevel": row["current_level"],
            "costs": {},
        }
    for row in cost_rows:
        city, building = row["city"], row["building"]
        if city in cities and building in cities[city]:
            cities[city][building]["costs"][str(row["level"])] = {
                "wood": row["wood"], "wine": row["wine"],
                "marble": row["marble"], "glass": row["glass"], "sulfur": row["sulfur"],
            }
    return {"lastUpdated": last_updated, "cities": cities}


def get_city_building_cost(city, building, level):
    """Return cost dict {wood,wine,marble,glass,sulfur} for one level or None."""
    init_db()
    conn = _connect()
    try:
        row = conn.execute("""
            SELECT wood, wine, marble, glass, sulfur FROM building_costs
            WHERE city = ? AND building = ? AND level = ?
        """, (city, building, level)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "wood": row["wood"], "wine": row["wine"], "marble": row["marble"],
        "glass": row["glass"], "sulfur": row["sulfur"],
    }


def costs_last_updated():
    """Return building costs last_updated timestamp or 0."""
    init_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT value FROM empire_meta WHERE key = 'costs_last_updated'"
        ).fetchone()
    finally:
        conn.close()
    return int(row["value"]) if row else 0


def scan_last_updated():
    """Return world scan last_updated timestamp or 0."""
    init_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT value FROM empire_meta WHERE key = 'scan_last_updated'"
        ).fetchone()
    finally:
        conn.close()
    return int(row["value"]) if row else 0


def save_scan_timestamp(ts):
    """Persist world scan completion timestamp to empire_meta."""
    init_db()
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO empire_meta (key, value) VALUES ('scan_last_updated', ?)",
                (str(ts),),
            )
    finally:
        conn.close()


# ── Building queue ────────────────────────────────────────────────────────────

def _migrate_queue():
    queue_path = os.path.join(_LOGS_DIR, "building_queue.json")
    if not os.path.exists(queue_path):
        return
    conn = _connect()
    try:
        item_count = conn.execute("SELECT COUNT(*) FROM queue_items").fetchone()[0]
        state_count = conn.execute("SELECT COUNT(*) FROM queue_state").fetchone()[0]
    finally:
        conn.close()
    if item_count > 0 or state_count > 0:
        return
    try:
        with open(queue_path) as f:
            data = json.load(f)
        _write_queue_to_db(data)
    except Exception:
        pass


def _write_queue_to_db(data):
    enabled = data.get("enabled", True)
    queues = data.get("queues", {})
    in_progress = data.get("inProgress", {})
    transport_errors = data.get("transportErrors", {})
    conn = _connect()
    try:
        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO queue_state (key, value) VALUES ('enabled', ?)
            """, ("true" if enabled else "false",))
            conn.execute("DELETE FROM queue_items")
            for city_idx, (city, items) in enumerate(queues.items()):
                for pos, item in enumerate(items):
                    conn.execute("""
                        INSERT INTO queue_items
                        (city, building, target_level, added_at, position, city_order, failed_attempts)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        city, item["building"], item.get("targetLevel", 0),
                        item.get("addedAt", 0), pos, city_idx,
                        item.get("failedAttempts", 0),
                    ))
            conn.execute("DELETE FROM queue_in_progress")
            for city, ip in in_progress.items():
                conn.execute("""
                    INSERT INTO queue_in_progress
                    (city, building, position, from_level, to_level, started_at, eta)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    city, ip.get("building", ""), ip.get("position", 0),
                    ip.get("fromLevel", 0), ip.get("toLevel", 0),
                    ip.get("startedAt", 0), ip.get("eta", 0),
                ))
            conn.execute("DELETE FROM queue_transport_errors")
            for city, err in transport_errors.items():
                conn.execute("""
                    INSERT INTO queue_transport_errors (city, failed_at, origin, resource)
                    VALUES (?, ?, ?, ?)
                """, (city, err.get("failedAt", 0), err.get("origin", ""),
                      err.get("resource", "")))
    finally:
        conn.close()


def _read_queue_from_db():
    conn = _connect()
    try:
        state_rows = conn.execute("SELECT key, value FROM queue_state").fetchall()
        item_rows = conn.execute("""
            SELECT city, building, target_level, added_at, position, failed_attempts
            FROM queue_items ORDER BY city_order, position
        """).fetchall()
        ip_rows = conn.execute("SELECT * FROM queue_in_progress").fetchall()
        err_rows = conn.execute("SELECT * FROM queue_transport_errors").fetchall()
    finally:
        conn.close()
    state = {r["key"]: r["value"] for r in state_rows}
    enabled = state.get("enabled", "true").lower() == "true"
    queues = {}
    for row in item_rows:
        city = row["city"]
        entry = {"building": row["building"], "targetLevel": row["target_level"],
                 "addedAt": row["added_at"]}
        if row["failed_attempts"]:
            entry["failedAttempts"] = row["failed_attempts"]
        queues.setdefault(city, []).append(entry)
    in_progress = {}
    for row in ip_rows:
        in_progress[row["city"]] = {
            "building": row["building"], "position": row["position"],
            "fromLevel": row["from_level"], "toLevel": row["to_level"],
            "startedAt": row["started_at"], "eta": row["eta"],
        }
    transport_errors = {}
    for row in err_rows:
        transport_errors[row["city"]] = {
            "failedAt": row["failed_at"], "origin": row["origin"],
            "resource": row["resource"],
        }
    return {
        "enabled": enabled,
        "queues": queues,
        "inProgress": in_progress,
        "transportErrors": transport_errors,
    }


def load_queue():
    """Return queue dict with same structure as building_queue.json."""
    init_db()
    return _read_queue_from_db()


def save_queue(data):
    """Save queue dict to SQLite and touch a sentinel for SSE change detection."""
    init_db()
    _write_queue_to_db(data)
    try:
        with open(os.path.join(_LOGS_DIR, ".queue_updated"), "w") as f:
            f.write(str(int(time.time())))
    except Exception:
        pass
