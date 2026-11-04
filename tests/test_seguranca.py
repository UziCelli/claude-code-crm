"""Revisão de segurança: destino de volta só dentro do CRM, número de tela finito, id de proposta inválido e consulta só leitura."""
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import assistente, db, main


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    c = db.conectar()
    with c:
        c.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, preco_base,
                     custo_operacional, mao_obra, custo_total, sessoes_mes) VALUES ('Pacote de Aulas', 'CIA', 'PIX', 8, 0, 1100, 900, 415.5, 900, 8)""")
    yield c
    c.close()


@pytest.fixture
def http(con):
    return TestClient(main.app, base_url="http://localhost")


@pytest.mark.parametrize("ruim", ["/\\mal.com", "//mal.com", "https://mal.com", "javascript:alert(1)"])
def test_novo_local_nao_volta_para_outro_site(http, ruim):
    r = http.post("/locais/novo", data={"nome": "Academia X", "voltar": ruim}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/grade")


def test_novo_local_volta_para_a_tela_do_crm(http):
    r = http.post("/locais/novo", data={"nome": "Academia Y", "voltar": "/agenda?semana=2026-11-02"}, follow_redirects=False)
    assert r.headers["location"].startswith("/agenda?semana=2026-11-02")


@pytest.mark.parametrize("ruim", ["inf", "-inf", "nan", "1e400"])
def test_num_br_recusa_numero_infinito(ruim):
    with pytest.raises(ValueError):
        main._num_br(ruim)


def test_novo_local_com_infinito_avisa_sem_erro_500(http, con):
    r = http.post("/locais/novo", data={"nome": "Academia Z", "max_pessoas": "inf", "taxa_aula": "inf"}, follow_redirects=False)
    assert r.status_code == 303 and "Confira os números" in unquote(r.headers["location"])
    assert not con.execute("SELECT 1 FROM locais_custos WHERE local='Academia Z'").fetchone()


def test_proposta_com_cliente_invalido_avisa_sem_erro_500(http, con):
    r = http.post("/propostas", data={"plano": "Pacote de Aulas|8|0", "forma": "PIX", "h": "1-7-CIA", "confirmar": 1,
                                      "cliente_id": "abc"}, follow_redirects=False)
    assert r.status_code == 303 and "inválido" in unquote(r.headers["location"])
    assert con.execute("SELECT COUNT(*) FROM propostas").fetchone()[0] == 0


def test_consulta_do_assistente_e_so_leitura(con):
    r = assistente._consultar_banco(con, {"sql": "SELECT COUNT(*) AS n FROM precos_base"})
    assert r["linhas"] == [[1]]
    con.execute("PRAGMA query_only=ON")   # a trava que a consulta liga: gravação é recusada
    with pytest.raises(Exception):
        con.execute("DELETE FROM precos_base")
    con.execute("PRAGMA query_only=OFF")
    with pytest.raises(assistente.ErroFerramenta):
        assistente._consultar_banco(con, {"sql": "SELECT * FROM tabela_que_nao_existe"})
    with con:   # depois da consulta (mesmo com erro) o banco volta a gravar
        con.execute("DELETE FROM precos_base")
    assert con.execute("SELECT COUNT(*) FROM precos_base").fetchone()[0] == 0
