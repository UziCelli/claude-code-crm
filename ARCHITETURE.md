# Arquitetura

- CRM Python/FastAPI com templates Jinja, assets locais e SQLite; roda no PC em localhost:8765. Estrutura e operação em [README.md](README.md); mapas específicos em [docs/mapa-rodada1.md](docs/mapa-rodada1.md) e [docs/mapa-financeiro.md](docs/mapa-financeiro.md).
- Turso é opcional: réplica permite consulta offline, mas gravação precisa de rede. Desativar Turso não transfere automaticamente seus lançamentos ao banco local.
- Acesso externo via Cloudflare Tunnel ao PC e reserva Cloud Run, ambos protegidos por Cloudflare Access e validação em `app/acesso.py`. Localhost mantém o fluxo local próprio.
- `app/` concentra aplicação, dados, cálculo, templates e estáticos; `tests/` verifica comportamento. Assistente usa API Anthropic e guarda conversa no banco; preservar confirmação e sigilo.
- Importação preserva dados preenchidos; backup/restauração e lixeira são barreiras contra perda. Não alterar esquema ou executar migração de produção por conveniência.
- Merge na main aciona atualização de ambientes conforme configuração existente; branch de trabalho não autoriza publicação. Avalie custo e recuperação antes de mudanças de infraestrutura.
