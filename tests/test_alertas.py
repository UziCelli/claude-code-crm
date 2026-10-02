"""Testes para alerts, lead parado e redirecionamento com destaque."""
import datetime as dt
import pytest
from fastapi.testclient import TestClient

from app import db, main


@pytest.fixture
def con_temp(tmp_path, monkeypatch):
    """Conexão com banco temporário."""
    db_path = tmp_path / "crm.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(db_path)
    con = db.conectar(db_path)
    yield con
    con.close()


def test_dias_parado(con_temp):
    """Calcula dias parado com base na última mudança de etapa."""
    hoje = dt.date.today().isoformat()
    tres_dias_atras = (dt.date.today() - dt.timedelta(days=3)).isoformat()

    # Lead parado há 3 dias (limite da etapa "lead" é 2)
    lead_parado = {
        "id": 1,
        "nome": "Test",
        "etapa": "lead",
        "data_mudanca_etapa": tres_dias_atras,
        "atualizado_em": tres_dias_atras + " 00:00:00"
    }
    dias = main.dias_parado(con_temp, lead_parado, hoje)
    assert dias == 3

    # Lead que ainda não passou do limite
    um_dia_atras = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    lead_fresco = {
        "id": 2,
        "nome": "Fresh",
        "etapa": "lead",
        "data_mudanca_etapa": um_dia_atras,
        "atualizado_em": um_dia_atras + " 00:00:00"
    }
    dias = main.dias_parado(con_temp, lead_fresco, hoje)
    assert dias is None

    # Lead em conversa com limite 4
    lead_conversa = {
        "id": 3,
        "nome": "Conv",
        "etapa": "conversa",
        "data_mudanca_etapa": tres_dias_atras,
        "atualizado_em": tres_dias_atras + " 00:00:00"
    }
    dias = main.dias_parado(con_temp, lead_conversa, hoje)
    assert dias is None  # 3 dias < 4 limite


@pytest.fixture
def cliente_http(tmp_path, monkeypatch):
    """Cliente HTTP para testar rotas."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    con = db.conectar(tmp_path / "crm.db")
    with con:
        lid = con.execute("INSERT INTO leads (nome, etapa, canal_origem) VALUES (?, ?, ?)",
                         ("Lead Teste", "lead", "Instagram")).lastrowid
    con.close()
    return TestClient(main.app), lid  # sem "with": o lifespan não roda


def test_post_etapa_redireciona_com_destaque(cliente_http):
    """POST /leads/{lid}/etapa redireciona para /leads?destaque=<id>."""
    http, lid = cliente_http

    # Fazer POST para mudar etapa
    r = http.post(f"/leads/{lid}/etapa", data={"etapa": "conversa"}, follow_redirects=False)

    # Verificar que é redirect 303
    assert r.status_code == 303
    assert f"destaque={lid}" in r.headers["location"]
    assert "/leads" in r.headers["location"]


def test_post_etapa_cliente_redireciona_com_destaque(cliente_http):
    """Converter lead para cliente redireciona com destaque."""
    http, lid = cliente_http

    # Ir para avaliação primeira
    http.post(f"/leads/{lid}/etapa", data={"etapa": "conversa"}, follow_redirects=False)
    http.post(f"/leads/{lid}/etapa", data={"etapa": "avaliacao"}, follow_redirects=False)

    # Converter para cliente
    r = http.post(f"/leads/{lid}/etapa", data={"etapa": "cliente"}, follow_redirects=False)

    # Verificar redirect com destaque
    assert r.status_code == 303
    assert f"destaque={lid}" in r.headers["location"]
    assert "/leads" in r.headers["location"]
