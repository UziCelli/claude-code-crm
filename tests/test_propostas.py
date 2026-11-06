"""Aba Propostas: vários horários (dias/horas/locais) na mesma proposta, ajuste de preço e o PDF com desconto."""
import pytest
from fastapi.testclient import TestClient

from app import db, locais, main, precos


@pytest.fixture
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    con = db.conectar()
    with con:
        con.execute("UPDATE parametros SET valor=0 WHERE grupo='mao_obra' AND chave='valor_hora_auto'")
        con.execute("UPDATE parametros SET valor=53 WHERE grupo='mao_obra' AND chave='valor_hora'")
    locais.criar_local(con, "SmartFit", taxa_aula=20, tempo_deslocamento=30)
    with con:
        con.execute("""INSERT OR REPLACE INTO grade_slots (tipo_calculo, dia, local, hora, status)
                       VALUES ('Pacotes', 1, 'SmartFit', 7, 'livre'), ('Pacotes', 3, 'SmartFit', 19, 'ocupado')""")
        con.execute("UPDATE parametros SET valor=0.86 WHERE grupo='mult_horario' AND chave='07'")   # 7h é vale em todos os locais
        cid = con.execute("INSERT INTO clientes (nome) VALUES ('Ana')").lastrowid
    con.close()
    return TestClient(main.app, base_url="http://localhost"), cid


PLANO = "Pacote de Aulas|8|0"


def _cheio(horarios, qtd=8, tipo="Pacote de Aulas", forma="PIX", pessoas=1):
    """Preço de tabela pelo motor: [(local, multiplicador), ...]."""
    con = db.conectar()
    try:
        p = precos.carregar_parametros(con)
        itens = [(precos.base_motor(tipo, qtd, local=loc), m, loc) for loc, m in horarios]
        return precos.calcular_misto(itens, p, pessoas, forma_pagamento=forma)["preco_cheio"]
    finally:
        con.close()


def test_simulador_antigo_vai_para_propostas(http):
    c, _ = http
    r = c.get("/simulador?plano=x&local=CIA", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/propostas?plano=x&local=CIA"


def test_adiciona_varios_dias_de_uma_vez_e_tira_a_media(http):
    c, _ = http
    r = c.get("/propostas", params={"plano": PLANO, "nd": [1, 3], "nh": 7, "nl": "SmartFit"})
    assert r.status_code == 200
    assert r.text.count('name="h" value="1-7-SmartFit"') == 2 and 'value="3-7-SmartFit"' in r.text   # GET + salvar
    # o multiplicador é da hora: Seg e Qua 7h são vale (x0,86), mesmo a Qua sem célula na grade
    assert main.moeda(_cheio([("SmartFit", 0.86), ("SmartFit", 0.86)])) in r.text
    # horas diferentes: Seg 7h (x0,86) e Qua 8h (x1) tiram a média
    r = c.get("/propostas", params={"plano": PLANO, "h": ["1-7-SmartFit", "3-8-SmartFit"]})
    assert main.moeda(_cheio([("SmartFit", 0.86), ("SmartFit", 1.0)])) in r.text and "média" in r.text


def test_pacote_misto_de_locais_avisa_ocupado_e_frequencia(http):
    c, _ = http
    r = c.get("/propostas", params={"plano": PLANO, "h": ["1-7-SmartFit", "3-19-SmartFit", "5-7-CIA"]})
    assert "ocupado na grade" in r.text
    assert "O plano é 2x por semana e a proposta tem 3 horários" in r.text


def test_tirar_um_horario(http):
    c, _ = http
    r = c.get("/propostas", params={"plano": PLANO, "h": ["1-7-SmartFit", "5-7-CIA"], "tira": 0})
    assert 'value="1-7-SmartFit"' not in r.text and 'value="5-7-CIA"' in r.text


def test_link_antigo_com_dia_e_hora_vira_um_horario(http):
    c, _ = http
    r = c.get("/propostas", params={"plano": PLANO, "local": "SmartFit", "dia": 1, "hora": 7})
    assert 'value="1-7-SmartFit"' in r.text and main.moeda(_cheio([("SmartFit", 0.86)])) in r.text


def test_ajuste_sobe_ate_a_margem_minima(http):
    c, _ = http
    r = c.get("/propostas", params={"plano": PLANO, "h": ["1-7-SmartFit"]})
    assert "Subir para" in r.text          # vale x0,86 fica abaixo da margem
    sug = main.simular(db.conectar(), PLANO, [{"dia": 1, "hora": 7, "local": "SmartFit"}], "PIX", 1)["preco_sugerido"]
    r2 = c.get("/propostas", params={"plano": PLANO, "h": ["1-7-SmartFit"], "ajuste": int(sug)})
    assert "dentro da margem" in r2.text and f'name="preco_final" value="{int(sug)}"' in r2.text


def test_salva_com_desconto_e_pdf_mostra_de_por(http):
    c, cid = http
    r = c.post("/propostas", data={"plano": PLANO, "forma": "PIX", "pessoas": 1, "desconto": "2", "cliente_id": cid, "confirmar": 1,
                                   "h": ["2-7-CIA", "4-7-SmartFit"]}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/propostas/")
    con = db.conectar()
    p = con.execute("SELECT * FROM propostas").fetchone()
    hs = con.execute("SELECT dia, hora, local FROM proposta_horarios WHERE proposta_id=? ORDER BY id", (p["id"],)).fetchall()
    con.close()
    assert [tuple(h) for h in hs] == [(2, 7, "CIA"), (4, 7, "SmartFit")]
    cheio = _cheio([("CIA", 0.86), ("SmartFit", 0.86)])   # 7h é vale em todos os locais (fixture)
    assert p["local"] == "CIA + SmartFit" and p["preco_cheio"] == pytest.approx(cheio) and p["desconto"] == pytest.approx(0.02)
    pdf = c.get(f"/propostas/{p['id']}").text
    assert f"<s>{main.moeda(cheio)}</s>" in pdf and main.moeda(cheio * 0.98) in pdf and "−2,0% de desconto" in pdf
    assert "CIA: Ter 07h · SmartFit: Qui 07h" in pdf
    lista = c.get("/propostas").text
    assert "CIA: Ter 07h · SmartFit: Qui 07h" in lista


def test_pdf_sem_desconto_nao_mostra_de_por(http):
    c, cid = http
    c.post("/propostas", data={"plano": PLANO, "forma": "PIX", "preco_final": "2000", "cliente_id": cid, "h": ["2-7-CIA"]})
    con = db.conectar()
    pid = con.execute("SELECT id FROM propostas").fetchone()[0]
    con.close()
    pdf = c.get(f"/propostas/{pid}").text
    assert "<s>" not in pdf and "R$ 2.000,00" in pdf


def _pdf_dupla(c, cid, valor_hoje, tipo="Pacote de Aulas", preco_final="1700"):
    con = db.conectar()
    with con:
        con.execute("UPDATE clientes SET valor=?, pessoas=1, tipo_servico=? WHERE id=?", (valor_hoje, tipo, cid))
    con.close()
    c.post("/propostas", data={"plano": PLANO, "forma": "PIX", "pessoas": 2, "preco_final": preco_final, "cliente_id": cid,
                               "confirmar": 1, "h": ["2-7-CIA"]})
    con = db.conectar()
    pid = con.execute("SELECT id FROM propostas ORDER BY id DESC").fetchone()[0]
    con.close()
    return c.get(f"/propostas/{pid}").text


def test_aluno_que_vira_dupla_ve_a_economia_sobre_o_que_ja_paga(http):
    """Aluno sozinho paga R$ 1.000; a dupla sai R$ 1.700 (R$ 850 cada): economiza R$ 150 (15%), não o desconto de tabela."""
    c, cid = http
    pdf = _pdf_dupla(c, cid, 1000)
    assert "Hoje você paga <b>R$ 1.000,00</b>" in pdf and "<b>R$ 850,00</b> por pessoa" in pdf
    assert "você economiza R$ 150,00" in pdf and "−15,0%" in pdf
    assert "Você economiza" not in pdf          # a economia de tabela (preço cheio da dupla) sumiu


def test_aluno_sem_economia_ou_de_outro_servico_nao_ve_conta_falsa(http):
    c, cid = http
    assert "economiza" not in _pdf_dupla(c, cid, 800)                    # dupla sai mais cara que o que paga hoje
    pdf = _pdf_dupla(c, cid, 1000, tipo="Mensalidade")                   # outro período: não compara
    assert "Hoje você paga" not in pdf


@pytest.mark.parametrize("campo,valor", [("desconto", "10%"), ("preco_final", "1000 reais"), ("ajuste", "abc")])
def test_numero_invalido_mostra_frase_sem_quebrar(http, campo, valor):
    c, _ = http
    r = c.get("/propostas", params={"plano": PLANO, "h": ["1-7-CIA"], campo: valor})
    assert r.status_code == 200
    assert "não é um número" in r.text and "could not convert" not in r.text


def test_salvar_com_numero_invalido_volta_com_a_frase(http):
    c, cid = http
    r = c.post("/propostas", data={"plano": PLANO, "forma": "PIX", "h": ["1-7-CIA"], "desconto": "10%",
                                   "cliente_id": str(cid)})
    assert r.status_code == 200 and "não é um número" in r.text and "Proposta #" not in r.text


# ---- Pacote personalizado (1 a 20 aulas), com ou sem consultoria ----
def _com_consultoria():
    return db.conectar()


def test_pacote_personalizado_de_7_aulas(http):
    c, _ = http
    r = main.simular(db.conectar(), main._plano_efetivo("personalizado", "7", ""), [{"dia": 1, "hora": 10, "local": "CIA"}], "PIX", 1)
    # o motor monta qualquer nº de aulas: 7 aulas + 1 h de planejamento = 8 h
    assert r["qtd"] == 7 and r["horas"] == 8 and r["preco_cheio"] == pytest.approx(_cheio([("CIA", 1.0)], qtd=7), abs=0.01)
    assert r["preco_cheio"] < _cheio([("CIA", 1.0)], qtd=8)
    tela = c.get("/propostas", params={"plano": "personalizado", "aulas": 7, "h": ["1-10-CIA"]})
    assert tela.status_code == 200 and main.moeda(r["preco_cheio"]) in tela.text


def test_personalizado_com_consultoria_soma_os_meses(http):
    c, _ = http
    con = _com_consultoria()
    h = [{"dia": 1, "hora": 10, "local": "CIA"}]
    sem = main.simular(con, "Pacote de Aulas|8|2", h, "PIX", 1)
    com = main.simular(con, "Pacote de Aulas|8|2", h, "PIX", 1, consultoria="Consultoria Online")
    # 8 aulas 2x/semana = 4 semanas = 1 mês; consultoria no preço de tabela do motor com 15% de desconto no combo
    assert com["meses_consultoria"] == 1
    p = precos.carregar_parametros(con)
    cons = precos.calcular(precos.base_motor("Consultoria Online"), p)["preco_cheio"]
    assert com["preco_cheio"] == pytest.approx(sem["preco_cheio"] + cons * 0.85, abs=0.01)
    # 150 min de consultoria no mês: pró-labore + a parte dos custos fixos dessas horas
    mo = 2.5 * p["mo"]["valor_hora"]
    assert com["custo_total"] == pytest.approx(sem["custo_total"] + mo + 2.5 * p["rateio_hora"], abs=0.01)
    assert com["mao_obra"] == pytest.approx(sem["mao_obra"] + mo, abs=0.01)
    assert com["horas"] == pytest.approx(sem["horas"] + 2.5)   # o tempo da consultoria entra no lucro/hora
    longo = main.simular(con, main._plano_efetivo("personalizado", "20", "1"), h, "PIX", 1, consultoria="Consultoria Online")
    assert longo["meses_consultoria"] == 5   # 20 semanas ≈ 4,6 meses -> 5
    tela = c.get("/propostas", params={"plano": "personalizado", "aulas": 7, "consultoria": "Consultoria Online", "h": ["1-10-CIA"]})
    assert "+ Consultoria Online" in tela.text and "acompanhamento" in tela.text


def test_salvar_personalizado_guarda_a_consultoria(http):
    c, cid = http
    _com_consultoria()
    r = c.post("/propostas", data={"plano": "personalizado", "aulas": "7", "consultoria": "Consultoria Online", "forma": "PIX",
                                   "h": "1-10-CIA", "cliente_id": str(cid), "confirmar": 1}, follow_redirects=False)
    assert r.headers["location"].startswith("/propostas/")
    p = db.conectar().execute("SELECT * FROM propostas ORDER BY id DESC LIMIT 1").fetchone()
    assert (p["tipo_servico"], p["qtd_aulas"], p["consultoria"]) == ("Pacote de Aulas", 7, "Consultoria Online")
    assert "Consultoria Online (acompanhamento completo)" in c.get(r.headers["location"].split("?")[0]).text


@pytest.mark.parametrize("aulas", ["0", "21", "abc"])
def test_personalizado_fora_de_1_a_20_avisa(http, aulas):
    c, _ = http
    tela = c.get("/propostas", params={"plano": "personalizado", "aulas": aulas, "h": ["1-10-CIA"]})
    assert tela.status_code == 200 and "1 a 20" in tela.text


def test_consultoria_sem_planilha_tem_preco(http):
    c, _ = http
    tela = c.get("/propostas", params={"plano": PLANO, "consultoria": "Consultoria Online", "h": ["1-10-CIA"]})
    assert tela.status_code == 200 and "+ Consultoria Online" in tela.text and "Não há preço" not in tela.text


def test_vale_a_pena_mostra_os_3_pisos_e_o_que_oferecer(http):
    """R$ 800 no pacote de 8 da CIA: paga as contas, não o salário inteiro. Pisos em ordem e contrapropostas que fecham."""
    c, _ = http
    con = db.conectar()
    try:
        r = main.simular(con, PLANO, [], "PIX", 1, preco_final=800, local="CIA")
        assert r["piso_negocio"] < r["piso_salario"] < r["preco_minimo"]
        assert r["piso_negocio"] <= 800 < r["piso_salario"] and r["veredito"] == "parcial"
        assert 0 < r["ganho_hora"] < r["valor_hora"]
        aulas = r["contra"]["aulas"]
        assert 1 <= aulas["qtd"] < 8
        menor = main.simular(con, f"Pacote de Aulas|{aulas['qtd']}|0", [], "PIX", 1, preco_final=800, local="CIA")
        assert menor["veredito"] == "fechar"
        assert r["contra"]["dupla"]["total"] == main.simular(con, PLANO, [], "PIX", 2, local="CIA")["preco_sugerido"]
        assert main.simular(con, PLANO, [], "PIX", 1, local="CIA", preco_final=2000)["contra"] == {}
    finally:
        con.close()
    t = c.get("/propostas", params={"plano": PLANO, "local": "CIA", "preco_final": "800"}).text
    assert "Esse preço vale a pena?" in t and "Só em horário vago" in t and "Piso do negócio" in t
    assert "depois do seu salário" in t


def test_cartao_mostra_o_veredito_no_pix(http):
    c, _ = http
    con = db.conectar()
    try:
        y = main.simular(con, PLANO, [], "PIX", 1, local="CIA")["preco_sugerido"]
        r = main.simular(con, PLANO, [], "Cartão 12x", 1, local="CIA", preco_final=y)
        assert r["veredito"] != "fechar" and r["contra"]["pix"] == "fechar"
    finally:
        con.close()
