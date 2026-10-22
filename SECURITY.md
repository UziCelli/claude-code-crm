# Segurança

Este repositório é público, mas **não guarda dado nenhum** do CRM: só o código.

- Banco de dados (`data/`, `*.db`), chaves (`.env`) e backups ficam só no PC do dono e no Turso. O `.gitignore` bloqueia e o teste `tests/test_seguranca.py` falha se algum deles for versionado.
- Quem chega pela internet só entra depois do login do Cloudflare Access (`app/acesso.py`). Sem a portaria configurada, tudo é bloqueado.

## Achou uma falha?

Não abra uma issue pública. Use **Security → Report a vulnerability** neste repositório (aviso privado).
