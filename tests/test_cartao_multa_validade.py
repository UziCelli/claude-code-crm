"""Cartão de cobrança com a multa e os juros separados e o prazo do Pix (o QR estático não expira: o cartão diz até quando vale).
Quem paga o Pix antigo depois do vencimento: o CRM avisa quanto faltou e, com a caixa do diálogo, lança a diferença a receber,
com o botão "Cobrar diferença" (o mesmo cartão com QR), "Recebi" e "Dispensar". A diferença nunca 'paga o mês' nem mexe na renovação."""
import datetime as dt
from urllib.parse import unquote

from app import alunos, financeiro, main
from tests.test_alertas import cliente, con_temp, dia, pix_completo  # noqa: F401  (con_temp: fixture de banco temporário)
from tests.test_alertas_acao import http  # noqa: F401
from tests.test_cobranca_botoes import alexei

HOJE = dt.date.today()


def paga(http, cid, valor, pago_em=None, diferenca=True):
    """Registra o pagamento pelo diálogo (dlg-pgto); diferenca = a caixa "Lançar a diferença a receber" marcada."""
    pago_em = pago_em or HOJE.isoformat()
    dados = {"escopo": "PJ", "tipo": "entrada", "data": pago_em, "pago_em": pago_em, "meses": "1", "valor": f"{valor:.2f}".replace(".", ","),
             "categoria": "Mensalidade (Aulas Presenciais)", "cliente_id": cid, "voltar": f"/clientes/{cid}"}
    if diferenca:
        dados["diferenca"] = "1"
    r = http.post("/financeiro/lancamento", data=dados, follow_redirects=False)
    assert r.status_code == 303
    return unquote(r.headers["location"])


def multas(con):
    return [dict(r) for r in con.execute("SELECT * FROM lancamentos WHERE categoria=? AND excluido_em IS NULL", (financeiro.MULTA_JUROS,))]


def em_ordem(texto, trechos):
    pos = [texto.index(t) for t in trechos]
    return pos == sorted(pos)


# ---------- o cartão ----------
def test_cartao_do_alexei_separa_multa_e_juros(con_temp, http):
    cid = alexei(con_temp)
    svg = http.get(f"/clientes/{cid}/cobranca/cartao.svg").text.split("Aponte a câmera", 1)[1]   # as linhas, depois do texto e do QR
    linhas = ["Mensalidade", "R$ 2.042,50", "Crédito descontado", "− R$ 612,75", "Multa (2%)", "R$ 28,60",
              "Juros (1 dia de atraso)", "R$ 0,48", "Total atualizado", "R$ 1.458,83", "Vencimento", main.data_br(dia(-1))]
    assert em_ordem(svg, linhas)   # 2.042,50 − 612,75 + 28,60 + 0,48 = 1.458,83
    assert f"Vale só hoje, {HOJE:%d/%m}, até 23:59" in svg and "Amanhã os juros mudam" in svg


def test_cartao_antes_do_vencimento_vale_ate_23h59_do_dia(con_temp, http):
    pix_completo(con_temp)
    cid = cliente(con_temp, "Ana", dia(2), inicio=dia(-3))
    svg = http.get(f"/clientes/{cid}/cobranca/cartao.svg").text
    assert f"Pague até 23:59 de {main.data_br(dia(2))}" in svg and "Depois do vencimento entram multa e juros" in svg
    assert "R$ 400,00" in svg and "Multa" not in svg and "Juros" not in svg and "Total atualizado" not in svg


def test_cartao_de_dois_meses_soma_as_mensalidades(con_temp, http):
    pix_completo(con_temp)
    cid = cliente(con_temp, "Bia", dia(-35))
    ca = main.cobranca_atual(con_temp, con_temp.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone(),
                             main.wa_contexto(con_temp, con_temp.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone()))
    assert ca["cob"]["meses"] == 2
    svg = http.get(f"/clientes/{cid}/cobranca/cartao.svg").text
    assert "Mensalidades (2)" in svg and "R$ 800,00" in svg and main.moeda(ca["cob"]["total"]) in svg


# ---------- pagou o Pix antigo depois do vencimento ----------
def test_pix_antigo_pago_depois_do_vencimento_lanca_a_diferenca(con_temp, http):
    cid = alexei(con_temp)
    destino = paga(http, cid, 1429.75)   # o valor sem multa e juros
    assert "Pagou depois do vencimento: faltaram R$ 29,08 de multa e juros. Lancei a receber" in destino
    [m] = multas(con_temp)
    pagamento = con_temp.execute("SELECT id FROM lancamentos WHERE cliente_id=? AND pago_em IS NOT NULL", (cid,)).fetchone()[0]
    assert (m["valor"], m["pago_em"], m["cliente_id"], m["origem"], m["contraparte"]) == (29.08, None, None, f"MULTA:{pagamento}", "Alexei")
    # a renovação andou e a diferença não é mensalidade (nem aparece para "ligar ao aluno")
    assert alunos.estado_aluno(con_temp, cid)["situacao"] != "cobrar"
    [linha] = [x for x in financeiro.mensalidades(con_temp, HOJE.isoformat()[:7]) if x["id"] == cid]
    assert linha["recebido"] == 1429.75 and not linha["abertos"]
    assert not financeiro.entradas_sem_aluno(con_temp, HOJE.isoformat()[:7])
    # o alerta e a ficha: cobrar a diferença (o mesmo botão-cartão), recebi, dispensar
    [a] = [x for x in main.alertas(con_temp) if "multa e juros" in x["texto"]]
    assert a["texto"] == f"Alexei: faltou R$ 29,08 de multa e juros (Pix de R$ 1.429,75 em {HOJE:%d/%m}, depois do vencimento)"
    assert a["botao"] == "Cobrar diferença R$ 29,08" and a["cartao"]["svg"] == f"/clientes/{cid}/diferenca/cartao.svg"
    assert [x["rotulo"] for x in a["acoes"][1:]] == ["Recebi", "Dispensar"]
    for url in ("/", f"/clientes/{cid}"):
        pg = http.get(url).text
        assert (f'<form method="post" action="/clientes/{cid}/wa/cobranca_diferenca" target="_blank" class="inline" '
                f'data-cartao="/clientes/{cid}/diferenca/cartao.svg"') in pg, url
        assert '<button type="submit" class="claro pequeno">Cobrar diferença R$ 29,08</button>' in pg, url
        assert f'action="/financeiro/lancamento/{m["id"]}/baixa"' in pg and f'action="/financeiro/lancamento/{m["id"]}/excluir"' in pg, url
    assert 'id="diferenca"' in http.get(f"/clientes/{cid}").text
    # o cartão e o WhatsApp levam o Pix de R$ 29,08
    svg = http.get(f"/clientes/{cid}/diferenca/cartao.svg").text
    assert "Recebi seu Pix de" in svg and "Falta pagar" in svg and "R$ 29,08" in svg   # o texto quebra em linhas de 36 letras
    assert f"Pix de R$ 1.429,75 em {HOJE:%d/%m}: faltou" in svg
    r = http.post(f"/clientes/{cid}/wa/cobranca_diferenca", follow_redirects=False)
    assert unquote(r.headers["location"]).startswith("https://wa.me/5511999990000?text=000201") and "540529.08" in r.headers["location"]
    assert con_temp.execute("SELECT 1 FROM cliente_eventos WHERE cliente_id=? AND tipo='mensagem' AND descricao LIKE '%diferença%'",
                            (cid,)).fetchone()


def test_recebi_e_dispensar_tiram_a_diferenca(con_temp, http):
    cid = alexei(con_temp)
    paga(http, cid, 1429.75)
    [m] = multas(con_temp)
    http.post(f"/financeiro/lancamento/{m['id']}/baixa", data={"voltar": f"/clientes/{cid}"})
    assert not financeiro.diferencas(con_temp) and not [x for x in main.alertas(con_temp) if "multa e juros" in x["texto"]]
    assert con_temp.execute("SELECT pago_em FROM lancamentos WHERE id=?", (m["id"],)).fetchone()[0] == HOJE.isoformat()
    # o que entrou de multa não renova nada nem gasta crédito
    assert alunos.estado_aluno(con_temp, cid)["situacao"] != "cobrar"
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET pago_em=NULL WHERE id=?", (m["id"],))
    assert financeiro.diferencas(con_temp)
    r = http.post(f"/financeiro/lancamento/{m['id']}/excluir", data={"volta": f"/clientes/{cid}"}, follow_redirects=False)
    assert r.headers["location"].startswith(f"/clientes/{cid}")
    assert not financeiro.diferencas(con_temp)


def test_caixa_desmarcada_so_avisa(con_temp, http):
    cid = alexei(con_temp)
    destino = paga(http, cid, 1429.75, diferenca=False)
    assert "Atenção: pagou depois do vencimento e faltaram R$ 29,08 de multa e juros." in destino
    assert not multas(con_temp)


def test_pago_no_prazo_e_lancado_depois_nao_avisa(con_temp, http):
    cid = alexei(con_temp)   # venceu ontem
    destino = paga(http, cid, 1429.75, pago_em=dia(-2))   # caiu antes do vencimento: o valor sem multa estava certo
    assert "multa e juros" not in destino and not multas(con_temp)


def test_total_pago_ou_pagamento_menor_que_a_mensalidade_nao_vira_diferenca(con_temp, http):
    cid = alexei(con_temp)
    assert "multa e juros" not in paga(http, cid, 1458.83) and not multas(con_temp)   # pagou o total: nada falta
    pix_completo(con_temp)
    outro = cliente(con_temp, "Caio", dia(-3))
    assert "multa e juros" not in paga(http, outro, 300) and not multas(con_temp)   # faltou mensalidade, não só multa


def test_dialogo_recebe_os_encargos(con_temp):
    cid = alexei(con_temp)
    [pagar] = [x for x in alunos.estado_aluno(con_temp, cid)["acoes"] if x.get("dialogo") == "dlg-pgto"]
    assert pagar["dados"]["valor"] == "1458,83" and pagar["dados"]["encargos"] == "29,08"
