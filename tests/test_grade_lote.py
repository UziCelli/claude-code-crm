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
    base = {"tipo": "Pacotes", "local": "CIA", "so_este": 1}
    return TestClient(main.app, base_url="http://localhost").post("/grade/slot", data={**base, **dados}, follow_redirects=False)


def test_lote_mantem_status_e_cliente(con_temp):
    ins = ("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, cliente_id, cliente_nome, multiplicador)"
           " VALUES (?,?,?,?,?,?,?,?)")
    with con_temp:
        con_temp.execute(ins, ("Pacotes", 1, "CIA", 7, "ocupado", None, "Fulano", 1.0))
        con_temp.execute(ins, ("Pacotes", 2, "CIA", 7, "livre", None, None, 1.0))
        con_temp.execute(ins, ("Mensalidades", 1, "CIA", 7, "livre", None, None, 1.0))
    r = _post(celulas=["1-7", "2-7", "3-8", "9-9"], status="", multiplicador="0,9")
    assert r.status_code == 303 and "3+hor" not in r.headers["location"] and "3%20hor" in r.headers["location"]
    a, b, c = _slot(con_temp, "Pacotes", 1, 7), _slot(con_temp, "Pacotes", 2, 7), _slot(con_temp, "Pacotes", 3, 8)
    assert (a["status"], a["cliente_nome"], a["multiplicador"]) == ("ocupado", "Fulano", 0.9)
    assert (b["status"], b["multiplicador"]) == ("livre", 0.9)
    assert (c["status"], c["multiplicador"]) == ("livre", 0.9)
    m = _slot(con_temp, "Mensalidades", 1, 7)
    assert (m["status"], m["multiplicador"]) == ("livre", 1.0)


def test_lote_sem_celula_valida(con_temp):
    r = _post(celulas=["0-0", "x"], status="livre")
    assert "erro=" in r.headers["location"]


def test_celula_unica_antiga(con_temp):
    r = _post(dia=3, hora=9, status="indisponivel", multiplicador="1")
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    s = _slot(con_temp, "Pacotes", 3, 9)
    assert (s["status"], s["multiplicador"]) == ("indisponivel", 1.0)
