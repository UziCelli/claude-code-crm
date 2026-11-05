"""Salário por hora automático: custos pessoais (saídas pagas da PF) ÷ horas de trabalho dos alunos ativos (regra do tempo)."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import db, financeiro, main, precos


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    c = db.conectar()
    yield c
    c.close()


def _mes(k):
    return financeiro.somar_meses(dt.date.today().strftime("%Y-%m"), k)


def gasto_pf(con, valor, k):
    with con:
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria) VALUES ('PF','saida',?,?,?, 'Mercado')",
                    (f"{_mes(k)}-10", f"{_mes(k)}-10", valor))


def aluno(con, nome, tipo="Pacote de Aulas", plano="Pacote 8 aulas", local="CIA", status="ativo"):
    with con:
        con.execute("INSERT INTO clientes (nome, valor, tipo_servico, plano, local, pessoas, forma_pagamento, status) VALUES (?,?,?,?,?,1,'PIX',?)",
                    (nome, 1000, tipo, plano, local, status))


def test_custo_pessoal_e_a_media_dos_meses_com_gasto(con):
    gasto_pf(con, 4000, -1)
    gasto_pf(con, 5000, -2)
    gasto_pf(con, 9999, 0)    # mês corrente ainda não fechou: fica fora
    gasto_pf(con, 9999, -4)   # mais de 3 meses atrás: fora
    assert financeiro.custo_pessoal_medio(con, _mes(0)) == (4500, 2)


def test_horas_de_trabalho_somam_aulas_planejamento_e_consultoria(con):
    aluno(con, "Ana")                                                          # 8 aulas + 1 h = 9 h
    aluno(con, "Bia", tipo="Consultoria Online", plano="Consultoria Online", local="Online")   # 150 min = 2,5 h
    aluno(con, "Caio", local="SmartFit")                                       # qualquer local: 9 h
    aluno(con, "Edu", tipo="Outro", plano="Pacote 8 aulas")                    # plano que o motor não conhece: só as 8 aulas
    aluno(con, "Duda", status="inativo")
    p = precos.carregar_parametros(con)
    assert main.horas_trabalho_mes(con, p) == pytest.approx(9 + 2.5 + 9 + 8)


def test_valor_da_hora_sai_dos_custos_pessoais_e_vai_para_os_precos(con):
    aluno(con, "Ana")
    aluno(con, "Bia")
    gasto_pf(con, 4500, -1)
    p = precos.carregar_parametros(con)
    sh = p["salario_hora"]
    # 18 h de hoje, mas divide pela agenda cheia (97 h): o salário não cai inteiro nos 2 alunos atuais
    assert sh["usado"] and sh["horas"] == 18 and sh["horas_base"] == 97 and sh["custo_pessoal"] == 4500
    assert p["mo"]["valor_hora"] == pytest.approx(4500 / 97, abs=0.01)
    base = precos.base_motor("Pacote de Aulas", 8, local="CIA")
    assert precos.calcular(base, p)["mao_obra"] == pytest.approx(9 * 46.39, abs=0.01)


def test_agenda_mais_cheia_que_a_meta_divide_pelas_horas_de_hoje(con):
    for n in range(12):   # 12 x 9 h = 108 h > 97 h
        aluno(con, f"A{n}")
    gasto_pf(con, 5400, -1)
    sh = precos.carregar_parametros(con)["salario_hora"]
    assert sh["horas_base"] == 108 and sh["valor_hora"] == pytest.approx(50)


def test_grupo_nao_soma_mao_de_obra_extra_com_salario_automatico(con):
    aluno(con, "Ana")
    gasto_pf(con, 4500, -1)
    p = precos.carregar_parametros(con)
    base = precos.base_motor("Pacote de Aulas", 8, local="CIA")
    assert precos.calcular(base, p, pessoas=2)["mao_obra"] == pytest.approx(precos.calcular(base, p)["mao_obra"])


def test_cobre_custos_usa_o_custo_pessoal_inteiro(con):
    aluno(con, "Ana")   # paga 1000; custos do negócio do pacote: 8 aulas x taxa da CIA (sem contas fixas cadastradas)
    gasto_pf(con, 4500, -1)
    p = precos.carregar_parametros(con)
    c = main.cobre_custos(con, p)
    negocio = 8 * p["taxa_cia"][1]
    assert c["receita"] == 1000 and c["negocio"] == pytest.approx(negocio) and c["pessoal"] == 4500
    assert c["sobra"] == pytest.approx(1000 - c["impostos"] - negocio - 4500) and not c["cobre"]


def test_tela_calculos_mostra_a_conta_e_salva_voltando_para_ela(con):
    aluno(con, "Ana")
    gasto_pf(con, 4500, -1)
    http = TestClient(main.app, base_url="http://localhost")
    t = http.get("/calculos").text
    assert "O mês cobre os seus custos?" in t and "Falta no mês" in t and "Minutos de cada aula" in t
    pid = con.execute("SELECT id FROM parametros WHERE grupo='metas' AND chave='horas_vendaveis'").fetchone()[0]
    r = http.post("/configuracoes", data={"voltar": "/calculos", f"p_{pid}": "120", f"f_{pid}": "num"}, follow_redirects=False)
    assert r.headers["location"].startswith("/calculos?msg=")
    assert precos.carregar_parametros(con)["salario_hora"]["horas_base"] == 120
    r = http.post("/configuracoes", data={"voltar": "https://fora.com"}, follow_redirects=False)
    assert r.headers["location"].startswith("/configuracoes")


def test_sem_gasto_na_pf_ou_desligado_usa_o_fixo(con):
    aluno(con, "Ana")
    p = precos.carregar_parametros(con)
    assert not p["salario_hora"]["usado"] and p["mo"]["valor_hora"] == pytest.approx(46.17)
    gasto_pf(con, 4500, -1)
    with con:
        con.execute("UPDATE parametros SET valor=0 WHERE grupo='mao_obra' AND chave='valor_hora_auto'")
    p = precos.carregar_parametros(con)
    assert not p["salario_hora"]["ligado"] and p["mo"]["valor_hora"] == pytest.approx(46.17)


def test_painel_e_configuracoes_mostram_de_onde_vem_o_valor(con):
    aluno(con, "Ana")
    gasto_pf(con, 4500, -1)
    http = TestClient(main.app, base_url="http://localhost")
    painel = http.get("/").text
    assert "Seu salário por hora" in painel and "R$ 46,39" in painel and "97 h da agenda cheia" in painel
    assert "O mês cobre seus custos?" in painel and 'href="/calculos"' in painel
    cfg = http.get("/configuracoes").text
    assert "Salário por hora em uso" in cfg and "R$ 46,39" in cfg


def _fixo(con, valor_hora=53):
    with con:
        con.execute("UPDATE parametros SET valor=? WHERE grupo='mao_obra' AND chave='valor_hora'", (valor_hora,))
        con.execute("UPDATE parametros SET valor=0 WHERE grupo='mao_obra' AND chave='valor_hora_auto'")


def test_valor_fixo_vai_para_os_precos(con):
    _fixo(con)
    p = precos.carregar_parametros(con)
    base = precos.base_motor("Pacote de Aulas", 8, local="CIA")
    r = precos.calcular(base, p, 1)
    assert r["valor_hora"] == 53 and r["horas"] == 9 and r["mao_obra"] == pytest.approx(477)


def test_cobre_custos_no_fixo_mostra_o_que_o_lucro_paga_da_pf(con):
    aluno(con, "Ana")
    gasto_pf(con, 4500, -1)
    _fixo(con)
    c = main.cobre_custos(con, precos.carregar_parametros(con))
    assert not c["pessoal_pf"] and c["pessoal"] == pytest.approx(477) and c["gasto_pf"] == 4500
    assert c["falta_pf"] == pytest.approx(4500 - 477)
    assert c["sobra_pf"] == pytest.approx(c["sobra"] - c["falta_pf"]) and not c["cobre_tudo"]


def test_cobre_custos_automatico_nao_conta_a_pf_duas_vezes(con):
    aluno(con, "Ana")
    gasto_pf(con, 4500, -1)
    c = main.cobre_custos(con, precos.carregar_parametros(con))
    assert c["pessoal_pf"] and c["falta_pf"] == 0 and c["cobre_tudo"] == c["cobre"]


def test_painel_e_calculos_no_fixo_escolhido(con):
    aluno(con, "Ana")
    gasto_pf(con, 4500, -1)
    _fixo(con)
    http = TestClient(main.app, base_url="http://localhost")
    painel = http.get("/").text
    assert "valor fixo escolhido por você" in painel and "lance os gastos da PF" not in painel
    assert "com o resto da PF" in painel
    t = http.get("/calculos").text
    assert "O lucro precisa cobrir" in t and "R$ 4.023,00" in t
