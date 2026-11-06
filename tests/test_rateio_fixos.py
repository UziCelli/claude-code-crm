"""Custos fixos no preço: as contas fixas da PJ (MFIT, softwares, assinaturas) ÷ horas da agenda cheia, sem planilha.
Ficam de fora o que o motor já cobra (DAS, Retirada, CIA, mensalidade de um local) e as contas variáveis/PF/encerradas."""
import pytest
from fastapi.testclient import TestClient

from app import db, financeiro, locais, main, precos


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    c = db.conectar()
    with c:
        c.execute("UPDATE parametros SET valor=0 WHERE grupo='mao_obra' AND chave='valor_hora_auto'")
        c.execute("UPDATE parametros SET valor=53 WHERE grupo='mao_obra' AND chave='valor_hora'")
    yield c
    c.close()


def conta(con, descricao, valor, categoria="Software", escopo="PJ", fixo=1, inicio="2020-01", fim=None):
    with con:
        con.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio, fim)
                       VALUES (?,?,?,?,5,?,?,?)""", (escopo, descricao, categoria, valor, fixo, inicio, fim))


def test_rateio_soma_so_as_fixas_da_pj_que_o_motor_nao_cobra_por_aula(con):
    locais.criar_local(con, "Opfit", taxa_mensal=300, aulas_mes=20)
    conta(con, "MFIT", 120)
    conta(con, "Canva", 30, categoria="Assinaturas")
    conta(con, "Dropbox", 50)                                  # tem "box" no nome, mas não é o local
    conta(con, "Mensalidade Opfit", 300, categoria="Aluguel")   # o motor já cobra por aula
    conta(con, "CIA - créditos de aula", 800, categoria="Aluguel")
    conta(con, "DAS Simples", 400, categoria="Impostos")
    conta(con, "Retirada", 2000, categoria=financeiro.RETIRADA)
    conta(con, "Netflix", 40, escopo="PF")
    conta(con, "Anúncios", 200, fixo=0)
    conta(con, "Software antigo", 99, fim="2021-01")
    conta(con, "Software futuro", 99, inicio="2099-01")
    r = financeiro.custos_fixos_rateio(con, main.mes_atual(), ["Opfit", "Box"])
    assert r["total"] == 200
    assert [i["descricao"] for i in r["itens"]] == ["MFIT", "Dropbox", "Canva"]


def test_rateio_por_hora_entra_no_custo_de_cada_hora_de_trabalho(con):
    conta(con, "MFIT", 150)
    conta(con, "Softwares", 50)
    p = precos.carregar_parametros(con)
    assert p["rateio"]["total"] == 200 and p["rateio"]["horas"] == 97
    assert p["rateio_hora"] == pytest.approx(200 / 97, abs=0.0001)
    r = precos.calcular(precos.base_motor("Pacote de Aulas", 8, local="CIA"), p)
    assert r["custo_negocio"] == pytest.approx(8 * p["taxa_cia"][1] + 9 * 200 / 97, abs=0.01)


def test_sem_contas_fixas_o_rateio_e_zero(con):
    p = precos.carregar_parametros(con)
    assert p["rateio"] == {"total": 0, "itens": [], "horas": 97, "por_hora": 0}


def test_pacote_de_4_na_opfit_fica_na_faixa_certa(con):
    """O caso que motivou a mudança: 4 aulas na Opfit davam mais de R$ 1.800 (preço da planilha + custos de novo).
    Com R$ 53/h, 30 min de deslocamento, R$ 10/aula e R$ 500 de contas fixas: entre R$ 400 e R$ 700."""
    locais.criar_local(con, "Opfit", taxa_aula=10, tempo_deslocamento=30)
    conta(con, "MFIT", 300)
    conta(con, "Softwares", 200)
    p = precos.carregar_parametros(con)
    base = precos.base_motor("Pacote de Aulas", 4, local="Opfit")
    r = precos.calcular(base, p)
    assert r["horas"] == 7 and r["mao_obra"] == pytest.approx(371)
    assert r["custo_total"] == pytest.approx(371 + 40 + 7 * 500 / 97, abs=0.01)
    assert 400 < r["preco_minimo"] < r["preco_cheio"] < 700
    cartao = precos.calcular(base, p, forma_pagamento="Cartão 12x")
    assert cartao["preco_cheio"] > r["preco_cheio"]
    dupla = precos.calcular(base, p, pessoas=2)
    assert r["preco_cheio"] < dupla["preco_cheio"] < 2 * r["preco_cheio"]


def test_tela_calculos_mostra_o_rateio_e_a_conta_do_preco(con):
    conta(con, "MFIT", 150)
    t = TestClient(main.app, base_url="http://localhost").get("/calculos").text
    assert "Custos fixos no preço" in t and "MFIT" in t and "R$ 150,00" in t
    assert "Como o preço é montado" in t and "margem alvo" in t
    assert "Margem alvo por serviço" in t


def test_propostas_sem_planilha_pacote_4_na_opfit(con):
    locais.criar_local(con, "Opfit", taxa_aula=10, tempo_deslocamento=30)
    r = main.simular(con, "Pacote de Aulas|4|0", [], "PIX", 1, local="Opfit")
    assert 400 < r["preco_cheio"] < 700
    http = TestClient(main.app, base_url="http://localhost")
    tela = http.get("/propostas", params={"plano": "Pacote de Aulas|4|0", "local": "Opfit"})
    assert tela.status_code == 200 and main.moeda(r["preco_cheio"]) in tela.text and "Importe a planilha" not in tela.text
