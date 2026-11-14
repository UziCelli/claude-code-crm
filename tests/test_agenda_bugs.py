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


def test_dockerfile_da_nuvem_tem_o_fuso():
    texto = open(os.path.join(os.path.dirname(__file__), "..", "Dockerfile"), encoding="utf-8").read()
    assert "TZ=America/Sao_Paulo" in texto and "CRM_NUVEM=1" in texto


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


def test_reativar_pela_ficha_tambem_tira_do_lotado(http):
    a, b, c = aluno("Ana", status="inativo"), aluno("Bia"), aluno("Caio")
    fixo(a, 1, 7); fixo(b, 1, 7); fixo(c, 1, 7)
    r = http.post(f"/clientes/{a}", data={"nome": "Ana", "status": "ativo"}, follow_redirects=False)
    assert "Saiu do horário fixo de Seg 07h" in (msg(r) or "")
    assert [n for n, *_ in fixos_ativos(1, 7)] == ["Bia", "Caio"]
    r = http.post(f"/clientes/{b}", data={"nome": "Bia", "status": "ativo"}, follow_redirects=False)   # já era ativa: não mexe
    assert "Saiu" not in (msg(r) or "") and [n for n, *_ in fixos_ativos(1, 7)] == ["Bia", "Caio"]


def test_restaurar_aluno_da_lixeira_tira_do_horario_que_lotou(http):
    a, b, c = aluno("Ana"), aluno("Bia"), aluno("Caio")
    fixo(a, 1, 7); fixo(b, 1, 7); fixo(c, 1, 7)
    grava("UPDATE clientes SET excluido_em=? WHERE id=?", main.agora_txt(), a)
    r = http.post("/lixeira/restaurar", data={"tabela": "clientes", "rid": a}, follow_redirects=False)
    assert "Registro restaurado. Saiu do horário fixo de Seg 07h" in (msg(r) or "")
    assert [n for n, *_ in fixos_ativos(1, 7)] == ["Bia", "Caio"]


def test_restaurar_horario_antigo_da_lixeira_vale_so_daqui_para_frente(http):
    """Seg 07h no local A desde setembro; em 05/10 passou para B; em 19/10 saiu do horário. Restaurar a linha de A
    não pode mudar outubro (12/10 foi em B, 26/10 não tinha aula): volta a valer de hoje em diante."""
    a = aluno("Ana", data_inicio="2026-09-01")
    r1 = grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, criado_em, excluido_em) VALUES (?,1,7,'A',?,'2026-10-05 10:00:00')", a, ANTES)
    grava("""INSERT INTO agenda_fixos (cliente_id, dia, hora, local, vigente_de, criado_em, excluido_em)
             VALUES (?,1,7,'B','2026-10-05','2026-10-05 10:00:00','2026-10-19 10:00:00')""", a)
    antes = aulas(dt.date(2026, 10, 12)), aulas(dt.date(2026, 10, 26))
    assert [x[2] for x in antes[0]] == ["B"] and antes[1] == []
    r = http.post("/lixeira/restaurar", data={"tabela": "agenda_fixos", "rid": r1}, follow_redirects=False)
    assert msg(r) == "Registro restaurado."
    assert (aulas(dt.date(2026, 10, 12)), aulas(dt.date(2026, 10, 26))) == antes
    hoje = dt.date.today()
    proxima = hoje + dt.timedelta(days=7 - hoje.weekday())
    assert [x[2] for x in aulas(proxima, hoje)] == ["A"]
    assert fixos_ativos(1, 7) == [("Ana", 1, 7, "A")]
    assert consulta("SELECT excluido_em FROM agenda_fixos WHERE id=?", r1) == [("2026-10-05 10:00:00",)]   # a antiga fica como estava


def test_lixeira_mostra_so_o_horario_mais_novo_e_excluido_hoje_volta_inteiro(http):
    a = aluno("Ana")
    r1 = grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, criado_em, excluido_em) VALUES (?,1,7,'A',?,?)",
               a, ANTES, main.agora_txt())
    assert "Ana — Seg 07h (A)" in http.get("/dados").text
    r = http.post("/lixeira/restaurar", data={"tabela": "agenda_fixos", "rid": r1}, follow_redirects=False)
    assert msg(r) == "Registro restaurado."
    assert consulta("SELECT COUNT(*), MAX(excluido_em) FROM agenda_fixos WHERE cliente_id=?", a) == [(1, None)]   # excluído hoje: só desfaz
    b = aluno("Bia")
    grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, criado_em, excluido_em) VALUES (?,2,8,'A',?,?)",
          b, ANTES, main.agora_txt())
    grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?,2,8,'B')", b)   # trocou de local: a linha antiga sai da lista
    assert "Bia — Ter 08h (A)" not in http.get("/dados").text


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
    assert main.fixo_vale(r, "2026-10-20") and not main.fixo_vale(r, "2026-10-21")   # excluído no dia 20: a aula do dia 20 fica
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


# ---------- PR 98: bugs achados na revisão da Agenda ----------

def test_avulsa_em_cima_da_propria_fixa_desmarcada_e_recusada(http):
    """Avulsa comum no horário da própria fixa desmarcada misturava as marcações (marcar a avulsa apagava o desmarcou e a reposição)."""
    a = aluno("Ana")
    fixo(a, 1, 7)
    marcar(http, a, SEG, 7, "desmarcou")
    r = incluir(http, cliente_id=a, local="CIA", repetir=0, data=SEG, hora=7)
    assert "horário fixo de Ana" in (erro(r) or "")
    assert not consulta("SELECT 1 FROM agenda_avulsas WHERE cliente_id=?", a)
    assert alunos_do_card(http, 1, 7) == ["Ana"]


def test_reposicao_marcada_pela_ficha_sem_hora_desconta_do_saldo(http):
    a = aluno("Ana")
    grava("INSERT INTO cliente_eventos (cliente_id, tipo, data, hora) VALUES (?, 'desmarcou', '2026-10-05', 7)", a)
    grava("INSERT INTO agenda_avulsas (cliente_id, data, hora, local, reposicao) VALUES (?, '2026-10-13', 10, 'CIA', 1)", a)
    grava("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', '2026-10-13')", a)   # lançada pela ficha: sem hora
    con = db.conectar()
    try:
        s = main.saldos_reposicao(con, [a], dt.date(2026, 10, 15))[a]
    finally:
        con.close()
    assert (s["usadas"], s["saldo"], s["sem_marca"], s["a_agendar"]) == (1, 0, 0, 0)


def test_excluir_avulsa_marcada_leva_a_marcacao_junto(http):
    a = aluno("Ana")
    aid = grava("INSERT INTO agenda_avulsas (cliente_id, data, hora, local) VALUES (?, ?, 10, 'CIA')", a, SEG)
    marcar(http, a, SEG, 10, "feita", avulsa=1)
    r = http.post(f"/agenda/avulsa/{aid}/excluir", data={"semana": SEG}, follow_redirects=False)
    assert "marcação dela" in (msg(r) or "")
    assert not consulta("SELECT 1 FROM cliente_eventos WHERE cliente_id=? AND tipo='aula' AND excluido_em IS NULL", a)
    r = http.post(f"/agenda/avulsa/{aid}/excluir", data={"semana": SEG}, follow_redirects=False)   # 2º clique
    assert "já foi excluída" in (erro(r) or "")


def test_excluir_avulsa_mantem_a_marcacao_da_fixa_no_mesmo_horario(http):
    """Dado antigo: avulsa no horário da própria fixa. A marcação é da fixa também: fica."""
    a = aluno("Ana")
    fixo(a, 1, 7)
    aid = grava("INSERT INTO agenda_avulsas (cliente_id, data, hora, local) VALUES (?, ?, 7, 'CIA')", a, SEG)
    marcar(http, a, SEG, 7, "feita")
    r = http.post(f"/agenda/avulsa/{aid}/excluir", data={"semana": SEG}, follow_redirects=False)
    assert "marcação dela" not in (msg(r) or "")
    assert consulta("SELECT tipo FROM cliente_eventos WHERE cliente_id=? AND excluido_em IS NULL AND tipo='aula'", a) == [("aula",)]


def _troca_de_hora_no_dia(marcar_antiga=True, marcar_nova=False):
    """Ana tinha Seg 9h desde antes; na segunda 12/10 a aula das 9h é marcada e às 11h ela passa para Seg 10h (vigente no mesmo dia)."""
    a = aluno("Ana")
    grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, criado_em, excluido_em) VALUES (?, 1, 9, 'CIA', ?, ?)", a, ANTES, SEG + " 11:00:00")
    grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, vigente_de, criado_em) VALUES (?, 1, 10, 'CIA', ?, ?)", a, SEG, SEG + " 11:00:00")
    if marcar_antiga:
        grava("INSERT INTO cliente_eventos (cliente_id, tipo, data, hora) VALUES (?, 'aula', ?, 9)", a, SEG)
    if marcar_nova:
        grava("INSERT INTO cliente_eventos (cliente_id, tipo, data, hora) VALUES (?, 'aula', ?, 10)", a, SEG)
    return a


def test_mudar_de_hora_no_dia_mantem_a_aula_ja_marcada(http):
    _troca_de_hora_no_dia()
    seg = dt.date.fromisoformat(SEG)
    assert [x for x in aulas(seg) if x[0] == SEG] == [(SEG, 9, "CIA", "feita")]   # a feita das 9h não some; a das 10h começa na outra semana
    assert [x for x in aulas(seg + dt.timedelta(days=7)) if x[1] in (9, 10)] == [("2026-10-19", 10, "CIA", "pendente")]


def test_mudar_de_hora_no_dia_sem_marca_continua_valendo_a_nova(http):
    _troca_de_hora_no_dia(marcar_antiga=False)
    assert [x for x in aulas(dt.date.fromisoformat(SEG)) if x[0] == SEG] == [(SEG, 10, "CIA", "pendente")]


def test_mudar_de_hora_no_dia_com_as_duas_marcadas_mostra_as_duas(http):
    _troca_de_hora_no_dia(marcar_nova=True)
    assert [x for x in aulas(dt.date.fromisoformat(SEG)) if x[0] == SEG] == [(SEG, 9, "CIA", "feita"), (SEG, 10, "CIA", "feita")]
