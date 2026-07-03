# PLANO — ikabot (criado 2026-06-11, após auditoria completa do código)

Estado: **P0-P3 concluídos** (P0-P2 em 2026-06-11, P3 em 2026-06-12). Army e fleet
dispatch validados in-game ✅; auto-attack e deploy para cidade própria por validar.
Testes: 62/62 a passar (db, queue, attack_queue, espionage_parsers, military_parser).

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
- [ ] Validar a primeira vaga do auto-attack (agora usa sendArmyPlunderSea).
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
- [ ] **P6.7 Calibrar tempos de viagem.** ETA do DispatchTab e espaçamento de vagas do
      auto-attack usam a estimativa fixa (1200s×distância, ⅔ tropas) sem bónus
      (Poseidon, etc.). O farm já usa tempos reais; guardar o rácio real/estimado das
      viagens observadas (loot_log/movements) e aplicar como factor de correcção.

### Bloco C — UX e operação (conforto, sem risco)

- [ ] **P6.8 Feedback de acções da UI.** Botões (force scan, run now, dispatch) escrevem
      flag/fila e o toast diz "ok" = "enfileirado", não "feito". Mini-feed "última acção
      → estado" (enfileirado/executado/falhou) alimentado pelas filas SQLite + logs.
- [ ] **P6.9 Autenticação simples no dashboard.** Flask/Vite servem na LAN sem login —
      qualquer dispositivo na rede pode lançar ataques/pausar/apagar. Token partilhado
      ou basic auth no Flask (e proxy do Vite) chega.
- [ ] **P6.10 Split da MundoPage.** 1751 linhas com identidade dupla: world scan
      (inactivos/ilhas/ignoradas) + centro de combate (dispatch/farm/histórico); o
      DispatchTab (1222) serve 3 vistas. Promover "Combate" a página própria no sidebar
      e partir os componentes (sem mudar comportamento).
- [ ] **P6.11 Build de produção do frontend.** `npm run dev` (Vite dev server) como
      serviço permanente; `vite build` + servir estático pelo Flask elimina um
      container e o overhead de HMR. (O auto-reload do Flask já mordeu com inodes —
      manter a regra de restart.)
- [ ] **P6.12 Testes do Flask.** 1684 linhas sem um único teste (venv nem tem flask).
      Instalar flask no venv de testes + testes dos endpoints críticos: merge de marks,
      farm update/unignore, filas, /api/health.
