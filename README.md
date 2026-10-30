# Ikabot Docker Setup

A Dockerized setup for [ikabot](https://github.com/ikabot-collective/ikabot) — an automation bot for the browser game Ikariam — extended with a custom empire data collector, a SQLite database, and a React/TypeScript web dashboard.

## Overview

Three containers run side by side and share a Docker volume (`ikalogs_volume`):

| Container | Description |
|---|---|
| `ikabot` | Runs the ikabot automation bot with custom modules injected via volume mounts. Started deterministically by `bot_launcher.py` (no menu-number navigation); the interactive menu stays available over `docker attach`. |
| `ikabot-gui` | Flask — serves the REST API + SSE stream **and** the production React build (`frontend/dist`) on host port **5001**. Optional password auth (set `DASHBOARD_PASSWORD` in `.env`). |
| `ikabot-autoheal` | Watches the `ikabot` healthcheck and restarts it if the heartbeat goes stale. |

> Since 2026-07 there is **no separate `frontend` container**: the Flask app serves the built SPA. Frontend changes require `cd frontend && npx vite build`. The bot image is **pinned by digest** (stable channel, currently ikabot 7.7.2) — `:latest` is treated as beta and promoted deliberately after validation.

## Notable capabilities

- **Empire dashboard** — per-city resources, buildings, movements, world scan, espionage, combat dispatch, calculators; alerts and thresholds stored server-side; pt/en.
- **Farming (F4)** — per-target state machine (SQLite `farm_targets`), event-driven cadence tuned to real round-trip time, ship reserve, live inactivity confirmation before every action.
- **Wine strategy** — the empire produces no wine, so:
  - **Balancer (F9)** redistributes existing wine (and rescues emptied cities);
  - **Market buyer (F10)** buys wine from other players' offers within hard guards — price ceiling, gold floor, per-cycle spend cap, a refill deadband, a dry-run, and a critical mode that borrows the farm's reserved ships in a wine emergency;
  - a **"wine at a glance"** panorama shows per-city runway, empire totals and buyer status.
- **Robustness** — surgical runtime patches (no shadowing of stock files), persistent login session on a volume, digest-pinned image with a stable/beta promotion flow, self-healing, daily SQLite backups, and downtime-aware espionage timeouts.
- **Anti-detection** — randomised delays before/between game requests, active-hours gating (`SCAN_ACTIVE_HOURS` / `QUEUE_ACTIVE_HOURS`).
- **Tests** — `pytest` (`pytest.ini` sets the paths); 305 passing as of 2026-10.

### How it works

`empireFunction.py` runs as a background process inside the ikabot container. Every hour (configurable) it:

1. Writes `last_alive.json` at the very start of each iteration — if the process crashes mid-cycle this timestamp goes stale and the dashboard shows a "Bot offline" warning after `BOT_OFFLINE_SECS` (default 30 min); the container healthcheck + autoheal use the same threshold.
2. Decides whether to run a **full empire cycle** based on `SCAN_ACTIVE_HOURS`:
   - Within active hours: runs every `EMPIRE_UPDATE_INTERVAL` (default 1h ± 5 min jitter)
   - Outside active hours: runs every `SCAN_NIGHT_INTERVAL` (default 4h) — reduces nightly HTTP activity to a heartbeat scan
3. On a full cycle, collects per-city data: resources, building levels, production rates, wine status, gold. Cities are visited in a **randomised order** each cycle.
4. Fetches military and fleet movements from the military advisor endpoint.
5. Persists everything to the shared SQLite database (`ikabot.db`) via `finalize_empire_cycle()` and writes JSON files to the shared volume.
6. Processes the building queue **immediately** — never blocked by long scans.
7. Then, within `SCAN_ACTIVE_HOURS` only, one of the following runs:
   - If building costs are due (every 3 days, or `.force_costs_update` flag) → `collect_building_costs()` (~7 min)
   - Else if a world scan should start (every 7 days, or `.force_world_scan` flag) → `collect_shallow_scan()` (~30s, discovers island list)
8. Calculates the next wake-up time as the earliest of: next full cycle, next construction ETA, or next transport fleet arrival. Writes it to `next_cycle.json`. The sidebar countdown is derived from this value.
9. **During the sleep interval**, visits one island at a time from the deep-scan checkpoint (if active). The number of islands visited per sleep is organically random — determined by how long the bot sleeps, not a fixed batch size.

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
- 2–5s between the 4 quadrant requests in the world scan shallow phase; 15–30s between individual island requests in the deep phase (processed one per sleep interval).
- 3–7s between `changeCurrentCity` and `loadTransportersWithFreight`; 12–30s between consecutive transport fleets.
- `SCAN_ACTIVE_HOURS` suppresses the full empire scan outside a configurable time window, eliminating the most obvious bot signal (regular hourly HTTP activity at 3 AM).

The `ikabot-gui` Flask app reads from SQLite and exposes REST endpoints and a Server-Sent Events stream (`/api/stream`). The SSE stream pushes live updates to the browser within ~2 seconds of any data file changing. In production Flask serves the built SPA (`frontend/dist`) directly on host port **5001**; during frontend development the Vite dev server proxies all `/api/*` requests to Flask and hot-reloads on file changes.

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
# Optional: require a login for the dashboard's action routes
DASHBOARD_PASSWORD=choose-a-password
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
| `DASHBOARD_PASSWORD` | *(unset)* | If set, the dashboard requires this password to log in (protects every `/api/*` action route). Unset = open dashboard. |
| `BOT_OFFLINE_SECS` | `1800` | Single source for "bot offline": healthcheck, autoheal, Telegram watchdog and the sidebar badge |
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

Volume-mounted modules (`empireFunction.py` and all siblings) need no image rebuild, but editing any `.py` requires restarting **both** the `ikabot` and `ikabot-gui` containers (Python module cache + unreliable bind-mount reload) — `docker compose up -d --force-recreate <service>` if a plain restart doesn't pick up the change.

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
| `/api/military` | GET | Troops and fleet units per city (updated every 8h) |
| `/api/espionage/missions` | GET | All spy missions with state and results |
| `/api/espionage/spy-counts` | GET | Available spies per city |
| `/api/espionage/dispatch` | POST | Queue a spy dispatch `{originCityId, targetCityId, islandId, targetPlayerName, targetCityName, islandX, islandY, numAgents}` |
| `/api/espionage/settings` | GET | Garrison inspection thresholds |
| `/api/espionage/settings` | POST | Save garrison thresholds `{garrisonThresholds: {wood, wine, marble, glass, sulfur}}` |
| `/api/espionage/attack-queue` | GET | Pending manual attack queue (SQLite `shared_queue`) |
| `/api/espionage/attack-queue/add` | POST | Add manual attack `{originCityId, targetCityId, islandId, units, transporters, …}` |
| `/api/espionage/attack-queue/cancel` | POST | Cancel queued attack `{id}` |
| `/api/espionage/recall-unused` | POST | Mass-recall idle spies from safehouses (skips active farm targets) |
| `/api/attack-log` | GET | Dispatch history `?limit=&target=` (every attempt + game result) |
| `/api/loot-stats`, `/api/loot-log` | GET | Real loot brought back per target |
| `/api/farm` | GET | Farm targets with state, loot, attack counts |
| `/api/farm/{add,update,remove}` | POST | Manage farm targets (`add` accepts `mode` for the drain loop) |
| `/api/farm/army` | GET/POST | Per-target troop/fleet loadout + ship-reserve settings (POST merges) |
| `/api/transport`, `/api/transport/wine`, `/api/transport/wine-buy[/status\|/preview]` | GET/POST | Scheduled transports, consolidation, wine balancer, wine buyer |
| `/api/watchlist` | GET/POST | Per-island re-scan watchlist for marked targets |
| `/api/pause` | GET/POST | Global pause (suspends actions, keeps data collection) |
| `/api/logs` | GET | Tail of the bot log `?lines=N` (`?debug=1` includes DEBUG) |
| `/api/activity` | GET | Aggregated "what the bot is doing" (pending queues, active flags, recent dispatches) |
| `/api/alert-thresholds`, `/api/alert-settings` | GET/POST | Server-side alert thresholds and combat-alert settings |
| `/api/travel-calibration` | GET | Learned real/estimated travel ratios per mode |
| `/api/health` | GET | Liveness + per-subsystem health and config warnings |

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
| **World** | **Inactive**: inactive/vacation players near own cities — sortable by distance/scores, marks (novo/visto/alvo/ignorar), expandable rows with editable note, timestamped action log, spy report summary (warehouse + garrison results), "add to farm"/"add to drain loop" buttons. Highlights newly inactive players. **Islands**: nearby islands ranked by free slots, resource/wonder levels, "Use in Calc." button. Combat (dispatch, farm management, history, loot) lives on its own **Combat** page |
| **Settings** | **General**: language, default tab. **Alerts**: wine warning/critical thresholds, storage threshold. **Construction**: active hours window, per-resource buffer minimums. **Espionage**: spy defaults (origin city, number of agents), garrison inspection thresholds, minimum loot threshold, watchlist. Farm loadout, ship reserve and cadence are managed on the Combat/Farm card. **Notifications**: browser notifications toggle; Telegram configuration with live test |

## Espionage System

The espionage module (`espionage_manager.py`) implements a full spy-to-attack pipeline across four phases:

**Phase 1 — Spy dispatch**: from the Inactive players tab, open the spy modal, choose origin city and number of agents. The request is queued in `spy_dispatch_queue.json` and dispatched by the bot with 15–35s delays between consecutive missions. Pre-check against `spy_counts.json` prevents dispatching more agents than available.

**Phase 2 — State machine**: missions progress automatically across cycles:
```
TRAVELING → WAITING_AT_CITY → EXECUTING_WAREHOUSE → WAITING_FOR_GARRISON → EXECUTING_GARRISON → DONE / FAILED
```
The bot checks `spyMissions` view to detect arrival, then calls `executeMission` for warehouse inspection (mission type 5), waits 5–15 min, then for garrison inspection (mission type 6) if resources exceed the configured thresholds. Reports are fetched via `markReportAsRead`.

**Phase 3 — Manual attack**: once a mission reaches DONE with both warehouse and garrison results, a "Prepare Attack" button appears in the expanded row (Combat page). The modal shows available troops per city. The attack is queued in the SQLite `shared_queue` ("attack") and dispatched by the bot during active hours — player pillage via `sendArmyPlunderSea`/`sendArmyPlunderLand`, naval blockade via `sendFleetOnBlockade`, own-city deploy via `deployArmy`/`deployFleet`. Reports of each attempt land in the `attack_log` table.

**Phase 4 — Automated farming (the farm, `farm_manager.py`)**: the one-shot auto-attack waves system was **discontinued** in 2026-07; the **farm** is now the only automatic attack system. Each target is a row in the SQLite `farm_targets` table with its own state machine (`IDLE → SPYING → ATTACKING`), event-driven on the real round-trip cadence. It re-scouts on its own schedule, sizes each raid to the live warehouse, enforces a "drain to `min_loot`" rule, reserves trade ships against internal logistics, and — for **fleet targets** — never commits troops without fresh, trustworthy garrison intel (blockade-then-troops timing on a clean port). A separate **drain loop mode** (F13) hammers a single target wave-after-wave until empty. See FEATURES.md (F4, F4.b–F4.e, F13) for the full design. `minLootTotal` now lives in `espionage_settings.json` and auto-ignores poor reports at the espionage layer (farm targets exempt).

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
| `farm_targets` | Per-target farm state machine (state, intel, loadout, cadence, `mode`, `is_fleet_target`, `scout_fail_count`) — schema v13 |
| `shared_queue` | Transactional queues the Flask UI writes and the bot consumes: `attack`, `spy_dispatch`, `spy_recall`, `transport` (per-item removal, no races) |
| `attack_log` | Every dispatch attempt: target, origin, units, type, source, result, game error |
| `loot_log` | Real loot detected on returning fleets, deduped by arrival time |
| `schema_version` | Applied migration versions (lazy, idempotent `init_db`) |

**JSON files** — written for operational signalling and read by the Flask layer:

| File | Updated | Contents |
|---|---|---|
| `statusSummary.json` | Every cycle | Empire-wide totals |
| `empire.json` | Every cycle | Building levels per city |
| `resources.json` | Every cycle | Resources and wine timers per city |
| `movements.json` | Every cycle + on dispatch | Active fleet/army movements |
| `own_cities.json` | Every cycle | Island coordinates of own cities |
| `world_scan.json` | Per island (incremental) | Inactive players and island summaries — updated after each island during the deep scan, `scanInProgress: true` while scan is running |
| `world_scan_checkpoint.json` | Per island | Deep-scan state: remaining islands, accumulated results — deleted when scan completes |
| `world_scan_prev.json` | On shallow scan start | Previous full scan — used to detect newly inactive players (`isNew` flag) |
| `next_cycle.json` | Each sleep | Exact timestamp of next wake-up |
| `last_alive.json` | Each loop iteration | `{lastAlive, cycle}` — stale if bot crashes |
| `empire_scan_status.json` | During force-refresh | Per-city scan progress |
| `world_scan_status.json` | During world scan | Scan phase progress |
| `military.json` | Every 8h | Troops and fleet units per own city `{byCityName: {cityId, troops, fleet}}` |
| `spy_missions.json` | Each spy cycle | All missions with state machine: TRAVELING → WAITING_AT_CITY → EXECUTING_WAREHOUSE → WAITING_FOR_GARRISON → EXECUTING_GARRISON → DONE/FAILED |
| `spy_dispatch_queue.json` | On demand | Pending spy dispatches queued from the UI |
| `spy_counts.json` | Each active-hours cycle | Available/deployed/defense spy counts per city |
| `espionage_settings.json` | On save via UI | Garrison inspection thresholds per resource |
| `farm_settings.json` | On save via UI | Farm loadout (troops/fleet), ship reserve, cadence, early-respy, fleet-target timings (`fleetLeadMin`, `disperseMin`, `earlyReportMaxAgeMins`) |
| `wine_settings.json`, `wine_buy_settings.json`, `wine_buy_status.json` | On save / per cycle | Wine balancer + market-buyer config and last-run status |
| `pause.json` | On demand | Global pause flag (checked by every action processor) |
| `health.json`, `config_warnings.json` | Per cycle / on start | Per-subsystem success/failure and config-schema warnings (surfaced in `/api/health` + UI banners) |
| `travel_calibration.json` | Per raid | Learned real/estimated travel ratios (EWMA) per troop/fleet mode |
| `bot.log` | Continuously | Rotating bot log served by `/api/logs` |
| `telegram_settings.json` | On save via UI | Telegram bot token and chat ID |

> The one-shot auto-attack (`auto_attack_waves.json` / `auto_attack_settings.json`) and the standalone `attack_queue.json` / `spy_dispatch_queue.json` were **discontinued or migrated to SQLite** (`shared_queue`) in 2026-06/07; the legacy JSON files were renamed `.migrated`.
| `.queue_updated` | On each queue change | Sentinel touched on every queue write — SSE watches this |

## Project Structure

```
.
├── docker-compose.yml
├── bot_launcher.py          # Deterministic startup: login, launch empireFunction by reference, inject surgical patches, keep the menu on PID1
├── empireFunction.py        # Main loop orchestrator: full cycle → queue → espionage → farm → scans → smart_sleep
├── empire_utils.py          # Config/env, logger + i18n (lm), ThrottledSession, with_retry, is_paused, config validation, downtime accounting
├── empire_collector.py      # City data collection, movements fetch, military (troops + fleet) every 8h
├── costs_collector.py       # Building costs collection (every 3 days)
├── scan_collector.py        # Incremental world scan (shallow quadrants + deep per-island checkpoint)
├── queue_processor.py       # Building queue, resource transports, smart_sleep (processes spy/recall/attack/farm/scan queues)
├── farm_manager.py          # Automated farming (F4): per-target state machine, ship reserve, drain loop (F13)
├── espionage_manager.py     # Spy state machine, recalls, report parsing, spy-count fetch, mission retention
├── espionage_parsers.py     # Pure HTML parsers extracted from espionage_manager
├── attack_manager.py        # Attack queue + senders (plunder/blockade/deploy) and shared targeting helpers
├── transport_manager.py     # Scheduled transports, consolidation, wine balancer (F9), wine market buyer (F10)
├── db_manager.py            # SQLite layer: schema init, CRUD, migrations, shared_queue, daily online backup
├── planroutes_overrides.py  # Surgical runtime patch for planRoutes (anti-detection delays) — injected, not shadowed
├── loadcustommodule_overrides.py  # Surgical runtime patch for loadCustomModule
├── telegram_notifier.py     # Telegram Bot API notifications
├── healthcheck.py           # Freeze-aware heartbeat healthcheck (used by compose + autoheal)
├── tests/                   # pytest — 305 tests across 24 files (db, queues, parsers, spy state machine,
│                            #   farm/respy/reserve/loot, attack payload golden-files, wine, throttle, health, downtime, Flask API)
├── ikabot_gui/
│   └── app.py               # Flask REST API + SSE stream + serves frontend/dist
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # Root: SSE EventSource, routing, LangContext, global pause/attack banners
│   │   ├── components/      # One file per page/feature (HomePage, CitiesPage, BuildingsPage, Construction,
│   │   │                    #   MovementsPage, TransportTab, CombatPage, DispatchTab, WinePanorama, Logs, Settings, AuthGate, mundo/)
│   │   ├── types.ts · i18n.tsx · utils.ts · constants.ts · hooks/
│   ├── vite.config.ts       # Dev proxy /api/* → Flask (production build served by Flask)
│   └── package.json
└── .env                     # Credentials — never commit this
```

## Running Tests

```bash
.venv/bin/pytest tests/ -v
```

Tests use temporary SQLite databases and stub all ikabot imports — no live session or game connection required.

## Patches Applied to Ikabot Core

Stock files are **no longer shadowed** by whole-file copies (which froze and broke on upstream updates). Instead `bot_launcher.py` injects **surgical runtime patches** at startup: only the changed functions from `planroutes_overrides.py` (anti-detection delays between fleet dispatches) and `loadcustommodule_overrides.py` are `exec`'d into the stock module's namespace. Upstream additions to those files no longer break startup.

All custom modules (`empireFunction.py` and siblings) are mounted into the ikabot container at `/ikabot/ikabot/function/` via volume mounts — no rebuild of the base image is needed when editing them, but **both containers must be restarted** after a `.py` change (Python caches modules; the Flask auto-reloader is unreliable with bind-mounted inodes).
