"""Pendências da Agenda: a_agendar/sem_marca, aulas_da_semana em várias semanas, card Pendências e /agenda/pendentes."""
import datetime as dt

import pytest

from app import db, main, relogio
from tests.test_agenda import http, aluno, grava, fixo, marcar  # noqa: F401 (http é fixture)

HOJE = dt.date(2026, 10, 21)   # quarta; a semana atual começa em 2026-10-19
SEG_ATUAL, SEG_1, SEG_2 = "2026-10-19", "2026-10-12", "2026-10-05"


@pytest.fixture
def hoje_fixo(monkeypatch):
    """O app enxerga 'hoje' como 21/10/2026 (meio-dia em Brasília)."""
    monkeypatch.setattr(relogio, "_utc", lambda: dt.datetime(2026, 10, 21, 15, 0, tzinfo=dt.timezone.utc))


def evento(cid, tipo, data, hora=7):
    return grava("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao, hora) VALUES (?,?,?,?,?)", cid, tipo, data, "teste", hora)


def avulsa_repor(cid, data, hora=7):
    return grava("INSERT INTO agenda_avulsas (cliente_id, data, hora, local, reposicao) VALUES (?,?,?,'CIA',1)", cid, data, hora)


def saldo(cid):
    con = db.conectar()
    try:
        return main.saldos_reposicao(con, [cid], HOJE)[cid]
    finally:
        con.close()


# ---------- a_agendar / sem_marca ----------
def test_reposicao_passada_sem_marca_conta_como_agendada_e_nao_como_a_agendar(http):
    ana = aluno("Ana Silva")
    evento(ana, "desmarcou", "2026-10-05")
    avulsa_repor(ana, "2026-10-14")   # já passou e ninguém marcou: ainda não foi resolvida, então não é "a agendar"
    s = saldo(ana)
    assert (s["saldo"], s["sem_marca"], s["agendadas"], s["a_agendar"]) == (1, 1, 0, 0)


def test_a_agendar_desconta_so_as_sem_marca_e_nunca_fica_negativo(http):
    ana, bia = aluno("Ana Silva"), aluno("Bia Costa")
    for d in ("2026-10-05", "2026-10-06", "2026-10-07"):
        evento(ana, "desmarcou", d)
    avulsa_repor(ana, "2026-10-25")                       # futura, sem marca
    avulsa_repor(ana, "2026-10-15")                       # passada, com Feita: vira "usada"
    evento(ana, "aula", "2026-10-15")
    s = saldo(ana)
    assert (s["devidas"], s["usadas"], s["saldo"], s["sem_marca"], s["agendadas"], s["a_agendar"]) == (3, 1, 2, 1, 1, 1)
    evento(bia, "desmarcou", "2026-10-05")
    avulsa_repor(bia, "2026-10-25")
    avulsa_repor(bia, "2026-10-26")
    assert saldo(bia)["a_agendar"] == 0 and saldo(bia)["sem_marca"] == 2   # mais agendadas que devidas: não fica negativo


def test_chaves_novas_em_todos_os_dicts_padrao(http):
    ana = aluno("Ana Silva")
    con = db.conectar()
    try:
        assert main.saldos_reposicao(con, [ana], HOJE)[ana] == {"devidas": 0, "usadas": 0, "saldo": 0, "agendadas": 0, "sem_marca": 0, "a_agendar": 0}
        assert main.saldos_reposicao(con, [], HOJE) == {}
    finally:
        con.close()


# ---------- aulas_da_semana em várias semanas ----------
def test_duas_semanas_igual_a_duas_chamadas_com_troca_de_horario_no_meio(http):
    ana, bia, cai = aluno("Ana Silva"), aluno("Bia Costa"), aluno("Caio Lima")
    # Ana: terça 8h até 14/10, terça 9h a partir de 20/10 (o passado fica com a linha antiga)
    grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, criado_em, excluido_em) VALUES (?,2,8,'CIA','2026-09-01 10:00:00','2026-10-14 10:00:00')", ana)
    grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, vigente_de, criado_em) VALUES (?,2,9,'CIA','2026-10-20','2026-10-14 10:00:00')", ana)
    # Bia: troca de local no dia 20/10 (a antiga é excluída nesse dia: vale só a nova)
    grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, criado_em, excluido_em) VALUES (?,2,10,'CIA','2026-09-01 10:00:00','2026-10-20 08:00:00')", bia)
    grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, vigente_de, criado_em) VALUES (?,2,10,'Praia','2026-10-20','2026-10-19 10:00:00')", bia)
    fixo(cai, 1, 7)
    grava("UPDATE clientes SET data_inicio='2026-10-19' WHERE id=?", cai)   # só a partir da 2ª semana
    avulsa_repor(cai, "2026-10-17", 11)
    marcar(http, ana, "2026-10-13", hora=8)
    con = db.conectar()
    try:
        seg = dt.date(2026, 10, 12)
        junto = main.aulas_da_semana(con, seg, HOJE, semanas=2)
        separado = main.aulas_da_semana(con, seg, HOJE) + main.aulas_da_semana(con, seg + dt.timedelta(days=7), HOJE)
        assert junto == separado
        quem = [(a["data"], a["hora"], a["nome"], a["local"]) for a in junto]
        assert ("2026-10-13", 8, "Ana Silva", "CIA") in quem and ("2026-10-20", 9, "Ana Silva", "CIA") in quem
        assert ("2026-10-20", 8, "Ana Silva", "CIA") not in quem
        assert [x for x in quem if x[2] == "Bia Costa" and x[0] == "2026-10-20"] == [("2026-10-20", 10, "Bia Costa", "Praia")]
        assert [x[0] for x in quem if x[2] == "Caio Lima" and x[1] == 7] == ["2026-10-19"]
        assert main.aulas_da_semana(con, seg, HOJE, semanas=1) == main.aulas_da_semana(con, seg, HOJE)
    finally:
        con.close()


def test_varias_semanas_usam_o_mesmo_numero_de_consultas(http):
    ana = aluno("Ana Silva")
    fixo(ana, 1, 7)
    con = db.conectar()
    consultas = []
    con.set_trace_callback(consultas.append)
    try:
        main.aulas_da_semana(con, dt.date(2026, 10, 12), HOJE)
        uma = len(consultas)
        consultas.clear()
        main.aulas_da_semana(con, dt.date(2026, 9, 21), HOJE, semanas=4)
        assert len(consultas) == uma
    finally:
        con.close()


# ---------- página e rota ----------
def cenario():
    ana, bia = aluno("Ana Silva", data_inicio="2026-10-05"), aluno("Bia Costa")
    fixo(ana, 1, 7)
    fixo(ana, 2, 8)
    evento(ana, "desmarcou", "2026-10-05")
    evento(ana, "desmarcou", "2026-10-06")
    avulsa_repor(ana, "2026-10-14")   # passada, sem marca
    evento(bia, "desmarcou", "2026-10-05")
    avulsa_repor(bia, "2026-10-30")   # futura
    return ana, bia


def test_pagina_mostra_pendencias_e_reposicoes(http, hoje_fixo):
    ana, bia = cenario()
    marcar(http, ana, "2026-10-13", hora=8)   # a terça foi marcada; sobram segunda 12/10 e a reposição avulsa de 14/10
    html = http.get("/agenda", params={"semana": SEG_1}).text
    bloco = html.split('class="card pendencias"', 1)[1].split("</section>", 1)[0]
    assert "Sem marcar na semana de 12/10" in bloco
    assert bloco.count('class="pend-linha"') == 2 and "Seg 12/10 · 07h" in bloco and "Qua 14/10 · 07h" in bloco
    assert 'data-dh="1-7"' in bloco and "reposição</span>" in bloco and 'class="tag estado-lote" hidden' in bloco
    assert "Marcar todas como feitas" in bloco
    assert 'data-dh="1-7" data-info=' in html
    topo = html.split('class="card pendencias"', 1)[1].split('<div class="pend-colunas">', 1)[0]
    assert "2 sem marcar" in topo and "1 a agendar" in topo
    # Ana: saldo 2, 1 sem marca (a de 14/10) -> 1 a agendar; Bia: saldo 1 coberto pela futura -> em "Já agendadas"
    direita = html.split('aria-label="Reposições a fazer"', 1)[1]
    assert "Ana Silva" in direita.split("<details", 1)[0] and "1 a agendar" in direita and "1 já agendada" in direita
    assert 'class="claro pequeno btn-repor-aluno"' in direita and f"aluno={ana}" in direita
    assert "Já agendadas (1)" in direita and direita.index("Bia Costa") > direita.index("Já agendadas (1)")


def test_pagina_tudo_em_dia_e_sem_reposicao(http, hoje_fixo):
    ana = aluno("Ana Silva")
    fixo(ana, 1, 7)
    marcar(http, ana, "2026-10-19")   # a segunda de hoje já foi marcada
    html = http.get("/agenda", params={"semana": SEG_ATUAL}).text
    assert "Tudo em dia." in html and "Nenhuma reposição a fazer." in html and "Marcar todas como feitas" not in html


def test_rota_pendentes_json(http, hoje_fixo):
    ana, _ = cenario()
    marcar(http, ana, "2026-10-13", hora=8)
    r = http.get("/agenda/pendentes")
    assert r.status_code == 200
    # 12/10: segunda sem marcar + avulsa 14/10 = 2; 05/10: só a terça 8h (a segunda 7h tem a desmarcação lançada) = 1; a semana atual não entra
    assert r.json() == {"semanas": [{"segunda": SEG_1, "txt": "12/10 a 17/10", "n": 2}, {"segunda": SEG_2, "txt": "05/10 a 10/10", "n": 1}]}


def test_rota_pendentes_ignora_bloqueio_e_pausa(http, hoje_fixo):
    ana, _ = cenario()
    grava("INSERT INTO campanha_fases (nome, inicio, fim, tipo, ordem) VALUES ('Bloqueio de teste', '2026-10-05', '2026-10-11', 'bloqueio', 99)")
    marcar(http, ana, "2026-10-13", hora=8)
    assert http.get("/agenda/pendentes").json()["semanas"] == [{"segunda": SEG_1, "txt": "12/10 a 17/10", "n": 2}]
