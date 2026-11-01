"""Indicações: o presente (brinde, nunca desconto) de quem indicou, que aparece quando o indicado faz o 1º pagamento."""
import datetime as dt
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db, indicacoes, main

HOJE = dt.date.today().isoformat()


@pytest.fixture
def con_temp(tmp_path, monkeypatch):
    db_path = tmp_path / "crm.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(db_path)
    con = db.conectar(db_path)
    yield con
    con.close()


@pytest.fixture
def http(con_temp):
    # sem "with": o lifespan não roda; o app abre o mesmo banco temporário do con_temp
    return TestClient(main.app, base_url="http://localhost")


def aluno(con, nome, indicado_por=None, status="ativo"):
    with con:
        return con.execute("INSERT INTO clientes (nome, telefone, status, valor, indicado_por) VALUES (?, '11999990000', ?, 400, ?)",
                           (nome, status, indicado_por)).lastrowid


def pagar(con, cid, valor=400, categoria="Mensalidade (Aulas Presenciais)", pago_em=HOJE, **extra):
    with con:
        return con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id)
                              VALUES ('PJ','entrada',?,?,?,?,?)""", (HOJE, pago_em, valor, categoria, cid)).lastrowid


def alertas_presente(con):
    return [a for a in main.alertas(con) if a["texto"].startswith("Dar o presente")]


def dar(http, cid, iid, **form):
    return http.post(f"/clientes/{cid}/indicacao/{iid}/presente", data={"o_que": "Camiseta", **form}, follow_redirects=False)


# ---------- banco antigo ----------
def test_colunas_criadas_em_banco_antigo(tmp_path):
    """Banco de antes das indicações ganha as três colunas ao iniciar, sem perder os dados."""
    antigo = db.SCHEMA.read_text(encoding="utf-8")
    for linha in ("    indicado_por INTEGER REFERENCES clientes(id)   -- quem indicou este aluno (ganha um presente no 1º pagamento; nunca desconto)\n",
                  "    indicado_por INTEGER REFERENCES clientes(id)   -- quem indicou este lead; passa para o aluno quando ele fecha\n",
                  "    indicado_id INTEGER              -- brinde: o aluno indicado que rendeu o presente (1 presente por indicado)\n"):
        assert linha in antigo
        antigo = antigo.replace(linha, "")
    antigo = antigo.replace("renovacao_em TEXT,  ", "renovacao_em TEXT   ").replace("usado_lancamento_id INTEGER,  ", "usado_lancamento_id INTEGER   ")
    antigo = re.sub(r"excluido_em TEXT,\n\);\n\nCREATE TABLE IF NOT EXISTS lead_etapas_log", "excluido_em TEXT\n);\n\nCREATE TABLE IF NOT EXISTS lead_etapas_log", antigo)
    caminho = tmp_path / "antigo.db"
    raw = sqlite3.connect(caminho)
    raw.executescript(antigo)
    raw.execute("INSERT INTO clientes (nome) VALUES ('Ana')")
    raw.commit()
    for tabela, coluna in (("clientes", "indicado_por"), ("leads", "indicado_por"), ("cliente_eventos", "indicado_id")):
        assert coluna not in {r[1] for r in raw.execute(f"PRAGMA table_info({tabela})")}
    raw.close()
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    for tabela, coluna in (("clientes", "indicado_por"), ("leads", "indicado_por"), ("cliente_eventos", "indicado_id")):
        assert coluna in {r[1] for r in con.execute(f"PRAGMA table_info({tabela})")}
    assert con.execute("SELECT nome FROM clientes").fetchone()[0] == "Ana"
    con.close()


# ---------- lead e ficha ----------
def test_lead_criado_com_indicacao_vira_canal_indicacao_e_passa_para_o_aluno(con_temp, http):
    ana = aluno(con_temp, "Ana")
    r = http.post("/leads", data={"nome": "Bruno", "canal_origem": "Instagram orgânico", "indicado_por": str(ana)}, follow_redirects=False)
    assert r.status_code == 303
    lead = con_temp.execute("SELECT * FROM leads WHERE nome='Bruno'").fetchone()
    assert lead["indicado_por"] == ana and lead["canal_origem"] == "Indicação"
    http.post(f"/leads/{lead['id']}/etapa", data={"etapa": "cliente"}, follow_redirects=False)
    novo = con_temp.execute("SELECT * FROM clientes WHERE nome='Bruno'").fetchone()
    assert novo["indicado_por"] == ana and novo["canal_origem"] == "Indicação"


def test_lead_editado_ganha_indicador_e_troca_o_canal(con_temp, http):
    ana = aluno(con_temp, "Ana")
    http.post("/leads", data={"nome": "Caio", "canal_origem": "Google"}, follow_redirects=False)
    lid = con_temp.execute("SELECT id FROM leads").fetchone()[0]
    http.post(f"/leads/{lid}", data={"nome": "Caio", "canal_origem": "Google", "indicado_por": str(ana)}, follow_redirects=False)
    l = con_temp.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
    assert l["indicado_por"] == ana and l["canal_origem"] == "Indicação"


def test_tela_de_leads_tem_o_campo_indicado_por(con_temp, http):
    ana = aluno(con_temp, "Ana")
    http.post("/leads", data={"nome": "Caio", "canal_origem": "Google", "indicado_por": str(ana)}, follow_redirects=False)
    html = http.get("/leads").text
    assert 'name="indicado_por"' in html and "Indicado por Ana" in html and f'data-indicado_por="{ana}"' in html


def test_ficha_salva_indicado_por_e_marca_o_canal(con_temp, http):
    ana = aluno(con_temp, "Ana", status="inativo")
    bruno = aluno(con_temp, "Bruno")
    r = http.post(f"/clientes/{bruno}", data={"nome": "Bruno", "canal_origem": "Google", "indicado_por": str(ana), "pessoas": "1"}, follow_redirects=False)
    assert r.status_code == 303
    c = con_temp.execute("SELECT * FROM clientes WHERE id=?", (bruno,)).fetchone()
    assert c["indicado_por"] == ana and c["canal_origem"] == "Indicação"
    html = http.get(f"/clientes/{bruno}").text
    assert 'name="indicado_por"' in html and "(inativo)" in html and "Indicado por" in html and f'href="/clientes/{ana}"' in html


def test_novo_cliente_com_indicacao(con_temp, http):
    ana = aluno(con_temp, "Ana")
    assert 'name="indicado_por"' in http.get("/clientes/novo").text
    r = http.post("/clientes", data={"nome": "Dani", "indicado_por": str(ana)}, follow_redirects=False)
    assert r.status_code == 303
    d = con_temp.execute("SELECT * FROM clientes WHERE nome='Dani'").fetchone()
    assert d["indicado_por"] == ana and d["canal_origem"] == "Indicação"


def test_ninguem_indica_a_si_mesmo(con_temp, http):
    ana = aluno(con_temp, "Ana")
    r = http.post(f"/clientes/{ana}", data={"nome": "Ana", "indicado_por": str(ana), "pessoas": "1"}, follow_redirects=False)
    assert r.status_code == 303 and "erro=" in r.headers["location"]
    assert con_temp.execute("SELECT indicado_por FROM clientes WHERE id=?", (ana,)).fetchone()[0] is None
    # lead já convertido: o aluno em que ele virou também não se indica
    http.post("/leads", data={"nome": "Eva", "canal_origem": "Google"}, follow_redirects=False)
    lid = con_temp.execute("SELECT id FROM leads").fetchone()[0]
    http.post(f"/leads/{lid}/etapa", data={"etapa": "cliente"}, follow_redirects=False)
    eva = con_temp.execute("SELECT cliente_id FROM leads WHERE id=?", (lid,)).fetchone()[0]
    r = http.post(f"/leads/{lid}", data={"nome": "Eva", "canal_origem": "Google", "indicado_por": str(eva)}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert con_temp.execute("SELECT indicado_por FROM leads WHERE id=?", (lid,)).fetchone()[0] is None


def test_indicador_inexistente_ou_invalido_e_recusado(con_temp, http):
    r = http.post("/leads", data={"nome": "Fê", "canal_origem": "Google", "indicado_por": "9999"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    r = http.post("/leads", data={"nome": "Fê", "canal_origem": "Google", "indicado_por": "abc"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert con_temp.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0


# ---------- pendentes, aluno e alerta ----------
def test_so_aparece_depois_do_primeiro_pagamento_de_verdade(con_temp):
    ana = aluno(con_temp, "Ana")
    bruno = aluno(con_temp, "Bruno", ana)
    assert indicacoes.pendentes(con_temp) == [] and alertas_presente(con_temp) == []
    assert [r["status"] for r in indicacoes.do_aluno(con_temp, ana)] == ["aguardando"]
    pagar(con_temp, bruno, pago_em=None)   # lançado mas ainda não caiu
    pagar(con_temp, bruno, categoria="Empréstimo")   # empréstimo não é pagamento de aluno
    assert indicacoes.pendentes(con_temp) == []
    pagar(con_temp, bruno)
    [p] = indicacoes.pendentes(con_temp)
    assert (p["indicador_id"], p["indicado_id"], p["indicador"], p["indicado"]) == (ana, bruno, "Ana", "Bruno")
    [a] = alertas_presente(con_temp)
    assert a["cor"] == "azul" and a["texto"] == "Dar o presente a Ana (indicou Bruno)"
    assert [r["status"] for r in indicacoes.do_aluno(con_temp, ana)] == ["pendente"]


def test_pagamento_excluido_nao_conta(con_temp):
    ana = aluno(con_temp, "Ana")
    bruno = aluno(con_temp, "Bruno", ana)
    lid = pagar(con_temp, bruno)
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET excluido_em=datetime('now') WHERE id=?", (lid,))
    assert indicacoes.pendentes(con_temp) == []


def test_alerta_traz_o_botao_que_abre_o_dialogo(con_temp, http):
    ana = aluno(con_temp, "Ana")
    bruno = aluno(con_temp, "Bruno", ana)
    pagar(con_temp, bruno)
    [a] = alertas_presente(con_temp)
    [acao] = a["acoes"]
    assert acao["rotulo"] == "Registrar presente" and acao["dialogo"] == "dlg-presente" and acao["classe"] == "verde"
    assert acao["dados"]["acao"] == f"/clientes/{ana}/indicacao/{bruno}/presente"
    html = http.get("/").text   # o Painel mostra os alertas
    assert 'data-abrir="dlg-presente"' in html and f'data-acao="/clientes/{ana}/indicacao/{bruno}/presente"' in html
    assert html.count('<dialog id="dlg-presente">') == 1 and "O que você deu?" in html
    for sugestao in ("Avaliação física", "Camiseta", "Garrafa", "Treino extra para casa"):
        assert f'<option value="{sugestao}">' in html
    assert "Dar o presente a Ana" in http.get("/leads").text   # e o resumo de alertas do topo das outras telas


def test_presente_registrado_some_com_o_alerta_e_vira_entregue(con_temp, http):
    ana = aluno(con_temp, "Ana")
    bruno = aluno(con_temp, "Bruno", ana)
    pagar(con_temp, bruno)
    r = dar(http, ana, bruno, custo="35,90", data="2026-11-02", voltar=f"/clientes/{ana}")
    assert r.status_code == 303 and r.headers["location"].startswith(f"/clientes/{ana}") and "msg=" in r.headers["location"]
    e = con_temp.execute("SELECT * FROM cliente_eventos WHERE tipo='brinde'").fetchone()
    assert (e["cliente_id"], e["indicado_id"], e["data"], e["valor"]) == (ana, bruno, "2026-11-02", 35.9)
    assert e["descricao"] == "Presente pela indicação de Bruno: Camiseta"
    assert alertas_presente(con_temp) == [] and indicacoes.pendentes(con_temp) == []
    [i] = indicacoes.do_aluno(con_temp, ana)
    assert (i["status"], i["data"], i["o_que"]) == ("entregue", "2026-11-02", "Camiseta")


def test_um_presente_so_por_indicado(con_temp, http):
    ana = aluno(con_temp, "Ana")
    bruno = aluno(con_temp, "Bruno", ana)
    pagar(con_temp, bruno)
    assert "msg=" in dar(http, ana, bruno).headers["location"]
    r = dar(http, ana, bruno, o_que="Garrafa")
    assert r.status_code == 303 and "erro=" in r.headers["location"]
    assert con_temp.execute("SELECT COUNT(*) FROM cliente_eventos WHERE tipo='brinde'").fetchone()[0] == 1


def test_presente_recusa_sem_pagamento_sem_texto_e_indicacao_alheia(con_temp, http):
    ana = aluno(con_temp, "Ana")
    bruno = aluno(con_temp, "Bruno", ana)
    outro = aluno(con_temp, "Zé")
    assert "erro=" in dar(http, ana, bruno).headers["location"]   # Bruno ainda não pagou
    pagar(con_temp, bruno)
    assert "erro=" in dar(http, ana, bruno, o_que="  ").headers["location"]
    assert "erro=" in dar(http, outro, bruno).headers["location"]   # Zé não indicou o Bruno
    assert "erro=" in dar(http, ana, bruno, custo="abc").headers["location"]
    assert con_temp.execute("SELECT COUNT(*) FROM cliente_eventos WHERE tipo='brinde'").fetchone()[0] == 0


def test_destino_de_fora_do_crm_e_ignorado(con_temp, http):
    ana = aluno(con_temp, "Ana")
    bruno = aluno(con_temp, "Bruno", ana)
    pagar(con_temp, bruno)
    r = dar(http, ana, bruno, voltar="https://mal.exemplo/x")
    assert r.headers["location"].startswith(f"/clientes/{ana}")


def test_presente_nao_mexe_em_credito_nem_em_pagamentos(con_temp, http):
    ana = aluno(con_temp, "Ana")
    bruno = aluno(con_temp, "Bruno", ana)
    pagar(con_temp, bruno)
    antes = [tuple(r) for r in con_temp.execute("SELECT * FROM lancamentos")]
    dar(http, ana, bruno, custo="20")
    assert [tuple(r) for r in con_temp.execute("SELECT * FROM lancamentos")] == antes
    assert con_temp.execute("SELECT COUNT(*) FROM cliente_eventos WHERE tipo='credito'").fetchone()[0] == 0


def test_aluno_excluido_nao_gera_alerta(con_temp):
    ana = aluno(con_temp, "Ana")
    bruno = aluno(con_temp, "Bruno", ana)
    pagar(con_temp, bruno)
    with con_temp:
        con_temp.execute("UPDATE clientes SET excluido_em=datetime('now') WHERE id=?", (ana,))
    assert indicacoes.pendentes(con_temp) == []


# ---------- ficha ----------
def test_ficha_do_indicador_mostra_o_card_com_as_tres_situacoes(con_temp, http):
    ana = aluno(con_temp, "Ana")
    bruno = aluno(con_temp, "Bruno", ana)
    caio = aluno(con_temp, "Caio", ana)
    dani = aluno(con_temp, "Dani", ana)
    pagar(con_temp, bruno)
    pagar(con_temp, caio)
    dar(http, ana, caio, data="2026-11-02")
    html = http.get(f"/clientes/{ana}").text
    assert 'id="indicacoes"' in html
    assert "presente pendente" in html and "aguardando o 1º pagamento" in html and "presente entregue em 02/11/2026 (Camiseta)" in html
    assert html.count('data-abrir="dlg-presente"') == 2   # o botão do card + o do alerta; o do Caio e do Dani não têm botão
    assert f'data-acao="/clientes/{ana}/indicacao/{bruno}/presente"' in html
    assert f'data-acao="/clientes/{ana}/indicacao/{dani}/presente"' not in html
    assert ">presente</span>" in html   # no histórico o evento aparece como "presente", não como "brinde"


def test_ficha_sem_indicacao_nao_mostra_o_card(con_temp, http):
    ana = aluno(con_temp, "Ana")
    assert 'id="indicacoes"' not in http.get(f"/clientes/{ana}").text


def test_evento_de_presente_pode_ser_excluido_e_a_pendencia_volta(con_temp, http):
    ana = aluno(con_temp, "Ana")
    bruno = aluno(con_temp, "Bruno", ana)
    pagar(con_temp, bruno)
    dar(http, ana, bruno)
    eid = con_temp.execute("SELECT id FROM cliente_eventos WHERE tipo='brinde'").fetchone()[0]
    r = http.post(f"/agenda/evento/{eid}/excluir", data={"destino": "ficha"}, follow_redirects=False)
    assert r.headers["location"].startswith(f"/clientes/{ana}")
    assert len(alertas_presente(con_temp)) == 1
    # restaurar pela lixeira com outro presente já valendo é recusado
    dar(http, ana, bruno, o_que="Garrafa")
    r = http.post("/lixeira/restaurar", data={"tabela": "cliente_eventos", "rid": eid}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert con_temp.execute("SELECT COUNT(*) FROM cliente_eventos WHERE tipo='brinde' AND excluido_em IS NULL").fetchone()[0] == 1


def test_numero_de_consultas_nao_cresce_com_os_indicados(con_temp):
    ana = aluno(con_temp, "Ana")
    for i in range(12):
        pagar(con_temp, aluno(con_temp, f"Aluno {i}", ana))
    consultas = []

    class Contador:   # conta as consultas que passam pela conexão (a do libsql não tem set_trace_callback)
        def execute(self, sql, *args):
            consultas.append(sql)
            return con_temp.execute(sql, *args)

    assert len(indicacoes.pendentes(Contador())) == 12
    assert len(consultas) == 1
    consultas.clear()
    assert len(indicacoes.do_aluno(Contador(), ana)) == 12
    assert len(consultas) == 1
