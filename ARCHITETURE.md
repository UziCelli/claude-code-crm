# Arquitetura

- CRM Python/FastAPI com templates Jinja e assets locais, no Render grátis atrás do Cloudflare Access (`crm.vfitcoachapp.com`), validado em `app/acesso.py`. Operação em [README.md](README.md); mapas em [docs/mapa-rodada1.md](docs/mapa-rodada1.md) e [docs/mapa-financeiro.md](docs/mapa-financeiro.md).
- Banco Turso; o Render usa réplica local sincronizada, e as gravações vão ao Turso. PC, Tunnel e Cloud Run não são mais usados.
- Reescrita em TypeScript para Cloudflare Workers em `worker/` (Hono, Turso/D1, mesmo SQL e visual), numa PR só: [docs/reescrita-workers.md](docs/reescrita-workers.md). Regras novas entram com paridade gerada pelo Python.
- A Agenda (`agenda_fixos`) é a fonte dos horários fixos: Grade, horas de trabalho, ficha e aulas do mês leem e gravam nela ([docs/mapa-agenda.md](docs/mapa-agenda.md)). Data de hoje só por `app/relogio.py`.
- `app/` concentra aplicação, dados, cálculo, templates e estáticos; `tests/` verifica comportamento. Assistente usa API Anthropic e guarda conversa no banco; preservar confirmação e sigilo.
- Importação preserva dados preenchidos; backup/restauração e lixeira são barreiras contra perda. Não alterar esquema ou executar migração de produção por conveniência.
- Merge na main aciona atualização de ambientes conforme configuração existente; branch de trabalho não autoriza publicação. Avalie custo e recuperação antes de mudanças de infraestrutura.
