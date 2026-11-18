# Fila do GitHub Actions

Todos os workflows versionados usam o grupo `repository-workflows`, com
`cancel-in-progress: false` e `queue: max`. O GitHub executa um workflow por
vez no repositório e atende os pendentes na ordem de entrada no grupo.
Repositórios diferentes têm filas independentes. Jobs dentro de um mesmo
workflow podem continuar em paralelo.

A fila aceita até 100 execuções pendentes; acima disso, o GitHub cancela as
novas entradas. Execuções criadas com YAML antigo e workflows gerados pelo
GitHub (por exemplo, Dependabot) não recebem essa configuração automaticamente.
Novos arquivos de workflow precisam declarar o mesmo grupo. A fila não elimina
execuções de CI de commits diferentes, não evita conflitos entre agentes e não
substitui revisão de YAML antes do envio.


O workflow `dependabot-juntar.yml` roda quando uma verificação de PR do Dependabot termina (Actions por `workflow_run`, commit statuses por `status`); a última a terminar faz a junção. O GitHub não dispara workflow quando um app externo (como o Cloudflare) termina num commit que tem Actions; por isso, se só ele faltar, o job espera até 4 minutos por ele (e, passado esse prazo, o PR fica para reexecução manual do job). Só junta se toda atualização for minor/patch (pelo `update-type`; sem ele, pelo título "de A para B" de um PR de 1 dependência, sem salto de versão grande e, em 0.x, sem salto no número do meio) e toda verificação do commit tiver terminado com `success` (pulada ou neutra não vale). Como a junção usa o `GITHUB_TOKEN`, ela não dispara workflows de push: a atualização vai ao ar junto com o próximo merge normal.

Referência: https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions#concurrency
