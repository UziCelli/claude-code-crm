"""Importar extrato (Inter OFX, Contabilizei CSV): leitura, casamento, anti-duplicação, regras de categoria, saldo e tela. Dados sintéticos."""
import json
import re
from html import unescape

import pytest
from fastapi.testclient import TestClient

from app import db, extrato, main, relogio

OFX = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
CHARSET:1252

<OFX>
<BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>BRL
<BANKACCTFROM><BANKID>0077<ACCTID>123456<ACCTTYPE>CHECKING</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20261101<DTEND>20261110
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261103<TRNAMT>350.00<FITID>A1<MEMO>PIX RECEBIDO - Cp :12345678-MARIA TESTE</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261105<TRNAMT>-89.90<FITID>A2<MEMO>Pagamento de boleto ACADEMIA X</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261106<TRNAMT>-1200.00<FITID>A3<MEMO>PIX ENVIADO - IMOBILIARIA LAR</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>1000.50<DTASOF>20261110</LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
""".encode("cp1252")

CSV = """Data;Descrição;Valor;Saldo
03/11/2026;Pix recebido de Aluno Teste;400,00;5.400,00
04/11/2026;Tarifa pacote;-12,90;5.387,10
04/11/2026;Tarifa pacote;-12,90;5.374,20
""".encode("utf-8")

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
    assert [(m["data"], m["valor"], m["chave"]) for m in r["movimentos"]] == [
        ("2026-11-03", 350.0, "A1"), ("2026-11-05", -89.9, "A2"), ("2026-11-06", -1200.0, "A3")]


def test_le_csv_do_contabilizei_com_saldo_e_repeticao_no_mesmo_dia():
    r = extrato.ler_arquivo("extrato.csv", CSV)
    assert r["conta"] == "Contabilizei Bank" and r["saldo"] == 5374.2 and r["saldo_data"] == "2026-11-04"
    chaves = [m["chave"] for m in r["movimentos"]]
    assert len(set(chaves)) == 3 and chaves[1].endswith(":1") and chaves[2].endswith(":2")   # duas tarifas iguais = duas linhas


def test_arquivo_estranho_e_recusado_com_motivo():
    with pytest.raises(extrato.ArquivoInvalido):
        extrato.ler_arquivo("foto.png", b"\x89PNG....")
    with pytest.raises(extrato.ArquivoInvalido, match="Inter"):
        extrato.ler_arquivo("x.ofx", OFX.replace(b"0077", b"0341"))


def test_interpreta_forma_contraparte_aluno_e_categoria(con):
    with con:
        aid = con.execute("INSERT INTO clientes (nome) VALUES ('Aluno Teste')").lastrowid
    prev = extrato.previa(con, [("e.csv", CSV), ("i.ofx", OFX)], HOJE)
    pj, pf = prev["contas"]
    pix = pj["linhas"][0]
    assert (pix["tipo"], pix["escopo"], pix["forma"], pix["cliente_id"], pix["categoria"]) == (
        "entrada", "PJ", "PIX", aid, "Mensalidade (Aulas Presenciais)")
    assert pj["linhas"][1]["categoria"] == "Impostos/Taxas"
    assert pf["linhas"][1]["forma"] == "Boleto" and pf["linhas"][2]["contraparte"] == "Imobiliaria Lar"
    assert all(l["acao"] == "novo" and l["certo"] for l in pf["linhas"])


def test_reimportar_o_mesmo_periodo_nao_duplica_e_saldo_vira_foto(con):
    with con:
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES ('Inter', 999, '2026-11-10')")   # digitada: fica
    r = extrato.salvar(con, *_confirmar(extrato.previa(con, [("i.ofx", OFX), ("e.csv", CSV)], HOJE)))
    assert r["novos"] == 6 and r["saldos"] == 2
    n = con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0]
    prev = extrato.previa(con, [("i.ofx", OFX), ("e.csv", CSV)], HOJE)
    assert all(l["acao"] == "existe" and l["certo"] for c in prev["contas"] for l in c["linhas"])
    r = extrato.salvar(con, *_confirmar(prev))
    assert r["novos"] == 0 and r["saldos"] == 0
    assert con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == n
    fotos = [tuple(x) for x in con.execute("SELECT saldo, data FROM saldos WHERE conta='Inter' AND excluido_em IS NULL ORDER BY id")]
    assert fotos == [(999.0, "2026-11-10"), (1000.5, "2026-11-10")]
    assert con.execute("SELECT pago_em FROM lancamentos WHERE origem='OFX:Inter:A1'").fetchone()[0] == "2026-11-03"


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
    assert con.execute("SELECT origem FROM lancamentos WHERE id=?", (manual,)).fetchone()[0] == "OFX:Inter:A1"
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
    outro = OFX.replace(b"<FITID>A3", b"<FITID>B9").replace(b"20261106", b"20261206")
    linha = extrato.previa(con, [("i.ofx", outro)], HOJE)["contas"][0]["linhas"][2]
    assert linha["acao"] == "novo" and linha["categoria"] == "Moradia"


def test_ignorar_nao_volta_como_novo(con):
    linhas, _ = _confirmar(extrato.previa(con, [("i.ofx", OFX)], HOJE))
    linhas[0]["acao"] = "ignorar"
    extrato.salvar(con, linhas, [])
    l = extrato.previa(con, [("i.ofx", OFX)], HOJE)["contas"][0]["linhas"][0]
    assert l["acao"] == "ignorar" and con.execute("SELECT COUNT(*) FROM lancamentos WHERE origem='OFX:Inter:A1'").fetchone()[0] == 0


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
