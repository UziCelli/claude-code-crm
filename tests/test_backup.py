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
