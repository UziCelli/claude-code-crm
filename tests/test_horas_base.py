"""Salário por hora e custos fixos dividem pela MESMA base: as suas horas de trabalho do mês (aulas + deslocamento +
planejamento + consultoria), com a agenda cheia (metas > horas_vendaveis) só como piso. A parte das contas fixas que
nenhum aluno paga entra inteira no "O mês cobre?"."""
import re

import pytest
from fastapi.testclient import TestClient

from app import db, main, precos
from tests.test_rateio_fixos import conta
from tests.test_salario_hora import aluno, gasto_pf


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    c = db.conectar()
    yield c
    c.close()


def meta_cheia(con, horas):
    with con:
        con.execute("UPDATE parametros SET valor=? WHERE grupo='metas' AND chave='horas_vendaveis'", (horas,))


def texto(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def agenda_acima_da_meta(con):
    """Meta da agenda cheia 60 h; 12 alunos x 9 h = 108 h de trabalho (como no print: trabalha mais que a meta)."""
    meta_cheia(con, 60)
    for n in range(12):
        aluno(con, f"A{n}")
    gasto_pf(con, 5400, -1)
    conta(con, "MFIT", 216)


def test_agenda_acima_da_meta_salario_e_custos_fixos_dividem_pelas_horas_de_trabalho(con):
    agenda_acima_da_meta(con)
    p = precos.carregar_parametros(con)
    sh, ra = p["salario_hora"], p["rateio"]
    assert sh["horas_base"] == ra["horas"] == 108 and not sh["piso"] and not ra["piso"]
    assert sh["valor_hora"] == pytest.approx(50)          # 5.400 ÷ 108 h
    assert p["rateio_hora"] == pytest.approx(2)            # 216 ÷ 108 h, não 216 ÷ 60 h (3,60)
    # a soma das partes dos alunos dá exatamente as contas fixas: nada contado a mais
    ests = [main.estimativa_cliente(con, c, p) for c in con.execute("SELECT * FROM clientes")]
    assert sum(p["rateio_hora"] * e["horas"] for e in ests) == pytest.approx(216, abs=0.01)
    assert sum(e["mao_obra"] for e in ests) == pytest.approx(5400, abs=0.05)
    assert main.cobre_custos(con, p)["fixos_ociosos"] == 0


def test_agenda_abaixo_da_meta_piso_na_meta_e_o_resto_das_contas_entra_no_mes(con):
    meta_cheia(con, 97)
    aluno(con, "Ana")
    aluno(con, "Bia")                    # 18 h de trabalho < 97 h
    gasto_pf(con, 4850, -1)
    conta(con, "MFIT", 194)
    p = precos.carregar_parametros(con)
    assert p["salario_hora"]["piso"] and p["rateio"]["piso"] and p["rateio"]["horas"] == 97
    assert p["rateio_hora"] == pytest.approx(2)            # 194 ÷ 97 h
    c = main.cobre_custos(con, p)
    assert c["fixos_ociosos"] == pytest.approx(194 - 2 * 18, abs=0.01)   # 158 que nenhum aluno paga
    negocio_alunos = 2 * (8 * p["taxa_cia"][1] + 2 * 9)
    assert c["negocio"] == pytest.approx(negocio_alunos + c["fixos_ociosos"], abs=0.02)   # as contas entram inteiras


def test_horas_de_trabalho_por_parte_somam_o_total(con):
    with con:
        con.execute("UPDATE parametros SET valor=15 WHERE grupo='cia_deslocamento' AND chave='minutos_por_aula'")
    aluno(con, "Ana")                                                                          # 8 h aula + 2 h ida + 1 h plan.
    aluno(con, "Bia", tipo="Consultoria Online", plano="Consultoria Online", local="Online")   # 2,5 h de consultoria
    aluno(con, "Edu", tipo="Outro", plano="Pacote 8 aulas")                                    # sem plano do motor: 8 h de aula
    p = precos.carregar_parametros(con)
    d = main.horas_trabalho_detalhe(con, p)
    assert d == pytest.approx({"aulas": 16, "deslocamento": 2, "planejamento": 1, "consultoria": 2.5, "avaliacao": 0, "total": 21.5})
    assert main.horas_trabalho_mes(con, p) == pytest.approx(21.5)
    base = precos.base_motor("Pacote de Aulas", 8, local="CIA")
    assert precos.minutos_trabalho(base, p) == pytest.approx(sum(precos.partes_minutos(base, p).values())) == 660
    assert p["salario_hora"]["partes"]["deslocamento"] == 2


def test_telas_falam_de_horas_de_trabalho_quando_a_agenda_passa_da_meta(con):
    agenda_acima_da_meta(con)
    http = TestClient(main.app, base_url="http://localhost")
    t = texto(http.get("/calculos").text)
    assert "R$ 50,00 = custos pessoais R$ 5.400,00/mês ÷ 108 h de trabalho no mês." in t
    assert "108 h de trabalho = 96 h de aula + 12 h de planejamento" in t
    assert "R$ 2,00 por hora de trabalho = R$ 216,00/mês ÷ 108 h de trabalho no mês (as mesmas do salário)" in t
    assert "Divide pelas horas da agenda cheia" not in t and "menos que a agenda cheia" not in t
    assert "contas fixas que nenhum aluno paga" not in t
    painel = texto(http.get("/").text)
    assert "R$ 5.400,00/mês ÷ 108 h de trabalho" in painel
    assert "Lucro médio por hora de trabalho" in painel and "Lucro médio por hora de aula" not in painel


def test_telas_explicam_o_piso_quando_a_agenda_esta_abaixo_da_meta(con):
    aluno(con, "Ana")
    aluno(con, "Bia")
    gasto_pf(con, 4850, -1)
    conta(con, "MFIT", 194)
    http = TestClient(main.app, base_url="http://localhost")
    t = texto(http.get("/calculos").text)
    assert "÷ 97 h da agenda cheia." in t
    assert "Hoje você trabalha 18 h, menos que a agenda cheia (97 h): divide por 97 h" in t
    assert "contas fixas que nenhum aluno paga" in t and "R$ 158,00" in t
    assert "R$ 194,00/mês ÷ 97 h da agenda cheia (as mesmas do salário)" in t
    assert "÷ 97 h da agenda cheia" in texto(http.get("/").text)


def test_historico_marca_so_os_meses_gravados_pela_regra_antiga(con):
    """O * (lucro/h por hora de aula) vem de como o mês foi gravado, não da data: um mês antigo gravado agora já é por hora
    de trabalho; e a seta "vs mês anterior" do lucro/h não compara regras diferentes."""
    aluno(con, "Ana")
    http = TestClient(main.app, base_url="http://localhost")
    http.get("/")   # grava o mês anterior pela regra nova
    assert con.execute("SELECT COUNT(*) FROM metricas_mensais WHERE lucro_hora_trabalho=0").fetchone()[0] == 0
    t = http.get("/").text
    assert "Lucro/h gravado por hora de aula" not in t
    with con:   # um mês gravado antes desta versão (a coluna nova chega com 0)
        con.execute("INSERT INTO metricas_mensais (mes, clientes_ativos, horas_ocupadas, lucro_hora, pct_receita_grupos, "
                    "faturamento_recorrente, clientes_perdidos, vendas_abaixo_10, nivel, lucro_hora_trabalho) "
                    "VALUES ('2020-01', 3, 24, 80, 0, 2700, 0, 0, 1, 0)")
    t = texto(http.get("/").text)
    assert "Lucro/h gravado por hora de aula" in t and "R$ 80,00*" in t


def test_seta_do_lucro_hora_some_quando_o_mes_anterior_e_da_regra_antiga(con):
    aluno(con, "Ana")
    http = TestClient(main.app, base_url="http://localhost")
    ant = (main.dt.date.fromisoformat(main.mes_atual() + "-01") - main.dt.timedelta(days=1)).strftime("%Y-%m")
    with con:   # o Painel não grava mais o mês anterior sozinho: a linha antiga vem de um fechamento
        con.execute("INSERT INTO metricas_mensais (mes, clientes_ativos, horas_ocupadas, lucro_hora, pct_receita_grupos,"
                    " faturamento_recorrente, clientes_perdidos, vendas_abaixo_10, nivel) VALUES (?,1,1,1,0,0,0,0,1)", (ant,))

    def seta_do_lucro():
        html = http.get("/").text
        card = html[html.index("Lucro médio por hora de trabalho"):]
        return "vs mês anterior" in card[:card.index("Meta dez/26")]

    with con:
        con.execute("UPDATE metricas_mensais SET lucro_hora=999, lucro_hora_trabalho=1 WHERE mes=?", (ant,))
    assert seta_do_lucro()          # mesma regra: compara
    with con:
        con.execute("UPDATE metricas_mensais SET lucro_hora_trabalho=0 WHERE mes=?", (ant,))
    assert not seta_do_lucro()      # regra antiga: não compara
