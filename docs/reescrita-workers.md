# Reescrita para Cloudflare Workers

Fonte única da reescrita (Python no Render → TypeScript no Cloudflare Workers). Código em `worker/`.

## Decisão
| Peça | Escolha |
|---|---|
| Hospedagem | Workers grátis + Static Assets; rota `crm.vfitcoachapp.com/*`, sem `*.workers.dev` |
| Tela | Hono no servidor: JSX para layout e componentes; `html` do Hono para listas grandes (5× menos CPU) |
| Banco | Turso (HTTP) até a troca; D1 depois. Mesmo SQL, interface `query`/`run`/`batch` (`worker/src/banco/`) |
| Portaria | Cloudflare Access + conferência do token no Worker (`jose`), igual a `app/acesso.py` |
| Testes | Vitest no runtime do Workers (`@cloudflare/vitest-plugin`, novo nome do `vitest-pool-workers`) |
| Entrega | **Uma PR só** (economia de Actions); vai ao ar **só no merge** |

## Limites grátis (documentação, 19/11/2026)
- Workers: 10 ms de CPU por pedido e por Cron; 100 mil pedidos/dia; 50 subpedidos por pedido; 5 Crons; 128 MB.
- D1: 50 consultas por pedido (`batch` conta 1); 5 mi linhas lidas e 100 mil gravadas por dia; 500 MB; Time Travel de 7 dias.
- Workers Builds (publicação): 3.000 min/mês, fora do Actions.

## Regras de implementação
- **Idas ao banco:** as telas do Python fazem 95 a 590 consultas. `Banco` junta as leituras do mesmo instante (`Promise.all`)
  numa ida e lê uma vez a consulta repetida. Teto de 45 idas por pedido, conferido por tela nos testes.
- **Linhas congeladas:** a mesma linha serve a todos; quem muda faz cópia (`{ ...linha }`).
- **Paridade:** `python worker/paridade/gerar.py` gera esquema (`worker/migrations/`), semente e casos JSON a partir do Python;
  os testes TS exigem o mesmo resultado, centavo por centavo (`arred` = `round` do Python) e o mesmo HTML (`test/html.ts`).
- **Relógio:** `relogio.ts` (Brasília). SQL com `'localtime'` segue igual: no Turso/D1 roda em UTC, como já roda hoje no Render.

## Medição da Fase 0 (CPU)
Cenário sintético com 3× o volume real (`npm run cpu`, V8):
- Layout completo: 1 ida ao banco.
- HTML de 330 KB: 8 ms com JSX, 1,6 ms com `html` do Hono.
- Cálculo: 3,5 a 6× mais rápido que o Python.
- Estimativa das telas mais pesadas (Painel, Financeiro, Previsão): **3,5 a 5,5 ms hoje; 10 a 16 ms com 3× os dados**.

Cabe hoje; com o crescimento dos dados, as telas pesadas passariam do limite. Decisão do Victor antes da Fase 1.

## Fases (todas na mesma PR)
0. Fundação: banco, portaria, repasse ao Render, layout, Crons, testes e medição. **Feita.**
1. Configurações · 2. Clientes, ficha e leads · 3. Agenda e grade · 4. Propostas, ofertas e cálculos ·
5. Financeiro · 6. Assistente · 7. Painel, campanhas, rotina, explorador, dados, importar e exportar ·
8. Migração D1, remoção do Python e do código do PC.

Os alertas do topo entram com as regras de alunos e do financeiro (até lá, vazios nas telas novas).

## Ida ao ar (com o Victor, sem PR nova)
1. Painel do Cloudflare: criar o D1 `vfitcoach-crm`; ligar Workers Builds na pasta `worker` (`npm run deploy`);
   variáveis `BANCO=turso`, `RENDER_URL`, `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD`; segredos `TURSO_*` e `ANTHROPIC_API_KEY`.
   No Render, desligar o Auto-Deploy.
2. OK do Victor → merge → rota `crm.vfitcoachapp.com/*` no Worker, ainda no Turso. **Volta atrás:** tirar a rota.
   Tela com problema volta ao Render pela variável `ROTAS_RENDER` (prefixos separados por vírgula).
3. Estável por alguns dias + OK do Victor → cópia Turso → D1, conferência e `BANCO=d1`. Depois, desligar o Render.
