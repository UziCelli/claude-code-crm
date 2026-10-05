"""Portaria do CRM publicado: só passa quem entrou pelo Cloudflare Access (token assinado, AUD e emissor certos)."""
import datetime as dt

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import acesso, db, main

EQUIPE, AUD = "vfit.cloudflareaccess.com", "aud-do-crm"
CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(aud=AUD, iss=f"https://{EQUIPE}", chave=CHAVE, minutos=10):
    agora = dt.datetime.now(dt.timezone.utc)
    return jwt.encode({"aud": [aud], "iss": iss, "email": "dono@exemplo.com", "iat": agora,
                       "exp": agora + dt.timedelta(minutes=minutos)}, chave, algorithm="RS256")


class ChavesFalsas:   # no lugar de https://<equipe>/cdn-cgi/access/certs
    def get_signing_key_from_jwt(self, _):
        return type("K", (), {"key": CHAVE.public_key()})()


@pytest.fixture
def na_internet(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    monkeypatch.setattr(acesso, "LIGADO", True)
    monkeypatch.setattr(acesso, "EQUIPE", EQUIPE)
    monkeypatch.setattr(acesso, "AUD", AUD)
    monkeypatch.setattr(acesso, "_chaves", lambda: ChavesFalsas())
    return TestClient(main.app)


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
    token(aud="outro-app"), token(iss="https://outra.cloudflareaccess.com"), token(minutos=-5),
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


def test_encerrar_indisponivel_na_internet(na_internet):
    h = {"Cf-Access-Jwt-Assertion": token(), "host": "testserver", "origin": "http://testserver"}
    assert na_internet.post("/encerrar", headers=h).status_code == 404


def test_no_pc_a_portaria_fica_desligada(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    monkeypatch.setattr(acesso, "LIGADO", False)
    r = TestClient(main.app).get("/")
    assert r.status_code == 200 and "/encerrar" in r.text
