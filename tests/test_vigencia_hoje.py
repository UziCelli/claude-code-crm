"""Excluir um horário fixo hoje vale a partir de amanhã; aluno inativo não apaga o histórico de aulas marcadas."""
import datetime as dt

import pytest

from app import db, main

SEG = dt.date(2026, 10, 12)
TER, PROX_TER = "2026-10-13", "2026-10-20"


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


def _fixo(con, cid, dia, hora, criado="2026-09-01 10:00:00", excluido=None, vigente=None):
    with con:
        con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, criado_em, excluido_em, vigente_de) VALUES (?,?,?,'CIA',?,?,?)",
                    (cid, dia, hora, criado, excluido, vigente))


def _aulas(con, segunda=SEG):
    return {(a["nome"], a["data"], a["hora"]) for a in main.aulas_da_semana(con, segunda, SEG + dt.timedelta(days=1))}


def test_excluir_hoje_mantem_a_aula_de_hoje_e_some_amanha(con):
    _fixo(con, _aluno(con, "Ana"), 2, 8, excluido=f"{TER} 07:30:00")
    assert ("Ana", TER, 8) in _aulas(con)
    assert not _aulas(con, SEG + dt.timedelta(days=7))


def test_mudar_de_hora_hoje_mostra_so_a_nova(con):
    cid = _aluno(con, "Ana")
    _fixo(con, cid, 2, 8, excluido=f"{TER} 07:30:00")
    _fixo(con, cid, 2, 9, criado=f"{TER} 07:30:00", vigente=TER)
    assert _aulas(con) == {("Ana", TER, 9)}


def test_criado_e_excluido_no_mesmo_dia_nunca_vale(con):
    _fixo(con, _aluno(con, "Ana"), 2, 8, criado=f"{TER} 07:00:00", excluido=f"{TER} 07:30:00")
    assert not _aulas(con)


def test_inativo_mantem_as_aulas_marcadas(con):
    ana, bia = _aluno(con, "Ana", "inativo"), _aluno(con, "Bia", "inativo")
    _fixo(con, ana, 1, 8)
    _fixo(con, bia, 1, 9)
    with con:
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, hora) VALUES (?, 'aula', ?, 8)", (ana, SEG.isoformat()))
    assert _aulas(con) == {("Ana", SEG.isoformat(), 8)}   # Bia (sem marca) não vira "pendente"
