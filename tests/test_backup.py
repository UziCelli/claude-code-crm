"""Backup local: o CRM abre mesmo com o backup falhando; restauração recusa arquivo corrompido."""
import os

import pytest
from fastapi.testclient import TestClient

from app import db, main


@pytest.fixture
def banco_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")  # nunca tocar nos backups reais
    db.iniciar_banco()
    return tmp_path


def test_crm_abre_com_backup_falhando(banco_tmp, monkeypatch):
    def falha():
        raise OSError("disco cheio")
    monkeypatch.setattr(db, "backup_diario", falha)
    with TestClient(main.app) as c:  # com "with": roda o lifespan
        assert c.get("/").status_code == 200


def test_restaurar_corrompido_e_recusado(banco_tmp):
    pasta = db.pasta_backup()
    (pasta / "crm-ruim.db").write_bytes(os.urandom(4096))
    antes = db.DB_PATH.read_bytes()
    with pytest.raises(ValueError):
        db.restaurar_backup("crm-ruim.db")
    assert db.DB_PATH.read_bytes() == antes
    assert not list(pasta.glob("antes-restaurar-*.db"))  # recusou antes de mexer em qualquer coisa


def test_restaurar_arquivo_vazio_e_recusado(banco_tmp):
    pasta = db.pasta_backup()
    (pasta / "vazio.db").write_bytes(b"")
    antes = db.DB_PATH.read_bytes()
    with pytest.raises(ValueError):
        db.restaurar_backup("vazio.db")
    assert db.DB_PATH.read_bytes() == antes
    assert not list(pasta.glob("antes-restaurar-*.db"))  # recusou antes de mexer em qualquer coisa


def test_copiar_dados_deixa_destino_igual_a_origem(banco_tmp):
    """Usado para subir o crm.db ao Turso e para restaurar backup no modo nuvem."""
    from app import nuvem
    con = db.conectar()
    with con:
        cid = con.execute("INSERT INTO clientes (nome, status) VALUES ('Ana', 'ativo')").lastrowid
        con.execute("INSERT INTO cliente_eventos (cliente_id, data, tipo, descricao) VALUES (?, '2026-10-01', 'aula', 'x')", (cid,))
    con.close()
    copia = db.fazer_backup()
    con = db.conectar()
    with con:
        con.execute("DELETE FROM cliente_eventos")
        con.execute("UPDATE clientes SET nome='Outra'")
        con.execute("INSERT INTO clientes (nome, status) VALUES ('Sobra', 'ativo')")
    contagem = nuvem.copiar_dados(copia, con)
    assert contagem["clientes"] == 1 and contagem["cliente_eventos"] == 1
    assert [r["nome"] for r in con.execute("SELECT nome FROM clientes")] == ["Ana"]
    con.close()


def test_parametros_nomeados_viram_posicionais():
    from app import nuvem
    sql, p = nuvem._posicional("UPDATE t SET a=:a, b=':nao' WHERE c=:c AND d=:a", {"a": 1, "c": 3, "x": 9})
    assert sql == "UPDATE t SET a=?, b=':nao' WHERE c=? AND d=?" and p == (1, 3, 1)


def test_env_com_bom_e_textos_de_exemplo(tmp_path, monkeypatch):
    from app import nuvem
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("﻿TURSO_DATABASE_URL=libsql://crm-teste.turso.io\n", encoding="utf-8")   # BOM do Bloco de Notas
    nuvem.carregar_env(env)
    assert nuvem.os.environ["TURSO_DATABASE_URL"] == "libsql://crm-teste.turso.io"
    assert nuvem.preenchido("libsql://crm-teste.turso.io")
    assert not nuvem.preenchido("libsql://NOME-DO-BANCO-SEU-USUARIO.turso.io")
    assert not nuvem.preenchido("cole-o-token-aqui") and not nuvem.preenchido("")
