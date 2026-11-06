"""Contas a pagar: ordenar (mais urgente, por data, maior valor) e separar custos fixos de variáveis. O app lembra a escolha."""
import pytest

from app import financeiro
from tests.test_alertas import con_temp  # noqa: F401  (banco temporário)
from tests.test_alertas_acao import congelar, http  # noqa: F401  (hoje congelado no main; cliente HTTP do mesmo banco)
from tests.test_contas_a_pagar import SEM_LIVRO, lanc

HOJE = "2026-09-15"


def recorrencia(con, descricao, valor, dia, fixo):
    with con:
        return con.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio)
                              VALUES ('PJ', ?, 'Outros', ?, ?, ?, '2026-09')""", (descricao, valor, dia, fixo)).lastrowid


@pytest.fixture
def cenario(con_temp, monkeypatch):
    congelar(monkeypatch, HOJE)
    lanc(con_temp, "PF", "2026-09-10", 100, "Conta da luz")            # avulsa atrasada: variável
    lanc(con_temp, "PJ", "2026-09-30", 900, "Equipamento novo")         # avulsa, a mais cara: variável
    recorrencia(con_temp, "Aluguel da sala", 600, 20, fixo=1)           # recorrente fixa
    rid = recorrencia(con_temp, "Energia do estúdio", 150, 18, fixo=0)  # recorrente marcada como "varia"
    with con_temp:   # lançamento ligado a uma recorrente fixa herda o "fixo" dela
        fixa = recorrencia(con_temp, "Contador", 250, 25, fixo=1)
        con_temp.execute("""INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, descricao, recorrencia_id, competencia)
                            VALUES ('PJ','saida','2026-09-25',250,'Outros','Contador',?,'2026-09')""", (fixa,))
    return con_temp, rid


def nomes(contas):
    return [i["descricao"] for i in contas["itens"]]


def test_cada_conta_sabe_se_e_fixa_ou_variavel(cenario):
    con, _ = cenario
    c = financeiro.contas_a_pagar(con, HOJE)
    fixo = {i["descricao"]: i["fixo"] for i in c["itens"]}
    assert fixo == {"Conta da luz": False, "Equipamento novo": False, "Aluguel da sala": True,
                    "Energia do estúdio": False, "Contador": True}
    assert (c["total_fixos"], c["total_variaveis"], c["n_fixos"], c["n_variaveis"]) == (850, 1150, 2, 3)
    assert c["total"] == 2000


def test_filtro_de_custo_mostra_so_um_tipo_e_mantem_as_duas_somas(cenario):
    con, _ = cenario
    f = financeiro.contas_a_pagar(con, HOJE, custo="fixo")
    assert sorted(nomes(f)) == ["Aluguel da sala", "Contador"] and f["total"] == 850
    v = financeiro.contas_a_pagar(con, HOJE, custo="variavel")
    assert sorted(nomes(v)) == ["Conta da luz", "Energia do estúdio", "Equipamento novo"] and v["total"] == 1150
    assert f["total_variaveis"] == v["total_variaveis"] == 1150   # os botões mostram as duas somas, com ou sem filtro


def test_ordenar_por_data_e_por_valor(cenario):
    con, _ = cenario
    assert nomes(financeiro.contas_a_pagar(con, HOJE, ordem="data")) == [
        "Conta da luz", "Energia do estúdio", "Aluguel da sala", "Contador", "Equipamento novo"]
    assert nomes(financeiro.contas_a_pagar(con, HOJE, ordem="valor"))[:2] == ["Equipamento novo", "Aluguel da sala"]
    assert nomes(financeiro.contas_a_pagar(con, HOJE))[0] == "Conta da luz"   # o padrão segue: atrasada primeiro


def test_tela_tem_os_botoes_e_lembra_a_escolha(cenario, http):
    pg = http.get(SEM_LIVRO + "&ordem=data&custo=fixo").text
    assert 'aria-current="true">Por data<' in pg and "Fixos · R$" in pg and "(só fixos)" in pg
    assert pg.count("<strong>Aluguel da sala</strong>") == 1 and "<strong>Conta da luz</strong>" not in pg
    assert pg.index("<strong>Aluguel da sala</strong>") < pg.index("<strong>Contador</strong>")
    # sem nada na URL: volta como estava (cookie), ex.: depois de pagar uma conta
    pg = http.get(SEM_LIVRO).text
    assert 'aria-current="true">Por data<' in pg and "(só fixos)" in pg
    # Tudo de novo: as variáveis voltam, com a etiqueta
    pg = http.get(SEM_LIVRO + "&custo=todos").text
    assert "<strong>Conta da luz</strong>" in pg and ">variável</span>" in pg and ">fixo</span>" in pg


def test_valor_estranho_na_url_cai_no_padrao(cenario, http):
    http.cookies.set("contas_ordem", "xyz")
    pg = http.get(SEM_LIVRO + "&ordem=<script>&custo=nada").text
    assert 'aria-current="true">Mais urgente<' in pg and "<script>" not in pg.split("Contas a pagar")[1][:3000]


def test_filtro_vazio_oferece_ver_tudo(con_temp, monkeypatch, http):
    congelar(monkeypatch, HOJE)
    lanc(con_temp, "PF", "2026-09-20", 100, "Só variável")
    pg = http.get(SEM_LIVRO + "&custo=fixo").text
    assert "Nenhuma conta fixa nesse período" in pg and "custo=todos#t-contas" in pg
