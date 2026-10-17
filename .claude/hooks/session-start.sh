#!/bin/bash
# Sessões na nuvem: instala o Graphify (grátis) e monta o mapa do código.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
command -v graphify >/dev/null 2>&1 || pip install -q graphifyy==0.9.92 || exit 0
cd "$CLAUDE_PROJECT_DIR"
python3 -m graphify update . >/dev/null 2>&1 || true
