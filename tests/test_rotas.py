"""Teste de fumaça: todas as telas abrem (200) num banco temporário. Rede de segurança para mudanças nos templates."""
import pytest
from fastapi.testclient import TestClient

from app import db, main

TELAS = ["/", "/clientes", "/clientes/novo", "/leads", "/grade", "/agenda", "/simulador", "/explorador",
         "/campanhas", "/rotina", "/configuracoes", "/dados", "/financeiro", "/financeiro/painel", "/financeiro/mensalidades"]


@pytest.fixture
def cliente_http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")  # nunca tocar nos backups reais
    db.iniciar_banco()
    con = db.conectar()
    with con:
        cid = con.execute("INSERT INTO clientes (nome) VALUES ('Aluno Teste')").lastrowid
    con.close()
    # sem "with": o lifespan (backup diário) não roda; localhost: no PC, outro endereço passa pela portaria
    return TestClient(main.app, base_url="http://localhost"), cid


@pytest.mark.parametrize("url", TELAS)
def test_tela_abre(cliente_http, url):
    http, _ = cliente_http
    assert http.get(url).status_code == 200


def test_proposta_abre_sem_dados_internos(cliente_http):
    http, cid = cliente_http
    con = db.conectar()
    with con:
        pid = con.execute("""INSERT INTO propostas (cliente_id, tipo_servico, qtd_aulas, local, forma_pagamento, preco_total, preco_pessoa,
                             lucro, margem) VALUES (?, 'Pacote', 10, 'CIA', 'PIX', 900, 900, 400, 0.4)""", (cid,)).lastrowid
    con.close()
    r = http.get(f"/propostas/{pid}")
    assert r.status_code == 200 and "Aluno Teste" in r.text
    assert "Lucro" not in r.text and "Margem" not in r.text
    assert http.get("/propostas/999", follow_redirects=False).status_code in (302, 303)


def test_ficha_do_cliente_abre(cliente_http):
    http, cid = cliente_http
    r = http.get(f"/clientes/{cid}")
    assert r.status_code == 200 and "Aluno Teste" in r.text


def test_financeiro_lancamento_baixa_e_recorrencia(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today()
    base = {"escopo": "PJ", "volta": f"mes={hoje:%Y-%m}&escopo=todos"}
    # lançamento pendente (ontem) -> dar baixa -> pago
    http.post("/financeiro/lancamento", data={**base, "tipo": "saida", "data": (hoje - dt.timedelta(days=1)).isoformat(),
                                              "valor": "1.234,50", "categoria": "Outros", "descricao": "Conta de teste"}, follow_redirects=False)
    con = db.conectar()
    lid, valor, pago = con.execute("SELECT id, valor, pago_em FROM lancamentos").fetchone()
    assert valor == 1234.5 and pago is None
    http.post(f"/financeiro/lancamento/{lid}/baixa", data=base, follow_redirects=False)
    assert con.execute("SELECT pago_em FROM lancamentos").fetchone()[0] == hoje.isoformat()
    assert 'tag verde">pago' in http.get("/financeiro").text
    # valor zero é recusado
    r = http.post("/financeiro/lancamento", data={**base, "tipo": "saida", "data": hoje.isoformat(), "valor": "0", "categoria": "Outros"},
                  follow_redirects=False)
    assert "erro=" in r.headers["location"] and con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 1
    # recorrência: pagar duas vezes não duplica
    http.post("/financeiro/recorrencia", data={**base, "descricao": "Aluguel", "categoria": "Outros", "valor": "500", "dia_vencimento": "5",
                                               "fixo": "1", "inicio": f"{hoje:%Y-%m}"}, follow_redirects=False)
    rid = con.execute("SELECT id FROM recorrencias").fetchone()[0]
    pagar = {**base, "rid": rid, "competencia": f"{hoje:%Y-%m}", "valor": "520,00", "pago_em": hoje.isoformat()}
    http.post("/financeiro/recorrencia/baixa", data=pagar, follow_redirects=False)
    r = http.post("/financeiro/recorrencia/baixa", data=pagar, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert con.execute("SELECT COUNT(*) FROM lancamentos WHERE recorrencia_id=?", (rid,)).fetchone()[0] == 1
    con.close()


def test_registrar_pagamento_mensalidade(cliente_http):
    import datetime as dt
    http, cid = cliente_http
    hoje = dt.date.today()
    mes = f"{hoje:%Y-%m}"
    con = db.conectar()
    with con:
        con.execute("UPDATE clientes SET valor=500, status='ativo' WHERE id=?", (cid,))
    r = http.post("/financeiro/lancamento", data={"escopo": "PJ", "tipo": "entrada", "data": hoje.isoformat(), "pago_em": hoje.isoformat(),
                  "valor": "500,00", "categoria": "Outros", "descricao": "Mensalidade", "cliente_id": cid,
                  "volta": f"/financeiro/mensalidades?mes={mes}"}, follow_redirects=False)
    assert r.headers["location"].startswith(f"/financeiro/mensalidades?mes={mes}")
    assert 'tag verde">recebido' in http.get(f"/financeiro/mensalidades?mes={mes}").text
    assert "Mensalidade" in http.get(f"/clientes/{cid}").text
    con.close()


@pytest.mark.parametrize("valor,esperado", [("1.500", 1500), ("1.500,50", 1500.5), ("10.5", 10.5), ("1.234.567", 1234567)])
def test_num_br_milhar_sem_centavos(valor, esperado):
    assert main._num_br(valor) == esperado


def test_financeiro_entradas_invalidas_nao_gravam_nem_quebram(cliente_http):
    http, _ = cliente_http
    assert http.get("/financeiro?mes=2026-13").status_code == 200
    base = {"escopo": "PJ", "tipo": "saida", "data": "2026-09-01", "categoria": "Outros", "volta": "mes=2026-09"}
    for ruim in ({"valor": "nan"}, {"valor": "inf"}, {"valor": "1e400"}, {"valor": "10", "cliente_id": "999"}, {"valor": "10", "id": "abc"}):
        r = http.post("/financeiro/lancamento", data={**base, **ruim}, follow_redirects=False)
        assert r.status_code == 303 and "erro=" in r.headers["location"], ruim
    r = http.post("/financeiro/recorrencia", data={"escopo": "PJ", "descricao": "X", "categoria": "Outros", "valor": "5",
                                                   "dia_vencimento": "5", "inicio": "2026-13", "volta": "mes=2026-09"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    con = db.conectar()
    assert con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM recorrencias").fetchone()[0] == 0
    con.close()


def test_restaurar_backup_antigo_recria_tabelas_novas(cliente_http):
    import sqlite3
    http, _ = cliente_http
    antigo = db.pasta_backup() / "crm-antigo.db"
    con = sqlite3.connect(antigo)   # banco anterior à Rodada 2: sem lancamentos/recorrencias
    sqlite3.connect(db.DB_PATH).backup(con)   # API do sqlite3: vale também com o banco do Turso
    con.execute("DROP TABLE lancamentos")
    con.execute("DROP TABLE recorrencias")
    con.commit()
    con.close()
    db.restaurar_backup("crm-antigo.db")
    assert http.get("/dados").status_code == 200
