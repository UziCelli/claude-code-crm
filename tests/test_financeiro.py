"""Testes da lógica pura do financeiro (banco temporário)."""
import pytest

from app import db, financeiro


@pytest.fixture
def con_temp(tmp_path, monkeypatch):
    db_path = tmp_path / "crm.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(db_path)
    con = db.conectar(db_path)
    yield con
    con.close()


def lancar(con, tipo, valor, data, pago_em=None, escopo="PJ", recorrencia_id=None, competencia=None, conta=None, categoria="Outros"):
    with con:
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, recorrencia_id, competencia, conta)"
                    " VALUES (?,?,?,?,?,?,?,?,?)", (escopo, tipo, data, pago_em, valor, categoria, recorrencia_id, competencia, conta))


def recorrencia(con, valor=1000, dia=31, fixo=1):
    with con:
        return con.execute("INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio)"
                           " VALUES ('PJ','Aluguel','Aluguel',?,?,?,'2026-01')", (valor, dia, fixo)).lastrowid


def test_vencimento_dia_31_em_fevereiro():
    assert financeiro.vencimento(31, "2027-02") == "2027-02-28"
    assert financeiro.vencimento(31, "2028-02") == "2028-02-29"
    assert financeiro.vencimento(10, "2026-09") == "2026-09-10"


def test_status():
    assert financeiro.status({"pago_em": "2026-09-01", "data": "2026-09-01"}, "2026-09-20") == "pago"
    assert financeiro.status({"pago_em": None, "data": "2026-09-10"}, "2026-09-20") == "atrasado"
    assert financeiro.status({"pago_em": None, "data": "2026-09-20"}, "2026-09-20") == "pendente"


def test_ponto_de_equilibrio_sem_receita(con_temp):
    rid = recorrencia(con_temp)
    financeiro.baixar_recorrencia(con_temp, rid, "2026-09", 1000, "2026-09-30")
    r = financeiro.resumo_mes(con_temp, "2026-09")
    assert r["receita"] == 0 and r["custos_fixos"] == 1000
    assert r["ponto_equilibrio"] is None
    assert r["pro_labore"] == 0 and r["das"] == 0


def test_piso_do_pro_labore(con_temp):
    lancar(con_temp, "entrada", 1000, "2026-09-05", "2026-09-05")
    r = financeiro.resumo_mes(con_temp, "2026-09")
    assert r["pro_labore"] == 1518            # 28% de 1000 = 280, abaixo do salário mínimo
    assert r["inss"] == round(1518 * 0.11, 2)
    assert r["das"] == 60
    lancar(con_temp, "entrada", 9000, "2026-09-06", "2026-09-06")
    assert financeiro.resumo_mes(con_temp, "2026-09")["pro_labore"] == 2800   # 28% de 10000


def test_recorrencia_baixada_nao_volta_como_pendente(con_temp):
    rid = recorrencia(con_temp, dia=10)
    pend = financeiro.pendencias(con_temp, "2026-09", "2026-09-20")
    assert [(p["origem"], p["status"], p["data"]) for p in pend][-1] == ("recorrencia", "atrasado", "2026-09-10")
    financeiro.baixar_recorrencia(con_temp, rid, "2026-09", 1050.5, "2026-09-12")
    assert "2026-09" not in [p["competencia"] for p in financeiro.pendencias(con_temp, "2026-09", "2026-09-20")]
    with pytest.raises(ValueError):           # UNIQUE (recorrencia_id, competencia)
        financeiro.baixar_recorrencia(con_temp, rid, "2026-09", 1050.5, "2026-09-12")
    # competências anteriores sem baixa continuam aparecendo (até 3 meses atrás), atrasadas primeiro
    assert [p["competencia"] for p in financeiro.pendencias(con_temp, "2026-10", "2026-09-20")] == ["2026-07", "2026-08", "2026-10"]


def test_pendencias_vencidas_primeiro(con_temp):
    lancar(con_temp, "saida", 50, "2026-09-25")                      # pendente
    lancar(con_temp, "saida", 70, "2026-08-30")                      # atrasada, de mês anterior
    lancar(con_temp, "saida", 90, "2026-10-02")                      # fora do mês
    pend = financeiro.pendencias(con_temp, "2026-09", "2026-09-20")
    assert [p["valor"] for p in pend] == [70, 50]


def test_resumo_mes_so_conta_pagos(con_temp):
    rid = recorrencia(con_temp, valor=500)
    financeiro.baixar_recorrencia(con_temp, rid, "2026-09", 500, "2026-09-30")
    lancar(con_temp, "entrada", 2000, "2026-09-05", "2026-09-05")
    lancar(con_temp, "entrada", 3000, "2026-09-20")                  # em aberto: ignorada
    lancar(con_temp, "saida", 300, "2026-09-07", "2026-09-07")       # variável
    lancar(con_temp, "saida", 800, "2026-09-25")                     # em aberto: ignorada
    lancar(con_temp, "entrada", 100, "2026-09-08", "2026-09-08", escopo="PF")
    lancar(con_temp, "saida", 40, "2026-09-09", "2026-09-09", escopo="PF")
    r = financeiro.resumo_mes(con_temp, "2026-09")
    assert (r["receita"], r["custos_fixos"], r["custos_variaveis"], r["lucro"]) == (2000, 500, 300, 1200)
    assert r["ponto_equilibrio"] == round(500 / 0.85, 2)
    assert r["pf"] == {"entradas": 100, "saidas": 40, "saldo": 60}


def test_mensalidades_previsto_x_recebido(con_temp):
    with con_temp:
        a = con_temp.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Aluno A', 400, 'ativo')").lastrowid
        b = con_temp.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Aluno B', 300, 'ativo')").lastrowid
        con_temp.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Aluno C', 300, 'inativo')")
    for cid, valor, data, pago in [(a, 400, "2026-03-05", "2026-03-05"), (b, 300, "2026-03-05", None), (b, 100, "2026-02-28", "2026-02-28")]:
        with con_temp:
            con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id)"
                             " VALUES ('PJ','entrada',?,?,?,'Outros',?)", (data, pago, valor, cid))
    r = {i["nome"]: i for i in financeiro.mensalidades(con_temp, "2026-03")}
    assert set(r) == {"Aluno A", "Aluno B"}   # inativo fica de fora
    assert (r["Aluno A"]["recebido"], r["Aluno A"]["situacao"]) == (400, "recebido")
    assert (r["Aluno B"]["recebido"], r["Aluno B"]["situacao"]) == (0, "em aberto")   # pendente e pagamento de outro mes nao contam
    assert financeiro.mensalidades(con_temp, "2026-02")[1]["situacao"] == "parcial"


def test_mensalidades_em_aberto_falta_e_inicio(con_temp):
    with con_temp:
        a = con_temp.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Aluno A', 500, 'ativo')").lastrowid
        con_temp.execute("INSERT INTO clientes (nome, valor, status, data_inicio) VALUES ('Começa em dezembro', 400, 'ativo', '2026-12-01')")
        con_temp.execute("INSERT INTO clientes (nome, valor, status, data_inicio) VALUES ('Data antiga', 300, 'ativo', '05/12/2026')")
        con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, cliente_id) VALUES ('PJ','entrada','2026-10-05',500,'Outros',?)", (a,))
    r = {i["nome"]: i for i in financeiro.mensalidades(con_temp, "2026-10")}
    assert set(r) == {"Aluno A", "Data antiga"}   # quem começa depois do mês não deve nada nele; data fora do padrão não some
    assert (r["Aluno A"]["aberto"], r["Aluno A"]["falta"], r["Aluno A"]["situacao"]) == (500, 0, "em aberto")
    assert [x["valor"] for x in r["Aluno A"]["abertos"]] == [500]
    assert "Começa em dezembro" in {i["nome"] for i in financeiro.mensalidades(con_temp, "2026-12")}


def test_sugerir_aluno():
    alunos = [{"id": 1, "nome": "Giuliana Souza"}, {"id": 2, "nome": "Ana Lima"}, {"id": 3, "nome": "Ana Costa"}, {"id": 4, "nome": "Bia"}]
    assert financeiro.sugerir_aluno("10 aulas Giuliana", alunos) == 1
    assert financeiro.sugerir_aluno("PIX GIULIÂNA", alunos) == 1
    assert financeiro.sugerir_aluno("Mensalidade Ana", alunos) is None        # duas Anas: não chuta
    assert financeiro.sugerir_aluno("Ana Costa pix", alunos) == 3             # nome completo desempata
    assert financeiro.sugerir_aluno("Bianca", alunos) is None                 # palavra inteira, não pedaço
    assert financeiro.sugerir_aluno("Consultoria Híbrida", alunos) is None


def test_recorrencia_nao_paga_continua_atrasada_no_mes_seguinte(con_temp):
    recorrencia(con_temp, dia=10)
    pend = financeiro.pendencias(con_temp, "2026-10", "2026-10-02")
    assert [(p["competencia"], p["status"]) for p in pend] == [
        ("2026-07", "atrasado"), ("2026-08", "atrasado"), ("2026-09", "atrasado"), ("2026-10", "pendente")]


def test_baixa_excluida_volta_como_pendente_e_pode_ser_paga_de_novo(con_temp):
    rid = recorrencia(con_temp, dia=10)
    lid = financeiro.baixar_recorrencia(con_temp, rid, "2026-09", 1000, "2026-09-10")
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET excluido_em='2026-09-11' WHERE id=?", (lid,))
    assert "2026-09" in [p["competencia"] for p in financeiro.pendencias(con_temp, "2026-09", "2026-09-20")]
    assert financeiro.baixar_recorrencia(con_temp, rid, "2026-09", 1100, "2026-09-12") == lid
    assert tuple(con_temp.execute("SELECT valor, excluido_em FROM lancamentos WHERE id=?", (lid,)).fetchone()) == (1100, None)


def test_valor_nao_finito_e_recusado(con_temp):
    rid = recorrencia(con_temp)
    for v in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            financeiro.baixar_recorrencia(con_temp, rid, "2026-09", v, "2026-09-12")


def test_ponto_de_equilibrio_sem_custos_fixos(con_temp):
    lancar(con_temp, "entrada", 1000, "2026-09-06", "2026-09-06")
    assert financeiro.resumo_mes(con_temp, "2026-09")["ponto_equilibrio"] is None


# ---------- Saldo livre ----------
def saldo(con, conta, valor, data):
    financeiro.salvar_saldos(con, data, {conta: valor}, {})


def test_saldo_livre_desconta_recorrencia_aberta_e_nao_a_baixada(con_temp):
    saldo(con_temp, "Contabilizei Bank", 3000, "2026-10-15")
    rid = recorrencia(con_temp, valor=1000, dia=10)
    with con_temp:
        con_temp.execute("UPDATE recorrencias SET inicio='2026-09'")
    livre = financeiro.saldo_livre(con_temp, "2026-10-16")["PJ"]
    # setembro e outubro atrasados + novembro (10/11 cabe nos 30 dias)
    assert [i["data"] for i in livre["itens"]] == ["2026-09-10", "2026-10-10", "2026-11-10"]
    assert livre["tem"] == 3000 and livre["comprometido"] == 3000 and livre["livre"] == 0
    financeiro.baixar_recorrencia(con_temp, rid, "2026-09", 1000, "2026-10-16")
    financeiro.baixar_recorrencia(con_temp, rid, "2026-10", 1000, "2026-10-16")
    livre = financeiro.saldo_livre(con_temp, "2026-10-16")["PJ"]
    # pagas depois da foto: saem do comprometido e do "tem" (o livre não sobe só por pagar)
    assert livre["comprometido"] == 1000 and livre["tem"] == 1000 and livre["livre"] == 0


def test_saldo_livre_ignora_entrada_futura_e_conta_atrasado(con_temp):
    saldo(con_temp, "Inter", 500, "2026-10-16")
    lancar(con_temp, "entrada", 2000, "2026-10-20", escopo="PF")          # previsto: não conta
    lancar(con_temp, "saida", 300, "2026-09-01", escopo="PF")             # atrasado: conta
    lancar(con_temp, "saida", 100, "2026-12-01", escopo="PF")             # depois de 30 dias: não conta
    livre = financeiro.saldo_livre(con_temp, "2026-10-16")["PF"]
    assert livre["livre"] == 200 and livre["comprometido"] == 300


def test_saldo_livre_guarda_das_da_receita_do_mes(con_temp):
    saldo(con_temp, "Contabilizei Bank", 1000, "2026-10-16")
    lancar(con_temp, "entrada", 1000, "2026-10-05", pago_em="2026-10-05")
    pj = financeiro.saldo_livre(con_temp, "2026-10-16")["PJ"]
    assert pj["imposto"] == 60 and pj["livre"] == 940
    # o DAS de novembro já lançado em aberto não é contado duas vezes
    with con_temp:
        con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria) VALUES ('PJ','saida','2026-11-10',60,'Impostos/Taxas')")
    pj = financeiro.saldo_livre(con_temp, "2026-10-16")["PJ"]
    assert pj["imposto"] == 0 and pj["livre"] == 940


def test_saldo_velho_reserva_e_sem_saldo(con_temp):
    out = financeiro.saldo_livre(con_temp, "2026-10-16")
    assert out["PF"]["sem_saldo"] and not out["PF"]["desatualizado"]
    saldo(con_temp, "Inter", 100, "2026-10-01")
    financeiro.salvar_saldos(con_temp, "2026-10-16", {"Caixinha": 5000}, {})            # conta fora da lista: ignorada
    out = financeiro.saldo_livre(con_temp, "2026-10-16")
    assert out["PF"]["desatualizado"] and out["PF"]["dias_velho"] == 15 and out["reserva"] == 0
    financeiro.salvar_saldos(con_temp, "2026-10-16", {"Caixa": 800}, {"Caixa": "Reserva"})
    out = financeiro.saldo_livre(con_temp, "2026-10-16")
    assert out["reserva"] == 800 and out["PF"]["tem"] == 100


def test_salvar_saldo_no_mesmo_dia_troca_a_foto(con_temp):
    saldo(con_temp, "Inter", 100, "2026-10-16")
    saldo(con_temp, "Inter", 150, "2026-10-16")
    assert financeiro.saldos_atuais(con_temp)["Inter"]["saldo"] == 150
    assert con_temp.execute("SELECT COUNT(*) FROM saldos WHERE excluido_em IS NULL").fetchone()[0] == 1


def test_conta_nova_sem_frente(con_temp):
    with con_temp:
        con_temp.execute("INSERT INTO parametros (grupo, chave, valor_texto) VALUES ('lista_contas','Nubank','Nubank'), ('lista_contas','Cartão XP','Cartão XP')")
    fr = financeiro.frentes_contas(con_temp)
    assert fr["Nubank"] is None and fr["Cartão XP"] == "Fora"
    assert "Nubank" in financeiro.saldo_livre(con_temp, "2026-10-16")["sem_frente"]


def test_saldo_de_partida_desconta_o_pago_depois_da_foto(con_temp):
    """Foto de 10/10 com 1.000 e aluguel pago em 12/10: tem 400, não 1.000."""
    saldo(con_temp, "Inter", 1000, "2026-10-10")
    lancar(con_temp, "saida", 600, "2026-10-12", pago_em="2026-10-12", escopo="PF", conta="Inter")             # aluguel
    lancar(con_temp, "saida", 50, "2026-10-10", pago_em="2026-10-10", escopo="PF", conta="Inter")              # dia da foto: já está nela
    lancar(con_temp, "saida", 300, "2026-10-13", pago_em="2026-10-13", escopo="PF", conta="Cartão Inter")      # cartão não tira do banco
    lancar(con_temp, "entrada", 200, "2026-10-14", pago_em="2026-10-14", escopo="PF", conta="Contabilizei Bank")  # conta da PJ
    out = financeiro.saldo_livre(con_temp, "2026-10-17")
    assert out["PF"]["tem"] == 400 and out["PF"]["livre"] == 400
    assert out["PJ"]["tem"] == 0 and out["PJ"]["sem_saldo"]   # PJ sem foto: a entrada sozinha não vira saldo
    assert financeiro.previsao(con_temp, "2026-10-17")["inicio"]["PF"] == 400


def test_saldo_de_partida_sem_conta_vai_pelo_escopo_e_agendado_fica_em_aberto(con_temp):
    saldo(con_temp, "Inter", 1000, "2026-10-10")
    saldo(con_temp, "Itaú", 500, "2026-10-15")
    lancar(con_temp, "saida", 100, "2026-10-12", pago_em="2026-10-12", escopo="PF")     # sem conta, entre as fotos: desconta (lado seguro)
    lancar(con_temp, "entrada", 300, "2026-10-12", pago_em="2026-10-12", escopo="PF")   # talvez já esteja na foto do Itaú: não soma
    lancar(con_temp, "entrada", 80, "2026-10-16", pago_em="2026-10-16", escopo="PF")    # depois de todas as fotos: soma
    lancar(con_temp, "saida", 40, "2026-10-16", pago_em="2026-10-16", escopo="PJ")      # outra frente
    lancar(con_temp, "saida", 250, "2026-10-15", pago_em="2026-10-25", escopo="PF", conta="Inter")   # agendado: ainda está na conta
    pf = financeiro.saldo_livre(con_temp, "2026-10-17")["PF"]
    assert pf["tem"] == 1480 and pf["comprometido"] == 250 and pf["livre"] == 1230
    assert [i["data"] for i in pf["itens"]] == ["2026-10-25"]
    p = financeiro.previsao(con_temp, "2026-10-17")
    assert p["semanas"][1]["PF"]["saidas"] == 250 and p["semanas"][1]["PF"]["saldo"] == 1230   # sai na semana do pagamento
    assert p["desatualizado"]["PF"] is False and p["dias_velho"]["PF"] == 7


# ---------- Salário fixo ----------
def ligar_salario(con, valor=2000, dia=5):
    with con:
        con.execute("UPDATE parametros SET valor=? WHERE grupo='salario' AND chave='valor'", (valor,))
        con.execute("UPDATE parametros SET valor=? WHERE grupo='salario' AND chave='dia'", (dia,))


def test_salario_desligado_nao_paga(con_temp):
    assert not financeiro.salario_mes(con_temp, "2026-10", "2026-10-16")["pode_pagar"]
    with pytest.raises(ValueError):
        financeiro.pagar_salario(con_temp, "2026-10", "2026-10-16")


def test_salario_pago_uma_vez_e_fora_do_custo(con_temp):
    ligar_salario(con_temp)
    lancar(con_temp, "entrada", 5000, "2026-10-02", pago_em="2026-10-02")
    assert financeiro.salario_mes(con_temp, "2026-10", "2026-10-04")["pode_pagar"] is False   # antes do dia
    assert financeiro.salario_mes(con_temp, "2026-10", "2026-10-05")["pode_pagar"] is True
    financeiro.pagar_salario(con_temp, "2026-10", "2026-10-05")
    with pytest.raises(ValueError):
        financeiro.pagar_salario(con_temp, "2026-10", "2026-10-06")
    r = financeiro.resumo_mes(con_temp, "2026-10")
    assert r["retirada"] == 2000 and r["custos_variaveis"] == 0 and r["lucro"] == 5000
    assert r["pf"]["entradas"] == 2000
    s = financeiro.salario_mes(con_temp, "2026-10", "2026-10-06")
    assert s["pago_em"] == "2026-10-05" and not s["pode_pagar"]


def test_salario_excluido_pode_ser_pago_de_novo(con_temp):
    ligar_salario(con_temp)
    financeiro.pagar_salario(con_temp, "2026-10", "2026-10-05")
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET excluido_em='2026-10-06' WHERE origem LIKE 'SAL:2026-10:%'")
    ligar_salario(con_temp, valor=1800)
    financeiro.pagar_salario(con_temp, "2026-10", "2026-10-07")
    assert [r[0] for r in con_temp.execute("SELECT valor FROM lancamentos WHERE excluido_em IS NULL")] == [1800, 1800]


def test_gasto_pf_contra_salario_e_sugestao(con_temp):
    ligar_salario(con_temp, valor=1000)
    lancar(con_temp, "saida", 950, "2026-10-03", pago_em="2026-10-03", escopo="PF")
    assert financeiro.salario_mes(con_temp, "2026-10", "2026-10-16")["pct_gasto"] == 95
    for m in ("07", "08", "09"):
        lancar(con_temp, "entrada", 3000, f"2026-{m}-10", pago_em=f"2026-{m}-10")
    assert financeiro.sugestao_salario(con_temp, "2026-10") == 2400


def test_livre_pj_guarda_o_salario_nao_pago(con_temp):
    """Salário de 3.000 no dia 20 com 4.000 na PJ: livre 1.000, antes e depois de pagar."""
    ligar_salario(con_temp, valor=3000, dia=20)
    saldo(con_temp, "Contabilizei Bank", 4000, "2026-10-17")
    pj = financeiro.saldo_livre(con_temp, "2026-10-17")["PJ"]
    assert pj["salario"] == 3000 and pj["livre"] == 1000
    financeiro.pagar_salario(con_temp, "2026-10", "2026-10-20")
    pj = financeiro.saldo_livre(con_temp, "2026-10-20")["PJ"]   # o de novembro (20/11) ainda não cabe nos 30 dias
    assert pj["tem"] == 1000 and pj["salario"] == 0 and pj["livre"] == 1000
    assert financeiro.saldo_livre(con_temp, "2026-10-17", dias=40)["PJ"]["salario"] == 3000   # com 40 dias, só o de novembro


def test_retirada_a_mao_conta_como_salario_pago(con_temp):
    ligar_salario(con_temp, valor=3000, dia=20)
    financeiro.pagar_salario(con_temp, "2026-09", "2026-10-02")   # setembro pago em outubro: não paga outubro
    assert financeiro.salario_mes(con_temp, "2026-10", "2026-10-20")["pode_pagar"]
    lancar(con_temp, "saida", 1000, "2026-10-18", pago_em="2026-10-18", categoria="Retirada")
    s = financeiro.salario_mes(con_temp, "2026-10", "2026-10-20")
    assert not s["pode_pagar"] and s["retirado"] == 1000 and s["falta"] == 2000 and s["pago_em"] is None
    with pytest.raises(ValueError):
        financeiro.pagar_salario(con_temp, "2026-10", "2026-10-20")
    p = financeiro.previsao(con_temp, "2026-10-20")
    sal = sorted((i["data"], i["escopo"], i["valor"]) for s in p["semanas"] for i in s["itens"] if i["descricao"].startswith("Salário"))
    assert sal[:2] == [("2026-10-20", "PF", 2000), ("2026-10-20", "PJ", 2000)]   # só o que falta
    lancar(con_temp, "saida", 2000, "2026-10-19", pago_em="2026-10-19", categoria="Retirada")
    s = financeiro.salario_mes(con_temp, "2026-10", "2026-10-20")
    assert s["falta"] == 0 and s["pago_em"] == "2026-10-19"
    p = financeiro.previsao(con_temp, "2026-10-20")
    assert not [i for s in p["semanas"] for i in s["itens"] if i["descricao"].startswith("Salário") and i["data"] < "2026-11"]
    assert financeiro.saldo_livre(con_temp, "2026-10-20")["PJ"]["salario"] == 0


# ---------- Potes e colchão ----------
def test_potes_em_cascata(con_temp):
    ligar_salario(con_temp, valor=1000)
    with con_temp:
        con_temp.execute("UPDATE recorrencias SET excluido_em='x'")
    recorrencia(con_temp, valor=500, dia=10)                                     # contas da PJ: 500
    lancar(con_temp, "entrada", 400, "2026-10-02", pago_em="2026-10-02")         # 24 imposto, 376 contas
    lancar(con_temp, "entrada", 1000, "2026-10-05", pago_em="2026-10-05")        # 60 imposto, 124 contas, 816 salário
    lancar(con_temp, "entrada", 500, "2026-10-09", pago_em="2026-10-09")         # 30 imposto, 184 salário, 286 colchão
    lancar(con_temp, "entrada", 999, "2026-10-20")                               # não recebida: fora
    p = financeiro.potes_mes(con_temp, "2026-10")
    divs = [e["divisao"] for e in p["entradas"]]
    assert divs[0] == {"imposto": 24, "contas": 376, "salario": 0, "colchao": 0}
    assert divs[1] == {"imposto": 60, "contas": 124, "salario": 816, "colchao": 0}
    assert divs[2] == {"imposto": 30, "contas": 0, "salario": 184, "colchao": 286}
    potes = {x["chave"]: x for x in p["potes"]}
    assert potes["contas"]["falta"] == 0 and potes["salario"]["cheio"] == 1000 and potes["colchao"]["cheio"] == 286
    assert financeiro.texto_divisao(divs[2]) == "R$ 30,00 imposto · R$ 184,00 salário pf · R$ 286,00 colchão"


def test_potes_sem_salario_pula_o_pote(con_temp):
    lancar(con_temp, "entrada", 100, "2026-10-02", pago_em="2026-10-02")
    assert "salario" not in [x["chave"] for x in financeiro.potes_mes(con_temp, "2026-10")["potes"]]


def test_colchao(con_temp):
    recorrencia(con_temp, valor=800, dia=5, fixo=1)
    recorrencia(con_temp, valor=300, dia=5, fixo=0)                              # variável: fora do colchão
    c = financeiro.colchao(con_temp, "2026-10")
    assert c["mensal"] == 800 and c["tres"] == 2400 and c["meta"] is None
    ligar_salario(con_temp, valor=2000)
    financeiro.salvar_saldos(con_temp, "2026-10-16", {"Caixa": 1400}, {"Caixa": "Reserva"})
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=3 WHERE grupo='colchao' AND chave='meses'")
    c = financeiro.colchao(con_temp, "2026-10")
    assert c["mensal"] == 2800 and c["meta"] == 8400 and c["guardado"] == 1400 and c["cobre_meses"] == 0.5 and c["pct"] == 17


# ---------- Previsão 90 dias ----------
def test_previsao_sem_duplicar_e_com_aperto(con_temp):
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=0 WHERE grupo='imposto' AND chave='DAS'")   # sem DAS para isolar
    financeiro.salvar_saldos(con_temp, "2026-10-16", {"Inter": 1000, "Contabilizei Bank": 500}, {})
    with con_temp:
        rid = con_temp.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio)
                                  VALUES ('PF','Fatura','Fatura',800,25,0,'2026-10')""").lastrowid
    # outubro já lançado em aberto pela recorrência: não pode contar duas vezes
    lancar(con_temp, "saida", 800, "2026-10-25", escopo="PF", recorrencia_id=rid, competencia="2026-10")
    p = financeiro.previsao(con_temp, "2026-10-16")
    assert len(p["semanas"]) == 13 and p["fim"] == "2027-01-14"
    s1 = p["semanas"][1]   # 23/10 a 29/10
    assert s1["PF"]["saidas"] == 800 and s1["PF"]["saldo"] == 200
    assert p["aperto"]["PF"]["inicio"] == "2026-11-25" and p["aperto"]["PF"]["saldo"] == -600   # fatura de novembro: o aperto aponta o dia da fatura, não o início da semana
    assert "PJ" not in p["aperto"] and p["menor"]["PJ"] == 500
    assert p["semanas"][5]["negativo"]


def test_previsao_mensalidades_salario_e_das(con_temp):
    financeiro.salvar_saldos(con_temp, "2026-10-16", {"Contabilizei Bank": 0}, {})
    ligar_salario(con_temp, valor=1000, dia=5)
    with con_temp:
        cid = con_temp.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Ana', 2000, 'ativo')").lastrowid
    lancar(con_temp, "entrada", 2000, "2026-09-10", pago_em="2026-09-10")                     # receita de setembro
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET cliente_id=? ", (cid,))
    p = financeiro.previsao(con_temp, "2026-10-16")
    itens = [i for s in p["semanas"] for i in s["itens"]]
    descr = sorted((i["data"], i["descricao"], i["escopo"], i["valor"]) for i in itens)
    # outubro: Ana não pagou (entra hoje, atrasada), salário de outubro não pago (hoje), DAS de setembro dia 20
    assert ("2026-10-16", "Mensalidades a receber", "PJ", 2000) in descr
    assert ("2026-10-16", "Salário para a PF", "PJ", 1000) in descr and ("2026-10-16", "Salário da PJ", "PF", 1000) in descr
    assert ("2026-10-20", "DAS estimado (09/2026)", "PJ", 120) in descr
    # novembro: DAS sobre a receita esperada de outubro (2000)
    assert ("2026-11-20", "DAS estimado (10/2026)", "PJ", 120) in descr
    assert all(i["estimado"] for i in itens if i["descricao"].startswith(("Mensalidades", "DAS")))


def test_previsao_entrada_sem_aluno_nao_conta_duas_vezes(con_temp):
    """O caso do print: '10 aulas Giuliana' em aberto sem ligar à aluna não pode entrar de novo em 'Mensalidades a receber'."""
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=0 WHERE grupo='imposto' AND chave='DAS'")   # sem DAS para isolar
        con_temp.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Giuliana', 1123.37, 'ativo')")
        con_temp.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Ana', 500, 'ativo')")
        con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, descricao)"
                         " VALUES ('PJ','entrada','2026-10-05',1123.37,'Pacotes de Aulas','10 aulas Giuliana')")
    financeiro.salvar_saldos(con_temp, "2026-10-16", {"Contabilizei Bank": 0}, {})
    p = financeiro.previsao(con_temp, "2026-10-16")
    entradas = {i["descricao"]: i["valor"] for i in p["semanas"][0]["itens"] if i["tipo"] == "entrada"}
    assert entradas == {"10 aulas Giuliana": 1123.37, "Mensalidades a receber": 500}   # só a Ana falta
    assert p["semanas"][0]["PJ"]["entradas"] == 1623.37
    assert [e["descricao"] for e in p["sem_aluno"]] == ["10 aulas Giuliana"] and p["sem_aluno_total"] == 1123.37
    # ligada à aluna: mesmo resultado, e o aviso some
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET cliente_id=(SELECT id FROM clientes WHERE nome='Giuliana')")
    p = financeiro.previsao(con_temp, "2026-10-16")
    assert p["semanas"][0]["PJ"]["entradas"] == 1623.37 and p["sem_aluno"] == []


# ---------- DAS ----------
def saida(con, valor, data, descricao, categoria="Impostos/Taxas", pago_em=None):
    with con:
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao) VALUES ('PJ','saida',?,?,?,?,?)",
                    (data, pago_em, valor, categoria, descricao))


def recorrencia_imposto(con, descricao, valor, inicio="2026-10", fixo=1):
    with con:
        con.execute("INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio)"
                    " VALUES ('PJ',?,'Impostos/Taxas',?,20,?,?)", (descricao, valor, fixo, inicio))


def test_eh_das():
    assert financeiro.eh_das("DAS", "Impostos/Taxas") and financeiro.eh_das("Guia DAS 09/2026", "Outros")
    assert financeiro.eh_das("das setembro", "Outros") and financeiro.eh_das("Simples Nacional", "Impostos/Taxas")
    assert financeiro.eh_das(None, "DAS") and financeiro.eh_das("", "Impostos/Taxas")          # sem descrição: como era antes
    assert financeiro.eh_das("Impostos/Taxas", "Impostos/Taxas")                                 # tela mostra a categoria no lugar
    assert not financeiro.eh_das("DARF", "Impostos/Taxas") and not financeiro.eh_das("Taxa bancária", "Impostos/Taxas")
    assert not financeiro.eh_das("Anuidade CREF", "Impostos/Taxas") and not financeiro.eh_das("Material das aulas", "Material de Trabalho")


def test_previsao_das_nao_some_com_darf_nem_duplica(con_temp):
    with con_temp:
        con_temp.execute("UPDATE recorrencias SET excluido_em='x'")
        con_temp.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Ana', 2000, 'ativo')")
    financeiro.salvar_saldos(con_temp, "2026-10-16", {"Contabilizei Bank": 0}, {})
    lancar(con_temp, "entrada", 5000, "2026-09-10", pago_em="2026-09-10")             # receita de setembro
    recorrencia_imposto(con_temp, "DARF", 290.52)                                    # DARF todo mês: não é o DAS
    saida(con_temp, 400, "2026-11-20", "DAS 10/2026", categoria="Outros")             # DAS de novembro já lançado, fora de "Impostos"
    recorrencia_imposto(con_temp, "DAS", 100, inicio="2026-12")                      # DAS previsto por recorrência em dezembro
    itens = [i for s in financeiro.previsao(con_temp, "2026-10-16")["semanas"] for i in s["itens"]]
    das = sorted((i["data"], i["descricao"], i["valor"]) for i in itens if "DAS" in i["descricao"])
    assert das == [("2026-10-20", "DAS estimado (09/2026)", 300),                    # o DARF não apaga mais o DAS
                   ("2026-11-20", "DAS 10/2026", 400),                               # lançado: sem estimado em dobro
                   ("2026-12-20", "DAS", 100),
                   ("2026-12-20", "DAS estimado (11/2026) além do previsto", 20)]    # 6% de 2000 − 100 da recorrência
    assert sum(1 for i in itens if i["descricao"] == "DARF") == 3


def test_saldo_livre_guarda_das_do_mes_passado_ate_lancar(con_temp):
    saldo(con_temp, "Contabilizei Bank", 12000, "2026-11-01")
    lancar(con_temp, "entrada", 10000, "2026-10-05", pago_em="2026-10-05")
    pj = financeiro.saldo_livre(con_temp, "2026-11-01")["PJ"]
    assert pj["imposto"] == 600 and pj["livre"] == 11400                          # antes: 0 no dia 1º
    saida(con_temp, 600, "2026-11-20", "DAS 10/2026")                              # lançou: vai para o comprometido
    pj = financeiro.saldo_livre(con_temp, "2026-11-01")["PJ"]
    assert (pj["imposto"], pj["comprometido"], pj["livre"]) == (0, 600, 11400)


def test_saldo_livre_darf_nao_abate_reserva_do_das(con_temp):
    saldo(con_temp, "Contabilizei Bank", 5000, "2026-10-16")
    lancar(con_temp, "entrada", 5000, "2026-10-05", pago_em="2026-10-05")
    saida(con_temp, 290.52, "2026-11-10", "DARF")
    pj = financeiro.saldo_livre(con_temp, "2026-10-16")["PJ"]
    assert (pj["imposto"], pj["comprometido"]) == (300, 290.52)                   # antes: imposto 9,48


def test_potes_e_colchao_sem_o_das_recorrente(con_temp):
    with con_temp:
        con_temp.execute("UPDATE recorrencias SET excluido_em='x'")
    recorrencia(con_temp, valor=1000)
    recorrencia_imposto(con_temp, "DAS", 600, inicio="2026-01")                  # o pote Imposto já guarda o DAS
    recorrencia_imposto(con_temp, "DARF", 200, inicio="2026-01")                 # DARF continua nas contas
    lancar(con_temp, "entrada", 10000, "2026-10-02", pago_em="2026-10-02")
    contas = next(p for p in financeiro.potes_mes(con_temp, "2026-10")["potes"] if p["chave"] == "contas")
    assert contas["alvo"] == 1200
    assert financeiro.colchao(con_temp, "2026-10")["mensal"] == 1200


# ---------- Recorrência paga à mão (PR 4 da auditoria) ----------
def paga_a_mao(con, valor=1000, data="2026-10-05", descricao="Aluguel", categoria="Aluguel", pago_em="2026-10-05", escopo="PJ", tipo="saida"):
    with con:
        return con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao) VALUES (?,?,?,?,?,?,?)",
                           (escopo, tipo, data, pago_em, valor, categoria, descricao)).lastrowid


def abertas_de_outubro(con):
    return [i for i in financeiro.pendencias(con, "2026-10", "2026-10-16") if i["origem"] == "recorrencia" and i["competencia"] == "2026-10"]


def test_ligar_recorrencia_some_de_a_pagar_do_livre_e_vira_custo_fixo(con_temp):
    rid = recorrencia(con_temp, valor=1000, dia=5)
    saldo(con_temp, "Contabilizei Bank", 5000, "2026-10-01")
    lid = paga_a_mao(con_temp)
    assert len(abertas_de_outubro(con_temp)) == 1                                    # fantasma: já paguei, mas continua atrasada
    antes = financeiro.saldo_livre(con_temp, "2026-10-16")["PJ"]["comprometido"]
    resumo = financeiro.resumo_mes(con_temp, "2026-10")
    assert (resumo["custos_fixos"], resumo["custos_variaveis"]) == (0, 1000)
    assert financeiro.ligar_recorrencia(con_temp, lid, rid) == "Aluguel"
    assert abertas_de_outubro(con_temp) == []
    assert antes - financeiro.saldo_livre(con_temp, "2026-10-16")["PJ"]["comprometido"] == 1000
    resumo = financeiro.resumo_mes(con_temp, "2026-10")
    assert (resumo["custos_fixos"], resumo["custos_variaveis"]) == (1000, 0)
    assert tuple(con_temp.execute("SELECT recorrencia_id, competencia FROM lancamentos WHERE id=?", (lid,)).fetchone()) == (rid, "2026-10")


def test_ligar_recusa_mes_ja_baixado_e_nao_muda_nada(con_temp):
    rid = recorrencia(con_temp)
    financeiro.baixar_recorrencia(con_temp, rid, "2026-10", 1000, "2026-10-06")
    lid = paga_a_mao(con_temp)
    with pytest.raises(ValueError, match=r"Aluguel de 10/2026 já tem um lançamento \(dia 06/10\)"):
        financeiro.ligar_recorrencia(con_temp, lid, rid)
    assert con_temp.execute("SELECT recorrencia_id FROM lancamentos WHERE id=?", (lid,)).fetchone()[0] is None


def test_ligar_solta_a_vaga_presa_pela_lixeira(con_temp):
    rid = recorrencia(con_temp)
    velha = financeiro.baixar_recorrencia(con_temp, rid, "2026-10", 1000, "2026-10-06")
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET excluido_em='x' WHERE id=?", (velha,))
    lid = paga_a_mao(con_temp)
    financeiro.ligar_recorrencia(con_temp, lid, rid)
    assert con_temp.execute("SELECT recorrencia_id FROM lancamentos WHERE id=?", (lid,)).fetchone()[0] == rid
    assert tuple(con_temp.execute("SELECT recorrencia_id, competencia FROM lancamentos WHERE id=?", (velha,)).fetchone()) == (None, None)


def test_ligar_recusa_entrada_e_escopo_diferente(con_temp):
    rid = recorrencia(con_temp)
    entrada = paga_a_mao(con_temp, tipo="entrada")
    pf = paga_a_mao(con_temp, escopo="PF")
    with pytest.raises(ValueError, match="Só saída"):
        financeiro.ligar_recorrencia(con_temp, entrada, rid)
    with pytest.raises(ValueError, match="é da PJ e este lançamento é da PF"):
        financeiro.ligar_recorrencia(con_temp, pf, rid)


def test_saidas_parecidas_acha_por_descricao_ou_categoria_e_valor(con_temp):
    rid = recorrencia(con_temp, valor=1000)
    a = paga_a_mao(con_temp, valor=1010, descricao="  aluguel ", categoria="Outros")      # mesma descrição, valor diferente
    b = paga_a_mao(con_temp, valor=1000, descricao="Sala", data="2026-11-05", pago_em=None)   # categoria + valor, em aberto
    paga_a_mao(con_temp, valor=999, descricao="Reforma")                                    # mesma categoria, outro valor
    paga_a_mao(con_temp, valor=1000, descricao="Salário", categoria="Retirada")             # Retirada nunca é conta recorrente
    paga_a_mao(con_temp, valor=1000, descricao="Sala 2", data="2025-12-05")                 # antes do início da recorrência
    descartada = paga_a_mao(con_temp, valor=1000, descricao="Outro aluguel")
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET sem_recorrencia=1 WHERE id=?", (descartada,))
    ligada = paga_a_mao(con_temp, valor=1000, descricao="Já ligado", data="2026-12-05")
    financeiro.ligar_recorrencia(con_temp, ligada, rid)
    achados = {s["id"]: s for s in financeiro.saidas_parecidas(con_temp)}
    assert set(achados) == {a, b}
    assert achados[a]["candidatos"][0]["casou_por"] == "descricao" and achados[b]["candidatos"][0]["casou_por"] == "categoria+valor"
    assert not achados[a]["candidatos"][0]["ja_baixada"] and achados[b]["pago_em"] is None


def test_saidas_parecidas_avisa_pagamento_em_dobro(con_temp):
    rid = recorrencia(con_temp)
    financeiro.baixar_recorrencia(con_temp, rid, "2026-10", 1000, "2026-10-06")
    paga_a_mao(con_temp)
    (achado,) = financeiro.saidas_parecidas(con_temp)
    assert achado["candidatos"][0]["ja_baixada"] is True


def test_retirada_recorrente_nao_deixa_custo_negativo(con_temp):
    with con_temp:
        rid = con_temp.execute("INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio)"
                               " VALUES ('PJ','Salário','Retirada',3000,5,1,'2026-01')").lastrowid
    financeiro.baixar_recorrencia(con_temp, rid, "2026-10", 3000, "2026-10-05")
    lancar(con_temp, "entrada", 10000, "2026-10-02", pago_em="2026-10-02")
    resumo = financeiro.resumo_mes(con_temp, "2026-10")
    assert (resumo["custos_fixos"], resumo["custos_variaveis"], resumo["retirada"], resumo["lucro"]) == (0, 0, 3000, 10000)
    assert [r["id"] for r in financeiro.recorrencias_retirada(con_temp)] == [rid]


# ---------- Empréstimo da PJ não é receita ----------
EMP = financeiro.EMPRESTIMO


def test_emprestimo_nao_paga_das_nem_entra_no_lucro(con_temp):
    saldo(con_temp, "Contabilizei Bank", 0, "2026-10-01")
    lancar(con_temp, "entrada", 1000, "2026-10-05", pago_em="2026-10-05")                         # mensalidade
    lancar(con_temp, "entrada", 5000, "2026-10-06", pago_em="2026-10-06", categoria=EMP)         # empréstimo
    lancar(con_temp, "saida", 700, "2026-10-08", pago_em="2026-10-08", categoria=financeiro.DEVOLUCAO)
    assert financeiro._receita_pj(con_temp, "2026-10") == 1000
    r = financeiro.resumo_mes(con_temp, "2026-10")
    assert (r["receita"], r["custos_variaveis"], r["lucro"]) == (1000, 0, 1000)
    assert (r["emprestimos"], r["devolucoes"]) == (5000, 700)
    # o dinheiro está na conta: o "tem" conta o empréstimo, o DAS (6%) só a mensalidade
    pj = financeiro.saldo_livre(con_temp, "2026-10-16")["PJ"]
    assert pj["imposto"] == 60 and pj["tem"] == 5300


def test_emprestimo_vai_inteiro_para_as_contas_da_pj(con_temp):
    with con_temp:
        con_temp.execute("UPDATE recorrencias SET excluido_em='x'")
    lancar(con_temp, "entrada", 3000, "2026-10-02", pago_em="2026-10-02", categoria=EMP)
    (e,) = financeiro.potes_mes(con_temp, "2026-10")["entradas"]
    assert e["divisao"] == {"imposto": 0, "contas": 3000, "salario": 0, "colchao": 0}
    assert financeiro.texto_divisao(e["divisao"]) == "R$ 3.000,00 contas da pj"


def test_emprestimo_nao_pede_aluno_nem_desconta_mensalidade(con_temp):
    with con_temp:
        con_temp.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Ana', 500, 'ativo')")
    lancar(con_temp, "entrada", 2000, "2026-10-05", pago_em="2026-10-05", categoria=EMP)
    assert financeiro.entradas_sem_aluno(con_temp, "2026-10") == []
    falta, sem = financeiro._mensalidades_a_receber(con_temp, "2026-10")
    assert falta == 500 and sem == []      # sem a regra, os 2000 zerariam a mensalidade da Ana


def test_previsao_ignora_emprestimo_na_base_do_das(con_temp):
    financeiro.salvar_saldos(con_temp, "2026-10-16", {"Contabilizei Bank": 0}, {})
    lancar(con_temp, "entrada", 10000, "2026-10-05", pago_em="2026-10-05", categoria=EMP)
    lancar(con_temp, "entrada", 1000, "2026-10-06", pago_em="2026-10-06")
    descr = {i["descricao"]: i["valor"] for s in financeiro.previsao(con_temp, "2026-10-16")["semanas"] for i in s["itens"]}
    assert descr["DAS estimado (10/2026)"] == 60      # 6% de 1000, não de 11000


def test_parece_emprestimo():
    assert financeiro.parece_emprestimo("PIX recebido - Empréstimo Banco X")
    assert financeiro.parece_emprestimo("capital de giro Dock")
    assert not financeiro.parece_emprestimo("PIX recebido Ana Souza")
    assert not financeiro.parece_emprestimo("CRÉDITO EM CONTA")      # extrato comum: não pode sugerir em toda entrada


# ---------- Lançamentos repetidos ----------
def lanc(con, valor=100, data="2026-10-05", tipo="saida", escopo="PJ", descricao=None, pago_em=None, **extra):
    campos = {"escopo": escopo, "tipo": tipo, "data": data, "pago_em": pago_em, "valor": valor, "categoria": "Outros",
              "descricao": descricao, **extra}
    with con:
        return con.execute(f"INSERT INTO lancamentos ({', '.join(campos)}) VALUES ({', '.join('?' * len(campos))})",
                           tuple(campos.values())).lastrowid


def test_duplicados_mesmo_dia_e_descricao_e_quase_certo(con_temp):
    a = lanc(con_temp, 89.9, descricao="Spotify", pago_em="2026-10-05")
    b = lanc(con_temp, 89.9, descricao="spotify ", pago_em="2026-10-05", conta="Inter", forma="PIX")
    (g,) = financeiro.duplicados(con_temp)
    assert g["certeza"] == "quase certo" and set(g["ids"]) == {a, b}
    assert g["manter"] == b                        # o mais completo fica; o outro vai para a lixeira
    assert [i["manter"] for i in g["itens"]] == [True, False]


def test_duplicados_dias_perto_ou_descricao_diferente_e_talvez(con_temp):
    lanc(con_temp, 50, data="2026-10-05", descricao="Uber")
    lanc(con_temp, 50, data="2026-10-07", descricao="Uber centro")
    (g,) = financeiro.duplicados(con_temp)
    assert g["certeza"] == "talvez"
    lanc(con_temp, 50, data="2026-10-20", descricao="Uber")             # longe demais: outro lançamento
    assert len(financeiro.duplicados(con_temp)) == 1


def test_duplicados_tres_copias_viram_um_grupo(con_temp):
    ids = [lanc(con_temp, 30, descricao="Café") for _ in range(3)]
    (g,) = financeiro.duplicados(con_temp)
    assert sorted(g["ids"]) == sorted(ids) and g["manter"] == min(ids)     # empate: o mais antigo


def test_duplicados_o_que_prova_que_sao_dois(con_temp):
    lanc(con_temp, 200, descricao="Parcela", parcela_num=1, parcela_total=3)
    lanc(con_temp, 200, descricao="Parcela", parcela_num=2, parcela_total=3)       # parcelas diferentes
    lanc(con_temp, 400, tipo="entrada", cliente_id=None, contraparte="Ana Souza")
    lanc(con_temp, 400, tipo="entrada", contraparte="Bia Lima")                    # quem pagou é outro
    lanc(con_temp, 70, conta="Inter")
    lanc(con_temp, 70, conta="Itaú")                                               # conta diferente
    lanc(con_temp, 10, escopo="PF")
    lanc(con_temp, 10, escopo="PJ")                                                # escopo diferente
    lanc(con_temp, 10, tipo="entrada", escopo="PJ")                                # tipo diferente
    assert financeiro.duplicados(con_temp) == []


def test_duplicados_alunos_diferentes_e_mesma_recorrencia_em_meses_diferentes(con_temp):
    with con_temp:
        a = con_temp.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Ana', 400, 'ativo')").lastrowid
        b = con_temp.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Bia', 400, 'ativo')").lastrowid
    lanc(con_temp, 400, tipo="entrada", cliente_id=a, pago_em="2026-10-05")
    lanc(con_temp, 400, tipo="entrada", cliente_id=b, pago_em="2026-10-05")
    rid = recorrencia(con_temp, valor=1000)
    lanc(con_temp, 1000, data="2026-09-30", recorrencia_id=rid, competencia="2026-09", pago_em="2026-09-30")
    lanc(con_temp, 1000, data="2026-10-01", recorrencia_id=rid, competencia="2026-10", pago_em="2026-10-01")
    assert financeiro.duplicados(con_temp) == []


def test_duplicados_excluido_some_e_nao_e_repetido_nao_volta(con_temp):
    a, b = lanc(con_temp, 60, descricao="Água"), lanc(con_temp, 60, descricao="Água")
    assert len(financeiro.duplicados(con_temp)) == 1
    with con_temp:
        con_temp.execute("INSERT INTO duplicados_ok (a, b) VALUES (?, ?)", (a, b))
    assert financeiro.duplicados(con_temp) == []
    c = lanc(con_temp, 60, descricao="Água")                  # um terceiro igual: avisa só dos pares novos
    (g,) = financeiro.duplicados(con_temp)
    assert c in g["ids"]
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET excluido_em='x' WHERE id=?", (c,))
    assert financeiro.duplicados(con_temp) == []


def test_duplicados_nao_repete_o_aviso_de_conta_parecida_com_recorrente(con_temp):
    rid = recorrencia(con_temp, valor=1000)
    financeiro.baixar_recorrencia(con_temp, rid, "2026-10", 1000, "2026-10-06")
    paga_a_mao(con_temp)                       # já aparece em saidas_parecidas
    assert financeiro.saidas_parecidas(con_temp) and financeiro.duplicados(con_temp) == []


def test_duplicados_data_ruim_nao_quebra(con_temp):
    lanc(con_temp, 5, data="2026-13-45")
    lanc(con_temp, 5, data="2026-10-01")
    assert financeiro.duplicados(con_temp) == []


# ---------- Fila de pagamento ----------
def fila(con, hoje="2026-10-16"):
    livre = financeiro.saldo_livre(con, hoje)
    return financeiro.fila_pagamentos(con, livre, hoje), livre


def rec_pj(con, descricao, categoria, valor, dia, prioridade=None):
    with con:
        return con.execute("INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio, prioridade)"
                           " VALUES ('PJ',?,?,?,?,1,'2026-10',?)", (descricao, categoria, valor, dia, prioridade)).lastrowid


def test_fila_ordena_por_impacto_e_corta_onde_o_dinheiro_acaba(con_temp):
    saldo(con_temp, "Contabilizei Bank", 1000, "2026-10-16")
    lancar(con_temp, "saida", 600, "2026-10-20", categoria="Aluguel")                      # 40 + 4 + 33 = 77
    lancar(con_temp, "saida", 300, "2026-10-18", categoria="Marketing/Divulgação")         # 0 + 7 + 0 = 7
    lancar(con_temp, "saida", 200, "2026-10-30", categoria="Software/Assinaturas")         # 40 + 0 + 6 = 46
    q, livre = fila(con_temp)
    pj = q["PJ"]
    assert [(i["categoria"], i["nota"]) for i in pj["itens"]] == [("Aluguel", 77), ("Software/Assinaturas", 46), ("Marketing/Divulgação", 7)]
    assert [i["coberto"] for i in pj["itens"]] == [True, True, False] and pj["cobertos"] == 2
    assert not pj["tudo_coberto"] and pj["sobra"] == 200 and livre["PJ"]["livre"] == -100
    assert pj["itens"][0]["esta_semana"] and not pj["itens"][1]["esta_semana"]            # vence em 4 dias / em 14
    assert pj["itens"][0]["custo_atraso"] == 66 and "essencial" in pj["itens"][0]["motivo"] and "vence em 4 dias" in pj["itens"][0]["motivo"]


def test_fila_conta_vencida_sobe_e_diz_ha_quantos_dias(con_temp):
    saldo(con_temp, "Contabilizei Bank", 5000, "2026-10-01")
    lancar(con_temp, "saida", 100, "2026-10-10", categoria="Material de Trabalho")        # 30 + 10 + 0
    lancar(con_temp, "saida", 100, "2026-10-17", categoria="Material de Trabalho")        # 30 + 7 + 0
    a, b = fila(con_temp)[0]["PJ"]["itens"]
    assert (a["nota"], b["nota"]) == (40, 37) and "atrasada há 6 dias" in a["motivo"]


def test_fila_escolha_manual_vence_o_automatico(con_temp):
    saldo(con_temp, "Contabilizei Bank", 5000, "2026-10-01")
    rid = rec_pj(con_temp, "Aluguel", "Aluguel", 600, 20)
    lancar(con_temp, "saida", 300, "2026-10-18", categoria="Marketing/Divulgação")
    assert fila(con_temp)[0]["PJ"]["itens"][0]["descricao"] == "Aluguel"
    with con_temp:
        con_temp.execute("UPDATE recorrencias SET prioridade=-1 WHERE id=?", (rid,))      # "pode esperar"
    itens = fila(con_temp)[0]["PJ"]["itens"]
    assert [i["descricao"] for i in itens] == ["Marketing/Divulgação", "Aluguel"] and "pode esperar" in itens[1]["motivo"]
    with con_temp:
        con_temp.execute("UPDATE recorrencias SET prioridade=1 WHERE id=?", (rid,))       # "sempre primeiro"
        con_temp.execute("UPDATE lancamentos SET categoria='Aluguel'")                    # até o outro virar aluguel: a escolha pesa mais
    assert fila(con_temp)[0]["PJ"]["itens"][0]["descricao"] == "Aluguel"


def test_fila_inclui_das_e_salario_e_bate_com_o_saldo_livre(con_temp):
    saldo(con_temp, "Contabilizei Bank", 100, "2026-10-01")
    ligar_salario(con_temp, valor=1000, dia=5)
    lancar(con_temp, "entrada", 1000, "2026-09-10", pago_em="2026-09-10")               # receita de setembro: DAS de outubro = 60
    lancar(con_temp, "saida", 50, "2026-10-25", categoria="Aluguel")
    q, livre = fila(con_temp)
    pj, l = q["PJ"], livre["PJ"]
    nomes = [i["descricao"] for i in pj["itens"]]
    assert "Guardar o DAS de 10/2026" in nomes and "Salário 10/2026 para a PF" in nomes
    assert round(sum(i["valor"] for i in pj["itens"]), 2) == round(l["comprometido"] + l["imposto"] + l["salario"], 2)
    assert pj["tudo_coberto"] == (l["livre"] >= 0)


def test_fila_sem_saldo_digitado_nao_da_nada_como_coberto(con_temp):
    lancar(con_temp, "saida", 10, "2026-10-20", categoria="Aluguel")
    pj = fila(con_temp)[0]["PJ"]
    assert pj["sem_saldo"] and pj["cobertos"] == 0 and not any(i["coberto"] for i in pj["itens"])


def test_fila_categoria_sem_padrao_usa_20_e_2_por_cento(con_temp):
    saldo(con_temp, "Contabilizei Bank", 5000, "2026-10-01")
    lancar(con_temp, "saida", 1000, "2026-10-30", categoria="Categoria Nova")
    (i,) = fila(con_temp)[0]["PJ"]["itens"]
    assert (i["nota"], i["custo_atraso"]) == (20 + 0 + 6, 20)
