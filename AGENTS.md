Instruções comuns: Codex lê CODEX.md; Claude Code lê CLAUDE.md; cada agente ignora o guia exclusivo do outro.

# VFITCOACH CRM

## Começar com pouco contexto

- Leia este arquivo e somente o guia do seu agente: [Codex](CODEX.md) ou [Claude](CLAUDE.md).
- Consulte o [índice](docs/README.md) conforme a tarefa. Histórico e planos não são leitura inicial obrigatória.
- Busque só arquivos e trechos pertinentes. Graphify existente pode localizar relações: `graphify query "tema específico" --budget 1000 --depth 1`. Confirme no código; use `rg` se indisponível ou desatualizado. Não leia o grafo inteiro nem regenere por rotina de revisão; depois de mudar código, atualize o grafo conforme a configuração existente.
- Para segurança, implementação e estrutura, consulte respectivamente [SECURITY.md](SECURITY.md), [CODE_STYLE.md](CODE_STYLE.md) e [ARCHITETURE.md](ARCHITETURE.md).

## Entrega e revisão

- Explique ao dono em português simples e curto, com resultado e limitações.
- Use branch própria baseada na main atual; preserve trabalho paralelo.
- Cada PR identifica implementador, revisor cruzado, documentação e validação conforme o [modelo](.github/pull_request_template.md).
- Claude revisa PR do Codex; Codex revisa PR do Claude. Antes do merge, registrar “Revisão cruzada: OK”, pelo outro agente, com commit revisado e parecer. Nova alteração exige revisão do novo diff. Não aprovar o próprio trabalho em nome do outro.
- Só juntar após revisores consultados/aprovados, revisão cruzada válida, CI obrigatório verde na versão atual e autorização aplicável. Corrija achados reais e resolva as conversas antes de juntar. Não contorne proteções nem conte teste pulado como aprovação. Não publique uma branch de trabalho.
- Validação proporcional: verificações afetadas, ampliando por risco/falha. Preserve o CI existente. Não repita testes aprovados sem mudança relevante.
- **Minutos do Actions são limitados (repositórios privados, plano grátis).** PR em rascunho não roda CI; não reexecute verificação verde sem mudança; mudança só de documentação não pede teste.
- Sem check-ins agendados nos PRs. Sem delegação automática para tarefas simples; operações básicas usam ferramentas.
- Uma fonte por assunto; atualize documentação quando regra ou comportamento mudar, sem acumular diário nos guias iniciais.

## Fluxo automático de PR (Victor, 17/11/2026)

Do PR ao merge sem esperar o Victor, com o mínimo de Actions e de uso das IAs.

- **Todo PR abre em rascunho.** Rascunho não roda CI. Sai do rascunho só com a revisão cruzada OK no commit atual, para uma única rodada completa de CI.
- **PR do Claude:** comentar `@codex review`. Vale como OK do Codex o resumo "Codex Review" concluído no commit atual sem achados pendentes, ou um comentário "Revisão cruzada: OK" do Codex. Achado real: corrigir, enviar e pedir `@codex review` de novo. Achado que não procede: responder na conversa com o motivo.
- **Sem revisão automática do Codex ao sair do rascunho** (desligada pelo Victor em 18/11/2026): vale só o `@codex review` pedido em rascunho. Não espere revisão extra depois de tirar do rascunho; se o Codex revisar sozinho de novo, a configuração voltou e o Victor deve ser avisado.
- **PR do Codex (branch `codex/…`):** o Codex abre o PR só com o trabalho terminado e não envia commits depois (mudança pedida depois vira PR novo). Não precisa avisar ninguém: uma tarefa do Claude com gatilho do GitHub é acionada sozinha e revisa. Se achar problema, o Claude corrige no próprio PR e pede `@codex review` para o Codex conferir a correção. Com tudo OK, o Claude registra "Revisão cruzada: OK" com o commit.
- **Dependabot (branch `dependabot/…`):** atualizações pequenas chegam juntas uma vez por mês; o workflow `dependabot-juntar.yml` junta sozinho, sem IA, quando toda atualização é pequena (minor/patch) e toda verificação do commit (check-runs e commit statuses) terminou com sucesso, sem contar pulada como aprovação; sem revisão do Codex. O tamanho vem do `update-type`; sem ele (correção de segurança do npm, `requirement` do pip), vem do título "de A para B" de um PR de 1 commit e 1 dependência, só se a versão grande (major) não mudou (em 0.x, também o número do meio). Versão grande, sem número (SHA) ou que não dá para classificar: não junta; o Claude comenta o risco no PR e avisa o Victor.
- **Juntar sem perguntar:** o merge fica com o Claude. Com revisão cruzada OK no commit atual, nenhum achado pendente e CI obrigatório verde, ele tira do rascunho se preciso, junta conferindo o commit e acompanha a publicação. Perguntar ao Victor antes só se a mudança apagar ou migrar dados que já estão em produção, ou tiver custo em dinheiro.
- **CI vermelho:** corrigir e repetir; mudança de código depois do OK pede novo `@codex review`. Falha que não é do PR: explicar ao Victor em linguagem simples. Instabilidade: reexecutar só o job que falhou, uma vez.
- **Esperar não gasta IA:** a revisão do Codex e o CI são acompanhados por consulta à API do GitHub em segundo plano, sem rotina agendada nem conversa de verificação.
- **No fim:** avisar o Victor em 2–3 tópicos (o que mudou e se já está no ar).
