"""Testes para alerts, lead parado e redirecionamento com destaque."""
import datetime as dt
import pytest
from fastapi.testclient import TestClient

from app import db, financeiro, main


@pytest.fixture
def con_temp(tmp_path, monkeypatch):
    """Conexão com banco temporário."""
    db_path = tmp_path / "crm.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(db_path)
    con = db.conectar(db_path)
    yield con
    con.close()


def test_dias_parado(con_temp):
    """Calcula dias parado com base na última mudança de etapa."""
    hoje = dt.date.today().isoformat()
    tres_dias_atras = (dt.date.today() - dt.timedelta(days=3)).isoformat()

    # Lead parado há 3 dias (limite da etapa "lead" é 2)
    lead_parado = {
        "id": 1,
        "nome": "Test",
        "etapa": "lead",
        "data_mudanca_etapa": tres_dias_atras,
        "atualizado_em": tres_dias_atras + " 00:00:00"
    }
    dias = main.dias_parado(con_temp, lead_parado, hoje)
    assert dias == 3

    # Lead que ainda não passou do limite
    um_dia_atras = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    lead_fresco = {
        "id": 2,
        "nome": "Fresh",
        "etapa": "lead",
        "data_mudanca_etapa": um_dia_atras,
        "atualizado_em": um_dia_atras + " 00:00:00"
    }
    dias = main.dias_parado(con_temp, lead_fresco, hoje)
    assert dias is None

    # Lead em conversa com limite 4
    lead_conversa = {
        "id": 3,
        "nome": "Conv",
        "etapa": "conversa",
        "data_mudanca_etapa": tres_dias_atras,
        "atualizado_em": tres_dias_atras + " 00:00:00"
    }
    dias = main.dias_parado(con_temp, lead_conversa, hoje)
    assert dias is None  # 3 dias < 4 limite


@pytest.fixture
def cliente_http(tmp_path, monkeypatch):
    """Cliente HTTP para testar rotas."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    con = db.conectar(tmp_path / "crm.db")
    with con:
        lid = con.execute("INSERT INTO leads (nome, etapa, canal_origem) VALUES (?, ?, ?)",
                         ("Lead Teste", "lead", "Instagram")).lastrowid
    con.close()
    return TestClient(main.app, base_url="http://localhost"), lid  # sem "with": o lifespan não roda


def test_post_etapa_redireciona_com_destaque(cliente_http):
    """POST /leads/{lid}/etapa redireciona para /leads?destaque=<id>."""
    http, lid = cliente_http

    # Fazer POST para mudar etapa
    r = http.post(f"/leads/{lid}/etapa", data={"etapa": "conversa"}, follow_redirects=False)

    # Verificar que é redirect 303
    assert r.status_code == 303
    assert f"destaque={lid}" in r.headers["location"]
    assert "/leads" in r.headers["location"]


def test_post_etapa_cliente_redireciona_com_destaque(cliente_http):
    """Converter lead para cliente redireciona com destaque."""
    http, lid = cliente_http

    # Ir para avaliação primeira
    http.post(f"/leads/{lid}/etapa", data={"etapa": "conversa"}, follow_redirects=False)
    http.post(f"/leads/{lid}/etapa", data={"etapa": "avaliacao"}, follow_redirects=False)

    # Converter para cliente
    r = http.post(f"/leads/{lid}/etapa", data={"etapa": "cliente"}, follow_redirects=False)

    # Verificar redirect com destaque
    assert r.status_code == 303
    assert f"destaque={lid}" in r.headers["location"]
    assert "/leads" in r.headers["location"]


def test_alertas_ordem_e_agregacao(con_temp):
    """Renovação vencida vem antes da próxima; 3 alunos sem telefone = 1 linha agregada."""
    hoje = dt.date.today()
    with con_temp:
        for nome, dias in [("Proxima", 3), ("Vencida", -2)]:
            con_temp.execute("INSERT INTO clientes (nome, telefone, status, tipo_servico, data_renovacao) VALUES (?,?,?,?,?)",
                             (nome, "11999990000", "ativo", "Consultoria Online", (hoje + dt.timedelta(days=dias)).isoformat()))
        for i in range(3):
            con_temp.execute("INSERT INTO clientes (nome, status, tipo_servico, data_renovacao) VALUES (?,?,?,?)",
                             (f"Sem tel {i}", "ativo", "Consultoria Online", (hoje + dt.timedelta(days=60)).isoformat()))
    lista = main.alertas(con_temp)
    textos = [a["texto"] for a in lista]
    assert textos.index(next(t for t in textos if "Vencida" in t)) < textos.index(next(t for t in textos if "Proxima" in t))
    assert [a["cor"] for a in lista if "Vencida" in a["texto"]] == ["vermelho"]
    assert sum("cadastro incompleto" in t for t in textos) == 1
    assert next(a for a in lista if "incompleto" in a["texto"])["texto"].startswith("3 alunos")
    assert [a["grav"] for a in lista] == sorted(a["grav"] for a in lista)


def test_whatsapp(con_temp):
    assert main.wa("(11) 98765-4321") == "https://wa.me/5511987654321?text="
    assert main.wa("+55 11 98765-4321", "oi") == "https://wa.me/5511987654321?text=oi"
    assert main.wa("5511987654321").startswith("https://wa.me/5511987654321?")
    assert main.wa("", "oi") == "https://wa.me/?text=oi"
    assert main.wa(None, "Olá & tchau").endswith("?text=Ol%C3%A1%20%26%20tchau")
    modelos = db.parametros(con_temp, "msg_whatsapp")
    assert set(modelos) == {"renovacao", "falta", "boas_vindas", "reativacao", "cobranca"}
    assert main.preencher(modelos["falta"], "Ana", "01/01/2026").startswith("Oi, Ana!")
    txt = main.preencher(modelos["cobranca"], "Dora", "11/10/2026", {"dias": 20, "valor": "R$ 400,00", "multa": "R$ 8,00",
                                                                     "juros": "R$ 2,67", "total": "R$ 410,67"})
    assert "{" not in txt and "20 dias" in txt and "R$ 410,67" in txt


def test_alerta_contas_vencidas(con_temp):
    """Conta pendente vencida gera um alerta vermelho para /financeiro; paga, não."""
    ontem = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    with con_temp:
        con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria) VALUES ('PJ','saida',?,100,'Outros')", (ontem,))
    a = [x for x in main.alertas(con_temp) if x["url"] == "/financeiro"]
    assert len(a) == 1 and a[0]["cor"] == "vermelho" and a[0]["texto"].startswith("1 conta vencida")
    assert a[0]["texto"].endswith("(R$ 100,00)")   # o total já aparece no alerta
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET pago_em=?", (ontem,))
    assert not [x for x in main.alertas(con_temp) if x["url"] == "/financeiro"]

# ---------- revisão dos alertas do Painel de 31/10 ----------
def dia(n):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


def cliente(con, nome, renova=None, valor=400, tipo="Pacote de Aulas", inicio=None):
    with con:
        return con.execute("""INSERT INTO clientes (nome, telefone, status, tipo_servico, valor, data_renovacao, data_inicio)
                              VALUES (?, '11999990000', 'ativo', ?, ?, ?, ?)""", (nome, tipo, valor, renova, inicio)).lastrowid


def do_aluno(con, nome):
    return [a for a in main.alertas(con) if a.get("nome") == nome]


def test_alerta_de_renovacao_some_com_pagamento_e_vira_cobranca_sem_ele(con_temp):
    """Pago (mesmo parcial) sai do vermelho; sem pagamento, o alerta traz o botão de cobrar com multa e juros."""
    a = cliente(con_temp, "Bruno", dia(-26))
    t = cliente(con_temp, "Dora", dia(-20))
    [al] = do_aluno(con_temp, "Bruno")
    assert al["cor"] == "vermelho"
    with con_temp:
        con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id)"
                         " VALUES ('PJ','entrada',?,?,200,'Pacotes de Aulas',?)", (dia(-3), dia(-3), a))
    assert all(x["cor"] != "vermelho" for x in do_aluno(con_temp, "Bruno"))   # renovou: no máximo o aviso do próximo mês
    [th] = do_aluno(con_temp, "Dora")
    assert (th["cor"], th["modelo"], th["botao"]) == ("vermelho", "cobranca", "Cobrar R$ 410,67")
    texto = main.preencher(db.parametros(con_temp, "msg_whatsapp")["cobranca"], th["nome"], th["data"], th["extra"])
    assert "20 dias" in texto and "R$ 8,00" in texto and "R$ 2,67" in texto and "R$ 410,67" in texto
    sem_valor = cliente(con_temp, "Sem valor", dia(-5), valor=0)
    [sv] = do_aluno(con_temp, "Sem valor")
    assert (sv["modelo"], sv["botao"]) == ("renovacao", None)   # sem valor mensal não dá para calcular: WhatsApp normal
    assert t and sem_valor


def test_ficha_renovacao_sem_data_e_pulou_o_mes(con_temp):
    http = TestClient(main.app, base_url="http://localhost")
    v = cliente(con_temp, "Caio", "2026-10-25")
    r = http.post(f"/clientes/{v}/evento", data={"tipo": "renovacao", "data": "2026-10-31"}, follow_redirects=False)
    assert "Renova%C3%A7%C3%A3o%20registrada" in r.headers["location"]
    assert financeiro.renovacoes(con_temp, v)[v]["efetiva"] == "2026-11-25"
    r = http.post(f"/clientes/{v}/evento", data={"tipo": "renovacao", "data": "2026-10-31"}, follow_redirects=False)
    assert financeiro.renovacoes(con_temp, v)[v]["efetiva"] == "2026-11-25"           # marcar de novo não pula outro mês
    assert "continua" in r.headers["location"]

    g = cliente(con_temp, "Elisa", "2026-10-06")
    r = http.post(f"/clientes/{g}/evento", data={"tipo": "pausa", "data": "2026-10-31", "nova_renovacao": "2026-11-01"},
                  follow_redirects=False)
    assert r.status_code == 303 and "erro" not in r.headers["location"]
    ev = con_temp.execute("SELECT data, ate FROM cliente_eventos WHERE cliente_id=? AND tipo='pausa'", (g,)).fetchone()
    assert tuple(ev) == ("2026-10-06", "2026-11-01")                                # guarda a renovação pulada e a volta
    assert con_temp.execute("SELECT data_renovacao FROM clientes WHERE id=?", (g,)).fetchone()[0] == "2026-11-01"
    assert {i["nome"]: i for i in financeiro.mensalidades(con_temp, "2026-10")}["Elisa"]["situacao"] == "pulou o mês"
    h = cliente(con_temp, "Sem volta", "2026-10-06")
    http.post(f"/clientes/{h}/evento", data={"tipo": "pausa", "data": "2026-10-31"}, follow_redirects=False)
    assert financeiro.renovacoes(con_temp, h)[h]["efetiva"] == "2026-11-06"          # vazio: um mês depois
    r = http.post(f"/clientes/{h}/evento", data={"tipo": "pausa", "data": "2026-10-31", "nova_renovacao": "2026-10-01"},
                  follow_redirects=False)
    assert "erro" in r.headers["location"]                                            # volta antes do mês pulado

    pagina = http.get(f"/clientes/{g}").text
    assert 'value="2026-11-01"' in pagina and "pulou o mês" in pagina


def test_ficha_mostra_data_que_andou_e_salvar_nao_mexe(con_temp):
    http = TestClient(main.app, base_url="http://localhost")
    a = cliente(con_temp, "Bruno", "2026-10-05")
    with con_temp:
        con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id)"
                         " VALUES ('PJ','entrada','2026-10-28','2026-10-28',200,'Pacotes de Aulas',?)", (a,))
    pagina = http.get(f"/clientes/{a}").text
    assert 'value="2026-11-05"' in pagina and "Andou com o pagamento de 28/10/2026" in pagina and "falta R$ 200,00" in pagina
    form = {"nome": "Bruno", "telefone": "11988887777", "status": "ativo", "data_renovacao": "2026-11-05", "valor": "400"}
    http.post(f"/clientes/{a}", data=form, follow_redirects=False)
    gravada = con_temp.execute("SELECT data_renovacao, renovacao_em FROM clientes WHERE id=?", (a,)).fetchone()
    assert tuple(gravada) == ("2026-10-05", None)   # salvou o telefone: a data que andou não vira troca à mão
    http.post(f"/clientes/{a}", data={**form, "data_renovacao": "2026-10-20"}, follow_redirects=False)
    gravada = con_temp.execute("SELECT data_renovacao, renovacao_em FROM clientes WHERE id=?", (a,)).fetchone()
    assert gravada[0] == "2026-10-20" and gravada[1]                                   # trocou à mão: vale a data dele
    assert financeiro.renovacoes(con_temp, a)[a]["efetiva"] == "2026-10-20"


def test_lista_de_clientes_usa_a_renovacao_que_andou(con_temp):
    http = TestClient(main.app, base_url="http://localhost")
    a = cliente(con_temp, "Bruno", dia(-26))
    with con_temp:
        con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id)"
                         " VALUES ('PJ','entrada',?,?,400,'Pacotes de Aulas',?)", (dia(-3), dia(-3), a))
    proxima = financeiro.proxima_renovacao(dia(-26))
    pagina = http.get("/clientes").text
    assert f"Renova em {main.data_br(proxima)}" in pagina and "borda-vermelho" not in pagina


def test_sem_aula_desconta_bloqueio_e_mes_pulado(con_temp):
    with con_temp:
        con_temp.execute("DELETE FROM campanha_fases WHERE tipo='bloqueio'")
    th = cliente(con_temp, "Fabio", dia(30))
    with con_temp:
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', ?)", (th, dia(-16)))
    assert [a["texto"] for a in do_aluno(con_temp, "Fabio")] == [f"Fabio — sem aula desde {main.data_br(dia(-16))}"]
    with con_temp:   # viagem de 7 dias até hoje (e mais 2): 16 - 7 = 9 dias sem aula, abaixo de 14
        con_temp.execute("INSERT INTO campanha_fases (nome, inicio, fim, tipo, ordem) VALUES ('Viagem', ?, ?, 'bloqueio', 9)", (dia(-6), dia(2)))
    assert not do_aluno(con_temp, "Fabio")
    gi = cliente(con_temp, "Elisa", dia(10))
    with con_temp:
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', ?)", (gi, dia(-40)))
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, ate) VALUES (?, 'pausa', ?, ?)", (gi, dia(-35), dia(-10)))
    # 40 dias sem aula - 25 de mês pulado - 7 de viagem = 8: sem alerta
    assert not [a for a in do_aluno(con_temp, "Elisa") if "sem aula" in a["texto"]]
    assert main.dias_parados(dt.date(2026, 10, 15), dt.date(2026, 10, 31), [("2026-10-25", "2026-11-02"), ("2026-10-20", "2026-10-26")]) == 12
    assert main.dias_parados(dt.date(2026, 10, 15), dt.date(2026, 10, 31), [("2026-09-01", "2026-10-10")]) == 0


def test_alunos_sem_nenhuma_aula_mostram_nomes(con_temp):
    for nome in ("Bruno", "Ana", "Carla", "Duda"):
        cliente(con_temp, nome, dia(30), inicio=dia(-60))
    cliente(con_temp, "Novato", dia(30), inicio=dia(-3))        # começou há 3 dias: ainda não é alerta
    cliente(con_temp, "Futuro", dia(30), inicio=dia(5))
    cliente(con_temp, "Online", dia(30), tipo="Consultoria Online")
    [a] = [x for x in main.alertas(con_temp) if "sem nenhuma aula" in x["texto"]]
    assert a["texto"] == "4 alunos sem nenhuma aula registrada: Ana, Bruno, Carla e mais 1"


def test_alerta_de_propostas_abre_o_simulador(con_temp):
    """Proposta enviada gera alerta que abre /simulador (o antigo /propostas não tem tela GET, dava 405)."""
    with con_temp:
        con_temp.execute("INSERT INTO propostas (tipo_servico, preco_total, status) VALUES ('Pacote de Aulas', 500, 'enviada')")
    [a] = [x for x in main.alertas(con_temp) if "esperando resposta" in x["texto"]]
    assert a["url"] == "/simulador" and a["texto"] == "1 proposta enviada esperando resposta"
