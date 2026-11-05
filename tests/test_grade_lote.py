"""Edicao em lote da grade: POST /grade/slot com varias celulas."""
import pytest
from fastapi.testclient import TestClient

from app import db, main


@pytest.fixture
def con_temp(tmp_path, monkeypatch):
    db_path = tmp_path / "crm.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(db_path)
    con = db.conectar(db_path)
    yield con
    con.close()


def _slot(con, t, d, h):
    return con.execute("SELECT * FROM grade_slots WHERE tipo_calculo=? AND dia=? AND local='CIA' AND hora=?",
                       (t, d, h)).fetchone()


def _post(**dados):
    base = {"tipo": "Pacotes", "local": "CIA"}
    return TestClient(main.app, base_url="http://localhost").post("/grade/slot", data={**base, **dados}, follow_redirects=False)


def _inserir(con_temp):
    ins = ("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, cliente_id, cliente_nome, multiplicador)"
           " VALUES (?,?,?,?,?,?,?,?)")
    with con_temp:
        con_temp.execute(ins, ("Pacotes", 1, "CIA", 7, "ocupado", None, "Fulano", 1.0))
        con_temp.execute(ins, ("Pacotes", 2, "CIA", 7, "livre", None, None, 1.0))
        con_temp.execute(ins, ("Mensalidades", 1, "CIA", 7, "livre", None, None, 1.0))


def test_lote_sem_situacao_nao_grava(con_temp):
    """O multiplicador saiu da janela do horário (agora é por hora, em Multiplicadores): sem situação, nada muda."""
    _inserir(con_temp)
    r = _post(celulas=["1-7", "2-7", "3-8", "9-9"], status="")
    assert r.status_code == 303 and "erro=" in r.headers["location"]
    a = _slot(con_temp, "Pacotes", 1, 7)
    assert (a["status"], a["cliente_nome"]) == ("ocupado", "Fulano") and _slot(con_temp, "Pacotes", 3, 8) is None


def test_lote_grava_a_situacao_nos_dois_tipos(con_temp):
    _inserir(con_temp)
    r = _post(celulas=["1-7", "2-7", "3-8", "9-9"], status="indisponivel")
    assert r.status_code == 303 and "3+hor" not in r.headers["location"] and "3%20hor" in r.headers["location"]
    for t in ("Pacotes", "Mensalidades"):
        assert [_slot(con_temp, t, d, h)["status"] for d, h in ((1, 7), (2, 7), (3, 8))] == ["indisponivel"] * 3
    assert _slot(con_temp, "Pacotes", 1, 7)["cliente_nome"] is None


def test_lote_sem_celula_valida(con_temp):
    r = _post(celulas=["0-0", "x"], status="livre")
    assert "erro=" in r.headers["location"]


def test_celula_unica_antiga(con_temp):
    r = _post(dia=3, hora=9, status="indisponivel")
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    s = _slot(con_temp, "Pacotes", 3, 9)
    assert s["status"] == "indisponivel"
