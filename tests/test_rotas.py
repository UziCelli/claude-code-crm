"""Teste de fumaça: todas as telas abrem (200) num banco temporário. Rede de segurança para mudanças nos templates."""
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import db, main

TELAS = ["/", "/clientes", "/clientes/novo", "/leads", "/grade", "/agenda", "/simulador", "/explorador",
         "/campanhas", "/rotina", "/configuracoes", "/dados", "/financeiro", "/financeiro/painel", "/financeiro/mensalidades", "/financeiro/previsao", "/assistente"]


@pytest.fixture
def cliente_http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")  # nunca tocar nos backups reais
    db.iniciar_banco()
    con = db.conectar()
    with con:
        cid = con.execute("INSERT INTO clientes (nome) VALUES ('Aluno Teste')").lastrowid
    con.close()
    # sem "with": o lifespan (backup diário) não roda; localhost: no PC, outro endereço passa pela portaria
    return TestClient(main.app, base_url="http://localhost"), cid


@pytest.mark.parametrize("url", TELAS)
def test_tela_abre(cliente_http, url):
    http, _ = cliente_http
    assert http.get(url).status_code == 200


def test_proposta_abre_sem_dados_internos(cliente_http):
    http, cid = cliente_http
    con = db.conectar()
    with con:
        pid = con.execute("""INSERT INTO propostas (cliente_id, tipo_servico, qtd_aulas, local, forma_pagamento, preco_total, preco_pessoa,
                             lucro, margem) VALUES (?, 'Pacote', 10, 'CIA', 'PIX', 900, 900, 400, 0.4)""", (cid,)).lastrowid
    con.close()
    r = http.get(f"/propostas/{pid}")
    assert r.status_code == 200 and "Aluno Teste" in r.text
    assert "Lucro" not in r.text and "Margem" not in r.text
    assert http.get("/propostas/999", follow_redirects=False).status_code in (302, 303)


def test_ficha_do_cliente_abre(cliente_http):
    http, cid = cliente_http
    r = http.get(f"/clientes/{cid}")
    assert r.status_code == 200 and "Aluno Teste" in r.text


def _card_do_cliente(pagina, nome):
    """Trecho HTML do card da lista de clientes que mostra o nome dado."""
    fim = pagina.index(f"<strong>{nome}</strong>")
    ini = pagina.rindex('<div class="card cartao-aluno', 0, fim)
    return pagina[ini:pagina.index("</a>", fim)]


def test_lista_de_clientes_mostra_pacote_ou_mes(cliente_http):
    """Pacote de aulas mostra '/ pacote' no preço; mensalidade continua com '/ mês'."""
    http, cid = cliente_http
    con = db.conectar()
    with con:
        con.execute("INSERT INTO clientes (nome, status, tipo_servico, plano, valor) VALUES ('Pacotista', 'ativo', 'Pacote de Aulas', 'Pacote 8 aulas', 640)")
        con.execute("INSERT INTO clientes (nome, status, tipo_servico, plano, valor) VALUES ('Mensalista', 'ativo', 'Mensalidade', 'Mensalidade 2x/semana', 480)")
        con.execute("INSERT INTO clientes (nome, status, plano, valor) VALUES ('Antigo', 'ativo', 'Pacote 4 aulas', 320)")
    con.close()
    pagina = http.get("/clientes").text
    assert "/ pacote" in _card_do_cliente(pagina, "Pacotista") and "/ mês" not in _card_do_cliente(pagina, "Pacotista")
    assert "/ pacote" in _card_do_cliente(pagina, "Antigo")   # sem tipo de serviço: o plano já diz "Pacote"
    assert "/ mês" in _card_do_cliente(pagina, "Mensalista") and "/ pacote" not in _card_do_cliente(pagina, "Mensalista")
    assert "Valor (R$ por mês, ou do pacote)" in http.get(f"/clientes/{cid}").text


def test_financeiro_lancamento_baixa_e_recorrencia(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today()
    base = {"escopo": "PJ", "volta": f"mes={hoje:%Y-%m}&escopo=todos"}
    # lançamento pendente (ontem; no dia 1, hoje, para não cair no mês anterior) -> dar baixa -> pago
    ontem = hoje - dt.timedelta(days=1) if hoje.day > 1 else hoje
    http.post("/financeiro/lancamento", data={**base, "tipo": "saida", "data": ontem.isoformat(),
                                              "valor": "1.234,50", "categoria": "Outros", "descricao": "Conta de teste"}, follow_redirects=False)
    con = db.conectar()
    lid, valor, pago = con.execute("SELECT id, valor, pago_em FROM lancamentos").fetchone()
    assert valor == 1234.5 and pago is None
    http.post(f"/financeiro/lancamento/{lid}/baixa", data=base, follow_redirects=False)
    assert con.execute("SELECT pago_em FROM lancamentos").fetchone()[0] == hoje.isoformat()
    assert 'tag verde">pago' in http.get("/financeiro").text
    # valor zero é recusado
    r = http.post("/financeiro/lancamento", data={**base, "tipo": "saida", "data": hoje.isoformat(), "valor": "0", "categoria": "Outros"},
                  follow_redirects=False)
    assert "erro=" in r.headers["location"] and con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 1
    # recorrência: pagar duas vezes não duplica
    http.post("/financeiro/recorrencia", data={**base, "descricao": "Aluguel", "categoria": "Outros", "valor": "500", "dia_vencimento": "5",
                                               "fixo": "1", "inicio": f"{hoje:%Y-%m}"}, follow_redirects=False)
    rid = con.execute("SELECT id FROM recorrencias").fetchone()[0]
    pagar = {**base, "rid": rid, "competencia": f"{hoje:%Y-%m}", "valor": "520,00", "pago_em": hoje.isoformat()}
    http.post("/financeiro/recorrencia/baixa", data=pagar, follow_redirects=False)
    r = http.post("/financeiro/recorrencia/baixa", data=pagar, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert con.execute("SELECT COUNT(*) FROM lancamentos WHERE recorrencia_id=?", (rid,)).fetchone()[0] == 1
    con.close()


def test_registrar_pagamento_mensalidade(cliente_http):
    import datetime as dt
    http, cid = cliente_http
    hoje = dt.date.today()
    mes = f"{hoje:%Y-%m}"
    con = db.conectar()
    with con:
        con.execute("UPDATE clientes SET valor=500, status='ativo' WHERE id=?", (cid,))
    r = http.post("/financeiro/lancamento", data={"escopo": "PJ", "tipo": "entrada", "data": hoje.isoformat(), "pago_em": hoje.isoformat(),
                  "valor": "500,00", "categoria": "Outros", "descricao": "Mensalidade", "cliente_id": cid,
                  "volta": f"/financeiro/mensalidades?mes={mes}"}, follow_redirects=False)
    assert r.headers["location"].startswith(f"/financeiro/mensalidades?mes={mes}")
    assert 'tag verde">recebido' in http.get(f"/financeiro/mensalidades?mes={mes}").text
    assert "Mensalidade" in http.get(f"/clientes/{cid}").text
    con.close()


def test_registrar_pagamento_da_baixa_na_entrada_ja_lancada(cliente_http):
    """Aluno com a entrada já lançada em aberto: registrar o pagamento dá baixa nela em vez de criar uma 2ª (contaria duas vezes)."""
    import datetime as dt
    http, cid = cliente_http
    hoje = dt.date.today().isoformat()
    volta = f"/financeiro/mensalidades?mes={hoje[:7]}"
    con = db.conectar()
    with con:
        con.execute("UPDATE clientes SET valor=500, status='ativo' WHERE id=?", (cid,))
    base = {"escopo": "PJ", "tipo": "entrada", "data": hoje, "valor": "500,00", "categoria": "Outros", "cliente_id": cid, "volta": volta}
    http.post("/financeiro/lancamento", data=base, follow_redirects=False)                  # lançada, ainda não caiu
    tela = http.get(volta).text
    assert "Dar baixa R$ 500,00" in tela and "Registrar pagamento</button>" not in tela     # nada falta lançar: só a baixa
    r = http.post("/financeiro/lancamento", data={**base, "pago_em": hoje, "conta": "Inter"}, follow_redirects=False)
    assert "dei baixa" in unquote(r.headers["location"])
    linhas = con.execute("SELECT pago_em, conta FROM lancamentos WHERE cliente_id=? AND excluido_em IS NULL", (cid,)).fetchall()
    assert [tuple(x) for x in linhas] == [(hoje, "Inter")]
    # valor diferente é outro pagamento: grava normal
    http.post("/financeiro/lancamento", data={**base, "valor": "80", "pago_em": hoje}, follow_redirects=False)
    assert con.execute("SELECT COUNT(*) FROM lancamentos WHERE cliente_id=? AND excluido_em IS NULL", (cid,)).fetchone()[0] == 2
    con.close()


def test_ligar_entrada_sem_aluno_e_falta_por_aluno(cliente_http):
    import datetime as dt
    import re
    http, cid = cliente_http
    hoje = dt.date.today().isoformat()
    volta = f"/financeiro/mensalidades?mes={hoje[:7]}"
    con = db.conectar()
    with con:
        con.execute("UPDATE clientes SET valor=500, status='ativo' WHERE id=?", (cid,))
        outro = con.execute("INSERT INTO clientes (nome, valor, status) VALUES ('Pagou Adiantado', 500, 'ativo')").lastrowid
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id) VALUES ('PJ','entrada',?,?,800,'Outros',?)",
                    (hoje, hoje, outro))
        lid = con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao) VALUES ('PJ','entrada',?,?,500,'Outros',?)",
                          (hoje, hoje, "PIX Aluno Teste")).lastrowid
    tela = http.get(volta).text
    assert "1 entrada sem aluno" in tela and f'<option value="{cid}" selected>' in tela   # sugere o aluno citado
    # quem pagou a mais não cobre quem não pagou: falta 500, não 200
    assert re.search(r'Falta receber</div><div class="valor">([^<]+)<', tela).group(1) == "R$ 500,00"
    r = http.post(f"/financeiro/lancamento/{lid}/aluno", data={"cliente_id": cid, "volta": volta}, follow_redirects=False)
    assert "ligada a Aluno Teste" in unquote(r.headers["location"])
    tela = http.get(volta).text
    assert "sem aluno" not in tela
    assert re.search(r'Falta receber</div><div class="valor">([^<]+)<', tela).group(1) == "R$ 0,00"
    assert http.post(f"/financeiro/lancamento/{lid}/aluno", data={"cliente_id": 0, "volta": volta}, follow_redirects=False).status_code == 303
    con.close()


def test_marcar_entrada_como_emprestimo_tira_da_receita_e_da_lista_de_sem_aluno(cliente_http):
    import datetime as dt
    http, cid = cliente_http
    hoje = dt.date.today().isoformat()
    volta = f"/financeiro/mensalidades?mes={hoje[:7]}"
    con = db.conectar()
    with con:
        lid = con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao) VALUES ('PJ','entrada',?,?,4000,'Outros',?)",
                          (hoje, hoje, "Empréstimo Dock")).lastrowid
        pf = con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria) VALUES ('PF','entrada',?,?,10,'Outros')",
                         (hoje, hoje)).lastrowid
    tela = http.get(volta).text
    assert "1 entrada sem aluno" in tela and "parece empréstimo" in tela and "É empréstimo" in tela
    r = http.post(f"/financeiro/lancamento/{lid}/emprestimo", data={"volta": volta}, follow_redirects=False)
    assert "Marcado como empréstimo" in unquote(r.headers["location"])
    assert con.execute("SELECT categoria FROM lancamentos WHERE id=?", (lid,)).fetchone()[0] == "Empréstimo"
    assert "sem aluno" not in http.get(volta).text
    livro = http.get(f"/financeiro?mes={hoje[:7]}").text
    assert "Sem empréstimo (R$ 4.000,00)" in livro and ">empréstimo</span>" in livro
    # PF não pode ser empréstimo da PJ: nada muda e volta com erro
    r = http.post(f"/financeiro/lancamento/{pf}/emprestimo", data={"volta": volta}, follow_redirects=False)
    assert "Só uma entrada da PJ" in unquote(r.headers["location"])
    assert con.execute("SELECT categoria FROM lancamentos WHERE id=?", (pf,)).fetchone()[0] == "Outros"
    con.close()


@pytest.mark.parametrize("valor,esperado", [("1.500", 1500), ("1.500,50", 1500.5), ("10.5", 10.5), ("1.234.567", 1234567)])
def test_num_br_milhar_sem_centavos(valor, esperado):
    assert main._num_br(valor) == esperado


def test_financeiro_entradas_invalidas_nao_gravam_nem_quebram(cliente_http):
    http, _ = cliente_http
    assert http.get("/financeiro?mes=2026-13").status_code == 200
    base = {"escopo": "PJ", "tipo": "saida", "data": "2026-09-01", "categoria": "Outros", "volta": "mes=2026-09"}
    for ruim in ({"valor": "nan"}, {"valor": "inf"}, {"valor": "1e400"}, {"valor": "10", "cliente_id": "999"}, {"valor": "10", "id": "abc"}):
        r = http.post("/financeiro/lancamento", data={**base, **ruim}, follow_redirects=False)
        assert r.status_code == 303 and "erro=" in r.headers["location"], ruim
    r = http.post("/financeiro/recorrencia", data={"escopo": "PJ", "descricao": "X", "categoria": "Outros", "valor": "5",
                                                   "dia_vencimento": "5", "inicio": "2026-13", "volta": "mes=2026-09"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    con = db.conectar()
    assert con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM recorrencias").fetchone()[0] == 0
    con.close()


def test_restaurar_backup_antigo_recria_tabelas_novas(cliente_http):
    import sqlite3
    http, _ = cliente_http
    antigo = db.pasta_backup() / "crm-antigo.db"
    con = sqlite3.connect(antigo)   # banco anterior à Rodada 2: sem lancamentos/recorrencias
    sqlite3.connect(db.DB_PATH).backup(con)   # API do sqlite3: vale também com o banco do Turso
    con.execute("DROP TABLE lancamentos")
    con.execute("DROP TABLE recorrencias")
    con.commit()
    con.close()
    db.restaurar_backup("crm-antigo.db")
    assert http.get("/dados").status_code == 200


def test_atualizar_saldos_e_ver_quanto_tem_nas_contas(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today()
    r = http.post("/financeiro/saldos", data={"data": hoje.isoformat(), "volta": "mes=&escopo=todos",
                                               "conta_1": "Inter", "frente_1": "PF", "saldo_1": "-50,00",
                                               "conta_2": "Contabilizei Bank", "frente_2": "PJ", "saldo_2": "1.200,00",
                                               "conta_3": "Caixa", "frente_3": "Reserva", "saldo_3": ""}, follow_redirects=False)
    assert "msg=" in r.headers["location"]
    con = db.conectar()
    assert con.execute("SELECT COUNT(*) FROM saldos").fetchone()[0] == 2
    assert db.parametros(con, "conta_escopo")["Caixa"] == "Reserva"
    con.close()
    pagina = http.get("/financeiro").text
    assert f"Nas contas: R$ 1.150,00 (atualizado em {hoje:%d/%m})" in pagina      # −50 (PF) + 1.200 (PJ)
    assert "Quanto dá para gastar" not in pagina and "Saldo livre" not in http.get("/").text
    r = http.post("/financeiro/saldos", data={"data": "ontem", "conta_1": "Inter", "saldo_1": "10"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]


def test_pagar_salario_pela_tela(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today()
    con = db.conectar()
    with con:
        con.execute("UPDATE parametros SET valor=1500 WHERE grupo='salario' AND chave='valor'")
        con.execute("UPDATE parametros SET valor=1 WHERE grupo='salario' AND chave='dia'")
    assert "Pagar salário de" in http.get("/financeiro").text
    dados = {"mes": f"{hoje:%Y-%m}", "pago_em": hoje.isoformat(), "volta": "mes=&escopo=todos"}
    assert "msg=" in http.post("/financeiro/salario", data=dados, follow_redirects=False).headers["location"]
    assert "erro=" in http.post("/financeiro/salario", data=dados, follow_redirects=False).headers["location"]
    assert con.execute("SELECT COUNT(*) FROM lancamentos WHERE origem LIKE 'SAL:%'").fetchone()[0] == 2
    con.close()
    assert "Salário pago à PF" in http.get("/financeiro/painel").text


def test_saldo_e_pagamento_no_futuro_sao_recusados(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    amanha = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    base = {"volta": "mes=&escopo=todos"}
    con = db.conectar()
    with con:
        con.execute("UPDATE parametros SET valor=1500 WHERE grupo='salario' AND chave='valor'")
        rid = con.execute("INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio) VALUES ('PJ','Aluguel','Outros',500,1,'2026-01')").lastrowid
    pedidos = [("/financeiro/saldos", {"data": amanha, "conta_1": "Inter", "saldo_1": "10"}),
               ("/financeiro/lancamento", {"escopo": "PF", "tipo": "saida", "data": "2026-10-01", "pago_em": amanha, "valor": "10", "categoria": "Outros"}),
               ("/financeiro/salario", {"mes": amanha[:7], "pago_em": amanha}),
               ("/financeiro/recorrencia/baixa", {"rid": rid, "competencia": amanha[:7], "valor": "500", "pago_em": amanha})]
    for url, dados in pedidos:
        r = http.post(url, data={**base, **dados}, follow_redirects=False)
        assert "futuro" in unquote(r.headers["location"]), url
    assert con.execute("SELECT COUNT(*) FROM saldos").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 0
    con.close()


def test_previsao_avisa_saldo_velho_e_conta_sem_frente(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    velho = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    http.post("/financeiro/saldos", data={"data": velho, "conta_1": "Inter", "frente_1": "PF", "saldo_1": "100"}, follow_redirects=False)
    con = db.conectar()
    with con:
        con.execute("INSERT INTO parametros (grupo, chave, valor_texto) VALUES ('lista_contas','Nubank','Nubank')")
    con.close()
    tela = http.get("/financeiro/previsao").text
    assert "Saldo PF de 10 dias atrás" in tela and "Conta sem frente: Nubank" in tela


def test_entrada_pj_diz_como_separar(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today().isoformat()
    r = http.post("/financeiro/lancamento", data={"escopo": "PJ", "tipo": "entrada", "data": hoje, "pago_em": hoje, "valor": "1000",
                                                  "categoria": "Outros", "volta": "mes=&escopo=todos"}, follow_redirects=False)
    assert "Separe R$ 60,00 para o imposto (DAS 6%)." in unquote(r.headers["location"])
    pagina = http.get("/financeiro").text
    assert "Imposto a separar este mês: R$ 60,00" in pagina and "(DAS 6%)" in pagina
    assert "Potes do mês" not in pagina and "Divisão de cada entrada" not in pagina and "olchão" not in pagina
    painel = http.get("/financeiro/painel").text
    assert "Reserva para meses fracos" in painel and "olchão" not in painel and "Gasto pessoal × salário" not in painel


def test_financeiro_ligar_saida_a_recorrencia(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today()
    mes = f"{hoje:%Y-%m}"
    base = {"escopo": "PJ", "volta": f"mes={mes}&escopo=todos"}
    http.post("/financeiro/recorrencia", data={**base, "descricao": "Aluguel", "categoria": "Aluguel", "valor": "1000", "dia_vencimento": "5",
                                               "fixo": "1", "inicio": mes}, follow_redirects=False)
    con = db.conectar()
    rid = con.execute("SELECT id FROM recorrencias").fetchone()[0]
    # lançado à mão pelo formulário, já ligado à conta recorrente: competência = mês da data
    saida = {**base, "tipo": "saida", "data": hoje.isoformat(), "valor": "1000", "categoria": "Aluguel", "descricao": "Aluguel",
             "pago_em": hoje.isoformat(), "recorrencia_id": str(rid)}
    r = http.post("/financeiro/lancamento", data=saida, follow_redirects=False)
    assert "erro=" not in r.headers["location"]
    lid, comp = con.execute("SELECT id, competencia FROM lancamentos").fetchone()
    assert comp == mes and "talvez" not in http.get("/financeiro").text
    # o mesmo mês de novo: erro amigável, nada gravado
    r = http.post("/financeiro/lancamento", data=saida, follow_redirects=False)
    assert "erro=" in r.headers["location"] and "j%C3%A1+tem+um+lan%C3%A7amento" in r.headers["location"].replace("%20", "+")
    assert con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 1
    # editar a data para outro mês mantém a competência da baixa; esvaziar o campo desliga
    outro = (hoje.replace(day=1) - dt.timedelta(days=1)).isoformat()
    http.post("/financeiro/lancamento", data={**saida, "id": str(lid), "data": outro, "pago_em": outro}, follow_redirects=False)
    assert tuple(con.execute("SELECT recorrencia_id, competencia FROM lancamentos").fetchone()) == (rid, mes)
    http.post("/financeiro/lancamento", data={**saida, "id": str(lid), "recorrencia_id": ""}, follow_redirects=False)
    assert tuple(con.execute("SELECT recorrencia_id, competencia FROM lancamentos").fetchone()) == (None, None)
    # entrada não pode ser conta recorrente
    r = http.post("/financeiro/lancamento", data={**saida, "tipo": "entrada", "data": hoje.isoformat()}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    con.close()


def test_financeiro_card_de_contas_parecidas_ligar_e_descartar(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today()
    mes = f"{hoje:%Y-%m}"
    base = {"escopo": "PJ", "volta": f"mes={mes}&escopo=todos"}
    http.post("/financeiro/recorrencia", data={**base, "descricao": "Aluguel", "categoria": "Aluguel", "valor": "1000", "dia_vencimento": "5",
                                               "fixo": "1", "inicio": mes}, follow_redirects=False)
    con = db.conectar()
    rid = con.execute("SELECT id FROM recorrencias").fetchone()[0]
    for desc in ("Aluguel", "Sala"):
        http.post("/financeiro/lancamento", data={**base, "tipo": "saida", "data": hoje.isoformat(), "valor": "1000", "categoria": "Aluguel",
                                                  "descricao": desc, "pago_em": hoje.isoformat()}, follow_redirects=False)
    a, b = [r[0] for r in con.execute("SELECT id FROM lancamentos ORDER BY id")]
    tela = http.get(f"/financeiro?mes={mes}").text
    assert "Conferir (2)" in tela and "talvez já pago" in tela                  # o livro-caixa só avisa (botão com contador); o cartão fica na tela Conferir
    assert "coisas para conferir" not in tela                                    # sem o card repetido
    assert "2 contas lançadas à mão parecem recorrentes" in http.get("/financeiro/conferir").text
    http.post(f"/financeiro/lancamento/{a}/recorrencia", data={**base, "recorrencia_id": rid}, follow_redirects=False)
    assert con.execute("SELECT recorrencia_id FROM lancamentos WHERE id=?", (a,)).fetchone()[0] == rid
    # o outro agora é pagamento em dobro: sem Ligar, com Excluir; "Não é a mesma conta" tira da lista
    tela = http.get("/financeiro/conferir").text
    assert "1 conta lançada à mão parece recorrente" in tela and "já foi paga pelo botão Pagar" in tela
    r = http.post(f"/financeiro/lancamento/{b}/recorrencia", data={**base, "recorrencia_id": rid}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    http.post(f"/financeiro/lancamento/{b}/nao-recorrente", data=base, follow_redirects=False)
    assert con.execute("SELECT sem_recorrencia FROM lancamentos WHERE id=?", (b,)).fetchone()[0] == 1
    assert "lançada à mão parece" not in http.get("/financeiro/conferir").text
    assert "Conferir (" not in http.get(f"/financeiro?mes={mes}").text
    con.close()


def test_financeiro_parcela_e_retirada_recorrente_sao_recusadas(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today()
    base = {"escopo": "PF", "volta": f"mes={hoje:%Y-%m}&escopo=todos"}
    con = db.conectar()
    nota = {**base, "tipo": "saida", "data": hoje.isoformat(), "valor": "250", "categoria": "Pessoal", "descricao": "Notebook"}
    r = http.post("/financeiro/lancamento", data={**nota, "parcela_num": "15", "parcela_total": "12"}, follow_redirects=False)
    assert "erro=" in r.headers["location"] and con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 0
    r = http.post("/financeiro/lancamento", data={**nota, "parcela_num": "3"}, follow_redirects=False)       # nº sem o total
    assert "erro=" in r.headers["location"]
    http.post("/financeiro/lancamento", data={**nota, "parcela_num": "3", "parcela_total": "12"}, follow_redirects=False)
    assert tuple(con.execute("SELECT parcela_num, parcela_total FROM lancamentos").fetchone()) == (3, 12)
    r = http.post("/financeiro/recorrencia", data={"escopo": "PJ", "descricao": "Salário", "categoria": "Retirada", "valor": "3000",
                                                   "dia_vencimento": "5", "fixo": "1", "inicio": f"{hoje:%Y-%m}", "volta": base["volta"]},
                  follow_redirects=False)
    assert "erro=" in r.headers["location"] and con.execute("SELECT COUNT(*) FROM recorrencias").fetchone()[0] == 0
    con.close()


def test_financeiro_card_avisa_recorrencia_de_retirada_ja_cadastrada(cliente_http):
    http, _ = cliente_http
    con = db.conectar()
    with con:
        con.execute("INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio)"
                    " VALUES ('PJ','Salário','Retirada',3000,5,1,'2026-01')")
    con.close()
    assert "Conferir (1)" in http.get("/financeiro").text
    assert "Salário não é conta recorrente" in http.get("/financeiro/conferir").text


def test_conferir_repetidos_manter_um_e_nao_e_repetido(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today().isoformat()
    con = db.conectar()
    with con:
        ids = [con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao) VALUES ('PJ','saida',?,?,89.9,'Software/Assinaturas','Spotify')",
                           (hoje, hoje)).lastrowid for _ in range(3)]
        x, y = [con.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, descricao) VALUES ('PF','saida',?,40,'Lazer','Cinema')",
                            (hoje,)).lastrowid for _ in range(2)]
    tela = http.get("/financeiro/conferir").text
    assert "Pode estar repetido (2)" in tela and "quase certo" in tela and "(sugerido)" in tela
    assert "2 grupos de lançamentos do financeiro parecem repetido" in http.get("/financeiro").text      # alerta em toda página
    # manter só o primeiro: os outros dois vão para a lixeira
    r = http.post("/financeiro/duplicados/manter", data={"manter": ids[0], "ids": ids, "volta": "/financeiro/conferir"}, follow_redirects=False)
    assert "2 lançamentos repetidos enviados para a lixeira" in unquote(r.headers["location"])
    vivos = [r[0] for r in con.execute("SELECT id FROM lancamentos WHERE excluido_em IS NULL AND descricao='Spotify'")]
    assert vivos == [ids[0]]
    # "não é repetido" guarda o par e o grupo some
    http.post("/financeiro/duplicados/nao-repetido", data={"ids": [x, y], "volta": "/financeiro/conferir"}, follow_redirects=False)
    assert "Tudo certo" in http.get("/financeiro/conferir").text
    # pedido torto: manter fora do grupo não exclui nada
    r = http.post("/financeiro/duplicados/manter", data={"manter": 999, "ids": [x, y], "volta": "/financeiro/conferir"}, follow_redirects=False)
    assert "erro=" in r.headers["location"] and con.execute("SELECT COUNT(*) FROM lancamentos WHERE excluido_em IS NOT NULL").fetchone()[0] == 2
    con.close()


def test_financeiro_ordena_contas_a_pagar_por_impacto_e_salva_prioridade(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today()
    con = db.conectar()
    with con:
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES ('Contabilizei Bank', 1000, ?)", (hoje.isoformat(),))
        for k, (cat, valor) in enumerate([("Aluguel", 600), ("Software/Assinaturas", 200), ("Marketing/Divulgação", 300),
                                          ("Outros", 10), ("Outros", 11), ("Outros", 12), ("Outros", 13)]):
            con.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, descricao) VALUES ('PJ','saida',?,?,?,?)",
                        ((hoje + dt.timedelta(days=2 + k)).isoformat(), valor, cat, f"Conta {k}"))
    tela = http.get(f"/financeiro?mes={hoje - dt.timedelta(days=400):%Y-%m}").text   # livro-caixa de outro mês: a conta só aparece na lista
    assert tela.count("Contas a pagar</h2>") == 1 and all(tela.count(f"Conta {k}<") == 1 for k in range(7))
    assert "Pague nesta ordem" not in tela and "falta dinheiro" not in tela and "pague esta semana" not in tela
    assert tela.index("Conta 0<") < tela.index("Conta 2<")              # aluguel antes do marketing
    assert "Atrasar 1 mês custa" in tela
    # prioridade na conta recorrente: salva, aparece na lista e some do automático
    base = {"escopo": "PJ", "descricao": "Internet", "categoria": "Internet/Telefone", "valor": "120", "dia_vencimento": "10", "fixo": "1",
            "inicio": f"{hoje:%Y-%m}", "volta": f"mes={hoje:%Y-%m}&escopo=todos"}
    http.post("/financeiro/recorrencia", data={**base, "prioridade": "1"}, follow_redirects=False)
    assert con.execute("SELECT prioridade FROM recorrencias WHERE descricao='Internet'").fetchone()[0] == 1
    assert "sempre primeiro" in http.get("/financeiro").text
    r = http.post("/financeiro/recorrencia", data={**base, "descricao": "Outra", "prioridade": "5"}, follow_redirects=False)
    assert "erro=" in r.headers["location"] and con.execute("SELECT COUNT(*) FROM recorrencias").fetchone()[0] == 1
    con.close()


def test_linha_do_tempo_e_banco_x_crm_nas_telas(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today()
    d1, d2 = (hoje - dt.timedelta(days=9)).isoformat(), (hoje - dt.timedelta(days=1)).isoformat()
    con = db.conectar()
    with con:
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES ('Inter', 1000, ?)", (d1,))
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES ('Inter', 1500, ?)", (hoje.isoformat(),))
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, conta) VALUES ('PF','entrada',?,?,900,'Outros','Freela','Inter')", (d2, d2))
    tela = http.get("/financeiro/conferir").text
    assert "Banco × CRM" in tela and "Inter: você digitou R$ 1.500,00 em" in tela
    assert "Pelos lançamentos, devia ter R$ 1.900,00. Diferença: −R$ 400,00." in tela
    assert "Falta lançar uma saída de R$ 400,00, ou tem entrada a mais." in tela
    assert "Lançar a diferença" in tela and "Ver lançamentos desta conta" in tela and "Está certo" in tela
    assert "Conferir (1)" in http.get("/financeiro").text                                  # a diferença entra no contador
    t = http.get("/financeiro/linha-do-tempo").text
    assert "Linha do tempo" in t and "Hoje" in t and "Ontem" in t and "Freela" in t and "Saldo digitado: Inter" in t
    so_inter = http.get("/financeiro/linha-do-tempo?dias=7&conta=Inter").text
    assert "Freela" in so_inter and ">7 dias<" in so_inter
    # parâmetro torto cai no padrão, sem erro
    assert http.get("/financeiro/linha-do-tempo?dias=999&conta=Banco%20Fantasma").status_code == 200
    assert "Linha do tempo" in http.get("/financeiro").text
    con.close()


def test_financeiro_sem_potes_com_o_imposto_em_uma_linha(cliente_http):
    http, _ = cliente_http
    pagina = http.get("/financeiro").text
    assert "Imposto a separar este mês: R$ 0,00" in pagina and "(DAS 6%)" in pagina
    assert "Potes do mês" not in pagina and "Divisão de cada entrada" not in pagina and "olchão" not in pagina
    assert "coisas para conferir" not in pagina and "coisa para conferir" not in pagina


def test_esta_certo_esconde_a_diferenca_e_baixa_o_contador(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today()
    d1 = (hoje - dt.timedelta(days=9)).isoformat()
    con = db.conectar()
    with con:
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES ('Inter', 1000, ?)", (d1,))
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES ('Inter', 0, ?)", (hoje.isoformat(),))
    tela = http.get("/financeiro/conferir").text
    assert "Você digitou R$ 0,00 — foi isso mesmo?" in tela and "Tudo certo" not in tela
    assert "Conferir (1)" in http.get("/financeiro").text
    r = http.post("/financeiro/conferir/ok", data={"conta": "Inter", "volta": "/financeiro/conferir"}, follow_redirects=False)
    assert r.headers["location"].startswith("/financeiro/conferir") and "msg=" in r.headers["location"]
    assert "Tudo certo" in http.get("/financeiro/conferir").text and "Conferir (" not in http.get("/financeiro").text
    r = http.post("/financeiro/conferir/ok", data={"conta": "Conta Fantasma"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    con.close()


def test_lancar_a_diferenca_abre_o_novo_lancamento_e_ver_lancamentos_filtra_a_conta(cliente_http):
    import datetime as dt
    http, _ = cliente_http
    hoje = dt.date.today()
    d1, d2 = (hoje - dt.timedelta(days=9)).isoformat(), (hoje - dt.timedelta(days=1)).isoformat()
    con = db.conectar()
    with con:
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES ('Inter', 1000, ?)", (d1,))
        con.execute("INSERT INTO saldos (conta, saldo, data) VALUES ('Inter', 1500, ?)", (hoje.isoformat(),))
        for conta, desc in (("Inter", "Freela Inter"), ("Itaú", "Mercado Itaú")):
            con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, conta)
                           VALUES ('PF','entrada',?,?,100,'Outros',?,?)""", (d2, d2, desc, conta))
    con.close()
    tela = http.get("/financeiro/conferir").text
    assert 'href="/financeiro?novo=1&amp;conta=Inter&amp;tipo=entrada' in tela and "valor=400%2C00" in tela
    assert f'href="/financeiro?conta=Inter&amp;mes={hoje:%Y-%m}"' in tela
    pagina = http.get("/financeiro?novo=1&conta=Inter&tipo=entrada&escopo=PF&valor=400,00&data=" + hoje.isoformat()).text
    assert 'id="dlg-lanc"' in pagina and 'get("novo")' in pagina                     # a página tem o script que abre o diálogo
    todos = http.get(f"/financeiro?mes={d2[:7]}").text
    so_inter = http.get(f"/financeiro?mes={d2[:7]}&conta=Inter").text
    assert "Freela Inter" in todos and "Mercado Itaú" in todos
    assert "Freela Inter" in so_inter and "Mercado Itaú" not in so_inter and "Só da conta Inter" in so_inter
    assert http.get("/financeiro?conta=Banco%20Fantasma").status_code == 200


@pytest.mark.parametrize("url", ["/financeiro/mensalidades", "/financeiro/painel", "/financeiro/previsao", "/financeiro/conferir",
                                 "/financeiro/linha-do-tempo"])
def test_subtelas_do_financeiro_tem_o_mesmo_link_de_volta(cliente_http, url):
    http, _ = cliente_http
    assert '<a class="voltar" href="/financeiro">← Financeiro</a>' in http.get(url).text
