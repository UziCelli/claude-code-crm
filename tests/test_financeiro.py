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


def lancar(con, tipo, valor, data, pago_em=None, escopo="PJ", recorrencia_id=None, competencia=None):
    with con:
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, recorrencia_id, competencia)"
                    " VALUES (?,?,?,?,?,'Outros',?,?)", (escopo, tipo, data, pago_em, valor, recorrencia_id, competencia))


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
    assert livre["comprometido"] == 1000 and livre["livre"] == 2000


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
