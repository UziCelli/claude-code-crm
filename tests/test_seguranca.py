"""Repositório público: nada de chave, banco ou .env pode ser versionado.
Roda sobre os arquivos que o git controla (git ls-files), então pega o erro antes de ir para o GitHub."""
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
PROIBIDOS = re.compile(r"(^|/)(\.env|data/.*|.*\.(db|sqlite3?|pem|key|pfx|p12)|continuar-com-omniroute\.bat)$")
# formatos de chave conhecidos (nada de palavras soltas como "token", que aparecem em qualquer código)
CHAVES = re.compile(
    r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}"   # JWT / token do Turso e do Cloudflare
    r"|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    r"|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def versionados() -> list[str]:
    try:
        saida = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("sem git por aqui (ex.: pasta baixada sem .git)")
    return [a for a in saida.splitlines() if a]


def test_nenhum_arquivo_secreto_versionado():
    assert [a for a in versionados() if PROIBIDOS.search(a)] == []


def test_nenhuma_chave_no_codigo():
    achados = []
    for nome in versionados():
        caminho = RAIZ / nome
        if caminho.suffix in (".png", ".ico", ".woff2", ".svg") or not caminho.is_file():
            continue
        texto = caminho.read_text(encoding="utf-8", errors="ignore")
        achados += [f"{nome}: {m.group(0)[:12]}…" for m in CHAVES.finditer(texto)]
    assert achados == []


def test_gitignore_cobre_segredos():
    regras = (RAIZ / ".gitignore").read_text(encoding="utf-8").split()
    for regra in (".env", "data/", "*.db"):
        assert regra in regras
