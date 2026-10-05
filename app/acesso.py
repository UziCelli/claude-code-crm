"""Portaria do CRM publicado na internet (Render): só passa quem entrou pelo Cloudflare Access.

Ligada por CRM_NUVEM=1 (definido no render.yaml). No PC (localhost) fica desligada.
O Cloudflare Access pede o e-mail e manda um código; depois disso ele envia em cada requisição um token
assinado (cabeçalho Cf-Access-Jwt-Assertion). Aqui conferimos a assinatura, o emissor e o "AUD" do app,
então quem tentar entrar direto pelo endereço *.onrender.com (sem passar pelo Cloudflare) é barrado.
Sem CF_ACCESS_TEAM_DOMAIN / CF_ACCESS_AUD configurados, tudo fica bloqueado (falha fechada).
"""
import os
from urllib.parse import urlparse

import jwt

LIGADO = os.environ.get("CRM_NUVEM") == "1"
EQUIPE = os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip().removeprefix("https://").strip("/")
AUD = os.environ.get("CF_ACCESS_AUD", "").strip()
LIVRES = {"/saude", "/health", "/healthz"}   # checagem de saúde do Render (qualquer nome): não mostra dado nenhum
_jwks = None

MENSAGENS = {
    "config": "O CRM está publicado, mas a portaria do Cloudflare Access ainda não foi configurada no Render "
              "(CF_ACCESS_TEAM_DOMAIN e CF_ACCESS_AUD). Por segurança, nada é mostrado.",
    "sem": "Entre pelo endereço do CRM (crm.vfitcoachapp.com) para fazer o login com o seu e-mail.",
    "invalido": "Login expirado ou inválido. Abra crm.vfitcoachapp.com de novo para entrar.",
    "origem": "Pedido recusado: ele não veio de uma tela do próprio CRM.",
}


def _chaves():
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(f"https://{EQUIPE}/cdn-cgi/access/certs", cache_keys=True)
    return _jwks


def verificar(token: str) -> dict:
    """Devolve os dados do token (com o e-mail) ou levanta erro se a assinatura/AUD/emissor/validade não baterem."""
    chave = _chaves().get_signing_key_from_jwt(token).key
    return jwt.decode(token, chave, algorithms=["RS256"], audience=AUD, issuer=f"https://{EQUIPE}")


def motivo_bloqueio(metodo: str, caminho: str, cabecalhos, cookies) -> str | None:
    """None = pode passar; senão, a chave de MENSAGENS que explica o bloqueio."""
    if not LIGADO or caminho in LIVRES:
        return None
    if not (EQUIPE and AUD):
        return "config"
    token = cabecalhos.get("cf-access-jwt-assertion") or cookies.get("CF_Authorization")
    if not token:
        return "sem"
    try:
        verificar(token)
    except Exception:
        return "invalido"
    if metodo == "POST":   # outro site não pode enviar formulário usando o login do Cloudflare (CSRF)
        origem = cabecalhos.get("origin") or cabecalhos.get("referer") or ""
        if urlparse(origem).netloc != cabecalhos.get("host"):
            return "origem"
    return None
