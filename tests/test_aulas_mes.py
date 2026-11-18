"""Aulas do mês na Agenda: contratadas (plano), previstas (horários fixos do mês), feitas, faltam, "mês 100%" e "passou" (com o custo na CIA)."""
import datetime as dt

from app import db, main
from tests.test_agenda import grava, http  # noqa: F401  (http é fixture: banco temporário)

DEZ = dt.date(2026, 12, 31)   # dezembro de 2026 tem 5 terças e 5 quintas


def aluno(nome, plano, local="CIA", pessoas=1, tipo="Mensalidade"):
    return grava("INSERT INTO clientes (nome, status, local, tipo_servico, plano, pessoas, data_inicio) VALUES (?, 'ativo', ?, ?, ?, ?, '2026-01-01')",
                 nome, local, tipo, plano, pessoas)


def fixo(cid, dia, hora, local="CIA"):
    return grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?,?,?,?)", cid, dia, hora, local)


def feita(cid, data, hora=7):
    grava("INSERT INTO cliente_eventos (cliente_id, tipo, data, hora) VALUES (?, 'aula', ?, ?)", cid, data, hora)


def resumo(mes="2026-12", hoje=DEZ, **kw):
    con = db.conectar()
    try:
        return {a["nome"]: a for a in main.resumo_aulas_mes(con, mes, hoje, **kw)["alunos"]}
    finally:
        con.close()


def test_mensalidade_2x_em_mes_de_5_semanas_passou_e_custa_na_cia(http):
    ana = aluno("Ana", "Mensalidade 2x/semana")
    fixo(ana, 2, 7), fixo(ana, 4, 7)
    for d in ("01", "03", "08", "10", "15", "17", "22", "24", "29"):
        feita(ana, f"2026-12-{d}")
    a = resumo()["Ana"]
    assert (a["contratadas"], a["previstas"], a["feitas"]) == (8, 10, 9)
    assert a["completo"] and a["faltam"] == 0 and a["passou"] == 2 and a["cia"]
    con = db.conectar()
    taxa = db.parametros(con, "taxa_cia")["1"]
    con.close()
    assert a["custo_extra"] == round(2 * taxa, 2)


def test_novembro_normal_fica_100_por_cento_sem_passar(http):
    ana = aluno("Ana", "Mensalidade 2x/semana")
    fixo(ana, 2, 7), fixo(ana, 4, 7)
    for d in ("03", "05", "10", "12", "17", "19", "24", "26"):
        feita(ana, f"2026-11-{d}")
    a = resumo("2026-11", dt.date(2026, 11, 30))["Ana"]
    assert (a["contratadas"], a["previstas"], a["feitas"], a["passou"]) == (8, 8, 8, 0) and a["completo"]


def test_faltam_no_meio_do_mes(http):
    bia = aluno("Bia", "Pacote 8 aulas", tipo="Pacote de Aulas")
    fixo(bia, 2, 18)
    feita(bia, "2026-12-01", 18), feita(bia, "2026-12-08", 18)
    b = resumo(hoje=dt.date(2026, 12, 10))["Bia"]
    assert (b["contratadas"], b["feitas"], b["faltam"], b["completo"], b["passou"]) == (8, 2, 6, False, 0)


def test_reposicao_nao_e_prevista_mas_conta_como_feita(http):
    ana = aluno("Ana", "Mensalidade 1x/semana")
    fixo(ana, 2, 7)
    grava("INSERT INTO agenda_avulsas (cliente_id, data, hora, local, reposicao) VALUES (?, '2026-12-05', 9, 'CIA', 1)", ana)
    feita(ana, "2026-12-05", 9)
    a = resumo()["Ana"]
    assert a["previstas"] == 5 and a["feitas"] == 1


def test_mes_pulado_e_bloqueio_nao_contam_como_previstas(http):
    ana = aluno("Ana", "Mensalidade 1x/semana")
    fixo(ana, 2, 7)
    grava("INSERT INTO cliente_eventos (cliente_id, tipo, data, ate) VALUES (?, 'pausa', '2026-12-01', '2026-12-10')", ana)   # pula 01 e 08
    assert resumo()["Ana"]["previstas"] == 3


def test_smart_fit_passa_mas_sem_custo(http):
    joao = aluno("Joao", "Mensalidade 2x/semana", local="SmartFit")
    fixo(joao, 2, 20, "SmartFit"), fixo(joao, 4, 20, "SmartFit")
    j = resumo()["Joao"]
    assert j["passou"] == 2 and not j["cia"] and j["custo_extra"] == 0


def test_consultoria_sem_meta_e_parametro_muda_as_contratadas(http):
    aluno("Carla", "Consultoria Online", local="Online", tipo="Consultoria Online")
    ana = aluno("Ana", "Mensalidade 2x/semana")
    fixo(ana, 2, 7)
    assert "Carla" not in resumo()   # sem aula e sem meta: não aparece
    grava("UPDATE parametros SET valor=5 WHERE grupo='agenda' AND chave='semanas_contratadas'")
    assert resumo()["Ana"]["contratadas"] == 10


def test_agenda_mostra_o_card_e_o_painel_do_aluno(http):
    ana = aluno("Ana", "Mensalidade 2x/semana")
    fixo(ana, 2, 7), fixo(ana, 4, 7)
    pg = http.get("/agenda").text
    assert 'id="aulas-mes"' in pg and "contratadas" in pg and "Ana" in pg.split('id="aulas-mes"')[1]
    pg = http.get(f"/agenda?aluno={ana}").text
    assert "<span>Contratadas</span>" in pg and "<span>Previstas</span>" in pg
    cfg = http.get("/configuracoes").text
    assert "semanas contratadas por mês" in cfg


def test_dupla_na_cia_divide_o_custo_da_aula_extra(http):
    """A CIA cobra a aula pelo nº de pessoas no horário: a dupla divide a aula, e o total é o de uma aula a mais, não o de duas."""
    a, b = aluno("Ana", "Mensalidade 1x/semana"), aluno("Bia", "Mensalidade 1x/semana")
    fixo(a, 2, 7), fixo(b, 2, 7)   # 5 terças em dezembro: passou +1 cada
    r = resumo()
    con = db.conectar()
    taxa2 = db.parametros(con, "taxa_cia")["2"]
    con.close()
    assert r["Ana"]["passou"] == r["Bia"]["passou"] == 1
    assert abs(r["Ana"]["custo_extra"] + r["Bia"]["custo_extra"] - taxa2) <= 0.01   # uma aula a mais (centavo do arredondamento)
