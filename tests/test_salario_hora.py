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
    with c:
        c.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, preco_base,
                     custo_operacional, mao_obra, custo_total, sessoes_mes) VALUES ('Pacote de Aulas', 'CIA', 'PIX', 8, 0, 1100, 900, 415.5, 900, 8)""")
        c.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, preco_base,
                     custo_operacional, mao_obra, custo_total, sessoes_mes) VALUES ('Consultoria Online', 'Online', 'PIX', 0, 0, 300, 100, 60, 100, 0)""")
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
    aluno(con, "Caio", local="SmartFit")                                       # sem preço base: só as 8 aulas
    aluno(con, "Duda", status="inativo")
    p = precos.carregar_parametros(con)
    assert main.horas_trabalho_mes(con, p) == pytest.approx(9 + 2.5 + 8)


def test_valor_da_hora_sai_dos_custos_pessoais_e_vai_para_os_precos(con):
    aluno(con, "Ana")
    aluno(con, "Bia")
    gasto_pf(con, 4500, -1)
    p = precos.carregar_parametros(con)
    sh = p["salario_hora"]
    assert sh["usado"] and sh["horas"] == 18 and sh["custo_pessoal"] == 4500
    assert p["mo"]["valor_hora"] == pytest.approx(250)
    base = dict(con.execute("SELECT * FROM precos_base WHERE tipo_servico='Pacote de Aulas'").fetchone())
    assert precos.calcular(base, p)["mao_obra"] == pytest.approx(9 * 250)


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
    assert "Seu salário por hora" in painel and "R$ 500,00" in painel and "9 h de trabalho" in painel
    cfg = http.get("/configuracoes").text
    assert "Salário por hora em uso" in cfg and "R$ 500,00" in cfg
