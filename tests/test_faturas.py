"""Faturas de cartão em PDF (Inter, Itaú): leitura, categoria, total, limite, pagamento no extrato, anti-duplicação e tela.
Dados sintéticos no formato do texto real de cada banco."""
import json
import re
from html import unescape

import pytest
from fastapi.testclient import TestClient

from app import db, extrato, faturas, main, relogio

INTER = """Resumo da fatura
Total da sua fatura
R$ 300,00
Limite de crédito total
R$ 1.000,00
Data de Vencimento
25/11/2026
Despesas do mês R$ 300,00
Fatura atual R$ 300,00
TESTE DA SILVA
5555****1111 25/11/2026 R$ 300,00
Despesas da fatura
CARTÃO 5555****1111
Data Movimentação Beneficiário Valor
26 de out. 2026 PAGAMENTO ON LINE - + R$ 250,00
18 de nov. 2026 IOF - R$ 2,00
Total CARTÃO 5555****1111 R$ 2,00
CARTÃO 5555****2222
Data Movimentação Beneficiário Valor
20 de jul. 2026 LOJA ROUPA X (Parcela 04 de 10) - R$ 50,00
27 de out. 2026 NETFLIX.COM - R$ 40,00
31 de out. 2026 ANTHROPIC
Valor e símbolo da moeda de origem: 5,00 USD
Cotação do dólar americano: R$ 5,6000
TESTE DA SILVA
5555****1111 25/11/2026 R$ 300,00
- R$ 28,00
04 de nov. 2026 PIX CRED A VISTA FULANO R$ 100,00
04 de nov. 2026 JUROS PIX CREDITO - R$ 10,00
10 de nov. 2026 IFD*RESTAURANTE Y (Parcela 01 de 02) - R$ 30,00
11 de nov. 2026 IOF INTERNACIONAL - R$ 1,00
11 de nov. 2026 IOF INTERNACIONAL - R$ 1,00
12 de nov. 2026 LOJA Z - R$ 38,00
Total CARTÃO 5555****2222 R$ 298,00
Limite de crédito total:
R$ 1.000,00
Utilizado:
R$ 630,00
Disponível:
R$ 370,00
Pix no crédito
Utilizado:
R$ 100,00
Disponível:
R$ 900,00
Próxima fatura
LOJA ROUPA X (Parcela 05 de
10) R$ 50,00
"""

ITAU = """Resumo da fatura em R$
Total da fatura anterior 500,00
Pagamento efetuado em 04/11/2026 -500,00
Saldo financiado 0,00
Encargos (Financiamento + moratório) 12,00
Lançamentos atuais 330,00
Total desta fatura 342,00
Limite total de crédito:
R$ 2.000,00
Titular TESTE DA SILVA
Cartão 5000.XXXX.XXXX.4444
Postagem:  21/11/2026
Vencimento: 28/11/2026
Emissão: 21/11/2026
Banco Itaú S.A.
P
L
Pagamentos efetuados
DATA VALOR EM R$
04/11 PAGAMENTO -500,00
Total dos pagamentos -500,00
Lançamentos: compras e saques
TESTE D SILVA
DATA ESTABELECIMENTO VALOR EM R$
03/09 EBN*CANVA0000X 03/12 30,00
ELETRONICS  CURITIBA
27/12 LOJA ANTIGA 100,00
outros  CAMPO GRANDE
Lançamentos no cartão 130,00
Lançamentos: produtos e serviços
DATA PRODUTOS/SERVIÇOS VALOR EM R$
06/01 PARCELA DE REF 11/11 200,00
Principal (R$ 180,00) + Juros (R$ 20,00)
Lançamentos produtos e serviços 200,00
Total dos lançamentos atuais 330,00
Compras parceladas - próximas faturas
DATA ESTABELECIMENTO VALOR EM R$
03/09 EBN*CANVA0000X 04/12 30,00
Próxima fatura 30,00
Total para próximas faturas 270,00
Limites de crédito Valor em R$
Limite total de crédito 2.000,00
Limite disponível 1.388,00
E
Limite total utilizado 612,00
Encargos cobrados nesta fatura
Juros do rotativo 15,99 % 10,00
IOF de financiamento (0,38 % + 0,00820 % a.d.) 2,00
Total de encargos em R$ 12,00
"""


def _pdf(texto: str) -> bytes:
    """PDF mínimo com o texto (Helvetica, uma linha por linha do texto), como o app do banco exporta: texto, não foto."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    linhas = texto.splitlines()
    paginas = [linhas[i:i + 60] for i in range(0, len(linhas), 60)] or [[]]
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for pag in paginas:
        corpo = "BT /F1 9 Tf 11 TL 30 810 Td " + " ".join(f"({esc(l)}) Tj T*" for l in pag) + " ET"
        stream = corpo.encode("cp1252")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
                    % len(objs))
        kids.append(len(objs))
    objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(tmp_path / "crm.db")
    c = db.conectar(tmp_path / "crm.db")
    yield c
    c.close()


def _tudo(prev):
    """As faturas da prévia como a revisão devolve (categoria sugerida em cada compra) e os pagamentos achados para marcar."""
    marcar = {p["lancamento"]["id"] for f in prev["faturas"] for p in f["pagamentos"] if p["lancamento"]}
    return prev["faturas"], marcar


def test_le_inter_compras_parcelas_dolar_e_pagamento():
    f = faturas.ler_texto(INTER)
    assert (f["conta"], f["vencimento"], f["total"], f["esperado"]) == ("Cartão Inter", "2026-11-25", 300.0, 300.0)
    assert f["pagamentos"] == [{"data": "2026-10-26", "valor": 250.0, "descricao": "PAGAMENTO ON LINE"}]   # crédito não é compra
    c = {x["descricao"]: x for x in f["compras"]}
    assert len(f["compras"]) == 10 and round(sum(x["valor"] for x in f["compras"]), 2) == 300.0
    assert (c["LOJA ROUPA X"]["parcela_num"], c["LOJA ROUPA X"]["parcela_total"], c["LOJA ROUPA X"]["cartao"]) == (4, 10, "2222")
    assert c["IOF"]["cartao"] == "1111" and c["IOF"]["data"] == "2026-11-18"
    # compra em dólar em várias linhas, cortada pelo rodapé da página: o valor é o da linha "- R$" e a cotação vai para a nota
    assert c["ANTHROPIC"]["valor"] == 28.0 and "5,00 USD" in c["ANTHROPIC"]["nota"]
    assert c["PIX CRED A VISTA FULANO"]["valor"] == 100.0
    iofs = [x["chave"] for x in f["compras"] if x["descricao"] == "IOF INTERNACIONAL"]
    assert len(set(iofs)) == 2   # dois IOF iguais no mesmo dia são duas compras
    lim = faturas.conferir_limite(f)
    assert (f["limite_total"], f["limite_usado"], f["limite_disponivel"]) == (1000.0, 630.0, 370.0)
    assert lim["usado_crm"] == 630.0 and lim["bate"] and not lim["estourado"]   # 300 + 50×6 + 30×1


def test_le_itau_sem_ano_ramo_parcelamento_e_encargos():
    f = faturas.ler_texto(ITAU)
    assert (f["conta"], f["vencimento"], f["fechamento"], f["total"]) == ("Cartão Itaú", "2026-11-28", "2026-11-21", 342.0)
    assert f["pagamentos"] == [{"data": "2026-11-04", "valor": 500.0, "descricao": "PAGAMENTO"}]
    c = {x["descricao"]: x for x in f["compras"]}
    assert set(c) == {"EBN*CANVA0000X", "LOJA ANTIGA", "PARCELA DE REF", "Juros do rotativo", "IOF de financiamento"}
    assert (c["EBN*CANVA0000X"]["data"], c["EBN*CANVA0000X"]["parcela_num"], c["EBN*CANVA0000X"]["ramo"]) == ("2026-09-03", 3, "ELETRONICS")
    assert c["LOJA ANTIGA"]["data"] == "2025-12-27"   # dezembro depois do fechamento de novembro: ano anterior
    assert c["PARCELA DE REF"]["nota"].startswith("Principal") and c["Juros do rotativo"]["data"] == "2026-11-21"
    assert all(x["cartao"] == "4444" for x in f["compras"])
    lim = faturas.conferir_limite(f)
    assert lim["usado_crm"] == 612.0 and lim["bate"] and lim["diferenca"] == 0


def test_ano_da_compra_parcelada_que_atravessa_o_ano():
    assert faturas._ano("03/09", "2026-11-21", 3) == "2026-09-03"
    assert faturas._ano("03/09", "2026-11-21", 15) == "2025-09-03"   # parcela 15: a compra tem mais de um ano
    assert faturas._ano("27/12", "2026-11-21") == "2025-12-27"
    assert faturas._ano("29/02", "2025-03-21", 13) == "2024-02-29"   # dia que só existe em ano bissexto
    f = faturas.ler_texto(ITAU.replace("27/12 LOJA ANTIGA 100,00", "29/02 LOJA ANTIGA 05/18 100,00"))
    assert next(c for c in f["compras"] if c["descricao"] == "LOJA ANTIGA")["data"] == "2024-02-29"


def test_parcela_do_inter_numa_linha_do_meio():
    f = faturas.ler_texto(INTER.replace("20 de jul. 2026 LOJA ROUPA X (Parcela 04 de 10) - R$ 50,00",
                                        "20 de jul. 2026 LOJA ROUPA X\n(Parcela 04 de 10)\n- R$ 50,00"))
    c = next(x for x in f["compras"] if x["descricao"] == "LOJA ROUPA X")
    assert (c["parcela_num"], c["parcela_total"], c["nota"]) == (4, 10, None)
    assert faturas.conferir_limite(f)["usado_crm"] == 630.0


def test_categoria_sugerida_por_palavra():
    validas = db.LISTAS_INICIAIS[faturas.LISTA]
    cat = {d: faturas.categoria(d, r, [], validas)[0] for d, r in [
        ("IFD*LIBERATO BAR REST", None), ("NETFLIX.COM", None), ("EBN*CANVA1234X", "ELETRONICS"), ("JUROS PIX CREDITO", None),
        ("PIX CRED A VISTA FULANO", None), ("OPA*OPCONVENIENCIA DA", None), ("MERCADOLIVRE*M", "outros"), ("PARCELA DE REF", None),
        ("IOF INTERNACIONAL", None), ("LOJA DESCONHECIDA", None), ("BARBEARIA DO ZE", None)]}
    assert cat == {"IFD*LIBERATO BAR REST": "Delivery", "NETFLIX.COM": "Assinaturas", "EBN*CANVA1234X": "Ferramentas de trabalho",
                   "JUROS PIX CREDITO": "Juros e tarifas do cartão", "PIX CRED A VISTA FULANO": "Pix no crédito",
                   "OPA*OPCONVENIENCIA DA": "Mercado", "MERCADOLIVRE*M": "Compras", "PARCELA DE REF": "Parcelamento de fatura",
                   "IOF INTERNACIONAL": "Juros e tarifas do cartão", "LOJA DESCONHECIDA": "Outros", "BARBEARIA DO ZE": "Outros"}


def test_arquivo_estranho_e_recusado_com_motivo():
    with pytest.raises(faturas.ArquivoInvalido, match="não é um PDF"):
        faturas.ler_arquivo("f.png", b"\x89PNG....")
    with pytest.raises(faturas.ArquivoInvalido, match="abrir"):
        faturas.ler_arquivo("f.pdf", b"%PDF-1.4 quebrado")
    with pytest.raises(faturas.ArquivoInvalido, match="não reconheci"):
        faturas.ler_arquivo("f.pdf", _pdf("Extrato de outro banco\nnada aqui"))
    with pytest.raises(faturas.ArquivoInvalido, match="vencimento"):
        faturas.ler_texto(INTER.replace("Data de Vencimento\n25/11/2026", ""))


def test_le_o_pdf_de_verdade_com_acento():
    f = faturas.ler_arquivo("fatura.pdf", _pdf(ITAU))
    assert f["total"] == 342.0 and len(f["compras"]) == 5 and f["arquivo"] == "fatura.pdf"


def test_salvar_e_reimportar_nao_duplica_e_soma_por_categoria(con):
    prev = faturas.previa(con, [("inter.pdf", _pdf(INTER)), ("itau.pdf", _pdf(ITAU))])
    assert not prev["erros"] and [f["confere"] for f in prev["faturas"]] == [True, True]
    r = faturas.salvar(con, *_tudo(prev))
    assert (r["faturas"], r["compras"], r["existentes"]) == (2, 15, 0)
    prev2 = faturas.previa(con, [("inter.pdf", _pdf(INTER))])
    assert prev2["faturas"][0]["importada_em"] and prev2["faturas"][0]["novas"] == 0
    r2 = faturas.salvar(con, *_tudo(prev2))
    assert (r2["faturas"], r2["atualizadas"], r2["compras"], r2["existentes"]) == (0, 1, 0, 10)
    assert con.execute("SELECT COUNT(*) FROM cartao_compras").fetchone()[0] == 15
    assert con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 0   # compra do cartão não é lançamento: não conta duas vezes
    tab = faturas.por_categoria(con, faturas.meses(con))
    assert tab["totais"] == {"2026-11": 642.0}
    por = {l["categoria"]: l["total"] for l in tab["linhas"]}
    assert por["Juros e tarifas do cartão"] == 26.0 and por["Pix no crédito"] == 100.0 and por["Parcelamento de fatura"] == 200.0


def test_categoria_corrigida_vira_regra_para_a_proxima(con):
    prev = faturas.previa(con, [("inter.pdf", _pdf(INTER))])
    f = prev["faturas"][0]
    loja = next(c for c in f["compras"] if c["descricao"] == "LOJA Z")
    assert loja["categoria"] == "Outros"
    loja["categoria"] = "Lazer"
    assert faturas.salvar(con, *_tudo(prev))["regras"] == 1
    outra = faturas.previa(con, [("inter.pdf", _pdf(INTER.replace("25/11/2026", "25/12/2026")))])["faturas"][0]
    assert next(c for c in outra["compras"] if c["descricao"] == "LOJA Z")["categoria"] == "Lazer"


def test_pagamento_no_extrato_vira_fatura_e_extrato_seguinte_ja_sugere(con):
    with con:
        lid = con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, conta)
                             VALUES ('PF', 'saida', '2026-10-27', '2026-10-27', 250, 'Outros', 'Inter')""").lastrowid
        con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, conta)
                       VALUES ('PF', 'saida', '2026-10-27', '2026-10-27', 250, 'Outros', 'Cartão Inter')""")   # do cartão: não é o pagamento
    prev = faturas.previa(con, [("inter.pdf", _pdf(INTER))])
    assert prev["faturas"][0]["pagamentos"][0]["lancamento"]["id"] == lid
    assert faturas.salvar(con, *_tudo(prev))["pagamentos"] == 1
    assert con.execute("SELECT categoria FROM lancamentos WHERE id=?", (lid,)).fetchone()[0] == "Fatura"
    # a fatura importada: o pagamento dela no próximo extrato já vem como "Fatura"
    arq = {"conta": "Inter", "formato": "OFX", "movimentos": [
        {"data": "2026-11-24", "valor": -300.0, "descricao": "Pagamento efetuado", "contraparte": None, "chave": "x1"},
        {"data": "2026-11-24", "valor": -301.0, "descricao": "Pagamento efetuado", "contraparte": None, "chave": "x2"}]}
    assert [l["categoria"] for l in extrato.interpretar(con, arq)] == ["Fatura", "Outros"]


def test_limite_diferente_ou_estourado_avisa(con):
    texto = INTER.replace("Utilizado:\nR$ 630,00\nDisponível:\nR$ 370,00", "Utilizado:\nR$ 1.020,00\nDisponível:\nR$ -20,00")
    f = faturas.ler_texto(texto)
    lim = faturas.conferir_limite(f)
    assert lim["estourado"] and not lim["bate"] and lim["diferenca"] == -390.0
    faturas.salvar(con, [{**f, "arquivo": "x.pdf", "compras": [{**c, "categoria": "Outros", "categoria_sugerida": "Outros"}
                                                                  for c in f["compras"]]}], set())
    assert faturas.avisos(con) == ["Cartão Inter: limite estourado em R$ 20,00 na última fatura"]
    assert faturas.cartoes(con)[0]["usado_crm"] == 630.0


@pytest.fixture
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(relogio, "hoje", lambda: __import__("datetime").date(2026, 11, 25))
    db.iniciar_banco()
    return TestClient(main.app, base_url="http://localhost")


def _formulario(html: str) -> dict:
    """Os campos que o navegador enviaria da revisão (hidden + selects com a opção escolhida + checkbox marcado)."""
    campos = {}
    for nome, valor in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', html):
        campos[nome] = unescape(valor)
    for nome, corpo in re.findall(r'<select name="([^"]+)"[^>]*>(.*?)</select>', html, re.S):
        sel = re.search(r"<option selected>([^<]*)", corpo) or re.search(r"<option\s*>([^<]*)", corpo)
        campos[nome] = unescape(sel.group(1))
    for nome in re.findall(r'<input type="checkbox" name="([^"]+)" value="1" checked>', html):
        campos[nome] = "1"
    return campos


def test_tela_importar_revisar_salvar_e_ver_por_categoria(http):
    assert http.get("/financeiro/cartoes").status_code == 200
    r = http.post("/financeiro/cartoes", files=[("arquivos", ("inter.pdf", _pdf(INTER), "application/pdf"))])
    assert r.status_code == 200 and "Revisar fatura" in r.text and "confere" in r.text
    campos = _formulario(r.text)
    nome = next(k for k in campos if k.startswith("categoria_0_"))
    campos[nome] = "Lazer"
    r2 = http.post("/financeiro/cartoes/salvar", data=campos, follow_redirects=False)
    assert r2.status_code == 303 and "erro" not in r2.headers["location"], r2.headers["location"]
    pagina = http.get(r2.headers["location"]).text
    assert "Gastos por categoria" in pagina and "Lazer" in pagina and "confere" in pagina
    http.post("/financeiro/cartoes/salvar", data=campos, follow_redirects=False)   # o mesmo envio de novo
    con = db.conectar()
    assert con.execute("SELECT COUNT(*) FROM cartao_compras").fetchone()[0] == 10
    assert con.execute("SELECT COUNT(*) FROM cartao_faturas").fetchone()[0] == 1
    con.close()


def test_tela_recusa_revisao_adulterada_e_arquivo_invalido(http):
    r = http.post("/financeiro/cartoes", files=[("arquivos", ("x.png", b"\x89PNG"))], follow_redirects=False)
    assert r.status_code == 303 and "erro" in r.headers["location"]
    r = http.post("/financeiro/cartoes", files=[("arquivos", ("itau.pdf", _pdf(ITAU), "application/pdf"))])
    campos = _formulario(r.text)
    dados = json.loads(campos["dados"])
    for mexer in (lambda d: d[0]["compras"][0].update(data="2027-01-01"),                 # compra no futuro
                  lambda d: d[0]["compras"][0].update(chave="Cartão Inter:2026-11-28:x"),  # chave de outro cartão
                  lambda d: d[0].update(conta="Inter"),                                    # conta que não é cartão
                  lambda d: d[0]["compras"][0].update(valor="1e999")):
        d = json.loads(campos["dados"])
        mexer(d)
        r = http.post("/financeiro/cartoes/salvar", data={**campos, "dados": json.dumps(d)}, follow_redirects=False)
        assert "erro" in r.headers["location"]
    r = http.post("/financeiro/cartoes/salvar", data={**campos, "categoria_0_0": "Inventada"}, follow_redirects=False)
    assert "erro" in r.headers["location"]
    con = db.conectar()
    assert con.execute("SELECT COUNT(*) FROM cartao_compras").fetchone()[0] == 0
    con.close()
    assert dados[0]["conta"] == "Cartão Itaú"
