# Segurança

Este repositório é público, mas **não guarda dado nenhum** do CRM: só o código.

- Banco de dados (`data/`, `*.db`), chaves (`.env`) e backups ficam só no PC do dono e no Turso. O `.gitignore` bloqueia e o teste `tests/test_seguranca.py` falha se algum deles for versionado.
- Quem chega pela internet só entra depois do login do Cloudflare Access (`app/acesso.py`). Sem a portaria configurada, tudo é bloqueado.

## Achou uma falha?

Não abra uma issue pública. Use **Security → Report a vulnerability** neste repositório (aviso privado).

## Dados e operação

- Preserve validação do token Cloudflare Access em cada pedido externo; configuração ausente deve negar acesso. A entrada local tem fronteira distinta: não ampliar essa exceção para a internet.
- Banco SQLite/Turso, dados financeiros, backups, conversas e chave do assistente são privados. Não incluir dados reais em logs, testes, screenshots ou PRs.
- Não testar migração/restauração no banco real. Preserve backup antes de importação/restauração e a recusa de arquivo inválido.
- O assistente envia dados à API da Anthropic: preserve confirmações antes de excluir ou mudar valores e informe custo/privacidade ao alterar o fluxo.
- Suspeita de chave exposta: revogar/rotacionar e revisar acessos; apagar o arquivo não revoga a chave.
- Evidências datadas: [ameaças](docs/security/THREAT_MODEL.md), [auditoria](docs/security/SECURITY_AUDIT.md), [remediação](docs/security/REMEDIATION_PLAN.md) e [cache](docs/security/PWA_CACHE_POLICY.md). Não presumir configuração externa validada.
