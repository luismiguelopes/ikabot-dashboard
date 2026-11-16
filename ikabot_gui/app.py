from flask import (Flask, render_template, jsonify, request, Response,
                   send_from_directory, stream_with_context, session)
from datetime import timedelta
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import settings_registry   # shared with the bot (mounted next to this file) — P13.30
try:
    import db_manager as _db
except Exception:
    _db = None

app = Flask(__name__)

LOGS_DIR = "/tmp/ikalogs/"
EMPIRE_JSON_PATH        = os.path.join(LOGS_DIR, "empire.json")
STATUS_SUMMARY_JSON_PATH = os.path.join(LOGS_DIR, "statusSummary.json")
RESOURCES_JSON_PATH     = os.path.join(LOGS_DIR, "resources.json")
MOVEMENTS_JSON_PATH     = os.path.join(LOGS_DIR, "movements.json")
BUILDING_COSTS_JSON_PATH = os.path.join(LOGS_DIR, "building_costs.json")
FORCE_COSTS_FLAG_PATH   = os.path.join(LOGS_DIR, ".force_costs_update")
WORLD_SCAN_JSON_PATH    = os.path.join(LOGS_DIR, "world_scan.json")
WORLD_SCAN_PREV_PATH    = os.path.join(LOGS_DIR, "world_scan_prev.json")
WORLD_SCAN_STATUS_PATH  = os.path.join(LOGS_DIR, "world_scan_status.json")
FORCE_WORLD_SCAN_FLAG       = os.path.join(LOGS_DIR, ".force_world_scan")
FORCE_MOVEMENTS_FLAG_PATH   = os.path.join(LOGS_DIR, ".force_movements_update")
FORCE_EMPIRE_FLAG_PATH      = os.path.join(LOGS_DIR, ".force_empire_update")
FORCE_QUEUE_FLAG_PATH       = os.path.join(LOGS_DIR, ".force_queue_check")
QUEUE_SENTINEL_PATH         = os.path.join(LOGS_DIR, ".queue_updated")
TELEGRAM_SETTINGS_PATH      = os.path.join(LOGS_DIR, "telegram_settings.json")
DB_PATH                     = os.path.join(LOGS_DIR, "ikabot.db")
QUEUE_SETTINGS_JSON_PATH    = os.path.join(LOGS_DIR, "queue_settings.json")
NEXT_CYCLE_JSON_PATH    = os.path.join(LOGS_DIR, "next_cycle.json")
LAST_ALIVE_JSON_PATH    = os.path.join(LOGS_DIR, "last_alive.json")

# P6.6: single source for "bot offline" — the docker healthcheck, the Telegram watchdog and
# the sidebar badge all use this value (env-overridable via docker-compose).
BOT_OFFLINE_SECS = int(os.environ.get("BOT_OFFLINE_SECS", "1800"))

# Nightly quiet window for the Telegram "bot offline" alert (local hours, [start, end)).
# When the host (e.g. a laptop) sleeps overnight the whole stack freezes and resumes in the
# morning with a stale heartbeat — a predictable, benign gap we don't want to be paged for.
# An outage that BEGAN inside this window is suppressed (keyed on the last heartbeat's hour,
# i.e. when the bot actually went quiet). A daytime outage still alerts. start==end disables.
# Wrap-around (e.g. 23→7) is supported. Env-overridable.
OFFLINE_QUIET_START = int(os.environ.get("OFFLINE_QUIET_START", "0"))
OFFLINE_QUIET_END   = int(os.environ.get("OFFLINE_QUIET_END", "7"))


def _in_quiet_window(ts):
    """True if the local hour of `ts` falls in [OFFLINE_QUIET_START, OFFLINE_QUIET_END)."""
    if OFFLINE_QUIET_START == OFFLINE_QUIET_END:
        return False                      # disabled
    h = time.localtime(ts).tm_hour
    if OFFLINE_QUIET_START < OFFLINE_QUIET_END:
        return OFFLINE_QUIET_START <= h < OFFLINE_QUIET_END
    return h >= OFFLINE_QUIET_START or h < OFFLINE_QUIET_END   # wrap-around (e.g. 23→7)
EMPIRE_SCAN_STATUS_PATH = os.path.join(LOGS_DIR, "empire_scan_status.json")
SPY_MISSIONS_PATH          = os.path.join(LOGS_DIR, "spy_missions.json")
SPY_COUNTS_PATH            = os.path.join(LOGS_DIR, "spy_counts.json")
ESPIONAGE_SETTINGS_PATH    = os.path.join(LOGS_DIR, "espionage_settings.json")
MILITARY_JSON_PATH         = os.path.join(LOGS_DIR, "military.json")
WORLD_SCAN_SETTINGS_PATH     = os.path.join(LOGS_DIR, "world_scan_settings.json")
FORCE_IMPORT_REPORTS_FLAG    = os.path.join(LOGS_DIR, ".force_import_reports")

_DEFAULT_ESPIONAGE_SETTINGS = {
    "garrisonThresholdTotal": 50000,
    "minLootTotal": 50000,
    "processingEnabled": True,
    "ignoreExpiryDays": 60,        # a temporary ignore lifts after this long for re-evaluation
    "ignorePermanentAfter": 4,     # strikes before an ignore becomes permanent
}


def _atomic_write_json(path, data, **dump_kwargs):
    """Write JSON via a temp file + os.replace so the bot never reads a half-written
    settings file (same helper as the bot's empire_utils.atomic_write_json)."""
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump(data, f, **dump_kwargs)
    os.replace(tmp, path)


def _spy_missions():
    """Spy missions as a list (SQLite since P13.11; never the legacy JSON file)."""
    if not _db:
        return []
    try:
        return _db.missions_load().get("missions", [])
    except Exception:
        return []


def get_last_modified_date(filepath):
    if os.path.exists(filepath):
        t = os.path.getmtime(filepath)
        return time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(t))
    return "Desconhecida"


def get_last_modified_ts(filepath):
    if os.path.exists(filepath):
        return int(os.path.getmtime(filepath))
    return 0


def load_all_data():
    # Try SQLite snapshot first (written_at is exact, no mtime fragility)
    snapshot = None
    if _db:
        try:
            snapshot = _db.get_empire_snapshot()
        except Exception:
            pass

    if snapshot:
        written_at, empire_data, resources_data, status_summary = snapshot
    else:
        # JSON fallback
        for path, name in [
            (EMPIRE_JSON_PATH,         "empire.json"),
            (STATUS_SUMMARY_JSON_PATH, "statusSummary.json"),
            (RESOURCES_JSON_PATH,      "resources.json"),
        ]:
            if not os.path.exists(path):
                return None, f"Ficheiro {name} não encontrado!"
        with open(EMPIRE_JSON_PATH) as f:
            empire_data = json.load(f)
        with open(STATUS_SUMMARY_JSON_PATH) as f:
            status_summary = json.load(f)
        with open(RESOURCES_JSON_PATH) as f:
            resources_data = json.load(f)
        written_at = get_last_modified_ts(RESOURCES_JSON_PATH)

    # Patch empire_data with inProgress so queue constructions are visible immediately
    now_ts = time.time()
    # From the live queue (database). This used to read building_queue.json — a file last
    # written in May — so the patch had been doing nothing for months.
    try:
        queue_data = _load_building_queue()
        for city_name, ip in queue_data.get("inProgress", {}).items():
            eta = ip.get("eta", 0)
            building = ip.get("building", "")
            from_level = ip.get("fromLevel", 0)
            if not building or eta <= now_ts or city_name not in empire_data:
                continue
            city_entry = empire_data[city_name]
            current = str(city_entry.get(building, ""))
            if not current.endswith("+"):
                city_entry[building] = "{}+".format(from_level)
            if not city_entry.get("_constructionEnds"):
                city_entry["_constructionEnds"] = eta
    except Exception:
        pass

    # Adjust wineRunsOutIn using exact written_at (not fragile mtime)
    elapsed = int(now_ts - written_at)
    for city_data in resources_data.values():
        t = city_data.get('wineRunsOutIn')
        if t is not None and t != -1:
            city_data['wineRunsOutIn'] = max(0, t - elapsed)

    next_cycle_at = None
    if os.path.exists(NEXT_CYCLE_JSON_PATH):
        try:
            with open(NEXT_CYCLE_JSON_PATH) as f:
                next_cycle_at = json.load(f).get("nextCycleAt")
        except Exception:
            pass

    last_alive = None
    if os.path.exists(LAST_ALIVE_JSON_PATH):
        try:
            with open(LAST_ALIVE_JSON_PATH) as f:
                last_alive = json.load(f).get("lastAlive")
        except Exception:
            pass

    last_updated_ts = written_at if snapshot else get_last_modified_ts(EMPIRE_JSON_PATH)
    return {
        "empireData":    empire_data,
        "statusSummary": status_summary,
        "resourcesData": resources_data,
        "lastUpdated":   time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(last_updated_ts)),
        "lastUpdatedTs": last_updated_ts,
        "nextCycleAt":   next_cycle_at,
        "lastAlive":     last_alive,
        "offlineAfterSecs": BOT_OFFLINE_SECS,
    }, None


# P6.11: Flask serves the production React build (./frontend/dist mounted at /gui/dist),
# replacing the permanent Vite dev-server container. Explicit /api routes always win over
# ── Dashboard authentication (B1) ─────────────────────────────────────────────
# Opt-in: set DASHBOARD_PASSWORD in .env to require a login for every action route.
# With no password set, the dashboard stays open (and logs a warning), so nobody is
# accidentally locked out. Only /api/* is gated — the SPA shell carries no data.
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
AUTH_ENABLED = bool(DASHBOARD_PASSWORD)
_SECRET_PATH = os.path.join(LOGS_DIR, ".dashboard_secret")


def _load_dashboard_secret():
    """Stable signing key so logins survive restarts: env first, else a persisted random."""
    env = os.getenv("DASHBOARD_SECRET", "").strip()
    if env:
        return env
    try:
        with open(_SECRET_PATH) as f:
            s = f.read().strip()
        if s:
            return s
    except (FileNotFoundError, OSError):
        pass
    s = secrets.token_hex(32)
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(_SECRET_PATH, "w") as f:
            f.write(s)
        os.chmod(_SECRET_PATH, 0o600)
    except OSError:
        pass
    return s


app.secret_key = _load_dashboard_secret()
app.permanent_session_lifetime = timedelta(days=30)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
if not AUTH_ENABLED:
    print("[gui] AVISO: dashboard SEM autenticação — define DASHBOARD_PASSWORD no .env "
          "para exigir login nas acções.", flush=True)

_AUTH_OPEN_PATHS = {"/api/login", "/api/logout", "/api/auth-status"}


@app.before_request
def _auth_gate():
    if not AUTH_ENABLED:
        return
    p = request.path
    if not p.startswith("/api/") or p in _AUTH_OPEN_PATHS:
        return
    if not session.get("auth"):
        return jsonify({"error": "auth_required"}), 401


@app.route("/api/auth-status")
def api_auth_status():
    return jsonify({"enabled": AUTH_ENABLED,
                    "authed": (not AUTH_ENABLED) or bool(session.get("auth"))})


@app.route("/api/login", methods=["POST"])
def api_login():
    if not AUTH_ENABLED:
        return jsonify({"ok": True, "enabled": False})
    data = request.get_json(silent=True) or {}
    if hmac.compare_digest(str(data.get("password", "")), DASHBOARD_PASSWORD):
        session["auth"] = True
        session.permanent = True
        return jsonify({"ok": True})
    time.sleep(0.6)  # slow down brute force
    return jsonify({"ok": False, "error": "wrong_password"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


# the catch-all; unknown paths fall back to index.html (SPA routing).
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")


@app.route("/")
@app.route("/<path:path>")
def serve_frontend(path="index.html"):
    if path.startswith("api/"):
        return jsonify({"error": "not found"}), 404
    if not os.path.isdir(FRONTEND_DIST):
        return render_template("index.html")   # legacy fallback (dist not mounted)
    full = os.path.normpath(os.path.join(FRONTEND_DIST, path))
    if full.startswith(FRONTEND_DIST) and os.path.isfile(full):
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, "index.html")


@app.route("/api/data")
def api_data():
    data, error = load_all_data()
    if error:
        return jsonify({"error": error}), 404
    return jsonify(data)


# Cache windows mirror the collectors: costs_collector (3d), empire_collector military (8h).
_MILITARY_CACHE_SECS = 8 * 3600
_COSTS_CACHE_SECS    = 3 * 24 * 3600


@app.route("/api/cycles")
def api_cycles():
    """Single snapshot for the Home 'Cycles & refreshes' grid: last-updated timestamps,
    the empire next-cycle countdown, cache windows, and world-scan progress."""
    now = int(time.time())

    next_cycle_at = None
    if os.path.exists(NEXT_CYCLE_JSON_PATH):
        try:
            with open(NEXT_CYCLE_JSON_PATH) as f:
                next_cycle_at = json.load(f).get("nextCycleAt")
        except Exception:
            pass

    scan = {"status": "idle", "phase": "", "progress": 0, "total": 0}
    if os.path.exists(WORLD_SCAN_STATUS_PATH):
        try:
            with open(WORLD_SCAN_STATUS_PATH) as f:
                scan = json.load(f)
        except Exception:
            pass

    last_alive = None
    if os.path.exists(LAST_ALIVE_JSON_PATH):
        try:
            with open(LAST_ALIVE_JSON_PATH) as f:
                last_alive = json.load(f).get("lastAlive")
        except Exception:
            pass

    empire_ts = get_last_modified_ts(EMPIRE_JSON_PATH)
    mil_ts    = get_last_modified_ts(MILITARY_JSON_PATH)
    # Costs are stored in SQLite (save_building_costs), not the legacy JSON —
    # read the DB timestamp, falling back to the stale JSON mtime only if no DB.
    costs_ts  = 0
    if _db:
        try:
            costs_ts = int(_db.costs_last_updated() or 0)
        except Exception:
            costs_ts = 0
    if not costs_ts:
        costs_ts = get_last_modified_ts(BUILDING_COSTS_JSON_PATH)

    cycles = [
        {"key": "empire",     "lastUpdated": empire_ts,
         "nextAt": next_cycle_at, "endpoint": "/api/data/refresh"},
        {"key": "world",      "lastUpdated": get_last_modified_ts(WORLD_SCAN_JSON_PATH),
         "scan": scan, "endpoint": "/api/world-scan/refresh"},
        {"key": "movements",  "lastUpdated": get_last_modified_ts(MOVEMENTS_JSON_PATH),
         "endpoint": "/api/movements/refresh"},
        {"key": "military",   "lastUpdated": mil_ts,
         "nextAt": (mil_ts + _MILITARY_CACHE_SECS) if mil_ts else None,
         "cacheSecs": _MILITARY_CACHE_SECS, "endpoint": "/api/military/refresh"},
        {"key": "costs",      "lastUpdated": costs_ts,
         "nextAt": (costs_ts + _COSTS_CACHE_SECS) if costs_ts else None,
         "cacheSecs": _COSTS_CACHE_SECS, "endpoint": "/api/building-costs/refresh"},
        {"key": "queue",      "lastUpdated": None,
         "everyCycle": True, "endpoint": "/api/building-queue/check"},
    ]
    return jsonify({"now": now, "lastAlive": last_alive, "cycles": cycles})


@app.route("/api/movements")
def api_movements():
    if not os.path.exists(MOVEMENTS_JSON_PATH):
        return jsonify([])
    with open(MOVEMENTS_JSON_PATH) as f:
        return jsonify(json.load(f))


def _db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/api/history")
def api_history():
    """Return the last 168 history entries. ?city=Name returns per-city resource history."""
    limit = min(int(request.args.get("limit", 168)), 2160)
    city  = request.args.get("city", "").strip()

    if city:
        if not os.path.exists(DB_PATH):
            return jsonify([])
        try:
            with _db_connect() as conn:
                rows = conn.execute(
                    "SELECT ts, wood, wine, marble, crystal, sulfur, wine_runs_out "
                    "FROM history_cities WHERE city=? ORDER BY ts DESC LIMIT ?",
                    (city, limit)
                ).fetchall()
            return jsonify([{
                "timestamp": r["ts"],
                "resources": {"available": [r["wood"], r["wine"], r["marble"], r["crystal"], r["sulfur"]]},
                "wineRunsOutIn": r["wine_runs_out"],
            } for r in reversed(rows)])
        except Exception:
            return jsonify([])

    # Empire-wide (database only)
    if os.path.exists(DB_PATH):
        try:
            with _db_connect() as conn:
                rows = conn.execute(
                    "SELECT ts, gold, gold_production, ships_avail, ships_total, "
                    "wine_consumption, citizens, housing_space, resources_avail, resources_prod "
                    "FROM history ORDER BY ts DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return jsonify([{
                "timestamp": r["ts"],
                "gold":     {"total": r["gold"], "production": r["gold_production"]},
                "ships":    {"available": r["ships_avail"], "total": r["ships_total"]},
                "housing":  {"citizens": r["citizens"], "space": r["housing_space"]},
                "wine_consumption": r["wine_consumption"],
                "resources": {
                    "available": json.loads(r["resources_avail"] or "[]"),
                    "production": json.loads(r["resources_prod"] or "[]"),
                },
            } for r in reversed(rows)])
        except Exception:
            pass

    return jsonify([])


@app.route("/api/history/cities")
def api_history_cities():
    if not os.path.exists(DB_PATH):
        return jsonify([])
    try:
        with _db_connect() as conn:
            rows = conn.execute("SELECT DISTINCT city FROM history_cities ORDER BY city").fetchall()
        return jsonify([r["city"] for r in rows])
    except Exception:
        return jsonify([])


@app.route("/api/building-costs")
def api_building_costs():
    if _db:
        try:
            ts = _db.costs_last_updated()
            if ts > 0:
                return jsonify(_db.get_building_costs())
        except Exception:
            pass
    if not os.path.exists(BUILDING_COSTS_JSON_PATH):
        return jsonify({"error": "building_costs.json não encontrado. Aguarda o próximo ciclo do bot."}), 404
    with open(BUILDING_COSTS_JSON_PATH) as f:
        return jsonify(json.load(f))


@app.route("/api/building-costs/refresh", methods=["POST"])
def api_building_costs_refresh():
    os.makedirs(LOGS_DIR, exist_ok=True)
    open(FORCE_COSTS_FLAG_PATH, "w").close()
    return jsonify({"ok": True, "message": "Extração forçada agendada para o próximo ciclo do bot."})


@app.route("/api/movements/refresh", methods=["POST"])
def api_movements_refresh():
    os.makedirs(LOGS_DIR, exist_ok=True)
    open(FORCE_MOVEMENTS_FLAG_PATH, "w").close()
    return jsonify({"ok": True})


@app.route("/api/data/refresh", methods=["POST"])
def api_data_refresh():
    os.makedirs(LOGS_DIR, exist_ok=True)
    open(FORCE_EMPIRE_FLAG_PATH, "w").close()
    return jsonify({"ok": True})


@app.route("/api/data/status")
def api_data_status():
    if not os.path.exists(EMPIRE_SCAN_STATUS_PATH):
        return jsonify({"status": "idle", "phase": "", "progress": 0, "total": 0, "message": ""})
    with open(EMPIRE_SCAN_STATUS_PATH) as f:
        data = json.load(f)
    if data.get("status") == "running":
        last_alive = None
        if os.path.exists(LAST_ALIVE_JSON_PATH):
            try:
                with open(LAST_ALIVE_JSON_PATH) as f:
                    last_alive = json.load(f).get("lastAlive")
            except Exception:
                pass
        if last_alive is None or (time.time() - last_alive) > 600:
            data["status"] = "error"
            data["message"] = "Bot offline"
    return jsonify(data)


@app.route("/api/world-scan")
def api_world_scan():
    if not os.path.exists(WORLD_SCAN_JSON_PATH):
        return jsonify({"error": "world_scan.json não encontrado. Aguarda o primeiro scan semanal ou força um."}), 404
    with open(WORLD_SCAN_JSON_PATH) as f:
        scan = json.load(f)
    # Marks live in the database only (the legacy player_marks.json was merged into it and
    # retired — see db_manager._migrate_marks).
    marks = {}
    if _db:
        try:
            marks = _db.get_all_marks()
        except Exception:
            pass
    # Build set of player IDs that were already inactive in the previous scan
    prev_inactive_ids = set()
    if os.path.exists(WORLD_SCAN_PREV_PATH):
        with open(WORLD_SCAN_PREV_PATH) as f:
            prev = json.load(f)
        prev_inactive_ids = {p["playerId"] for p in prev.get("players", [])}
    now = int(time.time())
    for player in scan.get("players", []):
        pid = player["playerId"]
        cid = str(player.get("cityId") or "")
        mk_city   = f"{pid}_{cid}" if cid else None
        mk_island = f"{pid}_{player.get('islandX', '')}_{player.get('islandY', '')}"
        entry = (mk_city and marks.get(mk_city)) or marks.get(mk_island) or marks.get(str(pid), {})
        status = entry.get("status", "novo")
        expires_at = entry.get("expiresAt")
        # Tiered ignore: a temporary ignore whose window has passed no longer hides the target
        # (it reappears for re-evaluation), but its strike count is kept for escalation.
        if status == "ignorar" and expires_at and now >= int(expires_at):
            status = "novo"
        player["mark"] = status
        player["markNote"] = entry.get("note", "")
        player["markActions"] = entry.get("actions", [])
        player["markUpdatedAt"] = entry.get("updatedAt")
        player["ignoreCount"] = entry.get("ignoreCount", 0) or 0
        player["ignoreExpiresAt"] = expires_at
        player["ignorePermanent"] = entry.get("status") == "ignorar" and not expires_at
        player["isNew"] = pid not in prev_inactive_ids
    return jsonify(scan)


@app.route("/api/world-scan/status")
def api_world_scan_status():
    if not os.path.exists(WORLD_SCAN_STATUS_PATH):
        return jsonify({"status": "idle", "phase": "", "progress": 0, "total": 0, "message": ""})
    with open(WORLD_SCAN_STATUS_PATH) as f:
        return jsonify(json.load(f))


@app.route("/api/world-scan/refresh", methods=["POST"])
def api_world_scan_refresh():
    os.makedirs(LOGS_DIR, exist_ok=True)
    open(FORCE_WORLD_SCAN_FLAG, "w").close()
    return jsonify({"ok": True, "message": "Scan forçado agendado para o próximo ciclo do bot."})


@app.route("/api/world-scan/mark", methods=["POST"])
def api_world_scan_mark():
    body = request.get_json(force=True)
    player_id = str(body.get("playerId", ""))
    island_x  = str(body.get("islandX", ""))
    island_y  = str(body.get("islandY", ""))
    city_id   = str(body.get("cityId", ""))
    status = body.get("status", "novo")
    note = body.get("note", "")
    if status not in ("novo", "visto", "alvo", "ignorar"):
        return jsonify({"error": "Status inválido"}), 400
    # Ignore/un-ignore always key on player+island (matching the bot's auto-ignore and the
    # Ignoradas tab's un-ignore), so a city-keyed mark can't shadow them. Other statuses
    # keep the historical city-or-island key.
    if status in ("ignorar", "novo"):
        mark_key = f"{player_id}_{island_x}_{island_y}"
    else:
        mark_key = f"{player_id}_{city_id}" if city_id else f"{player_id}_{island_x}_{island_y}"
    if _db:
        try:
            if status == "ignorar":
                esp = dict(_DEFAULT_ESPIONAGE_SETTINGS)
                try:
                    with open(ESPIONAGE_SETTINGS_PATH) as f:
                        esp.update(json.load(f))
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                res = _db.escalate_ignore(
                    mark_key, player_id, island_x, island_y, note or "Ignorado manualmente",
                    int(esp.get("ignoreExpiryDays", 60)),
                    int(esp.get("ignorePermanentAfter", 4)),
                )
                return jsonify({"ok": True, **res})
            # 'novo' un-ignore resets the strike count; 'visto'/'alvo' are plain marks.
            _db.save_mark(mark_key, player_id, island_x, island_y, status, note,
                          expires_at=None, ignore_count=0)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": "A marca não ficou gravada: %s" % e}), 500
    return jsonify({"error": "Base de dados indisponível"}), 503


@app.route("/api/world-scan/action", methods=["POST"])
def api_world_scan_action():
    body = request.get_json(force=True)
    player_id = str(body.get("playerId", ""))
    island_x  = str(body.get("islandX", ""))
    island_y  = str(body.get("islandY", ""))
    text = str(body.get("text", "")).strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    mark_key = f"{player_id}_{island_x}_{island_y}"
    if _db:
        try:
            _db.append_action(mark_key, player_id, island_x, island_y, text)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": "A nota não ficou gravada: %s" % e}), 500
    return jsonify({"error": "Base de dados indisponível"}), 503


def _load_building_queue():
    if _db:
        try:
            return _db.load_queue()
        except Exception:
            pass
    return {"queues": {}, "inProgress": {}, "transportErrors": {}}


def _save_building_queue(data):
    if _db:
        _db.save_queue(data)


def _load_queue_settings():
    """Load settings from queue_settings.json, falling back to building_queue.json."""
    if os.path.exists(QUEUE_SETTINGS_JSON_PATH):
        try:
            with open(QUEUE_SETTINGS_JSON_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    q = _load_building_queue()
    return {k: q[k] for k in ("activeHours", "resourceBuffer") if k in q}


def _save_queue_settings(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    _atomic_write_json(QUEUE_SETTINGS_JSON_PATH, data, indent=2)


@app.route("/api/building-queue")
def api_building_queue():
    data = _load_building_queue()
    data.pop("_base", None)          # merge snapshot (db_manager.save_queue) — internal
    data.update(_load_queue_settings())
    return jsonify(data)


def _queue_index_of(city_queue, body, index_key="index"):
    """Position of the item a queue action refers to. Prefer the item's stable `id`: the
    list on screen can be stale (the bot pops the head when a build starts), so a bare
    index could hit a different building than the one the user clicked. Returns
    (index, error_response) — exactly one is None."""
    if body.get("id") is not None:
        try:
            wanted = int(body["id"])
        except (ValueError, TypeError):
            return None, (jsonify({"error": "id inválido"}), 400)
        for i, it in enumerate(city_queue):
            if it.get("id") == wanted:
                return i, None
        return None, (jsonify({"error": "Esse item já não está na fila — lista actualizada",
                               "stale": True}), 409)
    try:
        index = int(body.get(index_key, -1))
    except (ValueError, TypeError):
        return None, (jsonify({"error": "index inválido"}), 400)
    if index < 0 or index >= len(city_queue):
        return None, (jsonify({"error": "index fora do intervalo"}), 400)
    return index, None


@app.route("/api/building-queue/add", methods=["POST"])
def api_building_queue_add():
    body = request.get_json(force=True)
    city_name = str(body.get("cityName", "")).strip()
    building_name = str(body.get("buildingName", "")).strip()
    try:
        target_level = int(body.get("targetLevel", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "targetLevel inválido"}), 400
    if not city_name or not building_name or target_level < 1:
        return jsonify({"error": "cityName, buildingName e targetLevel são obrigatórios"}), 400

    data = _load_building_queue()
    data.setdefault("queues", {}).setdefault(city_name, [])
    data["queues"][city_name].append({
        "building": building_name,
        "targetLevel": target_level,
        "addedAt": int(time.time()),
    })
    _save_building_queue(data)
    return jsonify({"ok": True, "queue": data["queues"][city_name]})


@app.route("/api/building-queue/add-many", methods=["POST"])
def api_building_queue_add_many():
    """Apply a construction template in one request (P13.47): it used to be one POST per row,
    each a full load + save of the queue. Rows whose building is already queued for that city
    are skipped ("queued"); invalid rows are reported ("error") without stopping the others."""
    body = request.get_json(silent=True) or {}
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return jsonify({"error": "items obrigatório (lista não vazia)"}), 400

    data = _load_building_queue()
    queues = data.setdefault("queues", {})
    now = int(time.time())
    results, added = [], 0
    for it in items:
        it = it if isinstance(it, dict) else {}
        city = str(it.get("cityName", "")).strip()
        building = str(it.get("buildingName", "")).strip()
        try:
            level = int(it.get("targetLevel", 0))
        except (ValueError, TypeError):
            level = 0
        if not city or not building or level < 1:
            results.append({"cityName": city, "buildingName": building, "status": "error",
                            "error": "cityName, buildingName e targetLevel são obrigatórios"})
            continue
        city_queue = queues.setdefault(city, [])
        if any(q.get("building") == building for q in city_queue):
            results.append({"cityName": city, "buildingName": building, "status": "queued"})
            continue
        city_queue.append({"building": building, "targetLevel": level, "addedAt": now})
        results.append({"cityName": city, "buildingName": building, "status": "added"})
        added += 1
    if added:
        _save_building_queue(data)
    return jsonify({"ok": True, "added": added, "results": results})


@app.route("/api/building-queue/remove", methods=["POST"])
def api_building_queue_remove():
    body = request.get_json(force=True)
    city_name = str(body.get("cityName", "")).strip()

    data = _load_building_queue()
    city_queue = data.get("queues", {}).get(city_name, [])
    index, err = _queue_index_of(city_queue, body)
    if err:
        return err

    city_queue.pop(index)
    data["queues"][city_name] = city_queue
    _save_building_queue(data)
    return jsonify({"ok": True, "queue": city_queue})


@app.route("/api/building-queue/clear", methods=["POST"])
def api_building_queue_clear():
    body = request.get_json(force=True) or {}
    city_name = str(body.get("cityName", "")).strip()
    data = _load_building_queue()
    if city_name:
        data.setdefault("queues", {})[city_name] = []
    else:
        data["queues"] = {c: [] for c in data.get("queues", {})}
    _save_building_queue(data)
    return jsonify({"ok": True})


@app.route("/api/building-queue/check", methods=["POST"])
def api_building_queue_check():
    os.makedirs(LOGS_DIR, exist_ok=True)
    open(FORCE_QUEUE_FLAG_PATH, "w").close()
    return jsonify({"ok": True})


@app.route("/api/building-queue/enabled", methods=["POST"])
def api_building_queue_enabled():
    body = request.get_json(force=True) or {}
    enabled = bool(body.get("enabled", True))
    data = _load_building_queue()
    data["enabled"] = enabled
    _save_building_queue(data)
    return jsonify({"ok": True, "enabled": enabled})


@app.route("/api/building-queue/settings", methods=["POST"])
def api_building_queue_settings():
    body = request.get_json(force=True) or {}
    settings = _load_queue_settings()
    if "activeHours" in body:
        ah = body["activeHours"]
        if isinstance(ah, dict):
            try:
                s, e = int(ah.get("start", 0)), int(ah.get("end", 24))
            except (ValueError, TypeError):
                return jsonify({"error": "Horas activas inválidas"}), 400
            # An inverted or empty window (22→6) used to be dropped while answering "ok".
            # The window cannot cross midnight: it is one stretch within the day.
            if not 0 <= s < e <= 24:
                return jsonify({"error": "As horas activas têm de ir de uma hora mais cedo para "
                                         "uma mais tarde, no mesmo dia (ex.: 7 → 23)."}), 400
            settings["activeHours"] = {"start": s, "end": e}
    if "resourceBuffer" in body:
        buf = body["resourceBuffer"]
        if isinstance(buf, list) and len(buf) == 5:
            try:
                settings["resourceBuffer"] = [max(0, int(b)) for b in buf]
            except (ValueError, TypeError):
                pass
    _save_queue_settings(settings)
    return jsonify({"ok": True})


@app.route("/api/building-queue/reorder", methods=["POST"])
def api_building_queue_reorder():
    body = request.get_json(force=True)
    city_name = str(body.get("cityName", "")).strip()

    data = _load_building_queue()
    city_queue = data.get("queues", {}).get(city_name, [])
    n = len(city_queue)
    from_idx, err = _queue_index_of(city_queue, body, index_key="fromIndex")
    if err:
        return err
    try:
        if body.get("id") is not None and "delta" in body:
            to_idx = from_idx + int(body["delta"])      # move relative to where it is NOW
        else:
            to_idx = int(body.get("toIndex", -1))
    except (ValueError, TypeError):
        return jsonify({"error": "fromIndex/toIndex inválidos"}), 400
    if not (0 <= from_idx < n and 0 <= to_idx < n) or from_idx == to_idx:
        return jsonify({"error": "índices inválidos"}), 400

    item = city_queue.pop(from_idx)
    city_queue.insert(to_idx, item)
    data["queues"][city_name] = city_queue
    _save_building_queue(data)
    return jsonify({"ok": True, "queue": city_queue})


_NOTIFY_LEVELS = ("activity", "info", "success", "warning", "error", "critical")
_NOTIFY_DEFAULT_MIN = {"telegramMinLevel": "info", "discordMinLevel": "activity"}
_NOTIFY_CATEGORIES = ("combat", "farm", "spy", "wine", "transport", "build", "system", "digest")
_NOTIFY_DIGEST_MODES = ("off", "hourly", "daily")
_DISCORD_WEBHOOK_RE = re.compile(r"^https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$")


_NOTIFY_SECRETS = (("botToken", "TELEGRAM_BOT_TOKEN"), ("discordWebhook", "DISCORD_WEBHOOK_URL"))


def _read_notify_settings():
    try:
        with open(TELEGRAM_SETTINGS_PATH) as f:
            saved = json.load(f)
        return saved if isinstance(saved, dict) else {}
    except Exception:
        return {}


@app.route("/api/telegram-settings", methods=["GET"])
def api_telegram_settings_get():
    """Notification settings. The two secrets (bot token, Discord webhook) are NEVER sent to
    the browser: each comes back empty with `<name>Set` / `<name>Hint` (its last 4
    characters) / `<name>Source` ("file" or "env"). They used to be returned in full — the
    environment values included — into plain text fields."""
    saved = _read_notify_settings()
    data = {"botToken": "", "chatId": "", "discordWebhook": "", **_NOTIFY_DEFAULT_MIN,
            "telegramMuted": [], "discordMuted": [], "digest": "daily", "digestHour": 21}
    for k in data:
        v = saved.get(k)
        if v not in (None, ""):
            data[k] = v
    if not data["chatId"]:
        data["chatId"] = os.getenv("TELEGRAM_CHAT_ID", "")
    for key, env in _NOTIFY_SECRETS:
        stored, from_env = str(saved.get(key) or ""), os.getenv(env, "")
        value = stored or from_env
        data[key] = ""
        data[key + "Set"] = bool(value)
        data[key + "Hint"] = ("…" + value[-4:]) if len(value) >= 8 else ""
        data[key + "Source"] = "file" if stored else ("env" if from_env else None)
    return jsonify(data)


@app.route("/api/telegram-settings", methods=["POST"])
def api_telegram_settings_save():
    body = request.get_json(force=True) or {}
    saved = _read_notify_settings()
    data = {"chatId": str(body.get("chatId", saved.get("chatId", ""))).strip()}
    # A secret is only replaced when a new value is typed; an empty field keeps what is
    # stored (the browser never has the current value), and `<name>Clear` removes it. A
    # value that lives in the environment is not copied into the file.
    for key, _env in _NOTIFY_SECRETS:
        typed = str(body.get(key, "") or "").strip()
        if body.get(key + "Clear"):
            data[key] = ""
        else:
            data[key] = typed or str(saved.get(key) or "")
    if data["discordWebhook"] and not _DISCORD_WEBHOOK_RE.match(data["discordWebhook"]):
        return jsonify({"ok": False, "error": "invalid_discord_webhook"}), 400
    for k, default in _NOTIFY_DEFAULT_MIN.items():
        lvl = str(body.get(k, saved.get(k, default)))
        data[k] = lvl if lvl in _NOTIFY_LEVELS else default
    for k in ("telegramMuted", "discordMuted"):
        raw = body.get(k, saved.get(k)) or []
        data[k] = [c for c in _NOTIFY_CATEGORIES if isinstance(raw, list) and c in raw]
    mode = str(body.get("digest", saved.get("digest", "daily")))
    data["digest"] = mode if mode in _NOTIFY_DIGEST_MODES else "daily"
    try:
        data["digestHour"] = min(23, max(0, int(body.get("digestHour", saved.get("digestHour", 21)))))
    except (TypeError, ValueError):
        data["digestHour"] = 21
    os.makedirs(LOGS_DIR, exist_ok=True)
    _atomic_write_json(TELEGRAM_SETTINGS_PATH, data)
    return jsonify({"ok": True})


@app.route("/api/telegram-settings/test", methods=["POST"])
def api_telegram_settings_test():
    """Send a test alert to every configured channel and report each one separately
    (True = sent, False = failed, None = not configured)."""
    try:
        import telegram_notifier as _tg
        results = _tg._send("🤖 <b>Teste de notificação</b>\nikabot dashboard — este canal está a funcionar.",
                            level="success", force=True)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    configured = [v for v in results.values() if v is not None]
    ok = bool(configured) and all(configured)
    return jsonify({"ok": ok, "channels": results})


@app.route("/api/espionage/spy-counts")
def api_espionage_spy_counts():
    """
    Return spy counts per city.
    Primary source: spy_counts.json written by fetch_spy_counts() from the bot.
    Fallback: compute deployed count from TRAVELING missions.
    """
    # Merge in-field counts from missions (always accurate)
    in_field: dict[str, int] = {}
    for m in _spy_missions():
        if m.get("state") == "TRAVELING":
            cid = str(m.get("originCityId", ""))
            in_field[cid] = in_field.get(cid, 0) + m.get("numAgents", 0)

    # Primary source: game-fetched counts
    try:
        with open(SPY_COUNTS_PATH) as f:
            data = json.load(f)
        by_city = data.get("byCityId", {})
        # Overlay in-field count from missions (more real-time than cached game data)
        for cid, cnt in in_field.items():
            if cid in by_city:
                by_city[cid]["deployed"] = cnt
            else:
                by_city[cid] = {"cityName": None, "available": None, "inDefense": None,
                                 "inTraining": None, "deployed": cnt, "trainable": None}
        return jsonify({"counts": by_city, "lastUpdated": data.get("lastUpdated", 0)})
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Fallback: only in-field data
    by_city = {cid: {"cityName": None, "available": None, "inDefense": None,
                      "inTraining": None, "deployed": cnt, "trainable": None}
               for cid, cnt in in_field.items()}
    return jsonify({"counts": by_city, "lastUpdated": 0})


def _garrison_view(mission):
    """What the garrison leg of a mission really established — decided HERE, once, with the
    bot's own rules, so the browser does not classify units itself (it did, with an English
    keyword list on a Portuguese server: nearly no ship matched and the land Catapulta did).
      garrisonOk   the garrison report completed (not failed / rejected / missing);
      enemyShips   ships in port — the report's own "Frotas em" section when present, else by
                   unit name; None when the garrison is not known;
      enemyTroops  land units; None when not known.
    A failed scout (success:false with an empty troops dict) is NOT "no troops, no ships"."""
    g = mission.get("garrisonResult")
    known = (isinstance(g, dict) and g.get("success", True) is not False
             and isinstance(g.get("troops"), dict) and g.get("error") is None)
    if not known:
        return {"garrisonOk": False, "enemyShips": None, "enemyTroops": None}
    troops = g["troops"]
    total = sum(int(v or 0) for v in troops.values())
    fleet = g.get("fleet")
    if isinstance(fleet, dict):
        ships = sum(int(v or 0) for v in fleet.values())
        land = sum(int(v or 0) for k, v in troops.items() if k not in fleet)
    else:                                  # report stored before the fleet section was kept
        ships = _seed_garrison_fleet_count(troops)
        land = total - ships
    return {"garrisonOk": True, "enemyShips": ships, "enemyTroops": land}


@app.route("/api/espionage/missions")
def api_espionage_missions():
    return jsonify({"missions": [dict(m, **_garrison_view(m)) for m in _spy_missions()]})


@app.route("/api/own-cities")
def api_own_cities():
    try:
        with open(os.path.join(LOGS_DIR, "own_cities.json")) as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


WORLD_SCAN_RADIUS_MIN, WORLD_SCAN_RADIUS_MAX = 1, 60


def _world_scan_default_radius():
    try:
        return max(WORLD_SCAN_RADIUS_MIN, min(WORLD_SCAN_RADIUS_MAX,
                                              int(os.getenv("WORLD_SCAN_RADIUS", 10))))
    except ValueError:
        return 10


def _read_world_scan_settings():
    try:
        with open(WORLD_SCAN_SETTINGS_PATH) as f:
            s = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    s.setdefault("enabled", True)
    try:
        s["radius"] = max(WORLD_SCAN_RADIUS_MIN, min(WORLD_SCAN_RADIUS_MAX, int(s["radius"])))
    except (KeyError, TypeError, ValueError):
        s["radius"] = _world_scan_default_radius()
    return s


@app.route("/api/world-scan/settings")
def api_world_scan_settings_get():
    return jsonify(_read_world_scan_settings())


@app.route("/api/world-scan/settings", methods=["POST"])
def api_world_scan_settings_post():
    """Partial update: only the keys present in the body change, so toggling `enabled`
    never resets the radius and vice-versa."""
    body = request.get_json(silent=True) or {}
    settings = _read_world_scan_settings()
    if "enabled" in body:
        settings["enabled"] = bool(body["enabled"])
    if "radius" in body:
        try:
            radius = int(body["radius"])
        except (TypeError, ValueError):
            return jsonify({"error": "radius must be an integer"}), 400
        if not WORLD_SCAN_RADIUS_MIN <= radius <= WORLD_SCAN_RADIUS_MAX:
            return jsonify({"error": f"radius must be between {WORLD_SCAN_RADIUS_MIN} "
                                     f"and {WORLD_SCAN_RADIUS_MAX}"}), 400
        settings["radius"] = radius
    os.makedirs(LOGS_DIR, exist_ok=True)
    _atomic_write_json(WORLD_SCAN_SETTINGS_PATH, settings, indent=2)
    return jsonify({"ok": True, **settings})


@app.route("/api/espionage/settings")
def api_espionage_settings_get():
    try:
        with open(ESPIONAGE_SETTINGS_PATH) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = dict(_DEFAULT_ESPIONAGE_SETTINGS)
    data.setdefault("processingEnabled", True)
    data.setdefault("minLootTotal", 50000)
    return jsonify(data)


@app.route("/api/espionage/settings", methods=["POST"])
def api_espionage_settings_post():
    body = request.get_json(silent=True) or {}
    try:
        with open(ESPIONAGE_SETTINGS_PATH) as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = dict(_DEFAULT_ESPIONAGE_SETTINGS)
    if "garrisonThresholdTotal" in body:
        existing["garrisonThresholdTotal"] = max(0, int(body["garrisonThresholdTotal"]))
    if "minLootTotal" in body:
        existing["minLootTotal"] = max(0, int(body["minLootTotal"]))
    if "processingEnabled" in body:
        existing["processingEnabled"] = bool(body["processingEnabled"])
    # These two were editable in Settings and showed "saved", but were never stored.
    for key, lo, hi in (("ignoreExpiryDays", 1, 365), ("ignorePermanentAfter", 1, 20)):
        if key in body:
            try:
                existing[key] = max(lo, min(hi, int(body[key])))
            except (TypeError, ValueError):
                pass
    os.makedirs(LOGS_DIR, exist_ok=True)
    _atomic_write_json(ESPIONAGE_SETTINGS_PATH, existing, indent=2)
    return jsonify({"ok": True, "settings": existing})


@app.route("/api/espionage/dispatch", methods=["POST"])
def api_espionage_dispatch():
    import uuid
    body = request.get_json(silent=True) or {}
    required = ["originCityId", "targetCityId", "islandId",
                "targetPlayerName", "targetCityName", "islandX", "islandY"]
    missing = [k for k in required if str(body.get(k, "")).strip() == ""]
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    item = {
        "id":               str(uuid.uuid4())[:8],
        "originCityId":     str(body["originCityId"]),
        "targetCityId":     str(body["targetCityId"]),
        "islandId":         str(body["islandId"]),
        "targetPlayerName": body["targetPlayerName"],
        "targetCityName":   body["targetCityName"],
        "islandX":          body["islandX"],
        "islandY":          body["islandY"],
        "numAgents":        int(body.get("numAgents", 1)),
        "numDecoys":        int(body.get("numDecoys", 0)),
        # Full sweep by default (warehouse + garrison + movements): a scout that also reads the
        # movements can stand in for the farm's first contact, so adding the target afterwards
        # does not repeat the whole sweep. Pass needMovements=false for a quicker look.
        "needGarrison":     True,
        "needMovements":    bool(body.get("needMovements", True)),
        "queuedAt":         int(time.time()),
    }

    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503
    try:
        _db.queue_add("spy_dispatch", item)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "queued"})


@app.route("/api/military")
def api_military():
    try:
        with open(MILITARY_JSON_PATH) as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"lastUpdated": 0, "byCityName": {}})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/attack-log")
def api_attack_log():
    if not _db:
        return jsonify([])
    try:
        limit = int(request.args.get("limit", 100))
        target = request.args.get("target", "").strip() or None
        return jsonify(_db.get_attack_log(limit=limit, target=target))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


CONSOLIDATE_SETTINGS_PATH = os.path.join(LOGS_DIR, "consolidate_settings.json")
CONSOLIDATE_STATE_PATH    = os.path.join(LOGS_DIR, "consolidate_state.json")



@app.route("/api/transport/queue")
def api_transport_queue_get():
    if not _db:
        return jsonify({"pending": []})
    try:
        return jsonify({"pending": _db.queue_items("transport")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/transport/queue/add", methods=["POST"])
def api_transport_queue_add():
    import uuid
    data = request.get_json(silent=True) or {}
    required = ["originCityId", "originCityName", "destCityId", "destCityName"]
    missing = [k for k in required if str(data.get(k, "")).strip() == ""]
    if missing:
        return jsonify({"error": f"Campo obrigatório: {missing}"}), 400
    if str(data["originCityId"]) == str(data["destCityId"]):
        return jsonify({"error": "Origem e destino têm de ser diferentes"}), 400

    try:
        resources = [max(0, int(a)) for a in (data.get("resources") or [])][:5]
    except (ValueError, TypeError):
        return jsonify({"error": "resources inválidos"}), 400
    resources += [0] * (5 - len(resources))
    if sum(resources) <= 0:
        return jsonify({"error": "Selecciona pelo menos um recurso"}), 400

    ships = int(data.get("ships", 0))
    if ships <= 0:
        return jsonify({"error": "Número de navios obrigatório"}), 400
    ship_type = data.get("shipType", "transporters")
    if ship_type not in ("transporters", "freighters"):
        return jsonify({"error": "shipType inválido"}), 400

    now = int(time.time())
    schedule_type = data.get("scheduleType", "now")
    if schedule_type == "delay":
        dispatch_after = now + max(1, int(data.get("delayMinutes", 1))) * 60
    elif schedule_type == "at":
        dispatch_after = int(data.get("dispatchAfter", now))
        if dispatch_after <= now:
            return jsonify({"error": "Hora de lançamento já passou"}), 400
    else:
        dispatch_after = now + 10

    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503

    item = {
        "id":             str(uuid.uuid4())[:8],
        "originCityId":   str(data["originCityId"]),
        "originCityName": str(data["originCityName"]),
        "destCityId":     str(data["destCityId"]),
        "destCityName":   str(data["destCityName"]),
        "islandId":       str(data.get("islandId", "")),
        "resources":      resources,
        "ships":          ships,
        "shipType":       ship_type,
        "addedAt":        now,
        "dispatchAfter":  dispatch_after,
    }
    try:
        _db.queue_add("transport", item)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "queued", "item": item})


@app.route("/api/transport/queue/cancel", methods=["POST"])
def api_transport_queue_cancel():
    data = request.get_json(silent=True) or {}
    item_id = data.get("id")
    if not item_id:
        return jsonify({"error": "id obrigatório"}), 400
    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503
    try:
        removed = _db.queue_remove("transport", [item_id])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if removed == 0:
        return jsonify({"error": "Transporte não encontrado"}), 404
    return jsonify({"status": "cancelled"})


@app.route("/api/transport/consolidate")
def api_consolidate_get():
    settings = settings_registry.load("consolidate", CONSOLIDATE_SETTINGS_PATH)
    state = {"lastRun": 0, "lastSent": {}}
    try:
        with open(CONSOLIDATE_STATE_PATH) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    settings["lastRun"]  = state.get("lastRun", 0)
    settings["lastSent"] = state.get("lastSent", {})
    return jsonify(settings)


@app.route("/api/transport/consolidate", methods=["POST"])
def api_consolidate_post():
    data = request.get_json(silent=True) or {}
    current = settings_registry.load("consolidate", CONSOLIDATE_SETTINGS_PATH)
    enabled = bool(data.get("enabled", current["enabled"]))
    if enabled and not str(data.get("destCityId", current["destCityId"]) or ""):
        return jsonify({"error": "Cidade de destino obrigatória"}), 400
    # Merge: keys the form does not send (skipResources, respectDestCap…) keep their value.
    settings = settings_registry.update("consolidate", data, CONSOLIDATE_SETTINGS_PATH)
    return jsonify({"status": "ok", "settings": settings})


@app.route("/api/farm")
def api_farm_list():
    if not _db:
        return jsonify([])
    try:
        return jsonify(_farm_queue_positions(_db.farm_list()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _farm_queue_positions(targets, now=None):
    """Add `queue_pos` (1 = worked first) to every enabled target, in the order the bot really
    works them (farm_manager._farm_working_set): targets already spying/attacking, then the
    DUE idle ones — loop mode first, then loot per hour, then scouted loot, then oldest — and
    last the idle ones still waiting, by when they come due. The browser used to rank them
    itself, by loot per hour only."""
    now = int(now if now is not None else time.time())

    def per_hour(t):
        journey = int(t.get("last_troop_journey", 0) or 0)
        return int(t.get("last_loot", 0) or 0) / max(1, journey * 2 if journey > 0 else 4 * 3600)

    def rank(t):
        return (1 if str(t.get("mode", "farm")) == "loop" else 0, per_hour(t),
                int(t.get("last_loot", 0) or 0), -int(t.get("created_at", 0) or 0))
    enabled = [t for t in targets if t.get("enabled")]
    active = [t for t in enabled if t.get("state", "IDLE") != "IDLE"]
    idle = [t for t in enabled if t.get("state", "IDLE") == "IDLE"]
    due = sorted((t for t in idle if now >= int(t.get("next_run_at", 0) or 0)), key=rank, reverse=True)
    later = sorted((t for t in idle if now < int(t.get("next_run_at", 0) or 0)),
                   key=lambda t: int(t.get("next_run_at", 0) or 0))
    for i, t in enumerate(active + due + later):
        t["queue_pos"] = i + 1
    return targets


FARM_SETTINGS_PATH = os.path.join(LOGS_DIR, "farm_settings.json")


def _load_farm_settings():
    try:
        with open(FARM_SETTINGS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _loot_cap_per_raid(settings):
    try:
        manual = int(settings.get("lootCapPerRaid", 0) or 0)
    except (TypeError, ValueError):
        manual = 0
    if manual > 0:
        return manual
    try:
        return _db.learned_loot_cap() if _db else None
    except Exception:
        return None


@app.route("/api/farm/army")
def api_farm_army_get():
    s = _load_farm_settings()
    return jsonify({
        "army": s.get("army", {}),
        "fleet": s.get("fleet", {}),
        "spyAgents": int(s.get("spyAgents", 1)),
        "shipReserveEnabled": bool(s.get("shipReserveEnabled", True)),
        "reserveHorizonMin": int(s.get("reserveHorizonMin", 45)),
        "earlyRespyEnabled": bool(s.get("earlyRespyEnabled", True)),
        # what one wave can carry home (manual setting, else learned from real returns)
        "lootCapPerRaid": _loot_cap_per_raid(s),
    })


@app.route("/api/farm/army", methods=["POST"])
def api_farm_army_set():
    data = request.get_json(silent=True) or {}
    # Merge so the ship-reserve keys (and any future settings) survive an army save. Each
    # key is only touched when it is SENT: every save used to replace `army` (and reset
    # spyAgents to 1 when absent), so toggling the ship reserve stored a half-typed loadout.
    s = _load_farm_settings()
    if "army" in data:
        try:
            s["army"] = {str(k): int(v) for k, v in (data.get("army") or {}).items() if int(v) > 0}
        except (ValueError, TypeError, AttributeError):
            return jsonify({"error": "loadout inválida"}), 400
    if "spyAgents" in data:
        try:
            s["spyAgents"] = max(1, min(99, int(data.get("spyAgents"))))
        except (ValueError, TypeError):
            pass
    if "fleet" in data:
        try:
            s["fleet"] = {str(k): int(v) for k, v in (data.get("fleet") or {}).items() if int(v) > 0}
        except (ValueError, TypeError):
            return jsonify({"error": "loadout de frota inválida"}), 400
    if "shipReserveEnabled" in data:
        s["shipReserveEnabled"] = bool(data.get("shipReserveEnabled"))
    if "reserveHorizonMin" in data:
        try:
            s["reserveHorizonMin"] = max(0, min(720, int(data.get("reserveHorizonMin"))))
        except (ValueError, TypeError):
            pass
    if "earlyRespyEnabled" in data:
        s["earlyRespyEnabled"] = bool(data.get("earlyRespyEnabled"))
    os.makedirs(LOGS_DIR, exist_ok=True)
    _atomic_write_json(FARM_SETTINGS_PATH, s, indent=2)
    return jsonify({"ok": True, **{k: s[k] for k in
                    ("army", "fleet", "spyAgents", "shipReserveEnabled", "reserveHorizonMin",
                     "earlyRespyEnabled") if k in s}})


# Naval-unit keywords (accent-stripped, lowercase) — a MIRROR of
# attack_manager._NAVAL_UNIT_NAMES, which is the source of truth. attack_manager is a bot
# module and is NOT mounted in the gui container, so the add-to-farm seed (Flask side) keeps
# its own copy; test_farm_seed_garrison asserts the two lists stay identical. Each keyword
# matches ONLY a naval unit in the mixed land+fleet garrison dict (e.g. "ariete a vapor" not
# "ariete", "porta-bal" not "balao").
_SEED_NAVAL_KEYWORDS = (
    "chamas", "ariete a vapor", "trirreme", "balista", "barco catapulta",
    "barco morteiro", "foguetes", "submergivel", "lancha", "porta-bal", "reparador",
)


def _seed_garrison_fleet_count(troops):
    """Count naval units in a garrison dict {unit_name: count}. 0 = fleet-free port (safe for
    a direct land raid); >0 = ships present → still a fleet target that needs its own scout +
    blockade. Mirrors attack_manager._enemy_fleet_count; land units are ignored."""
    if not troops:
        return 0
    import unicodedata
    total = 0
    for name, count in troops.items():
        norm = ''.join(c for c in unicodedata.normalize('NFD', str(name).lower())
                       if unicodedata.category(c) != 'Mn')
        if any(k in norm for k in _SEED_NAVAL_KEYWORDS):
            total += int(count or 0)
    return total


def _seed_farm_target_intel(city_id, island_x, island_y):
    """A freshly added farm target already has intel we can rank it by: the latest DONE spy
    report (MundoPage) gives the scouted warehouse total, and the island coordinates give a
    troop-travel estimate (closest own city, same formula as attack_manager, adjusted by the
    P6.7 calibration ratio). Without this every new target scores 0 and queues LAST even when
    its report says it's the richest — the head would only reorder after draining everything
    above it.

    It does NOT seed any clean-port / fleet-free confirmation (P12.2): an old garrison report is
    a point-in-time snapshot and can read 0 ships while a fleet is merely out at sea and due
    back, so trusting it to unlock a direct raid sent troops into a defended port (the Tróia 3
    bounce, 05/11). last_spy_at is left at 0 so the farm always runs its own first live full
    sweep (garrison + movements) before raiding a brand-new target; only a clean live sweep
    confirms it safe. Only fills fields still at 0: re-adding never overwrites measured
    stats/runtime state."""
    try:
        t = _db.farm_get(str(city_id))
        if not t:
            return
        # One pass over the mission store: newest DONE warehouse (loot) + newest SUCCESSFUL
        # garrison (troops) for this target.
        best_wh  = (-1, 0)      # (reportedAt, loot)
        best_gar = (-1, None)   # (reportedAt, troops) — successful reads only
        for m in _spy_missions():
            if str(m.get("targetCityId", "")) != str(city_id):
                continue
            if m.get("state") == "DONE":
                res = (m.get("result") or {}).get("resources") or {}
                ts  = int((m.get("result") or {}).get("reportedAt", 0)
                          or m.get("executedAt", 0) or 0)
                if res and ts >= best_wh[0]:
                    best_wh = (ts, sum(int(v or 0) for v in res.values()))
            g = m.get("garrisonResult") or {}
            if g.get("success") and ("troops" in g):
                ts = int(g.get("reportedAt", 0) or m.get("garrisonExecutedAt", 0) or 0)
                if ts >= best_gar[0]:
                    best_gar = (ts, g.get("troops") or {})

        updates = {}
        if not int(t.get("last_loot", 0) or 0) and best_wh[1] > 0:
            updates["last_loot"] = best_wh[1]
        if not int(t.get("last_troop_journey", 0) or 0) and island_x and island_y:
            try:
                with open(os.path.join(LOGS_DIR, "own_cities.json")) as f:
                    own = json.load(f)
                dist = min((((c.get("x", 0) - island_x) ** 2
                             + (c.get("y", 0) - island_y) ** 2) ** 0.5 for c in own),
                           default=0)
                if dist > 0:
                    est = int(1200 * dist)
                    try:
                        with open(TRAVEL_CALIBRATION_PATH) as f:
                            ratio = float(json.load(f).get("troop", {}).get("ratio", 1.0) or 1.0)
                    except (FileNotFoundError, json.JSONDecodeError, ValueError):
                        ratio = 1.0
                    updates["last_troop_journey"] = max(600, int(est * ratio))
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        # P12.2: the seed NO LONGER seals clean-port. An old garrison report showing 0 ships is a
        # point-in-time snapshot — if the fleet was out at sea (raiding, or bounced out by another
        # attacker and still sailing back), the harbour read empty while a fleet was due home. A
        # seed that unlocked direct-attack on that basis sent troops into a defended port (the
        # Tróia 3 bounce, 05/11). last_spy_at is left at 0 so the farm runs its OWN first live
        # full sweep (garrison + movements) before ever raiding; only a clean live sweep confirms
        # a target safe. The loot/journey seed above stays — it only feeds ranking, not safety.
        if updates:
            _db.farm_update(str(city_id), updates)
    except Exception:
        pass


@app.route("/api/farm/add", methods=["POST"])
def api_farm_add():
    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503
    data = request.get_json(silent=True) or {}
    if not str(data.get("targetCityId", "")).strip():
        return jsonify({"error": "targetCityId obrigatório"}), 400
    try:
        _db.farm_add({
            "targetCityId":   str(data["targetCityId"]),
            "targetCityName": data.get("targetCityName", ""),
            "targetPlayer":   data.get("targetPlayer", ""),
            "islandId":       str(data.get("islandId", "")),
            "islandX":        int(data.get("islandX", 0)),
            "islandY":        int(data.get("islandY", 0)),
            "enabled":        bool(data.get("enabled", True)),
            "intervalHours":  max(1, min(168, int(data.get("intervalHours", 8)))),
            "minLoot":        max(0, int(data.get("minLoot", 50000))),
            "maxEnemyShips":  max(0, int(data.get("maxEnemyShips", 0))),
            "respyEvery":     max(1, min(50, int(data.get("respyEvery", 3)))),
            "fleetLeadMin":   max(1, min(120, int(data.get("fleetLeadMin", 5)))),
            "disperseMin":    max(1, min(1440, int(data.get("disperseMin", 240)))),
            "mode":           "loop" if str(data.get("mode", "farm")) == "loop" else "farm",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    _seed_farm_target_intel(data["targetCityId"],
                            int(data.get("islandX", 0)), int(data.get("islandY", 0)))
    return jsonify({"ok": True})


def _unignore_farm_target(city_id):
    """Re-enabling a farm target un-hides it in the inactives list: clear any 'ignorar'
    mark (auto drain/skip or manual, city- or island-level key) back to 'novo'."""
    try:
        with open(WORLD_SCAN_JSON_PATH) as f:
            scan = json.load(f)
        player = next((p for p in scan.get("players", [])
                       if str(p.get("cityId")) == str(city_id)), None)
        if not player:
            return
        pid = str(player.get("playerId", ""))
        ix, iy = str(player.get("islandX", "")), str(player.get("islandY", ""))
        keys = {f"{pid}_{city_id}", f"{pid}_{ix}_{iy}"}

        db_marks = {}
        if _db:
            try:
                db_marks = _db.get_all_marks()
            except Exception:
                pass
        for k in keys:
            if db_marks.get(k, {}).get("status") == "ignorar" and _db:
                try:
                    _db.save_mark(k, pid, ix, iy, "novo", "")
                except Exception:
                    pass
    except Exception:
        pass


@app.route("/api/farm/update", methods=["POST"])
def api_farm_update():
    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503
    data = request.get_json(silent=True) or {}
    tid = str(data.get("targetCityId", "")).strip()
    if not tid:
        return jsonify({"error": "targetCityId obrigatório"}), 400
    fields = {}
    if "enabled" in data:        fields["enabled"] = 1 if data["enabled"] else 0
    if "intervalHours" in data:  fields["interval_hours"] = max(1, min(168, int(data["intervalHours"])))
    if "minLoot" in data:        fields["min_loot"] = max(0, int(data["minLoot"]))
    if "mode" in data:           fields["mode"] = "loop" if str(data["mode"]) == "loop" else "farm"
    if "maxEnemyShips" in data:  fields["max_enemy_ships"] = max(0, int(data["maxEnemyShips"]))
    if "respyEvery" in data:     fields["respy_every"] = max(1, min(50, int(data["respyEvery"])))
    if "fleetLeadMin" in data:   fields["fleet_lead_min"] = max(1, min(120, int(data["fleetLeadMin"])))
    if "disperseMin" in data:    fields["disperse_min"] = max(1, min(1440, int(data["disperseMin"])))
    # Manual reset back to IDLE/now so the next cycle re-runs immediately
    if data.get("runNow"):
        # Never while a raid is out: forcing IDLE made the farm forget troops that were still
        # sailing — it could launch a second wave on the same target and the real return was
        # then read against the wrong round.
        cur = _db.farm_get(tid) or {}
        if cur.get("state") == "ATTACKING":
            return jsonify({"error": "Há tropas a caminho ou a regressar deste alvo — "
                                     "o farm relança sozinho quando chegarem."}), 409
        fields["state"] = "IDLE"
        fields["next_run_at"] = 0
    try:
        _db.farm_update(tid, fields)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if fields.get("enabled") == 1:
        _unignore_farm_target(tid)
    return jsonify({"ok": True})


@app.route("/api/farm/remove", methods=["POST"])
def api_farm_remove():
    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503
    data = request.get_json(silent=True) or {}
    tid = str(data.get("targetCityId", "")).strip()
    if not tid:
        return jsonify({"error": "targetCityId obrigatório"}), 400
    try:
        removed = _db.farm_remove(tid)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if removed == 0:
        return jsonify({"error": "Alvo não encontrado"}), 404
    return jsonify({"ok": True})


ALERT_SETTINGS_PATH = os.path.join(LOGS_DIR, "alert_settings.json")
_DEFAULT_ALERT_SETTINGS = {"incomingEnabled": True, "returnEnabled": True, "checkMinutes": 0}

# P6.7: real/estimated travel ratio observed by the farm's journey fetches — the ETA
# preview in the UI multiplies its estimate (same fixed model as the bot) by this.
TRAVEL_CALIBRATION_PATH = os.path.join(LOGS_DIR, "travel_calibration.json")


@app.route("/api/travel-calibration")
def api_travel_calibration():
    try:
        with open(TRAVEL_CALIBRATION_PATH) as f:
            return jsonify(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({})


# P6.8: activity feed — "did my click actually happen?". Aggregates the signals that
# already exist (pending queue items, active .force_* flags, recent dispatch outcomes)
# instead of new bot-side plumbing: a flag disappearing means the bot picked it up.
_ACTIVITY_FLAGS = {
    ".force_empire_update":    "empire_update",
    ".force_world_scan":       "world_scan",
    ".force_costs_update":     "costs_update",
    ".force_movements_update": "movements_update",
    ".force_queue_check":      "queue_check",
    ".force_import_reports":   "import_reports",
    ".force_military_update":  "military_update",
    ".force_recall_unused":    "recall_unused",
}


@app.route("/api/activity")
def api_activity():
    pending = []
    if _db:
        for queue in ("attack", "spy_dispatch", "spy_recall", "transport"):
            try:
                for it in _db.queue_items(queue):
                    pending.append({
                        "queue":  queue,
                        "label":  it.get("targetCityName") or it.get("cityName")
                                  or it.get("destName") or it.get("targetPlayerName") or "",
                        "queuedAt": it.get("queuedAt") or it.get("addedAt") or it.get("createdAt"),
                        "dispatchAfter": it.get("dispatchAfter"),
                        "retries": it.get("retries", 0),
                    })
            except Exception:
                pass
    flags = []
    for fname, kind in _ACTIVITY_FLAGS.items():
        path = os.path.join(LOGS_DIR, fname)
        if os.path.exists(path):
            try:
                flags.append({"kind": kind, "requestedAt": int(os.path.getmtime(path))})
            except OSError:
                pass
    recent = []
    if _db:
        try:
            recent = _db.get_attack_log(limit=8)
        except Exception:
            pass
    return jsonify({"pending": pending, "flags": flags, "recent": recent})


TRANSPORT_FAILURES_PATH = os.path.join(LOGS_DIR, "transport_failures.json")


@app.route("/api/alerts/extra")
def api_alerts_extra():
    """What the Alerts page needs beyond the empire data (P13.58): subsystems failing and
    transports that failed — still retrying (from the queue) or given up in the last 24 h.
    Incoming attacks and the bot's heartbeat the browser already has."""
    subsystems = []
    try:
        with open(os.path.join(LOGS_DIR, "health.json")) as f:
            for name, v in (json.load(f) or {}).items():
                n = (v or {}).get("consecutiveFailures") or 0
                if isinstance(v, dict) and n > 0:
                    subsystems.append({"name": name, "failures": n, "error": str(v.get("lastError") or "")})
    except Exception:
        pass
    retrying = []
    if _db:
        try:
            for it in _db.queue_items("transport"):
                if (it.get("retries") or 0) > 0:
                    retrying.append({"origin": it.get("originCityName") or "", "dest": it.get("destCityName") or "",
                                     "retries": it.get("retries"), "error": it.get("lastError") or "",
                                     "nextTry": it.get("dispatchAfter")})
        except Exception:
            pass
    dropped = []
    try:
        with open(TRANSPORT_FAILURES_PATH) as f:
            cut = time.time() - 86400
            dropped = [x for x in (json.load(f).get("failures") or [])
                       if isinstance(x, dict) and (x.get("ts") or 0) >= cut]
    except Exception:
        pass
    return jsonify({"subsystems": subsystems, "transportRetrying": retrying, "transportDropped": dropped})


# P6.4: UI alert thresholds (wine/storage) live on the server, not per-browser localStorage,
# so every device sees the same configuration.
ALERT_THRESHOLDS_PATH = os.path.join(LOGS_DIR, "alert_thresholds.json")
_DEFAULT_ALERT_THRESHOLDS = {"wineWarning": 8, "wineCritical": 2, "storageWarning": 95}


@app.route("/api/alert-thresholds")
def api_alert_thresholds_get():
    try:
        with open(ALERT_THRESHOLDS_PATH) as f:
            data = json.load(f)
        merged = {k: data.get(k, v) for k, v in _DEFAULT_ALERT_THRESHOLDS.items()}
        return jsonify({"configured": True, **merged})
    except (FileNotFoundError, json.JSONDecodeError):
        # configured=False lets the frontend migrate its localStorage values on first load
        return jsonify({"configured": False, **_DEFAULT_ALERT_THRESHOLDS})


@app.route("/api/alert-thresholds", methods=["POST"])
def api_alert_thresholds_post():
    body = request.get_json(silent=True) or {}
    data = {}
    for k, v in _DEFAULT_ALERT_THRESHOLDS.items():
        try:
            data[k] = max(0, int(body.get(k, v)))
        except (TypeError, ValueError):
            data[k] = v
    os.makedirs(LOGS_DIR, exist_ok=True)
    _atomic_write_json(ALERT_THRESHOLDS_PATH, data, indent=2)
    return jsonify({"ok": True, **data})


@app.route("/api/alert-settings")
def api_alert_settings_get():
    try:
        with open(ALERT_SETTINGS_PATH) as f:
            s = json.load(f)
        for k, v in _DEFAULT_ALERT_SETTINGS.items():
            s.setdefault(k, v)
    except (FileNotFoundError, json.JSONDecodeError):
        s = dict(_DEFAULT_ALERT_SETTINGS)
    return jsonify(s)


@app.route("/api/alert-settings", methods=["POST"])
def api_alert_settings_post():
    data = request.get_json(silent=True) or {}
    s = {
        "incomingEnabled": bool(data.get("incomingEnabled", True)),
        "returnEnabled":   bool(data.get("returnEnabled", True)),
        "checkMinutes":    max(0, min(120, int(data.get("checkMinutes", 0)))),
    }
    os.makedirs(LOGS_DIR, exist_ok=True)
    _atomic_write_json(ALERT_SETTINGS_PATH, s, indent=2)
    return jsonify({"status": "ok", "settings": s})


WATCHLIST_SETTINGS_PATH = os.path.join(LOGS_DIR, "watchlist_settings.json")
_DEFAULT_WATCHLIST = {"enabled": False, "intervalHours": 12}


@app.route("/api/watchlist")
def api_watchlist_get():
    try:
        with open(WATCHLIST_SETTINGS_PATH) as f:
            s = json.load(f)
        for k, v in _DEFAULT_WATCHLIST.items():
            s.setdefault(k, v)
    except (FileNotFoundError, json.JSONDecodeError):
        s = dict(_DEFAULT_WATCHLIST)
    return jsonify(s)


@app.route("/api/watchlist", methods=["POST"])
def api_watchlist_post():
    data = request.get_json(silent=True) or {}
    s = {"enabled": bool(data.get("enabled", False)),
         "intervalHours": max(1, min(168, int(data.get("intervalHours", 12))))}
    os.makedirs(LOGS_DIR, exist_ok=True)
    _atomic_write_json(WATCHLIST_SETTINGS_PATH, s, indent=2)
    return jsonify({"status": "ok", "settings": s})


@app.route("/api/loot-log")
def api_loot_log():
    if not _db:
        return jsonify([])
    try:
        limit  = int(request.args.get("limit", 100))
        target = request.args.get("target", "").strip() or None
        return jsonify(_db.get_loot_log(limit=limit, target=target))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/loot-stats")
def api_loot_stats():
    if not _db:
        return jsonify([])
    try:
        # ?by=city → per source city (the targets list); default → per player (history panel)
        if request.args.get("by") == "city":
            return jsonify(_db.get_loot_stats_by_city())
        return jsonify(_db.get_loot_stats())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


WINE_SETTINGS_PATH = os.path.join(LOGS_DIR, "wine_settings.json")


@app.route("/api/transport/wine")
def api_wine_get():
    return jsonify(settings_registry.load("wine", WINE_SETTINGS_PATH))


@app.route("/api/transport/wine", methods=["POST"])
def api_wine_post():
    data = request.get_json(silent=True) or {}
    s = settings_registry.update("wine", data, WINE_SETTINGS_PATH)
    return jsonify({"status": "ok", "settings": s})


# ── Wine market buyer (F10) ───────────────────────────────────────────────────
WINE_BUY_SETTINGS_PATH = os.path.join(LOGS_DIR, "wine_buy_settings.json")
WINE_BUY_STATUS_PATH   = os.path.join(LOGS_DIR, "wine_buy_status.json")


@app.route("/api/transport/wine-buy")
def api_wine_buy_get():
    return jsonify(settings_registry.load("wine_buy", WINE_BUY_SETTINGS_PATH))


@app.route("/api/transport/wine-buy", methods=["POST"])
def api_wine_buy_post():
    data = request.get_json(silent=True) or {}
    s = settings_registry.update("wine_buy", data, WINE_BUY_SETTINGS_PATH)
    return jsonify({"status": "ok", "settings": s})


@app.route("/api/transport/wine-buy/status")
def api_wine_buy_status():
    try:
        with open(WINE_BUY_STATUS_PATH) as f:
            return jsonify(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({})


@app.route("/api/transport/wine-buy/preview", methods=["POST"])
def api_wine_buy_preview():
    os.makedirs(LOGS_DIR, exist_ok=True)
    open(os.path.join(LOGS_DIR, ".force_wine_buy"), "w").close()
    return jsonify({"ok": True, "message": "Preview de compra agendado (≤60s)."})


# ── Autonomous spy training (F14) ─────────────────────────────────────────────
SPY_BUILD_SETTINGS_PATH = os.path.join(LOGS_DIR, "spy_build_settings.json")
SPY_BUILD_STATUS_PATH   = os.path.join(LOGS_DIR, "spy_build_status.json")


def _spy_build_view(s):
    return {k: s[k] for k in settings_registry.defaults("spy_build")}


@app.route("/api/espionage/spy-build")
def api_spy_build_get():
    return jsonify(_spy_build_view(settings_registry.load("spy_build", SPY_BUILD_SETTINGS_PATH)))


@app.route("/api/espionage/spy-build", methods=["POST"])
def api_spy_build_post():
    data = request.get_json(silent=True) or {}
    s = settings_registry.update("spy_build", data, SPY_BUILD_SETTINGS_PATH)
    return jsonify({"status": "ok", "settings": _spy_build_view(s)})


@app.route("/api/espionage/spy-build/status")
def api_spy_build_status():
    try:
        with open(SPY_BUILD_STATUS_PATH) as f:
            return jsonify(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({})


@app.route("/api/espionage/spy-build/preview", methods=["POST"])
def api_spy_build_preview():
    os.makedirs(LOGS_DIR, exist_ok=True)
    open(os.path.join(LOGS_DIR, ".force_spy_build"), "w").close()
    return jsonify({"ok": True})


@app.route("/api/military/refresh", methods=["POST"])
def api_military_refresh():
    os.makedirs(LOGS_DIR, exist_ok=True)
    open(os.path.join(LOGS_DIR, ".force_military_update"), "w").close()
    return jsonify({"ok": True, "message": "Actualização militar agendada (≤60s)."})


@app.route("/api/espionage/attack-queue")
def api_attack_queue_get():
    if not _db:
        return jsonify({"pending": []})
    try:
        return jsonify({"pending": _db.queue_items("attack")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/espionage/attack-queue/add", methods=["POST"])
def api_attack_queue_add():
    import uuid, random as _rnd
    data = request.get_json(silent=True) or {}
    for field in ["originCityId", "originCityName", "targetCityId", "targetCityName",
                  "targetPlayerName", "islandX", "islandY", "islandId"]:
        if not str(data.get(field, "")).strip():
            return jsonify({"error": f"Campo obrigatório: {field}"}), 400
    units = {str(k): int(v) for k, v in (data.get("units") or {}).items() if int(v) > 0}
    if not units:
        return jsonify({"error": "units não pode estar vazio"}), 400

    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503

    delay_min = _rnd.randint(5, 20)
    item = {
        "id":               str(uuid.uuid4())[:8],
        "originCityId":     str(data["originCityId"]),
        "originCityName":   str(data["originCityName"]),
        "targetCityId":     str(data["targetCityId"]),
        "targetCityName":   str(data["targetCityName"]),
        "targetPlayerName": str(data["targetPlayerName"]),
        "islandX":          int(data["islandX"]),
        "islandY":          int(data["islandY"]),
        "islandId":         str(data["islandId"]),
        "units":            units,
        "transporters":     int(data.get("transporters", 0)),
        "addedAt":          int(time.time()),
        "dispatchAfter":    int(time.time()) + delay_min * 60,
        "missionId":        data.get("missionId"),
        "source":           "manual",
    }
    try:
        _db.queue_add("attack", item)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "queued", "item": item})


# How long after its dispatch time an attack counts as "being dispatched". The bot looks at
# the queue at least once a minute, and spaces several due attacks 30-90 s apart; past this
# window an item still in the queue is stuck (bot paused / outside active hours) and may go.
ATTACK_DISPATCH_GRACE_SECS = 5 * 60


def _attack_being_dispatched(item, now=None):
    """True while the bot may be sending this attack right now. A troop wave held by its
    blockade (`waitsForFleet`) is not sent at its dispatch time, so it can always be cancelled."""
    if item.get("waitsForFleet"):
        return False
    now = time.time() if now is None else now
    try:
        late = now - float(item.get("dispatchAfter", 0) or 0)
    except (TypeError, ValueError):
        return False
    return 0 <= late < ATTACK_DISPATCH_GRACE_SECS


@app.route("/api/espionage/attack-queue/cancel", methods=["POST"])
def api_attack_queue_cancel():
    data = request.get_json(silent=True) or {}
    attack_id = data.get("id")
    if not attack_id:
        return jsonify({"error": "id obrigatório"}), 400
    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503
    try:
        item = next((it for it in _db.queue_items("attack") if it.get("id") == attack_id), None)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if item and _attack_being_dispatched(item):
        # The bot reads the queue once per pass and dispatches from that copy: removing the row
        # now would say "cancelled" while the attack still leaves (P13.36).
        return jsonify({"error": "O bot está a despachar este ataque — já não dá para cancelar",
                        "code": "dispatching"}), 409
    try:
        removed = _db.queue_remove("attack", [attack_id])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if removed == 0:
        return jsonify({"error": "Ataque não encontrado"}), 404
    return jsonify({"status": "cancelled"})


@app.route("/api/dispatch/combat", methods=["POST"])
def api_dispatch_combat():
    import uuid
    data = request.get_json(silent=True) or {}
    required = ["originCityId", "originCityName", "targetCityId", "targetCityName",
                "targetPlayerName", "islandX", "islandY", "islandId", "missionType"]
    missing = [k for k in required if str(data.get(k, "")).strip() == ""]
    if missing:
        return jsonify({"error": f"Campo obrigatório: {missing}"}), 400

    units = {str(k): int(v) for k, v in (data.get("units") or {}).items() if int(v) > 0}
    if not units:
        return jsonify({"error": "units não pode estar vazio"}), 400

    mission_type = data["missionType"]
    if mission_type not in ("army", "fleet"):
        return jsonify({"error": "missionType deve ser 'army' ou 'fleet'"}), 400

    target_type = data.get("targetType", "enemy")
    if target_type not in ("own", "enemy"):
        return jsonify({"error": "targetType deve ser 'own' ou 'enemy'"}), 400

    now = int(time.time())
    schedule_type = data.get("scheduleType", "now")
    if schedule_type == "delay":
        delay_minutes = max(1, int(data.get("delayMinutes", 1)))
        dispatch_after = now + delay_minutes * 60
    elif schedule_type == "at":
        dispatch_after = int(data.get("dispatchAfter", now))
        if dispatch_after <= now:
            return jsonify({"error": "Hora de lançamento já passou"}), 400
    else:
        dispatch_after = now + 10

    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503

    item = {
        "id":               str(uuid.uuid4())[:8],
        "originCityId":     str(data["originCityId"]),
        "originCityName":   str(data["originCityName"]),
        "targetCityId":     str(data["targetCityId"]),
        "targetCityName":   str(data["targetCityName"]),
        "targetPlayerName": str(data["targetPlayerName"]),
        "islandX":          int(data["islandX"]),
        "islandY":          int(data["islandY"]),
        "islandId":         str(data["islandId"]),
        "units":            units,
        "transporters":     int(data.get("transporters", 0)),
        "missionType":      mission_type,
        "targetType":       target_type,
        "addedAt":          now,
        "dispatchAfter":    dispatch_after,
        "missionId":        None,
        "source":           "manual",
    }
    try:
        _db.queue_add("attack", item)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "queued", "item": item})


@app.route("/api/espionage/import-reports", methods=["POST"])
def api_espionage_import_reports():
    os.makedirs(LOGS_DIR, exist_ok=True)
    open(FORCE_IMPORT_REPORTS_FLAG, "w").close()
    return jsonify({"status": "queued"})


def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path, data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    _atomic_write_json(path, data, indent=2)


_SPY_GONE_MARKERS = ("não encontrado ao tentar executar", "possivelmente capturado",
                     "servidor rejeitou o dispatch", "não está inactivo", "férias",
                     "espiões insuficientes", "reposto no arranque")


def _missions_newest_first(missions, city_id):
    """Indices of the city's spy missions, newest dispatch first."""
    idx = [i for i, m in enumerate(missions) if str(m.get("targetCityId", "")) == city_id]
    return sorted(idx, key=lambda i: int(missions[i].get("dispatchedAt") or 0), reverse=True)


@app.route("/api/espionage/force-warehouse", methods=["POST"])
def api_espionage_force_warehouse():
    body    = request.get_json(force=True)
    city_id = str(body.get("cityId", ""))
    if not city_id:
        return jsonify({"error": "cityId required"}), 400

    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503
    data     = _db.missions_load()
    missions = data.get("missions", [])
    now      = int(time.time())
    # Act on the NEWEST mission for the city — the one the UI shows. File order is not
    # chronological, so the first match was often a weeks-old ghost (or an imported report).
    for i in _missions_newest_first(missions, city_id):
        m = missions[i]
        if m.get("state") == "WAITING_AT_CITY":
            missions[i]["executeAfter"] = now - 1
            data["missions"] = missions
            _db.missions_save(data)
            return jsonify({"ok": True})
        if m.get("state") == "WAITING_FOR_GARRISON":
            missions[i]["garrisonExecuteAfter"] = now - 1
            data["missions"] = missions
            _db.missions_save(data)
            return jsonify({"ok": True})
        if m.get("state") in ("EXECUTING_WAREHOUSE", "EXECUTING_GARRISON"):
            return jsonify({"ok": True, "message": "Missão já em execução"})
        # DONE = spy parked after a clean run; FAILED = a run was abandoned but the spy may
        # still be stationed (transient rejection / missing report). Re-arm either one — the
        # bot re-fetches the safehouse and only acts if the spy is really there.
        if m.get("state") in ("DONE", "FAILED"):
            if not m.get("originCityId"):
                # Synthetic imported mission — no real spy stationed, cannot re-execute
                return jsonify({"error": "Missão importada sem espião activo — usa o dispatch normal"}), 400
            err = str(m.get("error") or "").lower()
            if m.get("state") == "FAILED" and any(k in err for k in _SPY_GONE_MARKERS):
                # Mirrors espionage_manager._SPY_GONE_MARKERS: re-arming would only end in
                # "espião desapareceu" again — tell the user to send fresh spies instead.
                return jsonify({"error": "Os espiões desta cidade foram capturados ou nunca partiram — envia espiões novos"}), 409
            missions[i]["state"] = "WAITING_AT_CITY"
            missions[i]["executeAfter"] = now - 1
            missions[i]["garrisonResult"] = None
            missions[i]["garrisonExecutedAt"] = None
            missions[i]["garrisonExecuteAfter"] = None
            missions[i]["warehouseRetries"] = 0
            missions[i]["error"] = None
            data["missions"] = missions
            _db.missions_save(data)
            return jsonify({"ok": True})

    return jsonify({"error": "Nenhum espião estacionado nessa cidade"}), 404


@app.route("/api/espionage/recall-spy", methods=["POST"])
def api_espionage_recall_spy():
    body    = request.get_json(force=True)
    city_id = str(body.get("cityId", ""))
    if not city_id:
        return jsonify({"error": "cityId required"}), 400

    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503
    data     = _db.missions_load()
    missions = data.get("missions", [])
    now      = int(time.time())
    changed  = False
    # FAILED included: a failed run often leaves the spy stranded in the target safehouse,
    # and this is the only way to bring it home (the recall processor treats "already home"
    # as success, so recalling a genuinely-gone spy is harmless).
    recallable = {"TRAVELING", "WAITING_AT_CITY", "EXECUTING_WAREHOUSE",
                  "WAITING_FOR_GARRISON", "EXECUTING_GARRISON", "DONE", "FAILED"}
    for i in _missions_newest_first(missions, city_id):
        m = missions[i]
        if m.get("state") not in recallable:
            continue
        origin_id = str(m.get("originCityId") or "")
        if not origin_id:
            return jsonify({"error": "Missão importada — sem espião real para chamar de volta"}), 400
        missions[i]["state"]      = "RECALLED"
        missions[i]["recalledAt"] = now
        position = m.get("safehousePosition")
        if position and _db:
            _db.queue_add("spy_recall", {
                "targetCityId":   city_id,
                "targetIslandId": str(m.get("targetIslandId", "")),
                "originCityId":   origin_id,
                "position":       position,
                "cityName":       m.get("targetCityName", ""),
                "spySessionId":   m.get("spySessionId"),
                "numAgents":      m.get("numAgents", 1),
                "queuedAt":       now,
            })
        changed = True
        break  # recall only the first active mission found
    if not changed:
        return jsonify({"error": "Nenhum espião activo nessa cidade"}), 404
    data["missions"] = missions
    _db.missions_save(data)
    return jsonify({"ok": True})


@app.route("/api/espionage/recall-unused", methods=["POST"])
def api_espionage_recall_unused():
    """Flag the bot to sweep-recall every stationed spy nothing is using (enabled farm
    targets and missions in progress are kept). The bot reads the real deployments from
    the safehouses and queues recalls in throttled batches on its next wake-up."""
    open(os.path.join(LOGS_DIR, ".force_recall_unused"), "w").close()
    deployed = 0
    try:
        with open(SPY_COUNTS_PATH) as f:
            for c in json.load(f).get("byCityId", {}).values():
                deployed += int(c.get("deployed") or 0)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass
    return jsonify({"ok": True, "deployed": deployed})


BOT_LOG_PATH = os.path.join(LOGS_DIR, "bot.log")
PAUSE_PATH   = os.path.join(LOGS_DIR, "pause.json")


@app.route("/api/logs")
def api_logs():
    """Tail the bot log (F10). bot.log is size-bounded (rotating), so reading it
    whole is cheap."""
    try:
        n = max(1, min(int(request.args.get("lines", 200)), 2000))
    except (ValueError, TypeError):
        n = 200
    if not os.path.exists(BOT_LOG_PATH):
        return jsonify({"lines": [], "note": "bot.log ainda não existe — aguarda o bot arrancar"})
    try:
        # Read only the tail: the page polls every 5s and the whole file (up to ~1 MB) was
        # read and split each time. DEBUG lines are filtered out below, so take a generous
        # window (they outnumber the rest about 10 to 1) and widen it if that is not enough.
        size = os.path.getsize(BOT_LOG_PATH)
        want_debug = request.args.get("debug") in ("1", "true")
        window = n * (300 if want_debug else 3000)
        while True:
            with open(BOT_LOG_PATH, "rb") as f:
                f.seek(max(0, size - window))
                raw = f.read()
            content = raw.decode("utf-8", errors="replace").splitlines()
            if size > window:
                content = content[1:]          # the first line is cut mid-way
            kept = sum(1 for ln in content if want_debug or " DEBUG " not in ln)
            if kept >= n or window >= size:
                break
            window *= 4
        # bot.log records DEBUG (routine chatter); the dashboard shows INFO+ unless
        # explicitly asked for the full stream with ?debug=1.
        if request.args.get("debug") not in ("1", "true"):
            content = [ln for ln in content if " DEBUG " not in ln]
        return jsonify({"lines": content[-n:]})
    except Exception as e:
        return jsonify({"lines": [], "error": str(e)}), 500


@app.route("/api/pause")
def api_pause_get():
    paused = False
    try:
        with open(PAUSE_PATH) as f:
            paused = bool(json.load(f).get("paused", False))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return jsonify({"paused": paused})


@app.route("/api/pause", methods=["POST"])
def api_pause_set():
    data = request.get_json(silent=True) or {}
    paused = bool(data.get("paused", False))
    os.makedirs(LOGS_DIR, exist_ok=True)
    _atomic_write_json(PAUSE_PATH, {"paused": paused})
    return jsonify({"ok": True, "paused": paused})


@app.route("/api/health")
def api_health():
    db_ok = False
    if _db:
        try:
            _db.init_db()
            db_ok = True
        except Exception:
            pass
    # Per-subsystem health (P5.2): consecutive failures, last error/success per module.
    subsystems = {}
    try:
        with open(os.path.join(LOGS_DIR, "health.json")) as f:
            subsystems = json.load(f)
    except Exception:
        pass
    # Config schema warnings (P5.8): mistyped/unknown keys silently ignored by the bot.
    config_warnings = {}
    try:
        with open(os.path.join(LOGS_DIR, "config_warnings.json")) as f:
            config_warnings = json.load(f)
    except Exception:
        pass
    # Requests the bot sent to the game, per hour (P13.23) — last 24 hours, newest last.
    requests_by_hour = []
    try:
        with open(os.path.join(LOGS_DIR, "request_stats.json")) as f:
            hours = json.load(f).get("hours", {})
        for h in sorted(hours)[-24:]:
            st = hours[h]
            requests_by_hour.append({"hour": h, "get": st.get("get", 0), "post": st.get("post", 0),
                                     "tokenGets": st.get("post", 0),
                                     "kinds": st.get("kinds", {})})
    except Exception:
        pass
    return jsonify({"status": "ok", "ts": int(time.time()), "dbOk": db_ok,
                    "subsystems": subsystems, "configWarnings": config_warnings,
                    "requests": requests_by_hour})


class _DbChangeWatch:
    """Tells whether another connection committed to the SQLite file since the last look
    (P13.40). The queues, farm, attack/loot logs and spy missions live there, and the SSE only
    watched JSON files, so the pages built on them never heard of a change. File mtimes do not
    work for this (the WAL is truncated on checkpoint and readers touch the -shm);
    `PRAGMA data_version` changes exactly when someone else commits."""

    def __init__(self, path):
        self.path, self.conn, self.last = path, None, None

    def changed(self):
        try:
            if self.conn is None:
                if not os.path.exists(self.path):
                    return False
                self.conn = sqlite3.connect("file:%s?mode=ro" % self.path, uri=True,
                                            timeout=2, check_same_thread=False)
            version = self.conn.execute("PRAGMA data_version").fetchone()[0]
        except Exception:
            self.close()
            return False
        prev, self.last = self.last, version
        return prev is not None and version != prev

    def close(self):
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass
        self.conn = None


def _topic_paths():
    """Files behind each live topic besides the database (`change` event, P13.40)."""
    return {"spy": [SPY_COUNTS_PATH], "military": [MILITARY_JSON_PATH]}


@app.route("/api/stream")
def api_stream():
    """SSE endpoint — emits 'update' whenever any data file on the shared volume changes."""
    watched = [
        EMPIRE_JSON_PATH, RESOURCES_JSON_PATH, STATUS_SUMMARY_JSON_PATH,
        MOVEMENTS_JSON_PATH, QUEUE_SENTINEL_PATH, NEXT_CYCLE_JSON_PATH,
        WORLD_SCAN_JSON_PATH, WORLD_SCAN_STATUS_PATH,
    ]
    # The heartbeat is rewritten every ≤60s. Watched with the data files it fired `update`
    # all the time, and every `update` made the browser re-fetch the whole empire (and the
    # home page the whole cost table). It gets its own light event carrying the timestamp.

    # `change` (P13.40) names what else changed — "db" (queues, farm, logs, missions), "spy",
    # "military" — so a page re-fetches only what it shows. `update` stays as it was: the
    # empire data, which the whole app reloads.
    topic_paths = _topic_paths()

    def _mt(p):
        return os.path.getmtime(p) if os.path.exists(p) else 0

    def generate():
        last_mtimes = {p: os.path.getmtime(p) if os.path.exists(p) else 0 for p in watched}
        alive_mtime = os.path.getmtime(LAST_ALIVE_JSON_PATH) if os.path.exists(LAST_ALIVE_JSON_PATH) else 0
        topic_mtimes = {p: _mt(p) for ps in topic_paths.values() for p in ps}
        db_watch = _DbChangeWatch(DB_PATH)
        db_watch.changed()   # first look sets the baseline
        yield ": connected\n\n"
        try:
            yield from _stream_loop(last_mtimes, alive_mtime, topic_mtimes, db_watch)
        finally:
            db_watch.close()

    def _stream_loop(last_mtimes, alive_mtime, topic_mtimes, db_watch):
        while True:
            time.sleep(2)
            mtime = os.path.getmtime(LAST_ALIVE_JSON_PATH) if os.path.exists(LAST_ALIVE_JSON_PATH) else 0
            if mtime != alive_mtime:
                alive_mtime = mtime
                yield "event: alive\ndata: %d\n\n" % int(mtime)
            changed = False
            for p in watched:
                mtime = os.path.getmtime(p) if os.path.exists(p) else 0
                if mtime != last_mtimes[p]:
                    last_mtimes[p] = mtime
                    changed = True
            topics = ["db"] if db_watch.changed() else []
            for topic, paths in topic_paths.items():
                for p in paths:
                    mtime = _mt(p)
                    if mtime != topic_mtimes.get(p):
                        topic_mtimes[p] = mtime
                        if topic not in topics:
                            topics.append(topic)
            if changed:
                yield "event: update\ndata: {}\n\n"
            if topics:
                yield "event: change\ndata: %s\n\n" % ",".join(topics)
            if not changed and not topics:
                yield ": keepalive\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _offline_watch_loop():
    """Notify via Telegram when the bot stops writing last_alive (checked every 5 min).
    Lives in its own thread — a GET endpoint must not have notification side effects."""
    while True:
        time.sleep(300)
        try:
            with open(LAST_ALIVE_JSON_PATH) as f:
                last_alive = json.load(f).get("lastAlive")
        except Exception:
            continue
        if not last_alive:
            continue
        try:
            import telegram_notifier as _tg
            offline_min = int((time.time() - last_alive) / 60)
            if (time.time() - last_alive) > BOT_OFFLINE_SECS:
                # Suppress alerts for outages that began during the nightly quiet window
                # (host asleep → benign). The flag isn't armed, so the morning recovery
                # won't fire a spurious clear either.
                if not _in_quiet_window(last_alive):
                    _tg.notify_bot_offline(offline_min)
            else:
                _tg.clear_bot_offline()
        except Exception:
            pass


if __name__ == "__main__":
    # debug=False: the Werkzeug debugger is an RCE if the port is ever exposed.
    # No auto-reload: it restarted the dashboard on a half-written edit, or onto code whose
    # new module was not mounted yet (down for a minute on 2026-11-15), and it was never
    # reliable through the bind mount anyway. A change to this file needs a container
    # restart — which is already the deploy rule.
    import threading
    threading.Thread(target=_offline_watch_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, threaded=True)
