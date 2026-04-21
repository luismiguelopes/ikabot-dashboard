from flask import Flask, render_template, jsonify, request
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
FORCE_WORLD_SCAN_FLAG   = os.path.join(LOGS_DIR, ".force_world_scan")


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

    elapsed = int(time.time() - get_last_modified_ts(RESOURCES_JSON_PATH))
    for city_data in resources_data.values():
        t = city_data.get('wineRunsOutIn')
        if t is not None and t != -1:
            city_data['wineRunsOutIn'] = max(0, t - elapsed)

    return {
        "empireData":    empire_data,
        "statusSummary": status_summary,
        "resourcesData": resources_data,
        "lastUpdated":   get_last_modified_date(EMPIRE_JSON_PATH),
        "lastUpdatedTs": get_last_modified_ts(EMPIRE_JSON_PATH),
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
        player["mark"] = marks.get(mk, {}).get("status", "novo")
        player["markNote"] = marks.get(mk, {}).get("note", "")
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
    marks[mark_key] = {"status": status, "note": note, "updatedAt": int(time.time())}
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(PLAYER_MARKS_JSON_PATH, "w") as f:
        json.dump(marks, f, indent=2)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
