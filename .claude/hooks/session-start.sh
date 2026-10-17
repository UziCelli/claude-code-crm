#!/bin/bash
# Sessões na nuvem: instala o Graphify (grátis) e, se o grafo ainda não está no repositório, monta o mapa do código.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
command -v graphify >/dev/null 2>&1 || pip install -q graphifyy==0.9.92 || exit 0
cd "$CLAUDE_PROJECT_DIR"
# Grafo já versionado: usa o do repositório. Reconstruir mudaria o graph.json a cada commit e sujaria o git.
git ls-files --error-unmatch graphify-out/graph.json >/dev/null 2>&1 && exit 0
python3 -m graphify update . >/dev/null 2>&1 || true
