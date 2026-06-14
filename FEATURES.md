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

### F3. Validação de capacidade de saque
Cruzar transporters seleccionados com o último relatório de espionagem do alvo:
"50 navios = 25.000 de capacidade, mas o armazém tem 180.000 — faltam navios".
Os dados já existem (spy_missions.json result.resources + capacidade por navio).

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
⚠️ Por validar in-game o ciclo completo.

### F5. Notificação de regresso com saque
Destacar nos movimentos o regresso de tropas/frota e notificar via Telegram
("tropas regressaram de X"). O movements.json já tem direction="<-" e isOwn.

## 🛡️ Defesa / vigilância

### F6. Alarme de ataque recebido ⭐⭐ melhor custo/benefício
O movements.json já tem `isHostile` — notificação Telegram imediata quando aparece
movimento hostil, com ETA e origem. Hoje só se vê se abrires o dashboard.
Atenção: o movements só refresca a cada ciclo (~1h) — considerar um check
leve de movimentos no smart_sleep (ex.: a cada 10-15 min, com delay aleatório).

### F7. Watchlist de jogadores
Re-scan periódico apenas das ilhas dos alvos marcados "alvo" (vs. world scan semanal
completo): detectar reactivação de inactivos e mudanças de defesa. Reutiliza o
scan_collector incremental com uma fila de ilhas restrita.

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
