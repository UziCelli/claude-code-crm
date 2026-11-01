"""Saúde financeira (app/marcadores.py): marcadores da PJ e da PF, cores, janela de 3 meses fechados, exclusões e telas."""
import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from app import assistente, db, financeiro, main, marcadores

HOJE = "2026-12-10"   # janela = set, out, nov/2026; fixo e variável só valem desde 2026-10 (out e nov)


@pytest.fixture
def con_temp(tmp_path, monkeypatch):
    db_path = tmp_path / "crm.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(db_path)
    con = db.conectar(db_path)
    yield con
    con.close()


@pytest.fixture
def cliente_http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    con = db.conectar()
    yield TestClient(main.app, base_url="http://localhost"), con
    con.close()


def lancar(con, tipo, valor, data, pago_em="igual", escopo="PJ", categoria="Outros", descricao=None, **extra):
    """pago_em='igual' paga no mesmo dia; None deixa em aberto."""
    pago_em = data if pago_em == "igual" else pago_em
    campos = {"escopo": escopo, "tipo": tipo, "data": data, "pago_em": pago_em, "valor": valor, "categoria": categoria,
              "descricao": descricao, **extra}
    with con:
        con.execute(f"INSERT INTO lancamentos ({', '.join(campos)}) VALUES ({', '.join('?' * len(campos))})", tuple(campos.values()))


def recorrencia(con, valor, descricao="Aluguel", categoria="Aluguel", escopo="PJ", fixo=1, dia=10):
    with con:
        return con.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio)
                              VALUES (?,?,?,?,?,?,'2026-01')""", (escopo, descricao, categoria, valor, dia, fixo)).lastrowid


def saldo(con, conta, valor, data=HOJE):
    with con:
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES (?,?,?)", (conta, valor, data))


def montar(con, meses=("2026-10", "2026-11"), receita=10000, variaveis=1000, fixo=3000, pf_entradas=9000, pf_saidas=6000, moradia=0,
           saldo_pj=20000, saldo_pf=5000, reserva=15000):
    """Empresa saudável (receita 10 mil, variáveis 1 mil, fixo 3 mil) e família com sobra, nos meses dados."""
    rid = recorrencia(con, fixo) if fixo else None
    for m in meses:
        if receita:
            lancar(con, "entrada", receita, f"{m}-05", categoria="Mensalidade")
        if variaveis:
            lancar(con, "saida", variaveis, f"{m}-06", categoria="Material")
        if fixo:
            financeiro.baixar_recorrencia(con, rid, m, fixo, f"{m}-10")
        if pf_entradas:
            lancar(con, "entrada", pf_entradas, f"{m}-05", escopo="PF", categoria="Salário")
        if pf_saidas:
            lancar(con, "saida", pf_saidas - moradia, f"{m}-07", escopo="PF", categoria="Alimentação")
        if moradia:
            lancar(con, "saida", moradia, f"{m}-08", escopo="PF", categoria="Moradia", descricao="Aluguel casa")
    if saldo_pj is not None:
        saldo(con, "Contabilizei Bank", saldo_pj)
    if saldo_pf is not None:
        saldo(con, "Inter", saldo_pf)
    if reserva:
        with con:
            con.execute("UPDATE parametros SET valor_texto='Reserva' WHERE grupo='conta_escopo' AND chave='Caixa'")
        saldo(con, "Caixa", reserva)


def marcadores_de(con, hoje=HOJE, **kw):
    ctx = marcadores.contexto(con, hoje, **kw)
    return ctx, marcadores.calcular(ctx)


def um(res, chave):
    return res["todos"][chave]


# ---------- cores: limites ----------
@pytest.mark.parametrize("chave, valor, cor", [
    ("margem_contribuicao", 0.70, "verde"), ("margem_contribuicao", 0.6999, "amarelo"), ("margem_contribuicao", 0.50, "amarelo"),
    ("margem_contribuicao", 0.4999, "vermelho"),
    ("margem_lucro", 0.40, "verde"), ("margem_lucro", 0.20, "amarelo"), ("margem_lucro", 0.1999, "vermelho"),
    ("margem_liquida", 0.15, "verde"), ("margem_liquida", 0.05, "amarelo"), ("margem_liquida", 0.0499, "vermelho"),
    ("pe_contabil", 1.20, "verde"), ("pe_contabil", 1.0, "amarelo"), ("pe_contabil", 0.99, "vermelho"),
    ("pe_economico", 1.0, "verde"), ("pe_economico", 0.90, "amarelo"), ("pe_economico", 0.89, "vermelho"),
    ("faturamento", 0.0, "verde"), ("faturamento", -0.10, "amarelo"), ("faturamento", -0.1001, "vermelho"),
    ("reserva", 3, "verde"), ("reserva", 1, "amarelo"), ("reserva", 0.9, "vermelho"),
    ("vencidas", 0.05, "verde"), ("vencidas", 0.15, "amarelo"), ("vencidas", 0.1501, "vermelho"),
    ("saidas", 1, "verde"), ("saidas", 2, "amarelo"), ("saidas", 2.01, "vermelho"),
    ("agenda", 1, "verde"), ("agenda", 0.70, "amarelo"), ("agenda", 0.69, "vermelho"),
    ("renda_pessoa", 3, "verde"), ("renda_pessoa", 2, "amarelo"), ("renda_pessoa", 1.99, "vermelho"),
    ("sobra", 0.20, "verde"), ("sobra", 0.10, "amarelo"), ("sobra", 0.0999, "vermelho"),
    ("contas_fixas", 0.50, "verde"), ("contas_fixas", 0.60, "amarelo"), ("contas_fixas", 0.6001, "vermelho"),
    ("moradia", 0.30, "verde"), ("moradia", 0.35, "amarelo"), ("moradia", 0.3501, "vermelho"),
    ("dividas", 0.15, "verde"), ("dividas", 0.30, "amarelo"), ("dividas", 0.3001, "vermelho"),
    ("reserva_pf", 6, "verde"), ("reserva_pf", 3, "amarelo"), ("reserva_pf", 2.9, "vermelho"),
])
def test_limites_de_cada_cor(chave, valor, cor):
    assert marcadores.cor_da_faixa(valor, marcadores.FAIXAS[chave]) == cor


# ---------- as contas ----------
def test_margens_com_numeros_conhecidos(con_temp):
    montar(con_temp)
    ctx, res = marcadores_de(con_temp)
    assert ctx["validos"] == ["2026-10", "2026-11"] and ctx["janela"] == ["2026-09", "2026-10", "2026-11"]
    # receita 10.000; variáveis 1.000; DAS 6% = 600; fixo 3.000; pró-labore 28% = 2.800; INSS 11% = 308
    mc, ml, mliq = um(res, "margem_contribuicao"), um(res, "margem_lucro"), um(res, "margem_liquida")
    assert (mc["valor"], mc["cor"]) == (0.84, "verde")
    assert (ml["valor"], ml["cor"]) == (0.54, "verde")
    assert (mliq["valor"], mliq["cor"]) == (0.2292, "verde")
    assert mc["texto"] == "84%" and "70%" in mc["frase"]   # a frase já diz o que é bom


def test_equilibrio_contabil_e_economico(con_temp):
    montar(con_temp)
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=4000 WHERE grupo='salario' AND chave='valor'")
    _, res = marcadores_de(con_temp)
    contabil, economico = um(res, "pe_contabil"), um(res, "pe_economico")
    assert contabil["valor"] == pytest.approx(3000 / 0.84, abs=0.01) and contabil["cor"] == "verde"          # 10.000 ≥ 1,2 × 3.571
    assert economico["valor"] == pytest.approx(7000 / 0.84, abs=0.01) and economico["cor"] == "verde"       # fixo + salário
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=1500 WHERE grupo='saude' AND chave='reserva_mensal_desejada'")
        con_temp.execute("UPDATE parametros SET valor=7000 WHERE grupo='salario' AND chave='valor'")
    _, res = marcadores_de(con_temp)
    economico = um(res, "pe_economico")
    assert economico["valor"] == pytest.approx((3000 + 7000 + 1500) / 0.84, abs=0.01)    # a reserva desejada entra
    assert economico["cor"] == "vermelho" and economico["dados"]["falta"] > 0


def test_retirada_e_emprestimo_nao_entram(con_temp):
    montar(con_temp)
    _, antes = marcadores_de(con_temp)
    lancar(con_temp, "saida", 2000, "2026-11-12", categoria=financeiro.RETIRADA)
    lancar(con_temp, "entrada", 5000, "2026-11-13", categoria=financeiro.EMPRESTIMO)
    lancar(con_temp, "saida", 800, "2026-11-14", categoria=financeiro.DEVOLUCAO)
    _, depois = marcadores_de(con_temp)
    for chave in ("faturamento", "margem_contribuicao", "margem_lucro", "pe_contabil"):
        assert um(antes, chave)["valor"] == um(depois, chave)["valor"], chave


def test_das_pago_nao_conta_duas_vezes(con_temp):
    montar(con_temp)
    _, antes = marcadores_de(con_temp)
    for m in ("2026-10", "2026-11"):
        lancar(con_temp, "saida", 600, f"{m}-20", categoria="Impostos/Taxas", descricao="DAS")   # o DAS que já foi pago
    _, depois = marcadores_de(con_temp)
    assert um(depois, "margem_contribuicao")["valor"] == um(antes, "margem_contribuicao")["valor"] == 0.84


def test_mes_corrente_nao_muda_nada(con_temp):
    montar(con_temp)
    _, antes = marcadores_de(con_temp)
    lancar(con_temp, "entrada", 90000, "2026-12-02", categoria="Mensalidade")     # mês pela metade: não conta
    lancar(con_temp, "saida", 70000, "2026-12-03", categoria="Material")
    lancar(con_temp, "saida", 9000, "2026-12-04", escopo="PF", categoria="Lazer")
    lancar(con_temp, "entrada", 800, "2026-12-04", escopo="PF", categoria="Extra")
    _, depois = marcadores_de(con_temp)
    resumo = lambda r: [(m["chave"], m["valor"], m["cor"], m["frase"]) for m in r["todos"].values() if m["chave"] not in ("caixa_pj", "caixa_pf")]  # noqa: E731
    assert resumo(antes) == resumo(depois)


def test_cinza_sem_dados_ou_antes_do_inicio(con_temp):
    # sem nada lançado
    _, res = marcadores_de(con_temp)
    for chave in ("faturamento", "margem_contribuicao", "pe_contabil", "caixa_pj", "caixa_pf", "renda_pessoa", "sobra", "moradia", "reserva_pf"):
        m = um(res, chave)
        assert m["cor"] == "cinza" and m["valor"] is None and m["acao"]["href"], chave
    assert res["nota"]["PF"]["texto"] == "sem dados ainda" and res["nota"]["PF"]["nota"] is None
    # em outubro: setembro e antes não separam fixo de variável: margens e equilíbrio ficam cinza, faturamento não
    con_temp.execute("DELETE FROM saldos")
    montar(con_temp, meses=("2026-08", "2026-09"), saldo_pj=None, saldo_pf=None, reserva=0)
    ctx, res = marcadores_de(con_temp, "2026-10-15")
    assert ctx["validos"] == []
    for chave in ("margem_contribuicao", "margem_lucro", "margem_liquida", "pe_contabil", "pe_economico", "contas_fixas"):
        assert um(res, chave)["cor"] == "cinza" and "fim do mês" in um(res, chave)["frase"], chave
    assert um(res, "faturamento")["cor"] != "cinza" and um(res, "sobra")["cor"] != "cinza"


def test_moradia_cinza_sem_categorias_e_verde_com_elas(con_temp):
    montar(con_temp)
    assert um(marcadores_de(con_temp)[1], "moradia")["cor"] == "cinza"
    con_temp.execute("DELETE FROM lancamentos WHERE escopo='PF'")
    montar_pf = dict(meses=("2026-10", "2026-11"), receita=0, variaveis=0, fixo=0, moradia=2400, saldo_pj=None, saldo_pf=None, reserva=0)
    montar(con_temp, **montar_pf)
    m = um(marcadores_de(con_temp)[1], "moradia")
    assert m["cor"] == "verde" and m["valor"] == pytest.approx(2400 / 9000, abs=0.001)    # 27% da renda


def test_pf_renda_por_pessoa_sobra_e_familia(con_temp):
    montar(con_temp)
    _, res = marcadores_de(con_temp)
    renda = um(res, "renda_pessoa")
    assert renda["dados"]["por_pessoa"] == 4500 and renda["cor"] == "amarelo"        # 4.500 ÷ 1.518 = 2,96 salários mínimos
    assert um(res, "sobra")["valor"] == pytest.approx(1 / 3, abs=0.001) and um(res, "sobra")["cor"] == "verde"
    assert um(res, "custo_vida")["dados"]["custo"] == 6000 and um(res, "custo_vida")["na_nota"] is False
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=3 WHERE grupo='familia' AND chave='pessoas'")
    renda = um(marcadores_de(con_temp)[1], "renda_pessoa")
    assert renda["dados"]["por_pessoa"] == 3000 and renda["cor"] == "vermelho"      # 3 pessoas: 3.000 ÷ 1.518 = 1,98 SM


def test_pf_dividas_proximos_30_dias(con_temp):
    montar(con_temp)
    assert um(marcadores_de(con_temp)[1], "dividas")["cor"] == "verde"               # sem parcelas
    lancar(con_temp, "saida", 1500, "2026-12-20", pago_em=None, escopo="PF", categoria="Dívidas", descricao="Financiamento moto",
           parcela_num=3, parcela_total=10)
    lancar(con_temp, "saida", 900, "2027-03-01", pago_em=None, escopo="PF", categoria="Dívidas", descricao="Fora dos 30 dias")
    m = um(marcadores_de(con_temp)[1], "dividas")
    assert m["dados"]["total"] == 1500 and m["cor"] == "amarelo"                     # 1.500 ÷ 9.000 = 16,7%


def test_reserva_pj_e_pf(con_temp):
    montar(con_temp, reserva=15000)
    _, res = marcadores_de(con_temp)
    assert um(res, "reserva_pj")["valor"] == 5.0 and um(res, "reserva_pj")["cor"] == "verde"     # 15.000 ÷ 3.000 fixos
    assert um(res, "reserva_pf")["valor"] == 2.5 and um(res, "reserva_pf")["cor"] == "vermelho"  # 15.000 ÷ 6.000 de vida
    saldo(con_temp, "Caixa", 40000, "2026-12-11")
    assert um(marcadores_de(con_temp, "2026-12-12")[1], "reserva_pf")["cor"] == "verde"         # 40.000 ÷ 6.000 = 6,7 meses


def test_caixa_negativo_fica_vermelho_e_sem_saldo_fica_cinza(con_temp):
    montar(con_temp, saldo_pj=None)
    assert um(marcadores_de(con_temp)[1], "caixa_pj")["cor"] == "cinza"
    saldo(con_temp, "Contabilizei Bank", 1000)        # o aluguel e o DAS dos próximos meses não cabem
    m = um(marcadores_de(con_temp)[1], "caixa_pj")
    assert m["cor"] == "vermelho" and m["dados"]["menor"] < 0 and "negativo" in m["frase"]
    assert m["acao"]["href"] == "/financeiro/previsao"


def test_faturamento_e_seta_de_tendencia(con_temp):
    montar(con_temp, meses=("2026-10", "2026-11"), receita=10000)
    montar(con_temp, meses=("2026-06", "2026-07", "2026-08"), receita=6000, variaveis=0, fixo=0, pf_entradas=0, pf_saidas=0, saldo_pj=None,
           saldo_pf=None, reserva=0)
    m = um(marcadores_de(con_temp)[1], "faturamento")
    assert m["tendencia"] == "↑" and m["tendencia_boa"] is True and m["cor"] == "verde"
    lancar(con_temp, "entrada", 50000, "2026-07-02", categoria="Mensalidade")     # os 3 meses antes foram muito melhores
    m = um(marcadores_de(con_temp)[1], "faturamento")
    assert m["tendencia"] == "↓" and m["tendencia_boa"] is False and m["cor"] == "vermelho"


def test_vencidas_e_saidas_e_agenda(con_temp):
    montar(con_temp)
    with con_temp:
        a = con_temp.execute("INSERT INTO clientes (nome, telefone, status, tipo_servico, plano, valor, data_renovacao)"
                             " VALUES ('Atrasada','11999990000','ativo','Mensalidade','Mensalidade 2x',2000,'2026-11-20')").lastrowid
        for i in range(2):   # saíram em novembro e continuam inativos
            cid = con_temp.execute("INSERT INTO clientes (nome, status, valor) VALUES (?, 'inativo', 300)", (f"Saiu {i}",)).lastrowid
            con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'status', '2026-11-15', "
                             "'Status alterado para inativo')", (cid,))
        voltou = con_temp.execute("INSERT INTO clientes (nome, status, valor) VALUES ('Voltou', 'ativo', 300)").lastrowid
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'status', '2026-11-16', "
                         "'Status alterado para inativo')", (voltou,))
    ctx, res = marcadores_de(con_temp)
    venc = um(res, "vencidas")
    assert ctx["ids_cobrar"] == [a] and venc["dados"]["n"] == 1 and venc["cor"] == "vermelho"      # 2.000 de 2.300 recorrentes
    assert venc["acao"] == {"rotulo": "Cobrar (1)", "href": f"/clientes?ids={a}&motivo=cobrar"}
    sai = um(res, "saidas")
    assert sai["dados"]["media"] == pytest.approx(2 / 3, abs=0.01) and sai["cor"] == "verde"      # quem voltou não conta
    assert sai["acao"]["href"].endswith("&motivo=reativar")
    ag = um(res, "agenda")
    assert ag["cor"] == "vermelho" and ag["valor"] == 8.7     # 2x por semana = 8,7 horas, longe da meta de 82


def test_faixas_podem_ser_trocadas_em_parametros(con_temp):
    montar(con_temp)
    assert um(marcadores_de(con_temp)[1], "margem_contribuicao")["cor"] == "verde"
    with con_temp:
        con_temp.execute("INSERT INTO parametros (grupo, chave, valor, ordem) VALUES ('saude_faixas', 'margem_contribuicao_verde', 0.9, 1)")
    m = um(marcadores_de(con_temp)[1], "margem_contribuicao")
    assert m["cor"] == "amarelo" and "90%" in m["frase"]


# ---------- formato: nenhum beco sem saída ----------
def test_todo_marcador_tem_frase_curta_e_botao(con_temp):
    montar(con_temp, moradia=2400)
    lancar(con_temp, "saida", 1500, "2026-12-20", pago_em=None, escopo="PF", categoria="Dívidas", parcela_num=1, parcela_total=4)
    for hoje in (HOJE, "2026-10-15"):
        _, res = marcadores_de(con_temp, hoje)
        achados = [m for e in ("PJ", "PF") for g in res[e] for m in g["marcadores"]]
        assert len(achados) == 19
        for m in achados:
            assert m["cor"] in ("verde", "amarelo", "vermelho", "cinza")
            assert 0 < len(m["frase"]) <= 90, (m["chave"], len(m["frase"]), m["frase"])
            assert m["acao"]["rotulo"] and m["acao"]["href"].startswith("/"), m["chave"]
            assert m["tendencia"] in ("↑", "↓", None)


def test_nota_conta_verde_amarelo_vermelho_e_ignora_cinza():
    n = marcadores.nota([{"cor": c, "na_nota": True} for c in ("verde", "verde", "amarelo", "vermelho", "cinza")]
                        + [{"cor": "verde", "na_nota": False}])
    assert (n["verdes"], n["total"], n["nota"], n["texto"]) == (2, 4, 62, "2 de 4 no verde")      # (100+100+50+0) ÷ 4
    assert marcadores.nota([{"cor": "cinza", "na_nota": True}])["nota"] is None


# ---------- consultas: não crescem com o número de alunos ----------
class Contador:
    def __init__(self, con):
        self.con, self.consultas = con, []

    def execute(self, sql, *args):
        self.consultas.append(sql)
        return self.con.execute(sql, *args)

    def __getattr__(self, nome):
        return getattr(self.con, nome)


def alunos_demais(con, n):
    with con:
        base = con.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, sessoes_mes, preco_base,
                              custo_operacional, mao_obra, custo_total) VALUES ('Mensalidade','CIA','PIX',0,2,8.66,900,500,300,800)""")
        for i in range(n):
            con.execute("""INSERT INTO clientes (nome, telefone, status, tipo_servico, plano, local, valor, data_renovacao, data_inicio)
                           VALUES (?, '11999990000', 'ativo', 'Mensalidade', 'Mensalidade 2x', 'CIA', 300, ?, '2026-01-10')""",
                        (f"Aluno {i}", f"2026-12-{(i % 28) + 1:02d}"))
    return base


def consultas(con_temp, n):
    alunos_demais(con_temp, n)
    c = Contador(con_temp)
    marcadores.calcular(marcadores.contexto(c, HOJE))
    return len(c.consultas)


def test_consultas_nao_crescem_com_o_numero_de_alunos(tmp_path, monkeypatch):
    contagens = []
    for n in (5, 30):
        monkeypatch.setattr(db, "DB_PATH", tmp_path / f"c{n}.db")
        monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
        db.iniciar_banco()
        con = db.conectar()
        montar(con)
        contagens.append(consultas(con, n))
        con.close()
    assert contagens[0] == contagens[1], contagens


# ---------- telas e assistente ----------
def test_tela_saude_financeira_mes_atual_e_passado(cliente_http):
    http, con = cliente_http
    hoje = dt.date.today()
    mes = hoje.strftime("%Y-%m")
    lancar(con, "entrada", 5000, f"{mes}-02", categoria="Mensalidade")
    for url in ("/financeiro/painel", f"/financeiro/painel?mes={mes}", "/financeiro/painel?mes=2025-03"):
        r = http.get(url)
        assert r.status_code == 200
        t = r.text
        assert "Saúde financeira" in t and "Painel financeiro" not in t and "olchão" not in t
        assert "Empresa (PJ)" in t and "Pessoal (PF)" in t and "no verde" in t or "sem dados ainda" in t
        assert "Reserva para meses fracos" in t and "Salário pago à PF" in t        # o que já existia segue embaixo
        assert 'id="reserva"' in t and 'id="o-que-fazer"' in t


def test_ancoras_dos_botoes_existem(cliente_http):
    http, _ = cliente_http
    assert 'id="recorrentes"' in http.get("/financeiro").text
    cfg = http.get("/configuracoes").text
    for grupo in ("salario", "colchao", "fiscal", "metas", "familia", "saude"):
        assert f'id="cfg-{grupo}"' in cfg, grupo


def test_botao_saude_financeira_no_lugar_do_painel_financeiro(cliente_http):
    http, _ = cliente_http
    for url in ("/financeiro", "/financeiro/previsao", "/financeiro/mensalidades"):
        t = http.get(url).text
        assert "Saúde financeira" in t and "Painel financeiro" not in t, url


def test_assistente_devolve_json_com_marcadores_e_sugestoes(con_temp):
    montar(con_temp)
    texto, erro = assistente.executar(con_temp, "saude_financeira", {})
    assert not erro
    dados = json.loads(texto)
    assert set(dados) >= {"hoje", "nota", "marcadores", "sugestoes"} and set(dados["marcadores"]) == {"PJ", "PF"}
    assert all({"nome", "cor", "frase", "tela"} <= set(m) for m in dados["marcadores"]["PJ"])
    texto, erro = assistente.executar(con_temp, "saude_financeira", {"escopo": "PF"})
    assert not erro and set(json.loads(texto)["marcadores"]) == {"PF"}
    assert "saude_financeira" in assistente.SISTEMA
    assert assistente.executar(con_temp, "saude_financeira", {"escopo": "XX"})[1] is True
