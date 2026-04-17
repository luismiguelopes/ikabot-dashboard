# Ikabot Docker Setup

A Dockerized setup for [ikabot](https://github.com/ikabot-collective/ikabot) — an automation bot for the browser game Ikariam — extended with a custom empire data collector and a web dashboard.

## Overview

Two containers run side by side and share a volume (`ikalogs_volume`) to exchange data:

| Container | Description |
|---|---|
| `ikabot` | Runs the ikabot automation bot with a custom `empireFunction.py` injected |
| `ikabot-gui` | Flask web dashboard that reads the collected JSON data |

### How it works

`empireFunction.py` runs as a background process inside the ikabot container. Every hour (configurable) it:

1. Iterates over all your cities and collects resources, buildings, production rates, and wine status.
2. Fetches military and fleet movements from the military advisor.
3. Writes the results to four JSON files on the shared volume:
   - `statusSummary.json` — empire-wide totals (gold, ships, resources, population)
   - `empire.json` — per-city building levels and construction status
   - `resources.json` — per-city resource amounts and wine timers
   - `movements.json` — active fleet and army movements
4. Appends a timestamped snapshot to `history.jsonl` (capped at ~90 days).

The `ikabot-gui` container serves a Flask app on port `5001` that reads those files and exposes them via a REST API, consumed by the frontend dashboard.

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

| Endpoint | Description |
|---|---|
| `GET /api/data` | Empire-wide status, buildings, and resources |
| `GET /api/movements` | Current fleet and army movements |
| `GET /api/history` | Last 7 days of hourly empire snapshots |

## Project Structure

```
.
├── docker-compose.yml
├── empireFunction.py      # Custom empire data collector (injected into ikabot)
├── ikabot_gui/            # Flask dashboard
│   ├── app.py
│   └── templates/
└── .env                   # Credentials — never commit this
```
