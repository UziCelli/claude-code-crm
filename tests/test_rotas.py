"""Teste de fumaça: todas as telas abrem (200) num banco temporário. Rede de segurança para mudanças nos templates."""
import pytest
from fastapi.testclient import TestClient

from app import db, main

TELAS = ["/", "/clientes", "/clientes/novo", "/leads", "/grade", "/simulador", "/explorador",
         "/campanhas", "/rotina", "/configuracoes", "/dados"]


@pytest.fixture
def cliente_http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")  # nunca tocar nos backups reais
    db.iniciar_banco()
    con = db.conectar()
    with con:
        cid = con.execute("INSERT INTO clientes (nome) VALUES ('Aluno Teste')").lastrowid
    con.close()
    return TestClient(main.app), cid  # sem "with": o lifespan (backup diário) não roda


@pytest.mark.parametrize("url", TELAS)
def test_tela_abre(cliente_http, url):
    http, _ = cliente_http
    assert http.get(url).status_code == 200


def test_ficha_do_cliente_abre(cliente_http):
    http, cid = cliente_http
    r = http.get(f"/clientes/{cid}")
    assert r.status_code == 200 and "Aluno Teste" in r.text
