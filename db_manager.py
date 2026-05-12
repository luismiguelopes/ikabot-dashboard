#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import sqlite3

DB_PATH           = "/tmp/ikalogs/ikabot.db"
HISTORY_JSONL_PATH = "/tmp/ikalogs/history.jsonl"

_DB_INIT_DONE = False


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    global _DB_INIT_DONE
    if _DB_INIT_DONE:
        return
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS history (
                ts              INTEGER PRIMARY KEY,
                gold            INTEGER,
                gold_production INTEGER,
                ships_avail     INTEGER,
                ships_total     INTEGER,
                wine_consumption INTEGER,
                citizens        INTEGER,
                housing_space   INTEGER,
                resources_avail TEXT,
                resources_prod  TEXT
            );
            CREATE TABLE IF NOT EXISTS history_cities (
                ts            INTEGER,
                city          TEXT,
                wood          REAL,
                wine          REAL,
                marble        REAL,
                crystal       REAL,
                sulfur        REAL,
                wine_runs_out INTEGER,
                PRIMARY KEY (ts, city)
            );
            CREATE INDEX IF NOT EXISTS idx_history_ts      ON history(ts);
            CREATE INDEX IF NOT EXISTS idx_hc_city_ts      ON history_cities(city, ts);
        """)
    _migrate_jsonl()
    _DB_INIT_DONE = True


def _migrate_jsonl():
    if not os.path.exists(HISTORY_JSONL_PATH):
        return
    with _connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] > 0:
            return
    with open(HISTORY_JSONL_PATH) as f:
        lines = f.readlines()
    with _connect() as conn:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                h = json.loads(line)
                ts = h.get("timestamp", 0)
                conn.execute(
                    "INSERT OR IGNORE INTO history VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        ts,
                        h.get("gold", {}).get("total", 0),
                        h.get("gold", {}).get("production", 0),
                        h.get("ships", {}).get("available", 0),
                        h.get("ships", {}).get("total", 0),
                        h.get("wine_consumption", 0),
                        h.get("housing", {}).get("citizens", 0),
                        h.get("housing", {}).get("space", 0),
                        json.dumps(h.get("resources", {}).get("available", [])),
                        json.dumps(h.get("resources", {}).get("production", [])),
                    )
                )
            except Exception:
                pass
    print("[db] Migrated history.jsonl → SQLite")


def insert_history(ts, status_summary, resources_data):
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO history VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                ts,
                status_summary["gold"]["total"],
                status_summary["gold"]["production"],
                status_summary["ships"]["available"],
                status_summary["ships"]["total"],
                status_summary["wine_consumption"],
                status_summary["housing"]["citizens"],
                status_summary["housing"]["space"],
                json.dumps(status_summary["resources"]["available"]),
                json.dumps(status_summary["resources"]["production"]),
            )
        )
        for city_name, city_res in resources_data.items():
            conn.execute(
                "INSERT OR REPLACE INTO history_cities VALUES (?,?,?,?,?,?,?,?)",
                (
                    ts,
                    city_name,
                    city_res.get("Wood", 0),
                    city_res.get("Wine", 0),
                    city_res.get("Marble", 0),
                    city_res.get("Crystal", 0),
                    city_res.get("Sulfur", 0),
                    city_res.get("wineRunsOutIn", -1),
                )
            )
