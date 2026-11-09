"""Correções de tela da auditoria: setas do Painel (N6), lucro/h sem aulas (N9), card PF (D10), rótulos e avisos (D17)."""
import datetime as dt

from app import db, financeiro, main, precos
from tests.test_financeiro import con_temp, lancar  # noqa: F401
from tests.test_rotas import cliente_http  # noqa: F401


def _mes_ant():
    return (dt.date.fromisoformat(main.mes_atual() + "-01") - dt.timedelta(days=1)).strftime("%Y-%m")


def _linha(mes):
    con = db.conectar()
    try:
        return con.execute("SELECT * FROM metricas_mensais WHERE mes=?", (mes,)).fetchone()
    finally:
        con.close()


def _aluno_ativo(nome="Outro Aluno", valor=300):
    con = db.conectar()
    with con:
        con.execute("INSERT INTO clientes (nome, status, valor) VALUES (?, 'ativo', ?)", (nome, valor))
    con.close()


# ---------- N6 ----------
def test_painel_sem_mes_anterior_nao_grava_nem_mostra_seta(cliente_http):
    http, _ = cliente_http
    r = http.get("/")
    assert r.status_code == 200
    assert _linha(_mes_ant()) is None
    assert "vs mês anterior" not in r.text


def test_painel_grava_foto_do_mes_atual_e_atualiza_na_visita_seguinte(cliente_http):
    http, _ = cliente_http
    http.get("/")
    antes = _linha(main.mes_atual())
    assert antes is not None and antes["foto"] == 1
    _aluno_ativo()
    http.get("/")
    depois = _linha(main.mes_atual())
    assert depois["foto"] == 1 and depois["clientes_ativos"] == antes["clientes_ativos"] + 1


def test_painel_nao_toca_linha_do_mes_atual_com_foto_nula(cliente_http):
    http, _ = cliente_http
    con = db.conectar()
    with con:
        con.execute("INSERT INTO metricas_mensais (mes, clientes_ativos, horas_ocupadas, lucro_hora, foto) VALUES (?,?,?,?,NULL)",
                    (main.mes_atual(), 77, 5, 10))
    con.close()
    antes = dict(_linha(main.mes_atual()))
    _aluno_ativo()
    http.get("/")
    assert dict(_linha(main.mes_atual())) == antes


def test_fechar_mes_grava_foto_nula_e_visitas_nao_mudam(cliente_http):
    http, _ = cliente_http
    http.get("/")   # cria a foto automática
    assert _linha(main.mes_atual())["foto"] == 1
    assert http.post("/painel/fechar-mes", follow_redirects=False).status_code == 303
    fechada = dict(_linha(main.mes_atual()))
    assert fechada["foto"] is None
    _aluno_ativo()
    http.get("/")
    assert dict(_linha(main.mes_atual())) == fechada


def test_linha_antiga_do_mes_anterior_fica_identica_e_mostra_seta(cliente_http):
    http, _ = cliente_http
    con = db.conectar()
    with con:
        con.execute("INSERT INTO metricas_mensais (mes, clientes_ativos, horas_ocupadas, lucro_hora, pct_receita_grupos,"
                    " faturamento_recorrente, clientes_perdidos, vendas_abaixo_10, nivel) VALUES (?,5,10,50,0,1000,0,0,1)", (_mes_ant(),))
    con.close()
    antes = dict(_linha(_mes_ant()))
    r = http.get("/")
    assert dict(_linha(_mes_ant())) == antes
    assert "vs mês anterior" in r.text   # 1 aluno hoje contra 5: seta aparece


# ---------- N9 ----------
def test_servico_sem_aulas_tem_horas_e_lucro_hora_coerente(cliente_http):
    con = db.conectar()
    p = precos.carregar_parametros(con)
    con.close()
    for tipo, qtd, freq in precos.PLANOS:
        r = precos.calcular(precos.base_motor(tipo, qtd, freq, "CIA"), p, local="CIA")
        assert r["horas"] > 0, tipo
        assert abs(r["lucro_hora"] - r["lucro"] / r["horas"]) <= 0.02 * abs(r["lucro_hora"]) + 0.01, tipo   # horas vêm arredondadas


def test_explorador_abre_ordenado_por_lucro_hora(cliente_http):
    http, _ = cliente_http
    assert http.get("/explorador?ordem=lucro_hora").status_code == 200


# ---------- D10 ----------
def test_card_pf_conta_pelo_dia_do_pagamento(con_temp):
    lancar(con_temp, "saida", 100, "2026-10-30", pago_em="2026-11-02", escopo="PF")
    assert financeiro.resumo_mes(con_temp, "2026-11")["pf"]["saidas"] == 100
    assert financeiro.resumo_mes(con_temp, "2026-10")["pf"]["saidas"] == 0


def test_receita_pj_continua_pelo_mes_da_data(con_temp):
    lancar(con_temp, "entrada", 500, "2026-10-30", pago_em="2026-11-02")
    assert financeiro.resumo_mes(con_temp, "2026-10")["receita"] == 500
    assert financeiro.resumo_mes(con_temp, "2026-11")["receita"] == 0


def test_tela_card_pf_explica_pago_em(cliente_http):
    http, _ = cliente_http
    assert "Conta pelo dia em que o dinheiro entrou ou saiu (pago em)." in http.get("/financeiro/painel").text


# ---------- D17a ----------
def test_painel_financeiro_rotulo_mes_em_andamento(cliente_http):
    http, _ = cliente_http
    t = http.get("/financeiro/painel").text
    assert "Mês em andamento: ainda faltam entradas e contas." in t and "(em andamento)" in t
    passado = http.get("/financeiro/painel?mes=2026-01").text
    assert "Mês em andamento" not in passado and "(em andamento)" not in passado


# ---------- D17b ----------
def _gasto(con, mes, valor):
    with con:
        con.execute("INSERT INTO gastos_marketing (mes, canal, mensalidade, anuncios, comissoes, outros) VALUES (?, 'Instagram', ?, 0, 0, 0)", (mes, valor))


def test_marketing_divergencia_bate_nao_bate_e_lado_vazio(con_temp):
    assert financeiro.marketing_divergencia(con_temp, "2026-11") is None
    _gasto(con_temp, "2026-11", 200)
    lancar(con_temp, "saida", 200, "2026-11-05", categoria="Marketing/Divulgação")
    assert financeiro.marketing_divergencia(con_temp, "2026-11") is None
    lancar(con_temp, "saida", 50, "2026-11-06", categoria="Marketing/Divulgação")
    assert financeiro.marketing_divergencia(con_temp, "2026-11") == {"campanhas": 200, "financeiro": 250}
    _gasto(con_temp, "2026-12", 80)   # só Campanhas
    assert financeiro.marketing_divergencia(con_temp, "2026-12") == {"campanhas": 80, "financeiro": 0}
    lancar(con_temp, "saida", 30, "2027-01-05", categoria="Marketing/Divulgação")   # só Financeiro
    assert financeiro.marketing_divergencia(con_temp, "2027-01") == {"campanhas": 0, "financeiro": 30}


def test_tela_campanhas_avisa_quando_nao_bate(cliente_http):
    http, _ = cliente_http
    con = db.conectar()
    _gasto(con, "2026-11", 120)
    con.close()
    t = http.get("/campanhas?mes=2026-11").text
    assert "Marketing de 11/2026 não bate" in t and "R$ 120,00" in t and "lance o gasto nos dois lugares" in t
    con = db.conectar()
    lancar(con, "saida", 120, "2026-11-03", categoria="Marketing/Divulgação")
    con.close()
    assert "não bate" not in http.get("/campanhas?mes=2026-11").text
