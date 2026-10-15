"""Atualização automática no PC: confere a main no GitHub, avança só sem conflito, reinicia sem ninguém usando
e volta para a versão anterior se a nova não abrir. Aqui o "GitHub" é um repositório git numa pasta temporária."""
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app import atualizar, db, main


def sh(pasta, *args):
    return subprocess.run(["git", "-c", "user.name=Teste", "-c", "user.email=t@t", *args], cwd=pasta,
                          capture_output=True, text=True, check=True).stdout.strip()


def commit(pasta, arquivo, texto):
    (pasta / arquivo).write_text(texto)
    sh(pasta, "add", arquivo)
    sh(pasta, "commit", "-q", "-m", f"{arquivo}: {texto}")
    return sh(pasta, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """origem (o GitHub), pc (a pasta do CRM no PC) e dev (onde sai a versão nova)."""
    origem, pc, dev = tmp_path / "origem.git", tmp_path / "pc", tmp_path / "dev"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origem)], check=True)
    subprocess.run(["git", "clone", "-q", str(origem), str(dev)], check=True)
    sh(dev, "symbolic-ref", "HEAD", "refs/heads/main")
    commit(dev, "app.txt", "v1")
    sh(dev, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", str(origem), str(pc)], check=True)
    monkeypatch.setattr(atualizar, "PASTA", pc)
    monkeypatch.setattr(atualizar, "DATA", pc / "data")
    monkeypatch.setattr(atualizar, "RECUSADA", pc / "data" / "atualizacao-recusada.txt")
    monkeypatch.setattr(atualizar, "LOG", pc / "data" / "atualizacao.log")
    monkeypatch.setattr(atualizar, "ATUALIZANDO", pc / "data" / "atualizando.txt")
    monkeypatch.setitem(atualizar.status, "erro", None)
    reinicios = []
    monkeypatch.setattr(atualizar, "reiniciar", reinicios.append)
    return pc, dev, reinicios


def publicar(dev, texto):
    novo = commit(dev, "app.txt", texto)
    sh(dev, "push", "-q", "origin", "main")
    return novo


def parado(monkeypatch, minutos):
    monkeypatch.setattr(atualizar, "ultimo_uso", time.monotonic() - minutos * 60)


def test_em_dia_nao_faz_nada(repos, monkeypatch):
    pc, _, reinicios = repos
    parado(monkeypatch, 60)
    assert atualizar.rodada() == atualizar.INTERVALO
    assert not reinicios and atualizar.status["versao"] == sh(pc, "rev-parse", "HEAD")[:7]


def test_versao_nova_atualiza_e_reinicia_sem_ninguem_usando(repos, monkeypatch):
    pc, dev, reinicios = repos
    antigo = sh(pc, "rev-parse", "HEAD")
    novo = publicar(dev, "v2")
    parado(monkeypatch, 10)
    assert atualizar.rodada() is None
    assert sh(pc, "rev-parse", "HEAD") == novo and (pc / "app.txt").read_text() == "v2"
    assert reinicios == [antigo]


def test_versao_nova_espera_quem_esta_usando(repos, monkeypatch):
    pc, dev, reinicios = repos
    antigo = sh(pc, "rev-parse", "HEAD")
    publicar(dev, "v2")
    atualizar.registrar_uso()
    assert atualizar.rodada() == 60
    assert atualizar.status["pendente"] and not reinicios
    assert sh(pc, "rev-parse", "HEAD") == antigo   # nem baixou: arquivo novo com o CRM velho rodando quebraria a tela


def test_usar_o_crm_conta_como_uso(repos, monkeypatch):
    parado(monkeypatch, 60)
    TestClient(main.app, base_url="http://localhost").get("/saude")
    assert time.monotonic() - atualizar.ultimo_uso < 5


def test_mudanca_propria_no_pc_nao_e_atropelada(repos, monkeypatch):
    pc, dev, reinicios = repos
    commit(pc, "meu.txt", "coisa do PC")
    publicar(dev, "v2")
    parado(monkeypatch, 60)
    assert atualizar.rodada() == atualizar.INTERVALO
    assert "mudanças próprias" in atualizar.status["erro"] and not reinicios
    assert "mudanças próprias" in (pc / "data" / "atualizacao.log").read_text(encoding="utf-8")


def test_fora_da_main_nao_atualiza(repos, monkeypatch):
    pc, dev, reinicios = repos
    sh(pc, "checkout", "-q", "-b", "teste")
    publicar(dev, "v2")
    parado(monkeypatch, 60)
    atualizar.rodada()
    assert "ramo main" in atualizar.status["erro"] and not reinicios


def test_sem_github_tenta_depois(repos, monkeypatch):
    pc, _, reinicios = repos
    sh(pc, "remote", "set-url", "origin", str(pc.parent / "nao-existe.git"))
    assert atualizar.rodada() == atualizar.INTERVALO
    assert atualizar.status["erro"] and not reinicios


def test_versao_que_nao_abriu_volta_e_nao_tenta_de_novo(repos, monkeypatch):
    pc, dev, reinicios = repos
    antigo = sh(pc, "rev-parse", "HEAD")
    novo = publicar(dev, "v2-quebrada")
    sh(pc, "pull", "-q", "--ff-only", "origin", "main")   # o que a rodada faz antes de reiniciar
    aberturas = iter([False, True])   # a nova não abre; a anterior abre
    monkeypatch.setattr(atualizar, "porta_ocupada", lambda: False)
    monkeypatch.setattr(atualizar, "abrir_crm", lambda: next(aberturas))
    atualizar.ajudante(antigo)
    assert sh(pc, "rev-parse", "HEAD") == antigo and (pc / "app.txt").read_text() == "v1"
    assert atualizar.RECUSADA.read_text(encoding="utf-8") == novo
    parado(monkeypatch, 60)
    atualizar.rodada()
    assert sh(pc, "rev-parse", "HEAD") == antigo and not reinicios and "não abriu" in atualizar.status["erro"]
    publicar(dev, "v3-consertada")   # a próxima versão volta a ser tentada
    assert atualizar.rodada() is None and (pc / "app.txt").read_text() == "v3-consertada"


def test_versao_nova_que_abre_fica(repos, monkeypatch):
    pc, dev, _ = repos
    antigo = sh(pc, "rev-parse", "HEAD")
    novo = publicar(dev, "v2")
    sh(pc, "pull", "-q", "--ff-only", "origin", "main")
    monkeypatch.setattr(atualizar, "porta_ocupada", lambda: False)
    monkeypatch.setattr(atualizar, "abrir_crm", lambda: True)
    atualizar.ajudante(antigo)
    assert sh(pc, "rev-parse", "HEAD") == novo and not atualizar.RECUSADA.exists()


@pytest.mark.parametrize("windows, env, ligado", [
    (False, {}, False),                            # aqui (Linux) e nos testes
    (True, {"CRM_NUVEM": "1"}, False),             # Render
    (True, {"CRM_AUTOATUALIZAR": "0"}, False),     # desligado no .env
    (True, {}, True),
])
def test_quando_liga(repos, monkeypatch, windows, env, ligado):
    monkeypatch.setattr(atualizar, "WINDOWS", windows)
    monkeypatch.delenv("CRM_NUVEM", raising=False)
    monkeypatch.delenv("CRM_AUTOATUALIZAR", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert (atualizar.motivo_desligado() == "") is ligado


def test_dados_mostra_a_situacao(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    http = TestClient(main.app, base_url="http://localhost")
    monkeypatch.setattr(atualizar, "status", {**atualizar.status, "mostrar": False})
    assert "Atualização automática" not in http.get("/dados").text   # Render e fora do Windows: nada
    monkeypatch.setattr(atualizar, "status", {**atualizar.status, "mostrar": True, "ligado": True, "erro": None, "pendente": False})
    assert "Atualização automática ligada" in http.get("/dados").text
    monkeypatch.setattr(atualizar, "status", {**atualizar.status, "mostrar": True, "ligado": True, "erro": "sem internet"})
    assert "com problema: sem internet" in http.get("/dados").text


def test_arquivo_mudado_no_pc_explica(repos, monkeypatch):
    pc, dev, reinicios = repos
    publicar(dev, "v2")
    (pc / "app.txt").write_text("mexido no PC")   # mudança sem commit no mesmo arquivo da versão nova
    parado(monkeypatch, 60)
    assert atualizar.rodada() == atualizar.INTERVALO
    assert "rode git status" in atualizar.status["erro"] and not reinicios
    assert (pc / "app.txt").read_text() == "mexido no PC"
