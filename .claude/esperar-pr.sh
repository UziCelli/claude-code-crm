#!/usr/bin/env bash
# Espera sem gastar IA: rode em segundo plano. Termina quando o Codex ou o CI tem
# resultado no commit atual do PR e imprime uma linha com o estado.
# Uso: .claude/esperar-pr.sh codex|ci <número do PR>   (desiste depois de ~90 min)
set -u
modo=${1:?use codex ou ci}
pr=${2:?informe o número do PR}
repo=$(git remote get-url origin | sed -E 's#\.git$##; s#:#/#g' | awk -F/ '{print $(NF-1)"/"$NF}')

codex() { # revisão do Codex no commit $1: ok | achados | pendente
  local r
  r=$(gh api "repos/$repo/issues/$pr/comments?per_page=100" --paginate \
        --jq '.[] | select(.user.login == "chatgpt-codex-connector[bot]") | .body' 2>/dev/null \
      | grep -o 'codex-review-state:v1 {.*}' | tail -1 | sed 's/^codex-review-state:v1 //' \
      | jq -r --arg sha "$1" '.code_review
          | if .commit_sha == $sha and .status == "completed"
            then (if .has_unresolved_findings then "achados" else "ok" end)
            else "pendente" end' 2>/dev/null)
  echo "${r:-pendente}"
}

sleep 45 # dá tempo de o GitHub criar a rodada nova
sha=desconhecido
for _ in $(seq 1 90); do
  sha=$(gh api "repos/$repo/pulls/$pr" --jq .head.sha 2>/dev/null) || { sleep 60; continue; }
  if [ "$modo" = codex ]; then
    r=$(codex "$sha")
    [ "$r" != pendente ] && { echo "codex: $r no commit ${sha:0:7}"; exit 0; }
  else
    runs=$(gh api "repos/$repo/commits/$sha/check-runs?per_page=100" \
             --jq '.check_runs[] | [.status, (.conclusion // "-"), .name] | @tsv' 2>/dev/null)
    # Pronto quando nada está rodando e ao menos um job de verdade (não pulado) terminou.
    if [ -n "$runs" ] && ! grep -qv '^completed' <<<"$runs" && grep -qv $'^completed\tskipped\t' <<<"$runs"; then
      falhas=$(awk -F'\t' '$2 != "success" && $2 != "skipped" && $2 != "neutral" {printf "%s (%s); ", $3, $2}' <<<"$runs")
      echo "ci: ${falhas:+vermelho: }${falhas:-verde} no commit ${sha:0:7} | codex: $(codex "$sha")"
      exit 0
    fi
  fi
  sleep 60
done
echo "tempo esgotado (~90 min) no commit ${sha:0:7}: confira o PR"
exit 1
