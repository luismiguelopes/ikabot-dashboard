from flask import Flask, render_template, jsonify, request, Response, stream_with_context
import json
import os
import time

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
BUILDING_QUEUE_JSON_PATH = os.path.join(LOGS_DIR, "building_queue.json")
NEXT_CYCLE_JSON_PATH    = os.path.join(LOGS_DIR, "next_cycle.json")
LAST_ALIVE_JSON_PATH    = os.path.join(LOGS_DIR, "last_alive.json")
EMPIRE_SCAN_STATUS_PATH = os.path.join(LOGS_DIR, "empire_scan_status.json")


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

    # Patch empire_data with inProgress from building_queue.json so constructions
    # started by the queue processor are visible before the next full cycle writes
    # empire.json (which only happens hourly).
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

    elapsed = int(time.time() - get_last_modified_ts(RESOURCES_JSON_PATH))
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

    return {
        "empireData":    empire_data,
        "statusSummary": status_summary,
        "resourcesData": resources_data,
        "lastUpdated":   get_last_modified_date(EMPIRE_JSON_PATH),
        "lastUpdatedTs": get_last_modified_ts(EMPIRE_JSON_PATH),
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


@app.route("/api/history")
def api_history():
    """Return the last 168 history entries (≈7 days at 1h interval)."""
    if not os.path.exists(HISTORY_JSONL_PATH):
        return jsonify([])
    with open(HISTORY_JSONL_PATH) as f:
        lines = f.readlines()
    entries = []
    for line in lines[-168:]:
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    return jsonify(entries)


@app.route("/api/building-costs")
def api_building_costs():
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
        return jsonify(json.load(f))


@app.route("/api/world-scan")
def api_world_scan():
    if not os.path.exists(WORLD_SCAN_JSON_PATH):
        return jsonify({"error": "world_scan.json não encontrado. Aguarda o primeiro scan semanal ou força um."}), 404
    with open(WORLD_SCAN_JSON_PATH) as f:
        scan = json.load(f)
    marks = {}
    if os.path.exists(PLAYER_MARKS_JSON_PATH):
        with open(PLAYER_MARKS_JSON_PATH) as f:
            marks = json.load(f)
    # Build set of player IDs that were already inactive in the previous scan
    prev_inactive_ids = set()
    if os.path.exists(WORLD_SCAN_PREV_PATH):
        with open(WORLD_SCAN_PREV_PATH) as f:
            prev = json.load(f)
        prev_inactive_ids = {p["playerId"] for p in prev.get("players", [])}
    for player in scan.get("players", []):
        pid = player["playerId"]
        mk = f"{pid}_{player.get('islandX', '')}_{player.get('islandY', '')}"
        entry = marks.get(mk, {})
        player["mark"] = entry.get("status", "novo")
        player["markNote"] = entry.get("note", "")
        player["markActions"] = entry.get("actions", [])
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
    mark_key  = f"{player_id}_{island_x}_{island_y}"
    status = body.get("status", "novo")
    note = body.get("note", "")
    if status not in ("novo", "visto", "alvo", "ignorar"):
        return jsonify({"error": "Status inválido"}), 400
    marks = {}
    if os.path.exists(PLAYER_MARKS_JSON_PATH):
        with open(PLAYER_MARKS_JSON_PATH) as f:
            marks = json.load(f)
    existing = marks.get(mark_key, {})
    marks[mark_key] = {
        "status": status,
        "note": note,
        "updatedAt": int(time.time()),
        "actions": existing.get("actions", []),
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
    marks = {}
    if os.path.exists(PLAYER_MARKS_JSON_PATH):
        with open(PLAYER_MARKS_JSON_PATH) as f:
            marks = json.load(f)
    entry = marks.setdefault(mark_key, {"status": "novo", "note": "", "updatedAt": int(time.time()), "actions": []})
    entry.setdefault("actions", []).append({"ts": int(time.time()), "text": text})
    entry["updatedAt"] = int(time.time())
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(PLAYER_MARKS_JSON_PATH, "w") as f:
        json.dump(marks, f, indent=2)
    return jsonify({"ok": True})


def _load_building_queue():
    if not os.path.exists(BUILDING_QUEUE_JSON_PATH):
        return {"queues": {}, "inProgress": {}}
    with open(BUILDING_QUEUE_JSON_PATH) as f:
        return json.load(f)


def _save_building_queue(data):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(BUILDING_QUEUE_JSON_PATH, "w") as f:
        json.dump(data, f, indent=2)


@app.route("/api/building-queue")
def api_building_queue():
    return jsonify(_load_building_queue())


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


@app.route("/api/building-queue/enabled", methods=["POST"])
def api_building_queue_enabled():
    body = request.get_json(force=True) or {}
    enabled = bool(body.get("enabled", True))
    data = _load_building_queue()
    data["enabled"] = enabled
    _save_building_queue(data)
    return jsonify({"ok": True, "enabled": enabled})


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


@app.route("/api/stream")
def api_stream():
    """SSE endpoint — emits 'update' whenever any data file on the shared volume changes."""
    watched = [
        EMPIRE_JSON_PATH, RESOURCES_JSON_PATH, STATUS_SUMMARY_JSON_PATH,
        MOVEMENTS_JSON_PATH, BUILDING_QUEUE_JSON_PATH, NEXT_CYCLE_JSON_PATH,
        LAST_ALIVE_JSON_PATH,
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
