# Plano de remediação

## P0 — proprietário e revisor antes de publicar
1. Revisar o diff e checagens desta branch; não integrar mudanças não aprovadas. O merge na main pode atualizar o Render e o PC automaticamente.
2. GitHub → Settings → Rules/Rulesets: proteger main, exigir PR, aprovação e checks; impedir force-push e exclusão. Validar com PR de teste. Settings → Environments: limitar credenciais de publicação à branch principal e exigir aprovador; conferir escopo de cada token. Filtro no YAML sozinho não protege de YAML adulterado.
3. Ativar MFA/passkeys em GitHub, Google, Cloudflare e registrador; revisar colaboradores, sessões e tokens. Não foram consultados nem alterados neste trabalho.
4. Se quiser restringir cópia futura: Settings → General → Danger Zone → Change visibility → Private. Confirmar compatibilidade do plano/hospedagem antes; histórico público e cópias já feitas permanecem.

## P1 — responsável técnico + proprietário
- Revisar allowlist de e-mails e duração/revogação de sessões no Cloudflare Zero Trust → Access. O CRM confia na identidade autorizada pelo Access; não limita e-mail por si.
- Criar lockfile Python completo com hashes na plataforma de build, testar Windows/Linux e automatizar atualização; não congelar versões sem validar compatibilidade do libsql. Proteger disco e backups, testar restauração em cópia isolada sem dados reais neste ambiente.
- Confirmar TLS/renovação, DNS/lock do domínio, alertas de deploy/login e permissões; testar rollback em staging.
- Revisar dependências/licenças e titularidade; não inserir licença proprietária sobre componentes de terceiros.

## P2 — responsável técnico
Gerar SBOM a cada release; revisar pinning de todas as actions/imagens, permissões e logs. Definir retenção, plano de incidente e testes periódicos. Restringir CSP script/style após inventário dos inline scripts e estilos, primeiro Report-Only com coleta explícita e mínima.

## Aceite e rollback
Aceite local: testes do SECURITY_AUDIT.md verdes, nenhum dado/segredo publicado e revisão do último diff. Aceite externo: regras/MFA realmente habilitados e conta não autorizada bloqueada em staging; backups restaurados com sucesso quando aplicável.
Rollback: reverter apenas o commit desta entrega por PR e aguardar os checks, sem apagar dados nem cache do usuário. Se rollback reabrir uma proteção, restringir o recurso afetado enquanto corrige; produção não foi alterada por esta entrega.
