"""Conta automática de cada local criado pelo "+ Novo local" (bug 9): as aulas Feitas lá viram uma saída em Contas a pagar,
como a da CIA. Hoje, nos testes, é segunda 02/11/2026: a competência é outubro."""
import pytest

from app import contas_auto, financeiro, locais
from tests.test_alertas import con_temp  # noqa: F401  (banco temporário)
from tests.test_contas_automaticas import HOJE, aluno, automaticas, cenario_outubro, lancar_a_mao, marca

CHAVE = "local:SmartFit:2026-10"


def local(con, nome="SmartFit", taxa_aula=20.0, extra=10.0, desloc=5.0, mensal=50.0, aulas_mes=8):
    with con:
        con.execute("""INSERT INTO locais_custos (local, taxa_aula, taxa_pessoa_extra, deslocamento, taxa_mensal, aulas_mes, referencia, modo)
                       VALUES (?,?,?,?,?,?,'CIA','margem')""", (nome, taxa_aula, extra, desloc, mensal, aulas_mes))


def cenario(con):
    """SmartFit, segunda 9h: Ana e Beto. 05/10 os dois (1 aula de 2 pessoas), 12/10 só Ana, 19/10 Beto faltou."""
    local(con)
    a, b = aluno(con, "Ana", local="SmartFit"), aluno(con, "Beto", local="SmartFit")
    marca(con, a, "2026-10-05")
    marca(con, b, "2026-10-05")
    marca(con, a, "2026-10-12")
    marca(con, a, "2026-10-19")
    marca(con, b, "2026-10-19", tipo="falta")
    return a, b


# 3 aulas × 20 + 1 pessoa a mais × 10 + taxa mensal 50. O deslocamento (combustível do personal) não é conta do local.
VALOR = 3 * 20 + 10 + 50


def test_local_mes_soma_taxa_pessoa_extra_e_taxa_mensal_uma_vez_sem_deslocamento(con_temp):
    cenario(con_temp)
    r = contas_auto.local_mes(con_temp, "SmartFit", "2026-10")
    assert (r["aulas"], r["pessoas_extra"], r["valor"]) == (3, 1, VALOR)
    assert r["texto"] == "3 aulas × R$ 20,00 + 1 pessoa a mais × R$ 10,00 + taxa mensal R$ 50,00"
    assert r["vencimento"] == "2026-11-05"


def test_cria_a_conta_do_local_com_chave_categoria_e_texto(con_temp):
    cenario(con_temp)
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == [CHAVE]
    c = automaticas(con_temp, CHAVE)[0]
    assert (c["escopo"], c["tipo"], c["pago_em"], c["data"], c["valor"]) == ("PJ", "saida", None, "2026-11-05", VALOR)
    assert c["descricao"] == "SmartFit: aulas de 10/2026" and c["categoria"] == "Aluguel"
    assert c["observacao"].startswith("3 aulas × R$ 20,00")
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []      # idempotente


def test_sem_aula_no_mes_nao_cria_nem_cobra_a_taxa_mensal(con_temp):
    local(con_temp)
    a = aluno(con_temp, "Ana", local="SmartFit")
    marca(con_temp, a, "2026-10-05", tipo="falta")
    marca(con_temp, a, "2026-11-02")                                       # aula, mas em novembro
    r = contas_auto.local_mes(con_temp, "SmartFit", "2026-10")
    assert r["valor"] == 0 and r["texto"] == "Nenhuma aula Feita em SmartFit"
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []
    assert automaticas(con_temp) == []


def test_aula_em_outro_local_nao_entra(con_temp):
    local(con_temp)
    local(con_temp, "Smart", taxa_aula=99)                                 # nome contido em outro: não mistura
    a = aluno(con_temp, "Ana", local="SmartFit")
    c = aluno(con_temp, "Caio", local="CIA")
    marca(con_temp, a, "2026-10-05")
    marca(con_temp, c, "2026-10-05")                                       # mesmo dia e hora, mas na CIA
    assert contas_auto.local_mes(con_temp, "SmartFit", "2026-10")["aulas"] == 1
    assert contas_auto.local_mes(con_temp, "Smart", "2026-10")["aulas"] == 0


def test_avulsa_no_local_conta_e_fixo_la_com_avulsa_em_outro_nao(con_temp):
    local(con_temp)
    a = aluno(con_temp, "Ana", local="CIA")
    b = aluno(con_temp, "Beto", local="SmartFit")
    with con_temp:
        con_temp.execute("INSERT INTO agenda_avulsas (cliente_id, data, hora, local, reposicao) VALUES (?, '2026-10-14', 18, 'SmartFit', 1)", (a,))
        con_temp.execute("INSERT INTO agenda_avulsas (cliente_id, data, hora, local, reposicao) VALUES (?, '2026-10-12', 9, 'CIA', 1)", (b,))
    marca(con_temp, a, "2026-10-14", hora=18)                              # reposição da Ana na SmartFit
    marca(con_temp, b, "2026-10-12")                                       # Beto foi na CIA nesse dia
    assert contas_auto.local_mes(con_temp, "SmartFit", "2026-10")["aulas"] == 1


def test_local_com_nome_de_cia_fica_de_fora(con_temp):
    local(con_temp, "Cia 111")
    local(con_temp)
    assert contas_auto.locais_com_conta(con_temp) == ["SmartFit"]


def test_lancada_a_mao_impede_a_automatica(con_temp):
    cenario(con_temp)
    lancar_a_mao(con_temp, "Aluguel smartfit outubro", "2026-11-05", categoria="Aluguel")
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []
    assert automaticas(con_temp, CHAVE) == []


def test_outra_conta_com_nome_parecido_nao_impede(con_temp):
    cenario(con_temp)
    lancar_a_mao(con_temp, "Smart TV", "2026-11-05", categoria="Aluguel")
    lancar_a_mao(con_temp, "CIA 111: aulas de 10/2026", "2026-11-05", categoria="Aluguel")
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == [CHAVE]


def test_em_aberto_e_recalculada_e_paga_nao(con_temp):
    a, b = cenario(con_temp)
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    marca(con_temp, b, "2026-10-12")                                       # Feita lançada depois: 12/10 vira dupla
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == [CHAVE]
    assert automaticas(con_temp, CHAVE)[0]["valor"] == VALOR + 10
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET pago_em='2026-11-03' WHERE auto=?", (CHAVE,))
    marca(con_temp, a, "2026-10-26")
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []
    assert automaticas(con_temp, CHAVE)[0]["valor"] == VALOR + 10


def test_recorrencia_do_local_fica_ligada_e_nao_aparece_de_novo(con_temp):
    cenario(con_temp)
    with con_temp:
        rid = con_temp.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio, conta)
                                  VALUES ('PJ','Aluguel SmartFit','Aluguel',150,5,'2026-01','Contabilizei Bank')""").lastrowid
        con_temp.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio)
                            VALUES ('PJ','Internet','Contas',100,5,'2026-01')""")
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    c = automaticas(con_temp, CHAVE)[0]
    assert (c["recorrencia_id"], c["competencia"], c["conta"]) == (rid, "2026-11", "Contabilizei Bank")
    nov = [i["descricao"] for i in financeiro.em_aberto_ate(con_temp, "2026-12-31", HOJE)
           if i["data"][:7] == "2026-11" and i["tipo"] == "saida"]
    assert "SmartFit: aulas de 10/2026" in nov and "Aluguel SmartFit" not in nov and "Internet" in nov


def test_mudar_o_local_do_horario_nao_muda_o_mes_que_passou(con_temp):
    """Ana era segunda 9h na SmartFit e passou para a CIA em 19/10: as aulas antes disso continuam na SmartFit."""
    local(con_temp)
    a = aluno(con_temp, "Ana", local="SmartFit")
    with con_temp:
        con_temp.execute("UPDATE agenda_fixos SET criado_em='2026-09-01 10:00:00', excluido_em='2026-10-19 08:00:00' WHERE cliente_id=?", (a,))
        con_temp.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, vigente_de) VALUES (?, 1, 9, 'CIA', '2026-10-19')", (a,))
    for d in ("2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26"):
        marca(con_temp, a, d)
    assert contas_auto.local_mes(con_temp, "SmartFit", "2026-10")["aulas"] == 2
    assert sum(contas_auto.cia_mes(con_temp, "2026-10")["aulas"].values()) == 2


def test_previa_mostra_o_local_com_aula(con_temp):
    cenario(con_temp)
    local(con_temp, "Vazio")
    linhas = contas_auto.previa(con_temp, "2026-10-28")
    assert f"SmartFit este mês até agora: 3 aulas = R$ {VALOR:.2f}".replace(".", ",") in linhas
    assert not any(x.startswith("Vazio") for x in linhas)
    assert linhas[-1].startswith("DAS de 10/2026")


@pytest.mark.parametrize("texto, sim", [("Aluguel SmartFit", True), ("smartfit out", True), ("SMARTFIT", True),
                                        ("Smart TV", False), ("SmartFitness", False), ("", False)])
def test_eh_do_local_casa_o_nome_inteiro(texto, sim):
    assert contas_auto.eh_do_local(texto, "SmartFit") is sim


# --- Revisão do PR: nomes parecidos, aula sem hora, acento e número de leituras ---

def rec(con, descricao, valor=150):
    with con:
        return con.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio)
                              VALUES ('PJ',?,'Aluguel',?,5,'2026-01')""", (descricao, valor)).lastrowid


def test_recorrencia_fica_com_o_local_de_nome_mais_especifico(con_temp):
    """Locais 'Smart Fit' e 'Fit': 'Aluguel Smart Fit' é do Smart Fit, e o Fit ganha a conta dele também."""
    local(con_temp, "Smart Fit")
    local(con_temp, "Fit")
    a = aluno(con_temp, "Ana", local="Smart Fit")
    b = aluno(con_temp, "Beto", local="Fit", hora=10)
    marca(con_temp, a, "2026-10-05")
    marca(con_temp, b, "2026-10-05", hora=10)
    rid = rec(con_temp, "Aluguel Smart Fit")
    feitas = contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    assert "local:Smart Fit:2026-10" in feitas and "local:Fit:2026-10" in feitas
    assert automaticas(con_temp, "local:Smart Fit:2026-10")[0]["recorrencia_id"] == rid
    assert automaticas(con_temp, "local:Fit:2026-10")[0]["recorrencia_id"] is None


def test_recorrencia_de_local_com_111_no_nome_nao_rouba_a_cia(con_temp):
    cenario_outubro(con_temp)
    local(con_temp, "Studio 111")
    s = aluno(con_temp, "Sara", local="Studio 111", hora=11)
    marca(con_temp, s, "2026-10-05", hora=11)
    rid = rec(con_temp, "Aluguel Studio 111")
    feitas = contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    assert "cia:2026-10" in feitas and "local:Studio 111:2026-10" in feitas
    assert automaticas(con_temp, "cia:2026-10")[0]["recorrencia_id"] != rid


def test_conta_a_mao_de_um_local_nao_bloqueia_outro_local(con_temp):
    local(con_temp, "Smart Fit")
    local(con_temp, "Fit")
    b = aluno(con_temp, "Beto", local="Fit")
    marca(con_temp, b, "2026-10-05")
    lancar_a_mao(con_temp, "Aluguel Smart Fit outubro", "2026-11-05", categoria="Aluguel")
    assert "local:Fit:2026-10" in contas_auto.gerar_contas_automaticas(con_temp, HOJE)


def test_conta_a_mao_do_local_com_111_nao_bloqueia_a_cia(con_temp):
    cenario_outubro(con_temp)
    local(con_temp, "Studio 111")
    lancar_a_mao(con_temp, "Studio 111 outubro", "2026-11-05", categoria="Aluguel")
    assert "cia:2026-10" in contas_auto.gerar_contas_automaticas(con_temp, HOJE)


def test_gasto_de_transporte_com_o_nome_do_local_nao_bloqueia(con_temp):
    cenario(con_temp)
    lancar_a_mao(con_temp, "Gasolina SmartFit", "2026-11-05", categoria="Transporte")
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == [CHAVE]


def test_aula_sem_hora_com_dois_horarios_no_dia_conta_uma_vez_no_primeiro(con_temp):
    """Ana: seg 9h CIA e seg 18h SmartFit. Aula pela ficha (sem hora) em 05/10: conta uma vez, na CIA (9h)."""
    local(con_temp)
    a = aluno(con_temp, "Ana", local="CIA")
    with con_temp:
        con_temp.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?, 1, 18, 'SmartFit')", (a,))
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, hora) VALUES (?, 'aula', '2026-10-05', NULL)", (a,))
    assert contas_auto.local_mes(con_temp, "SmartFit", "2026-10")["aulas"] == 0
    assert sum(contas_auto.cia_mes(con_temp, "2026-10")["aulas"].values()) == 1


def test_aula_sem_hora_em_dado_antigo_conta_uma_vez(con_temp):
    """Antes do vigente_de, trocar a hora excluía a linha velha e criava outra com vigente_de NULL."""
    local(con_temp)
    a = aluno(con_temp, "Ana", local="SmartFit")
    with con_temp:
        con_temp.execute("UPDATE agenda_fixos SET criado_em='2026-09-01 10:00:00', excluido_em='2026-10-19 08:00:00' WHERE cliente_id=?", (a,))
        con_temp.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, criado_em) VALUES (?, 1, 10, 'CIA', '2026-10-19 08:00:00')", (a,))
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, hora) VALUES (?, 'aula', '2026-10-05', NULL)", (a,))
    sf = contas_auto.local_mes(con_temp, "SmartFit", "2026-10")["aulas"]
    cia = sum(contas_auto.cia_mes(con_temp, "2026-10")["aulas"].values())
    assert sf + cia == 1


def test_nomes_que_so_mudam_no_acento_sao_o_mesmo_local(con_temp):
    locais.criar_local(con_temp, "Academia", taxa_aula=20)
    with pytest.raises(ValueError):
        locais.criar_local(con_temp, "Acadêmia", taxa_aula=20)
    local(con_temp, "ACADÊMIA")                                            # dado antigo, gravado direto
    assert contas_auto.locais_com_conta(con_temp) == ["Academia"]


def test_leituras_nao_crescem_com_o_numero_de_locais(con_temp):
    def contar(k):
        for i in range(k):
            local(con_temp, f"Local{k}x{i}")
        n = [0]
        con_temp.set_trace_callback(lambda s: n.__setitem__(0, n[0] + 1))
        contas_auto.gerar_contas_automaticas(con_temp, HOJE)
        contas_auto.previa(con_temp, "2026-11-03")
        con_temp.set_trace_callback(None)
        return n[0]
    um = contar(1)
    assert contar(6) <= um + 2                                              # 7 locais custam o mesmo que 1
