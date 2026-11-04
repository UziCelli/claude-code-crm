"""Aba Propostas: vários horários (dias/horas/locais) na mesma proposta, ajuste de preço e o PDF com desconto."""
import pytest
from fastapi.testclient import TestClient

from app import db, main


@pytest.fixture
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    con = db.conectar()
    with con:
        for local, preco, custo in (("CIA", 1100, 900), ("SmartFit", 932, 736.2353)):
            con.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, preco_base,
                           custo_operacional, mao_obra, sessoes_mes) VALUES ('Pacote de Aulas', ?, 'PIX', 8, 0, ?, ?, 415.5, 8)""",
                        (local, preco, custo))
        con.execute("""INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador)
                       VALUES ('Pacotes', 1, 'SmartFit', 7, 'livre', 0.86), ('Pacotes', 3, 'SmartFit', 19, 'ocupado', 1.0)""")
        cid = con.execute("INSERT INTO clientes (nome) VALUES ('Ana')").lastrowid
    con.close()
    return TestClient(main.app, base_url="http://localhost"), cid


PLANO = "Pacote de Aulas|8|0"


def test_simulador_antigo_vai_para_propostas(http):
    c, _ = http
    r = c.get("/simulador?plano=x&local=CIA", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/propostas?plano=x&local=CIA"


def test_adiciona_varios_dias_de_uma_vez_e_tira_a_media(http):
    c, _ = http
    r = c.get("/propostas", params={"plano": PLANO, "nd": [1, 3], "nh": 7, "nl": "SmartFit"})
    assert r.status_code == 200
    assert r.text.count('name="h" value="1-7-SmartFit"') == 2 and 'value="3-7-SmartFit"' in r.text   # GET + salvar
    # Seg 7h é vale (x0,86), Qua 7h não tem slot (x1): média 0,93
    assert "R$ 866,76" in r.text and "média" in r.text


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
    assert 'value="1-7-SmartFit"' in r.text and "R$ 801,52" in r.text


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
    assert p["local"] == "CIA + SmartFit" and p["preco_cheio"] == pytest.approx(1016) and p["desconto"] == pytest.approx(0.02)
    pdf = c.get(f"/propostas/{p['id']}").text
    assert "<s>R$ 1.016,00</s>" in pdf and "R$ 995,68" in pdf and "−2,0% de desconto" in pdf
    assert "CIA: Ter 07h · SmartFit: Qui 07h" in pdf
    lista = c.get("/propostas").text
    assert "CIA: Ter 07h · SmartFit: Qui 07h" in lista


def test_pdf_sem_desconto_nao_mostra_de_por(http):
    c, cid = http
    c.post("/propostas", data={"plano": PLANO, "forma": "PIX", "preco_final": "1200", "cliente_id": cid, "h": ["2-7-CIA"]})
    con = db.conectar()
    pid = con.execute("SELECT id FROM propostas").fetchone()[0]
    con.close()
    pdf = c.get(f"/propostas/{pid}").text
    assert "<s>" not in pdf and "R$ 1.200,00" in pdf


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
    con = db.conectar()
    with con:
        con.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, preco_base,
                       custo_operacional, mao_obra, sessoes_mes) VALUES ('Consultoria Online', 'Online', 'PIX', 1, 0, 300, 100, 60, 1)""")
    return con


def test_pacote_personalizado_de_7_aulas(http):
    c, _ = http
    r = main.simular(db.conectar(), main._plano_efetivo("personalizado", "7", ""), [{"dia": 1, "hora": 10, "local": "CIA"}], "PIX", 1)
    # só tem o pacote de 8 cadastrado: 7 aulas = 7/8 do de 8
    assert r["qtd"] == 7 and r["preco_cheio"] == pytest.approx(1100 / 8 * 7, abs=0.01)
    tela = c.get("/propostas", params={"plano": "personalizado", "aulas": 7, "h": ["1-10-CIA"]})
    assert tela.status_code == 200 and "R$ 962,50" in tela.text


def test_personalizado_com_consultoria_soma_os_meses(http):
    c, _ = http
    con = _com_consultoria()
    h = [{"dia": 1, "hora": 10, "local": "CIA"}]
    sem = main.simular(con, "Pacote de Aulas|8|2", h, "PIX", 1)
    com = main.simular(con, "Pacote de Aulas|8|2", h, "PIX", 1, consultoria="Consultoria Online")
    # 8 aulas 2x/semana = 4 semanas = 1 mês; consultoria 300 com 15% de desconto no combo
    assert com["meses_consultoria"] == 1
    assert com["preco_cheio"] == pytest.approx(sem["preco_cheio"] + 255, abs=0.01)
    # custo operacional 100 da planilha já traz os 60 de mão de obra: não soma de novo (antes: 160)
    assert com["custo_total"] == pytest.approx(sem["custo_total"] + 100, abs=0.01)
    assert com["mao_obra"] == pytest.approx(sem["mao_obra"] + 60, abs=0.01)
    assert com["horas"] > sem["horas"]   # o tempo da consultoria entra no lucro/hora
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


def test_consultoria_sem_preco_cadastrado_avisa(http):
    c, _ = http
    tela = c.get("/propostas", params={"plano": PLANO, "consultoria": "Consultoria Online", "h": ["1-10-CIA"]})
    assert "Não há preço de Consultoria Online" in tela.text
