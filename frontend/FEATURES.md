
## UX — reorganização Combate vs Logística (2026-06-16)

### Fase 1 ✅ — agrupar por intenção
"Mundo" passou a "Combate": as suas abas (Alvos/Ilhas/Ignoradas) ganharam a aba **Ataque**
(o DispatchTab — dispatch manual, fila, histórico, saque, farm), movida de "Movimentos".
"Movimentos" ficou só com logística (Movimentos próprios + Transportes). Sem itens de
menu novos; resolve a incoerência de a execução de ataques viver sob a logística.

### Fase 2 ✅ — visibilidade transversal
- **Cartão de combate na Home**: farms activos (+ quantos a atacar), próximo ataque
  (countdown), saque das últimas 24h, ataques a chegar (com ETA, a vermelho).
- **Banner global de ataque recebido**: app-wide (como o de pausa), vermelho, com nº de
  movimentos hostis a chegar e ETA do mais próximo.

### Fase 3 ✅ — linha de alvo unificada
Fundir o pipeline do Mundo com o saque-por-alvo/histórico numa única vista por alvo
(espiei → saque visto → saque real trazido → estado do farm + acções inline).
Implementado no `InactivosTab`: cada linha de alvo mostra as pills de pipeline da espionagem,
o saque visto (relatório) e o **saque real trazido** por jogador (F1.b), o estado do farm do
alvo e acções inline (`FarmSettings` embutido, add/remove ao farm). *(label actualizado na
reconciliação de 2026-11-04 — estava "POR FAZER" mas já estava feito.)*
