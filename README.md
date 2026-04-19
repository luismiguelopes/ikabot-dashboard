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
5. Triggers a background thread every 3 days to collect building upgrade costs for all non-maxed buildings, writing `building_costs.json`.

All HTTP requests to the game server use randomised delays to simulate human behaviour (anti-detection).

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
| `EMPIRE_UPDATE_INTERVAL` | `3600` | Seconds between data collection cycles |

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/data` | GET | Empire-wide status, buildings, and resources |
| `/api/movements` | GET | Current fleet and army movements |
| `/api/history` | GET | Last 7 days of hourly empire snapshots |
| `/api/building-costs` | GET | Upgrade costs per building per level per city |
| `/api/building-costs/refresh` | POST | Schedules an early building costs refresh |

## Dashboard Tabs

| Tab | Description |
|---|---|
| Home | Empire-wide summary (gold, ships, population) |
| Cidades | Per-city resources, production, and wine timers |
| Edifícios | Building levels and active constructions per city |
| Movimentos | Active fleet and army movements |
| Alertas | Configurable alerts (wine, storage, etc.) |
| Histórico | Charts of empire stats over the last 7 days |
| Calculadoras | **Building upgrade time estimator** and **island vs city ROI comparator** |

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
