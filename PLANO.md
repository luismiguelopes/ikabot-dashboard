# PLANO — ikabot (criado 2026-06-11, após auditoria completa do código)

Estado (2026-10-29): **P0-P10 concluídos** + backlog da auditoria (B1-B10, F1, F11) feito ou
descartado conscientemente (B5, B8 saltados). Extras recentes: supervisor do worker (relança o
bot em segundos em vez de ~36 min via autoheal), credenciais por env em vez de argv, **F13 —
loop de drenagem** (ataque agressivo a um alvo até secar; ver FEATURES.md) e **P10 — robustez do
farm e da espionagem** (fixes de intel obsoleta/rejeitada em alvos de frota, retenção de missões,
watchdog de construção, imunidade ao sleep do host; ver secção P10). Bot em produção no
**ikabot 7.7.2** (pinado por digest `6224352e`), sessão persistente, self-healing e backups activos.
**305 testes a passar.**
Trabalho de código: nada pendente. Em aberto só **dívidas de validação in-game** (precisam de
sessão supervisionada, não é código): deploy para cidade própria; reescrita do farm nunca correu
supervisionada live. Auto-attack foi **descontinuado** (P6.2) — ignorar itens antigos que o referem.

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
- [ ] Validar deploy para cidade própria (após 1 ciclo do império, para o islandId
      aparecer no own_cities.json): dispatch com destino "própria" → deployArmy type=10.
- [ ] Validar in-game toda a reescrita do farm (2026-06): fila pura (drenar 1 alvo),
      flee-fleet bloqueio→tropas (F4.b), ataque-directo + confirmação de inactividade (F4.e).
      Nunca correu live — código completo e testado, validação real em dívida.
- [ ] Validar o self-healing (P5.1): `docker compose up -d`, confirmar o `ikabot` a ficar
      `healthy` e o container `ikabot-autoheal` a correr com acesso ao docker.sock.

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
- [ ] Deploy para cidade própria (DispatchTab → destino "própria" → deployArmy type=10).
- [ ] Reescrita do farm supervisionada live. *(parcialmente exercitada: os fixes P10.4–P10.7
      saíram de incidentes reais em produção, logo o caminho de frota já corre live — falta uma
      sessão supervisionada de ponta a ponta.)*

---

## P11 — Roadmap candidato (auditoria a frio 2026-10-29)

Auditoria de todo o projecto com P0-P10 concluídos, 305 testes a passar, zero TODO/FIXME, build
do frontend fresco e git limpo. **Veredicto: o projecto está maduro e estável** — não há bugs
abertos nem trabalho de código pendente. O que resta é dívida de manutenibilidade, validação live
e afinação operacional. Ordenado por valor/risco. Nenhum item é urgente.

### A — Operacional / estratégia *(config, não código — decisão do utilizador)*
- [ ] **P11.1 "Espiões insuficientes: 2 na cidade, 10 pedidos"** (~36× nos logs). O pre-check já
      envia com os que houver (F11), mas pedir 10 com 2 disponíveis desperdiça rondas. Decidir:
      baixar o nº de agentes por omissão **ou** treinar mais espiões nas cidades de origem.
- [ ] **P11.2 Clusters "possivelmente capturado"** (HEFESTO×3, Jaka, Triplex do Lula). Contra-
      espionagem do alvo. Decidir por alvo se vale continuar a espiar (queima espiões) ou marcar
      ignorar.

### B — Manutenibilidade *(dívida técnica real, risco baixo)*
- [ ] **P11.3 Observabilidade e tamanho do `ikabot_gui/app.py`** (2049 linhas, 53 `except
      Exception`). O bot tem `health_guard`/`health.json`; a camada Flask não tem equivalente — um
      endpoint que engole um erro fica invisível. Candidato: split por blueprints + um wrapper de
      erro uniforme que registe falhas. Maior ficheiro do projecto, sem plano até agora.
- [ ] **P11.4 Reavaliar o split do `espionage_manager.py`** (1971 linhas; B8 foi saltado em
      2026-09). Mudou o contexto: agora há `test_espionage_state_machine.py` (rede de segurança) e
      o caminho de frota já corre live. Uma extracção mínima (contagem de espiões / fetch de counts)
      é agora mais segura do que era. Continua opcional — só se o módulo voltar a doer.
- [ ] **P11.5 Split do `DispatchTab.tsx`** (1229 linhas, maior componente). Dispatch manual + fila
      + histórico + saque + farm num só ficheiro. Extrair sub-painéis como já se fez na MundoPage.

### C — UX
- [ ] **P11.6 Linha de alvo unificada** (Fase 3 do `frontend/FEATURES.md`). Fundir o pipeline do
      Mundo com saque-por-alvo/histórico numa vista por alvo: espiei → saque visto → saque real
      trazido → estado do farm + acções inline.

### D — Validação in-game *(ver dívidas acima — a mesma lista)*
- [ ] Deploy para cidade própria; sessão supervisionada de ponta a ponta do farm.
