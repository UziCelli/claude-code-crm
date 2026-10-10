"""Portaria do CRM: quem chega pela internet só passa se entrou pelo Cloudflare Access.

Dois jeitos de chegar pela internet, os dois atrás do Cloudflare Access (crm.vfitcoachapp.com):
- Render (CRM_NUVEM=1, definido no render.yaml): toda requisição passa pela portaria.
- PC + Cloudflare Tunnel (cloudflared -> localhost:8765): só a requisição *remota* passa pela portaria;
  quem abre o CRM no próprio PC (http://localhost:8765) entra direto, como sempre.
O Cloudflare Access pede o e-mail e manda um código; depois disso ele envia em cada requisição um token
assinado (cabeçalho Cf-Access-Jwt-Assertion). Aqui conferimos a assinatura, o emissor, o "AUD" do app e a validade,
então quem tentar entrar direto pelo endereço *.onrender.com (sem passar pelo Cloudflare) é barrado.
Sem CF_ACCESS_TEAM_DOMAIN / CF_ACCESS_AUD configurados (no Render ou no .env do PC), tudo o que é remoto
fica bloqueado (falha fechada).
"""
import os
from urllib.parse import urlparse

import jwt

from . import nuvem

nuvem.carregar_env()   # no PC as variáveis CF_ACCESS_* ficam no .env: carregar antes de ler (não sobrescreve nada)

LIGADO = os.environ.get("CRM_NUVEM") == "1"
EQUIPE = os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip().removeprefix("https://").strip("/")
AUD = os.environ.get("CF_ACCESS_AUD", "").strip()
LIVRES = {"/saude", "/health", "/healthz"}   # checagem de saúde do Render (qualquer nome): não mostra dado nenhum
LOCAIS = {"localhost", "127.0.0.1", "::1"}   # nomes do próprio PC (o uvicorn só escuta em 127.0.0.1)
# o Cloudflare (e o túnel) sempre acrescenta cf-ray e cf-connecting-ip; os outros denunciam qualquer proxy no caminho
CABECALHOS_PROXY = ("cf-ray", "cf-connecting-ip", "cf-visitor", "cdn-loop", "x-forwarded-for", "forwarded")
_jwks = None

MENSAGENS = {
    "config": "A portaria do Cloudflare Access ainda não foi configurada (CF_ACCESS_TEAM_DOMAIN e CF_ACCESS_AUD, "
              "no .env do PC ou nas configurações do Render). Por segurança, nada é mostrado pela internet.",
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
    return jwt.decode(token, chave, algorithms=["RS256"], audience=AUD, issuer=f"https://{EQUIPE}",
                      options={"require": ["exp"]})   # token sem validade não serve


def _nome_host(valor: str) -> str:
    """'localhost:8765' -> 'localhost'; '[::1]:8765' -> '::1'."""
    valor = valor.strip().lower()
    if valor.startswith("["):
        return valor[1:].partition("]")[0]
    return valor if valor.count(":") > 1 else valor.partition(":")[0]


def local(alvo) -> bool:
    """True só para quem abriu o CRM no próprio PC: um único Host localhost/127.0.0.1/::1 e nenhum cabeçalho
    de proxy (o que vem pelo túnel sempre traz cf-ray). Na dúvida é remoto. Aceita a requisição ou os cabeçalhos."""
    cabecalhos = getattr(alvo, "headers", alvo)
    hosts = cabecalhos.getlist("host")
    if len(hosts) != 1 or _nome_host(hosts[0]) not in LOCAIS:
        return False
    return not any(c in cabecalhos for c in CABECALHOS_PROXY)


def pode_encerrar(alvo) -> bool:
    """Botão/rota Encerrar: só no PC e por quem está nele (nunca no Render, nunca pelo túnel)."""
    return not LIGADO and local(alvo)


def motivo_bloqueio(metodo: str, caminho: str, cabecalhos, cookies) -> str | None:
    """None = pode passar; senão, a chave de MENSAGENS que explica o bloqueio.
    No Render tudo passa pela portaria; no PC, só o que chega de fora (túnel)."""
    if caminho in LIVRES or (not LIGADO and local(cabecalhos)):
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
