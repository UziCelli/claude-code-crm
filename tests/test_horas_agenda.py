"""Horas de trabalho pela Agenda (Victor, 18/11/2026): aulas e deslocamento vêm dos horários fixos; o plano só vale para quem não tem horário."""
import pytest
from fastapi.testclient import TestClient

from app import main, precos
from tests.test_horas_base import con  # noqa: F401  (banco temporário)
from tests.test_salario_hora import aluno, gasto_pf

S = main.SEMANAS_MES


def fixo(con, cid, dia, hora, local="CIA"):  # noqa: F811
    with con:
        con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?,?,?,?)", (cid, dia, hora, local))


def cid(con, nome):  # noqa: F811
    return con.execute("SELECT id FROM clientes WHERE nome=?", (nome,)).fetchone()[0]


def horas(con):  # noqa: F811
    return main.horas_trabalho_detalhe(con, precos.carregar_parametros(con))


def ida_cia(con, minutos):  # noqa: F811
    with con:
        con.execute("UPDATE parametros SET valor=? WHERE grupo='cia_deslocamento' AND chave='minutos_por_aula'", (minutos,))


def test_sem_horario_continua_pelo_plano(con):  # noqa: F811
    aluno(con, "Ana")   # Pacote 8 aulas, sem horário: 8 h de aula + 1 h de planejamento
    h = horas(con)
    assert h["aulas"] == pytest.approx(8) and h["planejamento"] == pytest.approx(1)


def test_com_horario_as_aulas_vem_da_agenda(con):  # noqa: F811
    aluno(con, "Ana")   # plano diz 8 aulas, mas a Agenda tem 3 horários por semana
    a = cid(con, "Ana")
    for d in (1, 3, 5):
        fixo(con, a, d, 7)
    h = horas(con)
    assert h["aulas"] == pytest.approx(3 * S) and h["planejamento"] == pytest.approx(1)


def test_dupla_no_mesmo_horario_conta_uma_hora_so(con):  # noqa: F811
    aluno(con, "Edilene")
    aluno(con, "Marcos")
    fixo(con, cid(con, "Edilene"), 2, 18)
    fixo(con, cid(con, "Marcos"), 2, 18)
    h = horas(con)
    assert h["aulas"] == pytest.approx(1 * S) and h["planejamento"] == pytest.approx(2)   # planejamento é de cada aluno


def test_deslocamento_e_do_local_de_cada_horario(con):  # noqa: F811
    ida_cia(con, 30)
    aluno(con, "Ana")
    a = cid(con, "Ana")
    fixo(con, a, 1, 7, "CIA")
    fixo(con, a, 3, 7, "Online")   # local sem custo de deslocamento
    assert horas(con)["deslocamento"] == pytest.approx(30 / 60 * S)


def test_salario_hora_usa_as_horas_da_agenda(con):  # noqa: F811
    aluno(con, "Ana")
    fixo(con, cid(con, "Ana"), 1, 7)
    gasto_pf(con, 4500, -1)
    sh = precos.carregar_parametros(con)["salario_hora"]
    assert sh["horas"] == pytest.approx(S + 1, abs=0.1) and set(sh["partes"]) == set(precos.PARTES_TRABALHO)


def test_divergencias_plano_agenda(con):  # noqa: F811
    aluno(con, "Ana")   # Pacote 8 = 2 por semana; Agenda com 3
    aluno(con, "Bia")   # Pacote 8 sem horário nenhum
    aluno(con, "Caio")  # Pacote 8 com 2 horários: bate
    for d in (1, 3, 5):
        fixo(con, cid(con, "Ana"), d, 7)
    for d in (2, 4):
        fixo(con, cid(con, "Caio"), d, 9)
    dv = {d["nome"]: d for d in main.divergencias_plano_agenda(con)}
    assert set(dv) == {"Ana", "Bia"} and dv["Ana"]["agenda"] == 3 and dv["Bia"]["agenda"] == 0 and dv["Ana"]["por_semana"] == 2
    pg = TestClient(main.app, base_url="http://localhost").get("/calculos").text
    assert 'id="divergencias"' in pg and "Plano diferente da Agenda (2)" in pg
