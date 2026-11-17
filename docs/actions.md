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


O workflow `dependabot-juntar.yml` é disparado quando `CI` e `Segredos no código` terminam e junta o PR do Dependabot só se toda atualização for minor/patch e todas as verificações do commit estiverem verdes. Como a junção usa o `GITHUB_TOKEN`, ela não dispara workflows de push: a atualização vai ao ar junto com o próximo merge normal.

Referência: https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions#concurrency
