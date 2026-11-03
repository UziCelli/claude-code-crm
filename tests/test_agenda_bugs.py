"""Bugs graves da Agenda (PR 2): fuso, limite de 2 alunos, avulsa duplicada e mudar horário/local sem reescrever o passado."""
import datetime as dt
import os
import time

from app import db, main
from tests.test_agenda import (SEMANA, http, aluno, grava, consulta, fixo, horario, cards, grade, ocupar,  # noqa: F401 (http é fixture)
                               erro, msg, marcar, fixos_ativos)

SEG = SEMANA   # 2026-10-12, segunda (já passou: hoje no teste é depois)
ANTES = "2026-10-01 10:00:00"


def incluir(http, **d):
    return http.post("/agenda/incluir", data={"semana": SEMANA, **d}, follow_redirects=False)


def alunos_do_card(http, dia, hora, quando=SEG):
    achou = cards(http.get("/agenda", params={"semana": quando}).text, dia, hora)
    return [x["nome"] for x in achou[0][0]["alunos"]] if achou else []


def aulas(segunda, hoje=dt.date(2026, 10, 30)):
    con = db.conectar()
    try:
        return [(x["data"], x["hora"], x["local"], x["situacao"]) for x in main.aulas_da_semana(con, segunda, hoje)]
    finally:
        con.close()


# ---------- bug 3: fuso ----------

def test_app_roda_no_fuso_do_brasil():
    assert os.environ.get("TZ") == "America/Sao_Paulo"
    assert time.strftime("%z") in ("-0300", "-0200")


def test_render_yaml_tem_o_fuso():
    texto = open(os.path.join(os.path.dirname(__file__), "..", "render.yaml"), encoding="utf-8").read()
    assert "TZ" in texto and "America/Sao_Paulo" in texto


def test_status_grava_a_data_de_hoje_do_python(http):
    a = aluno("Ana")
    http.post(f"/clientes/{a}/status", data={"status": "inativo"}, follow_redirects=False)
    assert consulta("SELECT data FROM cliente_eventos WHERE cliente_id=? AND tipo='status'", a) == [(dt.date.today().isoformat(),)]


# ---------- bug 4: no máximo 2 alunos ----------

def test_avulsa_em_horario_cheio_e_recusada(http):
    a, b, c = aluno("Ana"), aluno("Bia"), aluno("Caio")
    fixo(a, 1, 7); fixo(b, 1, 7)
    r = incluir(http, cliente_id=c, local="CIA", repetir=0, data=SEG, hora=7)
    assert "Horário cheio" in (erro(r) or "")
    assert len(alunos_do_card(http, 1, 7)) == 2
    assert not consulta("SELECT 1 FROM agenda_avulsas WHERE cliente_id=?", c)


def test_avulsa_conta_vaga_de_quem_desmarcou(http):
    a, b, c = aluno("Ana"), aluno("Bia"), aluno("Caio")
    fixo(a, 1, 7); fixo(b, 1, 7)
    marcar(http, a, SEG, 7, "desmarcou")
    assert erro(incluir(http, cliente_id=c, local="CIA", repetir=0, data=SEG, hora=7)) is None


def test_avulsa_no_proprio_horario_fixo_e_recusada(http):
    a = aluno("Ana")
    fixo(a, 1, 7)
    assert "já tem aula fixa" in (erro(incluir(http, cliente_id=a, local="CIA", repetir=0, data=SEG, hora=7)) or "")


def test_reativar_aluno_em_horario_que_lotou_tira_ele_de_la(http):
    a, b, c = aluno("Ana"), aluno("Bia"), aluno("Caio")
    horario(http, 1, 7, a, b)
    grava("UPDATE clientes SET status='inativo' WHERE id=?", a)
    assert erro(incluir(http, cliente_id=c, local="CIA", repetir=1, dia=1, hora=7)) is None
    r = http.post(f"/clientes/{a}/status", data={"status": "ativo"}, follow_redirects=False)
    assert "Saiu do horário fixo de Seg 07h" in (msg(r) or "")
    assert sorted(alunos_do_card(http, 1, 7, quando=dt.date.today().isoformat())) == ["Bia", "Caio"]
    assert ("Ana", 1, 7, "CIA") not in fixos_ativos()
    assert all(cid != a for _, _, cid, _ in grade(1, 7))


def test_reativar_com_vaga_mantem_o_horario(http):
    a, b = aluno("Ana"), aluno("Bia")
    fixo(a, 1, 7); fixo(b, 1, 7)
    grava("UPDATE clientes SET status='inativo' WHERE id=?", a)
    r = http.post(f"/clientes/{a}/status", data={"status": "ativo"}, follow_redirects=False)
    assert "Saiu" not in (msg(r) or "")
    assert len(fixos_ativos(1, 7)) == 2


def test_reativar_pela_renovacao_tambem_tira_do_lotado(http):
    a, b, c = aluno("Ana", status="inativo"), aluno("Bia"), aluno("Caio")
    fixo(a, 1, 7); fixo(b, 1, 7); fixo(c, 1, 7)
    con = db.conectar()
    try:
        texto, falha = main.registrar_evento(con, a, "renovacao", dt.date.today().isoformat(), "100")
    finally:
        con.close()
    assert falha is None and "Saiu do horário fixo de Seg 07h" in texto
    assert [n for n, *_ in fixos_ativos(1, 7)] == ["Bia", "Caio"]


# ---------- bug 6: avulsa duplicada ----------

def test_avulsa_duplicada_e_recusada_e_saldo_conta_uma(http):
    a = aluno("Ana")
    for d in ("2026-10-05", "2026-10-06"):
        marcar(http, a, d, 7, "desmarcou")
    assert erro(incluir(http, cliente_id=a, local="CIA", repetir=0, data=SEG, hora=9, reposicao=1)) is None
    r = incluir(http, cliente_id=a, local="CIA", repetir=0, data=SEG, hora=9, reposicao=1)   # clique duplo
    assert "já tem aula avulsa" in (erro(r) or "")
    assert alunos_do_card(http, 1, 9) == ["Ana"]
    marcar(http, a, SEG, 9, "feita", avulsa=1)
    con = db.conectar()
    try:
        s = main.saldos_reposicao(con, [a])[a]
        ctl = main.controle_aluno(con, a, "2026-10", dt.date(2026, 10, 20))
    finally:
        con.close()
    assert (s["usadas"], s["saldo"]) == (1, 1)
    assert ctl["feitas"] == 1


def test_duplicata_antiga_no_banco_conta_uma_vez(http):
    a = aluno("Ana")
    for d in ("2026-10-05", "2026-10-06"):
        marcar(http, a, d, 7, "desmarcou")
    for _ in range(2):   # gravada antes da correção
        grava("INSERT INTO agenda_avulsas (cliente_id, data, hora, local, reposicao) VALUES (?,?,9,'CIA',1)", a, SEG)
    marcar(http, a, SEG, 9, "feita", avulsa=1)
    con = db.conectar()
    try:
        s = main.saldos_reposicao(con, [a])[a]
        ctl = main.controle_aluno(con, a, "2026-10", dt.date(2026, 10, 20))
    finally:
        con.close()
    assert (s["usadas"], s["saldo"]) == (1, 1)
    assert ctl["feitas"] == 1


# ---------- bug 5: mudar horário ou local não reescreve o passado ----------

def test_mover_horario_mantem_a_aula_feita_na_semana_passada(http):
    a = aluno("Ana")
    horario(http, 1, 7, a)
    grava("UPDATE agenda_fixos SET criado_em=?", ANTES)   # horário antigo, de antes de hoje
    marcar(http, a, SEG, 7, "feita")
    horario(http, 1, 7, "")
    horario(http, 2, 8, a)
    assert aulas(dt.date(2026, 10, 12)) == [("2026-10-12", 7, "CIA", "feita")]
    hoje = dt.date.today()
    proxima = hoje + dt.timedelta(days=7 - hoje.weekday())   # segunda que vem: só o horário novo
    assert aulas(proxima, hoje) == [((proxima + dt.timedelta(days=1)).isoformat(), 8, "CIA", "futura")]


def test_trocar_local_vale_dali_para_frente(http):
    a = aluno("Ana")
    horario(http, 1, 7, a, local="CIA")
    grava("UPDATE agenda_fixos SET criado_em=?", ANTES)
    horario(http, 1, 7, a, local="SmartFit")
    assert aulas(dt.date(2026, 10, 12))[0][:3] == ("2026-10-12", 7, "CIA")
    proxima = dt.date.today() + dt.timedelta(days=7 - dt.date.today().weekday())
    assert aulas(proxima, dt.date.today())[0][:3] == (proxima.isoformat(), 7, "SmartFit")
    assert fixos_ativos(1, 7) == [("Ana", 1, 7, "SmartFit")]


def test_horario_ajustado_no_mesmo_dia_nao_deixa_rastro(http):
    a = aluno("Ana")
    horario(http, 1, 7, a)        # criado hoje...
    horario(http, 1, 7, "")       # ... e tirado hoje: foi engano
    horario(http, 2, 8, a)
    assert consulta("SELECT vigente_de FROM agenda_fixos WHERE excluido_em IS NULL") == [(None,)]
    assert aulas(dt.date(2026, 10, 12)) == [("2026-10-13", 8, "CIA", "pendente")]


def test_fixo_vale():
    r = {"vigente_de": "2026-10-14", "criado_em": "2026-10-14 08:00:00", "excluido_em": "2026-10-20 09:00:00"}
    assert not main.fixo_vale(r, "2026-10-13")
    assert main.fixo_vale(r, "2026-10-14") and main.fixo_vale(r, "2026-10-19")
    assert not main.fixo_vale(r, "2026-10-20")
    assert main.fixo_vale({"vigente_de": None, "criado_em": "2026-10-01", "excluido_em": None}, "2020-01-01")
    assert not main.fixo_vale({"vigente_de": None, "criado_em": "2026-10-20 08:00", "excluido_em": "2026-10-20 09:00"}, "2026-10-19")


def test_vigencias(http):
    a, b, c = aluno("Ana"), aluno("Bia"), aluno("Caio")
    grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, criado_em, excluido_em) VALUES (?,1,7,'CIA',?,?)", a, ANTES, ANTES)
    grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, criado_em) VALUES (?,1,7,'CIA',?)", b, "2026-10-20 08:00:00")
    con = db.conectar()
    try:
        v = main.vigencias(con, [a, b, c, a], hoje=dt.date(2026, 10, 20))
    finally:
        con.close()
    assert v == {a: "2026-10-20", b: None, c: None}
