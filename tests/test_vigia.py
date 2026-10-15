"""Vigia: religa o CRM se a porta cair, mas respeita o botão Encerrar e a atualização automática.
Tudo numa pasta temporária: nunca toca em data/ de verdade."""
import os
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app import atualizar, db, main, vigia


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(atualizar, "DATA", data)
    monkeypatch.setattr(atualizar, "LOG", data / "atualizacao.log")
    monkeypatch.setattr(atualizar, "ATUALIZANDO", data / "atualizando.txt")
    monkeypatch.setattr(vigia, "DATA", data)
    monkeypatch.setattr(vigia, "DESLIGADO", data / "desligado.txt")
    monkeypatch.setattr(vigia, "ATUALIZANDO", data / "atualizando.txt")
    monkeypatch.setattr(vigia, "TRAVA", data / "vigia.pid")
    monkeypatch.setattr(vigia, "FORA_MIN", 1)
    monkeypatch.setattr(vigia, "fora", 0)
    data.mkdir()
    return data


@pytest.fixture
def aberturas(monkeypatch):
    """Porta fechada por padrão; abrir_crm de mentira guarda os pedidos."""
    pedidos = []
    monkeypatch.setattr(atualizar, "porta_ocupada", lambda: False)
    monkeypatch.setattr(atualizar, "abrir_crm", lambda: pedidos.append(1) or True)
    return pedidos


def envelhecer(arquivo, minutos):
    t = time.time() - minutos * 60
    os.utime(arquivo, (t, t))


# ---------- rodada ----------
def test_porta_fechada_religa(pasta, aberturas):
    assert vigia.rodada() is True
    assert len(aberturas) == 1
    assert "religado" in atualizar.LOG.read_text(encoding="utf-8")


def test_so_religa_depois_de_duas_conferidas_fora(pasta, aberturas, monkeypatch):
    monkeypatch.setattr(vigia, "FORA_MIN", 2)
    assert vigia.rodada() is False and not aberturas   # pode estar só subindo devagar
    assert vigia.rodada() is True and len(aberturas) == 1


def test_porta_volta_zera_a_contagem(pasta, aberturas, monkeypatch):
    monkeypatch.setattr(vigia, "FORA_MIN", 2)
    vigia.rodada()
    monkeypatch.setattr(atualizar, "porta_ocupada", lambda: True)
    vigia.rodada()
    monkeypatch.setattr(atualizar, "porta_ocupada", lambda: False)
    assert vigia.rodada() is False and not aberturas


def test_nao_religou_avisa_no_log(pasta, aberturas, monkeypatch):
    monkeypatch.setattr(atualizar, "abrir_crm", lambda: False)
    assert vigia.rodada() is True
    assert "não religou" in atualizar.LOG.read_text(encoding="utf-8")


def test_porta_aberta_nao_faz_nada(pasta, aberturas, monkeypatch):
    monkeypatch.setattr(atualizar, "porta_ocupada", lambda: True)
    assert vigia.rodada() is False and not aberturas


def test_encerrar_pelo_botao_nao_religa(pasta, aberturas):
    vigia.DESLIGADO.write_text("x")
    assert vigia.rodada() is False and not aberturas


def test_atualizando_agora_nao_religa(pasta, aberturas):
    vigia.ATUALIZANDO.write_text("x")
    assert vigia.rodada() is False and not aberturas


def test_marca_de_atualizacao_velha_e_ignorada(pasta, aberturas):
    vigia.ATUALIZANDO.write_text("x")
    envelhecer(vigia.ATUALIZANDO, 30)
    assert vigia.rodada() is True and len(aberturas) == 1


def test_erro_na_rodada_nao_derruba_o_vigia(pasta, monkeypatch):
    def quebra():
        raise RuntimeError("bat sumiu")
    monkeypatch.setattr(atualizar, "porta_ocupada", lambda: False)
    monkeypatch.setattr(atualizar, "abrir_crm", quebra)
    assert vigia.rodada() is False
    assert "bat sumiu" in atualizar.LOG.read_text(encoding="utf-8")


# ---------- um vigia só ----------
def test_trava_so_um_vigia(pasta):
    assert vigia.assumir_trava() is True
    assert vigia.TRAVA.read_text() == str(os.getpid())
    assert vigia.assumir_trava() is False   # o PID gravado (este processo) está vivo


def test_trava_de_processo_morto_e_lixo_sao_ignoradas(pasta):
    vigia.TRAVA.write_text("999999999")
    assert vigia.assumir_trava() is True
    vigia.TRAVA.write_text("lixo")
    assert vigia.assumir_trava() is True and vigia.TRAVA.read_text() == str(os.getpid())


def test_processo_vivo():
    assert vigia.processo_vivo(os.getpid()) and not vigia.processo_vivo(0)


# ---------- CRM abre sem internet ----------
@pytest.fixture
def nuvem_ligada(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(db, "backup_diario", lambda: None)
    monkeypatch.setattr(atualizar, "iniciar", lambda: None)
    monkeypatch.setattr(db.nuvem, "ativo", lambda: True)
    monkeypatch.setattr(db.nuvem, "sincronizar", lambda caminho: False)
    monkeypatch.setattr(db.nuvem, "iniciar_sync_periodico", lambda caminho: None)
    monkeypatch.setitem(db.nuvem.status, "erro", None)

    def sem_internet(caminho=None):
        raise sqlite3.OperationalError("sem internet")
    monkeypatch.setattr(db, "iniciar_banco", sem_internet)


def test_abre_com_a_replica_local_se_a_nuvem_estiver_fora(nuvem_ligada, capsys):
    with TestClient(main.app, base_url="http://localhost"):   # com "with": roda o lifespan
        pass
    assert "sem internet" in db.nuvem.status["erro"]
    assert "AVISO" in capsys.readouterr().out


def test_sem_nuvem_o_erro_do_banco_continua_derrubando(nuvem_ligada, monkeypatch):
    monkeypatch.setattr(db.nuvem, "ativo", lambda: False)
    with pytest.raises(sqlite3.OperationalError):
        with TestClient(main.app, base_url="http://localhost"):
            pass


# ---------- botão Encerrar e atualização ----------
def test_encerrar_marca_desligado(pasta, tmp_path, monkeypatch):
    from app import acesso
    pedidos = []
    monkeypatch.setattr(main.threading, "Timer", lambda *a: type("T", (), {"start": lambda s: pedidos.append(a)})())
    monkeypatch.setattr(acesso, "LIGADO", False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    assert not vigia.DESLIGADO.exists()
    r = TestClient(main.app, base_url="http://localhost").post("/encerrar", headers={"origin": "http://localhost"})
    assert r.status_code == 200 and vigia.DESLIGADO.exists() and len(pedidos) == 1


def test_reinicio_da_atualizacao_nao_marca_desligado(pasta, monkeypatch):
    monkeypatch.setattr(atualizar.subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr(atualizar.threading, "Timer", lambda *a: type("T", (), {"start": lambda s: None})())
    atualizar.reiniciar("abc")
    assert not vigia.DESLIGADO.exists()


def test_ajudante_marca_e_limpa_atualizando(pasta, monkeypatch):
    vistos = []
    monkeypatch.setattr(atualizar, "porta_ocupada", lambda: False)
    monkeypatch.setattr(atualizar, "abrir_crm", lambda: vistos.append(atualizar.ATUALIZANDO.exists()) or True)
    atualizar.ajudante("abc")
    assert vistos == [True] and not atualizar.ATUALIZANDO.exists()


def test_ajudante_limpa_atualizando_mesmo_com_erro(pasta, monkeypatch):
    def quebra():
        raise RuntimeError("bat travou")
    monkeypatch.setattr(atualizar, "porta_ocupada", lambda: False)
    monkeypatch.setattr(atualizar, "abrir_crm", quebra)
    with pytest.raises(RuntimeError):
        atualizar.ajudante("abc")
    assert not atualizar.ATUALIZANDO.exists()
