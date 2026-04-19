# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Dockerized automation suite for the browser game Ikariam. Extends the open-source [ikabot-collective/ikabot](https://github.com/ikabot-collective/ikabot) bot with a custom empire data collector (`empireFunction.py`) and a Flask/React dashboard (`ikabot_gui/`).

The user runs **13 cities**. All UI text and comments are in **Portuguese**.

## Running the Project

```bash
docker compose up -d          # start both containers
docker compose logs -f        # stream logs
docker compose up -d --build  # rebuild after code changes
docker compose down           # stop
```

**Configuration** (`.env` file):
- `IKABOT_EMAIL` / `IKABOT_PASSWORD` — Ikariam credentials
- `EMPIRE_UPDATE_INTERVAL` — hourly data collection interval in seconds (default: 3600)

**Dashboard:** http://localhost:5001

## Architecture

Two containers communicate via a shared Docker volume (`/tmp/ikalogs/`):

```
Ikariam Game Server
    ↓ (HTTP via ikabot session/helpers)
[ikabot container]
    ├── empireFunction.py main loop — runs every EMPIRE_UPDATE_INTERVAL seconds
    │     writes: statusSummary.json, empire.json, resources.json, movements.json, history.jsonl
    └── _collect_building_costs() thread — runs every 3 days in background
          writes: building_costs.json
    ↓ (shared volume)
[ikabot-gui container] — Flask on port 5001
    ↓ (REST API)
[React SPA — templates/index.html]
```

### Key Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Orchestrates containers and shared volume |
| `empireFunction.py` | Custom collector — main loop + building costs thread |
| `planRoutes_patched.py` | Patched version of ikabot's transport helper — adds human-like delays between fleet dispatches |
| `ikabot_gui/app.py` | Flask REST API |
| `ikabot_gui/templates/index.html` | Single-file React SPA (no build step, CDN deps) |
| `ikabot/ikabot/helpers/` | HTTP, parsing, game API helpers |
| `ikabot/ikabot/function/constructionList.py` | Source of `getCostsReducers` and `checkhash`, imported by `empireFunction.py` |
| `ikabot/ikabot/config.py` | Game constants: `materials_names`, `materials_names_tec`, `materials_names_english` |

### Data Files in `/tmp/ikalogs/`

| File | Updated | Purpose |
|------|---------|---------|
| `statusSummary.json` | Every hour | Empire-wide gold, ships, housing, production |
| `empire.json` | Every hour | Buildings + construction status per city |
| `resources.json` | Every hour | Resources per city with wine timers |
| `movements.json` | Every hour | Active fleet/army movements |
| `history.jsonl` | Every hour | Timestamped snapshots (max 2160 lines ≈ 90 days) |
| `building_costs.json` | Every 3 days | Upgrade costs per building per level per city |
| `.force_costs_update` | On demand | Flag file — triggers early building costs refresh |

### Flask API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/data` | GET | Empire status, buildings, resources |
| `/api/movements` | GET | Active movements |
| `/api/history` | GET | Last 7 days of hourly snapshots |
| `/api/building-costs` | GET | Upgrade costs per building per level per city |
| `/api/building-costs/refresh` | POST | Creates `.force_costs_update` flag to trigger early refresh |

### Frontend Tabs

Home, Cidades, Edifícios, Movimentos, Alertas, Histórico, Calculadoras.

**Calculadoras** has two sub-tabs:
- **Evolução de Edifícios** — selects city/building/target level, auto-fills costs from `/api/building-costs`, then estimates time to gather resources using empire production
- **ROI Serraria / Pedreira** — compares island vs city building ROI

## Building Costs Collection (`_collect_building_costs`)

Runs as a background daemon thread every 3 days (or when `.force_costs_update` flag exists). Uses **random delays to simulate human behaviour** — this is intentional anti-detection:
- **15–30s between cities**
- **5–15s between buildings within a city**

Per city: 1 HTTP request for the shared building detail HTML + 1 for research reduction (cached in session after first call) + 1 per non-max building for the cost table.

Imports `getCostsReducers` and `checkhash` from `ikabot/ikabot/function/constructionList.py`.

`building_costs.json` structure:
```json
{
  "lastUpdated": 1713456789,
  "cities": {
    "Lisboa": {
      "Academia": {
        "currentLevel": 12,
        "costs": {
          "13": {"wood": 45000, "wine": 0, "marble": 12000, "glass": 0, "sulfur": 0},
          "14": {"wood": 58000, "wine": 0, "marble": 16000, "glass": 0, "sulfur": 0}
        }
      }
    }
  }
}
```

Each level entry is the cost for that individual level (not cumulative). The frontend sums them for multi-level upgrades.

## Critical: Resource Name Mapping

Three different naming systems exist — always be aware of which context you're in:

| Index | `materials_names` (PT) | `materials_names_english` | `materials_names_tec` (API/costs keys) |
|-------|----------------------|--------------------------|----------------------------------------|
| 0 | Madeira | Wood | `wood` |
| 1 | Vinho | Wine | `wine` |
| 2 | Mármore | Marble | `marble` |
| 3 | Cristal | Crystal | `glass` ← different! |
| 4 | Enxofre | Sulfur | `sulfur` |

The frontend `MATERIALS` array uses `en` field matching `materials_names_english`. The `building_costs.json` uses `materials_names_tec` keys. In the frontend, `COST_KEYS = ['wood', 'wine', 'marble', 'glass', 'sulfur']` maps index-to-key.

## Development Notes

- **ikabot submodule:** `ikabot/` is excluded from git (`.gitignore`). `empireFunction.py` and `planRoutes_patched.py` are injected at runtime via Docker volume mounts — no `--build` needed when editing them.
- **Upstream patches via volume mount:** When an ikabot core file needs fixing (e.g., missing anti-detection delays), create a patched copy at the repo root and add a volume mount in `docker-compose.yml` pointing to the correct path inside the container (e.g., `./planRoutes_patched.py:/ikabot/ikabot/helpers/planRoutes.py`). Do NOT modify files inside `ikabot/` directly.
- **Frontend changes:** Edit `templates/index.html` directly — no build step. Refresh browser.
- **Backend changes:** `docker compose up -d --build` after editing `app.py`. Volume-mounted files (`empireFunction.py`, `planRoutes_patched.py`) take effect with just `docker compose up -d`.
- **Anti-detection:** Any new code that makes HTTP requests to the game server **must use random delays** (`time.sleep(random.randint(...))`) between requests to simulate human behaviour. Never batch requests without pauses. Reference delays by context:
  - Main hourly loop: 5–15s between cities, 2–6s between two requests within each city, 5–10s before movements request, ±5 min jitter on cycle (`UPDATE_INTERVAL + random.randint(-300, 300)`)
  - Building costs collection: 15–30s between cities, 5–15s between buildings within a city
  - Transport routes (`planRoutes_patched.py`): 3–7s between `changeCurrentCity` and `loadTransportersWithFreight`, 10–25s between consecutive fleets on the same route, 12–30s between distinct routes
- **Thread safety:** `_costs_running` is a `threading.Event()` used to prevent duplicate cost-collection threads. Always check `.is_set()` before starting, and `.clear()` in a `finally` block when done.
- **Ikabot session:** The `session` object passed to `empireFunction` supports `.get()`, `.post()`, `.getSessionData()`, `.setSessionData()`. Session data can be used to cache per-session values (e.g., research reduction is cached as `reduccion_inv_max`).
