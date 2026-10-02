import pytest

from app.precos import calcular, cor_margem

# Parâmetros iguais aos da tela Configurações (valores iniciais)
P = {
    "das": 0.06,
    "taxas": {"PIX": 0.0, "Cartão 1x": 0.0581, "Cartão 3x": 0.0765, "Cartão 6x": 0.104, "Cartão 12x": 0.159},
    "margens": {"Pacote de Aulas": 0.15, "Mensalidade": 0.15, "Consultoria Online": 0.20},
    "taxa_cia": {1: 70.76, 2: 99.69, 3: 151.47},
    "cia_max": 3,
    "grupo_mult": {1: 1.0, 2: 1.6, 3: 2.1, 4: 2.5},
    "grupo_mo": {1: 0.0, 2: 0.20, 3: 0.35, 4: 0.55},
}
# Linha real do Comparador: Pacote 8 aulas, SmartFit, PIX -> preço 932, custo op 736,24, lucro 139,84, margem 15%
SMARTFIT_8 = dict(tipo_servico="Pacote de Aulas", local="SmartFit", preco_base=932, custo_operacional=736.2353,
                  mao_obra=415.5081, sessoes_mes=8)
CIA_4 = dict(tipo_servico="Pacote de Aulas", local="CIA", preco_base=831, custo_operacional=607.97,
             mao_obra=230.8378, sessoes_mes=4)


def test_bate_com_a_planilha_pix():
    r = calcular(SMARTFIT_8, P)
    assert r["preco_total"] == 932
    assert r["lucro"] == pytest.approx(139.84, abs=0.01)
    assert r["margem"] == pytest.approx(0.15, abs=0.001)
    assert r["lucro_hora"] == pytest.approx(17.48, abs=0.01)
    assert not r["abaixo_margem"]


def test_cartao_reduz_lucro():
    pix = calcular(SMARTFIT_8, P)
    c3 = calcular(SMARTFIT_8, P, forma_pagamento="Cartão 3x")
    assert c3["lucro"] == pytest.approx(pix["lucro"] - 932 * 0.0765, abs=0.01)
    assert c3["abaixo_margem"]


def test_desconto_e_preco_minimo():
    r = calcular(SMARTFIT_8, P, desconto=0.10)
    assert r["preco_total"] == pytest.approx(838.8)
    assert r["abaixo_margem"]
    r_min = calcular({**SMARTFIT_8, "preco_base": r["preco_minimo"]}, P)
    assert r_min["margem"] == pytest.approx(0.15, abs=0.001)
    r_max = calcular(SMARTFIT_8, P, desconto=r["desconto_maximo"])
    assert r_max["preco_total"] == pytest.approx(r["preco_minimo"], abs=0.05)


def test_grupo_dupla_multiplica_preco_e_mao_de_obra():
    solo, dupla = calcular(SMARTFIT_8, P), calcular(SMARTFIT_8, P, pessoas=2)
    assert dupla["preco_total"] == pytest.approx(932 * 1.6)
    assert dupla["preco_pessoa"] == pytest.approx(932 * 0.8)
    assert dupla["custo_total"] == pytest.approx(solo["custo_total"] + 415.5081 * 0.20, abs=0.01)


def test_cia_cobra_taxa_extra_por_pessoa_e_limita_a_3():
    solo, trio = calcular(CIA_4, P), calcular(CIA_4, P, pessoas=3)
    assert trio["custo_total"] == pytest.approx(solo["custo_total"] + 230.8378 * 0.35 + (151.47 - 70.76) * 4, abs=0.01)
    with pytest.raises(ValueError):
        calcular(CIA_4, P, pessoas=4)


def test_multiplicador_horario_de_vale():
    r = calcular(SMARTFIT_8, P, mult_horario=0.86)
    assert r["preco_total"] == pytest.approx(932 * 0.86)
    assert r["abaixo_margem"]


def test_validacoes():
    with pytest.raises(ValueError):
        calcular(SMARTFIT_8, P, desconto=1.5)
    with pytest.raises(ValueError):
        calcular(SMARTFIT_8, P, forma_pagamento="Boleto")


def test_cor_margem():
    assert [cor_margem(m) for m in (0.2, 0.12, 0.05, -0.1, None)] == ["verde", "amarelo", "vermelho", "prejuizo", "neutro"]