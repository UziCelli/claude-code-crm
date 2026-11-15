Exclusivo do Codex: siga AGENTS.md e este arquivo; não leia CLAUDE.md nem instruções exclusivas do Claude.

# Codex

- As regras compartilhadas e a revisão cruzada estão em [AGENTS.md](AGENTS.md). Não duplique aqui segurança, estilo, arquitetura ou histórico.
- Revise mudanças do Claude pelo diff e pelo código afetado, independentemente da conclusão do autor. Informe problemas concretos, localização, efeito e validação; não registre OK antes de concluir.
- Em suas PRs, declare **Implementador: Codex; revisor cruzado: Claude — pendente** até haver revisão real. Não aprove o próprio trabalho em nome do Claude.
- Comece com busca direcionada e saída curta; não imprima patches gerados, mapas inteiros nem logs repetidos. Em revisão, não regenere Graphify.

## Preferência de modelos do dono

- Sol 6.1: consulta, planejamento, arquitetura e revisão.
- Terra 6.1: desenvolvimento e execução.
- Luna, ou o modelo disponível mais barato: operações simples, CI, commit, push e merge.
- Astra: apenas questões excepcionalmente complexas ou resistentes.
- Aplique essas preferências somente quando a plataforma permitir e as instruções da sessão autorizarem. Não crie agentes só para trocar de modelo; não simule uma troca indisponível. Operações de Git/CI normalmente são ferramentas, sem outro agente.
