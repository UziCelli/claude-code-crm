"""PR 5 da auditoria financeira: painéis honestos (previsão pelo pior dia, formato de valor, CAC do mês, lucro/h, ficha, funil, checkpoint)."""
import datetime as dt
import re

import pytest
from fastapi.testclient import TestClient

from app import db, financeiro, main


@pytest.fixture
def con_temp(tmp_path, monkeypatch):
    db_path = tmp_path / "crm.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(db_path)
    con = db.conectar(db_path)
    yield con
    con.close()


def lancar(con, tipo, valor, data, pago_em=None, escopo="PJ", categoria="Outros", descricao=None):
    with con:
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao) VALUES (?,?,?,?,?,?,?)",
                    (escopo, tipo, data, pago_em, valor, categoria, descricao))


def sem_das(con):
    with con:
        con.execute("UPDATE parametros SET valor=0 WHERE grupo='imposto' AND chave='DAS'")


def base_pacote(con, qtd=8, preco=900, op=500, mo=300, total=800):
    with con:
        con.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, sessoes_mes, preco_base,
                       custo_operacional, mao_obra, custo_total) VALUES ('Pacote de Aulas','CIA','PIX',?,0,?,?,?,?,?)""",
                    (qtd, qtd, preco, op, mo, total))


def aluno(con, nome, valor, local="CIA", pessoas=1, canal=None, data_inicio=None):
    with con:
        return con.execute("""INSERT INTO clientes (nome, valor, tipo_servico, plano, local, pessoas, forma_pagamento, canal_origem, data_inicio)
                              VALUES (?,?, 'Pacote de Aulas', 'Pacote 8 aulas', ?, ?, 'PIX', ?, ?)""",
                           (nome, valor, local, pessoas, canal, data_inicio)).lastrowid


# ---------- formato de valor ----------
def test_moeda_negativo_num_formato_so():
    assert main.moeda(-169.4) == "−R$ 169,40"
    assert main.moeda(179.97) == "R$ 179,97"
    assert main.moeda(-0.001) == "R$ 0,00" and main.moeda(-0.0) == "R$ 0,00"
    assert main.moeda(None) == "—"
    assert main.moeda(-1234567.5) == "−R$ 1.234.567,50"


# ---------- previsão: pior dia ----------
def test_aperto_olha_o_pior_dia_e_nao_o_fim_da_semana(con_temp):
    """Saída de 1.500 no dia 18 e entrada de 1.500 no dia 21: o fim da semana fecha positivo, mas no dia 18 o saldo é negativo."""
    con = con_temp
    sem_das(con)
    financeiro.salvar_saldos(con, "2026-10-16", {"Inter": 500}, {"Inter": "PJ"})
    lancar(con, "saida", 1500, "2026-10-18")
    lancar(con, "entrada", 1500, "2026-10-21")
    p = financeiro.previsao(con, "2026-10-16")
    assert p["semanas"][0]["PJ"]["saldo"] == 500   # fim da semana: parece tranquilo
    assert p["aperto"]["PJ"] == {"inicio": "2026-10-18", "saldo": -1000}
    assert p["menor"]["PJ"] == -1000 and p["menor_dia"]["PJ"] == {"saldo": -1000, "data": "2026-10-18"}
    assert p["semanas"][0]["PJ"]["pior"] == {"saldo": -1000, "data": "2026-10-18"}
    assert p["semanas"][0]["negativo"] is True


def test_atrasado_conta_em_hoje_e_semana_sem_aperto_nao_tem_pior(con_temp):
    con = con_temp
    sem_das(con)
    financeiro.salvar_saldos(con, "2026-10-16", {"Inter": 300}, {"Inter": "PJ"})
    lancar(con, "saida", 400, "2026-10-05")   # atrasada
    p = financeiro.previsao(con, "2026-10-16")
    assert p["aperto"]["PJ"] == {"inicio": "2026-10-16", "saldo": -100}
    assert p["semanas"][1]["PJ"]["pior"] is None


def test_tela_previsao_mostra_etiqueta_atrasado_previsto_e_o_dia_do_aperto(cliente_http):
    http, con = cliente_http
    sem_das(con)
    financeiro.salvar_saldos(con, dt.date.today().isoformat(), {"Inter": 100}, {"Inter": "PJ"})
    ontem = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    lancar(con, "saida", 400, ontem, descricao="Conta velha")
    with con:
        con.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio)
                       VALUES ('PJ','Aluguel','Aluguel',50,28,1,?)""", (financeiro.somar_meses(dt.date.today().isoformat()[:7], 1),))
    t = http.get("/financeiro/previsao").text
    assert "Conta velha" in t and ">atrasado<" in t
    assert ">previsto<" in t
    assert "Nesse dia o saldo fica em" in t and "−R$ 300,00" in t


# ---------- alerta na virada do mês ----------
class _DataFixa(dt.date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 30)


def test_alerta_de_conta_olha_o_mes_seguinte_na_virada(con_temp, monkeypatch):
    con = con_temp
    with con:
        con.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio)
                       VALUES ('PJ','Aluguel','Aluguel',1000,1,1,'2026-01')""")
    with con:   # as competências antigas já foram pagas: só novembro está em aberto, vencendo em 01/11
        rid = con.execute("SELECT id FROM recorrencias").fetchone()[0]
        for comp in ("2026-07", "2026-08", "2026-09", "2026-10"):
            con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, recorrencia_id, competencia)
                           VALUES ('PJ','saida',?,?,1000,'Aluguel',?,?)""", (comp + "-01", comp + "-01", rid, comp))

    class FakeDt:
        date = _DataFixa
        timedelta = dt.timedelta
        datetime = dt.datetime

        def __getattr__(self, nome):
            return getattr(dt, nome)

    monkeypatch.setattr(main, "dt", FakeDt())
    textos = [a["texto"] for a in main.alertas(con)]
    assert any("vencida ou vencendo em 3 dias" in t for t in textos)


# ---------- painel financeiro ----------
@pytest.fixture
def cliente_http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    con = db.conectar()
    yield TestClient(main.app, base_url="http://localhost"), con
    con.close()


def test_painel_prejuizo_tem_barra_propria_e_das_com_o_parametro(cliente_http):
    http, con = cliente_http
    hoje = dt.date.today()
    mes = hoje.strftime("%Y-%m")
    lancar(con, "entrada", 1000, f"{mes}-02", pago_em=f"{mes}-02", categoria="Mensalidade (Aulas Presenciais)")
    lancar(con, "saida", 3000, f"{mes}-03", pago_em=f"{mes}-03", categoria="Aluguel")
    with con:
        con.execute("UPDATE parametros SET valor=0.045 WHERE grupo='imposto' AND chave='DAS'")
    t = http.get(f"/financeiro/painel?mes={mes}").text
    assert 'class="b-prejuizo"' in t and "Prejuízo" in t
    assert "Estimativa: 4,5% da receita" in t


def test_aviso_do_salario_aparece_no_prejuizo(cliente_http):
    http, con = cliente_http
    with con:
        con.execute("UPDATE parametros SET valor=3000 WHERE grupo='salario' AND chave='valor'")
    t = http.get("/financeiro").text
    assert "a PJ não teve lucro" in t


def test_livro_caixa_pj_e_pf_nao_soma_o_salario_duas_vezes(cliente_http):
    http, con = cliente_http
    hoje = dt.date.today()
    mes = hoje.strftime("%Y-%m")
    lancar(con, "entrada", 5000, f"{mes}-01", pago_em=f"{mes}-01")
    lancar(con, "saida", 1000, f"{mes}-02", pago_em=f"{mes}-02", categoria="Aluguel")
    lancar(con, "saida", 3000, f"{mes}-05", pago_em=f"{mes}-05", categoria=financeiro.RETIRADA)
    lancar(con, "entrada", 3000, f"{mes}-05", pago_em=f"{mes}-05", escopo="PF", categoria="Salário")
    t = http.get(f"/financeiro?mes={mes}&escopo=todos").text
    assert "Sem o salário PJ→PF" in t
    tpj = http.get(f"/financeiro?mes={mes}&escopo=PJ").text
    assert "Sem o salário PJ→PF" not in tpj


# ---------- painel principal ----------
def test_lucro_hora_so_conta_as_horas_de_quem_tem_preco_base(con_temp):
    con = con_temp
    base_pacote(con, qtd=8, preco=900, op=500, mo=300, total=800)
    aluno(con, "Com base", 900)
    aluno(con, "Sem base (SmartFit)", 900, local="SmartFit")
    m = main.calcular_metricas(con)
    com_base = main.estimativa_cliente(con, con.execute("SELECT * FROM clientes WHERE nome='Com base'").fetchone(), main.precos.carregar_parametros(con))
    assert m["horas_ocupadas"] == 16
    assert m["lucro_hora"] == pytest.approx(com_base["lucro"] / 8)   # antes: lucro / 16 horas, metade do real


def test_ficha_nao_multiplica_o_valor_pago_pelo_grupo_e_bate_com_o_painel(cliente_http):
    http, con = cliente_http
    base_pacote(con)
    cid = aluno(con, "Dupla", 1440, pessoas=2)
    c = con.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone()
    est = main.estimativa_cliente(con, c, main.precos.carregar_parametros(con))
    assert est["preco_total"] == 1440   # o aluno paga 1.440: não vira 1.440 x 1,6
    m = main.calcular_metricas(con)
    assert m["lucro_hora"] == pytest.approx(est["lucro"] / 8)   # painel e ficha usam o mesmo cálculo
    t = http.get(f"/clientes/{cid}").text
    assert main.moeda(est["lucro"]) in t


# ---------- CAC do mês ----------
def test_cac_do_mes_nao_divide_pelos_clientes_de_toda_a_historia(con_temp):
    con = con_temp
    with con:
        for k in range(4):   # 4 leads de maio viraram cliente
            lid = con.execute("INSERT INTO leads (nome, canal_origem, etapa) VALUES (?, 'Instagram Ads', 'cliente')", (f"L{k}",)).lastrowid
            for etapa in ("lead", "conversa", "avaliacao", "cliente"):
                con.execute("INSERT INTO lead_etapas_log (lead_id, etapa, data) VALUES (?,?, '2026-05-10')", (lid, etapa))
        con.execute("INSERT INTO gastos_marketing (mes, canal, anuncios) VALUES ('2026-10','Instagram Ads', 600)")
    por_canal = {c["canal"]: c for c in main.metricas_por_canal(con, "2026-10")}
    ads = por_canal["Instagram Ads"]
    assert ads["clientes"] == 0 and ads["cac"] is None and ads["leads"] == 0   # nada aconteceu em outubro
    maio = {c["canal"]: c for c in main.metricas_por_canal(con, "2026-05")}["Instagram Ads"]
    assert maio["leads"] == 4 and maio["clientes"] == 4 and maio["tx_fechamento"] == 1


# ---------- funil ----------
def test_ticket_do_funil_ignora_valor_zero(con_temp):
    con = con_temp
    for v in (1000, 0):   # 0 = lead recém-convertido, ainda sem preço
        con.execute("INSERT INTO clientes (nome, valor) VALUES ('c', ?)", (v,))
    con.execute("INSERT INTO leads (nome, canal_origem, etapa) VALUES ('l', 'x', 'conversa')")
    con.commit()
    p = main.previsao_funil(con)
    assert p["ticket"] == 1000


# ---------- checkpoint ----------
def test_checkpoint_nao_conta_cliente_anterior_a_fase(cliente_http):
    http, con = cliente_http
    fase = con.execute("SELECT inicio, fim FROM campanha_fases WHERE tipo='fase' ORDER BY inicio LIMIT 1").fetchone()
    antes = (dt.date.fromisoformat(fase["inicio"]) - dt.timedelta(days=200)).isoformat()
    aluno(con, "Velho Conecta", 500, canal="Conecta Fitness", data_inicio=antes)
    with con:
        con.execute("INSERT INTO campanha_checkpoints (pergunta, canal, prazo) VALUES ('Conecta Fitness trouxe cliente?', 'Conecta Fitness', ?)",
                    (fase["fim"],))
    def resposta():
        t = http.get("/campanhas").text
        i = t.index("Conecta Fitness trouxe cliente?")
        return re.search(r'<span class="tag \w+">(Sim|Não|Pendente)</span>', t[i:]).group(1)

    assert resposta() != "Sim"   # cliente de antes da fase não prova que a campanha funcionou
    aluno(con, "Novo Conecta", 500, canal="Conecta Fitness", data_inicio=fase["inicio"])
    assert resposta() == "Sim"
