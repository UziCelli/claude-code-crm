"""Agenda: horários fixos da Grade + aulas avulsas, marcar Feita/Faltou/Desmarcou, aviso de aulas sem marcar."""
import datetime as dt
import sqlite3
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
    nome = nome or (consulta("SELECT nome FROM clientes WHERE id=?", cid)[0][0] if cid else "Fulano da planilha")
    for t in tipos:
        grava("""INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, cliente_id, cliente_nome)
                 VALUES (?,?,?,?,'ocupado',?,?)""", t, dia, local, hora, cid, nome)


def semana(http, quando=SEMANA, **extra):
    r = http.get("/agenda", params={"semana": quando, **extra})
    assert r.status_code == 200
    return tabela(r.text)


def tabela(pagina):
    return pagina.split('<table class="grade agenda">', 1)[1].split("</table>", 1)[0]


def aulas(quando=SEMANA, hoje=None):
    con = db.conectar()
    try:
        return main.aulas_da_semana(con, dt.date.fromisoformat(quando), hoje)
    finally:
        con.close()


def erro(r):
    return unquote(r.headers["location"].split("erro=", 1)[1]) if "erro=" in r.headers["location"] else None


def marcar(http, cid, data, hora=7, estado="feita", avulsa=0, local="CIA"):
    return http.post("/agenda/marcar", data={"cliente_id": cid, "data": data, "hora": hora, "local": local, "estado": estado,
                                             "avulsa": avulsa, "semana": data}, follow_redirects=False)


def ativos(cid, data):
    return consulta("""SELECT tipo, hora, descricao FROM cliente_eventos WHERE cliente_id=? AND data=? AND excluido_em IS NULL
                       AND tipo IN ('aula','falta','desmarcou') ORDER BY id""", cid, data)


# ---------- 1. o que aparece ----------
def test_aluno_ocupado_na_grade_aparece_e_inativo_nao(http):
    ana, bia, caio, dora = aluno("Ana Silva"), aluno("Bia Inativa", status="inativo"), aluno("Caio Excluido"), aluno("Dora Nova", data_inicio=QUA)
    grava("UPDATE clientes SET excluido_em=datetime('now','localtime') WHERE id=?", caio)
    for hora, c in enumerate((ana, bia, caio), 7):
        ocupar(c, 2, hora)
    ocupar(dora, 2, 10)   # terça, mas só começa na quarta
    ocupar(dora, 4, 10)   # quinta: já começou
    pagina = semana(http)
    assert "Ana Silva" in pagina and "Bia Inativa" not in pagina and "Caio Excluido" not in pagina
    lista = aulas()
    assert [(a["nome"], a["dia"], a["hora"], a["data"]) for a in lista] == [("Ana Silva", 2, 7, TER), ("Dora Nova", 4, 10, "2026-10-15")]   # um por aula, mesmo nos 2 tipos
    assert "Dora Nova" not in semana(http, "2026-10-05")   # semana anterior ao início


def test_tela_com_semana_invalida_abre_na_semana_atual(http):
    assert http.get("/agenda?semana=lixo").status_code == 200
    assert http.get("/agenda?semana=2026-13-45&todas=1").status_code == 200
    assert main.inicio_semana("lixo") == main.inicio_semana(dt.date.today().isoformat())
    assert main.inicio_semana("2026-10-18") == dt.date(2026, 10, 12)   # domingo pertence à semana que termina nele
    assert main.inicio_semana("2026-10-12") == dt.date(2026, 10, 12)


def test_ver_todos_os_horarios_e_semana_vazia(http):
    vazia = http.get("/agenda", params={"semana": SEMANA}).text
    assert "Nenhuma aula nesta semana" in vazia and ">05h<" in tabela(vazia) and ">23h<" in tabela(vazia)
    ocupar(aluno("Ana Silva"), 2, 7)
    pagina = http.get("/agenda", params={"semana": SEMANA}).text
    assert "Nenhuma aula nesta semana" not in pagina and ">07h<" in tabela(pagina) and ">08h<" not in tabela(pagina)
    assert "Ver todos os horários" in pagina
    pagina = http.get("/agenda", params={"semana": SEMANA, "todas": 1}).text
    assert ">05h<" in tabela(pagina) and ">23h<" in tabela(pagina) and "Só horários com aula" in pagina


# ---------- 2. incluir horário fixo ----------
def test_incluir_fixo_grava_grade_nos_dois_tipos(http):
    ana = aluno("Ana Silva")
    grava("""INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador) VALUES ('Pacotes', 2, 'CIA', 7, 'livre', 0.9)""")
    r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "dia": 2, "hora": 7, "repetir": 1, "semana": SEMANA}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"] and erro(r) is None
    assert consulta("""SELECT tipo_calculo, status, cliente_id, cliente_nome, multiplicador FROM grade_slots WHERE dia=2 AND hora=7 ORDER BY tipo_calculo""") == [
        ("Mensalidades", "ocupado", ana, "Ana Silva", 1.0), ("Pacotes", "ocupado", ana, "Ana Silva", 0.9)]   # mantém o multiplicador de cada tipo
    for tipo in ("Pacotes", "Mensalidades"):
        assert "Ana Silva" in http.get("/grade", params={"tipo": tipo, "local": "CIA"}).text
    assert [a["nome"] for a in aulas()] == ["Ana Silva"]
    # a mesma pessoa de novo no mesmo horário não dá erro
    assert erro(http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "dia": 2, "hora": 7, "repetir": 1}, follow_redirects=False)) is None


def test_incluir_fixo_em_horario_de_outro_aluno_e_recusado(http):
    ana, bia = aluno("Ana Silva"), aluno("Bia Costa")
    ocupar(ana, 2, 7)
    antes = consulta("SELECT * FROM grade_slots ORDER BY id")
    r = http.post("/agenda/incluir", data={"cliente_id": bia, "local": "CIA", "dia": 2, "hora": 7, "repetir": 1}, follow_redirects=False)
    assert erro(r) == "Esse horário já é de Ana Silva na Grade. Tire ele de lá antes."
    assert consulta("SELECT * FROM grade_slots ORDER BY id") == antes


def test_incluir_fixo_em_horario_indisponivel_e_recusado(http):
    ana = aluno("Ana Silva")
    grava("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status) VALUES ('Pacotes', 3, 'CIA', 8, 'indisponivel')")
    r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "dia": 3, "hora": 8, "repetir": 1}, follow_redirects=False)
    assert "indisponível" in erro(r)
    assert consulta("SELECT tipo_calculo, status, cliente_id FROM grade_slots") == [("Pacotes", "indisponivel", None)]


def test_ligar_nome_sem_vinculo_ao_aluno(http):
    ana = aluno("Ana Silva")
    ocupar(None, 4, 9)   # nome escrito à mão na planilha, sem cliente_id
    antes = semana(http)
    assert "Fulano da planilha" in antes and "ligar ao aluno" in antes and aulas() == []
    r = http.post("/agenda/incluir", data={"cliente_id": ana, "local": "CIA", "dia": 4, "hora": 9, "repetir": 1, "semana": SEMANA}, follow_redirects=False)
    assert erro(r) is None
    assert consulta("SELECT tipo_calculo, cliente_id, cliente_nome FROM grade_slots ORDER BY tipo_calculo") == [
        ("Mensalidades", ana, "Ana Silva"), ("Pacotes", ana, "Ana Silva")]
    depois = semana(http)
    assert "Fulano da planilha" not in depois and "ligar ao aluno" not in depois
    assert [(a["nome"], a["dia"], a["hora"]) for a in aulas()] == [("Ana Silva", 4, 9)]


# ---------- ligar nomes da Grade: sugestão e ligar todos ----------
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


def test_pagina_traz_sugestao_no_botao_do_nome_sem_vinculo(http):
    ana = aluno("Ana Silva")
    ocupar(None, 2, 7, nome="ana")
    ocupar(None, 3, 8, nome="Treino próprio")
    botoes = [b for b in semana(http).split("<button") if "sem-vinculo" in b]
    assert len(botoes) == 2
    com = next(b for b in botoes if ">ana<" in b)
    sem = next(b for b in botoes if "Treino próprio" in b)
    assert f'data-cliente_id="{ana}"' in com and 'data-cliente_id=""' in sem


def link_grade(pagina):
    return 'action="/agenda/vincular-todos"' in pagina


def test_vincular_todos_liga_os_que_batem_e_pula_os_ambiguos_e_conflitos(http):
    ana, jose, bia1, _ = aluno("Ana Silva"), aluno("José Álvares"), aluno("Bia Costa"), aluno("Bia Lima")
    ocupar(None, 2, 7, nome="ana")
    ocupar(None, 3, 8, nome="jose alvares")
    ocupar(None, 4, 9, nome="Bia")                     # ambígua
    ocupar(None, 5, 10, nome="Treino próprio")         # não é aluno
    ocupar(None, 1, 11, tipos=("Pacotes",), nome="Ana")
    ocupar(bia1, 1, 11, tipos=("Mensalidades",))       # conflito: o outro tipo já é da Bia
    pagina = http.get("/agenda", params={"semana": SEMANA}).text
    assert link_grade(pagina) and "Ligar 3 nomes da Grade aos alunos" in pagina   # ana, jose e a do (1,11): essa tem sugestão, mas vai conflitar
    r = http.post("/agenda/vincular-todos", data={"semana": SEMANA}, follow_redirects=False)
    assert r.status_code == 303 and erro(r) is None
    assert "2 horários ligados aos alunos. 3 ficaram para ligar à mão." in unquote(r.headers["location"])
    assert consulta("SELECT tipo_calculo, cliente_id, cliente_nome FROM grade_slots WHERE dia=2 AND hora=7 ORDER BY tipo_calculo") == [
        ("Mensalidades", ana, "Ana Silva"), ("Pacotes", ana, "Ana Silva")]
    assert consulta("SELECT DISTINCT cliente_id, cliente_nome FROM grade_slots WHERE dia=3 AND hora=8") == [(jose, "José Álvares")]
    assert consulta("SELECT DISTINCT cliente_id, cliente_nome FROM grade_slots WHERE dia=4 AND hora=9") == [(None, "Bia")]
    assert consulta("SELECT DISTINCT cliente_id, cliente_nome FROM grade_slots WHERE dia=5 AND hora=10") == [(None, "Treino próprio")]
    assert consulta("SELECT tipo_calculo, cliente_id FROM grade_slots WHERE dia=1 AND hora=11 ORDER BY tipo_calculo") == [
        ("Mensalidades", bia1), ("Pacotes", None)]   # conflito: nada mudou
    assert sorted(a["nome"] for a in aulas()) == ["Ana Silva", "Bia Costa", "José Álvares"]   # a Bia já estava na segunda 11h


def test_botao_de_ligar_todos_so_aparece_quando_tem_o_que_ligar(http):
    ana = aluno("Ana Silva")
    assert not link_grade(http.get("/agenda", params={"semana": SEMANA}).text)             # nada sem vínculo
    ocupar(None, 3, 8, nome="Treino próprio")
    assert not link_grade(http.get("/agenda", params={"semana": SEMANA}).text)             # sem vínculo, mas sem sugestão
    ocupar(None, 2, 7, nome="Ana")
    pagina = http.get("/agenda", params={"semana": SEMANA, "todas": 1}).text
    assert link_grade(pagina) and "Ligar 1 nome da Grade ao aluno" in pagina
    assert "Ligar 1 horário da Grade ao aluno com o mesmo nome? Dá para conferir e tirar depois." in pagina
    r = http.post("/agenda/vincular-todos", data={"semana": SEMANA, "todas": 1}, follow_redirects=False)
    assert "1 horário ligado ao aluno. 1 ficou para ligar à mão." in unquote(r.headers["location"]) and "todas=1" in r.headers["location"]
    assert not link_grade(http.get("/agenda", params={"semana": SEMANA}).text)             # só sobrou o que não tem aluno
    assert consulta("SELECT DISTINCT cliente_id FROM grade_slots WHERE dia=2 AND hora=7") == [(ana,)]


def test_janelinhas_trazem_situacao_e_link_da_grade(http):
    ana = aluno("Ana Silva")
    ocupar(ana, 2, 7)
    ocupar(ana, 3, 8)
    marcar(http, ana, TER, 7, "faltou")
    pagina = semana(http)
    assert 'data-situacao="faltou"' in pagina and ('data-situacao="pendente"' in pagina or 'data-situacao="futura"' in pagina)
    pagina = http.get("/agenda", params={"semana": SEMANA}).text
    assert 'id="aula-estado"' in pagina and 'id="b-desfazer"' in pagina and 'id="a-grade"' in pagina


@pytest.mark.parametrize("dados", [{"dia": 7, "hora": 7}, {"dia": 0, "hora": 7}, {"dia": 2, "hora": 4}, {"dia": 2, "hora": 24}, {"dia": 2, "hora": 7, "local": ""},
                                   {"dia": 2, "hora": 7, "cliente_id": 999}])
def test_incluir_fixo_invalido_nao_grava(http, dados):
    ana = aluno("Ana Silva")
    base = {"cliente_id": ana, "local": "CIA", "repetir": 1, **dados}
    r = http.post("/agenda/incluir", data=base, follow_redirects=False)
    assert r.status_code == 303 and erro(r)
    assert consulta("SELECT * FROM grade_slots") == []


# ---------- 3. marcar a aula ----------
def test_marcar_feita_faltou_desfazer_e_alerta_de_sem_aula(http):
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
    ocupar(ana, 2, 7)
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
    ocupar(ana, 2, 7)
    ocupar(ana, 2, 18)
    marcar(http, ana, TER, 7, "feita")
    assert [(a["hora"], a["estado"]) for a in aulas()] == [(7, "feita"), (18, None)]
    marcar(http, ana, TER, 18, "faltou")
    assert [(a["hora"], a["estado"]) for a in aulas()] == [(7, "feita"), (18, "faltou")]
    assert [(t, h) for t, h, _ in ativos(ana, TER)] == [("aula", 7), ("falta", 18)]   # marcar o das 18h não mexe no das 7h


def test_aula_lancada_pela_ficha_conta_como_feita_na_agenda(http):
    ana = aluno("Ana Silva")
    ocupar(ana, 2, 7)
    ocupar(ana, 2, 18)
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


# ---------- 5. tirar do horário fixo ----------
def test_tirar_do_horario_fixo_libera_a_grade_e_mantem_o_historico(http):
    ana, bia = aluno("Ana Silva"), aluno("Bia Costa")
    ocupar(ana, 2, 7)
    ocupar(bia, 2, 8)
    grava("UPDATE grade_slots SET multiplicador=0.9 WHERE hora=7 AND tipo_calculo='Pacotes'")
    marcar(http, ana, TER, 7, "feita")
    r = http.post("/agenda/fixo/excluir", data={"cliente_id": ana, "local": "CIA", "dia": 2, "hora": 7, "semana": SEMANA}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    assert consulta("SELECT tipo_calculo, status, cliente_id, cliente_nome, multiplicador FROM grade_slots WHERE hora=7 ORDER BY tipo_calculo") == [
        ("Mensalidades", "livre", None, None, 1.0), ("Pacotes", "livre", None, None, 0.9)]
    assert consulta("SELECT status, cliente_id FROM grade_slots WHERE hora=8 AND tipo_calculo='Pacotes'") == [("ocupado", bia)]   # só o dela
    assert [a["nome"] for a in aulas()] == ["Bia Costa"]
    assert ativos(ana, TER) == [("aula", 7, "Agenda — Ter 07h CIA")]   # histórico fica


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
        ocupar(ana, dia, hora)
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
    ocupar(ana, 1, 7)   # segunda, antes do início
    ocupar(ana, 3, 7)   # quarta, no dia do início
    ocupar(bia, 2, 7)
    grava("DELETE FROM campanha_fases WHERE tipo='bloqueio'")
    assert sem_marcar(dt.date(2026, 10, 16)) == 1


def test_alerta_de_aulas_sem_marcar_leva_para_a_agenda(http):
    ana = aluno("Ana Silva")
    ocupar(ana, 1, 7)   # segunda desta semana
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
