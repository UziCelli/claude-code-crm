import math

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

# ---------- vários horários na mesma proposta (aba Propostas) ----------
from app.precos import calcular_misto  # noqa: E402


def test_misto_com_horarios_iguais_fica_igual():
    um = calcular(SMARTFIT_8, P)
    dois = calcular_misto([(SMARTFIT_8, 1.0, "SmartFit"), (SMARTFIT_8, 1.0, "SmartFit")], P)
    assert dois["preco_total"] == um["preco_total"] and dois["margem"] == um["margem"]


def test_misto_tira_a_media_dos_horarios():
    """Seg num horário de vale (x0,86) + Qua cheio: preço = média dos dois."""
    r = calcular_misto([(SMARTFIT_8, 0.86, "SmartFit"), (SMARTFIT_8, 1.0, "SmartFit")], P)
    assert r["preco_total"] == pytest.approx(932 * 0.93, abs=0.01)


def test_misto_de_locais_diferentes_mistura_custo():
    cia8 = {**SMARTFIT_8, "local": "CIA", "preco_base": 1100, "custo_operacional": 900}
    r = calcular_misto([(SMARTFIT_8, 1.0, "SmartFit"), (cia8, 1.0, "CIA")], P)
    assert r["preco_cheio"] == pytest.approx((932 + 1100) / 2)
    assert r["custo_total"] == pytest.approx((736.2353 + 900) / 2, abs=0.01)


def test_misto_respeita_o_maximo_de_pessoas_da_cia():
    with pytest.raises(ValueError):
        calcular_misto([(SMARTFIT_8, 1.0, "SmartFit"), (CIA_4, 1.0, "CIA")], P, pessoas=4)
    with pytest.raises(ValueError):
        calcular_misto([], P)


def test_preco_final_vira_desconto_e_pode_ser_acrescimo():
    r = calcular(SMARTFIT_8, P, preco_final=838.8)
    assert r["preco_total"] == 838.8 and r["desconto"] == pytest.approx(0.10)
    mais = calcular(SMARTFIT_8, P, preco_final=1000)
    assert mais["desconto"] < 0 and mais["margem"] > 0.15


def test_preco_sugerido_e_o_minimo_arredondado_para_cima():
    r = calcular(SMARTFIT_8, P, forma_pagamento="Cartão 3x")
    assert r["abaixo_margem"]
    assert r["preco_sugerido"] == float(math.ceil(r["preco_minimo"]))
    ajustado = calcular(SMARTFIT_8, P, forma_pagamento="Cartão 3x", preco_final=r["preco_sugerido"])
    assert not ajustado["abaixo_margem"]


# ---- Pacote personalizado (1 a 20 aulas) ----
from app.precos import base_pacote, calcular_misto  # noqa: E402

PACOTES = [dict(tipo_servico="Pacote de Aulas", local="CIA", qtd_aulas=q, preco_base=pb, custo_operacional=co,
                mao_obra=mo, sessoes_mes=q) for q, pb, co, mo in ((6, 600, 420, 300), (8, 760, 540, 400))]


def test_pacote_impar_interpola_entre_os_vizinhos():
    b = base_pacote(PACOTES, 7)
    assert (b["qtd_aulas"], b["sessoes_mes"], b["tipo_servico"]) == (7, 7, "Pacote de Aulas")
    assert b["preco_base"] == pytest.approx(680) and b["custo_operacional"] == pytest.approx(480)
    assert b["mao_obra"] == pytest.approx(350)


def test_pacote_cadastrado_usa_a_linha_exata():
    assert base_pacote(PACOTES, 8)["preco_base"] == 760


def test_pacote_fora_da_faixa_e_proporcional_por_aula():
    assert base_pacote(PACOTES, 3)["preco_base"] == pytest.approx(300)    # 600/6 x 3
    assert base_pacote(PACOTES, 20)["preco_base"] == pytest.approx(1900)  # 760/8 x 20


def test_aula_avulsa_vira_o_pacote_de_1_normalizada():
    avulsa = dict(tipo_servico="Aula avulsa", preco_base=320, custo_operacional=200, mao_obra=100, sessoes_mes=2)
    assert base_pacote(PACOTES, 1, avulsa)["preco_base"] == pytest.approx(160)
    # entre a avulsa (1) e o de 6: 160 + (600-160) x 2/5
    assert base_pacote(PACOTES, 3, avulsa)["preco_base"] == pytest.approx(336)


def test_pacote_sem_aulas_ou_sem_cadastro_da_erro():
    with pytest.raises(ValueError):
        base_pacote(PACOTES, 0)
    with pytest.raises(ValueError):
        base_pacote([], 5)


def test_extra_soma_preco_e_custo_da_consultoria():
    sem = calcular(SMARTFIT_8, P)
    com = calcular_misto([(SMARTFIT_8, 1.0, None)], P, extra=(200, 50))
    assert com["preco_cheio"] == pytest.approx(sem["preco_cheio"] + 200)
    assert com["custo_total"] == pytest.approx(sem["custo_total"] + 50)


# ---- Mão de obra = pró-labore pela regra do tempo ----
from app.precos import custo_servico, minutos_trabalho  # noqa: E402

MO = {"valor_hora": 46.1676, "min_aula": 60, "min_planejamento_pacote": 60, "min_planejamento_mes": 60,
      "min_consultoria_mes": 0, "min_avaliacao": 0}
PR = {**P, "mo": MO}


def test_regra_reproduz_a_mao_de_obra_da_planilha():
    """A planilha já fazia (aulas + 1 h de planejamento) x 46,17/h: 8 aulas = 415,51 e 4 aulas = 230,84."""
    assert custo_servico(SMARTFIT_8, PR)[1] == pytest.approx(415.5081, abs=0.01)
    assert custo_servico(CIA_4, PR)[1] == pytest.approx(230.8378, abs=0.01)
    r = calcular(SMARTFIT_8, PR)
    assert r["lucro"] == pytest.approx(139.84, abs=0.02)   # mesmo lucro da planilha
    assert r["mao_obra"] == pytest.approx(415.51, abs=0.01) and r["horas"] == 9


def test_mao_de_obra_sai_do_custo_operacional_e_entra_a_da_regra():
    """Custo operacional da planilha = resto + mão de obra: a hora mais cara sobe o custo só pela diferença."""
    caro = {**PR, "mo": {**MO, "valor_hora": 60}}
    resto, mo, horas = custo_servico(SMARTFIT_8, caro)
    assert resto == pytest.approx(736.2353 - 415.5081) and mo == pytest.approx(540) and horas == 9
    assert calcular(SMARTFIT_8, caro)["custo_total"] == pytest.approx(resto + 540, abs=0.01)


def test_pacote_personalizado_conta_o_tempo_pelo_numero_de_aulas():
    b = base_pacote(PACOTES, 5)
    assert minutos_trabalho(b, PR) == 5 * 60 + 60


def test_mensalidade_usa_o_planejamento_do_mes():
    mens = dict(tipo_servico="Mensalidade", preco_base=900, custo_operacional=500, mao_obra=300, sessoes_mes=8.66)
    assert minutos_trabalho(mens, {**PR, "mo": {**MO, "min_planejamento_mes": 30}}) == pytest.approx(8.66 * 60 + 30)


def test_deslocamento_do_local_e_tempo_de_trabalho():
    p = {**PR, "locais": {"Longe": {"tempo_deslocamento": 30}}}
    assert minutos_trabalho({**SMARTFIT_8, "local": "Longe"}, p) == 8 * 90 + 60


def test_grupo_soma_o_esforco_extra_sobre_a_mao_de_obra():
    solo, dupla = calcular(SMARTFIT_8, PR), calcular(SMARTFIT_8, PR, pessoas=2)
    assert dupla["mao_obra"] == pytest.approx(solo["mao_obra"] * 1.2, abs=0.01)
    assert dupla["custo_total"] - solo["custo_total"] == pytest.approx(solo["mao_obra"] * 0.2, abs=0.01)


def test_consultoria_e_avaliacao_sem_minutos_usam_a_planilha():
    cons = dict(tipo_servico="Consultoria Online", preco_base=300, custo_operacional=100, mao_obra=60, sessoes_mes=0)
    assert minutos_trabalho(cons, PR) is None
    assert custo_servico(cons, PR) == (40, 60, 1.0)
    com_min = {**PR, "mo": {**MO, "min_consultoria_mes": 90}}
    assert custo_servico(cons, com_min)[1:] == pytest.approx((1.5 * 46.1676, 1.5))
    aval = dict(tipo_servico="Avaliação Física", preco_base=150, custo_operacional=50, mao_obra=40, sessoes_mes=1)
    assert minutos_trabalho(aval, {**PR, "mo": {**MO, "min_avaliacao": 75}}) == 75


def test_valor_hora_zero_desliga_a_regra():
    assert minutos_trabalho(SMARTFIT_8, {**PR, "mo": {**MO, "valor_hora": 0}}) is None
    assert calcular(SMARTFIT_8, {**PR, "mo": {**MO, "valor_hora": 0}}) == calcular(SMARTFIT_8, P)


def test_minutos_medidos_viram_padrao_e_migram_banco_com_zero(tmp_path, monkeypatch):
    """Consultoria 150 min/mês e avaliação 17,5 min: banco novo já nasce assim; banco com o 0 antigo recebe uma vez."""
    from app import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    db.iniciar_banco()
    con = db.conectar()
    assert db.parametros(con, "mao_obra")["min_consultoria_mes"] == 150
    assert db.parametros(con, "mao_obra")["min_avaliacao"] == 17.5
    with con:
        con.execute("UPDATE parametros SET valor=0 WHERE grupo='mao_obra' AND chave='min_avaliacao'")
        con.execute("DELETE FROM parametros WHERE grupo='migracao'")
    con.close()
    db.iniciar_banco()
    con = db.conectar()
    assert db.parametros(con, "mao_obra")["min_avaliacao"] == 17.5
    with con:   # depois da migração, um 0 digitado na tela fica
        con.execute("UPDATE parametros SET valor=0 WHERE grupo='mao_obra' AND chave='min_avaliacao'")
    con.close()
    db.iniciar_banco()
    con = db.conectar()
    assert db.parametros(con, "mao_obra")["min_avaliacao"] == 0
    con.close()
