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
Futuro (F1.b): estatísticas de saque por alvo cruzando com movimentos de regresso.

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

### F4. Farming de alvos (ciclo completo) — a feature mais ambiciosa
"Atacar este alvo a cada X horas enquanto o saque do relatório > Y":
re-espionagem automática antes de cada vaga → avaliação → ataque → repete.
A infra já existe quase toda (spy state machine + attack queue + auto-attack);
falta o orquestrador de ciclo por alvo e a UI de gestão.

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
Futuro (F8.b): agendar transportes proactivamente com base nesta previsão.

### F9. Otimizador de vinho
Já existe `wineRunsOutIn` por cidade — sugerir (ou automatizar) transportes de vinho
preventivos quando a autonomia projectada cai abaixo de N horas, antes do alerta crítico.

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
