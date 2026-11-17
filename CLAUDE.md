Exclusivo do Claude Code: siga AGENTS.md e este arquivo; não leia CODEX.md nem instruções exclusivas do Codex.

# Claude Code

- Regras compartilhadas em [AGENTS.md](AGENTS.md); não duplique segurança, arquitetura ou histórico aqui.
- Em suas PRs, identifique implementador Claude e revisor cruzado Codex — pendente até revisão real.
- Revise PRs do Codex pelo diff e fontes afetadas; confira a preservação de regras antes de registrar OK com o commit revisado.
- **Esperar sem gastar IA:** depois de `@codex review`, rode em segundo plano `.claude/esperar-pr.sh codex <PR>`; depois de tirar do rascunho, `.claude/esperar-pr.sh ci <PR>`. O script termina sozinho com o resultado, e só então a sessão volta a trabalhar.
- **Sessão da tarefa do GitHub (PR do Codex ou do Dependabot):** aja só em PR aberto de branch `codex/` ou `dependabot/` sem "Revisão cruzada: OK" no commit atual; senão, encerre sem fazer nada. Trabalhe na branch do próprio PR, não abra PR novo e termine com o resumo de 2–3 tópicos (é o que chega ao Victor).
- Tirar do rascunho: `gh api -X POST repos/<dono>/<repo>/pulls/<n>/ccr/ready_for_review`. Juntar: `merge_pull_request` com `expectedHeadSha`.
- Preserve as definições existentes em `.claude/`; não invente hierarquia ou troca de modelos indisponível.
- Busque trechos específicos; use o Graphify existente com orçamento limitado, sem leitura integral ou reconstrução em revisão.
