"""Auditoria de 16/10, bugs pequenos da previsão: D2 (pacote e avaliação só no mês da venda), N10 (DAS com a entrada atrasada)
e N11 (carteira mensal sem a avaliação)."""
from app import financeiro, main
from tests.test_financeiro import con_temp, lancar  # noqa: F401  (fixture: banco temporário)


def aluno(con, nome, tipo, valor=800, inicio=None, renova=None):
    with con:
        return con.execute("""INSERT INTO clientes (nome, valor, status, tipo_servico, plano, local, forma_pagamento, data_inicio, data_renovacao)
                              VALUES (?, ?, 'ativo', ?, 'Pacote 8 aulas', 'CIA', 'PIX', ?, ?)""", (nome, valor, tipo, inicio, renova)).lastrowid


def falta(con, mes):
    return {i["nome"]: i["falta"] for i in financeiro.mensalidades(con, mes)}


# ---------- D2 ----------
def test_pacote_e_avaliacao_so_entram_no_mes_da_venda(con_temp):
    aluno(con_temp, "Pacote", "Pacote de Aulas", inicio="2026-08-10", renova="2026-11-10")
    aluno(con_temp, "Avaliacao", "Avaliação Física", valor=150, inicio="2026-11-03")
    aluno(con_temp, "Mensal", "Mensalidade", valor=500, inicio="2026-08-10", renova="2026-11-10")
    assert falta(con_temp, "2026-11") == {"Avaliacao": 150, "Mensal": 500, "Pacote": 800}   # mês da venda (início) ou da renovação
    assert falta(con_temp, "2026-08") == {"Mensal": 500, "Pacote": 800}                      # mês em que o pacote começou
    for mes in ("2026-10", "2026-12", "2027-01"):                                            # fora deles, só a mensalidade
        assert falta(con_temp, mes) == {"Mensal": 500}, mes
    assert financeiro._mensalidades_a_receber(con_temp, "2026-12")[0] == 500


def test_pacote_pago_fora_do_mes_da_venda_aparece_como_recebido(con_temp):
    cid = aluno(con_temp, "Pacote", "Pacote de Aulas", inicio="2026-08-10", renova="2026-11-10")
    with con_temp:
        con_temp.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id)
                            VALUES ('PJ','entrada','2026-10-05','2026-10-05',800,'Pacotes de Aulas',?)""", (cid,))
    (i,) = financeiro.mensalidades(con_temp, "2026-10")
    assert (i["situacao"], i["recebido"], i["falta"], i["entra"]) == ("recebido", 800, 0, 800)


def test_pacote_que_renova_anda_para_o_mes_seguinte_ao_pagar(con_temp):
    cid = aluno(con_temp, "Pacote", "Pacote de Aulas", inicio="2026-08-10", renova="2026-11-10")
    with con_temp:   # pagou a renovação de novembro: a próxima compra esperada é em dezembro
        con_temp.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id)
                            VALUES ('PJ','entrada','2026-11-10','2026-11-10',800,'Pacotes de Aulas',?)""", (cid,))
    assert falta(con_temp, "2026-11") == {"Pacote": 0} and falta(con_temp, "2026-12") == {"Pacote": 800}
    assert falta(con_temp, "2027-01") == {}
    assert financeiro.mensalidades(con_temp, "2026-11")[0]["previsto"] == 800   # mês pago: a tela segue mostrando previsto x recebido


def test_pacote_sem_data_nenhuma_no_cadastro_segue_todo_mes(con_temp):
    """Sem data de início nem de renovação não dá para saber o mês da venda: fica como era (o Painel já avisa 'cadastro incompleto')."""
    aluno(con_temp, "Sem data", "Pacote de Aulas")
    assert falta(con_temp, "2026-10") == falta(con_temp, "2026-12") == {"Sem data": 800}


def test_pacote_fora_do_mes_da_venda_mantem_o_lancamento_em_aberto_na_tela(con_temp):
    cid = aluno(con_temp, "Pacote", "Pacote de Aulas", inicio="2026-08-10", renova="2026-11-10")
    with con_temp:
        con_temp.execute("""INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, cliente_id)
                            VALUES ('PJ','entrada','2026-12-15',300,'Pacotes de Aulas',?)""", (cid,))
    (i,) = financeiro.mensalidades(con_temp, "2026-12")
    assert (i["previsto"], i["aberto"], i["falta"], len(i["abertos"])) == (0, 300, 0, 1)


# ---------- N10 ----------
def test_das_estimado_inclui_a_entrada_atrasada_que_vai_ser_recebida_agora(con_temp):
    financeiro.salvar_saldos(con_temp, "2026-11-05", {"Contabilizei Bank": 0}, {})
    lancar(con_temp, "entrada", 1000, "2026-10-20")   # de outubro, ainda sem baixa: vai ser recebida em novembro
    itens = [i for s in financeiro.previsao(con_temp, "2026-11-05")["semanas"] for i in s["itens"]]
    assert ("2026-12-20", "DAS estimado (11/2026)", 60) in [(i["data"], i["descricao"], i["valor"]) for i in itens]


def test_das_estimado_nao_conta_duas_vezes_a_entrada_em_aberto_do_mes(con_temp):
    financeiro.salvar_saldos(con_temp, "2026-11-05", {"Contabilizei Bank": 0}, {})
    lancar(con_temp, "entrada", 1000, "2026-10-20")
    lancar(con_temp, "entrada", 500, "2026-11-25")
    lancar(con_temp, "entrada", 2000, "2026-12-10")
    das = {i["descricao"]: i["valor"] for s in financeiro.previsao(con_temp, "2026-11-05")["semanas"] for i in s["itens"]
           if i["descricao"].startswith("DAS")}
    assert das == {"DAS estimado (11/2026)": 90, "DAS estimado (12/2026)": 120}


# ---------- N11 ----------
def test_carteira_mensal_nao_soma_a_avaliacao(con_temp):
    aluno(con_temp, "Pacote", "Pacote de Aulas")
    aluno(con_temp, "Mensal", "Mensalidade", valor=500)
    aluno(con_temp, "Online", "Consultoria Online", valor=200)
    aluno(con_temp, "Avaliacao", "Avaliação Física", valor=150)
    m = main.calcular_metricas(con_temp, "2026-11")
    assert m["faturamento_recorrente"] == 1500 and m["clientes_ativos"] == 4
    assert m["cobre"]["carteira"] == 1500
