# FEATURES — backlog de funcionalidades

> Catálogo de features candidatas, por área e ordem de valor estimado.
> O plano de execução activo está no PLANO.md (P4 aponta para este ficheiro).

## ⚔️ Combate / pilhagem

### F1. Histórico de ataques ✅ IMPLEMENTADO 2026-06-12
Tabela SQLite `attack_log` (schema v5) com cada tentativa de dispatch: alvo, origem,
unidades, transporters, tipo (army/fleet, own/enemy), fonte (manual/auto), resultado
e texto de erro do jogo. Regista manuais E vagas do auto-attack.
UI: cartão "Histórico de despachos" no DispatchTab com filtro por alvo/jogador.
API: `GET /api/attack-log?limit=&target=`.
### F1.b ✅ IMPLEMENTADO 2026-06-13
Estatísticas de saque real por alvo. `_collect_movements` deteta frotas próprias a
regressar de cidades de outros jogadores com recursos (saque) e regista-as em `loot_log`
(schema v6), deduplicadas pela hora de chegada. Cartão "Saque por alvo" no separador
Ataque (total + nº de ataques + último, por jogador). API: `/api/loot-stats`, `/api/loot-log`.
⚠️ Best-effort: uma ida-e-volta curta entre ciclos de movimentos pode escapar.

### F2. ETA de chegada no DispatchTab ✅ IMPLEMENTADO 2026-06-12
Painel de ETA no formulário: tempo de viagem estimado + hora de chegada, replicando
o modelo do bot (`_calc_travel_secs`: mesma ilha ≈10 min; senão 1200s×distância para
frota, ⅔ para tropas em transportes). Inclui o 4º modo de agendamento **"Chegar às"**:
escolhe-se a hora de chegada desejada e a partida é calculada ao contrário
(client-side; o backend recebe um `at` normal). Rola para o dia seguinte se a
partida calculada já tiver passado.
⚠️ Estimativa — não considera bónus de velocidade (Poseidon, etc.); calibrar com
os tempos reais do jogo se divergir.

### F3. Validação de capacidade de saque ✅ IMPLEMENTADO 2026-06-16
No dispatch manual (army), painel que compara a capacidade dos transportes escolhidos
com o saque conhecido do alvo (último relatório de espionagem): verde se chega, laranja
+ nº de navios necessário + botão "navios p/ saque" se ficar curto. ship_cap adicionado
ao statusSummary; saque do alvo das missões DONE.

### F4. Farming de alvos (ciclo completo) ✅ IMPLEMENTADO 2026-06-13
`farm_manager.py`: máquina de estados por alvo (SQLite `farm_targets`, schema v7)
IDLE → SPYING → ATTACKING → IDLE. Reutiliza a fila de espiões (re-espia ao chegar a
hora), avalia o saque fresco e, se compensar (≥ minLoot, frota inimiga ≤ maxEnemyShips,
existe origem com tropas), enfileira o ataque na fila de ataques (frota primeiro se
tier 2). Espera o regresso estimado e repete a cada intervalHours.
- UI: botão "adicionar ao farm" no alvo do separador Ataque + cartão de gestão
  (toggle, correr-já, remover, estado, saque/ataques).
- API: `GET /api/farm`, `POST /api/farm/{add,update,remove}`.
- Alvos em farm são excluídos do auto-attack one-shot (evita ataques duplos).
- Respeita pausa e horas activas. Desligado por defeito (sem alvos).
- **Tropa mínima configurável** (2026-06-15): loadout `{unitId: qty}` em
  `farm_settings.json`, editável no cartão do farm. Em cada ataque envia min(loadout,
  disponível na origem) — só as tropas escolhidas, não todas. A origem é a cidade mais
  próxima que tenha pelo menos uma das unidades da loadout. Vazio → comportamento antigo
  (todas as tropas). API: `GET/POST /api/farm/army`.
- **Event-driven + cadência real** (2026-06-15, schema v8): o farm deixou de avançar só
  no ciclo horário e de usar intervalo fixo. Agora:
  - corre no `smart_sleep` (≤60s de latência) com `has_due_farm()` preciso (sem busy-loop);
  - o bot **acorda no momento exacto** do regresso das tropas (`next_farm_eta()` entra no
    cálculo de sleep), em vez de dormir até ao próximo ciclo;
  - a cadência é o **tempo real de ida-e-volta**; ao regressar relança com delay
    aleatório **1-15 min** (não 8h);
  - `attack_return_at` é refinado lendo os movimentos reais (`movements.json`);
  - **re-espia só de N em N ataques** (`respy_every`, default 3): entre scouts ataca
    directamente com o último intel (origem/transportes/saque), poupando o ida-e-volta do
    espião. Alvos que mostraram frota forçam re-espionagem sempre.
  - `interval_hours` passou a ser o backoff quando uma ronda é saltada (saque baixo,
    timeout de espião, sem origem).
⚠️ Por validar in-game o ciclo completo.

### F4.c Prioridade do farm sobre a logística interna ✅ IMPLEMENTADO 2026-06-17
Os barcos de comércio são o MESMO pool usado para pilhar e para mover recursos entre
cidades próprias. A logística interna (consolidação, vinho, transportes de construção)
varria a frota e esfomeava o farm — que é quem gera recursos e cujos ataques são
time-sensitive. Solução em duas camadas:
- **Reserva de navios** (`farm_manager.farm_ship_reserve`): conta os ataques de pilhagem
  já em fila + os alvos em farm cujo próximo ataque fica due dentro do horizonte
  (`reserveHorizonMin`, default 45 min; alvos já em ATTACKING não contam — os navios já
  saíram). A logística interna só pode usar `disponíveis − reserva` barcos de comércio e
  recorre a **cargueiros** para o resto (`apply_ship_reserve`). Aplicada em
  `_try_transport` (construção), `process_consolidation` e `process_wine_balancer`
  (este último com **bypass** quando uma cidade está com vinho crítico <6h). Garante que
  o farm nunca fica sem navios, independentemente da ordem dos ciclos.
- **Reordenação**: no ciclo completo (`empireFunction`) e no `smart_sleep`, a receita
  (espionagem → ataques → farm) corre ANTES da logística interna.
- UI: toggle "Reservar navios para o farm" + horizonte no separador Farm. Settings em
  `farm_settings.json` (`shipReserveEnabled`, `reserveHorizonMin`); o POST `/api/farm/army`
  passou a fazer merge (não apaga as chaves da reserva). Testes em `test_farm_reserve.py`.

### F4.d Fila pura: drenar um alvo de cada vez ✅ IMPLEMENTADO 2026-06-18
Os logs mostraram o farm a tentar pilhar vários alvos em paralelo a partir de uma só
cidade (Baphomet, 337 barcos): um alvo saturava a frota toda e os outros ficavam em loop
"relatório pronto mas 0 navios" a re-espiar de 5-15min sem nunca atacar (desperdício +
padrão robótico). Substituído por uma **fila pura** (`farm_manager`):
- **Um alvo activo de cada vez** (`_queue_head`): o que está a meio (SPYING/ATTACKING) ou,
  se todos IDLE, o de maior **saque/hora** (`_priority_score = last_loot / round_trip`;
  `round_trip` = `last_troop_journey×2` real quando conhecido, senão 4h). Os restantes
  esperam — não espiam nem atacam → acaba o loop e a competição por navios.
- **Prioridade dinâmica**: re-ordena à medida que novas espionagens actualizam `last_loot`;
  não espera por espiar todos (alvos sem intel entram por ordem e são espiados quando chegam
  à cabeça — a state machine espia sempre antes de comprometer tropas).
- **Drenar até `min_loot`**: quando o saque espiado cai abaixo do mínimo, o alvo é
  **desactivado de vez** (`enabled=0`) + alerta Telegram (`notify_farm_drained`), e a fila
  avança para o próximo. `has_due_farm`/`next_farm_eta` passaram a olhar só a cabeça da fila.
⚠️ Por validar in-game.

### F4.b.2 Frota que foge: bloqueio→tropas com tempos reais ✅ IMPLEMENTADO 2026-06-17
Para alvos cuja frota foge ao ser bloqueada (lanchas, reparadores — não combatem) e volta
horas depois. Validado com dados reais in-game (dev tools) do The Rock:
- **Reconhecimento de frota** refeito (`_NAVAL_UNIT_NAMES`) com os 11 navios PT, chaves
  sem colisão com tropas terrestres (Aríete vs Aríete a vapor, Catapulta vs Barco Catapulta,
  Gigante a Vapor vs …), match insensível a acentos. Tabela em `test_naval_units.py`.
- **Tempos de viagem reais** lidos dos formulários (que já buscamos): `fetch_fleet_journey`
  (max `unitJourneyTime` dos navios enviados, do form de bloqueio) e `fetch_troop_journey`
  (`transportJourneyTime` do form de pilhagem). Substitui a estimativa ⅔. Parser
  `_parse_journey_times` em `test_f4b_parsers.py`. Ex. real: frota 12616s vs tropas 6729s.
- **Decisão por TIPO de navio** (`_classify_enemy_fleet`): 0 navios → só tropas; só navios
  que fogem (lancha rápida / reparador) → bloqueio+tropas; qualquer navio de **combate**
  (acima de `max_enemy_ships`, def. 0) → **salta o alvo + alerta Telegram** (`notify_farm_blocked`).
  Substitui a antiga porta por contagem.
- **Loadout de frota de combate** configurável (`get_farm_fleet`, farm_settings "fleet"):
  ex. 10 arietes a vapor enviados no bloqueio em vez da frota toda; vazio → frota inteira.
  Editor na UI a par do loadout de tropas.
- **Cronometragem das 2 vagas**: bloqueio sai já, tropas atrasadas (tempos reais) para
  aterrarem `fleet_lead_min` (def. 5) depois da frota — porto limpo.
- **Decisão da 2ª vaga sem desperdício**: o bot guarda quando a frota afugentada volta
  (`enemy_return_at = chegada do bloqueio + disperse_min`, def. 240 min). Enquanto o porto
  está limpo, as rondas seguintes vão **só com tropas**; quando a frota estiver de volta,
  manda bloqueio primeiro outra vez. Alvos de frota (`is_fleet_target`) re-espiam **sempre**
  (garrison fresco a cada ronda decide). Schema v11.
- **Parser do relatório de movimentos** (mission 7 = espiar movimentos): `parse_fleet_movements`
  + `enemy_fleet_clean_window_secs` (linha com "Voltar" → janela de porto limpo, TZ-safe).
  Pronto para auto-calibrar o `disperse_min` no futuro; por agora o valor é configurável.
- UI: chip "frota" + campos `tropas após frota` e `porto limpo` por alvo; API `disperseMin`.
⚠️ Lógica nova por validar in-game (servidor estava em manutenção). Requer `max enemy ships`
≥ tamanho da frota no alvo para o farm engajar em vez de saltar.

### F4.b Timing de duas vagas (navios → tropas no porto limpo) ✅ IMPLEMENTADO 2026-06-17
Caso real: alguns alvos têm navios que, ao serem atacados, fogem e dispersam, regressando
passados X minutos. Técnica manual: 1) lançar a frota (afugenta a inimiga); 2) minutos
depois lançar tropas, que chegam com o porto limpo. Implementado em `_enqueue_attack`
(schema v9, `fleet_lead_min`):
- A frota de bloqueio parte **já** e chega a `now + fleet_travel`. As tropas (transportes,
  ~⅔ do tempo da frota — mais rápidas) são atrasadas de forma **dependente da distância**
  para **aterrarem `fleet_lead_min` depois da frota** (janela de porto limpo), nunca antes.
  Substitui o antigo `battle_delay` fixo (30-120 min) que ignorava a distância e podia
  fazer as tropas chegarem primeiro (porto defendido) ou tarde demais.
- A decisão "preciso de relançar navios?" em cada ronda resolve-se por **re-espionagem**:
  alvos que mostraram frota forçam sempre re-scout (`last_enemy_ships > 0`), pelo que a
  vaga seguinte só vai com tropas se o intel fresco confirmar o porto vazio. Não dependemos
  de ver os movimentos da frota inimiga (a API não os expõe) — usamos intel observado.
- `fleet_lead_min` editável por alvo na UI (default 5). API: `fleetLeadMin` em add/update.

### F4.c Re-espionagem em pipeline (espiar durante o regresso) ✅ IMPLEMENTADO 2026-06-17
Antes, uma ronda de re-espionagem era sequencial: tropas regressam → espera → despacha
espião → espera relatório → ataca. Agora (schema v10, `respy_launched_at`): quando a ronda
seguinte precisa de re-scout, o espião é lançado **enquanto as tropas ainda regressam** —
os espiões usam o esconderijo, não navios, por isso não há conflito com a reserva. Disparado
~5 min antes do desembarque (`_EARLY_RESPY_LEAD`) para o relatório refletir o armazém
re-acumulado; ao chegarem as tropas o estado passa directo para SPYING (avalia e ataca),
saltando o backoff IDLE e um segundo scout. `next_farm_eta`/`has_due_farm` acordam a tempo.
Reutiliza espiões estacionados primeiro (`reexecute_stationed_spy`). Kill switch
`earlyRespyEnabled` (default on) + toggle na UI. Testes em `test_farm_respy.py`.

### F5. Notificação de regresso com saque ✅ IMPLEMENTADO 2026-06-15
Telegram quando uma frota própria regressa com saque. Reutiliza o F1.b: `log_loot`
passou a indicar se a entrada é nova (não duplicada entre snapshots) e o
`_collect_movements` notifica só nos regressos novos (`notify_returned_loot`).
Ligado/desligado em `alert_settings.returnEnabled`.

## 🛡️ Defesa / vigilância

### F6. Alarme de ataque recebido ✅ IMPLEMENTADO 2026-06-15
Telegram imediato quando aparece um movimento hostil dirigido às minhas cidades, com
origem, alvo, ETA e contagem de tropas/navios (`notify_attack_incoming`). Detecção em
`_collect_movements`, dedup persistente em `attack_alerts.json` (com poda dos que já
chegaram). Latência: o "attack-watch" (`alert_settings.checkMinutes`, opt-in) refresca
os movimentos de N em N min no smart_sleep — sem ele, os alertas só disparam no ciclo
horário. UI: cartão "Alertas de combate" nas Settings. API: `GET/POST /api/alert-settings`.

### F7. Watchlist de jogadores ✅ IMPLEMENTADO 2026-06-16
process_watchlist: a cada intervalHours re-escaneia só as ilhas dos alvos marcados
"alvo" e refresca essas entradas no world_scan.json (reactivações/defesas), sem o scan
semanal completo. Salta se um scan completo estiver a decorrer. Settings em
Espionagem; API GET/POST /api/watchlist. Desligado por defeito.

## 💰 Economia

### F8. Previsão de recursos ✅ IMPLEMENTADO 2026-06-13
O orçamento da fila de construção (Construção → Queue Budget) passou a dar uma
previsão precisa com hora de relógio:
- conta os recursos **em trânsito** entre cidades próprias (antes só somava o stock)
- usa **vinho líquido** (produção − consumo da população); se negativo, marca o
  vinho como "a diminuir" em vez de dar um ETA falso
- mostra por recurso "pronto ~HH:MM" (+ dia se não for hoje) e a duração, e um
  "Tudo pronto ~HH:MM" global (pior recurso)
Implementação client-side (Construction.tsx), reutiliza produção/custos/movimentos
já existentes; sem alterações no bot.
Nota: a previsão usa produção do império; como a fila auto-transporta de cidades
com excedente, o tempo real costuma ser melhor que o estimado (estimativa conservadora).
### F8.b ✅ IMPLEMENTADO 2026-06-13
Transporte proactivo: enquanto uma construção decorre (horas), o `process_building_queue`
passou a pré-posicionar os recursos do PRÓXIMO item da fila dessa cidade (primeiro item
cujo edifício não está em obra), em vez de esperar a construção acabar. Reutiliza o
`_try_transport` e a lógica de buffer (`_needs_transport_for_buffer`, extraída). Bounded a
um item; só nas horas activas; respeita pausa.

### F9. Otimizador de vinho ✅ IMPLEMENTADO 2026-06-13
`process_wine_balancer`: quando a autonomia de vinho (`wineRunsOutIn`) de uma cidade cai
abaixo de `thresholdHours`, envia vinho das cidades auto-suficientes (runway = ∞, que
guardam `targetHours` para si) para a reabastecer até `targetHours` de consumo — antes do
alerta crítico. Cartão no separador Transportes; API `GET/POST /api/transport/wine`.
Respeita pausa e horas activas.

## 🔧 Operacional

### F10. Página de logs na UI ✅ IMPLEMENTADO 2026-06-13
Nova página "Logs" no menu: tail do log do bot (poll 5s, 100-1000 linhas, auto-scroll,
cores por nível). O bot passou a escrever para `bot.log` no volume partilhado via
`RotatingFileHandler` (1 MB × 2 backups, com data completa); Flask serve em
`GET /api/logs?lines=N`. Dispensa o `docker logs ikabot`.

### F11. Pausa global ✅ IMPLEMENTADO 2026-06-13
Botão na sidebar (com banner amarelo quando activo) que suspende ataques, transportes/
consolidação e construções, mantendo toda a recolha de dados (império, scan, movimentos,
militar, espionagem). Estado em `pause.json`; `empire_utils.is_paused()` é verificado
no topo de cada processador de acção, e o smart_sleep não cria busy-loop em pausa.
API: `GET/POST /api/pause`.

### F12. Transportes agendados + consolidação ✅ IMPLEMENTADO 2026-06-12
Novo separador "Transportes" em Movimentos (e "Despacho" renomeado para "Ataque"):
- **Manual**: origem + destino, quantidades por recurso (com disponível e Max),
  nº de navios e tipo (comércio ou cargueiros), agendamento agora/atraso/à hora.
  Fila SQLite "transport" com retry 3× e cap ao vivo no envio (stock da origem,
  navios livres, capacidade da frota).
- **Consolidação** (à la ikabot consolidate resources): cidade de destino + intervalo
  em horas + mínimo para enviar; a cada ronda envia o excedente de todas as cidades
  acima do resourceBuffer das Settings E das reservas da fila de construção.
  Estado da última ronda visível na UI.
  Selector de tipo de barco (2026-06-13): comércio / cargueiros / ambos. No modo
  "ambos" envia primeiro com transporters e o restante grande com cargueiros.

## Já implementadas (referência)

- ✅ F5 Notificação Telegram de regresso com saque — 2026-06-15
- ✅ F6 Alarme Telegram de ataque recebido (+ attack-watch opcional) — 2026-06-15
- ✅ F4 Farming de alvos (farm_manager, máquina de estados por alvo) — 2026-06-13
- ✅ F1.b Estatísticas de saque por alvo (loot_log + /api/loot-stats) — 2026-06-13
- ✅ F8.b Pré-posicionamento proactivo do próximo item da fila — 2026-06-13
- ✅ F9 Otimizador de vinho (transportes preventivos) — 2026-06-13
- ✅ F10 Página de logs do bot na UI (bot.log rotativo + /api/logs) — 2026-06-13
- ✅ F11 Pausa global (sidebar + banner, guards nos processadores) — 2026-06-13
- ✅ F8 Previsão de recursos da fila de construção (hora de relógio, em-trânsito, vinho líquido) — 2026-06-13
- ✅ F12 Transportes agendados + consolidação automática — 2026-06-12
- ✅ F1 Histórico de ataques (attack_log SQLite + UI no DispatchTab) — 2026-06-12
- ✅ F2 ETA de chegada + agendamento por hora de chegada no DispatchTab — 2026-06-12
- ✅ Refresh manual do military (`POST /api/military/refresh` + flag) — 2026-06-11
- ✅ Notificações Telegram de ataque despachado/falhado — 2026-06-11
- ✅ Retry com backoff em ataques falhados — 2026-06-11
- ✅ Dispatch para cidades próprias (deployArmy/deployFleet) — 2026-06-11

## Ordem sugerida

1. **F6** (alarme de ataque) — protege a conta, barato
2. **F1 + F2** — completam o ciclo de pilhagem manual
3. **F3** — qualidade de vida no dispatch
4. **F4** — o objectivo final; fazer depois de F1 (precisa do histórico para decidir)
5. Restantes conforme necessidade
