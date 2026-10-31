"""Agenda: horários fixos próprios (1 card por horário, até 2 alunos) + aulas avulsas, marcar Feita/Faltou/Desmarcou, aviso de aulas sem marcar."""
import datetime as dt
import json
import re
import sqlite3
from contextlib import contextmanager
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import db, main

SEMANA = "2026-10-12"   # segunda; datas fixas para o teste valer em qualquer dia da semana
TER, QUA = "2026-10-13", "2026-10-14"


@pytest.fixture
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    return TestClient(main.app, base_url="http://localhost")


def consulta(sql, *args):
    con = db.conectar()
    try:
        return [tuple(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def grava(sql, *args):
    con = db.conectar()
    try:
        with con:
            return con.execute(sql, args).lastrowid
    finally:
        con.close()


def alertas():
    con = db.conectar()
    try:
        return [a["texto"] for a in main.alertas(con)]
    finally:
        con.close()


def aluno(nome, status="ativo", data_inicio=None, local="CIA"):
    return grava("INSERT INTO clientes (nome, status, data_inicio, local, tipo_servico) VALUES (?,?,?,?,'Pacote de Aulas')",
                 nome, status, data_inicio, local)


def ocupar(cid, dia, hora, local="CIA", tipos=("Pacotes", "Mensalidades"), nome=None):
    """Põe um aluno (ou um nome escrito à mão, se cid=None) na Grade."""
    nome = nome or (consulta("SELECT nome FROM clientes WHERE id=?", cid)[0][0] if cid else "Fulano da planilha")
    for t in tipos:
        grava("""INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, cliente_id, cliente_nome)
                 VALUES (?,?,?,?,'ocupado',?,?)""", t, dia, local, hora, cid, nome)


def fixo(cid, dia, hora, local="CIA"):
    """Horário fixo direto na tabela da Agenda (para montar o cenário sem passar pelas rotas)."""
    return grava("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?,?,?,?)", cid, dia, hora, local)


def horario(http, dia, hora, a1="", a2="", local="CIA", **extra):
    """Salva o seletor do card, como a janelinha faz."""
    return http.post("/agenda/horario", data={"dia": dia, "hora": hora, "aluno1": a1, "aluno2": a2, "local": local, "semana": SEMANA, **extra},
                     follow_redirects=False)


def fixos_ativos(dia=None, hora=None):
    """[(nome, dia, hora, local)] da Agenda, do mais antigo ao mais novo."""
    return consulta("""SELECT c.nome, f.dia, f.hora, f.local FROM agenda_fixos f JOIN clientes c ON c.id=f.cliente_id
                       WHERE f.excluido_em IS NULL AND (? IS NULL OR f.dia=?) AND (? IS NULL OR f.hora=?) ORDER BY f.id""", dia, dia, hora, hora)


def grade(dia, hora, local="CIA"):
    return consulta("SELECT tipo_calculo, status, cliente_id, cliente_nome FROM grade_slots WHERE dia=? AND hora=? AND local=? ORDER BY tipo_calculo",
                    dia, hora, local)


def da_grade(cid, nome, status="ocupado"):
    return [("Mensalidades", status, cid, nome), ("Pacotes", status, cid, nome)]


def livre():
    return [("Mensalidades", "livre", None, None), ("Pacotes", "livre", None, None)]


def semana(http, quando=SEMANA, **extra):
    r = http.get("/agenda", params={"semana": quando, **extra})
    assert r.status_code == 200
    return tabela(r.text)


def tabela(pagina):
    return pagina.split('<table class="grade agenda">', 1)[1].split("</table>", 1)[0]


def cards(pagina_ou_tabela, dia=None, hora=None):
    """Botões da tabela da semana: [(info do data-info, html do botão)], filtrando por dia e hora. Um por horário."""
    t = tabela(pagina_ou_tabela) if "<table" in pagina_ou_tabela else pagina_ou_tabela
    out = []
    for b in re.findall(r'<button type="button" class="cel[^>]*>.*?</button>', t, re.S):
        info = json.loads(re.search(r"data-info='([^']*)'", b).group(1))
        if (dia is None or info["dia"] == dia) and (hora is None or info["hora"] == hora):
            out.append((info, b))
    return out


def aulas(quando=SEMANA, hoje=None):
    con = db.conectar()
    try:
        return main.aulas_da_semana(con, dt.date.fromisoformat(quando), hoje)
    finally:
        con.close()


def erro(r):
    return unquote(r.headers["location"].split("erro=", 1)[1]) if "erro=" in r.headers["location"] else None


def msg(r):
    return unquote(r.headers["location"].split("msg=", 1)[1].split("&")[0]) if "msg=" in r.headers["location"] else None


def marcar(http, cid, data, hora=7, estado="feita", avulsa=0, local="CIA"):
    return http.post("/agenda/marcar", data={"cliente_id": cid, "data": data, "hora": hora, "local": local, "estado": estado,
                                             "avulsa": avulsa, "semana": data}, follow_redirects=False)


def ativos(cid, data):
    return consulta("""SELECT tipo, hora, descricao FROM cliente_eventos WHERE cliente_id=? AND data=? AND excluido_em IS NULL
                       AND tipo IN ('aula','falta','desmarcou') ORDER BY id""", cid, data)


class Espia:
    """Conexão que anota cada comando enviado ao banco (vale para o sqlite3 e para o adaptador do Turso)."""
    def __init__(self, con, vistos):
        self._con, self.vistos = con, vistos

    def execute(self, sql, params=()):
        self.vistos.append(" ".join(sql.split()))
        return self._con.execute(sql, params)

    def executemany(self, sql, seq):
        self.vistos.append(" ".join(sql.split()))
        return self._con.executemany(sql, seq)

    def __enter__(self):
        self._con.__enter__()
        return self

    def __exit__(self, *a):
        return self._con.__exit__(*a)

    def __getattr__(self, nome):
        return getattr(self._con, nome)


@pytest.fixture
def espiar(monkeypatch):
    """with espiar() as vistos: ... anota os comandos que as rotas mandam ao banco; gravacoes(vistos) separa os que gravam."""
    @contextmanager
    def espiando():
        vistos, real = [], db.conectar
        with monkeypatch.context() as m:
            m.setattr(db, "conectar", lambda *a, **k: Espia(real(*a, **k), vistos))
            yield vistos
    return espiando


def gravacoes(vistos):
    return [v for v in vistos if v.split()[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE")]


# ---------- 1. o que aparece ----------
def test_aluno_com_horario_fixo_aparece_e_inativo_nao(http):
    ana, bia, caio, dora = aluno("Ana Silva"), aluno("Bia Inativa", status="inativo"), aluno("Caio Excluido"), aluno("Dora Nova", data_inicio=QUA)
    grava("UPDATE clientes SET excluido_em=datetime('now','localtime') WHERE id=?", caio)
    for hora, c in enumerate((ana, bia, caio), 7):
        fixo(c, 2, hora)
    fixo(dora, 2, 10)   # terça, mas só começa na quarta
    fixo(dora, 4, 10)   # quinta: já começou
    pagina = semana(http)
    assert ">Ana<" in pagina and "Bia" not in pagina and "Caio" not in pagina
    lista = aulas()
    assert [(a["nome"], a["dia"], a["hora"], a["data"]) for a in lista] == [("Ana Silva", 2, 7, TER), ("Dora Nova", 4, 10, "2026-10-15")]
    assert "Dora" not in semana(http, "2026-10-05")   # semana anterior ao início


def test_grade_ocupada_nao_alimenta_a_agenda(http):
    ocupar(aluno("Ana Silva"), 2, 7)
    assert aulas() == []
    pagina = http.get("/agenda", params={"semana": SEMANA, "todas": 1}).text
    assert all(not info["alunos"] for info, _ in cards(pagina))   # só horários vazios
    assert "/agenda/copiar-grade" in pagina


def test_tela_com_semana_invalida_abre_na_semana_atual(http):
    assert http.get("/agenda?semana=lixo").status_code == 200
    assert http.get("/agenda?semana=2026-13-45&todas=1").status_code == 200
    assert main.inicio_semana("lixo") == main.inicio_semana(dt.date.today().isoformat())
    assert main.inicio_semana("2026-10-18") == dt.date(2026, 10, 12)   # domingo pertence à semana que termina nele
    assert main.inicio_semana("2026-10-12") == dt.date(2026, 10, 12)


def test_ver_todos_os_horarios_e_semana_vazia(http):
    vazia = http.get("/agenda", params={"semana": SEMANA}).text
    assert "Nenhuma aula nesta semana" in vazia and ">05h<" in tabela(vazia) and ">23h<" in tabela(vazia)
    fixo(aluno("Ana Silva"), 2, 7)
    pagina = http.get("/agenda", params={"semana": SEMANA}).text
    assert "Nenhuma aula nesta semana" not in pagina and ">07h<" in tabela(pagina) and ">08h<" not in tabela(pagina)
    assert "Ver todos os horários" in pagina
    pagina = http.get("/agenda", params={"semana": SEMANA, "todas": 1}).text
    assert ">05h<" in tabela(pagina) and ">23h<" in tabela(pagina) and "Só horários com aula" in pagina
    # hora vazia: o + abre o mesmo seletor, com o data-info de um horário sem aluno
    vazio = cards(pagina, 3, 9)
    assert len(vazio) == 1 and 'class="cel vazio"' in vazio[0][1] and vazio[0][0]["alunos"] == [] and vazio[0][0]["fixos"] == []


def test_pagina_tem_uma_janelinha_so_e_o_cartao_de_copiar_da_grade(http):
    ana = aluno("Ana Silva")
    pagina = http.get("/agenda", params={"semana": SEMANA}).text
    assert 'id="dlg-horario"' in pagina and 'id="dlg-incluir"' in pagina
    assert 'id="dlg-aula"' not in pagina and 'id="dlg-vincular"' not in pagina and "Ligar " not in pagina and "vincular-todos" not in pagina
    assert 'action="/agenda/horario"' in pagina and "— sem aula —" in pagina and "— ninguém —" in pagina
    assert 'name="aluno1"' in pagina and 'name="aluno2"' in pagina and 'name="local"' in pagina
    assert "Horário fixo (toda semana)" in pagina
    assert "Sua agenda está vazia. Copie os alunos da Grade uma vez" in pagina
    assert re.search(r'<form method="post" action="/agenda/copiar-grade" data-confirmar="[^"]+">', pagina)
    fixo(ana, 2, 7)
    assert "/agenda/copiar-grade" not in http.get("/agenda", params={"semana": SEMANA}).text   # só com a Agenda vazia
    grava("UPDATE agenda_fixos SET excluido_em=datetime('now','localtime')")
    assert "/agenda/copiar-grade" in http.get("/agenda", params={"semana": SEMANA}).text      # excluídos não contam


def test_data_info_tem_os_dados_do_card_e_escapa_nomes_esquisitos(http):
    ana, ze = aluno("Ana Silva"), aluno("Zé O'Neil <b>x</b> & \"Cia\"")
    fixo(ana, 2, 7)
    fixo(ze, 2, 7, "SmartFit")
    marcar(http, ana, TER, 7, "faltou")
    pagina = http.get("/agenda", params={"semana": SEMANA}).text
    assert "<b>x</b>" not in pagina and "O'Neil" not in tabela(pagina)   # nada de HTML vindo do nome
    (info, botao), = cards(pagina, 2, 7)
    assert (info["dia"], info["hora"], info["data"], info["titulo"]) == (2, 7, TER, "Ter 13/10 · 07h")
    assert [(a["cliente_id"], a["nome"], a["estado"], a["local"], a["avulsa"], a["avulsa_id"]) for a in info["alunos"]] == [
        (ana, "Ana Silva", "faltou", "CIA", False, None), (ze, "Zé O'Neil <b>x</b> & \"Cia\"", None, "SmartFit", False, None)]
    assert info["alunos"][0]["situacao"] == "faltou" and info["alunos"][1]["situacao"] in ("pendente", "futura")   # depende de hoje
    assert all("bloqueio" in a for a in info["alunos"])
    assert [(f["cliente_id"], f["local"]) for f in info["fixos"]] == [(ana, "CIA"), (ze, "SmartFit")]
    assert info["local"] == "CIA"
    assert 'class="cel aula dupla' in botao and ">Ana<" in botao and "Zé" in botao


# ---------- 2. seletor do card: /agenda/horario ----------
def test_horario_com_1_aluno_e_com_2_alunos_vira_um_card_so(http):
    ana, bruno = aluno("Ana Silva"), aluno("Bruno Costa")
    r = horario(http, 1, 7, ana)
    assert r.status_code == 303 and erro(r) is None and msg(r) == "Seg 07h: Ana (CIA)." and f"semana={SEMANA}" in r.headers["location"]
    (info, botao), = cards(semana(http), 1, 7)
    assert [a["nome"] for a in info["alunos"]] == ["Ana Silva"] and "Bruno" not in botao and re.search(r'class="cel aula (pendente|futura)"', botao)
    r = horario(http, 1, 7, ana, bruno)
    assert msg(r) == "Seg 07h: Ana + Bruno (CIA)."
    (info, botao), = cards(semana(http), 1, 7)   # um botão só para o horário, com os dois nomes
    assert [a["nome"] for a in info["alunos"]] == ["Ana Silva", "Bruno Costa"] and ">Ana<" in botao and ">Bruno<" in botao and 'title="Ana Silva + Bruno Costa' in botao
    assert semana(http).count('class="cel aula') == 1
    assert fixos_ativos() == [("Ana Silva", 1, 7, "CIA"), ("Bruno Costa", 1, 7, "CIA")]
    assert [(a["nome"], a["hora"]) for a in aulas()] == [("Ana Silva", 7), ("Bruno Costa", 7)]


def test_horario_com_dois_primeiros_nomes_iguais_usa_o_nome_inteiro(http):
    a1, a2 = aluno("Ana Silva"), aluno("Ana Lima")
    assert msg(horario(http, 3, 18, a1, a2)) == "Qua 18h: Ana Silva + Ana Lima (CIA)."
    (info, botao), = cards(semana(http), 3, 18)
    assert ">Ana Silva<" in botao and ">Ana Lima<" in botao


def test_horario_marca_cada_aluno_do_card_com_a_sua_cor(http):
    ana, bruno = aluno("Ana Silva"), aluno("Bruno Costa")
    horario(http, 2, 7, ana, bruno)
    marcar(http, ana, TER, 7, "feita")
    marcar(http, bruno, TER, 7, "faltou")
    (info, botao), = cards(semana(http), 2, 7)
    assert [(a["nome"], a["estado"]) for a in info["alunos"]] == [("Ana Silva", "feita"), ("Bruno Costa", "faltou")]
    assert '<span class="n feita">Ana' in botao and '<span class="n faltou">Bruno' in botao


def test_terceiro_aluno_pelo_incluir_e_recusado(http):
    ana, bia, caio = aluno("Ana Silva"), aluno("Bia Costa"), aluno("Caio Santos")
    horario(http, 1, 7, ana, bia)
    antes = consulta("SELECT * FROM agenda_fixos ORDER BY id")
    r = http.post("/agenda/incluir", data={"cliente_id": caio, "local": "CIA", "dia": 1, "hora": 7, "repetir": 1}, follow_redirects=False)
    assert erro(r) == "Seg 07h já tem 2 alunos."
    assert consulta("SELECT * FROM agenda_fixos ORDER BY id") == antes
    assert grade(1, 7) == da_grade(ana, "Ana Silva")   # a Grade também não mexeu
    # os 2 que já estão podem ser incluídos de novo sem erro
    assert erro(http.post("/agenda/incluir", data={"cliente_id": bia, "local": "CIA", "dia": 1, "hora": 7, "repetir": 1}, follow_redirects=False)) is None


def test_seletor_ignora_terceiro_e_repetido(http):
    ana = aluno("Ana Silva")
    r = horario(http, 1, 7, ana, ana)   # o mesmo aluno nos dois campos vale uma vez
    assert msg(r) == "Seg 07h: Ana (CIA)." and fixos_ativos() == [("Ana Silva", 1, 7, "CIA")]
    r = horario(http, 1, 7, "", ana)    # só o 2º preenchido: vira o 1º
    assert erro(r) is None and fixos_ativos() == [("Ana Silva", 1, 7, "CIA")]


def test_sem_aula_esvazia_o_horario_e_solta_a_grade_nos_dois_tipos(http):
    ana, bruno = aluno("Ana Silva"), aluno("Bruno Costa")
    horario(http, 1, 7, ana, bruno)
    assert grade(1, 7) == da_grade(ana, "Ana Silva")   # a Grade ficou com o 1º; o 2º não cabe na mesma célula
    grava("UPDATE grade_slots SET multiplicador=0.9 WHERE hora=7 AND tipo_calculo='Pacotes'")
    marcar(http, ana, "2026-10-12", 7, "feita")
    r = horario(http, 1, 7, "", "", local="")
    assert r.status_code == 303 and erro(r) is None and msg(r) == "Seg 07h ficou sem aula."
    assert fixos_ativos() == [] and aulas() == []
    assert consulta("SELECT COUNT(*) FROM agenda_fixos WHERE excluido_em IS NOT NULL") == [(2,)]   # foram para a lixeira, nada apagado
    assert grade(1, 7) == livre()
    assert consulta("SELECT multiplicador FROM grade_slots WHERE hora=7 ORDER BY tipo_calculo") == [(1.0,), (0.9,)]   # o multiplicador fica
    assert ativos(ana, "2026-10-12") == [("aula", 7, "Agenda — Seg 07h CIA")]   # o histórico fica
    assert "Ana" not in semana(http)


def test_sem_aula_de_horario_vazio_nao_faz_nada(http, espiar):
    with espiar() as vistos:
        r = horario(http, 1, 7, "", "", local="")
    assert msg(r) == "Seg 07h ficou sem aula." and gravacoes(vistos) == []


def test_trocar_o_local_solta_a_celula_antiga_e_ocupa_a_nova(http):
    ana = aluno("Ana Silva")
    horario(http, 2, 8, ana, local="CIA")
    assert grade(2, 8, "CIA") == da_grade(ana, "Ana Silva") and grade(2, 8, "SmartFit") == []
    antes = consulta("SELECT id, criado_em FROM agenda_fixos")
    assert msg(horario(http, 2, 8, ana, local="SmartFit")) == "Ter 08h: Ana (SmartFit)."
    assert grade(2, 8, "CIA") == livre()
    assert grade(2, 8, "SmartFit") == da_grade(ana, "Ana Silva")
    assert consulta("SELECT id, criado_em, local, excluido_em FROM agenda_fixos") == [(antes[0][0], antes[0][1], "SmartFit", None)]   # a mesma linha, só mudou o local
    assert [a["local"] for a in aulas()] == ["SmartFit"]


def test_trocar_o_aluno_do_horario_solta_o_antigo_e_ocupa_o_novo(http):
    ana, bia = aluno("Ana Silva"), aluno("Bia Costa")
    horario(http, 2, 8, ana)
    horario(http, 2, 8, bia)
    assert fixos_ativos() == [("Bia Costa", 2, 8, "CIA")]
    assert grade(2, 8) == da_grade(bia, "Bia Costa")


def test_quem_fica_assume_a_celula_que_o_outro_deixou(http):
    ana, bruno = aluno("Ana Silva"), aluno("Bruno Costa")
    horario(http, 1, 7, ana, bruno)           # a célula da Grade é da Ana
    horario(http, 1, 7, bruno)                # a Ana sai; o Bruno não pode ficar sem a célula dele
    assert fixos_ativos() == [("Bruno Costa", 1, 7, "CIA")]
    assert grade(1, 7) == da_grade(bruno, "Bruno Costa")


def test_segundo_aluno_em_outro_local_ocupa_a_propria_celula(http):
    ana, bruno = aluno("Ana Silva"), aluno("Bruno Costa")
    horario(http, 1, 7, ana, local="CIA")
    r = http.post("/agenda/incluir", data={"cliente_id": bruno, "local": "SmartFit", "dia": 1, "hora": 7, "repetir": 1}, follow_redirects=False)
    assert erro(r) is None
    assert fixos_ativos() == [("Ana Silva", 1, 7, "CIA"), ("Bruno Costa", 1, 7, "SmartFit")]   # a Ana mantém o local dela
    assert grade(1, 7, "CIA") == da_grade(ana, "Ana Silva") and grade(1, 7, "SmartFit") == da_grade(bruno, "Bruno Costa")
    (info, botao), = cards(semana(http), 1, 7)
    assert [a["local"] for a in info["alunos"]] == ["CIA", "SmartFit"] and "CIA / SmartFit" in botao   # a semana tem mais de um local: o card mostra os dois
    assert info["local"] == "CIA"


def test_grade_nao_sobrescreve_outro_aluno_nem_celula_indisponivel_e_nao_da_erro(http):
    ana, bia, caio = aluno("Ana Silva"), aluno("Bia Costa"), aluno("Caio Santos")
    ocupar(ana, 1, 7)   # a célula da Grade é da Ana
    grava("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status) VALUES ('Pacotes', 2, 'SmartFit', 8, 'indisponivel')")
    r = horario(http, 1, 7, bia)
    assert r.status_code == 303 and erro(r) is None and msg(r) == "Seg 07h: Bia (CIA)."
    assert grade(1, 7) == da_grade(ana, "Ana Silva")   # nada mudou na Grade
    r = horario(http, 2, 8, caio, local="SmartFit")
    assert erro(r) is None and msg(r) == "Ter 08h: Caio (SmartFit)."
    assert grade(2, 8, "SmartFit") == [("Pacotes", "indisponivel", None, None)]
    assert sorted(a["nome"] for a in aulas()) == ["Bia Costa", "Caio Santos"]   # a Agenda gravou mesmo assim


def test_grade_ocupada_pelos_dois_tipos_e_nome_a_mao_e_trocado(http):
    ana = aluno("Ana Silva")
    ocupar(None, 4, 9, nome="Fulano da planilha")   # nome escrito à mão pode ser trocado pelo aluno
    grava("""INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador) VALUES ('Pacotes', 2, 'CIA', 7, 'livre', 0.9)""")
    horario(http, 2, 7, ana)
    assert consulta("SELECT tipo_calculo, status, cliente_id, cliente_nome, multiplicador FROM grade_slots WHERE dia=2 AND hora=7 ORDER BY tipo_calculo") == [
        ("Mensalidades", "ocupado", ana, "Ana Silva", 1.0), ("Pacotes", "ocupado", ana, "Ana Silva", 0.9)]   # mantém o multiplicador de cada tipo
    for tipo in ("Pacotes", "Mensalidades"):
        assert "Ana Silva" in http.get("/grade", params={"tipo": tipo, "local": "CIA"}).text
    horario(http, 4, 9, ana)
    assert grade(4, 9) == da_grade(ana, "Ana Silva")


def test_salvar_sem_mudanca_nao_grava_nada(http, espiar):
    ana, bruno = aluno("Ana Silva"), aluno("Bruno Costa")
    horario(http, 1, 7, ana, bruno)
    linhas = consulta("SELECT id, cliente_id, dia, hora, local, criado_em, excluido_em FROM agenda_fixos ORDER BY id")
    celulas = consulta("SELECT * FROM grade_slots ORDER BY id")
    with espiar() as vistos:
        r = horario(http, 1, 7, ana, bruno)
    assert erro(r) is None and msg(r) == "Seg 07h: Ana + Bruno (CIA)."
    assert gravacoes(vistos) == []                                   # nenhum INSERT/UPDATE/DELETE
    assert consulta("SELECT id, cliente_id, dia, hora, local, criado_em, excluido_em FROM agenda_fixos ORDER BY id") == linhas   # mesmos ids e criado_em
    assert consulta("SELECT COUNT(*) FROM agenda_fixos WHERE excluido_em IS NOT NULL") == [(0,)]
    assert consulta("SELECT * FROM grade_slots ORDER BY id") == celulas
    with espiar() as vistos:   # incluir de quem já está também não grava
        http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "dia": 1, "hora": 7, "repetir": 1})
    assert gravacoes(vistos) == []


def test_so_grava_a_diferenca(http, espiar):
    ana, bruno, caio = aluno("Ana Silva"), aluno("Bruno Costa"), aluno("Caio Santos")
    horario(http, 1, 7, ana, bruno)
    ana_id = consulta("SELECT id, criado_em FROM agenda_fixos WHERE cliente_id=?", ana)[0]
    with espiar() as vistos:   # o Bruno sai e entra o Caio; a Ana não é tocada
        horario(http, 1, 7, ana, caio)
    sql = gravacoes(vistos)
    assert not any("cliente_id=?" in x and "agenda_fixos" in x and "DELETE" in x for x in sql) and not any(x.startswith("DELETE") for x in sql)
    assert sum(x.startswith("INSERT INTO agenda_fixos") for x in sql) == 1 and sum(x.startswith("UPDATE agenda_fixos SET excluido_em") for x in sql) == 1
    assert not any(x.startswith("UPDATE agenda_fixos SET local") for x in sql)
    assert consulta("SELECT id, criado_em FROM agenda_fixos WHERE cliente_id=?", ana)[0] == ana_id
    assert fixos_ativos() == [("Ana Silva", 1, 7, "CIA"), ("Caio Santos", 1, 7, "CIA")]


@pytest.mark.parametrize("dados", [{"dia": 7}, {"dia": 0}, {"hora": 4}, {"hora": 24}, {"local": ""}, {"local": "   "}, {"a1": 999}, {"a1": "abc"}, {"a2": 999}])
def test_seletor_invalido_nao_grava(http, dados):
    ana = aluno("Ana Silva")
    base = {"dia": 2, "hora": 7, "a1": ana, "a2": "", "local": "CIA", **dados}
    r = horario(http, **base)
    assert r.status_code == 303 and erro(r)
    assert consulta("SELECT * FROM agenda_fixos") == [] and consulta("SELECT * FROM grade_slots") == []


def test_seletor_recusa_aluno_inativo_ou_excluido(http):
    inativo, excluido = aluno("Bia Inativa", status="inativo"), aluno("Caio Excluido")
    grava("UPDATE clientes SET excluido_em=datetime('now','localtime') WHERE id=?", excluido)
    for c in (inativo, excluido):
        assert erro(horario(http, 2, 7, c)) == "Escolha um aluno ativo."
    ana = aluno("Ana Silva")
    assert erro(horario(http, 2, 7, ana, inativo)) == "Escolha um aluno ativo."   # um ruim recusa tudo
    assert consulta("SELECT * FROM agenda_fixos") == []


def test_seletor_volta_para_a_semana_e_mantem_todas(http):
    ana = aluno("Ana Silva")
    r = horario(http, 2, 7, ana, todas=1)
    assert r.headers["location"].startswith(f"/agenda?semana={SEMANA}&todas=1&msg=")


# ---------- incluir horário fixo (+ Incluir aula) ----------
def test_incluir_fixo_grava_agenda_e_avisa_a_grade_nos_dois_tipos(http):
    ana = aluno("Ana Silva")
    grava("""INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador) VALUES ('Pacotes', 2, 'CIA', 7, 'livre', 0.9)""")
    r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "dia": 2, "hora": 7, "repetir": 1, "semana": SEMANA}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"] and erro(r) is None
    assert fixos_ativos() == [("Ana Silva", 2, 7, "CIA")]
    assert consulta("""SELECT tipo_calculo, status, cliente_id, cliente_nome, multiplicador FROM grade_slots WHERE dia=2 AND hora=7 ORDER BY tipo_calculo""") == [
        ("Mensalidades", "ocupado", ana, "Ana Silva", 1.0), ("Pacotes", "ocupado", ana, "Ana Silva", 0.9)]
    assert [a["nome"] for a in aulas()] == ["Ana Silva"]
    # a mesma pessoa de novo no mesmo horário não dá erro nem repete
    assert erro(http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "dia": 2, "hora": 7, "repetir": 1}, follow_redirects=False)) is None
    assert fixos_ativos() == [("Ana Silva", 2, 7, "CIA")]


def test_incluir_de_quem_ja_esta_em_outro_local_muda_o_local(http):
    ana = aluno("Ana Silva")
    horario(http, 2, 7, ana, local="CIA")
    r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "SmartFit", "dia": 2, "hora": 7, "repetir": 1}, follow_redirects=False)
    assert erro(r) is None and fixos_ativos() == [("Ana Silva", 2, 7, "SmartFit")]
    assert msg(r) == "Ana Silva agora fica em SmartFit no horário fixo de Ter 07h. A Grade também foi atualizada."
    assert grade(2, 7, "CIA") == livre() and grade(2, 7, "SmartFit") == da_grade(ana, "Ana Silva")


def test_incluir_fixo_em_horario_de_outro_aluno_na_grade_entra_na_agenda_sem_mexer_na_grade(http):
    ana, bia = aluno("Ana Silva"), aluno("Bia Costa")
    ocupar(ana, 2, 7)
    antes = consulta("SELECT * FROM grade_slots ORDER BY id")
    r = http.post("/agenda/incluir", data={"cliente_id": bia, "local": "CIA", "dia": 2, "hora": 7, "repetir": 1}, follow_redirects=False)
    assert erro(r) is None and fixos_ativos() == [("Bia Costa", 2, 7, "CIA")]
    assert consulta("SELECT * FROM grade_slots ORDER BY id") == antes


def test_incluir_fixo_em_horario_indisponivel_na_grade_entra_na_agenda(http):
    ana = aluno("Ana Silva")
    grava("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status) VALUES ('Pacotes', 3, 'CIA', 8, 'indisponivel')")
    r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "dia": 3, "hora": 8, "repetir": 1}, follow_redirects=False)
    assert erro(r) is None and fixos_ativos() == [("Ana Silva", 3, 8, "CIA")]
    assert consulta("SELECT tipo_calculo, status, cliente_id FROM grade_slots") == [("Pacotes", "indisponivel", None)]


@pytest.mark.parametrize("dados", [{"dia": 7, "hora": 7}, {"dia": 0, "hora": 7}, {"dia": 2, "hora": 4}, {"dia": 2, "hora": 24}, {"dia": 2, "hora": 7, "local": ""},
                                   {"dia": 2, "hora": 7, "cliente_id": 999}])
def test_incluir_fixo_invalido_nao_grava(http, dados):
    ana = aluno("Ana Silva")
    base = {"cliente_id": ana, "local": "CIA", "repetir": 1, **dados}
    r = http.post("/agenda/incluir", data=base, follow_redirects=False)
    assert r.status_code == 303 and erro(r)
    assert consulta("SELECT * FROM grade_slots") == [] and consulta("SELECT * FROM agenda_fixos") == []


def alunos_da_grade():
    return [dict(id=i, nome=n, status=st) for i, n, st in consulta("SELECT id, nome, status FROM clientes")]


def test_sugerir_cliente(http):
    jose, ana, bia1, bia2 = aluno("José Álvares"), aluno("Ana Silva"), aluno("Bia Costa"), aluno("Bia Lima")
    caio = aluno("Caio Santos", status="inativo")
    aluno("Ana Paula Inativa", status="inativo")
    todos = alunos_da_grade()
    assert main.sugerir_cliente("jose alvares", todos) == jose        # sem acento e sem maiúscula
    assert main.sugerir_cliente("  JOSÉ   ÁLVARES ", todos) == jose   # espaços sobrando
    assert main.sugerir_cliente("Ana", todos) == ana                  # primeiro nome único (a inativa não conta)
    assert main.sugerir_cliente("ana silva", todos) == ana
    assert main.sugerir_cliente("Bia", todos) is None                 # dois alunos: dúvida
    assert main.sugerir_cliente("Bia Costa", todos) == bia1           # nome completo desfaz a dúvida
    assert main.sugerir_cliente("Caio", todos) is None                # inativo é ignorado
    assert main.sugerir_cliente("Caio Santos", todos) is None
    assert main.sugerir_cliente("Treino próprio", todos) is None and main.sugerir_cliente("", todos) is None
    assert main.sugerir_cliente("An", todos) is None                  # só vale palavra inteira ("an" não é "ana")
    assert main.sugerir_cliente("Bia Lima", [{"id": bia2, "nome": "Bia Lima"}]) == bia2   # lista já filtrada, sem coluna status
    assert caio


# ---------- 3b. definir_horario direto ----------
def definir(dia, hora, alunos, local):
    con = db.conectar()
    try:
        with con:
            return main.definir_horario(con, dia, hora, alunos, local)
    finally:
        con.close()


def test_definir_horario_devolve_quem_entrou_saiu_e_mudou(http):
    ana, bruno, caio = aluno("Ana Silva"), aluno("Bruno Costa"), aluno("Caio Santos")
    assert definir(1, 7, [ana, bruno], "CIA") == {"entrou": [ana, bruno], "saiu": [], "mudou": []}
    assert definir(1, 7, [ana, bruno], "CIA") == {"entrou": [], "saiu": [], "mudou": []}
    assert definir(1, 7, [ana, caio], {ana: "SmartFit", caio: "CIA"}) == {"entrou": [caio], "saiu": [bruno], "mudou": [ana]}
    assert fixos_ativos() == [("Ana Silva", 1, 7, "SmartFit"), ("Caio Santos", 1, 7, "CIA")]
    assert definir(1, 7, [], "") == {"entrou": [], "saiu": [ana, caio], "mudou": []}


def test_definir_horario_limpa_linha_repetida_que_voltou_da_lixeira(http):
    ana = aluno("Ana Silva")
    fixo(ana, 1, 7)
    fixo(ana, 1, 7)   # duas linhas ativas do mesmo aluno
    assert [a["nome"] for a in aulas()] == ["Ana Silva"]   # a tela mostra uma
    definir(1, 7, [], "")
    assert fixos_ativos() == [] and aulas() == []


# ---------- 3c. Copiar da Grade ----------
def copiar(http, **extra):
    return http.post("/agenda/copiar-grade", data={"semana": SEMANA, **extra}, follow_redirects=False)


def test_copiar_da_grade_aluno_em_3_locais_vira_uma_linha_com_o_local_do_cadastro(http):
    ana = aluno("Ana Silva", local="SmartFit")
    bia = aluno("Bia Costa", local="Condomínio")   # o cadastro não está entre os locais dela na Grade
    for loc in ("CIA", "SmartFit", "Outro"):
        ocupar(ana, 1, 7, loc)
        ocupar(bia, 1, 8, loc)
    r = copiar(http)
    assert r.status_code == 303 and erro(r) is None
    assert msg(r) == "2 horários copiados da Grade."
    assert sorted(fixos_ativos()) == [("Ana Silva", 1, 7, "SmartFit"), ("Bia Costa", 1, 8, "CIA")]   # CIA: o primeiro na ordem dos locais
    assert [i["alunos"][0]["nome"] for i, _ in cards(semana(http)) if i["alunos"]] == ["Ana Silva", "Bia Costa"]   # um card por horário


def test_copiar_da_grade_nome_a_mao_e_reconhecido_e_os_outros_sao_listados(http):
    ana, jose = aluno("Ana Silva"), aluno("José Álvares")
    ocupar(None, 2, 7, nome="ana")                       # primeiro nome único
    ocupar(None, 3, 8, nome="jose alvares", local="SmartFit")
    ocupar(None, 4, 9, nome="Treino próprio")
    ocupar(None, 4, 10, nome="Treino próprio", local="SmartFit")   # o mesmo nome em outro horário conta uma vez
    ocupar(None, 5, 9, nome="Fulano")
    r = copiar(http)
    assert erro(r) is None
    assert msg(r) == "2 horários copiados da Grade. 2 nomes não reconhecidos: Treino próprio, Fulano."
    assert sorted(fixos_ativos()) == [("Ana Silva", 2, 7, "CIA"), ("José Álvares", 3, 8, "SmartFit")]


def test_copiar_da_grade_mostra_ate_5_nomes_e_reticencias_e_singular(http):
    for k in range(7):
        ocupar(None, 1, 5 + k, nome=f"Visitante {k}")
    aluno("Ana Silva")
    ocupar(None, 6, 7, nome="Ana")
    r = copiar(http)
    assert msg(r) == "1 horário copiado da Grade. 7 nomes não reconhecidos: Visitante 0, Visitante 1, Visitante 2, Visitante 3, Visitante 4…"
    grava("UPDATE agenda_fixos SET excluido_em=datetime('now','localtime')")
    grava("DELETE FROM grade_slots WHERE cliente_nome LIKE 'Visitante %' AND hora > 5")
    assert msg(copiar(http)) == "1 horário copiado da Grade. 1 nome não reconhecido: Visitante 0."


def test_copiar_da_grade_pula_o_terceiro_aluno_do_mesmo_horario(http):
    ana, bia, caio = aluno("Ana Silva"), aluno("Bia Costa"), aluno("Caio Santos")
    for loc, c in (("CIA", ana), ("Online", bia), ("SmartFit", caio)):   # a Grade tem uma célula por local: cada um no seu
        ocupar(c, 1, 7, loc)
    r = copiar(http)
    assert msg(r) == "1 horário copiado da Grade (2 alunos). 1 aluno ficou de fora (cabem 2 por horário)."
    assert [n for n, *_ in fixos_ativos(1, 7)] == ["Ana Silva", "Bia Costa"]   # fica quem aparece primeiro na Grade (por local)
    (info, botao), = cards(semana(http), 1, 7)
    assert len(info["alunos"]) == 2


def test_copiar_da_grade_plural_de_alunos_de_fora(http):
    for k, loc in enumerate(("CIA", "SmartFit", "Online", "Outro", "Condomínio")):
        ocupar(aluno(f"Aluno {k}"), 1, 7, loc)
    assert msg(copiar(http)).endswith("3 alunos ficaram de fora (cabem 2 por horário).")


def test_copiar_da_grade_so_vale_com_a_agenda_vazia(http):
    ana, bia = aluno("Ana Silva"), aluno("Bia Costa")
    ocupar(ana, 1, 7)
    assert erro(copiar(http)) is None
    antes = consulta("SELECT * FROM agenda_fixos ORDER BY id")
    ocupar(bia, 2, 8)
    r = copiar(http)
    assert erro(r) == "A Agenda já tem horários fixos. Copiar da Grade só vale com a Agenda vazia."
    assert consulta("SELECT * FROM agenda_fixos ORDER BY id") == antes   # nada de duplicar
    # com tudo excluído, a Agenda volta a ser vazia e dá para copiar de novo
    grava("UPDATE agenda_fixos SET excluido_em=datetime('now','localtime')")
    assert erro(copiar(http)) is None and sorted(n for n, *_ in fixos_ativos()) == ["Ana Silva", "Bia Costa"]


def test_copiar_da_grade_ignora_inativo_excluido_livre_indisponivel_domingo_e_hora_fora(http):
    ana, inativo, excluido = aluno("Ana Silva"), aluno("Bia Inativa", status="inativo"), aluno("Caio Excluido")
    grava("UPDATE clientes SET excluido_em=datetime('now','localtime') WHERE id=?", excluido)
    ocupar(ana, 1, 7)
    ocupar(inativo, 1, 8)
    ocupar(excluido, 1, 9)
    ocupar(None, 1, 10, nome="Bia Inativa")                         # nome à mão de aluno inativo: não reconhece
    ocupar(ana, 7, 7)                                               # domingo
    ocupar(ana, 2, 4)                                               # hora fora
    ocupar(ana, 2, 24)
    grava("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, cliente_id) VALUES ('Pacotes', 3, 'CIA', 7, 'livre', ?)", ana)
    grava("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status) VALUES ('Pacotes', 3, 'CIA', 8, 'indisponivel')")
    r = copiar(http)
    assert msg(r) == "1 horário copiado da Grade. 1 nome não reconhecido: Bia Inativa."
    assert fixos_ativos() == [("Ana Silva", 1, 7, "CIA")]


def test_copiar_da_grade_sem_nada_para_copiar_da_erro_amigavel(http):
    r = copiar(http)
    assert erro(r) == "Não achei alunos ativos na Grade para copiar." and consulta("SELECT * FROM agenda_fixos") == []
    ocupar(None, 1, 7, nome="Fulano")
    assert erro(copiar(http)) == "Não achei alunos ativos na Grade para copiar. Nomes sem aluno no CRM: Fulano."
    assert consulta("SELECT * FROM agenda_fixos") == []


def test_copiar_da_grade_nao_mexe_na_grade_nem_na_agenda_avulsa(http):
    ana = aluno("Ana Silva")
    ocupar(ana, 1, 7)
    ocupar(None, 2, 8, nome="Ana")
    antes = consulta("SELECT * FROM grade_slots ORDER BY id")
    copiar(http)
    assert consulta("SELECT * FROM grade_slots ORDER BY id") == antes
    assert fixos_ativos() == [("Ana Silva", 1, 7, "CIA"), ("Ana Silva", 2, 8, "CIA")]
    assert consulta("SELECT * FROM agenda_avulsas") == []


def test_copiar_da_grade_volta_para_a_semana_e_mantem_todas(http):
    ocupar(aluno("Ana Silva"), 1, 7)
    r = copiar(http, todas=1)
    assert r.headers["location"].startswith(f"/agenda?semana={SEMANA}&todas=1&msg=")


def test_copiar_da_grade_grava_num_insert_so(http, espiar):
    nomes = [aluno(f"Aluno {k:03d}") for k in range(30)]
    for k, c in enumerate(nomes):   # 30 alunos em vários horários, uns em 3 locais, uns em 2 no mesmo horário
        ocupar(c, 1 + k % 6, 5 + k // 2 % 19, "CIA")
        if k % 3 == 0:
            ocupar(c, 1 + k % 6, 5 + k // 2 % 19, "SmartFit")
            ocupar(c, 1 + k % 6, 5 + k // 2 % 19, "Outro")
    ocupar(None, 6, 22, nome="Nome solto")
    with espiar() as vistos:
        r = copiar(http)
    assert erro(r) is None
    escritas = gravacoes(vistos)
    assert len(escritas) == 1 and escritas[0].startswith("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?,?,?,?),(?,?,?,?)")
    assert escritas[0].count("(?,?,?,?)") == len(fixos_ativos())
    assert len(fixos_ativos()) == 30   # cada aluno uma vez, sem repetir por local


def test_inserir_fixos_em_blocos_de_200_linhas(http):
    ana = aluno("Ana Silva")

    class Contador:
        def __init__(self):
            self.chamadas = []

        def execute(self, sql, params=()):
            self.chamadas.append((sql, list(params)))

    for n, esperado in ((1, 1), (200, 1), (201, 2), (450, 3)):
        c = Contador()
        linhas = [(ana, 1 + k % 6, 5 + k % 19, "CIA") for k in range(n)]
        main.inserir_fixos(c, linhas)
        assert len(c.chamadas) == esperado
        assert sum(sql.count("(?,?,?,?)") for sql, _ in c.chamadas) == n and sum(len(p) for _, p in c.chamadas) == 4 * n
        assert all(len(p) <= 800 for _, p in c.chamadas)   # abaixo do limite de parâmetros do SQLite
    c = Contador()
    main.inserir_fixos(c, [])
    assert c.chamadas == []   # nada a gravar, nenhuma viagem ao banco
    con = db.conectar()   # e de verdade no banco
    try:
        with con:
            main.inserir_fixos(con, [(ana, 1 + k % 6, 5 + k % 19, "CIA") for k in range(450)])
        assert con.execute("SELECT COUNT(*) FROM agenda_fixos").fetchone()[0] == 450
    finally:
        con.close()


def test_rotas_antigas_da_agenda_sairam(http):
    for rota in ("/agenda/vincular-todos", "/agenda/fixo/excluir"):
        assert http.post(rota, data={}, follow_redirects=False).status_code == 404
    assert not hasattr(main, "grade_sem_vinculo")


# ---------- 3d. lixeira ----------
def test_horario_fixo_vai_para_a_lixeira_e_pode_ser_restaurado(http):
    ana = aluno("Ana Silva")
    horario(http, 1, 7, ana)
    assert "Horário fixo" not in http.get("/dados").text
    horario(http, 1, 7, "", "", local="")
    rid = consulta("SELECT id FROM agenda_fixos")[0][0]
    assert aulas() == [] and grade(1, 7) == livre()
    dados = http.get("/dados").text
    assert "Horário fixo" in dados and "Ana Silva — Seg 07h (CIA)" in dados
    r = http.post("/lixeira/restaurar", data={"tabela": "agenda_fixos", "rid": rid}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"] and erro(r) is None
    assert [(a["nome"], a["dia"], a["hora"]) for a in aulas()] == [("Ana Silva", 1, 7)]
    assert grade(1, 7) == da_grade(ana, "Ana Silva")   # a Grade volta a ficar com ela
    assert "Ana Silva — Seg 07h" not in http.get("/dados").text


def test_restaurar_horario_fixo_respeita_o_limite_de_2_alunos(http):
    ana, bia, caio = aluno("Ana Silva"), aluno("Bia Costa"), aluno("Caio Santos")
    horario(http, 1, 7, ana)
    rid = consulta("SELECT id FROM agenda_fixos")[0][0]
    horario(http, 1, 7, bia, caio)   # a Ana sai, entram os dois
    r = http.post("/lixeira/restaurar", data={"tabela": "agenda_fixos", "rid": rid}, follow_redirects=False)
    assert erro(r) == "Seg 07h já tem 2 alunos. Tire um deles antes de restaurar."
    assert sorted(n for n, *_ in fixos_ativos()) == ["Bia Costa", "Caio Santos"]
    horario(http, 1, 7, ana)         # a Ana volta pelo seletor; a linha antiga da lixeira não pode duplicar
    r = http.post("/lixeira/restaurar", data={"tabela": "agenda_fixos", "rid": rid}, follow_redirects=False)
    assert "já está no horário" in erro(r) and fixos_ativos() == [("Ana Silva", 1, 7, "CIA")]


# ---------- 3. marcar a aula ----------
def test_marcar_feita_faltou_desfazer_e_alerta_de_sem_aula(http):
    grava("DELETE FROM campanha_fases WHERE tipo='bloqueio'")   # dia de bloqueio não conta no "sem aula" (ver test_alertas)
    ana = aluno("Ana Silva")
    hoje = dt.date.today()
    http.post(f"/clientes/{ana}/evento", data={"tipo": "aula", "data": (hoje - dt.timedelta(days=20)).isoformat()})
    sem_aula = "Ana Silva — sem aula desde"
    assert any(a.startswith(sem_aula) for a in alertas())

    r = marcar(http, ana, hoje.isoformat(), 7, "feita")
    assert r.status_code == 303 and erro(r) is None and r.headers["location"].startswith(f"/agenda?semana={main.inicio_semana(hoje.isoformat())}")
    assert ativos(ana, hoje.isoformat()) == [("aula", 7, f"Agenda — {main.DIAS_CURTO[hoje.isoweekday()]} 07h CIA")]
    assert not any(a.startswith(sem_aula) for a in alertas())   # feita conta como aula

    marcar(http, ana, hoje.isoformat(), 7, "faltou")
    assert [t for t, _, _ in ativos(ana, hoje.isoformat())] == ["falta"]
    assert consulta("SELECT COUNT(*) FROM cliente_eventos WHERE cliente_id=? AND data=? AND tipo='aula' AND excluido_em IS NOT NULL", ana, hoje.isoformat()) == [(1,)]
    assert any(a.startswith(sem_aula) for a in alertas())   # faltou não conta como aula

    marcar(http, ana, hoje.isoformat(), 7, "desmarcou")
    assert [t for t, _, _ in ativos(ana, hoje.isoformat())] == ["desmarcou"]
    assert any(a.startswith(sem_aula) for a in alertas())

    marcar(http, ana, hoje.isoformat(), 7, "")   # Desfazer
    assert ativos(ana, hoje.isoformat()) == []


def test_marcacao_aparece_na_agenda_e_no_historico_do_aluno(http):
    ana = aluno("Ana Silva")
    fixo(ana, 2, 7)
    assert aulas()[0]["situacao"] in ("pendente", "futura") and aulas()[0]["estado"] is None
    marcar(http, ana, TER, 7, "feita")
    assert (aulas()[0]["estado"], aulas()[0]["situacao"]) == ("feita", "feita")
    marcar(http, ana, TER, 7, "faltou")
    assert aulas()[0]["estado"] == "faltou"
    ficha = http.get(f"/clientes/{ana}").text
    assert 'tag vermelho">faltou</span>' in ficha and "Agenda — Ter 07h CIA" in ficha
    assert '<option value="falta">Faltou</option>' in ficha and '<option value="desmarcou">Desmarcou</option>' in ficha
    marcar(http, ana, TER, 7, "desmarcou")
    assert 'tag amarelo">desmarcou</span>' in http.get(f"/clientes/{ana}").text
    marcar(http, ana, TER, 7, "feita")
    assert 'tag azul">aula dada</span>' in http.get(f"/clientes/{ana}").text


def test_duas_aulas_no_mesmo_dia_tem_marcacao_propria(http):
    ana = aluno("Ana Silva")
    fixo(ana, 2, 7)
    fixo(ana, 2, 18)
    marcar(http, ana, TER, 7, "feita")
    assert [(a["hora"], a["estado"]) for a in aulas()] == [(7, "feita"), (18, None)]
    marcar(http, ana, TER, 18, "faltou")
    assert [(a["hora"], a["estado"]) for a in aulas()] == [(7, "feita"), (18, "faltou")]
    assert [(t, h) for t, h, _ in ativos(ana, TER)] == [("aula", 7), ("falta", 18)]   # marcar o das 18h não mexe no das 7h


def test_aula_lancada_pela_ficha_conta_como_feita_na_agenda(http):
    ana = aluno("Ana Silva")
    fixo(ana, 2, 7)
    fixo(ana, 2, 18)
    http.post(f"/clientes/{ana}/evento", data={"tipo": "aula", "data": TER})   # sem hora
    assert consulta("SELECT hora FROM cliente_eventos WHERE tipo='aula'") == [(None,)]
    assert [(a["hora"], a["estado"]) for a in aulas()] == [(7, "feita"), (18, "feita")]
    marcar(http, ana, TER, 7, "faltou")   # a marcação nova substitui a da ficha
    assert consulta("SELECT COUNT(*) FROM cliente_eventos WHERE tipo='aula' AND excluido_em IS NULL") == [(0,)]
    assert [(a["hora"], a["estado"]) for a in aulas()] == [(7, "faltou"), (18, None)]   # a aula da ficha era uma só e foi trocada


def test_marcar_dado_invalido_nao_grava(http):
    ana = aluno("Ana Silva")
    grava("UPDATE clientes SET excluido_em=datetime('now','localtime') WHERE id=?", aluno("Caio Excluido"))
    for ruim in ({"estado": "talvez"}, {"hora": 4}, {"hora": 24}, {"data": "ontem"}, {"data": ""}, {"cliente_id": 999}, {"cliente_id": 2}):
        dados = {"cliente_id": ana, "data": TER, "hora": 7, "local": "CIA", "estado": "feita", **ruim}
        r = http.post("/agenda/marcar", data=dados, follow_redirects=False)
        assert r.status_code == 303 and erro(r), ruim
    assert consulta("SELECT * FROM cliente_eventos") == []


def test_marcar_domingo_e_futuro_pode(http):
    ana = aluno("Ana Silva")
    assert erro(marcar(http, ana, "2026-10-18", 9, "desmarcou")) is None   # desmarcar com antecedência vale em qualquer data
    assert ativos(ana, "2026-10-18") == [("desmarcou", 9, "Agenda — Dom 09h CIA")]


# ---------- 4. aula avulsa ----------
def test_avulsa_aparece_so_na_semana_marca_exclui_e_restaura(http):
    ana = aluno("Ana Silva")
    r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "SmartFit", "hora": 15, "repetir": 0, "data": QUA, "semana": "2026-11-02"},
                  follow_redirects=False)
    assert erro(r) is None and f"semana={SEMANA}" in r.headers["location"]   # volta para a semana da aula
    assert consulta("SELECT cliente_id, data, hora, local FROM agenda_avulsas") == [(ana, QUA, 15, "SmartFit")]
    assert consulta("SELECT COUNT(*) FROM grade_slots") == [(0,)]   # avulsa não mexe na Grade
    assert "Ana Silva" in semana(http) and "avulsa" in semana(http)
    assert "Ana Silva" not in semana(http, "2026-10-19") and "Ana Silva" not in semana(http, "2026-10-05")

    assert [(a["avulsa"], a["estado"]) for a in aulas()] == [(True, None)]
    marcar(http, ana, QUA, 15, "feita", avulsa=1, local="SmartFit")
    assert ativos(ana, QUA) == [("aula", 15, "Agenda — Qua 15h SmartFit (avulsa)")]
    assert aulas()[0]["estado"] == "feita"

    aid = consulta("SELECT id FROM agenda_avulsas")[0][0]
    r = http.post(f"/agenda/avulsa/{aid}/excluir", data={"semana": SEMANA}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    assert aulas() == [] and "Ana Silva" not in semana(http)
    assert f"Ana Silva {QUA}" in http.get("/dados").text   # na lixeira
    http.post("/lixeira/restaurar", data={"tabela": "agenda_avulsas", "rid": aid})
    assert [a["avulsa_id"] for a in aulas()] == [aid]


def test_avulsa_no_domingo_e_data_invalida_sao_recusadas(http):
    ana = aluno("Ana Silva")
    for data, trecho in (("2026-10-18", "Domingo"), ("", "data"), ("amanhã", "data")):
        r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "hora": 9, "repetir": 0, "data": data}, follow_redirects=False)
        assert trecho in erro(r), data
    assert consulta("SELECT * FROM agenda_avulsas") == []


# ---------- 6. aviso de aulas sem marcar ----------
def sem_marcar(hoje):
    con = db.conectar()
    try:
        return main.aulas_sem_marcar(con, hoje)
    finally:
        con.close()


def test_aulas_sem_marcar_conta_de_segunda_ate_ontem_e_pula_bloqueio(http):
    ana = aluno("Ana Silva")
    for dia, hora in ((1, 7), (1, 18), (2, 8), (3, 9), (4, 10), (5, 11)):   # seg 7h, seg 18h, ter, qua, qui, sex
        fixo(ana, dia, hora)
    grava("DELETE FROM campanha_fases WHERE tipo='bloqueio'")
    quinta = dt.date(2026, 10, 15)
    assert sem_marcar(quinta) == 4   # seg 7h, seg 18h, ter e qua; quinta (hoje) e sexta ainda não contam
    marcar(http, ana, "2026-10-12", 7, "feita")
    http.post(f"/clientes/{ana}/evento", data={"tipo": "aula", "data": TER})   # da ficha, sem hora
    assert sem_marcar(quinta) == 2
    grava("INSERT INTO campanha_fases (nome, inicio, fim, tipo, ordem) VALUES ('Bloqueio de teste', '2026-10-14', '2026-10-14', 'bloqueio', 99)")
    assert sem_marcar(quinta) == 1   # quarta é bloqueio
    marcar(http, ana, "2026-10-12", 18, "desmarcou")   # desmarcou também é marcar
    assert sem_marcar(quinta) == 0
    assert sem_marcar(dt.date(2026, 10, 12)) == 0     # segunda: não há dia anterior na semana
    assert sem_marcar("2026-10-12") == 0              # aceita data em texto
    assert sem_marcar(dt.date(2026, 10, 18)) == 2     # domingo: a semana toda já passou; faltam quinta e sexta
    assert sem_marcar(dt.date(2026, 10, 19)) == 0     # semana nova, nada ainda


def test_aulas_sem_marcar_ignora_aluno_inativo_e_data_de_inicio(http):
    ana, bia = aluno("Ana Silva", data_inicio="2026-10-14"), aluno("Bia Inativa", status="inativo")
    fixo(ana, 1, 7)   # segunda, antes do início
    fixo(ana, 3, 7)   # quarta, no dia do início
    fixo(bia, 2, 7)
    grava("DELETE FROM campanha_fases WHERE tipo='bloqueio'")
    assert sem_marcar(dt.date(2026, 10, 16)) == 1


def test_alerta_de_aulas_sem_marcar_leva_para_a_agenda(http):
    ana = aluno("Ana Silva")
    fixo(ana, 1, 7)   # segunda desta semana
    grava("DELETE FROM campanha_fases WHERE tipo='bloqueio'")
    hoje = dt.date.today()
    todos = [a for a in main.alertas(_con()) if "da agenda sem marcar" in a["texto"]]
    if hoje.weekday() == 0:   # hoje é segunda: ainda não passou nenhuma aula da semana
        assert todos == []
    else:
        assert [(a["texto"], a["url"], a["cor"]) for a in todos] == [("1 aula da agenda sem marcar nesta semana", "/agenda", "azul")]
        marcar(http, ana, (hoje - dt.timedelta(days=hoje.weekday())).isoformat(), 7, "feita")
        assert not [a for a in alertas() if "da agenda sem marcar" in a]


def _con():
    return db.conectar()


# ---------- 6b. marcar várias (lote), reposições, controle do aluno, vários horários ----------
SEG, QUI, SEX = "2026-10-12", "2026-10-15", "2026-10-16"


def lote(http, itens, **extra):
    corpo = itens if isinstance(itens, str) else json.dumps(itens)
    return http.post("/agenda/marcar-lote", data={"itens": corpo, "semana": SEMANA, **extra}, follow_redirects=False)


def item(cid, data=TER, hora=7, estado="feita", local="CIA", **extra):
    return {"cliente_id": cid, "data": data, "hora": hora, "local": local, "avulsa": 0, "estado": estado, **extra}


def repor(cid, data, hora=7, local="CIA", reposicao=1, excluida=False):
    """Aula avulsa direto na tabela (reposição por padrão)."""
    return grava("INSERT INTO agenda_avulsas (cliente_id, data, hora, local, reposicao, excluido_em) VALUES (?,?,?,?,?,?)",
                 cid, data, hora, local, reposicao, "2026-10-01 10:00:00" if excluida else None)


def saldo(cid, hoje=dt.date(2026, 10, 15)):
    con = db.conectar()
    try:
        return main.saldos_reposicao(con, [cid], hoje)[cid]
    finally:
        con.close()


def desmarcou(http, cid, data=TER, hora=7):
    marcar(http, cid, data, hora, "desmarcou")


def painel(http, **params):
    r = http.get("/agenda", params={"semana": SEMANA, **params})
    assert r.status_code == 200
    return r.text


def contador(pagina, classe):
    return int(re.search(rf'<div class="contador {classe}"><b>(\d+)</b>', pagina).group(1))


def test_marcar_lote_5_itens_gravam_em_2_comandos(http, espiar):
    ids = [aluno(f"Aluno {k}") for k in range(5)]
    marcar(http, ids[0], TER, 7, "faltou")   # já tinha uma marca: o lote substitui
    with espiar() as vistos:
        r = lote(http, [item(c, TER, 7 + k, ["feita", "feita", "faltou", "desmarcou", "feita"][k]) for k, c in enumerate(ids)])
    assert erro(r) is None and msg(r) == "5 aulas marcadas: 3 feitas, 1 faltou, 1 desmarcou."
    escritas = gravacoes(vistos)
    assert len(escritas) == 2 and escritas[0].startswith("UPDATE cliente_eventos SET excluido_em") and escritas[1].startswith("INSERT INTO cliente_eventos")
    assert escritas[1].count("(?,?,?,?,?)") == 5
    assert ativos(ids[0], TER) == [("aula", 7, "Agenda — Ter 07h CIA")]
    assert ativos(ids[3], TER) == [("desmarcou", 10, "Agenda — Ter 10h CIA")]


def test_marcar_lote_volta_para_a_semana_e_mantem_todas_aluno_e_mes(http):
    ana = aluno("Ana Silva")
    r = lote(http, [item(ana)], todas=1, aluno=ana, mes="2026-10")
    assert r.headers["location"].startswith(f"/agenda?semana={SEMANA}&todas=1&aluno={ana}&mes=2026-10&msg=")
    r = lote(http, [item(ana)], aluno="abc", mes="lixo")   # lixo some do endereço
    assert r.headers["location"].startswith(f"/agenda?semana={SEMANA}&msg=")


def test_marcar_lote_limpar_remove_a_marca_e_so_limpar_nao_insere(http, espiar):
    ana = aluno("Ana Silva")
    marcar(http, ana, TER, 7, "feita")
    with espiar() as vistos:
        r = lote(http, [item(ana, estado="")])
    assert msg(r) == "1 marcação desfeita." and ativos(ana, TER) == []
    assert len(gravacoes(vistos)) == 1   # só o UPDATE
    marcar(http, ana, TER, 7, "feita")
    r = lote(http, [item(ana, estado=""), item(ana, QUA, 8, "faltou")])
    assert msg(r) == "1 aula marcada: 1 faltou, 1 desfeita." and ativos(ana, TER) == [] and [t for t, *_ in ativos(ana, QUA)] == ["falta"]


def test_marcar_lote_item_repetido_vale_o_ultimo(http):
    ana = aluno("Ana Silva")
    r = lote(http, [item(ana, estado="feita"), item(ana, estado="faltou"), item(ana, estado="desmarcou")])
    assert msg(r) == "1 aula marcada: 1 desmarcou."
    assert [t for t, *_ in ativos(ana, TER)] == ["desmarcou"]


def test_marcar_lote_substitui_a_aula_lancada_pela_ficha_e_mantem_outras_horas(http):
    ana = aluno("Ana Silva")
    grava("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', ?)", ana, TER)   # sem hora
    marcar(http, ana, TER, 9, "feita")
    lote(http, [item(ana, TER, 7, "faltou")])
    assert [(t, h) for t, h, _ in ativos(ana, TER)] == [("aula", 9), ("falta", 7)]


@pytest.mark.parametrize("itens", ["", "nao e json", "{}", "[]", "[1]", json.dumps([item(1, estado="talvez")]), json.dumps([item(1, data="2026-13-45")]),
                                   json.dumps([item(1, data="")]), json.dumps([item(1, hora=4)]), json.dumps([item(1, hora=24)]),
                                   json.dumps([item(1, hora="x")]), json.dumps([{"data": TER, "hora": 7, "estado": "feita"}]),
                                   json.dumps([item(1), item(1, estado="feita", hora=99)]), json.dumps([item(999)])])
def test_marcar_lote_invalido_nao_grava_nada(http, espiar, itens):
    aluno("Ana Silva")
    with espiar() as vistos:
        r = lote(http, itens)
    assert r.status_code == 303 and erro(r)
    assert gravacoes(vistos) == [] and consulta("SELECT COUNT(*) FROM cliente_eventos") == [(0,)]


def test_marcar_lote_aluno_inexistente_ou_excluido_recusa_tudo(http):
    ana, bia = aluno("Ana Silva"), aluno("Bia Costa")
    grava("UPDATE clientes SET excluido_em=datetime('now') WHERE id=?", bia)
    assert erro(lote(http, [item(ana), item(bia)])) == "Aluno não encontrado."
    assert erro(lote(http, [item(ana), item(999)])) == "Aluno não encontrado."
    assert consulta("SELECT COUNT(*) FROM cliente_eventos") == [(0,)]


def test_marcar_lote_aceita_300_e_recusa_301(http, espiar):
    ana = aluno("Ana Silva")
    muitos = [item(ana, dt.date(2026, 1, 1).replace(day=1 + k % 28, month=1 + k // 28).isoformat(), 7) for k in range(300)]
    with espiar() as vistos:
        r = lote(http, muitos)
    assert erro(r) is None and msg(r) == "300 aulas marcadas: 300 feitas."
    assert len(gravacoes(vistos)) == 3   # 1 UPDATE (300 aulas cabem num) + 2 INSERTs de 150 linhas
    assert erro(lote(http, muitos + [item(ana, TER, 8)])) == "Muitas aulas de uma vez (máximo 300)."
    assert consulta("SELECT COUNT(*) FROM cliente_eventos WHERE excluido_em IS NULL") == [(300,)]


def test_marcar_lote_descricao_traz_avulsa_e_reposicao(http):
    ana = aluno("Ana Silva")
    lote(http, [item(ana, TER, 7, avulsa=1), item(ana, QUA, 8, avulsa=1, reposicao=1), item(ana, QUI, 9, local="")])
    assert ativos(ana, TER) == [("aula", 7, "Agenda — Ter 07h CIA (avulsa)")]
    assert ativos(ana, QUA) == [("aula", 8, "Agenda — Qua 08h CIA (reposição)")]
    assert ativos(ana, QUI) == [("aula", 9, "Agenda — Qui 09h")]


def test_marcar_simples_usa_o_helper_com_2_gravacoes_e_desfazer_com_1(http, espiar):
    ana = aluno("Ana Silva")
    with espiar() as vistos:
        r = marcar(http, ana, TER, 7, "feita")
    assert msg(r) == "Ana: aula feita." and len(gravacoes(vistos)) == 2
    with espiar() as vistos:
        r = marcar(http, ana, TER, 7, "")
    assert msg(r) == "Ana: marcação desfeita." and len(gravacoes(vistos)) == 1 and ativos(ana, TER) == []


def test_marcar_simples_com_reposicao_e_com_aluno_e_mes_no_endereco(http):
    ana = aluno("Ana Silva")
    r = http.post("/agenda/marcar", data={"cliente_id": ana, "data": TER, "hora": 7, "local": "CIA", "estado": "feita", "avulsa": 1, "reposicao": 1,
                                         "semana": SEMANA, "aluno": ana, "mes": "2026-10"}, follow_redirects=False)
    assert ativos(ana, TER) == [("aula", 7, "Agenda — Ter 07h CIA (reposição)")]
    assert r.headers["location"].startswith(f"/agenda?semana={SEMANA}&aluno={ana}&mes=2026-10&msg=")


def test_gravar_marcas_em_blocos(http, espiar):
    ana = aluno("Ana Silva")
    itens = [(ana, f"2026-{1 + k // 28:02d}-{1 + k % 28:02d}", 7, "feita", "x") for k in range(320)]
    con = db.conectar()
    try:
        vistos = []
        with con:
            main.gravar_marcas(Espia(con, vistos), itens, bloco_exclusao=100, bloco_insercao=150)
    finally:
        con.close()
    sql = gravacoes(vistos)
    assert [x.split()[0] for x in sql] == ["UPDATE"] * 4 + ["INSERT"] * 3
    assert consulta("SELECT COUNT(*) FROM cliente_eventos WHERE excluido_em IS NULL") == [(320,)]


# ---- saldo de reposição ----
def test_saldo_desmarcou_conta_1(http):
    ana = aluno("Ana Silva")
    desmarcou(http, ana)
    assert saldo(ana) == {"devidas": 1, "usadas": 0, "saldo": 1, "agendadas": 0}


def test_saldo_faltou_e_feita_comum_nao_geram_reposicao(http):
    ana = aluno("Ana Silva")
    marcar(http, ana, TER, 7, "faltou")
    marcar(http, ana, QUA, 7, "feita")
    assert saldo(ana)["saldo"] == 0


def test_saldo_reposicao_feita_desconta_1(http):
    ana = aluno("Ana Silva")
    desmarcou(http, ana)
    repor(ana, QUI, 8)
    assert saldo(ana)["saldo"] == 1
    marcar(http, ana, QUI, 8, "feita", avulsa=1)
    assert saldo(ana) == {"devidas": 1, "usadas": 1, "saldo": 0, "agendadas": 0}


def test_saldo_reposicao_com_falta_tambem_desconta(http):
    ana = aluno("Ana Silva")
    desmarcou(http, ana)
    repor(ana, QUI, 8)
    marcar(http, ana, QUI, 8, "faltou", avulsa=1)
    assert saldo(ana)["saldo"] == 0   # faltar na reposição perde a reposição


def test_saldo_reposicao_desmarcada_vira_2(http):
    ana = aluno("Ana Silva")
    desmarcou(http, ana)
    repor(ana, QUI, 8)
    marcar(http, ana, QUI, 8, "desmarcou", avulsa=1)
    assert saldo(ana) == {"devidas": 2, "usadas": 0, "saldo": 2, "agendadas": 0}


def test_saldo_reposicao_excluida_volta_o_saldo(http):
    ana = aluno("Ana Silva")
    desmarcou(http, ana)
    rid = repor(ana, QUI, 8)
    marcar(http, ana, QUI, 8, "feita", avulsa=1)
    assert saldo(ana)["saldo"] == 0
    http.post(f"/agenda/avulsa/{rid}/excluir", data={"semana": SEMANA})
    assert saldo(ana)["saldo"] == 1
    repor(ana, SEX, 8, excluida=True)   # excluída desde o início: nunca conta (nem como agendada)
    assert saldo(ana)["agendadas"] == 0


def test_saldo_avulsa_comum_feita_nao_desconta(http):
    ana = aluno("Ana Silva")
    desmarcou(http, ana)
    repor(ana, QUI, 8, reposicao=0)
    marcar(http, ana, QUI, 8, "feita", avulsa=1)
    assert saldo(ana) == {"devidas": 1, "usadas": 0, "saldo": 1, "agendadas": 0}


def test_saldo_nunca_fica_negativo_e_marca_so_vale_na_mesma_hora(http):
    ana = aluno("Ana Silva")
    repor(ana, QUI, 8)
    marcar(http, ana, QUI, 8, "feita", avulsa=1)
    assert saldo(ana) == {"devidas": 0, "usadas": 1, "saldo": 0, "agendadas": 0}   # repôs sem dever: não fica negativo
    desmarcou(http, ana, TER)
    repor(ana, SEX, 9)
    marcar(http, ana, SEX, 10, "feita")   # outra hora do mesmo dia: não é a reposição
    assert saldo(ana)["usadas"] == 1


def test_saldo_agendadas_contam_so_as_de_hoje_em_diante_sem_marca(http):
    ana = aluno("Ana Silva")
    repor(ana, "2026-10-14", 7)   # ontem, sem marca: não é agendada
    repor(ana, "2026-10-15", 7)   # hoje
    repor(ana, "2026-10-16", 7)
    repor(ana, "2026-10-17", 7)   # com marca: já foi
    marcar(http, ana, "2026-10-17", 7, "feita", avulsa=1)
    repor(ana, "2026-10-18", 7, reposicao=0)   # avulsa comum não conta
    assert saldo(ana)["agendadas"] == 2


def test_saldos_de_todos_os_alunos_em_2_selects_agrupados(http, espiar):
    a, b, c = aluno("Ana"), aluno("Bia"), aluno("Caio")
    desmarcou(http, a); desmarcou(http, a, QUA); desmarcou(http, b)
    repor(a, QUI, 8)
    con = db.conectar()
    try:
        vistos = []
        todos = main.saldos_reposicao(Espia(con, vistos), None, dt.date(2026, 10, 15))
        com_ids = main.saldos_reposicao(Espia(con, vistos), [a, b, c], dt.date(2026, 10, 15))
    finally:
        con.close()
    assert len(vistos) == 4 and all(v.startswith("SELECT") and "GROUP BY" in v for v in vistos)   # 2 por chamada, nunca por aluno
    assert todos[a]["saldo"] == 2 and todos[a]["agendadas"] == 1 and todos[b]["saldo"] == 1 and c not in todos
    assert com_ids[c] == {"devidas": 0, "usadas": 0, "saldo": 0, "agendadas": 0}
    assert main.saldos_reposicao(db.conectar(), [], dt.date(2026, 10, 15)) == {}


def test_aulas_da_semana_traz_a_flag_de_reposicao(http):
    ana = aluno("Ana Silva")
    fixo(ana, 1, 7)
    repor(ana, TER, 8)
    repor(ana, QUA, 9, reposicao=0)
    assert [(a["hora"], a["avulsa"], a["reposicao"]) for a in aulas()] == [(7, False, False), (8, True, True), (9, True, False)]


def test_incluir_avulsa_de_reposicao_e_comum(http):
    ana = aluno("Ana Silva")
    r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "repetir": 0, "data": TER, "hora": 8, "reposicao": 1, "semana": SEMANA,
                                          "aluno": ana, "mes": "2026-10"}, follow_redirects=False)
    assert msg(r) == "Reposição de Ana Silva em 13/10 às 08h." and f"aluno={ana}&mes=2026-10" in r.headers["location"]
    r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "repetir": 0, "data": QUA, "hora": 9}, follow_redirects=False)
    assert msg(r) == "Aula avulsa de Ana Silva em 14/10 às 09h."
    assert consulta("SELECT data, hora, reposicao FROM agenda_avulsas ORDER BY id") == [(TER, 8, 1), (QUA, 9, 0)]
    pagina = painel(http)
    assert '<span class="av">reposição</span>' in pagina and '<span class="av">avulsa</span>' in pagina


def test_reposicao_aparece_na_agenda_e_na_janelinha_com_o_saldo(http):
    ana = aluno("Ana Silva")
    desmarcou(http, ana)
    repor(ana, TER, 8)
    cartoes = cards(painel(http), 2, 8)
    (info, botao), = cartoes
    assert info["alunos"][0]["reposicao"] is True and info["alunos"][0]["deve"] == 1 and info["alunos"][0]["base"] in ("pendente", "futura")
    assert 'class="av">reposição<' in botao


# ---- painel de controle do aluno ----
def test_painel_mostra_saldo_contadores_e_lista_do_mes(http):
    ana, bia = aluno("Ana Silva"), aluno("Bia Costa")
    fixo(ana, 2, 7)
    marcar(http, ana, TER, 7, "feita")
    marcar(http, ana, "2026-10-06", 7, "faltou")
    desmarcou(http, ana, "2026-10-20")
    desmarcou(http, ana, "2026-09-29")   # de outro mês: não entra nas contagens do mês, mas o saldo é o total
    repor(ana, QUI, 8)
    marcar(http, ana, QUI, 8, "feita", avulsa=1)
    marcar(http, bia, TER, 7, "feita")
    pagina = painel(http, aluno=ana, mes="2026-10")
    assert "Reposições a fazer: 1" in pagina and "agendadas: 0" in pagina and "outubro de 2026" in pagina
    assert (contador(pagina, "feita"), contador(pagina, "faltou"), contador(pagina, "desmarcou"), contador(pagina, "reposta")) == (2, 1, 1, 1)
    lista = pagina.split('<ul class="aulas-aluno">', 1)[1].split("</ul>", 1)[0]
    assert [x for x in re.findall(r'<span class="quando">([^<]*)</span>', lista)] == ["Ter 06/10 · 07h", "Ter 13/10 · 07h", "Qui 15/10 · 08h", "Ter 20/10 · 07h"]
    assert lista.count("reposição</span>") == 1 and "Bia" not in lista and "CIA" in lista
    assert f'href="/clientes/{ana}"' in pagina and 'id="btn-repor"' in pagina


def test_painel_mes_sem_aulas_e_setas_de_mes(http):
    ana = aluno("Ana Silva")
    pagina = painel(http, aluno=ana, mes="2026-12")
    assert "Nenhuma aula marcada neste mês." in pagina and "dezembro de 2026" in pagina
    pagina = pagina.replace("&amp;", "&")
    assert f"&aluno={ana}&mes=2026-11" in pagina and f"&aluno={ana}&mes=2027-01" in pagina   # ← e → (vira o ano)
    assert f"&aluno={ana}&mes=2025-12" in painel(http, aluno=ana, mes="2026-01").replace("&amp;", "&")


def test_painel_abre_no_mes_atual_e_o_saldo_e_sempre_o_total(http):
    ana = aluno("Ana Silva")
    desmarcou(http, ana, "2026-03-03")
    pagina = painel(http, aluno=ana)   # sem mes: mês atual
    assert f"{main.MESES[dt.date.today().month - 1]} de {dt.date.today().year}" in pagina
    assert "Reposições a fazer: 1" in pagina
    assert "Reposições a fazer: 1" in painel(http, aluno=ana, mes="2026-10")   # a desmarcação é de março


def test_painel_reposicao_agendada_aparece_na_lista_do_mes(http):
    ana = aluno("Ana Silva")
    desmarcou(http, ana)
    repor(ana, "2099-05-04", 9)
    pagina = painel(http, aluno=ana, mes="2099-05")
    assert "agendadas: 1" in pagina and "Seg 04/05 · 09h" in pagina and 'class="tag azul">agendada<' in pagina
    assert contador(pagina, "feita") == contador(pagina, "reposta") == 0


@pytest.mark.parametrize("params", [{"aluno": "999"}, {"aluno": "abc"}, {"aluno": "-3"}, {"aluno": "0"}, {"aluno": "1" * 40}, {"aluno": "", "mes": "2026-10"}])
def test_painel_aluno_invalido_abre_a_agenda_normal(http, params):
    aluno("Ana Silva")
    pagina = painel(http, **params)
    assert 'class="painel-aluno"' not in pagina and 'id="sel-aluno"' in pagina


@pytest.mark.parametrize("mes", ["2026-13", "2026-00", "x", "26-10", "1999-12", "2101-01", "2026-1", "2026-10-01"])
def test_painel_mes_invalido_cai_no_mes_atual_sem_erro(http, mes):
    ana = aluno("Ana Silva")
    pagina = painel(http, aluno=ana, mes=mes)
    assert 'class="painel-aluno"' in pagina and f"{main.MESES[dt.date.today().month - 1]} de {dt.date.today().year}" in pagina


def test_painel_de_aluno_excluido_nao_abre_e_inativo_abre(http):
    ana, bia = aluno("Ana Silva"), aluno("Bia Costa", status="inativo")
    grava("UPDATE clientes SET excluido_em=datetime('now') WHERE id=?", ana)
    assert 'class="painel-aluno"' not in painel(http, aluno=ana)
    pagina = painel(http, aluno=bia)
    assert 'class="painel-aluno"' in pagina and "Bia Costa (inativo)" in pagina


def test_painel_escapa_nome_com_script(http):
    ana = aluno("<script>alert(1)</script> Ana")
    fixo(ana, 2, 7)
    desmarcou(http, ana)
    pagina = painel(http, aluno=ana, mes="2026-10")
    assert "<script>alert(1)</script>" not in pagina and "&lt;script&gt;alert(1)&lt;/script&gt; Ana" in pagina
    assert "\\u003cscript\\u003ealert(1)" in pagina   # no data-info (JSON) o nome sai com <


def test_painel_mantem_aluno_e_mes_nos_links_e_formularios(http):
    ana = aluno("Ana Silva")
    fixo(ana, 2, 7)
    marcar(http, ana, TER, 7, "feita")
    pagina = painel(http, aluno=ana, mes="2026-10").replace("&amp;", "&")   # o & dos links sai escapado no HTML
    assert f"/agenda?semana=2026-10-05&aluno={ana}&mes=2026-10" in pagina and f"/agenda?semana=2026-10-19&aluno={ana}&mes=2026-10" in pagina
    assert pagina.count(f'<input type="hidden" name="aluno" value="{ana}">') >= 2   # janelinha do horário e incluir (Copiar da Grade e Hoje só aparecem quando cabem)
    assert 'data-aluno="' + str(ana) + '" data-mes="2026-10"' in pagina
    sem = painel(http)
    assert '<input type="hidden" name="aluno"' not in sem and "&aluno=" not in sem.split("<script>")[0]   # (o script monta o link do "Ver controle")


@pytest.mark.parametrize("rota,dados", [("/agenda/horario", {"dia": 2, "hora": 7, "aluno1": "", "local": "CIA"}),
                                        ("/agenda/copiar-grade", {})])
def test_outras_rotas_da_agenda_mantem_aluno_e_mes(http, rota, dados):
    ana = aluno("Ana Silva")
    r = http.post(rota, data={**dados, "semana": SEMANA, "aluno": ana, "mes": "2026-10"}, follow_redirects=False)
    assert f"&aluno={ana}&mes=2026-10" in r.headers["location"]


def test_excluir_avulsa_mantem_aluno_e_mes(http):
    ana = aluno("Ana Silva")
    rid = repor(ana, TER, 8)
    r = http.post(f"/agenda/avulsa/{rid}/excluir", data={"semana": SEMANA, "aluno": ana, "mes": "2026-10"}, follow_redirects=False)
    assert f"&aluno={ana}&mes=2026-10" in r.headers["location"]


def test_pagina_tem_o_modo_marcar_varias_e_a_barra(http):
    ana = aluno("Ana Silva")
    fixo(ana, 2, 7)
    pagina = painel(http)
    assert 'id="btn-lote"' in pagina and 'id="barra-lote"' in pagina and "/agenda/marcar-lote" in pagina
    assert pagina.count('data-pincel="') == 4


# ---- vários horários fixos de uma vez ----
def incluir_varios(http, cid, dias, horas, local="CIA", **extra):
    return http.post("/agenda/incluir", data={"cliente_id": cid, "local": local, "repetir": 1, "dias": dias, "horas": horas, "semana": SEMANA, **extra},
                     follow_redirects=False)


def test_varios_horarios_3_pares_gravam_1_insert_na_agenda_e_1_upsert_na_grade(http, espiar):
    ana = aluno("Ana Silva")
    with espiar() as vistos:
        r = incluir_varios(http, ana, [1, 3, 5], [7, 7, 18])
    assert erro(r) is None and msg(r) == "Ana entrou em Seg 07h, Qua 07h, Sex 18h (CIA)."
    escritas = gravacoes(vistos)
    assert len(escritas) == 2
    assert escritas[0].startswith("INSERT INTO agenda_fixos") and escritas[0].count("(?,?,?,?)") == 3
    assert escritas[1].startswith("INSERT INTO grade_slots") and escritas[1].count("(?,?,?,?,?,?,?,?)") == 6 and "ON CONFLICT" in escritas[1]
    assert fixos_ativos() == [("Ana Silva", 1, 7, "CIA"), ("Ana Silva", 3, 7, "CIA"), ("Ana Silva", 5, 18, "CIA")]
    for dia, hora in ((1, 7), (3, 7), (5, 18)):
        assert grade(dia, hora) == da_grade(ana, "Ana Silva")
    assert [(a["dia"], a["hora"]) for a in aulas()] == [(1, 7), (3, 7), (5, 18)]


def test_varios_horarios_mantem_multiplicador_da_grade_e_nao_mexe_em_celula_de_outro(http):
    ana, bia = aluno("Ana Silva"), aluno("Bia Costa")
    grava("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador) VALUES ('Pacotes', 1, 'CIA', 7, 'livre', 0.9)")
    ocupar(bia, 3, 7)
    grava("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status) VALUES ('Pacotes', 5, 'CIA', 18, 'indisponivel')")
    ocupar(ana, 2, 7)   # esta já é dela nos dois tipos
    antes = consulta("SELECT * FROM grade_slots WHERE NOT (dia=1 AND hora=7) ORDER BY id")
    r = incluir_varios(http, ana, [1, 3, 5, 2], [7, 7, 18, 7])
    assert erro(r) is None
    assert len(fixos_ativos()) == 4   # a Agenda ganha todos; a Grade é que respeita as células dos outros
    assert consulta("SELECT * FROM grade_slots WHERE NOT (dia=1 AND hora=7) ORDER BY id") == antes
    assert consulta("SELECT tipo_calculo, status, cliente_id, multiplicador FROM grade_slots WHERE dia=1 AND hora=7 ORDER BY tipo_calculo") == [
        ("Mensalidades", "ocupado", ana, 1.0), ("Pacotes", "ocupado", ana, 0.9)]


def test_varios_horarios_grade_com_erro_nao_derruba_a_agenda(http, monkeypatch):
    ana = aluno("Ana Silva")

    def quebra(*a, **k):
        raise sqlite3.OperationalError("grade fora do ar")
    monkeypatch.setattr(main, "salvar_slots", quebra)
    r = incluir_varios(http, ana, [1, 2], [7, 7])
    assert erro(r) is None and len(fixos_ativos()) == 2 and consulta("SELECT COUNT(*) FROM grade_slots") == [(0,)]


def test_varios_horarios_par_cheio_e_pulado_com_aviso(http):
    ana, bia, caio = aluno("Ana Silva"), aluno("Bia Costa"), aluno("Caio Santos")
    horario(http, 2, 7, bia, caio)
    r = incluir_varios(http, ana, [1, 2, 3], [7, 7, 7])
    assert erro(r) is None and msg(r) == "Ana entrou em Seg 07h, Qua 07h (CIA). Ter 07h já tem 2 alunos."
    assert fixos_ativos(2, 7) == [("Bia Costa", 2, 7, "CIA"), ("Caio Santos", 2, 7, "CIA")] and len(fixos_ativos()) == 4


def test_varios_horarios_todos_cheios_vira_erro_e_nao_grava(http, espiar):
    ana, bia, caio = aluno("Ana Silva"), aluno("Bia Costa"), aluno("Caio Santos")
    horario(http, 2, 7, bia, caio)
    horario(http, 3, 7, bia, caio)
    with espiar() as vistos:
        r = incluir_varios(http, ana, [2, 3], [7, 7])
    assert erro(r) == "Ter 07h, Qua 07h já têm 2 alunos." and gravacoes(vistos) == []


def test_varios_horarios_par_que_ja_existe_diz_ja_estava_e_nao_grava(http, espiar):
    ana = aluno("Ana Silva")
    horario(http, 1, 7, ana)
    with espiar() as vistos:
        r = incluir_varios(http, ana, [1, 1], [7, 7])   # par repetido vale uma vez
    assert msg(r) == "Ana Silva já está no horário fixo de Seg 07h (CIA)."   # virou um par só: mesmo texto do modo antigo
    assert gravacoes(vistos) == [] and len(fixos_ativos()) == 1
    with espiar() as vistos:
        r = incluir_varios(http, ana, [1, 4], [7, 9])
    assert msg(r) == "Ana entrou em Qui 09h (CIA). Seg 07h já estava."
    assert [x.split()[0] for x in gravacoes(vistos)] == ["INSERT", "INSERT"]


def test_varios_horarios_dois_que_ja_estavam_no_plural(http):
    ana = aluno("Ana Silva")
    horario(http, 1, 7, ana)
    horario(http, 3, 7, ana)
    r = incluir_varios(http, ana, [1, 3], [7, 7])
    assert msg(r) == "Seg 07h, Qua 07h já estavam."


def test_varios_horarios_em_outro_local_troca_o_local_so_daquele_par(http):
    ana = aluno("Ana Silva")
    horario(http, 1, 7, ana, local="CIA")
    r = incluir_varios(http, ana, [1, 2], [7, 7], local="SmartFit")
    assert erro(r) is None and msg(r) == "Ana entrou em Ter 07h (SmartFit). Ana agora fica em SmartFit em Seg 07h."
    assert fixos_ativos() == [("Ana Silva", 1, 7, "SmartFit"), ("Ana Silva", 2, 7, "SmartFit")]
    assert grade(1, 7, "CIA") == livre() and grade(1, 7, "SmartFit") == da_grade(ana, "Ana Silva") and grade(2, 7, "SmartFit") == da_grade(ana, "Ana Silva")


def test_modo_antigo_de_um_dia_continua_igual(http):
    ana = aluno("Ana Silva")
    r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "dia": 2, "hora": 7, "repetir": 1, "semana": SEMANA}, follow_redirects=False)
    assert msg(r) == "Ana Silva entrou no horário fixo de Ter 07h (CIA). A Grade também foi atualizada."
    assert fixos_ativos() == [("Ana Silva", 2, 7, "CIA")] and grade(2, 7) == da_grade(ana, "Ana Silva")
    r = incluir_varios(http, ana, [2], [7])   # um par só, pelas listas: mesmo texto de quem já estava
    assert msg(r) == "Ana Silva já está no horário fixo de Ter 07h (CIA)."
    r = incluir_varios(http, ana, [4], [9])
    assert msg(r) == "Ana Silva entrou no horário fixo de Qui 09h (CIA). A Grade também foi atualizada."


@pytest.mark.parametrize("dados", [{"dias": [1, 2], "horas": [7]}, {"dias": [1], "horas": [7, 8]}, {"dias": [7], "horas": [7]}, {"dias": [0], "horas": [7]},
                                   {"dias": [1, 2], "horas": [7, 4]}, {"dias": [1, 2], "horas": [7, 24]}, {"dias": [1], "horas": [7], "local": ""},
                                   {"dias": [1], "horas": [7], "cliente_id": 999}])
def test_varios_horarios_invalido_nao_grava_nada(http, dados):
    ana = aluno("Ana Silva")
    base = {"cliente_id": ana, "local": "CIA", "repetir": 1, **dados}
    r = http.post("/agenda/incluir", data=base, follow_redirects=False)
    assert r.status_code == 303 and erro(r)
    assert consulta("SELECT * FROM agenda_fixos") == [] and consulta("SELECT * FROM grade_slots") == []


def test_varios_horarios_maximo_de_12_pares(http):
    ana = aluno("Ana Silva")
    dias = [d for d in range(1, 7) for _ in (0, 1)]
    horas = [h for _ in range(1, 7) for h in (7, 8)]
    r = incluir_varios(http, ana, dias[:12], horas[:12])
    assert erro(r) is None and len(fixos_ativos()) == 12
    outra = aluno("Bia Costa")
    assert erro(incluir_varios(http, outra, dias + [1], horas + [9])) == "No máximo 12 horários de uma vez."
    assert len(fixos_ativos()) == 12


def test_varios_horarios_ignoram_dia_e_hora_soltos_quando_vem_a_lista(http):
    ana = aluno("Ana Silva")
    r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "repetir": 1, "dia": 6, "hora": 20, "dias": [1], "horas": [7]}, follow_redirects=False)
    assert erro(r) is None and fixos_ativos() == [("Ana Silva", 1, 7, "CIA")]


def test_incluir_com_aluno_e_mes_volta_para_o_painel(http):
    ana = aluno("Ana Silva")
    r = incluir_varios(http, ana, [1], [7], aluno=ana, mes="2026-10", todas=1)
    assert r.headers["location"].startswith(f"/agenda?semana={SEMANA}&todas=1&aluno={ana}&mes=2026-10&msg=")


def test_salvar_slots_em_blocos_e_salvar_slot_continua(http):
    con = db.conectar()
    try:
        vistos = []
        slots = [("Pacotes", 1 + k % 6, "CIA", 5 + k // 6, "ocupado", None, "X", 1.0) for k in range(30)]
        with con:
            main.salvar_slots(Espia(con, vistos), slots, bloco=10)
            main.salvar_slot(con, "Pacotes", 1, "CIA", 5, "livre", None, None, 1.0)   # a mesma célula de novo: atualiza, não duplica
        assert len(vistos) == 3 and consulta("SELECT COUNT(*) FROM grade_slots") == [(30,)]
        assert consulta("SELECT status FROM grade_slots WHERE dia=1 AND hora=5") == [("livre",)]
    finally:
        con.close()


# ---------- 7. banco antigo ----------
def test_banco_antigo_ganha_coluna_hora_e_tabela_de_avulsas(tmp_path, monkeypatch):
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY, nome TEXT NOT NULL)")
    con.execute("""CREATE TABLE cliente_eventos (id INTEGER PRIMARY KEY, cliente_id INTEGER NOT NULL, tipo TEXT NOT NULL, data TEXT NOT NULL,
                   valor REAL, descricao TEXT, criado_em TEXT, excluido_em TEXT)""")
    con.execute("INSERT INTO clientes (nome) VALUES ('Antigo')")
    con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (1, 'aula', '2026-09-01')")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(caminho)
    db.iniciar_banco(caminho)   # idempotente
    con = db.conectar(caminho)
    try:
        assert [tuple(r) for r in con.execute("SELECT tipo, data, hora FROM cliente_eventos")] == [("aula", "2026-09-01", None)]
        assert con.execute("SELECT COUNT(*) FROM agenda_avulsas").fetchone()[0] == 0
    finally:
        con.close()


def test_banco_antigo_sem_agenda_fixos_ganha_a_tabela(tmp_path, monkeypatch):
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY, nome TEXT NOT NULL)")
    con.execute("INSERT INTO clientes (nome) VALUES ('Antigo')")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(caminho)
    db.iniciar_banco(caminho)   # de novo: CREATE IF NOT EXISTS, sem perder linhas
    con = db.conectar(caminho)
    try:
        assert {r[1] for r in con.execute("PRAGMA table_info(agenda_fixos)")} == {"id", "cliente_id", "dia", "hora", "local", "criado_em", "excluido_em"}
        with con:
            con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (1, 2, 7, 'CIA')")
        db.iniciar_banco(caminho)
        assert [tuple(r) for r in con.execute("SELECT cliente_id, dia, hora, local, excluido_em FROM agenda_fixos")] == [(1, 2, 7, "CIA", None)]
        assert con.execute("SELECT criado_em FROM agenda_fixos").fetchone()[0]   # padrão preenchido
    finally:
        con.close()


def test_banco_antigo_de_avulsas_sem_reposicao_ganha_a_coluna(tmp_path, monkeypatch):
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY, nome TEXT NOT NULL)")
    con.execute("""CREATE TABLE agenda_avulsas (id INTEGER PRIMARY KEY, cliente_id INTEGER NOT NULL, data TEXT NOT NULL, hora INTEGER NOT NULL,
                   local TEXT NOT NULL, criado_em TEXT, excluido_em TEXT)""")
    con.execute("INSERT INTO clientes (nome) VALUES ('Antigo')")
    con.execute("INSERT INTO agenda_avulsas (cliente_id, data, hora, local) VALUES (1, '2026-09-01', 7, 'CIA')")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(caminho)
    db.iniciar_banco(caminho)   # idempotente
    con = db.conectar(caminho)
    try:
        assert "reposicao" in {r[1] for r in con.execute("PRAGMA table_info(agenda_avulsas)")}
        assert [tuple(r) for r in con.execute("SELECT data, hora, reposicao FROM agenda_avulsas")] == [("2026-09-01", 7, 0)]   # as antigas ficam como aula comum
        with con:
            con.execute("INSERT INTO agenda_avulsas (cliente_id, data, hora, local, reposicao) VALUES (1, '2026-09-02', 7, 'CIA', 1)")
        assert main.saldos_reposicao(con, [1], dt.date(2026, 9, 1))[1]["agendadas"] == 1
    finally:
        con.close()


def test_banco_novo_tem_reposicao_zero_por_padrao(http):
    ana = aluno("Ana Silva")
    grava("INSERT INTO agenda_avulsas (cliente_id, data, hora, local) VALUES (?, ?, 7, 'CIA')", ana, TER)
    assert consulta("SELECT reposicao FROM agenda_avulsas") == [(0,)]
