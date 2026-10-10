"""Portaria do CRM: só passa quem entrou pelo Cloudflare Access (token assinado, AUD e emissor certos).
No Render vale para tudo; no PC, só para o que chega pelo túnel (quem está no próprio PC entra direto)."""
import datetime as dt

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import acesso, db, main

EQUIPE, AUD = "vfit.cloudflareaccess.com", "aud-do-crm"
CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
# como chega uma requisição do celular pelo Cloudflare Tunnel (cloudflared repassa o Host público)
TUNEL = {"host": "crm.vfitcoachapp.com", "cf-ray": "8f1e2d3c4b5a6978-GRU", "cf-connecting-ip": "200.100.50.25"}


def token(aud=AUD, iss=f"https://{EQUIPE}", chave=CHAVE, minutos=10):
    agora = dt.datetime.now(dt.timezone.utc)
    dados = {"aud": [aud], "iss": iss, "email": "dono@exemplo.com", "iat": agora}
    if minutos is not None:   # None = token sem validade (exp)
        dados["exp"] = agora + dt.timedelta(minutes=minutos)
    return jwt.encode(dados, chave, algorithm="RS256")


class ChavesFalsas:   # no lugar de https://<equipe>/cdn-cgi/access/certs
    def get_signing_key_from_jwt(self, _):
        return type("K", (), {"key": CHAVE.public_key()})()


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    monkeypatch.setattr(acesso, "EQUIPE", EQUIPE)
    monkeypatch.setattr(acesso, "AUD", AUD)
    monkeypatch.setattr(acesso, "_chaves", lambda: ChavesFalsas())


@pytest.fixture
def desligar(monkeypatch):
    """Encerrar de mentira: guarda os pedidos em vez de mandar SIGINT para o pytest."""
    pedidos = []
    monkeypatch.setattr(main.threading, "Timer", lambda *a: type("T", (), {"start": lambda s: pedidos.append(a)})())
    return pedidos


@pytest.fixture
def na_internet(banco, monkeypatch):
    monkeypatch.setattr(acesso, "LIGADO", True)
    return TestClient(main.app)


@pytest.fixture
def no_pc(banco, monkeypatch):
    """CRM no PC com o túnel: portaria configurada no .env; o cliente de teste abre http://localhost."""
    monkeypatch.setattr(acesso, "LIGADO", False)
    return TestClient(main.app, base_url="http://localhost")


def test_sem_login_e_barrado(na_internet):
    r = na_internet.get("/")
    assert r.status_code == 403 and "Acesso restrito" in r.text
    assert na_internet.get("/static/style.css").status_code == 403


@pytest.mark.parametrize("caminho", ["/saude", "/health", "/healthz"])
def test_saude_responde_sem_login(na_internet, caminho):
    assert na_internet.get(caminho).text == "ok"
    assert na_internet.head(caminho).status_code == 200


def test_login_valido_entra_e_esconde_encerrar(na_internet):
    r = na_internet.get("/", headers={"Cf-Access-Jwt-Assertion": token()})
    assert r.status_code == 200 and "/encerrar" not in r.text
    r = na_internet.get("/clientes", cookies={"CF_Authorization": token()})
    assert r.status_code == 200


@pytest.mark.parametrize("ruim", [
    token(aud="outro-app"), token(iss="https://outra.cloudflareaccess.com"), token(minutos=-5), token(minutos=None),
    token(chave=rsa.generate_private_key(public_exponent=65537, key_size=2048)), "lixo"])
def test_token_errado_e_barrado(na_internet, ruim):
    assert na_internet.get("/", headers={"Cf-Access-Jwt-Assertion": ruim}).status_code == 403


def test_sem_configuracao_bloqueia_tudo(na_internet, monkeypatch):
    monkeypatch.setattr(acesso, "AUD", "")
    r = na_internet.get("/", headers={"Cf-Access-Jwt-Assertion": token()})
    assert r.status_code == 403 and "ainda não foi configurada" in r.text


def test_post_de_outro_site_e_recusado(na_internet):
    h = {"Cf-Access-Jwt-Assertion": token(), "host": "crm.vfitcoachapp.com"}
    r = na_internet.post("/backup", headers={**h, "origin": "https://site-malicioso.com"}, follow_redirects=False)
    assert r.status_code == 403
    r = na_internet.post("/backup", headers={**h, "origin": "https://crm.vfitcoachapp.com"}, follow_redirects=False)
    assert r.status_code == 303


def test_encerrar_indisponivel_na_internet(na_internet, desligar):
    h = {"Cf-Access-Jwt-Assertion": token(), "host": "testserver", "origin": "http://testserver"}
    assert na_internet.post("/encerrar", headers=h).status_code == 404
    # nem fingindo estar no PC: no Render o servidor não é do dono
    h = {"Cf-Access-Jwt-Assertion": token(), "origin": "http://localhost"}
    assert TestClient(main.app, base_url="http://localhost").post("/encerrar", headers=h).status_code == 404
    assert not desligar


def test_no_pc_a_portaria_fica_desligada(banco, monkeypatch):
    monkeypatch.setattr(acesso, "LIGADO", False)
    monkeypatch.setattr(acesso, "AUD", "")   # sem configurar o Cloudflare, o uso no próprio PC segue igual
    r = TestClient(main.app, base_url="http://localhost").get("/")
    assert r.status_code == 200 and "/encerrar" in r.text


# ---------- PC + Cloudflare Tunnel ----------
@pytest.mark.parametrize("host", ["localhost", "localhost:8765", "127.0.0.1:8765", "[::1]:8765"])
def test_no_pc_local_entra_sem_login_e_ve_encerrar(no_pc, host):
    # Host no cabeçalho: o TestClient de algumas versões do Starlette não aceita IPv6 no base_url
    r = TestClient(main.app, base_url="http://localhost").get("/", headers={"host": host})
    assert r.status_code == 200 and "/encerrar" in r.text


def test_no_pc_tunel_sem_login_e_barrado(no_pc):
    r = no_pc.get("/", headers=TUNEL)
    assert r.status_code == 403 and "Acesso restrito" in r.text
    assert no_pc.get("/static/style.css", headers=TUNEL).status_code == 403
    assert no_pc.post("/backup", headers={**TUNEL, "origin": "https://crm.vfitcoachapp.com"}).status_code == 403


@pytest.mark.parametrize("host", ["crm.vfitcoachapp.com", "testserver", "site-malicioso.com", "localhost.evil.com", ""])
def test_no_pc_outro_endereco_sem_cloudflare_tambem_e_barrado(no_pc, host):
    """Host que não é do próprio PC é remoto mesmo sem cf-ray (ex.: site que aponta o próprio domínio para 127.0.0.1)."""
    assert no_pc.get("/", headers={"host": host}).status_code == 403


def test_no_pc_tunel_com_login_entra_sem_encerrar(no_pc):
    r = no_pc.get("/", headers={**TUNEL, "Cf-Access-Jwt-Assertion": token()})
    assert r.status_code == 200 and "/encerrar" not in r.text
    r = no_pc.get("/clientes", headers=TUNEL, cookies={"CF_Authorization": token()})
    assert r.status_code == 200


@pytest.mark.parametrize("ruim", [token(aud="outro-app"), token(minutos=-5), token(minutos=None), "lixo"])
def test_no_pc_tunel_com_token_errado_e_barrado(no_pc, ruim):
    assert no_pc.get("/", headers={**TUNEL, "Cf-Access-Jwt-Assertion": ruim}).status_code == 403


@pytest.mark.parametrize("marca", ["cf-ray", "cf-connecting-ip", "x-forwarded-for"])
def test_no_pc_localhost_vindo_pelo_cloudflare_e_barrado(no_pc, marca):
    """Túnel configurado para trocar o Host por localhost continua remoto: o Cloudflare deixa a sua marca."""
    r = no_pc.get("/", headers={marca: "1.2.3.4"})
    assert r.status_code == 403 and "/encerrar" not in r.text


def test_no_pc_post_pelo_tunel_de_outro_site_e_recusado(no_pc):
    h = {**TUNEL, "Cf-Access-Jwt-Assertion": token()}
    r = no_pc.post("/backup", headers={**h, "origin": "https://site-malicioso.com"}, follow_redirects=False)
    assert r.status_code == 403
    r = no_pc.post("/backup", headers={**h, "origin": "https://crm.vfitcoachapp.com"}, follow_redirects=False)
    assert r.status_code == 303


def test_no_pc_encerrar_so_para_quem_esta_no_pc(no_pc, desligar):
    h = {**TUNEL, "Cf-Access-Jwt-Assertion": token(), "origin": "https://crm.vfitcoachapp.com"}
    assert no_pc.post("/encerrar", headers=h).status_code == 404
    assert no_pc.post("/encerrar", headers={"cf-ray": "abc", "Cf-Access-Jwt-Assertion": token(),
                                            "origin": "http://localhost"}).status_code == 404
    assert not desligar
    r = no_pc.post("/encerrar")   # no próprio PC: desliga
    assert r.status_code == 200 and "CRM encerrado" in r.text and len(desligar) == 1


def test_no_pc_tunel_sem_configuracao_bloqueia(no_pc, monkeypatch):
    monkeypatch.setattr(acesso, "EQUIPE", "")
    monkeypatch.setattr(acesso, "AUD", "")
    r = no_pc.get("/", headers={**TUNEL, "Cf-Access-Jwt-Assertion": token()})
    assert r.status_code == 403 and "ainda não foi configurada" in r.text and ".env do PC" in r.text
    assert no_pc.get("/").status_code == 200   # no próprio PC continua abrindo


@pytest.mark.parametrize("caminho", ["/saude", "/health", "/healthz"])
def test_no_pc_saude_livre_pelo_tunel(no_pc, monkeypatch, caminho):
    assert no_pc.get(caminho, headers=TUNEL).text == "ok"
    monkeypatch.setattr(acesso, "AUD", "")
    assert no_pc.head(caminho, headers=TUNEL).status_code == 200
