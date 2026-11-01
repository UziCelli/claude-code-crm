"""Pagamento adiantado: aluno que parcelou no cartão (ou pagou vários meses de uma vez) não aparece todo mês para pagar a mensalidade.
lancamentos.meses = quantos meses o pagamento cobre; sem ele vale o cálculo automático pelo valor."""
import datetime as dt
from urllib.parse import unquote

import pytest

from app import alunos, assistente, db, financeiro
from tests.test_alertas import con_temp  # noqa: F401  (fixture: banco temporário)
from tests.test_rotas import cliente_http  # noqa: F401  (fixture: cliente HTTP num banco temporário)

PAGOU = "2026-09-08"   # data fixa: o teste não depende do dia em que roda


def aluno(con, valor=400, renova="2026-09-10", nome="Rita", tipo="Consultoria Online"):
    """Por padrão sem aula marcada (consultoria): o estado não depende de aula dada. Pacote de Aulas = tem aula."""
    with con:
        return con.execute("""INSERT INTO clientes (nome, telefone, status, tipo_servico, valor, data_renovacao, data_inicio)
                              VALUES (?, '11999990000', 'ativo', ?, ?, ?, '2026-01-01')""", (nome, tipo, valor, renova)).lastrowid


def pagar(con, cid, valor, data=PAGOU, meses=None):
    with con:
        return con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id, meses)
                              VALUES ('PJ','entrada',?,?,?,'Pacotes de Aulas',?,?)""", (data, data, valor, cid, meses)).lastrowid


def mes_do_aluno(con, cid, mes):
    return {i["id"]: i for i in financeiro.mensalidades(con, mes)}.get(cid)


def estado(con, cid, hoje):
    return alunos.estado(con, hoje=hoje, ids=[cid])[cid]


def rotulos(e):
    return [x.get("rotulo", "wa") for x in e["acoes"]]


def meses_de(con, lid):
    return con.execute("SELECT meses FROM lancamentos WHERE id=?", (lid,)).fetchone()[0]


def test_plano_de_6_meses_com_desconto_anda_6_meses_e_nao_pede_pagamento(con_temp):
    cid = aluno(con_temp)
    pagar(con_temp, cid, 2160, meses=6)   # 6 × 400 com desconto: 5,4 mensalidades
    r = financeiro.renovacoes(con_temp, cid)[cid]
    assert r["efetiva"] == "2027-03-10" and r["ciclos"] == 6 and not r["pendente"]
    for hoje in ("2026-10-12", "2026-11-05", "2026-12-20", "2027-01-15", "2027-02-01"):   # ainda coberto: nunca cobrar nem "vence logo"
        e = estado(con_temp, cid, hoje)
        assert e["situacao"] not in ("cobrar", "vence_logo", "sem_pagar_sem_aula"), hoje
        assert e["renovacao"]["efetiva"] == "2027-03-10" and "Registrar pagamento" not in rotulos(e)
    assert estado(con_temp, cid, "2027-03-05")["situacao"] == "vence_logo"   # a semana do fim da cobertura
    assert estado(con_temp, cid, "2027-03-20")["situacao"] == "cobrar"
    # mensalidades: setembro recebido; outubro a fevereiro pago adiantado; março em aberto de novo
    assert mes_do_aluno(con_temp, cid, "2026-09")["situacao"] == "recebido"
    for mes in ("2026-10", "2026-11", "2026-12", "2027-01", "2027-02"):
        i = mes_do_aluno(con_temp, cid, mes)
        assert (i["situacao"], i["quitado"], i["falta"], i["previsto"]) == ("pago adiantado", True, 0.0, 400.0), mes
        assert (i["pago_em_mes"], i["coberto_ate"]) == ("2026-09", "2027-02")
    i = mes_do_aluno(con_temp, cid, "2027-03")
    assert (i["situacao"], i["quitado"], i["falta"], i["coberto_ate"]) == ("em aberto", False, 400.0, None)


def test_mes_coberto_conta_como_pago_para_quem_nao_vai_a_aula(con_temp):
    cid = aluno(con_temp, tipo="Pacote de Aulas")
    pagar(con_temp, cid, 2160, meses=6)
    e = estado(con_temp, cid, "2026-11-05")
    assert e["situacao"] == "pago_sem_aula" and e["situacao"] != "sem_pagar_sem_aula"   # pagou (adiantado) e não veio: crédito ou pulou
    assert rotulos(e)[0] == "Pulou o mês"


def test_estado_mostra_pago_adiantado_no_pagamento_do_mes(con_temp):
    cid = aluno(con_temp)
    pagar(con_temp, cid, 2160, meses=6)
    p = estado(con_temp, cid, "2026-11-05")["pagamento"]
    assert (p["mes"], p["situacao"], p["recebido"], p["coberto_ate"]) == ("2026-11", "pago adiantado", 0.0, "2027-02")


def test_sem_meses_o_automatico_continua_o_mesmo_e_a_rota_corrige(cliente_http):
    http, cid = cliente_http
    con = db.conectar()
    with con:
        con.execute("UPDATE clientes SET valor=400, status='ativo', data_renovacao='2026-09-10' WHERE id=?", (cid,))
    lid = pagar(con, cid, 2160)
    assert financeiro.renovacoes(con, cid)[cid]["efetiva"] == "2027-02-10"   # 2160 ÷ 400 = 5 mensalidades inteiras: como sempre foi
    r = http.post(f"/financeiro/lancamento/{lid}/meses", data={"meses": "6", "cliente_id": cid, "voltar": f"/clientes/{cid}#pagamentos"},
                  follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/clientes/{cid}?msg=")
    assert "agora cobre 6 meses (até 02/2027)" in unquote(r.headers["location"])
    assert meses_de(con, lid) == 6
    assert financeiro.renovacoes(con, cid)[cid]["efetiva"] == "2027-03-10"
    http.post(f"/financeiro/lancamento/{lid}/meses", data={"meses": "1", "cliente_id": cid}, follow_redirects=False)
    assert meses_de(con, lid) is None   # 1 = automático
    assert financeiro.renovacoes(con, cid)[cid]["efetiva"] == "2027-02-10"
    con.close()


def test_registro_antigo_de_2_mensalidades_sem_meses_cobre_o_mes_seguinte(con_temp):
    cid = aluno(con_temp)
    pagar(con_temp, cid, 800)
    assert mes_do_aluno(con_temp, cid, "2026-09")["situacao"] == "recebido"
    i = mes_do_aluno(con_temp, cid, "2026-10")
    assert (i["situacao"], i["quitado"], i["falta"], i["coberto_ate"]) == ("pago adiantado", True, 0.0, "2026-10")
    assert mes_do_aluno(con_temp, cid, "2026-11")["situacao"] == "em aberto"


def test_mensalidade_normal_continua_igual(con_temp):
    cid = aluno(con_temp)
    pagar(con_temp, cid, 400)
    pagar(con_temp, cid, 360, data="2026-10-09")   # 90%: mês inteiro, não é adiantado
    assert mes_do_aluno(con_temp, cid, "2026-09")["situacao"] == "recebido"
    assert mes_do_aluno(con_temp, cid, "2026-10")["situacao"] == "recebido"
    i = mes_do_aluno(con_temp, cid, "2026-11")
    assert (i["situacao"], i["falta"], i["coberto_ate"], i["pago_em_mes"]) == ("em aberto", 400.0, None, None)
    assert financeiro.renovacoes(con_temp, cid)[cid]["efetiva"] == "2026-11-10"


def test_pagamento_do_proprio_mes_vale_mais_que_a_cobertura(con_temp):
    cid = aluno(con_temp)
    pagar(con_temp, cid, 2160, meses=6)
    pagar(con_temp, cid, 400, data="2026-10-05")
    i = mes_do_aluno(con_temp, cid, "2026-10")
    assert (i["situacao"], i["recebido"], i["coberto_ate"]) == ("recebido", 400.0, None)


def test_meses_com_renovacao_marcada_paga_a_marcada_e_anda_o_resto(con_temp):
    cid = aluno(con_temp, renova="2026-09-10")
    with con_temp:
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'renovacao', '2026-09-10')", (cid,))
    pagar(con_temp, cid, 1200, data="2026-09-12", meses=3)
    assert financeiro.renovacoes(con_temp, cid)[cid]["efetiva"] == "2026-12-10"   # a marcada + 2 a mais = 3 meses no total


def test_previsao_nao_conta_mes_coberto_como_a_receber(con_temp):
    cid = aluno(con_temp)
    financeiro.salvar_saldos(con_temp, "2026-10-16", {"Inter": 1000}, {})

    def a_receber():
        p = financeiro.previsao(con_temp, "2026-10-16")
        return sum(i["valor"] for s in p["semanas"] for i in s["itens"] if i["descricao"] == "Mensalidades a receber")

    assert a_receber() > 0
    pagar(con_temp, cid, 2160, meses=6)
    assert a_receber() == 0   # outubro a fevereiro cobertos; março fica fora das 13 semanas
    assert financeiro._mensalidades_a_receber(con_temp, "2026-11")[0] == 0
    assert financeiro._mensalidades_a_receber(con_temp, "2027-03")[0] == 400


def test_acao_ja_pagou_adiantado_so_com_pagamento_no_ultimo_ano(con_temp):
    sem = aluno(con_temp, nome="Sem", renova="2026-10-20")
    com = aluno(con_temp, nome="Com", renova="2026-10-20")
    pagar(con_temp, com, 400, data="2026-09-20")
    e_sem, e_com = estado(con_temp, sem, "2026-10-18"), estado(con_temp, com, "2026-10-18")
    assert e_sem["situacao"] == "vence_logo" and "Já pagou adiantado" not in rotulos(e_sem)
    assert rotulos(e_com)[-1] == "Já pagou adiantado" and e_com["acoes"][-1]["href"] == f"/clientes/{com}#pagamentos"
    e_cob = estado(con_temp, sem, "2026-11-10")
    assert e_cob["situacao"] == "cobrar" and rotulos(e_cob) == ["Registrar pagamento", "wa", "Pular mês"]
    pagar(con_temp, sem, 400, data="2026-05-01")
    e_cob = estado(con_temp, sem, "2026-11-10")
    assert rotulos(e_cob) == ["Registrar pagamento", "wa", "Já pagou adiantado"] and len(e_cob["acoes"]) <= 3


def test_rota_meses_valida_aluno_tipo_e_limites(cliente_http):
    http, cid = cliente_http
    con = db.conectar()
    with con:
        outro = con.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Outro', 400, 'ativo')").lastrowid
    meu, alheio = pagar(con, cid, 400), pagar(con, outro, 400)
    with con:
        saida = con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria) VALUES ('PJ','saida',?,?,50,'Outros')""",
                            (PAGOU, PAGOU)).lastrowid

    def tenta(lid, valor):
        r = http.post(f"/financeiro/lancamento/{lid}/meses", data={"meses": valor, "cliente_id": cid, "voltar": f"/clientes/{cid}"},
                      follow_redirects=False)
        assert r.status_code == 303
        return unquote(r.headers["location"])

    assert "erro=" in tenta(alheio, "3") and meses_de(con, alheio) is None   # pagamento de outro aluno
    assert "erro=" in tenta(saida, "3") and meses_de(con, saida) is None     # saída
    assert "erro=" in tenta(9999, "3")                                       # não existe
    for ruim in ("0", "25", "-2", "abc"):
        assert "erro=" in tenta(meu, ruim) and meses_de(con, meu) is None, ruim
    assert "msg=" in tenta(meu, "24") and meses_de(con, meu) == 24
    assert "msg=" in tenta(meu, "") and meses_de(con, meu) is None
    con.close()


def test_dialogo_tem_o_campo_e_o_post_grava_meses(cliente_http):
    http, cid = cliente_http
    ficha = http.get(f"/clientes/{cid}").text
    assert 'name="meses"' in ficha and "Cobre quantos meses?" in ficha and "Pagou adiantado ou parcelou no cartão?" in ficha
    assert '<option value="12">12 meses</option>' in ficha and '<option value="1">1 mês</option>' in ficha
    assert 'id="pagamentos"' in ficha
    hoje = dt.date.today().isoformat()
    con = db.conectar()

    def post(**extra):
        dados = {"escopo": "PJ", "tipo": "entrada", "data": hoje, "pago_em": hoje, "valor": "2160,00", "categoria": "Outros",
                 "cliente_id": cid, "voltar": f"/clientes/{cid}", **extra}
        return http.post("/financeiro/lancamento", data=dados, follow_redirects=False)

    r = post(meses="6")
    assert r.status_code == 303 and "msg=" in r.headers["location"] and meses_de(con, 1) == 6
    ficha = http.get(f"/clientes/{cid}").text
    assert "cobre 6 meses" in ficha and 'action="/financeiro/lancamento/1/meses"' in ficha
    assert "erro=" in unquote(post(meses="30").headers["location"]) and con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 1
    post(meses="1")
    post(meses="")
    assert [x[0] for x in con.execute("SELECT meses FROM lancamentos ORDER BY id")] == [6, None, None]
    # editar pelo livro-caixa (sem o campo) não apaga o que o aluno disse
    http.post("/financeiro/lancamento", data={"id": 1, "escopo": "PJ", "tipo": "entrada", "data": hoje, "pago_em": hoje, "valor": "2160,00",
                                              "categoria": "Outros", "cliente_id": cid}, follow_redirects=False)
    assert meses_de(con, 1) == 6
    con.close()


def test_mensalidades_mostra_pago_adiantado_sem_botao_de_registrar(cliente_http):
    http, cid = cliente_http
    con = db.conectar()
    with con:
        con.execute("UPDATE clientes SET valor=400, status='ativo', data_renovacao='2026-09-10', data_inicio='2026-01-01' WHERE id=?", (cid,))
    pagar(con, cid, 2160, meses=6)
    pag = http.get("/financeiro/mensalidades?mes=2026-11").text
    assert "pago adiantado" in pag and "09/2026 (até 02/2027)" in pag
    assert "Registrar pagamento" not in pag.split("<tbody>")[1].split("</tbody>")[0] and "Pagou adiantado?" not in pag
    pag = http.get("/financeiro/mensalidades?mes=2027-03").text
    assert f'href="/clientes/{cid}#pagamentos">Pagou adiantado?</a>' in pag and "Registrar pagamento" in pag
    con.close()


def test_assistente_grava_meses_ao_criar_e_editar(con_temp):
    cid = aluno(con_temp)
    hoje = dt.date.today().isoformat()
    r = assistente._criar_lancamento(con_temp, {"escopo": "PJ", "tipo": "entrada", "data": hoje, "pago_em": hoje, "valor": 2160,
                                                "categoria": "Pacotes de Aulas", "cliente_id": cid, "meses": 6})
    assert meses_de(con_temp, r["id"]) == 6
    assistente._editar_lancamento(con_temp, {"id": r["id"], "meses": 3})
    assert meses_de(con_temp, r["id"]) == 3
    with pytest.raises(assistente.ErroFerramenta):
        assistente._editar_lancamento(con_temp, {"id": r["id"], "meses": 25})
