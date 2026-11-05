"""Números do mês pelo dinheiro que cai de verdade: quem pagou vários meses adiantado (antecipação do cartão) põe tudo no caixa no mês
em que pagou e nada nos seguintes. Previsto da tela Mensalidades, "Entra no mês" do painel, lucro por hora e "O mês cobre os custos?"
seguem isso; a "Carteira mensal" (faturamento_recorrente) continua sendo o valor mensal de todos."""
import pytest

from app import assistente, financeiro, main
from tests.test_paineis import aluno, cliente_http, con_temp  # noqa: F401  (fixtures)

PAGOU = "2026-10-10"


def pagar(con, cid, valor, data=PAGOU, meses=None):
    with con:
        con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id, meses)
                       VALUES ('PJ','entrada',?,?,?,'Pacotes de Aulas',?,?)""", (data, data, valor, cid, meses))


def tres_alunos(con):
    """Rita pagou 3 meses em outubro (cobre out-dez); Ana pagou novembro; Bia ainda não pagou novembro."""
    rita, ana, bia = aluno(con, "Rita", 900), aluno(con, "Ana", 900), aluno(con, "Bia", 900)
    pagar(con, rita, 2700, meses=3)
    pagar(con, ana, 900, data="2026-11-05")
    return rita, ana, bia


def test_entra_e_zero_para_quem_pagou_adiantado_e_cheio_no_mes_do_pagamento(con_temp):
    rita, ana, bia = tres_alunos(con_temp)
    nov = {i["id"]: i for i in financeiro.mensalidades(con_temp, "2026-11")}
    assert nov[rita]["situacao"] == "pago adiantado" and nov[rita]["entra"] == 0
    assert nov[ana]["entra"] == 900 and nov[bia]["entra"] == 900   # pagou / ainda vai pagar
    out = {i["id"]: i for i in financeiro.mensalidades(con_temp, "2026-10")}
    assert out[rita]["entra"] == 2700   # os 3 meses caem inteiros em outubro


def test_cobre_custos_conta_so_o_que_entra_no_mes(con_temp):
    rita, ana, bia = tres_alunos(con_temp)
    p = main.precos.carregar_parametros(con_temp)
    nov, out = main.cobre_custos(con_temp, p, mes="2026-11"), main.cobre_custos(con_temp, p, mes="2026-10")
    assert nov["receita"] == 1800 and nov["carteira"] == 2700 and nov["adiantado"] == 900
    assert out["receita"] == 2700 + 900 + 900   # outubro: Ana e Bia em aberto (900 cada) + os 3 meses da Rita
    assert nov["negocio"] == out["negocio"] and nov["pessoal"] == out["pessoal"]   # custos existem todo mês
    assert nov["impostos"] < out["impostos"]   # impostos acompanham o dinheiro que entrou


def test_lucro_hora_cai_no_mes_coberto_e_sobe_no_mes_do_pagamento(con_temp):
    tres_alunos(con_temp)
    nov, out = main.calcular_metricas(con_temp, "2026-11"), main.calcular_metricas(con_temp, "2026-10")
    assert nov["faturamento_recorrente"] == out["faturamento_recorrente"] == 2700   # carteira mensal não muda
    assert nov["entra_mes"] == 1800 and out["entra_mes"] == 4500
    assert nov["lucro_hora"] < out["lucro_hora"]
    c = con_temp.execute("SELECT * FROM clientes WHERE nome='Ana'").fetchone()
    est = main.estimativa_cliente(con_temp, c, main.precos.carregar_parametros(con_temp))
    # novembro: Ana e Bia dão o lucro normal; Rita (0 entrou) tira a mensalidade inteira menos os impostos dela
    rita_nov = main.lucro_pelo_caixa(est, 900, 0)
    assert nov["lucro_hora"] == pytest.approx((2 * est["lucro"] + rita_nov) / 24, abs=0.01)


def test_tela_mensalidades_previsto_e_recebido_mais_falta(cliente_http):
    http, con = cliente_http
    tres_alunos(con)
    t = http.get("/financeiro/mensalidades?mes=2026-11").text
    assert "O que cai neste mês" in t and "Já pago adiantado: R$ 900,00" in t
    assert "R$ 1.800,00" in t   # previsto = 900 recebido (Ana) + 900 falta (Bia); Rita fora
    r = assistente._mensalidades_do_mes(con, {"mes": "2026-11"})
    assert (r["previsto"], r["recebido"], r["falta_receber"], r["ja_pago_adiantado"]) == (1800, 900, 900, 900)


def test_painel_mostra_carteira_mensal_e_entra_no_mes(cliente_http):
    http, con = cliente_http
    aluno(con, "Ana", 900)
    t = http.get("/").text
    assert "Carteira mensal" in t and "Entra no mês: R$ 900,00" in t and "pelo dinheiro que entra no mês" in t
    t = http.get("/calculos").text
    assert "Mensalidades que entram no mês" in t
