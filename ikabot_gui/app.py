from flask import Flask, render_template, jsonify, request, Response, stream_with_context
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
HISTORY_JSONL_PATH      = os.path.join(LOGS_DIR, "history.jsonl")
BUILDING_COSTS_JSON_PATH = os.path.join(LOGS_DIR, "building_costs.json")
FORCE_COSTS_FLAG_PATH   = os.path.join(LOGS_DIR, ".force_costs_update")
WORLD_SCAN_JSON_PATH    = os.path.join(LOGS_DIR, "world_scan.json")
WORLD_SCAN_PREV_PATH    = os.path.join(LOGS_DIR, "world_scan_prev.json")
WORLD_SCAN_STATUS_PATH  = os.path.join(LOGS_DIR, "world_scan_status.json")
PLAYER_MARKS_JSON_PATH  = os.path.join(LOGS_DIR, "player_marks.json")
FORCE_WORLD_SCAN_FLAG       = os.path.join(LOGS_DIR, ".force_world_scan")
FORCE_MOVEMENTS_FLAG_PATH   = os.path.join(LOGS_DIR, ".force_movements_update")
FORCE_EMPIRE_FLAG_PATH      = os.path.join(LOGS_DIR, ".force_empire_update")
FORCE_QUEUE_FLAG_PATH       = os.path.join(LOGS_DIR, ".force_queue_check")
BUILDING_QUEUE_JSON_PATH    = os.path.join(LOGS_DIR, "building_queue.json")
QUEUE_SENTINEL_PATH         = os.path.join(LOGS_DIR, ".queue_updated")
TELEGRAM_SETTINGS_PATH      = os.path.join(LOGS_DIR, "telegram_settings.json")
DB_PATH                     = os.path.join(LOGS_DIR, "ikabot.db")
QUEUE_SETTINGS_JSON_PATH    = os.path.join(LOGS_DIR, "queue_settings.json")
NEXT_CYCLE_JSON_PATH    = os.path.join(LOGS_DIR, "next_cycle.json")
LAST_ALIVE_JSON_PATH    = os.path.join(LOGS_DIR, "last_alive.json")
EMPIRE_SCAN_STATUS_PATH = os.path.join(LOGS_DIR, "empire_scan_status.json")
SPY_MISSIONS_PATH          = os.path.join(LOGS_DIR, "spy_missions.json")
SPY_COUNTS_PATH            = os.path.join(LOGS_DIR, "spy_counts.json")
ESPIONAGE_SETTINGS_PATH    = os.path.join(LOGS_DIR, "espionage_settings.json")
MILITARY_JSON_PATH         = os.path.join(LOGS_DIR, "military.json")
AUTO_ATTACK_WAVES_PATH     = os.path.join(LOGS_DIR, "auto_attack_waves.json")
AUTO_ATTACK_SETTINGS_PATH    = os.path.join(LOGS_DIR, "auto_attack_settings.json")
WORLD_SCAN_SETTINGS_PATH     = os.path.join(LOGS_DIR, "world_scan_settings.json")
FORCE_IMPORT_REPORTS_FLAG    = os.path.join(LOGS_DIR, ".force_import_reports")

_DEFAULT_ESPIONAGE_SETTINGS = {
    "garrisonThresholdTotal": 50000,
    "processingEnabled": True,
}

_DEFAULT_AUTO_ATTACK_SETTINGS = {
    "enabled":                False,
    "minLootTotal":           50000,
    "lootPerWave":            195000,
    "battleDelayFewMins":     30,
    "battleDelayMedMins":     60,
    "battleDelayManyMins":    120,
    "maxEnemyShipsToEngage":  20,
}


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
    if os.path.exists(BUILDING_QUEUE_JSON_PATH):
        try:
            with open(BUILDING_QUEUE_JSON_PATH) as f:
                queue_data = json.load(f)
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
    }, None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    data, error = load_all_data()
    if error:
        return jsonify({"error": error}), 404
    return jsonify(data)


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

    # Empire-wide: try SQLite first, fall back to JSONL
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

    # JSONL fallback
    if not os.path.exists(HISTORY_JSONL_PATH):
        return jsonify([])
    with open(HISTORY_JSONL_PATH) as f:
        lines = f.readlines()
    entries = []
    for line in lines[-limit:]:
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    return jsonify(entries)


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
    # Merge marks from DB and JSON — JSON wins on conflict (bot writes there)
    marks = {}
    if _db:
        try:
            marks = _db.get_all_marks()
        except Exception:
            pass
    if os.path.exists(PLAYER_MARKS_JSON_PATH):
        try:
            with open(PLAYER_MARKS_JSON_PATH) as f:
                json_marks = json.load(f)
            for k, v in json_marks.items():
                if k not in marks or v.get("updatedAt", 0) > marks[k].get("updatedAt", 0):
                    marks[k] = v
        except Exception:
            pass
    # Build set of player IDs that were already inactive in the previous scan
    prev_inactive_ids = set()
    if os.path.exists(WORLD_SCAN_PREV_PATH):
        with open(WORLD_SCAN_PREV_PATH) as f:
            prev = json.load(f)
        prev_inactive_ids = {p["playerId"] for p in prev.get("players", [])}
    for player in scan.get("players", []):
        pid = player["playerId"]
        cid = str(player.get("cityId") or "")
        mk_city   = f"{pid}_{cid}" if cid else None
        mk_island = f"{pid}_{player.get('islandX', '')}_{player.get('islandY', '')}"
        entry = (mk_city and marks.get(mk_city)) or marks.get(mk_island) or marks.get(str(pid), {})
        player["mark"] = entry.get("status", "novo")
        player["markNote"] = entry.get("note", "")
        player["markActions"] = entry.get("actions", [])
        player["markUpdatedAt"] = entry.get("updatedAt")
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
    mark_key  = f"{player_id}_{city_id}" if city_id else f"{player_id}_{island_x}_{island_y}"
    status = body.get("status", "novo")
    note = body.get("note", "")
    if status not in ("novo", "visto", "alvo", "ignorar"):
        return jsonify({"error": "Status inválido"}), 400
    if _db:
        try:
            _db.save_mark(mark_key, player_id, island_x, island_y, status, note)
            return jsonify({"ok": True})
        except Exception:
            pass
    # JSON fallback
    marks = {}
    if os.path.exists(PLAYER_MARKS_JSON_PATH):
        with open(PLAYER_MARKS_JSON_PATH) as f:
            marks = json.load(f)
    existing = marks.get(mark_key, {})
    marks[mark_key] = {
        "status": status, "note": note,
        "updatedAt": int(time.time()), "actions": existing.get("actions", []),
    }
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(PLAYER_MARKS_JSON_PATH, "w") as f:
        json.dump(marks, f, indent=2)
    return jsonify({"ok": True})


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
        except Exception:
            pass
    # JSON fallback
    marks = {}
    if os.path.exists(PLAYER_MARKS_JSON_PATH):
        with open(PLAYER_MARKS_JSON_PATH) as f:
            marks = json.load(f)
    entry = marks.setdefault(mark_key, {
        "status": "novo", "note": "", "updatedAt": int(time.time()), "actions": []
    })
    entry.setdefault("actions", []).append({"ts": int(time.time()), "text": text})
    entry["updatedAt"] = int(time.time())
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(PLAYER_MARKS_JSON_PATH, "w") as f:
        json.dump(marks, f, indent=2)
    return jsonify({"ok": True})


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
    with open(QUEUE_SETTINGS_JSON_PATH, "w") as f:
        json.dump(data, f, indent=2)


@app.route("/api/building-queue")
def api_building_queue():
    data = _load_building_queue()
    data.update(_load_queue_settings())
    return jsonify(data)


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


@app.route("/api/building-queue/remove", methods=["POST"])
def api_building_queue_remove():
    body = request.get_json(force=True)
    city_name = str(body.get("cityName", "")).strip()
    try:
        index = int(body.get("index", -1))
    except (ValueError, TypeError):
        return jsonify({"error": "index inválido"}), 400

    data = _load_building_queue()
    city_queue = data.get("queues", {}).get(city_name, [])
    if index < 0 or index >= len(city_queue):
        return jsonify({"error": "index fora do intervalo"}), 400

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
                if 0 <= s < e <= 24:
                    settings["activeHours"] = {"start": s, "end": e}
            except (ValueError, TypeError):
                pass
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
    try:
        from_idx = int(body.get("fromIndex", -1))
        to_idx   = int(body.get("toIndex",   -1))
    except (ValueError, TypeError):
        return jsonify({"error": "fromIndex/toIndex inválidos"}), 400

    data = _load_building_queue()
    city_queue = data.get("queues", {}).get(city_name, [])
    n = len(city_queue)
    if not (0 <= from_idx < n and 0 <= to_idx < n) or from_idx == to_idx:
        return jsonify({"error": "índices inválidos"}), 400

    item = city_queue.pop(from_idx)
    city_queue.insert(to_idx, item)
    data["queues"][city_name] = city_queue
    _save_building_queue(data)
    return jsonify({"ok": True, "queue": city_queue})


@app.route("/api/telegram-settings", methods=["GET"])
def api_telegram_settings_get():
    data = {"botToken": "", "chatId": ""}
    if os.path.exists(TELEGRAM_SETTINGS_PATH):
        try:
            with open(TELEGRAM_SETTINGS_PATH) as f:
                saved = json.load(f)
            data["botToken"] = saved.get("botToken", "")
            data["chatId"] = saved.get("chatId", "")
        except Exception:
            pass
    if not data["botToken"]:
        data["botToken"] = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not data["chatId"]:
        data["chatId"] = os.getenv("TELEGRAM_CHAT_ID", "")
    return jsonify(data)


@app.route("/api/telegram-settings", methods=["POST"])
def api_telegram_settings_save():
    body = request.get_json(force=True) or {}
    data = {
        "botToken": str(body.get("botToken", "")).strip(),
        "chatId":   str(body.get("chatId", "")).strip(),
    }
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(TELEGRAM_SETTINGS_PATH, "w") as f:
        json.dump(data, f)
    return jsonify({"ok": True})


@app.route("/api/telegram-settings/test", methods=["POST"])
def api_telegram_settings_test():
    try:
        import telegram_notifier as _tg
        _tg._send("🤖 Teste de notificação Telegram — ikabot dashboard")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/espionage/spy-counts")
def api_espionage_spy_counts():
    """
    Return spy counts per city.
    Primary source: spy_counts.json written by fetch_spy_counts() from the bot.
    Fallback: compute deployed count from TRAVELING missions.
    """
    # Merge in-field counts from missions (always accurate)
    in_field: dict[str, int] = {}
    try:
        with open(SPY_MISSIONS_PATH) as f:
            missions = json.load(f).get("missions", [])
        for m in missions:
            if m.get("state") == "TRAVELING":
                cid = str(m.get("originCityId", ""))
                in_field[cid] = in_field.get(cid, 0) + m.get("numAgents", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

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


@app.route("/api/espionage/missions")
def api_espionage_missions():
    try:
        with open(SPY_MISSIONS_PATH) as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"missions": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/own-cities")
def api_own_cities():
    try:
        with open(os.path.join(LOGS_DIR, "own_cities.json")) as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/world-scan/settings")
def api_world_scan_settings_get():
    try:
        with open(WORLD_SCAN_SETTINGS_PATH) as f:
            return jsonify(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({"enabled": True})


@app.route("/api/world-scan/settings", methods=["POST"])
def api_world_scan_settings_post():
    body = request.get_json(silent=True) or {}
    settings = {"enabled": bool(body.get("enabled", True))}
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(WORLD_SCAN_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
    return jsonify({"ok": True})


@app.route("/api/espionage/settings")
def api_espionage_settings_get():
    try:
        with open(ESPIONAGE_SETTINGS_PATH) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = dict(_DEFAULT_ESPIONAGE_SETTINGS)
    data.setdefault("processingEnabled", True)
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
    if "processingEnabled" in body:
        existing["processingEnabled"] = bool(body["processingEnabled"])
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(ESPIONAGE_SETTINGS_PATH, "w") as f:
        json.dump(existing, f, indent=2)
    return jsonify({"ok": True})


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

_DEFAULT_CONSOLIDATE_SETTINGS = {
    "enabled":       False,
    "destCityId":    "",
    "destCityName":  "",
    "intervalHours": 6,
    "minSendTotal":  1000,
    "shipType":      "transporters",  # transporters | freighters | both
}


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
    try:
        with open(CONSOLIDATE_SETTINGS_PATH) as f:
            settings = json.load(f)
        for k, v in _DEFAULT_CONSOLIDATE_SETTINGS.items():
            settings.setdefault(k, v)
    except (FileNotFoundError, json.JSONDecodeError):
        settings = dict(_DEFAULT_CONSOLIDATE_SETTINGS)
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
    settings = dict(_DEFAULT_CONSOLIDATE_SETTINGS)
    settings["enabled"]       = bool(data.get("enabled", False))
    settings["destCityId"]    = str(data.get("destCityId", ""))
    settings["destCityName"]  = str(data.get("destCityName", ""))
    settings["intervalHours"] = max(1, min(48, int(data.get("intervalHours", 6))))
    settings["minSendTotal"]  = max(0, int(data.get("minSendTotal", 1000)))
    ship_type = data.get("shipType", "transporters")
    settings["shipType"] = ship_type if ship_type in ("transporters", "freighters", "both") else "transporters"
    if settings["enabled"] and not settings["destCityId"]:
        return jsonify({"error": "Cidade de destino obrigatória"}), 400
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(CONSOLIDATE_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
    return jsonify({"status": "ok", "settings": settings})


@app.route("/api/farm")
def api_farm_list():
    if not _db:
        return jsonify([])
    try:
        return jsonify(_db.farm_list())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


FARM_SETTINGS_PATH = os.path.join(LOGS_DIR, "farm_settings.json")


def _load_farm_settings():
    try:
        with open(FARM_SETTINGS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


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
    })


@app.route("/api/farm/army", methods=["POST"])
def api_farm_army_set():
    data = request.get_json(silent=True) or {}
    army = data.get("army", {})
    try:
        clean = {str(k): int(v) for k, v in army.items() if int(v) > 0}
    except (ValueError, TypeError):
        return jsonify({"error": "loadout inválida"}), 400
    try:
        spy_agents = max(1, min(99, int(data.get("spyAgents", 1))))
    except (ValueError, TypeError):
        spy_agents = 1
    # Merge so the ship-reserve keys (and any future settings) survive an army save.
    s = _load_farm_settings()
    s["army"] = clean
    s["spyAgents"] = spy_agents
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
    with open(FARM_SETTINGS_PATH, "w") as f:
        json.dump(s, f, indent=2)
    return jsonify({"ok": True, **{k: s[k] for k in
                    ("army", "fleet", "spyAgents", "shipReserveEnabled", "reserveHorizonMin",
                     "earlyRespyEnabled") if k in s}})


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
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


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
    if "maxEnemyShips" in data:  fields["max_enemy_ships"] = max(0, int(data["maxEnemyShips"]))
    if "respyEvery" in data:     fields["respy_every"] = max(1, min(50, int(data["respyEvery"])))
    if "fleetLeadMin" in data:   fields["fleet_lead_min"] = max(1, min(120, int(data["fleetLeadMin"])))
    if "disperseMin" in data:    fields["disperse_min"] = max(1, min(1440, int(data["disperseMin"])))
    # Manual reset back to IDLE/now so the next cycle re-runs immediately
    if data.get("runNow"):
        fields["state"] = "IDLE"
        fields["next_run_at"] = 0
    try:
        _db.farm_update(tid, fields)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
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
    with open(ALERT_SETTINGS_PATH, "w") as f:
        json.dump(s, f, indent=2)
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
    with open(WATCHLIST_SETTINGS_PATH, "w") as f:
        json.dump(s, f, indent=2)
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
        return jsonify(_db.get_loot_stats())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


WINE_SETTINGS_PATH = os.path.join(LOGS_DIR, "wine_settings.json")
_DEFAULT_WINE_SETTINGS = {"enabled": False, "thresholdHours": 12, "targetHours": 48}


@app.route("/api/transport/wine")
def api_wine_get():
    try:
        with open(WINE_SETTINGS_PATH) as f:
            s = json.load(f)
        for k, v in _DEFAULT_WINE_SETTINGS.items():
            s.setdefault(k, v)
    except (FileNotFoundError, json.JSONDecodeError):
        s = dict(_DEFAULT_WINE_SETTINGS)
    return jsonify(s)


@app.route("/api/transport/wine", methods=["POST"])
def api_wine_post():
    data = request.get_json(silent=True) or {}
    s = dict(_DEFAULT_WINE_SETTINGS)
    s["enabled"]        = bool(data.get("enabled", False))
    s["thresholdHours"] = max(1, min(168, int(data.get("thresholdHours", 12))))
    s["targetHours"]    = max(s["thresholdHours"], min(336, int(data.get("targetHours", 48))))
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(WINE_SETTINGS_PATH, "w") as f:
        json.dump(s, f, indent=2)
    return jsonify({"status": "ok", "settings": s})


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
    }
    try:
        _db.queue_add("attack", item)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "queued", "item": item})


@app.route("/api/espionage/attack-queue/cancel", methods=["POST"])
def api_attack_queue_cancel():
    data = request.get_json(silent=True) or {}
    attack_id = data.get("id")
    if not attack_id:
        return jsonify({"error": "id obrigatório"}), 400
    if not _db:
        return jsonify({"error": "Base de dados indisponível"}), 503
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
    }
    try:
        _db.queue_add("attack", item)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "queued", "item": item})


@app.route("/api/espionage/attack-waves")
def api_attack_waves_get():
    try:
        with open(AUTO_ATTACK_WAVES_PATH) as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"waves": []})


@app.route("/api/espionage/attack-waves/cancel", methods=["POST"])
def api_attack_waves_cancel():
    data = request.get_json(silent=True) or {}
    wave_id = data.get("id")
    if not wave_id:
        return jsonify({"error": "id obrigatório"}), 400
    try:
        with open(AUTO_ATTACK_WAVES_PATH) as f:
            waves_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({"error": "Sem planos de ataque"}), 404
    original = len(waves_data.get("waves", []))
    waves_data["waves"] = [w for w in waves_data.get("waves", []) if w.get("id") != wave_id]
    if len(waves_data["waves"]) == original:
        return jsonify({"error": "Plano não encontrado"}), 404
    with open(AUTO_ATTACK_WAVES_PATH, "w") as f:
        json.dump(waves_data, f, indent=2)
    return jsonify({"status": "cancelled"})


@app.route("/api/espionage/auto-attack-settings")
def api_auto_attack_settings_get():
    try:
        with open(AUTO_ATTACK_SETTINGS_PATH) as f:
            s = json.load(f)
            for k, v in _DEFAULT_AUTO_ATTACK_SETTINGS.items():
                s.setdefault(k, v)
            return jsonify(s)
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify(_DEFAULT_AUTO_ATTACK_SETTINGS)


@app.route("/api/espionage/auto-attack-settings", methods=["POST"])
def api_auto_attack_settings_post():
    data = request.get_json(silent=True) or {}
    settings = dict(_DEFAULT_AUTO_ATTACK_SETTINGS)
    settings["enabled"]               = bool(data.get("enabled", False))
    settings["minLootTotal"]          = int(data.get("minLootTotal", 50000))
    settings["lootPerWave"]           = int(data.get("lootPerWave", 195000))
    settings["battleDelayFewMins"]    = int(data.get("battleDelayFewMins", 30))
    settings["battleDelayMedMins"]    = int(data.get("battleDelayMedMins", 60))
    settings["battleDelayManyMins"]   = int(data.get("battleDelayManyMins", 120))
    settings["maxEnemyShipsToEngage"] = int(data.get("maxEnemyShipsToEngage", 20))
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(AUTO_ATTACK_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
    return jsonify({"status": "ok", "settings": settings})


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
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


@app.route("/api/espionage/force-warehouse", methods=["POST"])
def api_espionage_force_warehouse():
    body    = request.get_json(force=True)
    city_id = str(body.get("cityId", ""))
    if not city_id:
        return jsonify({"error": "cityId required"}), 400

    data     = _load_json(SPY_MISSIONS_PATH, {"missions": []})
    missions = data.get("missions", [])
    now      = int(time.time())
    for i, m in enumerate(missions):
        if str(m.get("targetCityId", "")) != city_id:
            continue
        if m.get("state") == "WAITING_AT_CITY":
            missions[i]["executeAfter"] = now - 1
            data["missions"] = missions
            _save_json(SPY_MISSIONS_PATH, data)
            return jsonify({"ok": True})
        if m.get("state") == "WAITING_FOR_GARRISON":
            missions[i]["garrisonExecuteAfter"] = now - 1
            data["missions"] = missions
            _save_json(SPY_MISSIONS_PATH, data)
            return jsonify({"ok": True})
        if m.get("state") in ("EXECUTING_WAREHOUSE", "EXECUTING_GARRISON"):
            return jsonify({"ok": True, "message": "Missão já em execução"})
        if m.get("state") == "DONE":
            if not m.get("originCityId"):
                # Synthetic imported mission — no real spy stationed, cannot re-execute
                return jsonify({"error": "Missão importada sem espião activo — usa o dispatch normal"}), 400
            missions[i]["state"] = "WAITING_AT_CITY"
            missions[i]["executeAfter"] = now - 1
            missions[i]["garrisonResult"] = None
            missions[i]["garrisonExecutedAt"] = None
            missions[i]["garrisonExecuteAfter"] = None
            data["missions"] = missions
            _save_json(SPY_MISSIONS_PATH, data)
            return jsonify({"ok": True})

    return jsonify({"error": "Nenhum espião estacionado nessa cidade"}), 404


@app.route("/api/espionage/recall-spy", methods=["POST"])
def api_espionage_recall_spy():
    body    = request.get_json(force=True)
    city_id = str(body.get("cityId", ""))
    if not city_id:
        return jsonify({"error": "cityId required"}), 400

    data     = _load_json(SPY_MISSIONS_PATH, {"missions": []})
    missions = data.get("missions", [])
    now      = int(time.time())
    changed  = False
    recallable = {"TRAVELING", "WAITING_AT_CITY", "EXECUTING_WAREHOUSE",
                  "WAITING_FOR_GARRISON", "EXECUTING_GARRISON", "DONE"}
    for i, m in enumerate(missions):
        if str(m.get("targetCityId", "")) != city_id:
            continue
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
    _save_json(SPY_MISSIONS_PATH, data)
    return jsonify({"ok": True})


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
        with open(BOT_LOG_PATH, encoding="utf-8", errors="replace") as f:
            content = f.read().splitlines()
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
    with open(PAUSE_PATH, "w") as f:
        json.dump({"paused": paused}, f)
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
    return jsonify({"status": "ok", "ts": int(time.time()), "dbOk": db_ok})


@app.route("/api/stream")
def api_stream():
    """SSE endpoint — emits 'update' whenever any data file on the shared volume changes."""
    watched = [
        EMPIRE_JSON_PATH, RESOURCES_JSON_PATH, STATUS_SUMMARY_JSON_PATH,
        MOVEMENTS_JSON_PATH, QUEUE_SENTINEL_PATH, NEXT_CYCLE_JSON_PATH,
        LAST_ALIVE_JSON_PATH, WORLD_SCAN_JSON_PATH, WORLD_SCAN_STATUS_PATH,
        AUTO_ATTACK_WAVES_PATH,
    ]

    def generate():
        last_mtimes = {p: os.path.getmtime(p) if os.path.exists(p) else 0 for p in watched}
        yield ": connected\n\n"
        while True:
            time.sleep(2)
            changed = False
            for p in watched:
                mtime = os.path.getmtime(p) if os.path.exists(p) else 0
                if mtime != last_mtimes[p]:
                    last_mtimes[p] = mtime
                    changed = True
            if changed:
                yield "event: update\ndata: {}\n\n"
            else:
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
            if offline_min > 90:
                _tg.notify_bot_offline(offline_min)
            else:
                _tg.clear_bot_offline()
        except Exception:
            pass


if __name__ == "__main__":
    # debug=False: the Werkzeug debugger is an RCE if the port is ever exposed.
    # use_reloader keeps the convenient auto-reload on file changes.
    # WERKZEUG_RUN_MAIN guard: the reloader parent process also imports this module —
    # only the worker child may start the watcher thread (avoids double notifications).
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        import threading
        threading.Thread(target=_offline_watch_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=True, threaded=True)
