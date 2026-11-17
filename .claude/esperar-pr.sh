#!/usr/bin/env bash
# Espera sem gastar IA: rode em segundo plano. Termina quando o Codex ou o CI tem
# resultado no commit atual do PR e imprime uma linha com o estado.
# Uso: .claude/esperar-pr.sh codex|ci <número do PR>   (desiste depois de ~90 min)
set -u
modo=${1:?use codex ou ci}
pr=${2:?informe o número do PR}
repo=$(git remote get-url origin | sed -E 's#\.git$##; s#:#/#g' | awk -F/ '{print $(NF-1)"/"$NF}')

codex() { # revisão do Codex no commit $1: ok | achados | pendente
  # Vale o resumo "Codex Review" do commit ou um comentário "Revisão cruzada: OK" do Codex
  # citando o commit. Achado pendente no resumo vence o comentário.
  local estado aprovado
  estado=$(gh api "repos/$repo/issues/$pr/comments?per_page=100" --paginate \
        --jq '.[] | select(.user.login == "chatgpt-codex-connector[bot]") | .body' 2>/dev/null \
      | grep -o 'codex-review-state:v1 {.*}' | tail -1 | sed 's/^codex-review-state:v1 //' \
      | jq -r --arg sha "$1" '.code_review
          | if .commit_sha == $sha and .status == "completed"
            then (if .has_unresolved_findings then "achados" else "ok" end)
            else "pendente" end' 2>/dev/null)
  aprovado=$(gh api "repos/$repo/issues/$pr/comments?per_page=100" --paginate \
        --jq ".[] | select(.user.login == \"chatgpt-codex-connector[bot]\"
                    and (.body | contains(\"Revisão cruzada: OK\")) and (.body | contains(\"${1:0:7}\"))) | .id" 2>/dev/null)
  if [ "$estado" = achados ]; then echo achados
  elif [ -n "$aprovado" ]; then echo ok
  else echo "${estado:-pendente}"; fi
}

sleep 45 # dá tempo de o GitHub criar a rodada nova
sha=desconhecido
for _ in $(seq 1 90); do
  pr_json=$(gh api "repos/$repo/pulls/$pr" 2>/dev/null) || { sleep 60; continue; }
  sha=$(jq -r .head.sha <<<"$pr_json")
  if [ "$modo" = codex ]; then
    r=$(codex "$sha")
    [ "$r" != pendente ] && { echo "codex: $r no commit ${sha:0:7}"; exit 0; }
  elif [ "$(jq -r .draft <<<"$pr_json")" = false ]; then
    # Só as rodadas do Actions criadas depois de o PR sair do rascunho: as do rascunho
    # têm jobs pulados e checks de fora (ex.: Cloudflare) não são o CI obrigatório.
    pronto=$(gh api "repos/$repo/issues/$pr/events?per_page=100" --paginate \
               --jq '.[] | select(.event == "ready_for_review") | .created_at' 2>/dev/null | tail -1)
    runs=$(gh api "repos/$repo/actions/runs?head_sha=$sha&per_page=100" 2>/dev/null \
           | jq -r --arg desde "$pronto" '.workflow_runs[] | select(.created_at >= $desde)
                                          | [.status, (.conclusion // "-"), .name] | @tsv')
    if [ -n "$runs" ] && ! grep -qv '^completed' <<<"$runs"; then
      # Depois de sair do rascunho, toda rodada obrigatória tem de dar success (pulada não conta).
      falhas=$(awk -F'\t' '$2 != "success" {printf "%s (%s); ", $3, $2}' <<<"$runs")
      echo "ci: ${falhas:+vermelho: }${falhas:-verde} no commit ${sha:0:7} | codex: $(codex "$sha")"
      exit 0
    fi
  fi
  sleep 60
done
echo "tempo esgotado (~90 min) no commit ${sha:0:7}: confira o PR"
exit 1
