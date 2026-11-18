"""Contas a pagar: filtro de período (fim deste mês, próximos 30 dias, fim do mês que vem). O app lembra a escolha."""
import pytest

from app import financeiro
from tests.test_alertas import con_temp  # noqa: F401  (banco temporário)
from tests.test_alertas_acao import congelar, http  # noqa: F401  (hoje congelado no main; cliente HTTP do mesmo banco)
from tests.test_contas_a_pagar import SEM_LIVRO, lanc

HOJE = "2026-09-15"


@pytest.fixture
def cenario(con_temp, monkeypatch):
    congelar(monkeypatch, HOJE)
    lanc(con_temp, "PF", "2026-09-10", 100, "Conta da luz")     # atrasada: sempre aparece
    lanc(con_temp, "PJ", "2026-09-30", 200, "Fim do mes")      # último dia do mês atual
    lanc(con_temp, "PJ", "2026-10-12", 300, "Seguro")          # dentro de 30 dias, mas já no mês que vem
    lanc(con_temp, "PJ", "2026-10-28", 400, "IPVA")            # só no "fim do mês que vem"
    lanc(con_temp, "PJ", "2026-11-02", 500, "Depois")          # fora de tudo
    return con_temp


def nomes(contas):
    return sorted(i["descricao"] for i in contas["itens"])


def test_ate_do_periodo():
    assert financeiro.ate_do_periodo("2026-09-15", "mes") == "2026-09-30"
    assert financeiro.ate_do_periodo("2026-09-15", "30d") == "2026-10-15"
    assert financeiro.ate_do_periodo("2026-09-15", "mes_que_vem") == "2026-10-31"
    assert financeiro.ate_do_periodo("2026-12-10", "mes_que_vem") == "2027-01-31"   # virada do ano
    assert financeiro.ate_do_periodo("2026-01-31", "mes_que_vem") == "2026-02-28"
    assert financeiro.ate_do_periodo("2026-09-15", "xyz") == "2026-10-15"


def test_cada_periodo_filtra_as_contas(cenario):
    def periodo(p):
        return nomes(financeiro.contas_a_pagar(cenario, HOJE, ate=financeiro.ate_do_periodo(HOJE, p)))
    assert periodo("mes") == ["Conta da luz", "Fim do mes"]
    assert periodo("30d") == ["Conta da luz", "Fim do mes", "Seguro"]
    assert periodo("mes_que_vem") == ["Conta da luz", "Fim do mes", "IPVA", "Seguro"]
    assert nomes(financeiro.contas_a_pagar(cenario, HOJE)) == periodo("30d")   # sem período: o padrão de sempre


def test_tela_tem_os_botoes_e_lembra_o_periodo(cenario, http):
    pg = http.get(SEM_LIVRO + "&periodo=mes").text
    assert 'aria-current="true">Fim deste mês<' in pg and "Para pagar até 30/09" in pg
    assert "<strong>Fim do mes</strong>" in pg and "<strong>Seguro</strong>" not in pg
    pg = http.get(SEM_LIVRO).text   # sem nada na URL: volta como estava (cookie)
    assert 'aria-current="true">Fim deste mês<' in pg and "<strong>Seguro</strong>" not in pg
    pg = http.get(SEM_LIVRO + "&periodo=mes_que_vem").text
    assert "Para pagar até 31/10" in pg and "<strong>IPVA</strong>" in pg and "<strong>Depois</strong>" not in pg
    assert "&periodo=mes_que_vem#t-contas" in pg   # os outros filtros mantêm o período


def test_periodo_estranho_cai_em_30_dias(cenario, http):
    http.cookies.set("contas_periodo", "xyz")
    pg = http.get(SEM_LIVRO + "&periodo=<script>").text
    assert 'aria-current="true">Próximos 30 dias<' in pg and "Para pagar até 15/10" in pg


def test_vencidas_ignora_o_periodo(cenario, http):
    pg = http.get(SEM_LIVRO + "&periodo=mes&vencidas=1").text
    assert "Fim deste mês" not in pg and "<strong>Conta da luz</strong>" in pg


def test_saldo_livre_nao_muda_com_o_periodo(cenario, http):
    antes = financeiro.saldo_livre(cenario, HOJE)
    http.get(SEM_LIVRO + "&periodo=mes_que_vem")
    assert financeiro.saldo_livre(cenario, HOJE) == antes
