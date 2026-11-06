"""Bugs graves de preço e locais: taxa da CIA, grupos de 5+, 'Pacote de N aulas', 'Ciagym'."""
import pytest
from fastapi.testclient import TestClient

from app import contas_auto, db, locais, main, precos


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    c = db.conectar()
    with c:
        c.execute("UPDATE parametros SET valor=0 WHERE grupo='mao_obra' AND chave='valor_hora_auto'")
    yield c
    c.close()


def _base(local, tipo="Pacote de Aulas", qtd=8):
    return precos.base_motor(tipo, qtd, local=local)


def _salvar_taxa_cia(con, valor):
    pid = con.execute("SELECT id FROM parametros WHERE grupo='taxa_cia' AND chave='1'").fetchone()[0]
    http = TestClient(main.app, base_url="http://localhost")
    r = http.post("/configuracoes", data={f"p_{pid}": str(valor).replace(".", ","), f"f_{pid}": "num"}, follow_redirects=False)
    assert r.status_code == 303


# --- bug 1: taxa da CIA congelada no custo (hoje o motor lê a taxa na hora)

def test_mudar_taxa_da_cia_muda_o_custo_dos_precos_da_cia(con):
    antiga = precos.taxas_cia(con)[0][1]
    c0 = precos.calcular(_base("CIA"), precos.carregar_parametros(con))["custo_total"]
    _salvar_taxa_cia(con, 90)
    p = precos.carregar_parametros(con)
    assert precos.calcular(_base("CIA"), p)["custo_total"] == pytest.approx(c0 + (90 - antiga) * 8, abs=0.01)
    avulsa = precos.calcular(_base("CIA", "Aula avulsa"), p)   # aula avulsa também acompanha
    assert avulsa["custo_negocio"] == pytest.approx(90 + p["rateio_hora"] * avulsa["horas"], abs=0.01)


def test_local_com_a_mesma_taxa_tem_o_mesmo_custo_da_cia(con):
    _salvar_taxa_cia(con, 90)
    locais.criar_local(con, "Igual", "CIA", taxa_aula=90)
    p = precos.carregar_parametros(con)
    assert precos.calcular(_base("Igual"), p)["custo_total"] == pytest.approx(precos.calcular(_base("CIA"), p)["custo_total"], abs=0.01)


def test_taxa_com_tres_casas_sobrevive_a_salvar_a_tela(con):
    _salvar_taxa_cia(con, 70.125)
    http = TestClient(main.app, base_url="http://localhost")
    html = http.get("/configuracoes").text
    assert "70,125" in html   # vírgula: o "70.125" voltava como 70 mil e 125
    pid = con.execute("SELECT id FROM parametros WHERE grupo='taxa_cia' AND chave='1'").fetchone()[0]
    http.post("/configuracoes", data={f"p_{pid}": "70,125", f"f_{pid}": "num"}, follow_redirects=False)
    assert precos.taxas_cia(con)[0][1] == pytest.approx(70.125)


# --- bug 7: grupo maior que a tabela

def test_por_grupo_usa_o_maior_configurado():
    t = {1: 1.0, 2: 1.6, 3: 2.1, 4: 2.5}
    assert precos.por_grupo(t, 2, 1.0) == 1.6
    assert precos.por_grupo(t, 6, 1.0) == 2.5
    assert precos.por_grupo({}, 3, 1.0) == 1.0


def test_grupo_de_cinco_nao_custa_o_preco_de_um(con):
    locais.criar_local(con, "Parque", "CIA")
    p = precos.carregar_parametros(con)
    quatro = precos.calcular(_base("Parque"), p, pessoas=4)
    cinco = precos.calcular(_base("Parque"), p, pessoas=5)
    assert cinco["preco_total"] == quatro["preco_total"] and cinco["custo_total"] == quatro["custo_total"]


def test_cia_com_maximo_sem_taxa_configurada_nao_quebra(con):
    with con:
        con.execute("UPDATE parametros SET valor=4 WHERE grupo='taxa_cia' AND chave='maximo_pessoas'")
    p = precos.carregar_parametros(con)
    r = precos.calcular(_base("CIA"), p, pessoas=4)   # sem taxa_cia['4']: vale a de 3
    tres = precos.calcular(_base("CIA"), p, pessoas=3)["custo_total"]
    assert r["custo_total"] == pytest.approx(tres + p["mo"]["valor_hora"] * 9 * (0.55 - 0.35), abs=0.02)


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
