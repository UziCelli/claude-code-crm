# Modelo de ameaças — claude-code-crm

Data: 14/11/2026. Base inspecionada: `d1e7d40dad1d77095418e19cd74e0b9307b6d838`. Referência: OWASP ASVS 5.0.0; não representa certificação.

## Inventário e fronteiras
FastAPI/Jinja2, SQLite/réplica Turso, Cloudflare Access + Render (Tunnel no PC como alternativa); uso local Windows sem login em loopback.

Ativos: código, histórico Git, domínios, contas GitHub/Cloudflare, credenciais de publicação, marca, imagens/fontes e dependências. Também: cadastros, finanças, conversas do assistente, chave de IA, banco e backups locais/Turso.

Atores: proprietário, colaboradores, usuários legítimos, visitantes maliciosos e dependência/conta comprometida.

Fluxo: navegador não confiável → Cloudflare → Access/JWT validado pelo CRM → banco/assistente/backup. Localhost permite uso no próprio PC; exige servidor vinculado a loopback e túnel preservando marcas de proxy.
GitHub/CI → build/publicação é outra fronteira: revisão e proteção externa dos segredos continuam necessárias.

## Riscos prioritários
- Conta de publicação comprometida permite substituir a aplicação (impacto alto, probabilidade dependente de MFA/permissões não verificados).
- Cache do navegador/proxy podia guardar respostas privadas sem no-store explícito (corrigido). Pedidos de alteração de site externo sem Origin/Referer precisam de Fetch Metadata (corrigido para cross-site).
- Repositório público permite copiar o código atual e o histórico. Torná-lo privado não recolhe cópias existentes.
- Bibliotecas e workflows podem mudar: Dependabot e scanner de segredos adicionados; não garantem ausência de falhas.
- Banco/backups no dispositivo exigem criptografia de disco e controle do PC, não verificados. Um JWT válido permite ações administrativas: não é aplicação multiusuário com isolamento por cliente.

## Limites da revisão
Somente código disponibilizado e testes locais sintéticos. Sem acesso a painéis de produção, políticas reais de Access, DNS, MFA, buckets, backups ou faturamento; sem testes ativos nos domínios. Não registrar valores de segredos. Arquivos entregues ao navegador podem ser copiados.
