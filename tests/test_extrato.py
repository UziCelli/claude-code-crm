"""Importar extrato (Inter OFX, Contabilizei CSV): leitura, casamento, anti-duplicação, regras de categoria, saldo e tela. Dados sintéticos."""
import json
import re
from html import unescape

import pytest
from fastapi.testclient import TestClient

from app import db, extrato, main, relogio

def _trn(tipo, data, valor, fitid, memo, nome):
    return (f"<STMTTRN>\n<TRNTYPE>{tipo}</TRNTYPE>\n<DTPOSTED>{data}</DTPOSTED>\n<TRNAMT>{valor}</TRNAMT>\n<FITID>{fitid}</FITID>\n"
            f"<CHECKNUM>077</CHECKNUM>\n<REFNUM>077</REFNUM>\n<MEMO>{memo}</MEMO>\n<NAME>{nome}</NAME>\n</STMTTRN>\n")


# no formato real do Inter (SGML com fechamento, CHARSET 1252, FITID = data + 077 + sequência do dia); dados inventados
OFX = ("""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0</CODE>
<SEVERITY>INFO</SEVERITY>
</STATUS>
<DTSERVER>20261110</DTSERVER>
<LANGUAGE>POR</LANGUAGE>
<FI>
<ORG>Banco Intermedium S/A</ORG>
<FID>077</FID>
</FI>
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1001</TRNUID>
<STMTRS>
<CURDEF>BRL</CURDEF>
<BANKACCTFROM>
<BANKID>077</BANKID>
<BRANCHID>0001-9</BRANCHID>
<ACCTID>11111111</ACCTID>
<ACCTTYPE>CHECKING</ACCTTYPE>
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20261101</DTSTART>
<DTEND>20261110</DTEND>
""" + _trn("CREDIT", "20261103", "350.00", "202611030771", 'Pix recebido: "Cp :12345678-MARIA TESTE"', "Maria Teste")
    + _trn("PAYMENT", "20261105", "-89.90", "202611050771", 'Pagamento de Titulo: "ACADEMIA X"', "ACADEMIA X")
    + _trn("PAYMENT", "20261106", "-1200.00", "2026110607710", 'Pix enviado: "Cp :00000000-IMOBILIARIA LAR"', "Imobiliaria Lar")
    + """</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>1000.50</BALAMT>
<DTASOF>20261110</DTASOF>
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
""").encode("cp1252")

# no formato real do Contabilizei (vírgula, "R$ 1.006,82", "-" = vazio, saldo do dia repetido, linhas fora de ordem); dados inventados
CSV = ("\ufeffData,Categoria,Lançamento,Descrição,Entrada,Saída,Saldo do dia\n"
       '04/11/2026,Pessoa Jurídica,PIX,TARIFA PACOTE,-,"R$\xa012,90","R$\xa05.374,20"\n'
       '03/11/2026,Pessoa Jurídica,PIX,ALUNO TESTE,"R$\xa0400,00",-,"R$\xa05.400,00"\n'
       '04/11/2026,Pessoa Jurídica,PIX,TARIFA PACOTE,-,"R$\xa012,90","R$\xa05.374,20"\n').encode("utf-8")

HOJE = "2026-11-20"


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(tmp_path / "crm.db")
    c = db.conectar(tmp_path / "crm.db")
    yield c
    c.close()


def _confirmar(prev):
    """Aceita a sugestão de cada linha (as duvidosas também), como quem clica em Confirmar."""
    linhas, saldos = [], []
    for c in prev["contas"]:
        for l in c["linhas"]:
            linhas.append({**l, "acao": l["ref"] or l["acao"]})
        if c["saldo"] is not None:
            saldos.append({"conta": c["conta"], "saldo": c["saldo"], "data": c["saldo_data"]})
    return linhas, saldos


def test_le_ofx_do_inter():
    r = extrato.ler_arquivo("inter.ofx", OFX)
    assert r["conta"] == "Inter" and r["saldo"] == 1000.5 and r["saldo_data"] == "2026-11-10"
    assert [(m["data"], m["valor"], m["contraparte"]) for m in r["movimentos"]] == [
        ("2026-11-03", 350.0, "Maria Teste"), ("2026-11-05", -89.9, "ACADEMIA X"), ("2026-11-06", -1200.0, "Imobiliaria Lar")]
    assert r["movimentos"][0]["descricao"] == 'Pix recebido: "Cp :12345678-MARIA TESTE"'
    # a chave vem do conteúdo, não do FITID (que é a sequência do dia e muda se exportar no meio do dia)
    outro = extrato.ler_arquivo("i.ofx", OFX.replace(b"202611030771", b"202611030779"))
    assert [m["chave"] for m in outro["movimentos"]] == [m["chave"] for m in r["movimentos"]]


def test_nome_do_inter_sem_cidade_nem_codigo():
    assert extrato._nome_ofx("Super Market          Sao Paulo    Bra") == "Super Market"
    assert extrato._nome_ofx("São Paulo - Bilhete único - 01M7MT37GXQ05") == "São Paulo - Bilhete único"


def test_le_csv_do_contabilizei_com_saldo_e_repeticao_no_mesmo_dia():
    r = extrato.ler_arquivo("extrato.csv", CSV)
    assert r["conta"] == "Contabilizei Bank" and r["saldo"] == 5374.2 and r["saldo_data"] == "2026-11-04"
    chaves = [m["chave"] for m in r["movimentos"]]
    assert len(set(chaves)) == 3 and chaves[0].endswith(":1") and chaves[2].endswith(":2")   # duas tarifas iguais = duas linhas
    assert [(m["data"], m["valor"]) for m in r["movimentos"]] == [("2026-11-04", -12.9), ("2026-11-03", 400.0), ("2026-11-04", -12.9)]
    assert r["movimentos"][1]["descricao"] == "PIX: ALUNO TESTE" and r["movimentos"][1]["contraparte"] == "Aluno Teste"


def test_arquivo_estranho_e_recusado_com_motivo():
    with pytest.raises(extrato.ArquivoInvalido):
        extrato.ler_arquivo("foto.png", b"\x89PNG....")
    with pytest.raises(extrato.ArquivoInvalido, match="Inter"):
        extrato.ler_arquivo("x.ofx", OFX.replace(b"<BANKID>077", b"<BANKID>341").replace(b"Intermedium", b"Outro"))


def test_interpreta_forma_contraparte_aluno_e_categoria(con):
    with con:
        aid = con.execute("INSERT INTO clientes (nome) VALUES ('Aluno Teste')").lastrowid
    prev = extrato.previa(con, [("e.csv", CSV), ("i.ofx", OFX)], HOJE)
    pj, pf = prev["contas"]
    pix = pj["linhas"][1]
    assert (pix["tipo"], pix["escopo"], pix["forma"], pix["cliente_id"], pix["categoria"]) == (
        "entrada", "PJ", "PIX", aid, "Mensalidade (Aulas Presenciais)")
    assert pj["linhas"][0]["categoria"] == "Impostos/Taxas"
    assert pf["linhas"][1]["forma"] == "Boleto" and pf["linhas"][2]["contraparte"] == "Imobiliaria Lar"
    assert all(l["acao"] == "novo" and l["certo"] for l in pf["linhas"])


def test_reimportar_o_mesmo_periodo_nao_duplica_e_saldo_vira_foto(con):
    with con:
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES ('Inter', 999, '2026-11-10')")   # digitada: fica
    r = extrato.salvar(con, *_confirmar(extrato.previa(con, [("i.ofx", OFX), ("e.csv", CSV)], HOJE)))
    assert r["novos"] == 6 and r["saldos"] == 1
    n = con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0]
    prev = extrato.previa(con, [("i.ofx", OFX), ("e.csv", CSV)], HOJE)
    assert all(l["acao"] == "existe" and l["certo"] for c in prev["contas"] for l in c["linhas"])
    r = extrato.salvar(con, *_confirmar(prev))
    assert r["novos"] == 0 and r["saldos"] == 0
    assert con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == n
    fotos = [tuple(x) for x in con.execute("SELECT saldo, data FROM saldos WHERE conta='Inter' AND excluido_em IS NULL ORDER BY id")]
    assert fotos == [(999.0, "2026-11-10")]   # já tinha foto digitada no dia: ela fica, e o banco não cria outra no mesmo dia
    assert con.execute("SELECT pago_em FROM lancamentos WHERE origem LIKE 'OFX:Inter:2026-11-03:35000:%'").fetchone()[0] == "2026-11-03"


def test_casa_com_lancado_a_mao_conta_em_aberto_e_recorrente(con):
    with con:
        manual = con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, conta)
                                VALUES ('PF','entrada','2026-11-03','2026-11-03',350,'Outros','Inter')""").lastrowid
        aberto = con.execute("""INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, descricao)
                                VALUES ('PF','saida','2026-11-07',89.90,'Lazer','Academia')""").lastrowid
        rid = con.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio, conta)
                             VALUES ('PF','Aluguel','Moradia',1200,5,'2026-01','Inter')""").lastrowid
    linhas = extrato.previa(con, [("i.ofx", OFX)], HOJE)["contas"][0]["linhas"]
    assert [(l["acao"], l["ref"], l["certo"]) for l in linhas] == [
        ("existe", f"e:{manual}", True), ("pagar", f"l:{aberto}", True), ("pagar", f"r:{rid}:2026-11", True)]
    r = extrato.salvar(con, *_confirmar(extrato.previa(con, [("i.ofx", OFX)], HOJE)))
    assert (r["novos"], r["pagos"], r["existentes"]) == (0, 2, 1)
    assert con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 3   # nada em dobro
    assert con.execute("SELECT pago_em, conta FROM lancamentos WHERE id=?", (aberto,)).fetchone()[:] == ("2026-11-05", "Inter")
    assert con.execute("SELECT origem FROM lancamentos WHERE id=?", (manual,)).fetchone()[0].startswith("OFX:Inter:2026-11-03:35000:")
    assert con.execute("SELECT valor, pago_em FROM lancamentos WHERE recorrencia_id=? AND competencia='2026-11'", (rid,)).fetchone()[:] == (
        1200.0, "2026-11-06")


def test_duas_contas_iguais_em_aberto_pedem_decisao(con):
    with con:
        for d in ("2026-11-02", "2026-11-09"):
            con.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria) VALUES ('PF','saida',?,89.90,'Lazer')", (d,))
    l = extrato.previa(con, [("i.ofx", OFX)], HOJE)["contas"][0]["linhas"][1]
    assert l["acao"] == "pagar" and not l["certo"] and len([o for o in l["opcoes"] if o[0].startswith("l:")]) == 2


def test_categoria_corrigida_vira_regra_para_a_proxima(con):
    linhas, saldos = _confirmar(extrato.previa(con, [("i.ofx", OFX)], HOJE))
    linhas[2]["categoria"] = "Moradia"   # você corrigiu "Outros" -> "Moradia" no aluguel
    assert extrato.salvar(con, linhas, saldos)["regras"] == 1
    outro = OFX.replace(b"20261106", b"20261206")
    linha = extrato.previa(con, [("i.ofx", outro)], HOJE)["contas"][0]["linhas"][2]
    assert linha["acao"] == "novo" and linha["categoria"] == "Moradia"


def test_ignorar_nao_volta_como_novo(con):
    linhas, _ = _confirmar(extrato.previa(con, [("i.ofx", OFX)], HOJE))
    linhas[0]["acao"] = "ignorar"
    extrato.salvar(con, linhas, [])
    l = extrato.previa(con, [("i.ofx", OFX)], HOJE)["contas"][0]["linhas"][0]
    assert l["acao"] == "ignorar" and con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 2


def test_aviso_de_extrato_atrasado_so_depois_da_primeira_importacao(con):
    assert extrato.contas_atrasadas(con, HOJE) == []
    with con:
        con.execute("INSERT INTO importacoes (data, arquivo, resumo) VALUES ('2026-11-10 09:00:00', 'extrato:Inter', '{}')")
    assert extrato.contas_atrasadas(con, "2026-11-15") == [("Contabilizei Bank", None)]
    assert extrato.contas_atrasadas(con, "2026-11-20") == [("Inter", 10), ("Contabilizei Bank", None)]


# ---------- tela ----------
@pytest.fixture
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(relogio, "hoje", lambda: __import__("datetime").date(2026, 11, 20))
    db.iniciar_banco()
    return TestClient(main.app, base_url="http://localhost")


def _formulario(html: str) -> dict:
    """Os campos que o navegador enviaria da tela de revisão (hidden + selects com a opção escolhida + checkbox marcado)."""
    campos = {}
    for nome, valor in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', html):
        campos[nome] = unescape(valor)
    for nome, corpo in re.findall(r'<select name="([^"]+)"[^>]*>(.*?)</select>', html, re.S):
        sel = re.search(r'<option(?: value="([^"]*)")? selected>([^<]*)', corpo) or re.search(r'<option(?: value="([^"]*)")?\s*>([^<]*)', corpo)
        campos[nome] = unescape(sel.group(1) if sel.group(1) is not None else sel.group(2))
    for nome in re.findall(r'<input type="checkbox" name="([^"]+)" value="1" checked>', html):
        campos[nome] = "1"
    return campos


def test_tela_importar_revisar_e_salvar_sem_duplicar(http):
    assert http.get("/financeiro/extrato").status_code == 200
    r = http.post("/financeiro/extrato", files=[("arquivos", ("i.ofx", OFX)), ("arquivos", ("e.csv", CSV))])
    assert r.status_code == 200 and "Revisar extrato" in r.text and "1.000,50" in r.text
    campos = _formulario(r.text)
    r2 = http.post("/financeiro/extrato/salvar", data=campos, follow_redirects=False)
    assert r2.status_code == 303 and "erro" not in r2.headers["location"], r2.headers["location"]
    con = db.conectar()
    n = con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0]
    assert n == 6
    http.post("/financeiro/extrato/salvar", data=campos, follow_redirects=False)   # o mesmo envio de novo
    assert con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == n
    assert con.execute("SELECT COUNT(*) FROM saldos").fetchone()[0] == 2
    con.close()


def test_tela_recusa_revisao_adulterada_e_arquivo_invalido(http):
    r = http.post("/financeiro/extrato", files=[("arquivos", ("x.png", b"\x89PNG"))], follow_redirects=False)
    assert r.status_code == 303 and "erro" in r.headers["location"]
    r = http.post("/financeiro/extrato", files=[("arquivos", ("i.ofx", OFX))])
    campos = _formulario(r.text)
    r = http.post("/financeiro/extrato/salvar", data={**campos, "acao_0_0": ""}, follow_redirects=False)   # linha sem decisão
    assert "erro" in r.headers["location"]
    dados = json.loads(campos["dados"])
    dados[0][0]["data"] = "2027-01-01"   # futuro
    r = http.post("/financeiro/extrato/salvar", data={**campos, "dados": json.dumps(dados)}, follow_redirects=False)
    assert "erro" in r.headers["location"]
    dados[0][0]["data"], dados[0][0]["origem"] = "2026-11-03", "OFX:Contabilizei Bank:A1"   # chave de outra conta
    r = http.post("/financeiro/extrato/salvar", data={**campos, "dados": json.dumps(dados)}, follow_redirects=False)
    assert "erro" in r.headers["location"]
    con = db.conectar()
    assert con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 0
    con.close()


def test_entrada_que_parece_emprestimo_pede_decisao_e_depois_aprende(con):
    zippi = OFX.replace(b"MARIA TESTE", b"ZIPPI SOLUCOES DE CREDITO").replace(b"Maria Teste", b"Zippi Solucoes De Credito")
    l = extrato.previa(con, [("i.ofx", zippi)], HOJE)["contas"][0]["linhas"][0]
    assert l["emprestimo"] and not l["certo"]
    linhas, _ = _confirmar(extrato.previa(con, [("i.ofx", zippi)], HOJE))
    assert extrato.salvar(con, linhas, [])["regras"] == 1   # você confirmou "Outros": a próxima vem sem pedir
    l = extrato.previa(con, [("i.ofx", zippi.replace(b"20261103", b"20261108"))], HOJE)["contas"][0]["linhas"][0]
    assert l["acao"] == "novo" and l["certo"] and not l["emprestimo"]


def test_dois_arquivos_da_mesma_conta_nao_casam_com_o_mesmo_lancamento(con):
    with con:
        con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, conta)
                       VALUES ('PJ','entrada','2026-11-03','2026-11-03',400,'Outros','Contabilizei Bank')""")
    outro = CSV.replace("ALUNO TESTE".encode(), "OUTRA PESSOA".encode())
    prev = extrato.previa(con, [("a.csv", CSV), ("b.csv", outro)], HOJE)
    acoes = [l["ref"] or l["acao"] for c in prev["contas"] for l in c["linhas"] if l["valor"] == 400]
    assert acoes.count("e:1") == 1 and "novo" in acoes
    extrato.salvar(con, *_confirmar(prev))
    assert con.execute("SELECT COUNT(*) FROM lancamentos WHERE valor=400").fetchone()[0] == 2
    linha = _confirmar(extrato.previa(con, [("b.csv", outro.replace(b"03/11", b"02/11"))], HOJE))[0][1]
    with con:
        livre = con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, conta)
                               VALUES ('PJ','entrada','2026-11-02','2026-11-02',400,'Outros','Contabilizei Bank')""").lastrowid
    alvo = f"e:{livre}"
    dois = [{**linha, "acao": alvo}, {**linha, "origem": linha["origem"] + "x", "acao": alvo}]   # o mesmo lançamento para dois movimentos
    assert extrato.salvar(con, dois, [])["novos"] == 1   # o segundo é um movimento a mais


def test_pagamento_de_um_aluno_nao_quita_a_mensalidade_de_outro(con):
    with con:
        ana = con.execute("INSERT INTO clientes (nome) VALUES ('Ana Lima')").lastrowid
        bruna = con.execute("INSERT INTO clientes (nome) VALUES ('Bruna Costa')").lastrowid
        mens = con.execute("""INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, cliente_id)
                              VALUES ('PJ','entrada','2026-11-03',400,'Mensalidade (Aulas Presenciais)',?)""", (ana,)).lastrowid
    csv_bruna = CSV.replace("ALUNO TESTE".encode(), "BRUNA COSTA".encode())
    l = extrato.previa(con, [("b.csv", csv_bruna)], HOJE)["contas"][0]["linhas"][1]
    assert l["cliente_id"] == bruna and l["acao"] == "novo" and f"l:{mens}" not in [o[0] for o in l["opcoes"]]
    sem_nome = CSV.replace("ALUNO TESTE".encode(), "FULANO X".encode())
    l = extrato.previa(con, [("c.csv", sem_nome)], HOJE)["contas"][0]["linhas"][1]
    assert l["ref"] == f"l:{mens}" and not l["certo"]   # não sabe quem pagou: você decide


def test_reconhecer_lancado_a_mao_grava_o_aluno_confirmado(con):
    with con:
        ana = con.execute("INSERT INTO clientes (nome) VALUES ('Ana Lima')").lastrowid
        manual = con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria)
                                VALUES ('PJ','entrada','2026-11-03','2026-11-03',400,'Outros')""").lastrowid
    prev = extrato.previa(con, [("a.csv", CSV.replace("ALUNO TESTE".encode(), "ANA LIMA".encode()))], HOJE)
    assert prev["contas"][0]["linhas"][1]["ref"] == f"e:{manual}"
    extrato.salvar(con, *_confirmar(prev))
    assert con.execute("SELECT cliente_id FROM lancamentos WHERE id=?", (manual,)).fetchone()[0] == ana


def test_recorrente_de_outra_conta_nao_vem_como_certa(con):
    with con:
        rid = con.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio, conta)
                             VALUES ('PF','Aluguel','Moradia',1200,5,'2026-01','Itaú')""").lastrowid
    l = extrato.previa(con, [("i.ofx", OFX)], HOJE)["contas"][0]["linhas"][2]
    assert l["ref"] == f"r:{rid}:2026-11" and not l["certo"]


def test_lancamento_da_planilha_conciliado_nao_casa_de_novo(con):
    with con:
        con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, conta, origem)
                       VALUES ('PJ','entrada','2026-11-03','2026-11-03',400,'Outros','Contabilizei Bank','PJ:17')""")
    prev = extrato.previa(con, [("a.csv", CSV)], HOJE)
    assert prev["contas"][0]["linhas"][1]["ref"] == "e:1"
    extrato.salvar(con, *_confirmar(prev))
    assert con.execute("SELECT origem FROM lancamentos WHERE id=1").fetchone()[0] == "PJ:17"   # a origem da planilha fica
    again = extrato.previa(con, [("a.csv", CSV)], HOJE)["contas"][0]["linhas"][1]
    assert again["acao"] == "existe" and again["ref"] == "1"   # reconhece pela ligação guardada
    outro = extrato.previa(con, [("b.csv", CSV.replace("ALUNO TESTE".encode(), "OUTRA PESSOA".encode()))], HOJE)["contas"][0]["linhas"][1]
    assert outro["acao"] == "novo"   # o lançamento já conciliado não serve para outro movimento


def test_recorrente_paga_adiantada_no_fim_do_mes(con):
    with con:
        rid = con.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio)
                             VALUES ('PF','Aluguel','Moradia',1200,5,'2026-01')""").lastrowid
        con.execute("INSERT INTO recorrencia_pulos (recorrencia_id, competencia) VALUES (?, '2026-11')", (rid,))
    l = extrato.previa(con, [("i.ofx", OFX.replace(b"20261106", b"20261128"))], "2026-11-30")["contas"][0]["linhas"][2]
    assert l["ref"] == f"r:{rid}:2026-12"


def test_aluno_ligado_a_pagamento_existente_gasta_o_credito(con, monkeypatch):
    usados = []
    monkeypatch.setattr(extrato.financeiro, "usar_credito", lambda c, lid, *a, **k: usados.append(lid) or 0.0)
    with con:
        con.execute("INSERT INTO clientes (nome) VALUES ('Ana Lima')")
        manual = con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria)
                                VALUES ('PJ','entrada','2026-11-03','2026-11-03',400,'Outros')""").lastrowid
    extrato.salvar(con, *_confirmar(extrato.previa(con, [("a.csv", CSV.replace("ALUNO TESTE".encode(), "ANA LIMA".encode()))], HOJE)))
    assert manual in usados


def test_saldo_do_banco_diferente_do_digitado_no_mesmo_dia_nao_some_do_conferir(con):
    with con:
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES ('Inter', 500, '2026-11-01')")
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES ('Inter', 999, '2026-11-10')")
    antes = [c["conta"] for c in extrato.financeiro.conferencia_contas(con)]
    extrato.salvar(con, [], [{"conta": "Inter", "saldo": 1000.5, "data": "2026-11-10"}])
    assert [c["conta"] for c in extrato.financeiro.conferencia_contas(con)] == antes == ["Inter"]
