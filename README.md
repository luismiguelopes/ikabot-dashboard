# Ikabot Docker Setup

A Dockerized setup for [ikabot](https://github.com/ikabot-collective/ikabot) — an automation bot for the browser game Ikariam — extended with a custom empire data collector and a web dashboard.

## Overview

Two containers run side by side and share a volume (`ikalogs_volume`) to exchange data:

| Container | Description |
|---|---|
| `ikabot` | Runs the ikabot automation bot with custom files injected via volume mounts |
| `ikabot-gui` | Flask web dashboard that reads the collected JSON data |

### How it works

`empireFunction.py` runs as a background process inside the ikabot container. Every hour (configurable) it:

1. Iterates over all cities and collects resources, buildings, production rates, and wine status.
2. Fetches military and fleet movements from the military advisor.
3. Writes the results to JSON files on the shared volume:
   - `statusSummary.json` — empire-wide totals (gold, ships, resources, population)
   - `empire.json` — per-city building levels and construction status
   - `resources.json` — per-city resource amounts and wine timers
   - `movements.json` — active fleet and army movements
4. Appends a timestamped snapshot to `history.jsonl` (capped at ~90 days).
5. If building upgrade costs are due (every 3 days), runs the cost collector inline before sleeping, writing `building_costs.json`.
6. Otherwise, if the world scan is due (every 7 days), runs it inline before sleeping, writing `world_scan.json` with inactive/vacation players and island summaries (free slots, resource and wonder levels). The previous scan is kept as `world_scan_prev.json` to detect newly inactive players.

Steps 5 and 6 are mutually exclusive per cycle — only one runs at a time, keeping HTTP requests strictly sequential. All requests use randomised delays to simulate human behaviour (anti-detection).

The `ikabot-gui` container serves a Flask app on port `5001` that reads those files and exposes them via a REST API, consumed by the React frontend.

## Requirements

- Docker and Docker Compose
- An Ikariam account

## Setup

1. Clone this repository.
2. Create a `.env` file in the project root (never commit this file):

```env
IKABOT_EMAIL=your_email@example.com
IKABOT_PASSWORD=your_password
```

3. Start the containers:

```bash
docker compose up -d
```

4. Open the dashboard at [http://localhost:5001](http://localhost:5001).

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `IKABOT_EMAIL` | — | Your Ikariam account email |
| `IKABOT_PASSWORD` | — | Your Ikariam account password |
| `EMPIRE_UPDATE_INTERVAL` | `3600` | Seconds between main data collection cycles |
| `BUILDING_COSTS_UPDATE_INTERVAL` | `259200` | Seconds between building costs refreshes (default: 3 days) |
| `WORLD_SCAN_UPDATE_INTERVAL` | `604800` | Seconds between world scans (default: 7 days) |
| `WORLD_SCAN_RADIUS` | `10` | Max island distance from own cities included in the world scan |
| `LOG_LANG` | `en` | Language for backend log messages (`en` or `pt`) |

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/data` | GET | Empire-wide status, buildings, and resources |
| `/api/movements` | GET | Current fleet and army movements |
| `/api/history` | GET | Last 7 days of hourly empire snapshots |
| `/api/building-costs` | GET | Upgrade costs per building per level per city |
| `/api/building-costs/refresh` | POST | Schedules an early building costs refresh |
| `/api/world-scan` | GET | Inactive/vacation players near own cities, with marks merged |
| `/api/world-scan/status` | GET | Current scan progress |
| `/api/world-scan/refresh` | POST | Schedules an early world scan |
| `/api/world-scan/mark` | POST | Save a player mark (`novo`/`visto`/`alvo`/`ignorar`) |

## Dashboard Tabs

The dashboard defaults to **English**. A language toggle button in the sidebar footer switches to Portuguese — the preference is saved in browser `localStorage`.

| Tab | Description |
|---|---|
| Home | Empire-wide summary (gold, ships, population) |
| Cities | Per-city resources, production, and wine timers |
| Buildings | Building levels and active constructions per city |
| Movements | Active fleet and army movements |
| Alerts | Wine, storage, gold, and ships alerts with configurable thresholds (wine warning/critical hours, storage %) — settings persisted in browser localStorage |
| History | Charts of empire stats over the last 7 days |
| Calculators | **Building Upgrade**: selects city/building/target level, computes net total missing (`max(0, totalNeeded − totalAvailable)`) and estimates collection time using empire production. **ROI Sawmill / Quarry**: island vs city building comparator — level selectors for island building (Sawmill / Quarry) and city building (Forest Warden / Stonemason) auto-fill production gain and upgrade costs from built-in game data. **Colony ROI**: compares upgrading Sawmill/Quarry on all existing islands vs colonising a new island — Residence upgrade costs (all 5 resources, × N cities) and island build costs are auto-filled from game data; city count pre-filled from empire data |
| World | **Inactive**: inactive/vacation players near own cities with new-player detection, expanded scores, and per-player marks. **Islands**: nearby islands ranked by free slots, resource and wonder levels for colonisation planning |

## Project Structure

```
.
├── docker-compose.yml
├── empireFunction.py        # Custom empire data collector (injected into ikabot)
├── planRoutes_patched.py    # Patched transport helper with anti-detection delays
├── ikabot_gui/              # Flask dashboard
│   ├── app.py
│   └── templates/
│       └── index.html       # Single-file React SPA (no build step)
└── .env                     # Credentials — never commit this
```

## Patches Applied to Ikabot Core

`planRoutes_patched.py` replaces `ikabot/ikabot/helpers/planRoutes.py` via Docker volume mount. It adds randomised delays between consecutive fleet dispatches on the same route and between distinct routes, reducing detection risk when sending large transport operations.
