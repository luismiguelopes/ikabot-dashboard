# PLANO — ikabot (criado 2026-06-11, após auditoria completa do código)

Estado (2026-10-29): **P0-P10 concluídos** + backlog da auditoria (B1-B10, F1, F11) feito ou
descartado conscientemente (B5, B8 saltados). Extras recentes: supervisor do worker (relança o
bot em segundos em vez de ~36 min via autoheal), credenciais por env em vez de argv, **F13 —
loop de drenagem** (ataque agressivo a um alvo até secar; ver FEATURES.md) e **P10 — robustez do
farm e da espionagem** (fixes de intel obsoleta/rejeitada em alvos de frota, retenção de missões,
watchdog de construção, imunidade ao sleep do host; ver secção P10). Bot em produção no
**ikabot 7.7.2** (pinado por digest `6224352e`), sessão persistente, self-healing e backups activos.
**305 testes a passar.**
Trabalho de código: nada pendente. **Validação in-game: toda concluída (2026-11-04).** A reescrita
do farm foi validada live de ponta a ponta pelo utilizador; o deploy para cidade própria estava a
falhar (bug de formato de id), foi **corrigido (`7b95486`) e confirmado live** — `deployArmy` com
type=10 (`ataque despachado → Própria (Vampiria)` às 09:53). Auto-attack foi **descontinuado**
(P6.2) — ignorar itens antigos que o referem.

---

## P0 — Crítico ✅ CONCLUÍDO 2026-06-11

### P0.1 ✅ Busy-loop no smart_sleep com ataques agendados
- **Onde**: `queue_processor.py:272-279`
- **Problema**: `has_pending_attacks()` devolve True mesmo quando todos os itens têm
  `dispatchAfter` no futuro. O loop chama `process_attack_queue` (que regrava o
  `attack_queue.json` sem necessidade) e faz `continue`, saltando o `time.sleep`.
  Resultado: CPU a 100% e escritas em disco contínuas enquanto existir um ataque agendado.
- **Correcção aplicada**: nova função `has_due_attacks()` (verifica `dispatchAfter <= now`)
  usada no smart_sleep; `process_attack_queue` só grava quando despachou algo.

### P0.2 ✅ Auto-attack waves usavam a API errada
- **Onde**: `espionage_manager.py` — `_dispatch_army_wave` (linha ~2307) e ramo fleet
- **Problema**: ainda usa `deployArmy` + `_fetch_deployment_upkeep` + IDs `s303` crus.
  Vai falhar garantidamente na primeira utilização, como o dispatch manual falhava.
- **Correcção aplicada**: lógica plunder extraída para `_send_army_plunder()` (partilhada
  com helpers `_change_to_origin_city` e `_parse_attack_feedback`); `_dispatch_army_wave`
  passou a usá-la. ⚠️ Validar in-game na primeira vaga automática.

### P0.3 ✅ Race conditions nas filas JSON (perda silenciosa de dados)
- **Onde**: `process_attack_queue` e `process_dispatch_queue` (`espionage_manager.py`)
- **Problema**: carregam a fila, processam durante minutos (sleeps anti-detecção) e no fim
  gravam por cima. Itens adicionados pela UI Flask nesse intervalo são apagados.
- **Correcção aplicada**: merge-on-save nas 3 filas (attack, spy dispatch, recall) —
  reler antes de gravar e remover só os itens processados, identificados por
  `_queue_item_key()` (id quando existe, senão origem_destino_timestamp). O Flask agora
  também atribui `id` aos dispatches de espiões.
- **Correcção definitiva** (P3): migrar filas para SQLite como a building queue.

---

## P1 — Funcionalidade incompleta ✅ CONCLUÍDO 2026-06-11

### P1.1 ✅ Ataque naval (fleet) — migrado para bloqueio de porto
- `_send_fleet_blockade()`: substitui `deployFleet` (que só estaciona em cidades
  aliadas). Faz fetch do formulário (`view=blockade`, fallback `blockadeHarbour`),
  auto-descobre o nome real da função no próprio formulário (esperado
  `sendFleetBlockadeSea`), extrai upkeep, faz strip do prefixo `s` nos IDs.
- Se o formulário não tiver os campos esperados, loga os nomes dos inputs para
  diagnóstico (mesma técnica que descobriu `sendArmyPlunderSea`).
- `_dispatch_fleet_attack` (auto-attack) também usa a nova função.
- ⚠️ **POR VALIDAR IN-GAME** — testar um dispatch fleet e ver os logs.

### P1.2 ✅ Texto do aviso de jogador inactivo corrigido
- Agora diz "Jogador inactivo — atacável; confirma que ainda tem recursos antes de enviar".

### P1.3 ✅ Retry + Telegram nos ataques
- Falha → reagendado +5-15 min aleatório, máx. 3 tentativas, depois removido.
- Notificação Telegram em sucesso (`notify_attack_dispatched`) e falha final
  (`notify_attack_failed`).

### P1.4 ✅ `_auto_mark_ignored` usa `save_mark` directamente
- O import da classe inexistente `DbManager` foi removido; marcas vão para a DB.

### P1.5 ✅ Recalls com retry espaçado
- `nextAttemptAfter` (+3-10 min) em cada falha; `has_due_recalls()` no smart_sleep
  evita reprocessamento imediato (e o busy-loop equivalente ao P0.1).

---

## P2 — Higiene / infra-estrutura ✅ CONCLUÍDO 2026-06-11

- **P2.1 ✅** Dispatch entre cidades próprias corrigido: `own_cities.json` passa a incluir
  `islandId` (a partir do próximo ciclo do império); novo `targetType` ("own"/"enemy")
  na API e no item da fila; `_send_deploy()` usa `deployArmy`/`deployFleet` com o
  formulário deployment (IDs CSS `s303` sem strip, ao contrário do plunder).
  ⚠️ POR VALIDAR: requer 1 ciclo do império para o islandId aparecer; a UI avisa se faltar.
- **P2.2 ✅** `debug=False` no Flask (auto-reload mantido via `use_reloader=True`).
- **P2.3 ✅** Flask pinado: `pip install 'flask==3.1.*'` (container recriado, 3.1.3).
- **P2.4 ✅** `.gitignore`: `__pycache__/`, `.pytest_cache/`, `.venv/` e artefactos
  0-byte dos mountpoints em `ikabot_gui/`.
- **P2.5 ✅** Duplicações de paths removidas no app.py (`SPY_RECALL_QUEUE_PATH` movido
  para o topo).
- **P2.6 ✅** Notificação "bot offline" movida de `GET /api/data` para thread própria
  (verifica a cada 5 min; guard `WERKZEUG_RUN_MAIN` evita duplicação com o reloader).

---

## P3 — Sustentabilidade ✅ CONCLUÍDO 2026-06-12

- **P3.1 ✅** Testes dos parsers HTML (`test_espionage_parsers.py`, 17 testes: safehouse,
  countdown, spy session id, garrison, relatórios, missões activas, threshold).
- **P3.2 ✅** Split: `attack_manager.py` (fila de ataques, senders, auto-attack waves)
  separado do `espionage_manager.py` (espiões, recalls, parsing). Novo volume no compose.
- **P3.3 ✅** Filas attack/spy_dispatch/spy_recall migradas para SQLite
  (`db_manager.shared_queue`, schema v4): items com `id`, remoção transaccional por item
  (zero races), migração automática dos JSON antigos (renomeados `.migrated`).
  `auto_attack_waves.json` ficou em JSON (só o bot escreve; Flask lê/cancela — risco
  baixo; migrar se vier a dar problemas).
- ⚠️ Lição operacional: o auto-reload do Flask não apanha edições que substituem o inode
  dos ficheiros montados — reiniciar SEMPRE os dois containers após editar .py.

---

## P4 — Features novas

Catálogo completo movido para **FEATURES.md** (F1-F11, com ordem sugerida).
Já concluídas daqui: refresh military (✅), Telegram de combate (✅), retry (✅).
Próximas recomendadas: F6 (alarme de ataque recebido) → F1 (histórico de ataques)
→ F2 (ETA de chegada no DispatchTab).

---

## P5 — Robustez / observabilidade (auditoria 2026-06-23)

Fase de robustez antes de novas features. Auditoria a frio do projecto.

**Concluído nesta fase:**

### P5.0 ✅ Testes de comportamento da máquina de estados de espiões — 2026-06-23
`tests/test_espionage_state_machine.py` (19 testes de caracterização): fixa todas as
transições (TRAVELING→WAITING_AT_CITY→EXECUTING_WAREHOUSE→WAITING_FOR_GARRISON→
EXECUTING_GARRISON→DONE + caminhos FAILED + isolamento de falhas no `process_spy_cycle`).
Rede de segurança para o split (P5.6). O `espionage_manager` (2078 linhas) já não está sem
testes de comportamento — só tinha testes de parsers.

### P5.1 ✅ Self-healing do bot — 2026-06-23
A sessão base do ikabot já é robusta (re-login automático, timeout 300s, espera manutenção).
Gap era a recuperação quando o *worker* morre: um `sys.exit` da sessão (re-login/rede
esgotados) levanta `SystemExit`, não apanhado pelo `except Exception` do loop → worker morre
mas o pai ikabot (PID 1) sobrevive → `restart:unless-stopped` não dispara.
- `smart_sleep` escreve `last_alive.json` a cada ≤60s (era 1×/ciclo, horas à noite).
- `docker-compose`: healthcheck sobre a idade do heartbeat (>30 min = unhealthy) + sidecar
  `willfarrell/autoheal` que reinicia o `ikabot` unhealthy (label `autoheal=true`).
- `empireFunction` apanha `SystemExit`/`KeyboardInterrupt` → alerta Telegram
  (`notify_bot_fatal`) e re-levanta. Limiar offline do Flask 90→30 min.
- ⚠️ **Infra requer `docker compose up -d`** para activar (recria `ikabot` com healthcheck +
  arranca `ikabot-autoheal`; o sidecar precisa de `/var/run/docker.sock`).

### P5.2 ✅ Observabilidade de falhas silenciosas — 2026-06-23
~150 `except Exception` engoliam erros — o bot podia estar "vivo mas inútil". Cada subsistema
(empire/building/espionage/attack/farm/transport/scan) regista sucesso/falha em `health.json`
via `health_guard(...)` no `empireFunction` (substitui os `try/except` que só logavam). N
falhas consecutivas (3) → alerta Telegram uma vez (`notify_subsystem_down`), recuperação
limpa-o (`notify_subsystem_recovered`). Exposto na UI: `/api/health` traz `subsystems`, e o
`SubsystemHealthBanner` (App.tsx) mostra um banner vermelho quando há módulos em falha.
Testes: `test_health.py` (7).

### P5.3 ✅ Anti-detecção centralizada — 2026-06-23
A regra nº1 dependia de `time.sleep` espalhado (fácil de esquecer num caminho novo).
`ThrottledSession` (empire_utils) embrulha a sessão no arranque do `empireFunction` e garante
um **piso de espaçamento** entre QUALQUER get/post (≈1.5-3.5s) — onde já havia sleep local
(5-15s) não acrescenta nada; onde faltava, protege. Proxy transparente (`__getattr__`/
`__setattr__` delegam tudo o resto). Escape hatch `IKABOT_NO_THROTTLE=1`. Confirmado que nenhum
módulo contorna via `session.s.get`. Nota: o "teste que apanha get/post sem sleep" (estático,
grep) foi superado pela garantia em runtime — testámos antes o comportamento do wrapper
(`test_throttle.py`, 6).

### P5.4 ✅ Migrar `auto_attack_waves.json` para SQLite — 2026-06-23
Última race JSON Flask↔bot: o bot fazia load→processar (minutos de sleeps)→gravar o ficheiro
todo, esmagando waves que a UI tivesse cancelado. Agora cada plano é um item da `shared_queue`
(queue `auto_attack_waves`): `evaluate` faz `_wave_upsert` por plano novo; `process` regrava por
plano **re-lendo os ids vivos** no fim (não ressuscita um cancelado a meio); a UI lê/cancela via
`queue_items`/`queue_remove`. Migração one-shot do JSON legado (`_migrate_waves_json_once` →
`.migrated`). MundoPage faz poll 60s → liveness mantida. Teste em `test_attack_queue.py`.

### P5.5 ✅ Endurecer o fail-open da F4.e — 2026-06-23
`_confirm_inactive` devolvia None (incerto: scan velho + fetch da ilha falha) e continuava em
warehouse-only → ataque directo às cegas. Agora `_safe_target_verdict` devolve
`disable`/`warehouse`/`garrison`: incerteza → **garrison** (scout completo que lê o porto antes
de comprometer tropas). Fecha a única fenda reintroduzida na F4.e. Teste em `test_farm.py`.

### P5.6 ✅ Split físico do `espionage_manager.py` — 2026-06-23
2078→1674 linhas; parsers puros (safehouse, missões activas, countdown, session-id, relatórios,
guarnição, movimentos de frota) movidos para `espionage_parsers.py` (444) por extracção AST.
Re-export em `espionage_manager` → call sites e testes não mudam. Novo mount no
`docker-compose.yml` (⚠️ requer `docker compose up -d`, não chega `restart`). 206 testes passam.

### P5.7 ✅ Golden-file tests dos payloads que gastam tropas — 2026-06-23
`test_attack_payloads.py` (4): fixa o POST exacto de `sendArmyPlunderSea`,
`sendFleetBlockadeSea` e `deployArmy/deployFleet` mockando os form-fetchers e a sessão.
Apanha regressões no strip do `s` (plunder/blockade tiram, deploy mantém s303), nos upkeep
obrigatórios (zero-fill das unidades não enviadas) e no cap de transporters — antes de
custarem um exército in-game.

### P5.8 ✅ Validação de schema das configs — 2026-06-23
`validate_configs()` (empire_utils) verifica farm_settings/auto_attack_settings/
espionage_settings/world_scan_settings/telegram_settings contra os schemas autoritativos (as
chaves que os writers do Flask produzem). Chaves desconhecidas (typos) e tipos errados → aviso
no log + `config_warnings.json` + `/api/health` + banner âmbar na UI. Corre no arranque do
`empireFunction`. Antes, um typo caía em silêncio para o default. Testes em
`test_config_validation.py` (6).

---

**P5 concluído.** Próximo: validação in-game de tudo (ver pendências abaixo) antes de novas
features.

---

## Pendências de verificação (não são trabalho novo)

- [x] Confirmar in-game que `sendArmyPlunderSea` lança ataques — ✅ validado 2026-06-11.
- [x] Ataque naval — ✅ validado 2026-06-11: a função real é **`sendFleetOnBlockade`**
      (auto-descoberta pelo formulário `view=blockade`); ataque saiu com type=10.
- [x] Contagens militares erradas na UI (ex.: 290 Lança-Chamas inexistentes) — ✅ bug do
      parser corrigido 2026-06-11: a resposta cityMilitary traz army+fleet juntos e a
      frota emparelhava com as células do exército. Validado contra Baphomet in-game.
      Bónus: 1 pedido HTTP por cidade (era 2) e refresh manual via
      `POST /api/military/refresh` (P4.4 ✅).
- [x] ~~Validar a primeira vaga do auto-attack~~ — OBSOLETO: o auto-attack foi
      descontinuado (P6.2, 2026-07-03). O farm é o único sistema de ataque automático.
- [x] Validar deploy para cidade própria ✅ 2026-11-04 — `deployArmy` type=10 confirmado live
      (`ataque despachado → Própria (Vampiria)`), após o fix do formato de id (`7b95486`).
- [x] Validar in-game toda a reescrita do farm (2026-06): fila pura (drenar 1 alvo),
      flee-fleet bloqueio→tropas (F4.b), ataque-directo + confirmação de inactividade (F4.e).
      ✅ **Validada live de ponta a ponta pelo utilizador (2026-11-04)** — a funcionar devidamente.
- [x] Validar o self-healing (P5.1): ✅ 2026-11-04 — `ikabot` fica `healthy`, `ikabot-autoheal`
      está `Up (healthy)` com `/var/run/docker.sock` montado (pode reiniciar containers unhealthy).
      O supervisor do worker (P10.2) é a 1ª linha; o autoheal é a rede de último nível.

---

## P6 — Pipeline pós-auditoria (auditoria completa 2026-07-02)

Auditoria a frio de todo o projecto (lógica + UI + infra) com o P5 concluído e o bot
`healthy` em produção. Ordem = prioridade de implementação (risco primeiro, conforto depois).

### Bloco A — risco (fazer primeiro)

- [x] **P6.1 Guarda de tropas no auto-attack.** ✅ 2026-07-02 —
      `maxEnemyTroopsToEngage` (default 50) em settings/UI/schema; SKIPPED
      "Guarnição demasiado grande" (não auto-ignorado — alvo rico fica visível). `_determine_attack_tier` devolve tier 1
      com *qualquer* tropa terrestre e o ataque avança; existe `maxEnemyShipsToEngage`
      mas nenhum equivalente para o exército — um alvo com 500 hoplitas e armazém rico
      passa todos os filtros. Adicionar `maxEnemyTroopsToEngage` (settings + UI) e
      SKIPPED com razão quando excedido. É o maior risco actual de perder um exército.
- [x] **P6.2 → RESOLVIDO POR DESCONTINUAÇÃO.** ✅ 2026-07-03 — o auto-attack one-shot
      foi removido por decisão do utilizador (nunca usado, nunca validado, redundante
      com o farm, e enviava a guarnição inteira da origem). Removidos: evaluate/waves/
      settings/endpoints/cartão UI/pills de waves. O `minLootTotal` passou para
      `espionage_settings.json` e o auto-ignore de alvos pobres mudou para o pipeline
      de espionagem (fecha o relatório sem missão de guarnição; alvos do farm isentos).
      P6.1 (guarda de tropas) removido junto — só protegia o auto-attack.
      Fica pendente apenas: validar deploy para cidade própria (DispatchTab → destino
      "própria" → deployArmy type=10) numa sessão supervisionada.
- [x] **P6.3 Backup automático do `ikabot.db`.** ✅ 2026-07-02 — `backup_db()`
      no db_manager (sqlite3 online-backup API, 1×/dia, rotação 7), chamado no início
      de cada ciclo; `./backups` (host, gitignored) montado em `/backups` no container.
      Primeiro backup confirmado no host. No-op se o mount faltar.

### Bloco B — coerência de dados e configuração

- [x] **P6.4 Thresholds de alertas para o servidor.** ✅ 2026-07-03 —
      `alert_thresholds.json` no volume + `GET/POST /api/alert-thresholds`; o frontend
      migra o localStorage no primeiro load (confirmado live) e mantém-no só como
      cache de arranque. PC e telemóvel vêem os mesmos valores.
- [x] **P6.5 Vista unificada do funil de thresholds.** ✅ 2026-07-03 — a remoção do
      auto-attack já tinha juntado os 2 thresholds globais no cartão de espionagem;
      adicionado o bloco "Como os thresholds se encadeiam" (1. guarnição, 2. alvo
      interessante, 3. min_loot por alvo do farm com contagem e gama dos activos).
- [x] **P6.6 Unificar os limiares de "bot offline".** ✅ 2026-07-03 — fonte única
      `BOT_OFFLINE_SECS` (env, default 1800): healthcheck do compose lê-a, o watchdog
      Telegram do Flask usa-a, e o /api/data expõe `offlineAfterSecs` para o badge do
      sidebar (que estava a 90 min — passou a 30, coerente com o resto).
- [x] **P6.7 Calibrar tempos de viagem.** ✅ 2026-07-03 — cada raid do farm já busca o
      tempo real ao formulário; agora regista o rácio real/estimado (EWMA α=0.2, por
      tipo troop/fleet, amostras absurdas descartadas) em `travel_calibration.json`.
      O ETA do DispatchTab multiplica a estimativa pelo rácio (`/api/travel-calibration`).

### Bloco C — UX e operação (conforto, sem risco)

- [x] **P6.8 Feedback de acções da UI.** ✅ 2026-07-03 — `GET /api/activity` agrega
      sinais existentes (itens pendentes das 4 filas SQLite, flags `.force_*` activas
      — desaparecer = o bot pegou no pedido —, últimos dispatches do attack_log com
      ✓/✗ e erro). Cartão "Actividade do bot" na HomePage (poll 15s; oculto se vazio).
- [x] **P6.9 Autenticação simples no dashboard.** ✅ 2026-09-21 — concluído como **B1**:
      auth opt-in via `DASHBOARD_PASSWORD` no `.env`, `before_request` protege `/api/*`.
- [x] **P6.10 Split da MundoPage.** ✅ 2026-07-03 — "Combate" é página própria no
      sidebar (`CombatPage.tsx`: dispatch/farm/histórico via DispatchTab); MundoPage
      ficou só world scan (1637→296 linhas) com os componentes extraídos para ficheiros
      próprios em `mundo/`: SpyModal, AttackModal, InactivosTab (727), IgnoradasTab,
      IlhasTab, types.ts. Sem mudanças de comportamento; nav "Mundo"/"Combate" no
      sidebar e no selector de página inicial.
- [x] **P6.11 Build de produção do frontend.** ✅ 2026-07-03 — Flask serve
      `./frontend/dist` (montado ro em /gui/dist) com fallback SPA; porta 5001 passou
      a publicar o ikabot-gui; container `ikabot-frontend` removido do compose.
      ⚠️ Mudanças no frontend agora exigem `cd frontend && npx vite build`.
- [x] **P6.12 Testes do Flask.** ✅ 2026-07-03 — flask instalado no venv;
      `tests/test_flask_api.py` (9 testes via test_client): alert-thresholds (defaults/
      roundtrip/clamps), espionage settings (merge parcial não esmaga minLootTotal),
      travel-calibration, activity (filas+flags+log), marks POST, farm re-enable limpa
      'ignorar' mas preserva 'alvo', SPA serving/fallback/404 em /api. Nota: importar o
      db_manager REAL antes do app.py (ikabot_gui/ tem artefactos 0-byte dos mounts).
- [x] **P6.13 Recall em massa de espiões não usados.** ✅ 2026-07-17 — botão no MundoPage
      → POST /api/espionage/recall-unused → flag `.force_recall_unused`; o bot varre os
      safehouses (verdade real, não o spy_missions.json acumulado), salta alvos de farm
      ACTIVOS e missões em curso, e enfileira recalls em lotes de 20 espaçados 10min
      (nextAttemptAfter). Segundo carregamento apanha alvos com espiões de várias origens.
- [x] **P6.14 Verificação de inactividade em tempo real antes de CADA acção do farm.**
      ✅ 2026-07-17 — `_confirm_inactive` passou a fetch da ilha ao vivo como fonte
      primária (world scan só como fallback), com memo de 2min; corre antes de raids
      directos (None → escala para scout, nunca ataque cego), antes do lançamento
      pós-relatório e em todos os verdicts de scout (incl. primeiro contacto).
- [x] **P6.15 Logs legíveis no terminal.** ✅ 2026-07-18 — terminal a INFO+ (env
      `LOG_LEVEL`), bot.log grava DEBUG (F10 filtra DEBUG por omissão, `?debug=1` mostra
      tudo); catálogo _LM uniformizado (`[módulo] mensagem`, sem `[+]`/`->`/timestamps
      duplicados); rotina a DEBUG (extracção por cidade, waits anti-detecção, wakes de
      construção, dumps de safehouse); resumos: "Império actualizado: N cidades (Xmin)",
      "Safehouses: N destacados"; dumps humanizados; ícones ⚔️/💰/⚠️ nos eventos críticos.

## P7 — Bugs conhecidos por corrigir (2026-07-17)

- [x] **P7.1 Timeout de SPYING cego ao downtime.** ✅ — o farm deixou de abortar uma
      missão viva pelo relógio de parede: consulta `has_live_mission()` (espionage) antes
      de desistir; o timeout naive de 6h passou a um backstop de **13h** acima do
      auto-terminalizar da própria espionagem (12h/2h → FAILED). Já não deita relatórios fora.
- [x] **P7.2 SPYING encravado congela a fila do farm.** ✅ — `_spy_is_stuck()` liberta a
      cabeça SPYING quando não há missão viva (após uma folga de 12min) e `next_farm_eta`
      deixou de devolver None em SPYING → a fila não bloqueia mais nos restantes alvos.

> **Residual (aberto):** os timeouts do *lado da espionagem* (12h/2h) ainda são cegos ao
> downtime — causam **re-espião**, não perda de relatório (o pior ficou resolvido acima).

---

## P8 — Estratégia de vinho (2026-09-19/20)

O império não produz vinho (todas as cidades são de mármore), por isso o stock só desce.
Resolvido em dois planos complementares.

### P8.1 ✅ Balanceador de vinho (F9) — redistribui o que existe
- `transport_manager.process_wine_balancer`: quando a autonomia cai abaixo de
  `thresholdHours`, enche até `targetHours` — primeiro de produtoras
  (`wineProductionPerHour > 0`), senão de consumidoras com folga (runway ≥ `donorReserveHours`).
- **Correcções (2026-09-19):** (1) cidade vazia (consumo 0, produção 0, runway -1) já NÃO é
  tratada como dadora — evitava-se roubar-lhe os últimos pingos; (2) gatilho por stock: as
  vazias são abastecidas (estimadas pela mediana das irmãs), que o runway -1 escondia.
  **Ligado por defeito.** `wine_settings.json` + `/api/transport/wine`.

### P8.2 ✅ Comprador de mercado (F10) — repõe o que falta
- `transport_manager.process_wine_buyer`: compra vinho das ofertas de outros jogadores
  para manter o alvo por cidade; o balanceador espalha. Papéis separados: comprar vs distribuir.
- **Travões (única função que gasta ouro):** `maxPricePerUnit`, `goldFloor`,
  `maxSpendPerCycle`, `dryRun` — off + dry-run por defeito.
- **Banda morta** (`refillBelowHours`): só compra quando uma cidade cai abaixo do mínimo e
  enche até ao alvo de uma vez → lotes ocasionais, não compras constantes.
- Cede sempre barcos ao farm (`apply_ship_reserve`); "Prever agora" via `.force_wine_buy`.
  Reutiliza `buyResources`/`market`. `/api/transport/wine-buy[/status|/preview]`.
  Validado live (dry-run e compra real). Testes: `tests/test_wine.py`, `tests/test_wine_buy.py`.

---

## P9 — Infra de arranque, imagem e sessão (2026-09-09 → 2026-09-20)

- **P9.1 ✅ Arranque determinístico (`bot_launcher.py`).** Substituiu a navegação por números
  de menu (`21 7 1 …`), que partia a cada reordenação de menus do upstream. Login via
  `Session()`, lança `empireFunction` por referência, entrega o menu no PID1 (`docker attach`).
- **P9.2 ✅ Patches cirúrgicos.** Fim do shadowing de `planRoutes.py`/`loadCustomModule.py`
  (congelavam e partiam com updates — ex.: 7.6.0 acrescentou `splitCargoBetweenFleets`). O
  launcher injecta em runtime só as funções alteradas (`planroutes_overrides.py`,
  `loadcustommodule_overrides.py`). Adições do upstream já não partem.
- **P9.3 ✅ Imagem pinada por digest (stable/beta).** Stable actual **7.7.1** (`bcde4870…`);
  `:latest` é beta (diff stock → check imports offline → 1 arranque live → promover).
  Histórico: 7.5.1 → 7.6.0 → 7.6.1 → 7.6.2 → 7.6.3 → 7.7.1. O salto 7.6.3→7.7.1 (2026-10-15)
  foi um refactor amplo (decorador `@configurator` novo, feature `CONSTRUCTION_FREE_SPEEDUP`
  opcional/off); validado: planRoutes idêntico, APIs consumidas compatíveis, import offline +
  patches cirúrgicos OK, arranque live limpo.
- **P9.4 ✅ Sessão persistente (volume `ikabot_home` em `~/.ikabot`).** Sobrevive a
  `force-recreate`/promoção → deploys reutilizam a sessão (menos logins, menos dependência
  do serviço externo do blackbox).
- **P9.5 ✅ Recuperação de login.** Com o blackbox externo em baixo: semear cookies do
  browser (`gf-token-production` + `ikariam`/`PHPSESSID`) em `~/.ikabot/users/<email>.json`.

---

## P10 — Robustez do farm, espionagem e arranque (2026-10-15 → 2026-10-29)

Lote de correcções de fiabilidade saído de incidentes reais observados em produção (logs +
feedback do utilizador). Sem features novas; endurece caminhos que gastavam tropas, barcos ou
viagens à toa. Todos commitados em inglês e em produção.

### Arranque e supervisão
- [x] **P10.1 Worker não sequestra o `docker attach`** (`7f798d1`) — o worker autónomo herdava o
      stdin do attach; o `enter()` na rotação de sessão sequestrava o terminal. Fix: stdin do
      worker → `/dev/null`.
- [x] **P10.2 Supervisor do worker** (`8cecb9f`) — relança o worker em segundos quando morre, em
      vez de esperar ~36 min pelo autoheal. O autoheal fica como rede de segurança de último nível.
- [x] **P10.3 Credenciais por env** (`74446c7`) — email/password lidos do ambiente, não do argv
      (deixavam de aparecer no `ps`/process list).

### Farm — intel de alvos de frota (gastava tropas/viagens)
- [x] **P10.4 Pilhagem na mesma ilha fazia ida-e-volta morta** (`567707b`) — alvo na mesma ilha
      usava o cálculo de viagem marítima; tropas iam e voltavam sem pilhar. Corrigido o modo de
      viagem terrestre.
- [x] **P10.5 Cache militar obsoleta bloqueava raids** (`d4c2ae3`) — depois de as tropas
      regressarem, o `military.json` (cache 8h) ainda as dava como ausentes e o farm saltava a
      ronda. O farm deixou de confiar na cache stale para decidir origem.
- [x] **P10.6 Re-scout em intel antecipada obsoleta** (`c626f1e`) — um relatório antecipado (re-spy
      em pipeline) de horas antes era usado para atacar um alvo de frota às cegas. Agora, se a frota
      inimiga pode ter regressado (`enemy_return_at`) ou o scout tem mais de `earlyReportMaxAgeMins`
      (2h), força re-espionagem completa antes de comprometer tropas. Guarda-redes equivalente em
      `_enqueue_attack`.
- [x] **P10.7 Scout de guarnição rejeitado ≠ porto limpo** (`5cccf8b`) — a decisão de frota lia-se
      só do relatório de guarnição; um scout **rejeitado** (sem dados) era tratado como "0 navios"
      → tropas-só → ricochete. Agora distingo relatório fiável (ataca) de rejeitado/ausente
      (re-espia; ao fim de 3 falhas salta a ronda, nunca arrisca tropas contra frota não vista).
      Nova coluna `scout_fail_count` (schema v13).

### Espionagem — fiabilidade do store e das missões
- [x] **P10.8 Espiões de missão falhada ficavam encalhados** (`0b1c362`) — uma missão FAILED
      deixava os espiões estacionados inutilizáveis; agora voltam ao pool reutilizável.
- [x] **P10.9 Re-exec de armazém falha rápido sem feedback** (`e9e3b44`) — quando o servidor não
      devolve `provideFeedback`, a re-execução de armazém desiste depressa em vez de pendurar.
- [x] **P10.10 Retenção de missões terminais** (`e20d9b3`) — o `spy_missions.json` crescia sem
      limite (1261 missões observadas). `_prune_missions` no `_save_missions` corta terminais com
      mais de `missionRetentionDays` (30d); missões vivas e sem timestamp preservadas. Purga manual
      inicial 1261→184.

### Infra / robustez geral
- [x] **P10.11 Sleep do host não repagina nem reinicia** (`578c46c`) — o Mac a dormir criava
      lacunas no heartbeat que disparavam alertas offline e restart ao acordar. Healthcheck
      freeze-aware + janela nocturna de alerta tornam esses gaps benignos.
- [x] **P10.12 Watchdog de passos de construção** (`a396c11`) — um `expandBuilding` síncrono do
      stock podia pendurar o worker a meio de um build; watchdog SIGALRM em `queue_processor`
      limita cada passo e auto-recupera.
- [x] **P10.13 Promoção da imagem para 7.7.2 stable** (`982d9fa`, digest `6224352e`) — seguindo o
      fluxo de validação habitual (diff stock → imports offline → arranque live → promover digest).

> **Nota operacional recorrente (P10.6/P10.7):** os alvos com frota (`is_fleet_target=1`) são a
> fonte de quase todos os desperdícios de tropas. A regra consolidada é: **nunca comprometer tropas
> contra um alvo de frota sem intel de guarnição fiável e fresca**. Qualquer caminho novo que decida
> enviar tropas a um fleet-target tem de passar por esta porta.

---

## Backlog / próximos passos (auditoria 2026-09-20; progresso 2026-09-21)

Ordenado por prioridade (risco → conforto). Fonte da verdade viva; ver também o roadmap partilhável.

### Segurança
- [x] **B1 Autenticação no dashboard (era P6.9).** ✅ — auth opt-in: `DASHBOARD_PASSWORD` no
      `.env` liga um `before_request` que protege todas as rotas `/api/*` (cookie de sessão
      assinado, secret persistente, 30 dias, HttpOnly+SameSite). AuthGate no frontend + logout.

### Fechar a feature de vinho
- [x] **B2 Modo crítico do comprador.** ✅ — abaixo de `criticalHours` (default 6) o comprador
      fura a reserva do farm (como o balanceador); acima, cede como antes.
- [x] **B3 Aviso de coerência na UI.** ✅ — o card avisa se o balanceador está desligado ou se
      o alvo do comprador excede a reserva de dador.
- [x] **B4 Auto-preview ao Guardar.** ✅ — guardar dispara o dry-run e actualiza o plano.

### Funcionalidades
- [~] **B5 Generalizar o comprador a outros recursos.** DESCARTADO (2026-09-21) — os outros
      recursos não têm consumo/hora no `resources.json` (modelo "horas" não aplica) e são
      produzidos; comprar é marginal. Sem interesse.
- [x] **B6 Vista unificada "estratégia de vinho".** ✅ — card "Vinho num relance" (runway por
      cidade vs thresholds, totais do império, estado do comprador).

### Farm
- [x] **F1 Última vaga de cada alvo raspa o fundo (loot desperdiçado).** ✅ 2026-09-21 —
      `_estimated_warehouse()` = `last_loot` escotado − loot já trazido desde a escota
      (`_returned_since_scout`). Um alvo é *drenado* (→ re-espia, e dimensiona a vaga ao loot real)
      quando **qualquer** sinal dispara: a estimativa cai abaixo de `min_loot` (drenagem cumulativa,
      apanha a vaga desperdiçada 1 raid antes) **ou** o último regresso real < `min_loot` (armazém
      subitamente pequeno, que a estimativa não apanha). 7 testes novos; suite 291.

### Espionagem
- [x] **F11 Dispatch de espiões falhava quando pedia mais agentes do que os disponíveis.**
      ✅ 2026-10-02 — diagnóstico das missões "Missão falhada" na MundoPage (546 falhas em 1042):
      a maior fatia evitável (~110) era pedir N agentes com só M<N na cidade → missão inteira FAILED.
      Agora o pre-check faz cap ao disponível e **envia com os que houver** (≥1); só falha a 0 espiões.
      (As restantes falhas são type=11 do servidor ou risco normal do jogo — capturado/sem relatório.)

### Residuais / manutenção
- [x] **B7 Timeouts da espionagem downtime-aware.** ✅ — `record_startup_downtime()` +
      `active_elapsed()` (empire_utils) descontam o tempo offline; os 3 timeouts usam-no.
- [~] **B8 Split do `espionage_manager.py`** SALTADO (2026-09-21). *(os grupos
      coesos — contagem de espiões, missões, relatórios — estão todos entrelaçados pelo mesmo store
      de missões `_load_missions`/`_save_missions`, e o módulo é importado por 4 sítios. Um split
      limpo e valioso não é seguro para um módulo crítico nunca validado live; ganho baixo. Recomendação:
      **saltar** como o B5, ou só uma extracção mínima simbólica.)*
- [x] **B9 `pytest.ini`** ✅ — `pythonpath = . ikabot` + `testpaths`; o comando documentado
      corre sozinho.
- [x] **B10 Split do chunk do frontend** ✅ — `manualChunks` (react + chart.js); app 653→314KB.

### Dívidas de validação in-game *(precisam de sessão supervisionada — não é trabalho de código)*
- [x] Deploy para cidade própria ✅ 2026-11-04 — validado live (type=10) após o fix `7b95486`.
- [x] Reescrita do farm supervisionada live. ✅ **Validada de ponta a ponta pelo utilizador
      (2026-11-04)** — a funcionar devidamente.

---

## P11 — Roadmap candidato (auditoria a frio 2026-10-29)

Auditoria de todo o projecto com P0-P10 concluídos, zero TODO/FIXME, build do frontend fresco e
git limpo. **Veredicto: o projecto está maduro e estável** — não há bugs abertos nem trabalho de
código pendente. O que resta é dívida de manutenibilidade, validação live e afinação operacional.
Ordenado por valor/risco. Nenhum item é urgente.

> **Reconciliação 2026-11-04:** após fechar P11.1/P11.2/P11.5/P11.6/P11.7/P11.10 + self-healing e
> descartar P11.4/P11.8/P11.11, a suite está em **343 testes**. O deploy para cidade própria (última
> dívida) foi corrigido (`7b95486`) e **confirmado live (type=10)**. **Pipeline sem itens abertos**;
> trabalho de código pendente: zero.

### A — Operacional / estratégia *(config, não código — decisão do utilizador)*
- [x] **P11.1 "Espiões insuficientes: 2 na cidade, 10 pedidos"** ✅ 2026-11-04 — o utilizador baixou
      o nº de agentes por omissão para **4** na UI (farm settings `spyAgents`). Resolvido.
- [x] **P11.2 Clusters "possivelmente capturado"** ✅ 2026-11-04 (verificação) — regra do
      utilizador: só fica alvo se ainda estiver inactivo, senão ignorar. Verificado no world scan:
      **HEFESTO** = cidade do jogador `adauthos5675`, agora em **`vacation`** (não inactivo → o jogo
      recusa ataque); **Jaka** e **Triplex do Lula** já **não aparecem no scan** (contas apagadas /
      fora de alcance). Nenhum qualifica como alvo inactivo → todos **ignorar**. Além disso, nenhum
      é alvo de farm activo, logo já não queima espiões — concern morto.

### B — Manutenibilidade *(dívida técnica real, risco baixo)*
- [x] **P11.3 Observabilidade e tamanho do `ikabot_gui/app.py`** — ✅ ANALISADO 2026-11-02,
      **risco baixo, NÃO fazer o split**. O `app.py` (agora 2098 linhas, 94 `except`) **nunca fala
      com o jogo** (as 2 "sessions" são o cookie de auth do Flask, não a do jogo) — só lê JSON/SQLite
      que o bot escreve, e o bot valida tudo o que consome. Logo um bug no dashboard **não pode**
      causar acção errada no jogo; no pior caso mostra um valor errado/stale. Dos `except`: ~20
      devolvem 500 visível; os ~28 `pass` silenciosos são o padrão benigno "abrir JSON opcional →
      default" (não engolem escritas). Auth está ligada (`DASHBOARD_PASSWORD`, compare em tempo
      constante). **Veredicto: segurança nenhuma afectada; risco é só fiabilidade/manutenibilidade
      do dashboard.** O split por blueprints seria mexer muito numa camada crítica nunca validada
      live para ganho baixo → não compensa. Ganho barato opcional (se algum dia): um
      `@app.errorhandler(Exception)` que loga + devolve 500, para erros deixarem de ser invisíveis.
- [~] **P11.4 Split do `espionage_manager.py`** — **FORA DA PIPELINE (2026-11-04, decisão do
      utilizador).** O módulo tem 2137 linhas mas está **estável, testado e sem problemas**; partir
      um módulo crítico (importado por 4 sítios, store de missões entrelaçado) sem dor real que o
      justifique não compensa. Não é trabalho; só reabrir se o tamanho/emaranhado voltar a causar
      dor concreta (bug difícil de localizar por causa do tamanho, alteração que parte partes não
      relacionadas, ou feature nova que o emaranhado torne arriscada). Contexto favorável se um dia
      for preciso: há `test_espionage_state_machine.py` e o caminho de frota já corre live.
- [x] **P11.5 Split do `DispatchTab.tsx`** ✅ 2026-10-30 (`2d33c62`) — o monólito de 1229 linhas
      foi partido: `DispatchTab.tsx` é agora um router fino (10 linhas) que despacha para
      `dispatch/DispatchPanel.tsx` (dispatch manual + fila), `dispatch/HistoryPanel.tsx` (histórico)
      e `dispatch/FarmSettings.tsx`, com helpers/tipos comuns em `dispatch/shared.ts` — como se fez
      na MundoPage. O split na auditoria (2026-10-29) listou-o a 1229 linhas; foi feito no dia
      seguinte e só agora fechado no plano.

- [x] **P11.9 Farming paralelo — usar os barcos livres no próximo alvo** (pedido do utilizador
      2026-11-02; **feito 2026-11-02**). Uma vaga dimensiona os barcos ao saque
      (`transporters = ceil(saque/500)`), por isso um alvo pequeno deixa **muitos barcos livres**;
      a fila era **slot único** (`process_farm_targets` só trabalhava a cabeça; um alvo `ATTACKING`
      *ou* `SPYING` continuava a ser a cabeça), logo os barcos ficavam **parados horas** e, pior,
      um alvo a **espiar** bloqueava alvos já prontos a atacar.
  - **Afinação-chave (do exemplo real do utilizador):** **slot de espião ≠ slot de ataque.** A
    espionagem usa a casa dos espiões, **não os barcos** → um alvo em `SPYING` nunca deve bloquear
    um raid a outro alvo. Era o caso #1 (Jardim De Cima a espiar) a travar os #2/#3 prontos; e o
    #4 (drenado, armazém < threshold) nunca chegava a ser reavaliado/retirado por estar preso atrás.
  - **Implementado** (`farm_manager.py`):
    - `_farm_working_set` substitui o head único: avança **sempre** SPYING+ATTACKING e **oferece** o
      slot de ataque ao melhor alvo IDLE *due* por prioridade (Caso 1 primeiro; `loop` à frente).
    - **Teto de concorrência** `_MAX_CONCURRENT_FARM = 2` raids em voo; o **2º slot só abre** com
      `_free_ships ≥ _PARALLEL_SHIP_FLOOR` (50) — `_can_launch_attack`.
    - **Anti-detecção**: `_MAX_LAUNCHES_PER_CYCLE = 1` despacho (scout *ou* raid) por ciclo → raids
      paralelos abrem em **wakes consecutivos**, nunca em burst (o despacho ao jogo já é espaçado
      pela sessão *throttled*). `getAvailableShips` lido **≤1×/ciclo** (lazy).
    - **Guarda anti-busy-loop (P0.1)**: `_defer_parallel` adia `_PARALLEL_RETRY_BACKOFF` (7min)
      quando o slot/barcos bloqueiam, preservando o relatório; os agendadores (`has_due_farm`/
      `next_farm_eta`) só retêm o wake de um **raid** quando os 2 slots estão ocupados — um
      **scout** acorda sempre (`_idle_needs_attack_slot`).
  - **Frota (Caso 2)**: um alvo de frota ocupa o slot as 2 vagas (blockade→tropas, horas); com
    ≥50 barcos livres o 2º slot farma um alvo seguro **durante** essa espera — poupa as horas mortas.
  - Testes: `test_spying_target_does_not_block_ready_raid`, `test_second_slot_opens_with_enough_ships`,
    `test_second_slot_blocked_below_ship_floor`, `test_max_two_concurrent_raids`,
    `test_one_launch_per_cycle`, `test_scheduler_withholds_raid_wake_when_slots_full`.

- [~] **P11.11 Capar a raid do farm para não monopolizar a frota** — DESCARTADO (2026-11-04,
      decisão do utilizador). A ideia (capar uma raid para forçar farming paralelo) é o **oposto**
      do desejado: o utilizador quer que o alvo prioritário leve a **frota toda** vaga após vaga
      até secar, e só paralelizar um 2º alvo quando o prioritário estiver praticamente drenado.
      **O comportamento actual já faz isto** por construção: `transporters = ceil(saque/cap)`
      dimensiona a raid para carregar TODO o saque, logo só sobram navios livres (→ 2º slot) quando
      o armazém do prioritário cabe numa só vaga com ≥50 navios de folga — i.e. quando essa vaga o
      **esvazia**. Um prioritário rico pede ≥ frota inteira → 0 livres → zero paralelismo. Nada a
      fazer; capar partiria exactamente a estratégia pretendida. (Reserva de vinho P11.10 à parte.)

- [x] **P11.10×P11.9 Reserva de vinho vs. decisão de paralelismo** ✅ 2026-11-04 — a decisão de
      abrir o 2º slot passou a descontar a reserva de vinho dos navios livres (`_free_ships_once`
      reserve-aware), para o farm nunca paralelizar sobre os barcos reservados ao vinho.

### C — UX
- [x] **P11.6 Linha de alvo unificada** (Fase 3 do `frontend/FEATURES.md`) ✅ 2026-11-04
      (reconciliação — já estava implementado). O `InactivosTab` (Mundo) já tem a linha por alvo
      unificada: pills de pipeline (espiei → `pipeline_ready`/`has_ships`/`warehouse_known`/
      `low_resources`/`failed`), **saque visto** (relatório) + **saque real trazido** por jogador
      (F1.b, `lootByPlayer`), **estado do farm** por alvo (`farmByCity`) e **acções inline**
      (`FarmSettings` embutido, add/remove). `FEATURES.md` Fase 3 estava com o label "POR FAZER"
      desatualizado — corrigido.

### D — Validação in-game *(ver dívidas acima — a mesma lista)*
- [x] Deploy para cidade própria ✅ 2026-11-04 — **bug encontrado e corrigido** (`7b95486`): a 1ª
      tentativa live falhou com type=11 "Não selecionaste nenhuma unidade" porque o formulário de
      deployment indexa as unidades pelo número puro (`304`) e a UI envia o id CSS (`s304`) — o
      `_send_deploy` punha `cargo_army_304=0` e um `cargo_army_s304` que o jogo ignorava. Fix: emitir
      os campos sob o id do próprio formulário, casando a contagem através do prefixo `s`.
      **Confirmado live:** retry às 09:53 saiu com type=10 (`ataque despachado → Própria (Vampiria)`).

### E — Farm: afinação de re-scout e intel de frota *(discussão em curso 2026-11-01)*

Contexto: os três "modos" de atacar um alvo, depois de alinhados com o utilizador:
- **`loop`** (F13) → martela até secar, depois **desliga** o alvo. **Mantém-se como está.**
- **`farm` (actual, pós-P11.7)** → ataca direto entre scouts; **NÃO** re-espia por nº de raids;
  só re-espia quando a estimativa/último regresso seca (drenagem) ou o scout fica stale
  (`spyFreshnessHours`). O `respy_every` deixou de ser usado para alvos seguros.

- [x] **P11.7 Tirar a re-espionagem periódica por nº de raids nos alvos seguros** (o "Caso 1").
      ✅ 2026-11-04 — o núcleo (remover o termo `respy_every` de `_next_round_needs_spy` para
      alvos seguros) já tinha saído a 2026-11-01 (`8efab40d`): um alvo seguro espia 1× no início
      + 1× para confirmar o fim, zero no meio. Fechado agora com o **guard de frescura opcional**
      (belt-and-suspenders): `spyFreshnessHours` (default 24h, 0 desliga) em `_spy_stale` →
      um alvo seguro cujo último scout é mais velho que a janela re-espia 1× antes do próximo
      ataque directo, para não gastar uma vaga num armazém que um co-pilhador possa ter esvaziado
      enquanto o bot esteve offline. Não é segurança (`_confirm_inactive` continua a cobrir
      reactivação) — só poupa 1 vaga. `loop` isento. Schedulers (`_idle_needs_attack_slot`)
      actualizados. Testes: `test_stale_scout_rescouts_before_direct_raid`,
      `test_freshness_guard_disabled_attacks_directly`, `test_spy_stale_predicate`.
  - **Regra do jogo (confirmada 2026-11-01, ver [[reference-ikariam-inactive-no-fleet]])**: um
    inactivo **não produz recursos** → um alvo seguro drenado **NÃO regenera**. Só volta a ter
    loot se o dono reactivar e depois voltar a ficar inactivo. (A ideia anterior de "re-scout por
    tempo/24h para apanhar regen" era falsa — descartada.)
  - **Onde**: `farm_manager.py:112` (`_next_round_needs_spy`), `:121` (`respy_every`), `:882`
    (IDLE), `:1062-1067` (drenado → desliga + `_auto_mark_ignored`).
  - **Hoje**: alvo seguro (`is_fleet_target=0`) ataca direto entre scouts e dimensiona a vaga a
    `_estimated_warehouse`; trava e re-espia quando a estimativa OU o último regresso real cai
    abaixo de `min_loot`; nessa re-espia, se confirmar < mínimo, **desliga + ignora** (ignore
    re-avalia aos 30 dias, `espionage_manager.py:60`). **MAS** re-espia também a cada
    `respy_every=3` raids — desperdício, porque o armazém só desce (nós + co-pilhadores), nunca
    sobe; a estimativa nunca fica optimista por regen.
  - **Proposta**: remover o termo `raids_since_spy >= respy_every` de `_next_round_needs_spy`
    **para alvos seguros** (os termos de frota — `last_enemy_ships>0`, `is_fleet_target==1` —
    ficam). Resultado: espia 1× no início + 1× para confirmar o fim; zero no meio. Segurança
    intacta: `_confirm_inactive` (vista de ilha) corre antes de cada vaga → reactivação desliga o
    alvo; co-pilhador é apanhado pelo primeiro regresso real pequeno. `loop` inalterado.
  - **Opcional (belt-and-suspenders)**: guard de frescura — se `last_spy_at` > X horas (p.ex. após
    downtime do bot), re-espiar antes de atacar, para evitar perder 1 vaga a um co-pilhador que
    tenha mexido no alvo enquanto estávamos offline. Cobre o caso "desliguei o jogo e passaram
    horas". Não é segurança, é poupar 1 vaga.
  - **Ciclo de vida do alvo drenado (confirmado 2026-11-01 — JÁ IMPLEMENTADO na camada Mundo)**:
    regra do jogo — uma conta inactiva durante muito tempo é **apagada** pelo jogo. Comportamento
    desejado = drenado fica ignorado 30-60d → expira → reaparece no Mundo **se** ainda estiver no
    world scan, senão desaparece. Isto já existe: `_auto_mark_ignored` põe `expires_at = now +
    ignoreExpiryDays` (default 30, `app.py:78`); `app.py:539` levanta o ignore quando expira (volta
    a "novo"); a vista do Mundo é guiada pelo scan, logo conta apagada (ausente do scan) não
    aparece. **Decisões/gaps**: (a) subir o default de `ignoreExpiryDays` 30 → **60**? (só setting);
    (b) **limpeza-fantasma (NOVO)** — a linha `farm_targets` drenada fica `enabled=0` para sempre
    (o `farm_remove` só é chamado pela UI, `app.py:1415`); acrescentar: linha desligada cuja cidade
    está ausente do world scan → `farm_remove` (apaga o alvo morto); (c) reaparecer no Mundo ≠
    re-farmar automático — o utilizador re-adiciona (comportamento actual, provavelmente desejado).

- [~] **P11.8 Distinguir fleet-target verdadeiro de falso positivo via sinal de combate** (os
      "Casos 2/3"). **DESCARTADO (2026-11-01)** — ver veredicto no fim do item. *Eficiência, NÃO
      segurança — não urgente.*
  - **Achado**: `is_fleet_target` é **write-once** — posto a 1 (bounce sem saque `:1217`; frota
    vista `:788`; combate acima do máximo `:1080`) e **nunca** limpo a 0, apesar do comentário em
    `:874-881` prometer que "um full scout põe a 0" (nunca foi implementado).
  - **Pela regra do utilizador** (os navios do jogador são permanentes: dispersam e voltam, nunca
    morrem), um fleet-target verdadeiro **deve** ficar `=1` para sempre — limpar com base num scout
    limpo seria errado (a frota só está dispersa). Correcto por desenho.
  - **Problema residual**: o setter `:1217` marca `=1` sempre que um regresso não traz saque
    **registado** — o que também dispara em falsos positivos (regresso não logado, match de nome
    falhado, `get_loot_log` a rebentar, ou armazém mesmo vazio). Esses alvos pagam a cadeia de 3
    espionagens para sempre à toa. Evidência (01/11): Lançassolar/Braavos/Jardim/Valíria todos
    ~208k, marcados; Lançassolar com ricochete naval **confirmado in-game** (29/10).
  - **Proposta (era)**: parsear o resultado de combate real a partir dos movimentos, só para
    acrescentar confiança (nunca substituindo o heurístico "sem saque → marca frota").
  - **INVESTIGADO E DESCARTADO (01/11)**: captura do schema cru de `militaryAndFleetMovements`
    (feito passivamente, piggyback no ciclo). O `event` expõe só estado do movimento (`missionText`
    ex.: "Pilhar (Voltar)", `missionState`, `isFleetReturning`, `isInFight`/`isCombatant`
    transitórios) — **nenhum campo de resultado de combate**. Um ricochete é indistinguível de um
    regresso vazio neste feed (só difere no saque, que já usamos). A mensagem "combate marítimo"
    vive no sistema de **relatórios de combate**, que o ikabot não lê de todo → seria um subsistema
    novo e frágil (endpoint + parsing narrativo + i18n), e só daria eficiência, não segurança.
    **Veredicto: não construir.** O over-flagging actual é seguro (peca por excesso, nunca
    desprotege) e é o custo aceite. Fecha o Caso 2.

- [x] **P11.10 Prioridade/reserva de navios para o vinho sobre o farm** (incidente 2026-11-04).
      ✅ 2026-11-04 — implementada a opção (c): **reserva simétrica à `shipReserveEnabled` do farm,
      mas a favor do vinho**.
  - **Problema observado**: a DeathCrow desceu a ~2h de autonomia porque o farm monopoliza os
    transporters (raids na própria ilha reciclam a frota em permanência). Um transporte urgente de
    vinho falhou **3× seguidas** ("sem navios livres") e o balanceador de vinho (F9) sofre do mesmo —
    nenhum consegue navios enquanto o farm os agarra assim que regressam. Só saiu via **freighter**
    (pool separado que o farm não usa).
  - **Implementado**:
    - `transport_manager.wine_ship_reserve()` — **piso permanente** (decisão do utilizador
      2026-11-04, não condicional à autonomia): reserva sempre `reserveShips` (default **5**) navios
      de comércio para o vinho, fora do alcance do farm. O farm continua a usar tudo acima do piso.
      Barato de chamar no caminho do farm (sem HTTP).
    - Os ataques do farm levam a flag `respectWineReserve`; `_dispatch_attack` consulta a reserva e
      passa-a a `_cap_to_available_ships(..., reserve=N)`, que cede N navios ao vinho. Se a reserva
      consumir tudo, a pilhagem devolve `_DEFER` (reagenda limpo, sem contar como falha). Ataques
      **manuais da UI não levam a flag** → mantêm prioridade total, como o utilizador quer.
    - Settings no card de vinho (`reserveShipsFromFarm`, `reserveBelowHours`, `reserveShips`):
      `/api/transport/wine` GET/POST + toggle/inputs no `TransportTab`. Schema de validação
      actualizado.
    - Simétrico ao `apply_ship_reserve` do farm (que faz o vinho ceder ao farm): agora o farm cede
      ao vinho quando há défice. Não estrangula o farm — só cede quando há poucos navios E uma
      cidade baixa; com navios de sobra o farm continua a correr.
  - Testes: `test_wine_reserve_bites_when_city_low`, `test_wine_reserve_zero_when_all_comfortable`,
    `test_wine_reserve_off_switch`, `test_wine_reserve_catches_dry_city`,
    `test_cap_to_available_ships_honours_wine_reserve`, `test_farm_item_yields_ships_to_wine`.

---

## Caso 2 (alvos de frota) — FECHADO 2026-11-01

Alvo de frota = `is_fleet_target=1` (porto com frota que foge-e-volta). Estado final:
- **Motor — ETA real da frota** (`14b8d5b`): a cadeia de espionagem warehouse→garrison→**movimentos**
  lê o regresso real da frota inimiga (`_enemy_return_from_movements`) e alimenta `enemy_return_at`,
  em vez do palpite fixo `disperse_min`. Confirmado a funcionar ao vivo (Martelo).
- **Sender do blockade** validado pela captura do formulário real (01/11, read-only, sem ataque):
  view `blockade`, função `sendFleetOnBlockade`, campos `cargo_fleet_<id>_upkeep`, e o nosso
  loadout (`s216`→`216`) **bate** com os ids do formulário — zero mismatch. Fix do fallback do nome
  da função (`sendFleetBlockadeSea`→`sendFleetOnBlockade`), que não mordia mas estava errado.
- **Timing das duas vagas** (`farm_manager.py:812-844`) validado: barcos saem já; tropas agendadas
  para **chegar `fleet_lead` (5min, +20min se há combate) depois dos barcos chegarem**, com tempos
  reais dos formulários; nunca esperam a confirmação do blockade (desenho intencional — barcos
  demoram horas; o alvo é pré-validado). Edge cases (tropas mais rápidas/lentas) seguros.
- **Prioridade**: Caso 1 (alvos seguros) corre **sempre primeiro**; os alvos de frota são os últimos
  da fila (decisão do utilizador — um blockade é sempre mais lento/caro). Não há aging.
- **Não acoplar tropas↔sucesso do blockade**: rejeitado (quebraria a janela de timing).
- **Resíduo aceite**: se o *dispatch* do blockade falhar (raro, sender validado), as tropas saem na
  mesma → ricochete que auto-corrige. O utilizador aceita (pré-valida o alvo).
- **Validação ao vivo**: o blockade dispara naturalmente quando os alvos seguros secarem
  (prioridade); o diagnóstico de "ids ausentes do form" (em `_send_fleet_blockade`) apanha o
  primeiro real para confirmação de 100%.

---

## P12 — Pós-reconciliação (2026-11-04)

### Feito

- [x] **P12.1 Seed de porto-limpo ao adicionar alvo ao farm** ✅ 2026-11-04
      (`farm-add-seed-clean-port`, commit `0ee238e`). O `_seed_farm_target_intel` (em `app.py`,
      chamado por `/api/farm/add`) já semeava `last_loot` + `last_troop_journey` dos relatórios
      existentes (ranking). Passou a semear também a **confirmação de porto-limpo**
      (`is_fleet_target=0`, `last_enemy_ships=0`, `last_spy_at` = hora REAL do relatório) quando há
      um relatório de **guarnição `success=True` com 0 navios** (`_seed_garrison_fleet_count`) **e**
      um saque conhecido → o alvo seguro **ataca direto, sem re-espiar** intel que já temos. NÃO sela
      se houver qualquer navio (fica fleet-target — o timing da frota importa), se o scout de
      guarnição falhou, ou se não há saque. Como `last_spy_at` leva a hora real, o guarda de frescura
      (`_spy_stale`, 24h) re-espia sozinho quando a intel envelhece. Motivou-o o utilizador: re-espiar
      um alvo seguro de que já temos relatório fresco é desperdício. ⚠️ `attack_manager` (fonte de
      `_NAVAL_UNIT_NAMES`) não está montado no gui → `app.py` tem cópia `_SEED_NAVAL_KEYWORDS`, com
      teste-espelho. Só o caminho UI/API semeia; `db.farm_add` cru não. **350 testes.**
      ⚠️ **Revisto pelo P12.2 (2026-11-05):** o selar de porto-limpo foi REMOVIDO — era fail-open
      (ver abaixo). O seed continua a semear saque/jornada (ranking), mas já não marca segurança.

- [x] **P12.2 Primeiro scout = varrimento triplo; seed deixa de selar porto-limpo** ✅ 2026-11-05
      Motivado por um bounce real: um ataque do farm a **Tróia 3** (MARCOS LIMA, saque 5.5M) chegou
      ao alvo e **regressou vazio** — ricochete naval contra a frota local, "o tipo de situação que
      queríamos evitar". **Causa-raiz**: Tróia 3 **nunca** teve um scout de guarnição vivo; o
      `is_fleet_target=0` / `last_enemy_ships=0` veio **só do seed P12.1**, a partir de um relatório
      antigo que mostrava 0 navios **porque a frota estava no mar** (numa pilhagem / expulsa por outro
      atacante e a regressar). O seed selou "porto limpo" com base numa fotografia desatualizada,
      violando o invariante que o ataque directo assume (`farm_manager.py`: *"só um scout completo põe
      `is_fleet_target=0`"*). E um alvo "seguro" nunca re-espia o cais (só o armazém), por isso a frota
      ficou invisível até as tropas ricochetarem. **Correção** (ideia do utilizador):
      - **`farm_manager.py` — primeiro scout vivo = varrimento completo**: `need_movements` deixou de
        estar amarrado só a `is_fleet_target=1` — corre também no **primeiro contacto**
        (`last_spy_at==0`). A 1ª espionagem passa a ler **armazém + guarnição + movimentos**; um alvo
        só é confirmado seguro quando as três pernas vêm limpas. Uma frota no mar aparece na perna de
        movimentos mesmo com o cais a 0.
      - **`farm_manager.py` — reclassificação imediata**: quando os movimentos revelam frota a regressar
        (mesmo com guarnição a 0 agora), o alvo passa logo a `is_fleet_target=1` → o atalho de ataque
        directo nunca mais dispara nele.
      - **`app.py` — o seed NÃO sela porto-limpo**: removido o bloco que punha `is_fleet_target=0` /
        `last_enemy_ships=0` / `last_spy_at`. `last_spy_at` fica a 0 → o farm faz sempre o seu próprio
        varrimento vivo antes de atacar um alvo novo. O seed de saque/jornada (ranking) mantém-se.
      - **Mitigação imediata** (DB): Essos (estava selado pelo seed, mesmo risco) e Fidel repostos a
        primeiro-contacto; Tróia 3 pré-marcado `is_fleet_target=1`.
      - **Testes**: +2 (primeiro contacto pede movimentos; guarnição limpa + frota a regressar →
        `is_fleet_target=1`) e 2 testes do seed invertidos. **353 testes.**

- [x] **P12.3 Scout incompleto nunca autoriza ataque directo** ✅ 2026-11-06
      Segunda ricochete real em **Tróia 3** (06/11): o farm despachou tropas apesar de o varrimento
      **não** estar confirmado — o utilizador recolheu o ataque à mão. **Causa-raiz** (dois buracos no
      gate de decisão, `farm_manager.py` ramo SPYING):
      - **A — scout falhado lido como "porto limpo"**: o parser (`espionage_parsers.py`) só põe
        `success=True` quando o relatório diz *"completada com sucesso"*. O relatório de guarnição do
        Tróia 3 veio **`success:false`** com `troops:{}` (espião rejeitado/suspeito). Mas
        `garrison_known = ("troops" in gres) and (error is None)` **não** olhava para `success` → o
        `{}` de um relatório falhado passou como "0 inimigos" e atacou.
      - **B — movimentos nunca corridos tidos como "sem frota"**: o espião reutilizado "regressou antes
        dos movimentos" → `movementsResult: null`. Nada exigia que a perna de movimentos tivesse
        **corrido** antes de mandar tropas num alvo de frota.
      **Correção**: um alvo de frota **ou** um primeiro contacto (ambos pedem `needMovements`) só
      autoriza tropas após um varrimento **completo confirmado** — `garrison_known` passa a exigir
      `gres.get("success")` (default `True` só para relatórios importados, que vêm sempre de scouts
      bem-sucedidos), e `movements_ok` exige `movementsResult is not None` quando `needMovements`.
      `needs_full_sweep and not (garrison_known and movements_ok)` → re-espia, nunca ataca às cegas
      (com o streak de falhas a saltar a ronda ao fim de N). `app.py`/import semeia agora
      `garrison_result["success"]=True` para coerência. **Mitigação**: `force_fresh_spy=1` no Tróia 3
      (os espiões estacionados expiravam antes dos movimentos). **Testes**: +4 (guarnição falhada não
      ataca; movimentos não corridos não atacam; primeiro contacto incompleto não ataca; varrimento
      completo e limpo **continua** a atacar). **357 testes.**

### Por fazer

- [ ] **F14 — Construção autónoma de espiões** (pedido do utilizador 2026-11-04: *"o bot construir
      os espiões sozinho isso era excelente"*). **Alta prioridade / valor; esforço médio-alto.**
      - **Hoje**: o bot **só despacha/recolhe** espiões — **não os constrói** (confirmado no código:
        não há função de recrutamento; `spy_counts.py`/`empire_collector.py` só *lêem* a casa de
        espionagem). O treino dos ~179 "em treino" vistos em produção é **manual do utilizador**.
      - **Objectivo**: o bot mantém um **alvo de espiões por cidade** (p.ex. ≥N em defesa), e recruta
        automaticamente para lá chegar, consumindo o cristal que já garantimos em cada cidade (o
        trabalho dos transportes de cristal foi precisamente para isto).
      - **A descobrir/definir (pré-requisitos antes de escrever código)**:
        1. **Endpoint do jogo** para recrutar espiões (acção na Casa de Espionagem / Esconderijo) —
           auto-descobrir pelo formulário, como se fez para `sendArmyPlunderSea`/`sendFleetOnBlockade`
           (nunca hardcode; logar os inputs). `type=10/11` feedback.
        2. **Custo e travões** — cristal (glass) + ouro + tempo; piso de ouro, cap por ciclo, alvo
           por cidade (settings + UI, como o comprador de vinho). Nunca esgotar recursos de guerra.
        3. **Anti-detecção** — recrutar dentro das horas activas, com os delays da sessão *throttled*;
           não fazer bursts.
        4. **Capacidade** — a Casa de Espionagem tem limite por nível; respeitar e, opcionalmente,
           ligar à fila de construção (subir o edifício quando o limite trava o alvo).
      - **Interacções**: fecha o ciclo com os transportes de cristal (F9/manual) e com o farm (mais
        espiões = menos falhas de "insuficientes" e mais presença estacionada contra contra-espionagem).
      - **Validação live obrigatória** (gasta recursos): primeiro em dry-run/preview, depois 1 recruta
        supervisionado, como todas as acções que mexem no jogo.

- [x] **F15 — Notificações melhores em tudo: Telegram + Discord** ✅ 2026-11-13 (pedido do utilizador 2026-11-13:
      *"logs telegram e logs discord melhores em tudo"*). **Prioridade média; esforço médio.**
      - **Hoje** (verificado 2026-11-13): há **dois sistemas paralelos**:
        - **Nosso** `telegram_notifier.py` — só Telegram, HTML, 15 eventos (arranque, construção,
          transporte, vinho crítico, ataques, farm, saque, subsistemas, fatal, offline). Credenciais em
          `telegram_settings.json`/env. É o que está activo em produção.
        - **Stock do ikabot** `helpers/botComm.py` — **já suporta Discord e Telegram**: `sendToBot()`
          envia para os dois (`sendToDiscord` = POST `{"content": msg}` ao webhook). Config em
          `~/.ikabot/global.json` (`shared.discord.webhookUrl`, `shared.telegram.botToken/chatId`),
          definida pelo menu do bot (21 → Discord/Telegram, com teste). Usado pelos módulos stock
          (`decorators` erros, `autoBarbarians`). **Hoje ambos vazios** em `global.json`.
        - Limites do stock: texto simples (sem embeds/cores), síncrono sem timeout, prefixa
          pid/servidor/jogador em todas as mensagens, sem níveis/filtros/dedup/resumos.
      - **Conclusão: NÃO reconstruir do zero.** Reaproveitar a config de Discord do stock
        (mesma `webhookUrl`, uma única fonte de verdade) e acrescentar o canal Discord ao nosso
        notifier; o que se constrói é só a camada de qualidade (formato, cobertura, filtros, resumos).
      - **Fase 1 ✅ 2026-11-13** — Discord ligado ao nosso notifier: `_send(text, level)` faz fan-out
        Telegram + Discord (canais isolados; devolve `{canal: True|False|None}`); embeds com título,
        descrição em markdown, cor por nível (info/success/warning/error/critical) e timestamp; cada
        `notify_*` marca a sua gravidade. Webhook: `telegram_settings.json` (`discordWebhook`) →
        env `DISCORD_WEBHOOK_URL` → `global.json` do stock (só o bot o lê). UI: card "Notificações
        (Telegram + Discord)" com campo do webhook (validado no Flask) e teste por canal. Validado
        live (embed recebido no Discord). **+11 testes → 440.** Falta: pontos 2, 4, 5, 6 (cobertura,
        filtros por canal, anti-spam/resumos, toggles na UI).
      - **Fase 2 ✅ 2026-11-13** — cobertura + filtros por canal. Novo nível `activity` (o mais baixo,
        eventos rotineiros) e piso por canal (`telegramMinLevel` default `info` → o Telegram mantém o
        volume de antes; `discordMinLevel` default `activity` → o Discord recebe tudo), com select no
        card. `notify_once/clear_once` generaliza o dedup por condição. Eventos novos: espiões que
        passam a FAILED (diff central no `_save_missions`; capturados/desaparecidos = `warning`, resto
        `activity`), 1.º varrimento verificado de um alvo do farm (`info`), comprador de vinho
        (compra `success`, simulação `activity`, travões ouro-no-piso/sem-navios `warning` 1× até
        destravar), balanceador (1 mensagem por passagem), transporte agendado enviado, consolidação
        e world scan concluídos (`activity`). Nomes do jogo escapados (`_esc`) nos eventos novos. O
        teste da UI ignora os pisos (`force`). **+8 testes → 447.** Falta: resumo periódico (5),
        filtros por categoria, escapar os nomes nos alertas antigos, reserva de navios a travar o farm.
      - **Fase 3 ✅ 2026-11-13 — F15 fechado.** (a) **Categorias** em todos os 23 alertas (`combat`,
        `farm`, `spy`, `wine`, `transport`, `build`, `system`, `digest`); cada canal silencia as que
        quiser (`telegramMuted`/`discordMuted`, chips no card); **crítico nunca é silenciado**.
        (b) **Resumo periódico** `maybe_send_digest()` no `smart_sleep` (sem pedidos ao jogo):
        `digest` off/hourly/daily (default **daily às 21h**, `digestHour`); contadores em
        `notify_digest.json` (sobrevivem a restarts) — raids/falhados, saque por recurso, alvos
        varridos/drenados, espiões perdidos/missões falhadas, vinho comprado/ouro, construções,
        transportes, ataques recebidos, falhas de subsistema. 1.ª chamada só arma (sem resumo logo
        após deploy); horário salta horas sem actividade, diário envia sempre. (c) **Nomes do jogo
        escapados** (`_esc`) em todos os alertas antigos (um `<`/`&` no nome fazia o Telegram
        rejeitar a mensagem). (d) **Farm à espera da reserva de vinho** — alerta 1× por episódio
        quando há navios para uma raid mas a reserva de vinho os tira abaixo do piso; re-arma
        quando a raid volta a ter navios. Flask valida categorias/modo/hora. **+7 testes → 454.**
      - **Objectivo**:
        1. **Estender o `telegram_notifier.py`** (não um módulo novo): `_send` → fan-out Telegram +
           Discord. Webhook lido de `global.json` do stock (`shared.discord.webhookUrl`), com override
           opcional no nosso settings. Os `notify_*` actuais ficam iguais. Discord = POST ao Discord,
           **não** ao jogo → sem sleep anti-detecção, mas timeout curto e sem bloquear o loop.
           Configurar o webhook **uma vez** serve as duas coisas: os módulos stock passam a mandar para
           o Discord via `sendToBot` e os nossos eventos também.
        2. **Cobertura em tudo** — eventos em falta: espiões (despacho/regresso/capturados/falhas,
           varrimento completo de alvo novo), comprador de vinho (compras, travões a disparar,
           dry-run), balanceador de vinho, transportes concluídos, reserva de navios a travar o farm,
           world scan concluído, sessão/login renovado, F14 (espiões recrutados) quando existir.
        3. **Formato rico**: Telegram em HTML (negrito, cidades/jogadores, números `_pt_int`);
           Discord em *embeds* (cor por nível: info/sucesso/aviso/erro, campos, timestamp).
        4. **Níveis e filtros**: por canal e por categoria (farm, vinho, espiões, construção,
           sistema, combate); p.ex. Discord recebe tudo, Telegram só aviso+erro e alertas de combate.
        5. **Anti-spam**: dedup/cooldown por chave (generalizar o dedup actual), agregação em
           **resumo periódico** (p.ex. horário/diário: saque total, raids, vinho comprado, espiões
           perdidos, construções) em vez de uma mensagem por raid.
        6. **Settings + UI**: toggles por categoria/nível e horário do resumo no nosso settings +
           card no `SettingsPage` (webhook Discord + "enviar teste"). O webhook é escrito no
           `global.json` do stock (ou só lido de lá, se configurado pelo menu 21) — sem duplicar.
      - **Testes**: formatação por canal (golden), roteamento por nível/categoria, dedup/cooldown,
        falha de um canal não afecta o outro nem o loop do bot.
