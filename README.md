# Ikabot Docker Setup

A Dockerized setup for [ikabot](https://github.com/ikabot-collective/ikabot) — an automation bot for the browser game Ikariam — extended with a custom empire data collector, a SQLite database, and a React/TypeScript web dashboard.

## Overview

Three containers run side by side and share a Docker volume (`ikalogs_volume`):

| Container | Description |
|---|---|
| `ikabot` | Runs the ikabot automation bot with custom modules injected via volume mounts |
| `ikabot-gui` | Flask REST API + SSE stream (internal port 5000) |
| `frontend` | Vite dev server serving the React/TypeScript SPA on port 5001, proxying `/api/*` to `ikabot-gui` |

### How it works

`empireFunction.py` runs as a background process inside the ikabot container. Every hour (configurable) it:

1. Writes `last_alive.json` at the very start of each iteration — if the process crashes mid-cycle this timestamp goes stale and the dashboard shows a "Bot offline" warning after 90 minutes.
2. Decides whether to run a **full empire cycle** based on `SCAN_ACTIVE_HOURS`:
   - Within active hours: runs every `EMPIRE_UPDATE_INTERVAL` (default 1h ± 5 min jitter)
   - Outside active hours: runs every `SCAN_NIGHT_INTERVAL` (default 4h) — reduces nightly HTTP activity to a heartbeat scan
3. On a full cycle, collects per-city data: resources, building levels, production rates, wine status, gold. Cities are visited in a **randomised order** each cycle.
4. Fetches military and fleet movements from the military advisor endpoint.
5. Persists everything to the shared SQLite database (`ikabot.db`) and writes JSON files to the shared volume.
6. Persists everything to the shared SQLite database (`ikabot.db`) via `finalize_empire_cycle()`.
7. Processes the building queue immediately after the empire data is fresh (before any long scan starts).
8. Then, one of the following runs (mutually exclusive, strictly sequential):
   - If building costs are due (every 3 days, or `.force_costs_update` flag) → `collect_building_costs()`
   - Else if world scan is due (every 7 days, or `.force_world_scan` flag) → `collect_world_scan()`
9. Calculates the next wake-up time as the earliest of: next full cycle, next construction ETA, or next transport fleet arrival. Writes it to `next_cycle.json`. The sidebar countdown is derived from this value.

**Building queue** — when processing the queue, for each city:
- Checks if a tracked in-progress construction has completed.
- If the city is free, attempts to start the next item in the queue.
- If resources are insufficient, calls `_try_transport()`: calculates missing resources (respecting per-resource buffers), identifies surplus source cities (after reserving their own queue costs), and dispatches one bundled transport fleet per source city with all needed resources. Freighters are used only when total need exceeds 8 transporter ship-loads.
- If multiple buildings of the same type exist (e.g. two warehouses), the lowest-level instance below the target is always chosen. The queue item is only removed when **all** instances have reached the target level.
- Transport dispatch verifies the server response (`type == 10`). Failures are recorded in `transportErrors` and surfaced in the UI as an orange warning banner.
- If any transport was dispatched, `movements.json` is immediately re-fetched so fleet arrival ETAs are visible to the sleep scheduler.

**Anti-detection** — all HTTP requests to the game server use randomised delays to simulate human browsing patterns:
- Cities are visited in a random order on each cycle.
- A 3–10s orientation pause precedes the first request of each cycle.
- 5–15s between cities during empire collection; 2–6s between the two requests per city.
- 15–30s between cities during building costs collection; 3–8s between city GET and detail POST; 2–6s before the research reduction POST; 5–15s between buildings within a city.
- 2–5s between quadrant requests during the world scan shallow phase; 15–30s between island requests in the deep phase.
- 3–7s between `changeCurrentCity` and `loadTransportersWithFreight`; 12–30s between consecutive transport fleets.
- `SCAN_ACTIVE_HOURS` suppresses the full empire scan outside a configurable time window, eliminating the most obvious bot signal (regular hourly HTTP activity at 3 AM).

The `ikabot-gui` Flask app reads from SQLite and exposes REST endpoints and a Server-Sent Events stream (`/api/stream`). The SSE stream pushes live updates to the browser within ~2 seconds of any data file changing. The `frontend` Vite dev server (port 5001) proxies all `/api/*` requests to Flask and hot-reloads on file changes.

## Requirements

- Docker and Docker Compose
- An Ikariam account

## Setup

1. Clone this repository.
2. Create a `.env` file in the project root (never commit this file):

```env
IKABOT_EMAIL=your_email@example.com
IKABOT_PASSWORD=your_password

# Optional — shown with defaults
EMPIRE_UPDATE_INTERVAL=1h
BUILDING_COSTS_UPDATE_INTERVAL=3d
WORLD_SCAN_UPDATE_INTERVAL=7d
WORLD_SCAN_RADIUS=10
QUEUE_ACTIVE_HOURS=8-23
SCAN_ACTIVE_HOURS=8-23
SCAN_NIGHT_INTERVAL=4h
LOG_LANG=en
```

3. Start the containers:

```bash
docker compose up -d
```

4. Open the dashboard at [http://localhost:5001](http://localhost:5001).

## Configuration

Duration variables accept `Nd` (days), `Nh` (hours), `Nm` (minutes), `Ns` (seconds), or a plain integer (seconds).

| Variable | Default | Description |
|---|---|---|
| `IKABOT_EMAIL` | — | Ikariam account email |
| `IKABOT_PASSWORD` | — | Ikariam account password |
| `EMPIRE_UPDATE_INTERVAL` | `1h` | Interval between full empire data cycles (within active scan hours) |
| `BUILDING_COSTS_UPDATE_INTERVAL` | `3d` | Interval between building cost refreshes |
| `WORLD_SCAN_UPDATE_INTERVAL` | `7d` | Interval between world scans |
| `WORLD_SCAN_RADIUS` | `10` | Max tile distance from own cities included in the world scan |
| `QUEUE_ACTIVE_HOURS` | *(all hours)* | Hours during which the queue may **start constructions and dispatch transports** — format `H-H`, e.g. `8-23` |
| `SCAN_ACTIVE_HOURS` | *(all hours)* | Hours during which the bot runs **full empire scans** at the normal interval. Outside this window it scans at `SCAN_NIGHT_INTERVAL` instead. Format `H-H`, e.g. `8-23`. Unset = 24h operation |
| `SCAN_NIGHT_INTERVAL` | `4h` | Scan frequency outside `SCAN_ACTIVE_HOURS`. Keeps data roughly fresh overnight without hourly HTTP activity |
| `WINE_CRITICAL_NOTIFY_HOURS` | `2h` | Wine-critical Telegram alert threshold in hours |
| `LOG_LANG` | `en` | Backend log language (`en` or `pt`) |

## Docker Commands

```bash
docker compose up -d          # start all containers
docker compose logs -f        # stream logs from all containers
docker compose up -d --build  # rebuild after editing ikabot_gui/app.py or adding npm packages
docker compose down           # stop all containers
```

Volume-mounted files (`empireFunction.py` and all sibling modules, `planRoutes_patched.py`) take effect immediately — no rebuild needed.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/data` | GET | Empire-wide status, buildings, resources — includes `lastUpdatedTs`, `nextCycleAt`, `lastAlive` |
| `/api/data/refresh` | POST | Creates `.force_empire_update` flag — bot wakes immediately and runs a full cycle |
| `/api/data/status` | GET | Live per-city scan progress `{status, phase, progress, total, message}` |
| `/api/movements` | GET | Current fleet and army movements |
| `/api/movements/refresh` | POST | Creates `.force_movements_update` flag — bot refreshes movements on next wake |
| `/api/history` | GET | Last 7 days of hourly empire snapshots |
| `/api/history?city=Name` | GET | Last 7 days of per-city resource and wine timer history |
| `/api/history/cities` | GET | List of cities that have history data |
| `/api/building-costs` | GET | Upgrade costs per building per level per city |
| `/api/building-costs/refresh` | POST | Schedules an early building costs refresh |
| `/api/world-scan` | GET | Inactive/vacation players near own cities, with marks and action logs merged |
| `/api/world-scan/status` | GET | Current scan progress |
| `/api/world-scan/refresh` | POST | Schedules an early world scan |
| `/api/world-scan/mark` | POST | Save a player mark (`novo`/`visto`/`alvo`/`ignorar`) and note |
| `/api/world-scan/action` | POST | Append a timestamped action log entry for a player |
| `/api/building-queue` | GET | Current queue, in-progress construction, transport errors, `enabled` flag, and settings per city |
| `/api/building-queue/add` | POST | Add a building upgrade `{cityName, buildingName, targetLevel}` to the queue |
| `/api/building-queue/remove` | POST | Remove item `{cityName, index}` from the queue |
| `/api/building-queue/reorder` | POST | Reorder item `{cityName, fromIndex, toIndex}` in the queue |
| `/api/building-queue/clear` | POST | Clear queue for one city `{cityName}` or all cities (no body) |
| `/api/building-queue/enabled` | POST | Enable or pause the queue `{enabled: bool}` |
| `/api/building-queue/settings` | POST | Save queue settings `{activeHours: {start, end}, resourceBuffer: [5]}` |
| `/api/telegram-settings` | GET | Read saved Telegram bot token and chat ID |
| `/api/telegram-settings` | POST | Save Telegram credentials `{botToken, chatId}` to `/tmp/ikalogs/telegram_settings.json` |
| `/api/telegram-settings/test` | POST | Send a test message using the currently saved credentials |
| `/api/health` | GET | Liveness check — `{"status": "ok", "ts": timestamp, "dbOk": bool}` |

## Dashboard Tabs

The dashboard defaults to **English**. A toggle in the sidebar footer switches to Portuguese — preference saved in `localStorage`.

| Tab | Description |
|---|---|
| **Home** | Empire-wide summary: gold, ships, population. Active constructions card (in progress / waiting for resources / queued). Wine balance card (cities at risk with warning/critical pills). Resource balance matrix (cities × resources vs. queue reservations, green/yellow/red). Gold runway estimate |
| **Cities** | Per-city resources, production rates, wine timers. Force-refresh button triggers a live bot cycle with per-city progress bar |
| **Buildings** | Building levels and active constructions per city. "+" button per row adds to the queue. Force-refresh with live progress |
| **Movements** | Active fleet and army movements with live countdown timers. Refresh button requests an immediate re-fetch from the game |
| **Alerts** | Wine-running-out (warning + critical), storage overflow, negative gold, all ships busy. Thresholds configurable inline — persisted in `localStorage` |
| **History** | Empire-wide charts (gold, resources, ships, population) over the last 7 days. City selector switches to per-city view: resources (5 lines) and wine timer (hours until empty) |
| **Calculators** | **Building Upgrade**: city/building/level selector, auto-fills costs, estimates time to gather. **ROI Sawmill/Quarry**: island vs city building comparator. **Colony ROI**: current island vs new colony — pre-fillable from the Islands tab |
| **Construction** | Building upgrade queue manager. **Queue** sub-tab: enabled/paused toggle, bulk-clear, city pills, building list, per-city queue panel with drag-to-reorder, inProgress ETA countdown, transport error banner, queue budget summary. **Template** sub-tab: set target levels per building type and apply to all cities at once |
| **World** | **Inactive**: inactive/vacation players near own cities — sortable by distance/scores, marks (novo/visto/alvo/ignorar), expandable rows with editable note and timestamped action log. Highlights newly inactive players (not seen in previous scan). **Islands**: nearby islands ranked by free slots, resource/wonder levels, "Use in Calc." button |
| **Settings** | **General**: language, default tab. **Alerts**: wine warning/critical thresholds, storage threshold. **Construction**: active hours window, per-resource buffer minimums. **Notifications**: browser notifications toggle; Telegram bot token and chat ID configuration with a live test button |

## Data Storage

All persistent data is stored in two places on the shared volume (`/tmp/ikalogs/`):

**SQLite database** (`ikabot.db`) — primary data store, managed by `db_manager.py`:

| Table | Contents |
|---|---|
| `history` | Hourly empire-wide snapshots (gold, ships, resources, population) |
| `history_cities` | Hourly per-city resource and wine timer snapshots |
| `building_costs` | Upgrade costs per city/building/level |
| `building_costs_meta` | Current level and last-updated timestamp per building |
| `marks` | Player marks (status, note, last updated) |
| `mark_actions` | Timestamped action log entries per player |
| `queue_items` | Building queue entries per city |
| `queue_in_progress` | Active constructions per city |
| `queue_transport_errors` | Latest transport failure per city |
| `queue_state` | Queue enabled/paused flag |
| `empire_meta` | Key-value store: latest empire snapshot, costs timestamp, scan timestamp |

**JSON files** — written for operational signalling and read by the Flask layer:

| File | Updated | Contents |
|---|---|---|
| `statusSummary.json` | Every cycle | Empire-wide totals |
| `empire.json` | Every cycle | Building levels per city |
| `resources.json` | Every cycle | Resources and wine timers per city |
| `movements.json` | Every cycle + on dispatch | Active fleet/army movements |
| `own_cities.json` | Every cycle | Island coordinates of own cities |
| `world_scan.json` | Every 7 days | Inactive players and island summaries |
| `world_scan_prev.json` | Every 7 days | Previous scan — used to detect newly inactive players |
| `next_cycle.json` | Each sleep | Exact timestamp of next wake-up |
| `last_alive.json` | Each loop iteration | `{lastAlive, cycle}` — stale if bot crashes |
| `empire_scan_status.json` | During force-refresh | Per-city scan progress |
| `world_scan_status.json` | During world scan | Scan phase progress |
| `telegram_settings.json` | On save via UI | Telegram bot token and chat ID |
| `.queue_updated` | On each queue change | Sentinel touched on every queue write — SSE watches this |

## Project Structure

```
.
├── docker-compose.yml
├── empireFunction.py        # Main loop orchestrator (~120 lines)
├── empire_utils.py          # Constants, duration parser, i18n log strings, with_retry(), shared logger
├── empire_collector.py      # City data collection, movements fetch
├── costs_collector.py       # Building costs collection (every 3 days)
├── scan_collector.py        # World scan (every 7 days)
├── queue_processor.py       # Building queue: transport dispatch, smart sleep, city shuffling
├── db_manager.py            # SQLite layer: schema init, CRUD, migrations from JSON
├── planRoutes_patched.py    # Patched transport helper with anti-detection delays
├── telegram_notifier.py     # Telegram Bot API notifications
├── tests/
│   ├── test_db.py           # DB CRUD unit tests (13 tests)
│   └── test_queue.py        # Queue pure-function unit tests (13 tests)
├── ikabot_gui/
│   └── app.py               # Flask REST API + SSE stream
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # Root: SSE EventSource, tab routing, LangContext
│   │   ├── types.ts         # TypeScript interfaces for all API data
│   │   ├── i18n.tsx         # EN/PT translations + useT, useLang hooks
│   │   ├── utils.ts         # Formatting helpers (fmt, fmtTime, fmtTs, exportCsv…)
│   │   ├── constants.ts     # MATERIALS, COST_KEYS, resource icons/colours
│   │   ├── hooks/           # useNotifications
│   │   └── components/      # One file per tab/feature
│   ├── vite.config.ts       # Proxy /api/* → ikabot-gui:5000
│   └── package.json
└── .env                     # Credentials — never commit this
```

## Running Tests

```bash
.venv/bin/pytest tests/ -v
```

Tests use temporary SQLite databases and stub all ikabot imports — no live session or game connection required.

## Patches Applied to Ikabot Core

`planRoutes_patched.py` replaces `ikabot/ikabot/helpers/planRoutes.py` via Docker volume mount. Adds randomised delays between consecutive fleet dispatches on the same route (10–25s) and between distinct routes (12–30s), reducing detection risk during large transport operations.

All other custom modules (`empireFunction.py` and siblings) are injected into the ikabot container at `/ikabot/ikabot/function/` via volume mounts — no rebuild of the base image is needed when editing them.
