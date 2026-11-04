"""Aviso (sem bloquear) quando um horário fixo cai colado ou na mesma hora de uma aula em outro local."""
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import db, main


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    c = db.conectar()
    yield c
    c.close()


def _aluno(con, nome, status="ativo"):
    with con:
        return con.execute("INSERT INTO clientes (nome, status, local, tipo_servico) VALUES (?,?,'CIA','Pacote de Aulas')",
                           (nome, status)).lastrowid


def _fixo(con, cid, dia, hora, local):
    with con:
        con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?,?,?,?)", (cid, dia, hora, local))


def test_hora_colada_em_outro_local_avisa(con):
    _fixo(con, _aluno(con, "Ana"), 1, 8, "CIA")
    a = main.aviso_deslocamento(con, [(1, 9, "SmartFit")])
    assert "Atenção" in a and "08h em CIA" in a and "09h em SmartFit" in a


def test_mesma_hora_em_outro_local_avisa(con):
    _fixo(con, _aluno(con, "Ana"), 1, 8, "CIA")
    assert "ao mesmo tempo" in main.aviso_deslocamento(con, [(1, 8, "SmartFit")])


def test_mesmo_local_outro_dia_ou_inativo_nao_avisam(con):
    _fixo(con, _aluno(con, "Ana"), 1, 8, "CIA")
    _fixo(con, _aluno(con, "Bia", "inativo"), 1, 9, "SmartFit")
    assert main.aviso_deslocamento(con, [(1, 9, "CIA"), (1, 7, "cia")]) == ""
    assert main.aviso_deslocamento(con, [(2, 9, "SmartFit")]) == ""
    assert main.aviso_deslocamento(con, [(1, 10, "SmartFit")]) == ""   # 10h longe das 8h; Bia (inativa) não conta


def test_o_proprio_aluno_mudando_de_local_na_mesma_hora_nao_avisa(con):
    cid = _aluno(con, "Ana")
    _fixo(con, cid, 1, 8, "CIA")
    assert main.aviso_deslocamento(con, [(1, 8, "SmartFit")], cid) == ""


def test_os_horarios_novos_entre_si_contam(con):
    assert "09h em SmartFit" in main.aviso_deslocamento(con, [(3, 8, "CIA"), (3, 9, "SmartFit")])


def test_rota_da_agenda_mostra_o_aviso_e_inclui_mesmo_assim(con):
    _fixo(con, _aluno(con, "Ana"), 1, 8, "CIA")
    caio = _aluno(con, "Caio")
    http = TestClient(main.app, base_url="http://localhost")
    r = http.post("/agenda/incluir", data={"cliente_id": caio, "local": "SmartFit", "dia": 1, "hora": 9, "repetir": 1},
                  follow_redirects=False)
    loc = unquote(r.headers["location"])
    assert "msg=" in loc and "Atenção" in loc and "erro=" not in loc
    assert con.execute("SELECT COUNT(*) FROM agenda_fixos WHERE cliente_id=? AND local='SmartFit'", (caio,)).fetchone()[0] == 1
