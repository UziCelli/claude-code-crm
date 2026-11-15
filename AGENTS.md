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
- Sem check-ins agendados nos PRs. Sem delegação automática para tarefas simples; operações básicas usam ferramentas.
- Uma fonte por assunto; atualize documentação quando regra ou comportamento mudar, sem acumular diário nos guias iniciais.
- Preserve o fluxo automático já autorizado: depois das aprovações dos revisores (incluindo Codex, solicitado com `@codex review` no PR) e CI verde, marcar pronta e juntar sem nova pergunta.
