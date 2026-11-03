"""Bugs graves de preço e locais: taxa da CIA congelada, margem que zera o preço, grupos de 5+, 'Pacote de N aulas', 'Ciagym'."""
import pytest
from fastapi.testclient import TestClient

from app import contas_auto, db, importar, locais, main, precos


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    c = db.conectar()
    with c:
        c.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, preco_base,
                     custo_operacional, mao_obra, custo_total, sessoes_mes) VALUES ('Pacote de Aulas', 'CIA', 'PIX', 8, 0, 1100, 900, 415.5, 900, 8)""")
        c.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, preco_base,
                     custo_operacional, mao_obra, custo_total, sessoes_mes) VALUES ('Avaliação', 'CIA', 'PIX', 0, 0, 150, 40, 0, 40, 1)""")
    yield c
    c.close()


def _base(con, local, tipo="Pacote de Aulas"):
    return dict(con.execute("SELECT * FROM precos_base WHERE local=? AND tipo_servico=?", (local, tipo)).fetchone())


def _salvar_taxa_cia(con, valor):
    pid = con.execute("SELECT id FROM parametros WHERE grupo='taxa_cia' AND chave='1'").fetchone()[0]
    http = TestClient(main.app, base_url="http://localhost")
    r = http.post("/configuracoes", data={f"p_{pid}": str(valor).replace(".", ","), f"f_{pid}": "num"}, follow_redirects=False)
    assert r.status_code == 303


# --- bug 1: taxa da CIA congelada no custo importado

def test_mudar_taxa_da_cia_muda_o_custo_dos_precos_da_cia(con):
    antiga = precos.taxas_cia(con)[0][1]
    m0 = precos.calcular(_base(con, "CIA"), precos.carregar_parametros(con))["margem"]
    _salvar_taxa_cia(con, 90)
    b = _base(con, "CIA")
    assert b["custo_operacional"] == pytest.approx(900 + (90 - antiga) * 8, abs=0.01)
    assert b["custo_total"] == pytest.approx(900 + (90 - antiga) * 8, abs=0.01)
    assert precos.calcular(b, precos.carregar_parametros(con))["margem"] < m0
    assert _base(con, "CIA", "Avaliação")["custo_operacional"] == 40   # sem aula de CIA: não mexe


def test_local_com_a_taxa_antiga_tem_o_mesmo_custo_da_cia(con):
    antiga = precos.taxas_cia(con)[0][1]
    _salvar_taxa_cia(con, 90)
    locais.criar_local(con, "Igual", "CIA", "preco", taxa_aula=90)
    assert _base(con, "Igual")["custo_operacional"] == pytest.approx(_base(con, "CIA")["custo_operacional"], abs=0.01)
    _salvar_taxa_cia(con, antiga)   # voltar a taxa volta o custo
    assert _base(con, "CIA")["custo_operacional"] == pytest.approx(900, abs=0.01)


def test_salvar_sem_mudar_a_taxa_nao_mexe_no_custo(con):
    _salvar_taxa_cia(con, precos.taxas_cia(con)[0][1])
    assert _base(con, "CIA")["custo_operacional"] == 900


def test_aula_avulsa_da_cia_tambem_acompanha_a_taxa(con):
    antiga = precos.taxas_cia(con)[0][1]
    with con:
        con.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, preco_base,
                     custo_operacional, mao_obra, custo_total, sessoes_mes) VALUES ('Aula avulsa', 'CIA', 'PIX', 1, 0, 160, 100, 50, 100, 1)""")
    _salvar_taxa_cia(con, 90)
    assert _base(con, "CIA", "Aula avulsa")["custo_operacional"] == pytest.approx(100 + 90 - antiga, abs=0.01)


def test_reimportar_a_planilha_nao_desfaz_a_taxa_da_tela(con, monkeypatch):
    planilha = precos.taxas_cia(con)[0][1]   # a planilha usou a taxa de hoje no custo (900)
    _salvar_taxa_cia(con, 90)
    linhas = {
        "tblComparadorPrecos": [{"Tipo Serviço": "Pacote de Aulas", "Local": "CIA", "Forma Pagamento": "PIX", "Qtd Aulas/Planos": 8,
                                 "Preço Sugerido": 1100, "Custo Operacional": 900, "Mão-de-Obras": 415.5, "Custo Total": 900}],
        "Tabela18": [{"Taxas": "CIA 1 pessoa", "Nº de pessoas": 1, "Valor [R$]": planilha}],
    }
    monkeypatch.setattr(importar, "ler_tabela", lambda wb, aba, tabela: linhas.get(tabela, []))
    with con:
        importar.importar_precos(con, None)
    assert _base(con, "CIA")["custo_operacional"] == pytest.approx(900 + (90 - planilha) * 8, abs=0.01)


def test_taxa_com_tres_casas_sobrevive_a_salvar_a_tela(con):
    _salvar_taxa_cia(con, 70.125)
    http = TestClient(main.app, base_url="http://localhost")
    html = http.get("/configuracoes").text
    assert "70,125" in html   # vírgula: o "70.125" voltava como 70 mil e 125
    pid = con.execute("SELECT id FROM parametros WHERE grupo='taxa_cia' AND chave='1'").fetchone()[0]
    http.post("/configuracoes", data={f"p_{pid}": "70,125", f"f_{pid}": "num"}, follow_redirects=False)
    assert precos.taxas_cia(con)[0][1] == pytest.approx(70.125)


# --- bug 2: "manter a margem" com custo que zera

def test_manter_margem_com_custo_zero_mantem_o_preco_e_avisa(con):
    with con:
        con.execute("UPDATE precos_base SET custo_operacional=566.08 WHERE local='CIA'")   # o custo é só a taxa da CIA
    r = locais.criar_local(con, "Casa", "CIA", "margem")
    b = _base(con, "Casa")
    assert b["custo_operacional"] == 0
    assert b["preco_base"] == 1100 and r["mantidos"] == 1
    r = locais.criar_local(con, "Caro", "Casa", "margem", taxa_aula=100)   # copiar de um local sem custo também não zera
    assert _base(con, "Caro")["preco_base"] == 1100 and r["mantidos"] == 1


def test_manter_margem_normal_nao_conta_mantidos(con):
    assert locais.criar_local(con, "Prédio", "CIA", "margem", taxa_aula=30)["mantidos"] == 0
    assert locais.criar_local(con, "Mesmo", "CIA", "preco")["mantidos"] == 0


def test_rota_avisa_os_planos_mantidos(con):
    with con:
        con.execute("UPDATE precos_base SET custo_operacional=566.08 WHERE local='CIA'")
    http = TestClient(main.app, base_url="http://localhost")
    r = http.post("/locais/novo", data={"nome": "Casa", "modo": "margem", "voltar": "/propostas"}, follow_redirects=False)
    assert "Mantive" in http.get(r.headers["location"]).text


# --- bug 7: grupo maior que a tabela

def test_por_grupo_usa_o_maior_configurado():
    t = {1: 1.0, 2: 1.6, 3: 2.1, 4: 2.5}
    assert precos.por_grupo(t, 2, 1.0) == 1.6
    assert precos.por_grupo(t, 6, 1.0) == 2.5
    assert precos.por_grupo({}, 3, 1.0) == 1.0


def test_grupo_de_cinco_nao_custa_o_preco_de_um(con):
    locais.criar_local(con, "Parque", "CIA", "preco")
    p = precos.carregar_parametros(con)
    quatro = precos.calcular(_base(con, "Parque"), p, pessoas=4)
    cinco = precos.calcular(_base(con, "Parque"), p, pessoas=5)
    assert cinco["preco_total"] == quatro["preco_total"] and cinco["custo_total"] == quatro["custo_total"]


def test_cia_com_maximo_sem_taxa_configurada_nao_quebra(con):
    with con:
        con.execute("UPDATE parametros SET valor=4 WHERE grupo='taxa_cia' AND chave='maximo_pessoas'")
    p = precos.carregar_parametros(con)
    r = precos.calcular(_base(con, "CIA"), p, pessoas=4)   # sem taxa_cia['4']: vale a de 3
    tres = precos.calcular(_base(con, "CIA"), p, pessoas=3)["custo_total"]
    assert r["custo_total"] == pytest.approx(tres + 415.5 * (0.55 - 0.35), abs=0.02)


# --- bug 8: rótulo das Propostas

@pytest.mark.parametrize("plano, n", [("Pacote 8", 8), ("Pacote de 8 aulas", 8), ("Pacote de 12 aulas", 12), ("Mensalidade 2x por semana", 2 * main.SEMANAS_MES)])
def test_aulas_mes_entende_os_dois_rotulos(plano, n):
    assert main.aulas_mes({"plano": plano, "tipo_servico": ""}) == n


# --- bug 10: só a CIA é a CIA

@pytest.mark.parametrize("local", ["CIA", "cia", " Cia 111", "CIA - centro", "CIA111", "CIA2", "CIA_Centro"])
def test_eh_local_cia(local):
    assert contas_auto.eh_local_cia(local)


@pytest.mark.parametrize("local", ["Ciagym", "Ciática Studio", "SmartFit", "", None])
def test_nao_eh_local_cia(local):
    assert not contas_auto.eh_local_cia(local)
