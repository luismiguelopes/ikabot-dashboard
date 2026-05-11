# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git Commits and Pushes

- **Never** include any reference to Claude, Claude Code, or Anthropic in commit messages, PR descriptions, or any git output (no `Co-Authored-By: Claude`, no `Generated with Claude Code`, nothing).
- Write commit messages in **English**.

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
- `EMPIRE_UPDATE_INTERVAL` — data collection interval, e.g. `1h`, `3h`, `30m` or seconds (default: `1h`)
- `BUILDING_COSTS_UPDATE_INTERVAL` — e.g. `3d` (default: `3d`)
- `WORLD_SCAN_UPDATE_INTERVAL` — e.g. `7d` (default: `7d`)
- `WORLD_SCAN_RADIUS` — max tile distance for world scan (default: `10`)
- `QUEUE_ACTIVE_HOURS` — hours during which the building queue may start constructions and dispatch transports, format `H-H` e.g. `8-23` (default: all hours)

Interval values accept `Nd` (days), `Nh` (hours), `Nm` (minutes), `Ns` (seconds), or a plain integer (seconds). Parsed by `_parse_duration()` in `empireFunction.py`. The `.env` is loaded into the ikabot container via `env_file` in `docker-compose.yml`.

**Dashboard:** http://localhost:5001

## Architecture

Two containers communicate via a shared Docker volume (`/tmp/ikalogs/`):

```
Ikariam Game Server
    ↓ (HTTP via ikabot session/helpers)
[ikabot container]
    └── empireFunction.py main loop — runs every EMPIRE_UPDATE_INTERVAL seconds
          writes: statusSummary.json, empire.json, resources.json, movements.json, history.jsonl
          writes: own_cities.json (island coords of own cities, updated every cycle)
          then (mutually exclusive, inline, strictly sequential):
            if building costs due (every 3 days)  → _collect_building_costs() → building_costs.json
            elif world scan due   (every 7 days)  → _collect_world_scan()     → world_scan.json, world_scan_status.json
            elif queue items exist                → _process_building_queue() → building_queue.json
              if any transport dispatched → re-fetches movements.json (5–10s delay) so arrivalTime is visible
          _smart_sleep(): wakes at min(next_full_cycle, next_construction_ETA+jitter, next_transport_arrival+jitter)
          writes next_cycle.json with exact wake-up timestamp before sleeping
    ↓ (shared volume)
[ikabot-gui container] — Flask (internal port 5000, no external port)
    ↓ (REST API + SSE /api/stream, proxied by Vite)
[frontend container] — Vite dev server on port 5001
    ↓ (browser)
[React/TypeScript SPA — frontend/src/]
```

### Key Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Orchestrates containers and shared volume |
| `empireFunction.py` | Custom collector — main loop with inline sequential building costs and world scan |
| `planRoutes_patched.py` | Patched version of ikabot's transport helper — adds human-like delays between fleet dispatches |
| `ikabot_gui/app.py` | Flask REST API + SSE (`/api/stream`) |
| `ikabot_gui/templates/index.html` | Legacy single-file React SPA (kept as fallback, superseded by `frontend/`) |
| `frontend/` | Vite + React + TypeScript SPA — served on port 5001, proxies `/api/*` to `ikabot-gui:5000` |
| `frontend/src/App.tsx` | Root component: SSE EventSource, tab routing, language context |
| `frontend/src/components/` | Tab components (HomePage, CitiesPage, BuildingsPage, …, Construction, mundo/MundoPage) |
| `frontend/src/types.ts` | TypeScript interfaces for all JSON data files |
| `frontend/src/i18n.tsx` | Translations (EN/PT) + `useT`, `useLang`, `LangContext` |
| `frontend/src/utils.ts` | Formatting helpers: `fmt`, `fmtTime`, `fmtTs`, `fmtScore`, `exportCsv`, … |
| `frontend/src/constants.ts` | `MATERIALS`, `COST_KEYS`, `RESOURCE_ICONS`, `RESOURCE_COLORS`, `AUTO_REFRESH_SECONDS` |
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
| `own_cities.json` | Every hour | Island coords of own cities (used by world scan) |
| `building_costs.json` | Every 3 days | Upgrade costs per building per level per city |
| `world_scan.json` | Every 7 days | Inactive/vacation players + island summaries near own cities |
| `world_scan_prev.json` | Every 7 days | Previous scan — used to compute `isNew` flag |
| `world_scan_status.json` | During scan | Scan progress (status, phase, progress, total) |
| `player_marks.json` | On demand | User-assigned marks per player (novo/visto/alvo/ignorar) |
| `building_queue.json` | On demand / each queue cycle | Queue items per city + inProgress state + transportErrors + `enabled` flag |
| `next_cycle.json` | Each sleep | Exact timestamp when the bot will next wake up |
| `last_alive.json` | Each loop iteration | `{"lastAlive": timestamp, "cycle": N}` — written at the very start of each iteration before any logic |
| `empire_scan_status.json` | During force-refresh | Live city scan progress `{status, phase, progress, total, message}` — same shape as `ScanStatus` |
| `.force_costs_update` | On demand | Flag file — triggers early building costs refresh |
| `.force_world_scan` | On demand | Flag file — triggers early world scan |
| `.force_empire_update` | On demand | Flag file — wakes bot from sleep and forces a full empire data cycle immediately |

### Flask API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/data` | GET | Empire status, buildings, resources — includes `lastUpdatedTs`, `nextCycleAt`, `lastAlive` |
| `/api/data/refresh` | POST | Creates `.force_empire_update` flag — bot wakes from sleep and runs a full cycle immediately |
| `/api/data/status` | GET | Live city scan progress `{status, phase, progress, total, message}` |
| `/api/movements` | GET | Active movements |
| `/api/movements/refresh` | POST | Creates `.force_movements_update` flag — bot refreshes movements on next wake |
| `/api/history` | GET | Last 7 days of hourly snapshots |
| `/api/building-costs` | GET | Upgrade costs per building per level per city |
| `/api/building-costs/refresh` | POST | Creates `.force_costs_update` flag to trigger early refresh |
| `/api/world-scan` | GET | Inactive/vacation players near own cities, with marks and action logs merged |
| `/api/world-scan/status` | GET | Current scan progress (`status`, `phase`, `progress`, `total`, `message`) |
| `/api/world-scan/refresh` | POST | Creates `.force_world_scan` flag to trigger early scan |
| `/api/world-scan/mark` | POST | Save player mark `{playerId, status, note}` — preserves existing `actions` |
| `/api/world-scan/action` | POST | Append timestamped action `{playerId, islandX, islandY, text}` to player's log |
| `/api/building-queue` | GET | Current queue, inProgress, transportErrors, and `enabled` flag per city |
| `/api/building-queue/add` | POST | Add item `{cityName, buildingName, targetLevel}` to city queue |
| `/api/building-queue/remove` | POST | Remove item `{cityName, index}` from city queue |
| `/api/building-queue/reorder` | POST | Reorder item `{cityName, fromIndex, toIndex}` in city queue |
| `/api/building-queue/clear` | POST | Clear queue for one city `{cityName}` or all cities (no body) |
| `/api/building-queue/enabled` | POST | Enable or pause the queue `{enabled: bool}` |

### Frontend Tabs

Home, Cidades, Edifícios, Movimentos, Alertas, Histórico, Calculadoras, Construção, Mundo.

**Construção** — building upgrade queue manager:
- Status card: last bot cycle, costs last updated, enabled/paused toggle, "Limpar tudo" button, force-update button
- Sub-tabs: **Queue** and **Template**
- Queue sub-tab: city pills (split with × clear-city button when items exist), building list with "+" per row, queue panel per city with drag-to-reorder + remove, inProgress ETA card, transport error banner, queue budget summary card
- Template sub-tab: set target levels per building type, preview table, apply to all cities at once

**Calculadoras** has two sub-tabs:
- **Evolução de Edifícios** — selects city/building/target level, auto-fills costs from `/api/building-costs`, then estimates time to gather resources using empire production
- **ROI Serraria / Pedreira** — compares island vs city building ROI

**Alertas** — active alerts with configurable thresholds:
- Alert types: wine running out (warning + critical), storage overflow, negative gold production, all ships busy
- **Configurar** button opens an inline settings panel with inputs for: wine warning (h), wine critical (h), storage warning (%)
- Thresholds persisted to `localStorage` (no backend required); defaults: 8h / 2h / 95%
- Sidebar badge count respects the configured thresholds

**Mundo** — two sub-tabs sharing a single status card and "Forçar Scan" button:
- **Inactivos** — inactive and vacation players near own cities:
  - "Novos esta semana" toggle (filters by `isNew`, players absent from the previous scan)
  - Green ★ badge on newly inactive player names
  - Columns: Jogador, Aliança, Estado, Ilha, Dist., Score Militar (+ rank), Score Edifícios, Marcação
  - Sortable by distance, military score, building score, or name
  - Filters: max distance, state, mark status, free-text search
  - Per-row mark dropdown: **novo** / **alvo** / **visto** / **ignorar** — saved via `/api/world-scan/mark`
  - **Expandable rows** (chevron toggle): editable note textarea + save, timestamped action log with add-entry input — saved via `/api/world-scan/mark` (note) and `/api/world-scan/action` (log entries)
  - Action count badge on rows with logged entries
  - CSV export includes building score, rank, and isNew flag
- **Ilhas** — scanned islands for colonisation planning:
  - Columns: Ilha, Recurso (icon + colour), Floresta, Lv Recurso, Maravilha, Slots Livres, Dist.
  - Sortable by free slots (default desc), wood level, luxury level, distance
  - Filters: slots livres only (default on), exclude own islands (default on), resource type, max distance
  - "Usar na Calc." button pre-fills the Colony ROI calculator with the island's resource/level data
  - CSV export
- Progress bar while scan is running (polls `/api/world-scan/status` every 5s); CSV export per sub-tab

## Building Costs Collection (`_collect_building_costs`)

Runs inline in the main loop every 3 days (or when `.force_costs_update` flag exists), checked before the world scan (`if/elif` — mutually exclusive). Uses **random delays to simulate human behaviour** — this is intentional anti-detection:
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

## World Scan (`_collect_world_scan`)

Runs inline in the main loop every 7 days (or when `.force_world_scan` flag exists), via `elif` after the building costs check — never concurrent with any other scan. Configurable scan radius via `WORLD_SCAN_RADIUS` env var (default: 10).

Two-phase approach:
1. **Shallow scan** — 4 `getJSONArea` API calls covering the full 100×100 map. Extracts island IDs and coordinates. Delay: 2–5s between calls.
2. **Deep scan** — one `getIsland` request per island that (a) has players and (b) falls within `WORLD_SCAN_RADIUS` of any own city. Delay: 15–30s between islands.

Per island the deep scan records:
- **Players**: only `inactive` and `vacation` city slots, with scores (building, research, army, trader, rank).
- **Island summary**: resourceType, woodLevel, luxuryLevel, wonder, wonderLevel, freeSlots, totalSlots, hasOwnCity — stored in `islands[]` array.

Before overwriting `world_scan.json` the previous file is copied to `world_scan_prev.json`. The `/api/world-scan` endpoint compares both to set `isNew: true` on players not present in the previous scan.

Own city coordinates are read from `own_cities.json` (written every hourly cycle).

`world_scan.json` structure:
```json
{
  "lastUpdated": 1713456789,
  "scanRadius": 10,
  "ownCities": [{"name": "Lisboa", "x": 45, "y": 32}],
  "players": [
    {
      "playerId": "12345",
      "playerName": "Xpto",
      "allyTag": "ABC",
      "state": "inactive",
      "cityName": "Urbs",
      "islandName": "Phytios",
      "islandX": 47,
      "islandY": 33,
      "nearestOwnCity": "Lisboa",
      "distance": 2.8,
      "scores": {"building": "1,234", "research": "567", "army": "890", "trader": "12", "rank": "42"}
    }
  ],
  "islands": [
    {
      "islandId": "58",
      "islandName": "Phytios",
      "x": 47, "y": 33,
      "resourceType": 2,
      "woodLevel": "12", "luxuryLevel": "9",
      "wonder": "Hephaestus", "wonderLevel": "3",
      "freeSlots": 2, "totalSlots": 16,
      "hasOwnCity": false,
      "nearestOwnCity": "Lisboa",
      "distance": 2.8
    }
  ]
}
```

`player_marks.json` structure (written by Flask on each `/api/world-scan/mark` and `/api/world-scan/action` call):
```json
{
  "12345_47_33": {
    "status": "alvo",
    "note": "Próximo de Lisboa, bom alvo",
    "updatedAt": 1713456789,
    "actions": [
      {"ts": 1713456800, "text": "Enviado espião"},
      {"ts": 1713460000, "text": "Ataque planeado para amanhã"}
    ]
  }
}
```

Mark key format: `{playerId}_{islandX}_{islandY}`. Valid mark values: `novo` (default), `visto`, `alvo`, `ignorar`. The `actions` array is preserved across mark status/note updates.

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
- **Frontend changes:** Edit files in `frontend/src/`. The Vite dev server (running in the `frontend` container) hot-reloads automatically. No browser refresh needed for most changes. After adding npm dependencies, rebuild the frontend container: `docker compose up -d --build frontend`. Live data updates are pushed via SSE (`/api/stream`); fallback polling is `AUTO_REFRESH_SECONDS = 300` (5 min).
- **Backend changes:** `docker compose up -d --build ikabot-gui` after editing `app.py`. Volume-mounted files (`empireFunction.py`, `planRoutes_patched.py`) take effect with just `docker compose up -d`.
- **`wineRunsOutIn` recalculation:** `resources.json` stores the wine timer as seconds-remaining at collection time. `load_all_data()` in `app.py` subtracts the elapsed seconds since the file's mtime so the GUI always shows a live value, not a stale one.
- **Anti-detection:** Any new code that makes HTTP requests to the game server **must use random delays** (`time.sleep(random.randint(...))`) between requests to simulate human behaviour. Never batch requests without pauses. Reference delays by context:
  - Main hourly loop: 5–15s between cities, 2–6s between two requests within each city, 5–10s before movements request, ±5 min jitter on cycle (`UPDATE_INTERVAL + random.randint(-300, 300)`)
  - Building costs collection: 15–30s between cities, 5–15s between buildings within a city
  - World scan: 2–5s between the 4 shallow map calls; 15–30s between per-island deep requests
  - Transport routes (`planRoutes_patched.py`): 3–7s between `changeCurrentCity` and `loadTransportersWithFreight`, 10–25s between consecutive fleets on the same route, 12–30s between distinct routes
- **Sequential scans:** Building costs and world scan run inline (no threads), under a single `if/elif` in the main loop. Only one can run per cycle and they never overlap with the main data collection or each other. This is intentional — keeps all HTTP requests strictly sequential (human-like).
- **Ikabot session:** The `session` object passed to `empireFunction` supports `.get()`, `.post()`, `.getSessionData()`, `.setSessionData()`. Session data can be used to cache per-session values (e.g., research reduction is cached as `reduccion_inv_max`).

---

## Roadmap / Pipeline

Features planeadas por ordem de prioridade. Atualizar à medida que forem desenvolvidas.

### [DONE] Sistema de Queue de Construção

Fases 1, 2 e 3 completas e merged em main.

- **Fase 1** — queue passiva: verifica slot livre + recursos na cidade, chama `expandBuilding()`
- **Fase 2** — transporte automático: `_dispatch_transport` (fire-and-forget, não bloqueia), subtrai recursos em trânsito via `movements.json`
- **Fase 3** — sourcing inteligente: `_calc_city_reserved` reserva custos de toda a queue antes de ceder excedentes; `QUEUE_ACTIVE_HOURS` gating em construção e transporte

`building_queue.json` estrutura:
```json
{
  "enabled": true,
  "queues": {
    "Lisboa": [{"building": "Academia", "targetLevel": 15, "addedAt": 1713456789}]
  },
  "inProgress": {
    "Lisboa": {"building": "Academia", "position": 3, "fromLevel": 14, "startedAt": 1713456800, "eta": 1713460000}
  },
  "transportErrors": {
    "Porto": {"failedAt": 1713456789, "origin": "Lisboa", "resource": "wood"}
  }
}
```

`enabled` defaults to `true` if absent. When `false`, `has_building_queue()` returns `False` and `process_building_queue()` returns immediately — no constructions or transports are started.

---

### [DONE] Monitorização de saúde do bot

- `empireFunction.py` escreve `last_alive.json` com `{"lastAlive": timestamp, "cycle": N}` **no início de cada iteração** — crash a meio deixa o ficheiro parado
- `app.py` expõe `lastAlive` via `/api/data`
- Sidebar: badge vermelho "Bot offline" se `lastAlive` for mais antigo que 90 min; suprime o "Stale data" amarelo quando o bot já está offline

---

### [DONE] Modularização do `empireFunction.py`

`empireFunction.py` foi partido em 5 módulos, todos injectados via volume mount no `docker-compose.yml`:

- `empire_utils.py` — constantes, `_parse_duration`, `_parse_active_hours`, dict `_LM` com todas as strings i18n, `lm()`
- `empire_collector.py` — `collect_city_data()`, `finalize_empire_cycle()`, `refresh_movements()`
- `costs_collector.py` — `should_update_building_costs()`, `collect_building_costs()`
- `scan_collector.py` — `should_update_world_scan()`, `collect_world_scan()`
- `queue_processor.py` — `has_building_queue()`, `process_building_queue()`, `smart_sleep()`, `_try_transport()`, `_dispatch_transport()`, etc.
- `empireFunction.py` — main loop com ~100 linhas, só imports e orquestração

---

### [DONE] Verificação de transporte na queue

- `_dispatch_transport` verifica `resp[3][1][0]["type"] == 10` e retorna `True`/`False`
- `_try_transport` recebe `transport_errors` dict: escreve `{failedAt, origin, resource}` em falha, limpa em sucesso
- `_process_building_queue` passa o dict e salva quando muda (snapshot antes/depois)
- `building_queue.json` inclui agora `transportErrors: { cityName: {failedAt, origin, resource} }`
- Frontend tab Construção: pill com borda laranja + ícone ⚠ por cidade com erro; banner laranja no painel da fila com detalhe do erro

---

### [DONE] Transporte bundled por cidade + suporte a cargueiros

Problema anterior: o loop `for resource → for source_city` despachava múltiplas frotas da mesma cidade (uma por tipo de recurso), criando uma fila de carregamento no porto mercantil.

Fix:
- Loop refatorado para `for source_city → bundle all resources` — uma frota por cidade com todos os recursos bundled
- `_build_send_list()`: extrai payload e número de navios para uma cidade/capacidade dada; reutilizado nos dois tipos de frota
- `_dispatch_transport()`: parâmetro `use_freighters=False` — usa `transporters` ou `usedFreightersShips`/`transporters=0` conforme o tipo
- **Pass de transporters**: uma frota bundled por cidade fonte, navios rápidos, cobre a maioria dos casos
- **Pass de cargueiros**: só activado quando a necessidade total (`sum(net_missing)`) ultrapassa `_FREIGHTER_THRESHOLD_WAVES * ship_cap` (8 ship-loads por omissão); escolhe preferencialmente uma cidade fonte diferente das que já despacharam transporters (evita fila no porto); uma frota por ciclo

---

### [DONE] Wake-up no ETA de chegada de transporte

Problema: após despachar um transporte, `_smart_sleep` não sabia quando a frota chegaria — dormia o ciclo completo (até 1h). A construção ficava parada durante 30–50 min depois dos recursos chegarem.

Causa raiz dupla:
1. `_smart_sleep` só consultava `_get_next_construction_eta()` (apenas cidades com `inProgress`); cidades à espera de recursos não tinham ETA.
2. `movements.json` é escrito **antes** de `_process_building_queue` ser chamado — os transportes despachados nesse ciclo não constavam do ficheiro, tornando `_get_in_transit_to` cego a eles.

Fix:
- `_try_transport` devolve `True/False` (se despachou com sucesso)
- `_process_building_queue` devolve `True` se qualquer cidade despachoi transporte
- Quando `_process_building_queue` devolve `True`, o main loop re-busca `movements.json` (delay 5–10s, path idêntico ao da recolha normal de movimentos)
- Nova função `_get_next_transport_eta()`: lê `movements.json`, filtra frotas próprias (`isOwn=True`, `direction="->"`) com destino em cidades com queue pendente, devolve o `arrivalTime` mais cedo
- `_smart_sleep` calcula agora o mínimo de três valores: próximo ciclo completo, ETA de construção, ETA de chegada de transporte

---

### [DONE] SSE — live updates no dashboard

- `/api/stream` (`text/event-stream`): generator que faz poll de mtime dos ficheiros de dados a cada 2s; emite `event: update` quando qualquer ficheiro muda; envia `: keepalive` comments no idle para evitar timeouts de proxy
- `threaded=True` no `app.run()` para SSE não bloquear outros pedidos
- Frontend: `EventSource('/api/stream')` substitui o `setInterval` de 15 minutos; intervalo de fallback de 5 minutos cobre gaps de reconexão
- `AUTO_REFRESH_SECONDS` reduzido de 900 para 300 (fallback)

---

### [DONE] Migração frontend para Vite + React + TypeScript

O `index.html` com +3000 linhas foi substituído por uma SPA TypeScript modular no directório `frontend/`.

- **`frontend/src/App.tsx`** — componente raiz: SSE `EventSource`, routing por tab, `LangContext`
- **`frontend/src/components/`** — um ficheiro por tab/feature: `HomePage`, `CitiesPage`, `BuildingsPage`, `MovementsPage`, `AlertsPage`, `HistoryPage`, `Construction` (BuildingQueueTab), `mundo/MundoPage` (InactivosTab + IlhasTab), `calculadoras/` (BuildingUpgradeCalc, ROICalc, ColonyROICalc)
- **`frontend/src/types.ts`** — interfaces TypeScript para todos os JSON do volume
- **`frontend/src/i18n.tsx`** — traduções EN/PT + hooks `useT`, `useLang`
- **`frontend/vite.config.ts`** — proxy `/api/*` → `http://ikabot-gui:5000`
- **`docker-compose.yml`** — novo serviço `frontend` (node:20-alpine, porta `5001:5173`); `ikabot-gui` passou a interno (sem porta externa)
- Zero erros TypeScript (`tsc --noEmit` limpo)

Merged em main (commits `58fe619`→`b43e3df`).

---

### [DONE] Force-Refresh com Progresso (Cidades e Edifícios)

Ver secção detalhada mais abaixo.

---

### [DONE] Construção Dinâmica e Card Home Alargado

**Problema 1 — ETA estático na construção em curso**
`inProgress.eta` é um timestamp Unix mas o frontend não faz countdown — mostra a hora de conclusão estática ou passa directo a "concluído". Corrigir com `setInterval` igual ao "Refresh in" da sidebar.

**Problema 2 — Card "Construções Activas" incompleto**
No tab Home, o card só mostra cidades com `inProgress`. Renomear para **Construções Activas / Queue** e mostrar três estados distintos:
- 🔨 **Em construção** — `inProgress` existe; mostra edifício + countdown do ETA
- ⏳ **À espera de recursos** — item no topo da queue mas sem `inProgress` (bot ainda não iniciou); mostra edifício + nível alvo + botão "Verificar agora"
- 📋 **Em fila** — restantes itens da queue (posição 2+); lista compacta por cidade

**Problema 3 — Força re-verificação da queue sem esperar ciclo**
Botão "Verificar agora" nas cidades em estado "à espera de recursos":

- *Frontend only (imediato)*: re-faz `GET /api/building-queue` para refrescar estado visível
- *Com suporte do bot (Fase 2)*: novo flag `.force_queue_check` + endpoint `POST /api/building-queue/check`; bot detecta no início do loop, corre `_process_building_queue()` imediatamente e apaga o flag; SSE propaga a actualização

As mesmas melhorias de ETA dinâmico aplicam-se ao tab Construção (painel `inProgress` por cidade).

---

### [DONE] Movimentos Dinâmicos (Fases 1 e 2)

O tab Movimentos mostra `arrivalTime` como timestamp estático — os tempos não contam down em tempo real.

**Fase 1 — frontend only (sem alterações ao backend):**
- `setInterval` no `MovementsPage` força re-render a cada segundo e exibe tempo restante calculado em tempo real (como o "Refresh in" da sidebar)
- Quando `arrivalTime < now`, a linha desaparece automaticamente ou é marcada como "chegou" até ao próximo ciclo do bot confirmar
- Botão "Actualizar" re-faz `GET /api/movements` (Flask lê o ficheiro na hora — não vai ao jogo, devolve o estado mais recente do ficheiro)

**Fase 2 — force-refresh do jogo (requer alterações ao bot):**
- Novo ficheiro flag `.force_movements_update` (mesmo padrão que `.force_costs_update` e `.force_world_scan`)
- Bot detecta o flag no início do loop, chama `refresh_movements()` imediatamente e apaga o flag
- Flask expõe `POST /api/movements/refresh` que cria o flag
- Botão "Actualizar" chama este endpoint em vez de apenas re-ler o ficheiro; SSE propaga a actualização quando o bot termina

Fase 1 resolve o problema visual sem tocar no backend. Fase 2 é opcional e útil quando se quer confirmar que uma frota chegou sem esperar o próximo ciclo.

---

### [DONE] Template Global de Construção

Nova sub-tab "Template" no tab Construção. Permite definir níveis-alvo por tipo de edifício; ao aplicar, todas as cidades abaixo desse nível recebem automaticamente os itens em queue.

**Frontend only** — sem alterações ao backend. Usa `/api/building-queue/add` em sequência.

Fluxo:
1. Utilizador define níveis-alvo por edifício (e.g. Academia → 15, Serraria → 12) — guardado em `localStorage`
2. Botão "Pré-visualizar" mostra tabela: por cidade, quais os edifícios abaixo do alvo e quantos níveis faltam
3. Botão "Aplicar" percorre todas as cidades e chama `/api/building-queue/add` para cada par cidade/edifício abaixo do alvo (ignora já em queue ou já no nível alvo)
4. Feedback por linha: ✓ adicionado / — já em queue / ✗ erro

Considerações:
- Dados de nível actual vêm de `empire.json` (já disponível via `/api/data`)
- Dados de nível actual em queue vêm de `/api/building-queue`
- Edifícios que não existem numa cidade são ignorados silenciosamente
- Template múltiplo (guardar/carregar vários templates por nome) é extensão futura

---

### [DONE] Painel de Definições

Página completa (mesmo padrão que World/Construção) com 3 sub-tabs:
- **Geral** — idioma (EN/PT), tab inicial ao abrir o dashboard (guardados em `localStorage`)
- **Alertas** — thresholds de vinho (aviso/crítico) e armazém
- **Notificações** — browser notifications funcional (requestPermission, toggle, dedup); Telegram skeleton

---

### [DONE] Gestão Bulk da Queue + Toggle Activo/Pausado

- `POST /api/building-queue/clear` — limpa a fila de uma cidade `{cityName}` ou de todas (sem body)
- `POST /api/building-queue/enabled` — activa/pausa a queue `{enabled: bool}`; estado guardado em `building_queue.json`
- `has_building_queue()` e `process_building_queue()` verificam `data.get('enabled', True)` antes de agir
- Frontend: toggle activo/pausado no status card, botão × por city pill (quando tem itens), botão "Limpar tudo" global com confirmação

---

### [DONE] Force-Refresh com Progresso (Cidades e Edifícios)

- `POST /api/data/refresh` cria flag `.force_empire_update`
- `smart_sleep()` dorme em chunks de 60s e sai imediatamente quando o flag existe
- `empireFunction.py` detecta o flag no início do loop, remove-o e força `ids = None` (full cycle)
- `empire_collector.py` escreve `empire_scan_status.json` com `{status, phase, progress, total, message}` a cada cidade processada; marca `done` em `finalize_empire_cycle()`
- `GET /api/data/status` expõe o progresso ao frontend
- CitiesPage e BuildingsPage têm botão "Forçar actualização" que faz POST e depois polled `/api/data/status` a cada 2s mostrando `N/13` cidades

---

### [PLANNED] Notificações Telegram

O ikabot já tem suporte a Telegram nalgumas funções — avaliar reutilização.

- Alertas: bot offline >90min, construção completa, erro de transporte, vinho crítico
- Baixo esforço: `requests` para a Telegram Bot API, sem dependências novas

---

### [DONE] Notificações Nativas do Browser

`useNotifications` hook em `frontend/src/hooks/useNotifications.ts`:
- Dispara para: vinho crítico por cidade, bot offline (>90min)
- Dedup via `useRef<Set<string>>` — não repete até a condição ser resolvida
- `loadBrowserNotifEnabled` / `saveBrowserNotifEnabled` para `localStorage`
- Toggle em Definições → Notificações; estado partilhado com App.tsx

---

### [DONE] Matriz de Balanço de Recursos

Card no tab Home abaixo dos cards de construção e vinho. Visível apenas quando há itens em queue com dados de custos disponíveis.

- Tabela `cidades × recursos` — cada célula mostra `disponível − reservado` para a queue dessa cidade
- Cores: verde (excedente), amarelo (tem mas menos de 50% do necessário), vermelho (défice)
- Linha de totais no fundo com balanço global do império por recurso
- Frontend only — dados de `resources.json`, `building_queue.json`, `building_costs.json` já disponíveis via API

---

### [DONE] Orçamento Global da Queue

Sumário no topo do tab Construção: custo total de todos os itens em queue em todas as cidades, e tempo estimado para o império acumular esses recursos dado a produção actual.

- Inputs: `building_queue.json` (itens por cidade) + `building_costs.json` (custo por nível) + `resources.json` (produção/h + stock actual)
- Output: total de cada recurso necessário, tempo estimado em dias/horas
- Linha por recurso: [ícone] [total necessário] [já disponível no império] [falta X] [~N dias de produção]
- Frontend only — todos os dados já disponíveis via API existente

---

### [DONE] Integração Calculadora Colónia ↔ World Scan

Botão "Usar esta ilha" na tab Ilhas (Mundo) que abre a Calculadora → ROI Colónia pré-preenchida com os dados reais da ilha seleccionada.

- Dados disponíveis em `world_scan.json`: `woodLevel`, `luxuryLevel`, `resourceType`, `wonder`
- Implementação: estado partilhado entre MundoPage e CalculadorasPage (via App.tsx ou contexto simples), ou routing com query params internos
- Elimina copy-paste manual dos níveis da ilha para a calculadora
- Frontend only, zero alterações ao backend

---

### [DONE] Balanço de Vinho no Home

Card no Home mostra todas as cidades em risco, sumário de pills (N críticas / N em aviso), e estado vazio quando todas as cidades estão seguras. Thresholds respeitam os valores configurados em Definições → Alertas.

---

### [PLANNED] Histórico por Cidade

Filtro por cidade nos gráficos do tab Histórico. Actualmente só existem totais do império.

- `history.jsonl` já tem dados por cidade em cada snapshot? Verificar estrutura — se não, o bot teria de começar a escrever dados per-city nos snapshots
- Se os dados existirem: adicionar select de cidade + filtro "Todas" nos gráficos já existentes (recharts/chart.js)
- Se não existirem: adicionar ao bot a escrita de per-city snapshot em `history.jsonl` (pequena alteração ao `finalize_empire_cycle()`)

---

### [DONE] Log de Acções no Tab Mundo

- Cada linha da tab Inactivos tem um botão chevron que expande um painel inline
- Painel expandido: textarea de nota (guardada via `/api/world-scan/mark`), lista de acções com data + texto, input para adicionar nova acção (via `/api/world-scan/action`, Enter ou botão)
- `player_marks.json` ganha campo `actions: [{ts, text}]` — preservado em todas as actualizações de marca/nota
- Badge com contagem de acções visível nas linhas com histórico
- `api_world_scan` já inclui `markActions` na resposta para hidratação no frontend
