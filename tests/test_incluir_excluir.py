"""Checkpoints (Campanhas) e tarefas do checklist da Rotina: incluir, excluir (lixeira) e restaurar."""
import datetime as dt
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db, main


@pytest.fixture
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    return TestClient(main.app, base_url="http://localhost")


def consulta(sql, *args):
    con = db.conectar()
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def alertas():
    con = db.conectar()
    try:
        return [a["texto"] for a in main.alertas(con)]
    finally:
        con.close()


# ---------- checkpoints ----------
def test_incluir_checkpoint_com_e_sem_canal(http):
    prazo = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    r = http.post("/campanhas/checkpoint", data={"pergunta": "Instagram trouxe cliente?", "canal": "Instagram orgânico", "prazo": prazo},
                  follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    http.post("/campanhas/checkpoint", data={"pergunta": "Panfleto funcionou?", "prazo": prazo})
    pagina = http.get("/campanhas").text
    assert "Instagram trouxe cliente?" in pagina and "0 cliente(s) de Instagram orgânico" in pagina
    assert "Panfleto funcionou?" in pagina and ">pendente</option>" in pagina   # sem canal: só na mão
    assert any("Panfleto funcionou?" in a for a in alertas())


def test_checkpoint_com_prazo_invalido_nao_entra(http):
    antes = len(consulta("SELECT * FROM campanha_checkpoints"))
    r = http.post("/campanhas/checkpoint", data={"pergunta": "X?", "prazo": "31/10/2026"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert len(consulta("SELECT * FROM campanha_checkpoints")) == antes


def test_excluir_e_restaurar_checkpoint(http):
    cid, pergunta = consulta("SELECT id, pergunta FROM campanha_checkpoints ORDER BY id")[0]
    http.post(f"/campanhas/checkpoint/{cid}/excluir")
    assert pergunta not in http.get("/campanhas").text
    assert not any(pergunta in a for a in alertas())
    assert pergunta in http.get("/dados").text   # na lixeira
    http.post("/lixeira/restaurar", data={"tabela": "campanha_checkpoints", "rid": cid})
    assert pergunta in http.get("/campanhas").text


# ---------- rotina ----------
def test_tarefas_iniciais_no_checklist(http):
    pagina = http.get("/rotina").text
    for texto in ["Segunda: atualizar a grade", "Quarta: lançar os leads por canal", "Sexta: revisar as propostas", "Último dia do mês"]:
        assert texto in pagina


def test_incluir_tarefa_com_dia_avisa_no_dia(http):
    hoje = dt.date.today().isoweekday()
    http.post("/rotina/tarefa", data={"texto": "Postar no Instagram", "dia": hoje})
    http.post("/rotina/tarefa", data={"texto": "Ligar para ex-alunos", "dia": 0})
    pagina = http.get("/rotina").text
    assert f"{main.DIAS[hoje]}: Postar no Instagram" in pagina and "Ligar para ex-alunos" in pagina
    assert f"Rotina de hoje: {main.DIAS[hoje]}: Postar no Instagram" in alertas()
    assert not any("Ligar para ex-alunos" in a for a in alertas())   # sem dia: sem aviso
    chave = consulta("SELECT chave FROM rotina_tarefas WHERE texto='Postar no Instagram'")[0][0]
    http.post(f"/rotina/{chave}/toggle")
    assert not any("Postar no Instagram" in a for a in alertas())   # feito: some o aviso


def test_excluir_e_restaurar_tarefa(http):
    http.get("/rotina")   # cria a semana
    tid, chave = consulta("SELECT id, chave FROM rotina_tarefas WHERE chave='segunda_grade'")[0]
    http.post(f"/rotina/tarefa/{tid}/excluir")
    pagina = http.get("/rotina").text
    assert "atualizar a grade" not in pagina
    assert not consulta("SELECT 1 FROM rotina_itens WHERE semana=? AND item=?", main.semana_atual(), chave)
    http.post("/lixeira/restaurar", data={"tabela": "rotina_tarefas", "rid": tid})
    assert "Segunda: atualizar a grade" in http.get("/rotina").text


def test_tarefa_vazia_nao_entra(http):
    antes = len(consulta("SELECT * FROM rotina_tarefas"))
    r = http.post("/rotina/tarefa", data={"texto": "   ", "dia": 1}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert len(consulta("SELECT * FROM rotina_tarefas")) == antes


def test_fechar_mes_sem_a_tarefa_fim_mes(http):
    tid = consulta("SELECT id FROM rotina_tarefas WHERE chave='fim_mes'")[0][0]
    http.post(f"/rotina/tarefa/{tid}/excluir")
    http.post("/painel/fechar-mes")
    assert not consulta("SELECT 1 FROM rotina_itens WHERE item='fim_mes'")
    assert "Último dia do mês" not in http.get("/rotina").text


# ---------- banco ----------
def test_tarefas_excluidas_nao_voltam_ao_reabrir(http):
    con = db.conectar()
    with con:
        con.execute("UPDATE rotina_tarefas SET excluido_em=datetime('now','localtime')")
    con.close()
    db.iniciar_banco()
    db.iniciar_banco()
    assert len(consulta("SELECT * FROM rotina_tarefas")) == len(db.ROTINA_INICIAL) + 1   # + a tarefa "saldos" do Saldo livre
    assert not consulta("SELECT * FROM rotina_tarefas WHERE excluido_em IS NULL")


def test_banco_antigo_ganha_coluna_e_tarefas(tmp_path, monkeypatch):
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.execute("""CREATE TABLE campanha_checkpoints (id INTEGER PRIMARY KEY, pergunta TEXT NOT NULL, canal TEXT NOT NULL,
                   prazo TEXT NOT NULL, resposta TEXT DEFAULT 'pendente')""")
    con.execute("INSERT INTO campanha_checkpoints (pergunta, canal, prazo) VALUES ('Antigo?', 'Stadami', '2026-10-31')")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    try:
        assert [tuple(r) for r in con.execute("SELECT pergunta, excluido_em FROM campanha_checkpoints")] == [("Antigo?", None)]
        assert [r[0] for r in con.execute("SELECT chave FROM rotina_tarefas ORDER BY ordem")] == [c for c, _, _ in db.ROTINA_INICIAL] + ["saldos"]
    finally:
        con.close()
