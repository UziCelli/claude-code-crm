"""Motor de preços sem planilha: custo = mão de obra (horas x valor da hora) + local por aula + rateio dos fixos por hora.
Preço de tabela = custo ÷ (1 − imposto − taxa − margem alvo); mínimo = custo ÷ (1 − imposto − taxa − margem mínima)."""
import math

import pytest

from app.precos import base_motor, calcular, calcular_misto, cor_margem, custo_servico, margem_alvo, minutos_trabalho

MO = {"valor_hora": 53, "min_aula": 60, "min_planejamento_pacote": 60, "min_planejamento_mes": 60,
      "min_consultoria_mes": 150, "min_avaliacao": 30}
OPFIT = {"local": "Opfit", "taxa_aula": 10, "taxa_pessoa_extra": 5, "max_pessoas": 0, "deslocamento": 0,
         "tempo_deslocamento": 30, "taxa_mensal": 0, "aulas_mes": 0}
P = {
    "das": 0.06,
    "taxas": {"PIX": 0.0, "Cartão 1x": 0.0581, "Cartão 3x": 0.0765, "Cartão 6x": 0.104, "Cartão 12x": 0.159},
    "margens": {"Pacote de Aulas": 0.15, "Mensalidade": 0.15, "Consultoria Online": 0.20, "Avaliação Física": 0.20},
    "margens_alvo": {"Pacote de Aulas": 0.25, "Mensalidade": 0.25, "Consultoria Online": 0.30, "Avaliação Física": 0.30},
    "taxa_cia": {1: 70.76, 2: 99.69, 3: 151.47},
    "cia_max": 3,
    "grupo_mo": {1: 0.0, 2: 0.20, 3: 0.35, 4: 0.55},
    "locais": {"Opfit": OPFIT},
    "mo": MO,
    "rateio_hora": 5.0,
}
OP4 = base_motor("Pacote de Aulas", 4, local="Opfit")
CIA8 = base_motor("Pacote de Aulas", 8, local="CIA")


def test_pacote_de_4_na_opfit_pela_conta_do_motor():
    """4 x (60 + 30 min) + 1 h de planejamento = 7 h. MO 7 x 53 = 371; local 4 x 10 = 40; fixos 7 x 5 = 35: custo 446."""
    r = calcular(OP4, P)
    assert r["horas"] == 7 and r["mao_obra"] == pytest.approx(371)
    assert r["custo_total"] == pytest.approx(446)
    assert r["custo_negocio"] == pytest.approx(75)
    assert r["preco_cheio"] == pytest.approx(446 / 0.69, abs=0.01)     # 646,38: margem alvo 25%
    assert r["preco_minimo"] == pytest.approx(446 / 0.79, abs=0.01)    # 564,56: margem mínima 15%
    assert r["margem"] == pytest.approx(0.25, abs=0.0005) and r["margem_alvo"] == 0.25
    assert 400 < r["preco_minimo"] < r["preco_cheio"] < 700
    assert not r["abaixo_margem"]


def test_custo_servico_separa_negocio_mao_de_obra_e_horas():
    assert custo_servico(OP4, P) == pytest.approx((75, 371, 7))
    assert custo_servico(CIA8, P) == pytest.approx((70.76 * 8 + 5 * 9, 53 * 9, 9))


def test_cartao_tira_a_taxa_e_o_preco_de_tabela_sobe():
    pix, c3 = calcular(OP4, P), calcular(OP4, P, forma_pagamento="Cartão 3x")
    assert c3["preco_cheio"] == pytest.approx(446 / (1 - 0.06 - 0.0765 - 0.25), abs=0.01)
    assert c3["margem"] == pytest.approx(0.25, abs=0.0005)
    assert c3["preco_minimo"] > pix["preco_minimo"]


def test_desconto_ate_o_preco_minimo():
    r = calcular(OP4, P, desconto=0.20)
    assert r["preco_total"] == pytest.approx(r["preco_cheio"] * 0.8, abs=0.01) and r["abaixo_margem"]
    r_max = calcular(OP4, P, desconto=r["desconto_maximo"])
    assert r_max["preco_total"] == pytest.approx(r["preco_minimo"], abs=0.05)
    assert r_max["margem"] == pytest.approx(0.15, abs=0.001)


def test_grupo_soma_mao_de_obra_extra_e_taxa_por_pessoa_do_local():
    solo, dupla = calcular(OP4, P), calcular(OP4, P, pessoas=2)
    assert dupla["mao_obra"] == pytest.approx(371 * 1.2)
    assert dupla["custo_total"] == pytest.approx(446 + 371 * 0.2 + 5 * 4)
    assert dupla["preco_cheio"] == pytest.approx(dupla["custo_total"] / 0.69, abs=0.01)
    assert dupla["preco_pessoa"] == pytest.approx(dupla["preco_total"] / 2)
    assert dupla["preco_pessoa"] < solo["preco_total"]


def test_cia_cobra_taxa_extra_por_pessoa_e_limita_a_3():
    solo, trio = calcular(CIA8, P), calcular(CIA8, P, pessoas=3)
    assert trio["custo_total"] == pytest.approx(solo["custo_total"] + 53 * 9 * 0.35 + (151.47 - 70.76) * 8, abs=0.01)
    with pytest.raises(ValueError, match="máximo é 3"):
        calcular(CIA8, P, pessoas=4)


def test_local_com_maximo_de_pessoas():
    p = {**P, "locais": {"Opfit": {**OPFIT, "max_pessoas": 2}}}
    calcular(OP4, p, pessoas=2)
    with pytest.raises(ValueError, match="Em Opfit o máximo é 2"):
        calcular(OP4, p, pessoas=3)


def test_multiplicador_horario_de_vale():
    r = calcular(OP4, P, mult_horario=0.86)
    assert r["preco_total"] == pytest.approx(446 / 0.69 * 0.86, abs=0.01)
    assert r["margem"] < 0.25


def test_validacoes():
    with pytest.raises(ValueError):
        calcular(OP4, P, desconto=1.5)
    with pytest.raises(ValueError):
        calcular(OP4, P, forma_pagamento="Boleto")
    with pytest.raises(ValueError, match="passam de 100%"):
        calcular(OP4, {**P, "margens_alvo": {"Pacote de Aulas": 0.95}})


def test_margem_alvo_sem_cadastro_e_mínima_mais_10_e_nunca_abaixo_da_minima():
    assert margem_alvo({**P, "margens_alvo": {}}, "Pacote de Aulas") == pytest.approx(0.25)
    assert margem_alvo({**P, "margens_alvo": {"Pacote de Aulas": 0.05}}, "Pacote de Aulas") == 0.15
    assert margem_alvo(P, "Pacote de Aulas") == 0.25


def test_cor_margem():
    assert [cor_margem(m) for m in (0.2, 0.12, 0.05, -0.1, None)] == ["verde", "amarelo", "vermelho", "prejuizo", "neutro"]


# ---------- vários horários na mesma proposta (aba Propostas) ----------
def test_misto_com_horarios_iguais_fica_igual():
    um = calcular(OP4, P)
    dois = calcular_misto([(OP4, 1.0, "Opfit"), (OP4, 1.0, "Opfit")], P)
    assert dois["preco_total"] == um["preco_total"] and dois["margem"] == um["margem"]


def test_misto_tira_a_media_dos_horarios():
    r = calcular_misto([(OP4, 0.86, "Opfit"), (OP4, 1.0, "Opfit")], P)
    assert r["preco_total"] == pytest.approx(446 / 0.69 * 0.93, abs=0.01)


def test_misto_de_locais_diferentes_mistura_custo():
    cia4 = base_motor("Pacote de Aulas", 4, local="CIA")
    r = calcular_misto([(OP4, 1.0, "Opfit"), (cia4, 1.0, "CIA")], P)
    custo_cia = 70.76 * 4 + 5 * 5 + 53 * 5
    assert r["custo_total"] == pytest.approx((446 + custo_cia) / 2, abs=0.01)
    assert r["preco_cheio"] == pytest.approx(r["custo_total"] / 0.69, abs=0.01)


def test_misto_respeita_o_maximo_de_pessoas_da_cia():
    with pytest.raises(ValueError):
        calcular_misto([(OP4, 1.0, "Opfit"), (CIA8, 1.0, "CIA")], P, pessoas=4)
    with pytest.raises(ValueError):
        calcular_misto([], P)


def test_preco_final_vira_desconto_e_pode_ser_acrescimo():
    cheio = calcular(OP4, P)["preco_cheio"]
    r = calcular(OP4, P, preco_final=round(cheio * 0.9, 2))
    assert r["desconto"] == pytest.approx(0.10, abs=0.0001)
    mais = calcular(OP4, P, preco_final=800)
    assert mais["desconto"] < 0 and mais["margem"] > 0.25


def test_preco_sugerido_e_o_minimo_arredondado_para_cima():
    r = calcular(OP4, P, preco_final=500)
    assert r["abaixo_margem"]
    assert r["preco_sugerido"] == float(math.ceil(r["preco_minimo"]))
    assert not calcular(OP4, P, preco_final=r["preco_sugerido"])["abaixo_margem"]


def test_extra_soma_preco_e_custo_da_consultoria():
    sem = calcular(OP4, P)
    com = calcular_misto([(OP4, 1.0, None)], P, extra=(200, 50))
    assert com["preco_cheio"] == pytest.approx(sem["preco_cheio"] + 200)
    assert com["custo_total"] == pytest.approx(sem["custo_total"] + 50)


# ---------- planos e tempo de trabalho ----------
def test_base_motor_conta_as_aulas_do_mes():
    assert base_motor("Pacote de Aulas", 7)["sessoes_mes"] == 7
    m = base_motor("Mensalidade", freq=2, local="CIA")
    assert (m["sessoes_mes"], m["freq_semanal"], m["qtd_aulas"], m["local"]) == (pytest.approx(8.66), 2, 0, "CIA")
    assert base_motor("Aula avulsa")["sessoes_mes"] == 1
    assert base_motor("Consultoria Híbrida")["sessoes_mes"] == 1
    assert base_motor("Consultoria Online")["sessoes_mes"] == 0
    assert base_motor("Avaliação Física")["sessoes_mes"] == 0


def test_mensalidade_usa_o_planejamento_do_mes():
    mens = base_motor("Mensalidade", freq=2)
    assert minutos_trabalho(mens, {**P, "mo": {**MO, "min_planejamento_mes": 30}}) == pytest.approx(8.66 * 60 + 30)


def test_deslocamento_do_local_e_tempo_de_trabalho():
    assert minutos_trabalho(base_motor("Pacote de Aulas", 8, local="Opfit"), P) == 8 * 90 + 60
    assert minutos_trabalho(base_motor("Pacote de Aulas", 8, local="CIA"), P) == 8 * 60 + 60


def test_consultoria_e_avaliacao_pelos_minutos():
    assert minutos_trabalho(base_motor("Consultoria Online"), P) == 150
    assert minutos_trabalho(base_motor("Consultoria Híbrida", local="Opfit"), P) == 150 + 90
    assert minutos_trabalho(base_motor("Avaliação Física", local="Opfit"), P) == 30 + 30
    r = calcular(base_motor("Consultoria Online"), P)
    assert r["custo_total"] == pytest.approx(2.5 * 53 + 2.5 * 5)
    assert r["preco_cheio"] == pytest.approx(r["custo_total"] / (1 - 0.06 - 0.30), abs=0.01)


def test_valor_hora_zero_tira_a_mao_de_obra():
    r = calcular(OP4, {**P, "mo": {**MO, "valor_hora": 0}})
    assert r["mao_obra"] == 0 and r["custo_total"] == pytest.approx(75) and r["horas"] == 7


def test_salario_automatico_nao_soma_mao_de_obra_extra_do_grupo():
    p = {**P, "salario_hora": {"usado": True}}
    assert calcular(OP4, p, pessoas=2)["mao_obra"] == pytest.approx(371)


def test_pisos_e_veredito_por_faixa():
    """Piso do negócio = custo sem pró-labore ÷ (1 − taxa); do salário = custo ÷ (1 − taxa); mínimo = com a margem."""
    p = {**P, "rateio_hora": 0, "mo": {**MO, "valor_hora": 50},
         "locais": {"X": {"taxa_aula": 25, "tempo_deslocamento": 0}}}
    base = base_motor("Pacote de Aulas", 8, local="X")    # 9 h: MO 450 + local 200
    um = calcular(base, p)
    assert um["piso_negocio"] == pytest.approx(200 / 0.94, abs=0.01)
    assert um["piso_salario"] == pytest.approx(650 / 0.94, abs=0.01)
    assert um["preco_minimo"] == pytest.approx(650 / 0.79, abs=0.01)
    faixas = {830: "fechar", 700: "so_salario", 400: "parcial", 150: "recusar"}
    for preco, v in faixas.items():
        assert calcular(base, p, preco_final=preco)["veredito"] == v
    r = calcular(base, p, preco_final=400)
    assert r["ganho_hora"] == pytest.approx((400 * 0.94 - 200) / r["horas"], abs=0.01)


# ---------- banco ----------
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


def test_margem_alvo_nasce_mínima_mais_10_e_guarda_o_que_voce_muda(tmp_path, monkeypatch):
    from app import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    db.iniciar_banco()
    con = db.conectar()
    alvo = db.parametros(con, "margem_alvo")
    assert alvo["Pacote de Aulas"] == pytest.approx(0.25) and alvo["Consultoria Híbrida"] == pytest.approx(0.32)
    with con:
        con.execute("UPDATE parametros SET valor=0.30 WHERE grupo='margem_alvo' AND chave='Pacote de Aulas'")
    con.close()
    db.iniciar_banco()
    con = db.conectar()
    assert db.parametros(con, "margem_alvo")["Pacote de Aulas"] == pytest.approx(0.30)
    con.close()
