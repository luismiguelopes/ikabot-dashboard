# Ikabot Docker Setup

A Dockerized setup for [ikabot](https://github.com/ikabot-collective/ikabot) — an automation bot for the browser game Ikariam — extended with a custom empire data collector and a web dashboard.

## Overview

Two containers run side by side and share a volume (`ikalogs_volume`) to exchange data:

| Container | Description |
|---|---|
| `ikabot` | Runs the ikabot automation bot with custom files injected via volume mounts |
| `ikabot-gui` | Flask REST API that reads the collected JSON data (internal, port 5000) |
| `frontend` | Vite dev server that serves the React/TypeScript SPA on port 5001, proxying `/api/*` to `ikabot-gui` |

### How it works

`empireFunction.py` runs as a background process inside the ikabot container. Every hour (configurable) it:

0. Writes `last_alive.json` at the very start of each iteration — if the process crashes mid-cycle, this timestamp goes stale and the dashboard shows a "Bot offline" warning.
1. Iterates over all cities and collects resources, buildings, production rates, and wine status.
2. Fetches military and fleet movements from the military advisor.
3. Writes the results to JSON files on the shared volume:
   - `statusSummary.json` — empire-wide totals (gold, ships, resources, population)
   - `empire.json` — per-city building levels and construction status
   - `resources.json` — per-city resource amounts and wine timers
   - `movements.json` — active fleet and army movements
4. Appends a timestamped snapshot to `history.jsonl` (capped at ~90 days).
5. Then, one of the following runs inline (mutually exclusive, strictly sequential):
   - If building upgrade costs are due (every 3 days) → writes `building_costs.json`
   - Else if world scan is due (every 7 days) → writes `world_scan.json` with inactive/vacation players and island summaries; previous scan kept as `world_scan_prev.json` to detect newly inactive players
   - Else if building queue has pending items → processes one upgrade per city: dispatches missing resource transports from surplus cities (verifying the POST response), records any transport failures in `building_queue.json`, then starts construction when resources are available. Transport dispatch bundles all needed resources into a single fleet per source city (no port loading queue), with freighters used as a supplementary dispatch only when the total resource gap is very large (> 8 transporter ship-loads). If any transport was dispatched, `movements.json` is immediately refreshed so fleet arrival times are visible to the sleep scheduler.
6. Writes `next_cycle.json` with the exact wake-up timestamp before sleeping. The bot wakes at the earliest of: next full cycle, next construction ETA, or next transport fleet arrival — whichever comes first — respecting the `QUEUE_ACTIVE_HOURS` window. The sidebar "Refresh in" countdown is derived from this value.

All steps use randomised delays between HTTP requests to simulate human behaviour (anti-detection).

The `ikabot-gui` container runs a Flask app (internal port 5000) that reads those files and exposes them via a REST API and a Server-Sent Events stream (`/api/stream`). The `frontend` container runs a Vite dev server (port 5001) that serves the React/TypeScript SPA and proxies all `/api/*` requests to Flask. The SSE stream pushes live updates to the browser within ~2 seconds of any data file changing.

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
```

3. Start the containers:

```bash
docker compose up -d
```

4. Open the dashboard at [http://localhost:5001](http://localhost:5001).

## Configuration

Interval variables accept a human-readable duration string (`1h`, `3h`, `2d`, `30m`, `90s`) or a plain integer (seconds).

| Environment variable | Default | Description |
|---|---|---|
| `IKABOT_EMAIL` | — | Your Ikariam account email |
| `IKABOT_PASSWORD` | — | Your Ikariam account password |
| `EMPIRE_UPDATE_INTERVAL` | `1h` | Interval between main data collection cycles |
| `BUILDING_COSTS_UPDATE_INTERVAL` | `3d` | Interval between building costs refreshes |
| `WORLD_SCAN_UPDATE_INTERVAL` | `7d` | Interval between world scans |
| `WORLD_SCAN_RADIUS` | `10` | Max island distance from own cities included in the world scan |
| `QUEUE_ACTIVE_HOURS` | *(all hours)* | Hours during which the building queue may start constructions and dispatch transports — format `H-H`, e.g. `8-23` |
| `LOG_LANG` | `en` | Language for backend log messages (`en` or `pt`) |

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/data` | GET | Empire-wide status, buildings, and resources — includes `lastUpdatedTs`, `nextCycleAt`, `lastAlive` |
| `/api/movements` | GET | Current fleet and army movements |
| `/api/history` | GET | Last 7 days of hourly empire snapshots |
| `/api/building-costs` | GET | Upgrade costs per building per level per city |
| `/api/building-costs/refresh` | POST | Schedules an early building costs refresh |
| `/api/world-scan` | GET | Inactive/vacation players near own cities, with marks merged |
| `/api/world-scan/status` | GET | Current scan progress |
| `/api/world-scan/refresh` | POST | Schedules an early world scan |
| `/api/world-scan/mark` | POST | Save a player mark (`novo`/`visto`/`alvo`/`ignorar`) |
| `/api/building-queue` | GET | Current queue and active construction per city |
| `/api/building-queue/add` | POST | Add a building upgrade to a city queue |
| `/api/building-queue/remove` | POST | Remove an item from a city queue |
| `/api/building-queue/reorder` | POST | Reorder items in a city queue |

## Dashboard Tabs

The dashboard defaults to **English**. A language toggle button in the sidebar footer switches to Portuguese — the preference is saved in browser `localStorage`.

| Tab | Description |
|---|---|
| Home | Empire-wide summary: gold, ships, population, active constructions, gold runway, wine-at-risk cities |
| Cities | Per-city resources, production, and wine timers |
| Buildings | Building levels and active constructions per city — "+" button on each row to add to the upgrade queue |
| Movements | Active fleet and army movements |
| Alerts | Wine, storage, gold, and ships alerts with configurable thresholds (wine warning/critical hours, storage %) — settings persisted in browser localStorage |
| History | Charts of empire stats over the last 7 days |
| Calculators | **Building Upgrade**: selects city/building/target level, computes net total missing and estimates collection time. **ROI Sawmill / Quarry**: island vs city building comparator. **Colony ROI**: upgrading current island vs colonising a new one — amortization comparison |
| Construction | Building upgrade queue manager: city pills (orange border on transport error), building list with "+" per row, queue panel per city with drag-to-reorder, inProgress ETA card, transport error banner, status card with last bot cycle and force-update button |
| World | **Inactive**: inactive/vacation players near own cities with new-player detection, scores, and per-player marks. **Islands**: nearby islands ranked by free slots, resource and wonder levels for colonisation planning |

## Project Structure

```
.
├── docker-compose.yml
├── empireFunction.py        # Main loop orchestrator (injected into ikabot)
├── empire_utils.py          # Constants, duration parser, i18n strings
├── empire_collector.py      # City data collection, movements refresh
├── costs_collector.py       # Building costs collection
├── scan_collector.py        # World scan collection
├── queue_processor.py       # Building queue processor, transport dispatch, smart sleep
├── planRoutes_patched.py    # Patched transport helper with anti-detection delays
├── ikabot_gui/              # Flask REST API
│   └── app.py
├── frontend/                # Vite + React + TypeScript SPA
│   ├── src/
│   │   ├── App.tsx          # Root component (SSE, routing, language)
│   │   ├── types.ts         # TypeScript interfaces for all JSON data
│   │   ├── i18n.tsx         # EN/PT translations + hooks
│   │   ├── utils.ts         # Formatting helpers
│   │   ├── constants.ts     # MATERIALS, COST_KEYS, resource icons/colours
│   │   └── components/      # One file per tab/feature
│   ├── vite.config.ts       # Proxy /api/* → ikabot-gui:5000
│   └── package.json
└── .env                     # Credentials — never commit this
```

## Patches Applied to Ikabot Core

`planRoutes_patched.py` replaces `ikabot/ikabot/helpers/planRoutes.py` via Docker volume mount. It adds randomised delays between consecutive fleet dispatches on the same route and between distinct routes, reducing detection risk when sending large transport operations.
