# Reescrita para Cloudflare Workers

Fonte única da reescrita (Python no Render → TypeScript no Cloudflare Workers). Código em `worker/`.

## Decisão
| Peça | Escolha |
|---|---|
| Hospedagem | Workers grátis + Static Assets; rota `crm.vfitcoachapp.com/*`, sem `*.workers.dev` |
| Tela | Hono no servidor: JSX; `html` do Hono para listas grandes |
| Banco | Turso (HTTP) até a troca, D1 depois; mesmo SQL (`worker/src/banco/`) |
| Portaria | Cloudflare Access + token conferido no Worker (`jose`), como `app/acesso.py` |
| Testes | Vitest no runtime do Workers (`@cloudflare/vitest-plugin`) |
| Entrega | **Uma PR só**; vai ao ar **só no merge** |

## Limites grátis (19/11/2026)
- Workers: 10 ms de CPU por pedido e por Cron; 100 mil pedidos/dia; 50 subpedidos por pedido; 5 Crons.
- D1: 50 consultas por pedido (`batch` = 1); 5 mi linhas lidas e 100 mil gravadas por dia; Time Travel de 7 dias.

## Regras
- **Idas ao banco:** o Python faz 95 a 590 consultas por tela. `Banco` junta as leituras do mesmo `Promise.all` numa ida e
  lê uma vez a repetida; linhas vêm congeladas (quem muda faz cópia). Cada resposta traz `x-crm-idas`; teto de 45.
- **Paridade:** `python worker/paridade/gerar.py` gera esquema, semente, cenários e casos a partir do Python; os testes exigem
  o mesmo resultado, centavo por centavo (`arred` = `round`), e o mesmo HTML (`test/html.ts`).
- **Relógio:** `relogio.ts` (Brasília). SQL com `'localtime'` segue igual (UTC no Turso/D1, como hoje no Render).
- **CPU** (Victor, 19/11: ficar no Cloudflare e otimizar): soma ou filtro em laço vai para o SQL, que roda fora da CPU do
  Worker; listas grandes com `html`. `npm run cpu` (também no CI) mede o pedido inteiro de cada tela no cenário 3× e falha acima de **7 ms**.

## Medições
- Fase 0 (3× o volume): HTML de 330 KB custa 8 ms com JSX e 1,6 ms com `html`. Telas pesadas, estimativa: 3,5–5,5 ms hoje, 10–16 ms com 3× sem as regras.
- Fase 1: `/configuracoes` 4,8–5,0 ms (3×).

## Fases (todas na mesma PR)
0. Fundação: banco, portaria, repasse ao Render, layout, Crons, testes. **Feita.**
1. Configurações: motor de preços, DAS e horas de trabalho; o POST grava só o que mudou, numa ida, e confere as margens
   antes (fim do 503). Importar planilha, `/locais/*` e `/calculos` seguem no Render. **Feita.**
2. Clientes, ficha e leads · 3. Agenda e grade · 4. Propostas, ofertas e cálculos · 5. Financeiro · 6. Assistente ·
7. Painel, campanhas, rotina, explorador, dados, importar e exportar · 8. D1, remoção do Python e do código do PC.

Alertas do topo entram com as regras de alunos e do financeiro (até lá, vazios nas telas novas).

## Ida ao ar (com o Victor, sem PR nova)
1. Painel do Cloudflare: criar o D1 `vfitcoach-crm`; Workers Builds na pasta `worker` (`npm run deploy`); variáveis
   `BANCO=turso`, `RENDER_URL`, `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD`; segredos `TURSO_*` e `ANTHROPIC_API_KEY`. No Render, desligar o Auto-Deploy.
2. OK do Victor → merge → rota `crm.vfitcoachapp.com/*` no Worker, ainda no Turso. **Volta atrás:** tirar a rota;
   uma tela volta ao Render pela variável `ROTAS_RENDER`.
3. Estável alguns dias + OK do Victor → cópia Turso → D1, conferência e `BANCO=d1`. Depois, desligar o Render.
