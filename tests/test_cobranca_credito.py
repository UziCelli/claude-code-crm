"""Cobrança de aluno vencido com crédito (aula paga e não usada): o crédito sai do saldo ANTES da multa e dos juros,
que incidem só sobre o saldo devedor. O mesmo total no alerta, no Registrar pagamento, na ficha, no cartão, no Pix e no Assistente.
Também: crédito que cobre o mês, vários meses com crédito, Renovação marcada sem pagamento (pendente) e vencimento no fim do mês."""
import datetime as dt

from app import alunos, assistente, db, financeiro, main, marcadores
from tests.test_alertas import cliente, con_temp, dia, do_aluno, pix_completo  # noqa: F401  (con_temp: fixture de banco temporário)
from tests.test_alertas_acao import http  # noqa: F401

MES_PASSADO = financeiro.somar_meses(dt.date.today().isoformat()[:7], -1) + "-01"


def par(con):
    return db.parametros(con, "cobranca")   # multa 2%, juros 1% ao mês


def credito(con, cid, valor, mes=MES_PASSADO):
    with con:
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, valor) VALUES (?, 'credito', ?, ?)", (cid, mes, valor))


def paga(http, cid, valor):
    """Registra o pagamento pelo mesmo caminho do diálogo (desconta o crédito)."""
    hoje = dt.date.today().isoformat()
    r = http.post("/financeiro/lancamento", data={"escopo": "PJ", "tipo": "entrada", "data": hoje, "pago_em": hoje, "meses": "1",
                  "valor": f"{valor:.2f}".replace(".", ","), "categoria": "Pacotes de Aulas", "cliente_id": cid,
                  "voltar": f"/clientes/{cid}"}, follow_redirects=False)
    assert r.status_code == 303


# ---------- o motor ----------
def test_alexei_multa_e_juros_so_sobre_o_saldo(con_temp):
    """O caso do Painel: mensalidade 2.042,50, crédito 612,75, 1 dia de atraso. Antes: 2.084,03 (crédito ignorado)."""
    assert financeiro.cobranca(2042.50, "2026-11-05", "2026-11-06", par(con_temp))["total"] == 2084.03   # sem crédito: o de antes
    c = financeiro.cobranca(2042.50, "2026-11-05", "2026-11-06", par(con_temp), 612.75)
    assert (c["meses"], c["dias"], c["bruto"], c["credito"], c["valor"]) == (1, 1, 2042.50, 612.75, 1429.75)
    assert (c["multa"], c["juros"], c["total"]) == (28.60, 0.48, 1458.83)   # 2% e 1 dia de 1% sobre 1.429,75
    assert round(c["valor"] + c["multa"] + c["juros"], 2) == c["total"]    # as partes mostradas fecham com o total


def test_credito_que_cobre_o_mes_nao_deixa_nada_a_cobrar(con_temp):
    assert financeiro.cobranca(400, "2026-10-11", "2026-10-31", par(con_temp), 400) is None
    assert financeiro.cobranca(400, "2026-10-11", "2026-10-31", par(con_temp), 999) is None   # nunca passa de uma mensalidade


def test_varios_meses_o_credito_sai_so_do_mais_antigo(con_temp):
    c = financeiro.cobranca(400, "2026-09-11", "2026-10-31", par(con_temp), 100)
    # setembro: saldo 300 (50 dias) -> multa 6, juros 5; outubro: 400 (20 dias) -> multa 8, juros 2,67
    assert (c["meses"], c["bruto"], c["credito"], c["valor"], c["multa"], c["juros"], c["total"]) == (2, 800, 100, 700, 14, 7.67, 721.67)
    # o crédito cobre setembro inteiro: cobra só outubro
    c = financeiro.cobranca(400, "2026-09-11", "2026-10-31", par(con_temp), 400)
    assert (c["meses"], c["credito"], c["valor"], c["multa"], c["juros"], c["total"]) == (2, 400, 400, 8, 2.67, 410.67)


def test_fim_do_mes_usa_o_dia_do_cadastro(con_temp):
    """Venceu 28/02 (cadastro dia 31): o mês seguinte vence 31/03, não 28/03."""
    assert financeiro.cobranca(400, "2026-02-28", "2026-03-30", par(con_temp), dia=31)["meses"] == 1
    assert financeiro.cobranca(400, "2026-02-28", "2026-03-30", par(con_temp))["meses"] == 2   # sem o dia: caía em 28/03
    c = financeiro.cobranca(400, "2026-02-28", "2026-04-05", par(con_temp), dia=31)
    assert (c["meses"], c["juros"]) == (2, 5.47)   # 36 dias + 5 dias (de 31/03), não 8


# ---------- o mesmo total em todo lugar ----------
def test_alexei_mesmo_total_no_alerta_pagamento_ficha_cartao_pix_e_assistente(con_temp, http):
    pix_completo(con_temp)
    cid = cliente(con_temp, "Alexei", dia(-1), valor=2042.50)
    credito(con_temp, cid, 612.75)

    e = alunos.estado_aluno(con_temp, cid)
    assert e["situacao"] == "cobrar" and e["cobranca"]["total"] == 1458.83
    assert e["texto"] == f"renovação venceu em {main.data_br(dia(-1))} (crédito de R$ 612,75 já descontado)"
    pagar = e["acoes"][0]["dados"]
    assert (pagar["valor"], pagar["mensal"]) == ("1458,83", "2042,50")
    assert pagar["nota"] == "Crédito de R$ 612,75 descontado · multa de R$ 28,60 e juros de R$ 0,48 incluídos"

    [al] = do_aluno(con_temp, "Alexei")
    assert al["botao"] == "Cobrar R$ 1.458,83 · 1 dia" and al["cartao"]["codigo"]
    assert "54071458.83" in al["cartao"]["codigo"]   # o Pix leva o total com o crédito descontado

    ficha = http.get(f"/clientes/{cid}").text
    assert ("Total atualizado: <strong><span>R$ 1.458,83</span></strong> = saldo <span>R$ 1.429,75</span> "
            "(<span>R$ 2.042,50</span> − crédito <span>R$ 612,75</span>)") in ficha and "1 dia de atraso" in ficha
    assert 'data-valor="1458,83"' in ficha and 'data-mensal="2042,50"' in ficha
    svg = http.get(f"/clientes/{cid}/cobranca/cartao.svg").text
    assert "Crédito descontado" in svg and "− R$ 612,75" in svg and "R$ 1.458,83" in svg and "R$ 2.084,03" not in svg

    assert assistente._ver_aluno(con_temp, {"cliente_id": cid})["cobranca"]["total"] == 1458.83

    paga(http, cid, 1458.83)   # pagou o que foi cobrado: o crédito é usado e a cobrança some
    assert financeiro.creditos(con_temp, cid).get(cid) is None
    assert alunos.estado_aluno(con_temp, cid)["situacao"] != "cobrar"
    assert not [x for x in do_aluno(con_temp, "Alexei") if "venceu" in x["texto"] or x.get("cartao")]


def test_credito_que_cobre_o_mes_oferece_pulou_o_mes_e_nao_cobra(con_temp, http):
    cid = cliente(con_temp, "Bia", dia(-3), valor=400)
    credito(con_temp, cid, 400)
    e = alunos.estado_aluno(con_temp, cid)
    assert e["situacao"] == "cobrar" and e["cobranca"] is None and e["botao"] is None
    assert e["texto"] == f"renovação venceu em {main.data_br(dia(-3))}: o crédito de R$ 400,00 cobre esse mês"
    assert [x["rotulo"] for x in e["acoes"]] == ["Pulou o mês"]
    [al] = do_aluno(con_temp, "Bia")
    assert not al.get("cartao") and "Cobrar" not in (al.get("botao") or "")
    assert marcadores.contexto(con_temp)["cobrar_total"] == 0   # Saúde financeira: "a cobrar" não conta a mensalidade cheia
    assert "Total atualizado" not in http.get(f"/clientes/{cid}").text

    msg, erro = alunos.pular_mes(con_temp, cid)   # o botão: anda a renovação e usa o crédito
    assert not erro and "cobriu esse mês" in msg
    assert alunos.estado_aluno(con_temp, cid)["situacao"] != "cobrar"


def test_dois_meses_com_credito_pagar_o_total_quita_os_dois(con_temp, http):
    renova = financeiro.proxima_renovacao(dia(-5), -1)   # venceu há ~35 dias: 2 meses em atraso
    cid = cliente(con_temp, "Caio", renova, valor=400)
    credito(con_temp, cid, 100)
    cob = alunos.estado_aluno(con_temp, cid)["cobranca"]
    assert (cob["meses"], cob["credito"], cob["valor"]) == (2, 100, 700)
    paga(http, cid, cob["total"])
    assert financeiro.renovacoes(con_temp, cid)[cid]["efetiva"] == financeiro.proxima_renovacao(renova, 2)
    assert alunos.estado_aluno(con_temp, cid)["situacao"] != "cobrar"


# ---------- Renovação marcada sem pagamento ----------
def test_renovacao_marcada_sem_pagamento_cobra_desde_a_data(con_temp, http):
    cid = cliente(con_temp, "Duda", dia(-10), valor=400)
    with con_temp:   # marcou a renovação 2 dias antes do vencimento, e o aluno não pagou
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'renovacao', ?)", (cid, dia(-12)))
    r = financeiro.renovacoes(con_temp, cid)[cid]
    assert r["pendente"] and r["efetiva"] == financeiro.proxima_renovacao(dia(-10)) and r["vence"] == dia(-10)

    e = alunos.estado_aluno(con_temp, cid)
    assert e["situacao"] == "cobrar" and e["texto"] == f"renovação venceu em {main.data_br(dia(-10))}"
    assert (e["cobranca"]["meses"], e["cobranca"]["dias"], e["cobranca"]["total"]) == (1, 10, 409.33)   # 400 + 8 + 1,33
    [al] = do_aluno(con_temp, "Duda")
    assert al["botao"] == "Cobrar R$ 409,33 · 10 dias"
    ficha = http.get(f"/clientes/{cid}").text
    assert f"Renovação marcada (vencimento {main.data_br(dia(-10))})" in ficha and "Total atualizado: <strong><span>R$ 409,33</span></strong>" in ficha

    paga(http, cid, 409.33)   # quita a renovação marcada: a data não anda outro mês
    r = financeiro.renovacoes(con_temp, cid)[cid]
    assert not r["pendente"] and r["efetiva"] == r["vence"] == financeiro.proxima_renovacao(dia(-10))
    assert alunos.estado_aluno(con_temp, cid)["situacao"] != "cobrar"


def test_renovacao_marcada_e_outro_mes_vencido_cobra_os_dois(con_temp):
    renova = financeiro.proxima_renovacao(dia(-5), -1)
    cid = cliente(con_temp, "Eva", renova, valor=400)
    with con_temp:
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'renovacao', ?)",
                         (cid, (dt.date.fromisoformat(renova) - dt.timedelta(days=2)).isoformat()))
    cob = alunos.estado_aluno(con_temp, cid)["cobranca"]
    assert cob["meses"] == 2 and cob["valor"] == 800   # o mês renovado e o seguinte, cada um com sua multa e seus juros


def test_lembrete_antes_do_vencimento_continua_descontando_o_credito(con_temp):
    pix_completo(con_temp)
    cid = cliente(con_temp, "Gil", dia(2), valor=400, inicio=dia(-3))
    credito(con_temp, cid, 150)
    [al] = do_aluno(con_temp, "Gil")
    assert al["botao"] == "Lembrete: vence em 2 dias" and "5406250.00" in al["cartao"]["codigo"]
