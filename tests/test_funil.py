"""Previsao do funil e motivos de perda."""
import pytest

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


def test_previsao_e_motivos(con_temp):
    con = con_temp
    for v in (200, 400):
        con.execute("INSERT INTO clientes (nome, valor) VALUES ('c', ?)", (v,))
    con.execute("INSERT INTO clientes (nome, valor, status) VALUES ('i', 9999, 'inativo')")
    for etapa, motivo in [("lead", None), ("conversa", None), ("avaliacao", None), ("cliente", None),
                          ("perdido", "Preco"), ("perdido", " preco "), ("perdido", ""), ("perdido", "Horario")]:
        con.execute("INSERT INTO leads (nome, canal_origem, etapa, motivo_perda) VALUES ('l', 'x', ?, ?)", (etapa, motivo))
    con.commit()

    p = main.previsao_funil(con)
    # ticket 300; (0.10 + 0.30 + 0.60) * 300 = 300
    assert p["ticket"] == 300 and p["leads"] == 3 and p["receita"] == pytest.approx(300)

    assert [(m["m"], m["n"]) for m in main.motivos_perda(con)] == [("preco", 2), ("horario", 1), ("sem motivo", 1)]
