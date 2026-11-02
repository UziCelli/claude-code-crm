"""DAS pela tabela do Simples (Anexo III) e as contas automáticas (DAS e CIA do mês anterior) em Contas a pagar.
Datas fixas: nenhum teste depende do dia em que roda. Hoje, nos testes, é segunda 02/11/2026: a competência é outubro."""
import pytest

from app import assistente, contas_auto, db, financeiro, main, precos
from tests.test_alertas import con_temp  # noqa: F401  (banco temporário)
from tests.test_alertas_acao import congelar, http  # noqa: F401  (hoje congelado no main; cliente HTTP do mesmo banco)

HOJE = "2026-11-02"
MENSALIDADE = "Mensalidade (Aulas Presenciais)"


# ---------- montagem ----------
def entrada(con, valor, pago_em, categoria=MENSALIDADE, pago=True):
    with con:
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria) VALUES ('PJ','entrada',?,?,?,?)",
                    (pago_em, pago_em if pago else None, valor, categoria))


def meses(de, ate):
    m = de
    while m <= ate:
        yield m
        m = financeiro.somar_meses(m, 1)


def receita_mensal(con, valor, de, ate):
    for m in meses(de, ate):
        entrada(con, valor, f"{m}-10")


def aluno(con, nome, local="CIA", dia=1, hora=9):
    with con:
        cid = con.execute("INSERT INTO clientes (nome, status) VALUES (?, 'ativo')", (nome,)).lastrowid
        con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?,?,?,?)", (cid, dia, hora, local))
    return cid


def marca(con, cid, data, tipo="aula", hora=9):
    with con:
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, hora) VALUES (?,?,?,?)", (cid, tipo, data, hora))


def automaticas(con, chave=None):
    sql = "SELECT * FROM lancamentos WHERE auto IS NOT NULL" + (" AND auto=?" if chave else "") + " ORDER BY auto"
    return con.execute(sql, (chave,) if chave else ()).fetchall()


def lancar_a_mao(con, descricao, data, categoria="Impostos/Taxas", pago_em=None):
    with con:
        return con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao) VALUES ('PJ','saida',?,?,?,?,?)",
                           (data, pago_em, 123.45, categoria, descricao)).lastrowid


def cenario_outubro(con):
    """Primeira receita em outubro/2026 (R$ 8.000): DAS = 6% × 8.000 = 480. CIA: 2 aulas de 1 pessoa e 1 de 2 pessoas."""
    entrada(con, 8000, "2026-10-10")
    a, b = aluno(con, "Ana"), aluno(con, "Beto")
    marca(con, a, "2026-10-05")
    marca(con, a, "2026-10-12")
    marca(con, a, "2026-10-19")
    marca(con, b, "2026-10-19")
    return a, b


# ---------- tabela do Simples ----------
@pytest.mark.parametrize("rbt12, faixa", [(0, 1), (180_000, 1), (180_000.01, 2), (360_000, 2), (720_000, 3), (720_000.01, 4),
                                          (1_800_000, 4), (3_600_000, 5), (4_800_000, 6), (6_000_000, 6)])
def test_faixas_e_aliquota_efetiva(con_temp, monkeypatch, rbt12, faixa):
    monkeypatch.setattr(financeiro, "_rbt12", lambda con, mes: (rbt12, "12 meses", 12))
    d = financeiro.das_competencia(con_temp, "2026-10")
    _, nominal, deducao = financeiro.SIMPLES_ANEXO_III[faixa - 1]
    assert d["faixa"] == faixa and d["nominal"] == nominal and d["deducao"] == deducao
    assert d["efetiva"] == pytest.approx((rbt12 * nominal - deducao) / rbt12 if rbt12 else 0.06)


def test_faixa_1_e_6_por_cento_e_faixa_2_desconta_a_parcela(con_temp, monkeypatch):
    monkeypatch.setattr(financeiro, "_rbt12", lambda con, mes: (96_000, "12 meses", 12))
    assert financeiro.das_competencia(con_temp, "2026-10")["efetiva"] == pytest.approx(0.06)
    monkeypatch.setattr(financeiro, "_rbt12", lambda con, mes: (240_000, "12 meses", 12))
    d = financeiro.das_competencia(con_temp, "2026-10")
    assert d["faixa"] == 2 and d["efetiva"] == pytest.approx(0.073)   # (240.000 × 11,2% − 9.360) / 240.000
    assert financeiro.texto_pct(d["efetiva"]) == "7,3"


def test_rbt12_soma_os_12_meses_anteriores_e_explica(con_temp):
    receita_mensal(con_temp, 8000, "2025-10", "2026-10")                      # 12 meses anteriores a outubro + o próprio outubro
    entrada(con_temp, 99999, "2025-09-10")                                    # fora da janela (13 meses antes)
    entrada(con_temp, 5000, "2026-05-10", categoria=financeiro.EMPRESTIMO)    # empréstimo não é receita
    entrada(con_temp, 5000, "2026-06-10", pago=False)                         # em aberto não entrou
    d = financeiro.das_competencia(con_temp, "2026-10")
    assert d["rbt12"] == 96000 and d["base"] == "12 meses" and d["faixa"] == 1
    assert d["receita"] == 8000 and d["valor"] == 480 and d["vencimento"] == "2026-11-20"
    assert financeiro.explicacao_das(d) == ("6% (tabela do Simples, faixa 1; R$ 96.000,00 nos últimos 12 meses) "
                                            "× R$ 8.000,00 recebidos em 10/2026")


def test_rbt12_no_inicio_da_atividade_usa_media_e_primeiro_mes(con_temp):
    # sem receita nenhuma: faixa 1, nada a pagar
    d = financeiro.das_competencia(con_temp, "2026-10")
    assert d["base"] == "sem receita" and d["rbt12"] == 0 and d["efetiva"] == 0.06 and d["valor"] == 0
    # primeiro mês: a receita do próprio mês × 12
    entrada(con_temp, 10000, "2026-10-10")
    d = financeiro.das_competencia(con_temp, "2026-10")
    assert d["base"] == "primeiro" and d["rbt12"] == 120000 and d["valor"] == 600
    # menos de 12 meses: média dos meses anteriores × 12 (agosto 20 mil e setembro 40 mil: média 30 mil = 360 mil por ano)
    entrada(con_temp, 20000, "2026-08-10")
    entrada(con_temp, 40000, "2026-09-10")
    d = financeiro.das_competencia(con_temp, "2026-10")
    assert d["base"] == "media" and d["meses_base"] == 2 and d["rbt12"] == 360000 and d["faixa"] == 2
    assert d["efetiva"] == pytest.approx(0.112 - 9360 / 360000) and d["valor"] == 860
    assert "média dos 2 meses anteriores × 12" in financeiro.explicacao_das(d)
    # a competência anterior ao primeiro mês com receita não tem o que cobrar
    assert financeiro.das_competencia(con_temp, "2026-07")["base"] == "sem receita"


def test_pct_das_e_a_aliquota_efetiva_do_mes_de_hoje_e_alimenta_aviso_e_imposto(con_temp):
    receita_mensal(con_temp, 20000, "2025-11", "2026-10")   # 240 mil em 12 meses: faixa 2, 7,3%
    assert financeiro.pct_das(con_temp, HOJE) == pytest.approx(0.073)
    assert financeiro.das_competencia(con_temp, "2026-11")["rbt12"] == 240000
    assert financeiro.aviso_imposto(con_temp, 1000, HOJE) == "Separe R$ 73,00 para o imposto (DAS 7,3%)."
    assert financeiro.imposto_mes(con_temp, "2026-10", HOJE) == round(20000 * financeiro.das_competencia(con_temp, "2026-10")["efetiva"], 2)


def test_precos_usa_a_mesma_aliquota_e_as_taxas_da_cia(con_temp, monkeypatch):
    monkeypatch.setattr(financeiro, "pct_das", lambda con, hoje=None: 0.0731)
    p = precos.carregar_parametros(con_temp)
    assert p["das"] == 0.0731 and p["taxa_cia"] == {1: 70.76, 2: 99.69, 3: 151.47} and p["cia_max"] == 3


# ---------- vencimentos ----------
def test_vencimento_do_das_antecipa_fim_de_semana(con_temp):
    venc = lambda comp: financeiro.das_competencia(con_temp, comp)["vencimento"]   # noqa: E731
    assert venc("2026-10") == "2026-11-20"   # sexta
    assert venc("2026-11") == "2026-12-18"   # dia 20 é domingo
    assert venc("2027-02") == "2027-03-19"   # dia 20 é sábado
    assert venc("2026-12") == "2027-01-20"   # quarta


def test_vencimento_da_cia_padrao_dia_5_antecipa_fim_de_semana_e_e_configuravel(con_temp):
    assert db.parametros(con_temp, "contas_auto")["dia_cia"] == 5
    venc = lambda comp: contas_auto.cia_mes(con_temp, comp)["vencimento"]   # noqa: E731
    assert venc("2026-10") == "2026-11-05"   # quinta
    assert venc("2026-11") == "2026-12-04"   # dia 5 é sábado
    assert venc("2026-06") == "2026-07-03"   # dia 5 é domingo
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=12 WHERE grupo='contas_auto' AND chave='dia_cia'")
    assert venc("2026-10") == "2026-11-12"


# ---------- CIA ----------
def test_cia_dupla_faltou_outro_local_e_acima_do_maximo(con_temp):
    a, b, c, d = (aluno(con_temp, n, hora=9) for n in "ABCD")
    smart = aluno(con_temp, "Smart", local="SmartFit", hora=10)
    e = aluno(con_temp, "Elisa", local="Cia Norte", dia=2, hora=7)   # "começa com CIA", sem diferenciar maiúsculas
    marca(con_temp, a, "2026-10-05")
    marca(con_temp, b, "2026-10-05")                                  # dupla: UMA aula de 2 pessoas
    marca(con_temp, a, "2026-10-12")                                  # 1 pessoa
    marca(con_temp, a, "2026-10-19")
    marca(con_temp, b, "2026-10-19", tipo="falta")                    # Faltou não conta: 1 pessoa
    for x in (a, b, c, d):
        marca(con_temp, x, "2026-10-26")                              # 4 pessoas: vale a taxa do máximo (3)
    marca(con_temp, smart, "2026-10-05", hora=10)                     # outro local
    marca(con_temp, e, "2026-10-13", hora=7)                          # local "Cia Norte": conta
    marca(con_temp, a, "2026-09-28")
    marca(con_temp, a, "2026-11-02")                                  # fora do mês
    marca(con_temp, c, "2026-10-12", tipo="desmarcou")
    marca(con_temp, c, "2026-10-19", tipo="cancelada")
    with con_temp:   # aula lançada pela ficha (sem hora) no mesmo dia da dupla: não vira uma 3ª pessoa nem outra aula
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', '2026-10-05')", (a,))
    r = contas_auto.cia_mes(con_temp, "2026-10")
    assert r["aulas"] == {1: 3, 2: 1, 3: 1}
    assert r["valor"] == pytest.approx(3 * 70.76 + 99.69 + 151.47)
    assert r["texto"] == "3 aulas de 1 pessoa × R$ 70,76 + 1 de 2 pessoas × R$ 99,69 + 1 de 3 pessoas × R$ 151,47"
    assert r["mes"] == "2026-10" and r["vencimento"] == "2026-11-05"


def test_cia_local_da_avulsa_vale_e_aula_da_ficha_usa_o_horario_dele_na_cia(con_temp):
    a = aluno(con_temp, "Ana", local="SmartFit")                       # fixo fora da CIA
    with con_temp:
        con_temp.execute("INSERT INTO agenda_avulsas (cliente_id, data, hora, local, reposicao) VALUES (?, '2026-10-14', 18, 'CIA', 1)", (a,))
    marca(con_temp, a, "2026-10-14", hora=18)                         # a reposição foi na CIA
    marca(con_temp, a, "2026-10-12", hora=9)                          # o horário fixo é na SmartFit
    b = aluno(con_temp, "Beto")
    with con_temp:
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', '2026-10-05')", (b,))   # ficha: segunda 9h na CIA
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', '2026-10-06')", (b,))   # terça: sem horário
    assert contas_auto.cia_mes(con_temp, "2026-10")["aulas"] == {1: 2, 2: 0, 3: 0}


def test_cia_sem_aula_tem_texto_e_valor_zero(con_temp):
    r = contas_auto.cia_mes(con_temp, "2026-10")
    assert r["valor"] == 0 and r["aulas"] == {1: 0, 2: 0, 3: 0} and "Nenhuma aula" in r["texto"]


# ---------- gerar_contas_automaticas ----------
def test_cria_o_das_e_a_cia_do_mes_anterior_uma_vez_so(con_temp):
    cenario_outubro(con_temp)
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == ["das:2026-10", "cia:2026-10"]
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []     # idempotente
    das, cia = automaticas(con_temp, "das:2026-10")[0], automaticas(con_temp, "cia:2026-10")[0]
    assert (das["escopo"], das["tipo"], das["pago_em"], das["data"], das["valor"]) == ("PJ", "saida", None, "2026-11-20", 480)
    assert das["descricao"] == "DAS 10/2026 (Simples)" and financeiro.eh_das(das["descricao"], das["categoria"])
    assert das["observacao"].startswith("6% (tabela do Simples, faixa 1;")
    assert (cia["escopo"], cia["tipo"], cia["pago_em"], cia["data"]) == ("PJ", "saida", None, "2026-11-05")
    assert cia["valor"] == pytest.approx(2 * 70.76 + 99.69) and cia["descricao"] == "CIA 111: aulas de 10/2026"
    assert cia["categoria"] == "Aluguel" and cia["categoria"] in db.lista(con_temp, "lista_categorias_pj")
    assert cia["observacao"] == "2 aulas de 1 pessoa × R$ 70,76 + 1 de 2 pessoas × R$ 99,69"
    assert len(automaticas(con_temp)) == 2


def test_indice_unico_do_auto_evita_duplicar_entre_o_pc_e_o_servidor(con_temp):
    sql = "INSERT OR IGNORE INTO lancamentos (escopo, tipo, data, valor, categoria, auto) VALUES ('PJ','saida','2026-11-20',10,'Outros',?)"
    with con_temp:
        a = con_temp.execute(sql, ("das:2026-10",)).rowcount
        b = con_temp.execute(sql, ("das:2026-10",)).rowcount
        con_temp.execute(sql, (None,))
        con_temp.execute(sql, (None,))                                  # lançados à mão (NULL) podem repetir
    assert (a, b) == (1, 0) and len(automaticas(con_temp)) == 1
    assert con_temp.execute("SELECT COUNT(*) FROM lancamentos WHERE auto IS NULL").fetchone()[0] == 2


def test_banco_antigo_ganha_a_coluna_auto_e_o_indice(tmp_path, monkeypatch):
    caminho = tmp_path / "antigo.db"
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    with con:
        con.execute("DROP INDEX idx_lancamentos_auto")
        con.execute("ALTER TABLE lancamentos DROP COLUMN auto")
    db.iniciar_banco(caminho)
    assert "auto" in {r[1] for r in con.execute("PRAGMA table_info(lancamentos)")}
    assert con.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_lancamentos_auto'").fetchone()
    con.close()


def test_valor_zero_nao_cria(con_temp):
    a = aluno(con_temp, "Ana")
    marca(con_temp, a, "2026-10-05", tipo="falta")                 # só Faltou: sem aula Feita
    entrada(con_temp, 3000, "2026-09-10")                          # receita só em setembro: outubro não recebeu nada
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []
    assert automaticas(con_temp) == []


def test_so_cria_a_competencia_do_mes_anterior_a_hoje(con_temp):
    cenario_outubro(con_temp)
    assert contas_auto.gerar_contas_automaticas(con_temp, "2026-10-20") == []   # em outubro a competência é setembro: sem receita nem aula
    assert contas_auto.gerar_contas_automaticas(con_temp, "2026-12-01") == []   # em dezembro, novembro: nada
    assert automaticas(con_temp) == []


def test_excluido_nao_volta(con_temp):
    cenario_outubro(con_temp)
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET excluido_em=datetime('now') WHERE auto='das:2026-10'")
    entrada(con_temp, 1000, "2026-10-20")                          # mesmo com novo recebimento
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []
    assert con_temp.execute("SELECT COUNT(*) FROM lancamentos WHERE auto='das:2026-10'").fetchone()[0] == 1
    assert con_temp.execute("SELECT COUNT(*) FROM lancamentos WHERE auto='das:2026-10' AND excluido_em IS NULL").fetchone()[0] == 0
    assert not [x for x in financeiro.em_aberto_ate(con_temp, "2026-12-31", HOJE) if financeiro.eh_das(x["descricao"], x["categoria"])]


def test_em_aberto_e_recalculado_quando_o_valor_muda(con_temp):
    a, b = cenario_outubro(con_temp)
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    entrada(con_temp, 2000, "2026-10-28")                          # entrada lançada atrasada
    marca(con_temp, b, "2026-10-26")                               # aula marcada Feita depois
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == ["das:2026-10", "cia:2026-10"]
    das, cia = automaticas(con_temp, "das:2026-10")[0], automaticas(con_temp, "cia:2026-10")[0]
    assert das["valor"] == 600 and "R$ 10.000,00 recebidos em 10/2026" in das["observacao"]
    assert cia["valor"] == pytest.approx(3 * 70.76 + 99.69) and cia["observacao"].startswith("3 aulas de 1 pessoa")
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []
    assert len(automaticas(con_temp)) == 2


def test_pago_nao_e_recalculado(con_temp):
    cenario_outubro(con_temp)
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET pago_em='2026-11-03' WHERE auto IS NOT NULL")
    entrada(con_temp, 2000, "2026-10-28")
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []
    assert automaticas(con_temp, "das:2026-10")[0]["valor"] == 480


def test_editado_a_mao_pela_tela_nao_e_mais_recalculado(con_temp, http, monkeypatch):
    cenario_outubro(con_temp)
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    congelar(monkeypatch, HOJE)
    das = automaticas(con_temp, "das:2026-10")[0]
    r = http.post("/financeiro/lancamento", data={"id": das["id"], "escopo": "PJ", "tipo": "saida", "data": "2026-11-20", "valor": "500,00",
                                                  "categoria": "Impostos/Taxas", "descricao": "DAS 10/2026 (Simples)"}, follow_redirects=False)
    assert r.status_code == 303
    editado = con_temp.execute("SELECT * FROM lancamentos WHERE id=?", (das["id"],)).fetchone()
    assert editado["auto"] is None and editado["valor"] == 500
    entrada(con_temp, 2000, "2026-10-28")
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    assert con_temp.execute("SELECT valor FROM lancamentos WHERE id=?", (das["id"],)).fetchone()[0] == 500
    assert con_temp.execute("SELECT COUNT(*) FROM lancamentos WHERE descricao LIKE 'DAS%'").fetchone()[0] == 1   # e não nasce outro DAS


def test_editado_pelo_assistente_tambem_deixa_de_ser_automatico(con_temp):
    a, _ = cenario_outubro(con_temp)
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    cia = automaticas(con_temp, "cia:2026-10")[0]
    assistente._editar_lancamento(con_temp, {"id": cia["id"], "valor": 300})
    editado = con_temp.execute("SELECT auto, valor FROM lancamentos WHERE id=?", (cia["id"],)).fetchone()
    assert editado["auto"] is None and editado["valor"] == 300
    marca(con_temp, a, "2026-10-26")
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    assert con_temp.execute("SELECT COUNT(*) FROM lancamentos WHERE descricao LIKE 'CIA%'").fetchone()[0] == 1


# ---------- não duplicar ----------
@pytest.mark.parametrize("pago_em", [None, "2026-11-19"])
def test_das_lancado_a_mao_impede_o_automatico(con_temp, pago_em):
    cenario_outubro(con_temp)
    lancar_a_mao(con_temp, "DAS 10/2026", "2026-11-20", pago_em=pago_em)
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == ["cia:2026-10"]
    assert automaticas(con_temp, "das:2026-10") == []


def test_cia_lancada_a_mao_impede_o_automatico(con_temp):
    cenario_outubro(con_temp)
    lancar_a_mao(con_temp, "Aulas CIA outubro", "2026-11-05", categoria="Aluguel")
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == ["das:2026-10"]
    assert automaticas(con_temp, "cia:2026-10") == []


def test_outra_saida_no_mes_nao_impede(con_temp):
    cenario_outubro(con_temp)
    lancar_a_mao(con_temp, "DARF", "2026-11-20")                       # imposto, mas não é o DAS
    lancar_a_mao(con_temp, "Material de treino", "2026-11-05", categoria="Material de Trabalho")
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == ["das:2026-10", "cia:2026-10"]


def test_recorrencia_de_das_e_da_cia_ficam_ligadas_e_nao_aparecem_de_novo(con_temp):
    cenario_outubro(con_temp)
    with con_temp:
        r_das = con_temp.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio)
                                    VALUES ('PJ','DAS','Impostos/Taxas',500,20,'2026-01')""").lastrowid
        r_cia = con_temp.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio, conta)
                                    VALUES ('PJ','Aulas na CIA','Aluguel',400,5,'2026-01','Contabilizei Bank')""").lastrowid
    antes = [i["descricao"] for i in financeiro.em_aberto_ate(con_temp, "2026-12-31", HOJE)
             if i["origem"] == "recorrencia" and i["competencia"] == "2026-11"]
    assert sorted(antes) == ["Aulas na CIA", "DAS"]
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    das, cia = automaticas(con_temp, "das:2026-10")[0], automaticas(con_temp, "cia:2026-10")[0]
    assert (das["recorrencia_id"], das["competencia"]) == (r_das, "2026-11")
    assert (cia["recorrencia_id"], cia["competencia"], cia["conta"]) == (r_cia, "2026-11", "Contabilizei Bank")
    aberto = financeiro.em_aberto_ate(con_temp, "2026-12-31", HOJE)
    nov = [i for i in aberto if i["data"][:7] == "2026-11" and i["tipo"] == "saida"]
    assert sorted((i["origem"], i["descricao"]) for i in nov) == [("lancamento", "CIA 111: aulas de 10/2026"),
                                                                   ("lancamento", "DAS 10/2026 (Simples)")]
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []     # e rodar de novo não duplica nada


def test_recorrencia_ja_baixada_no_mes_impede_o_automatico(con_temp):
    cenario_outubro(con_temp)
    with con_temp:
        rid = con_temp.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio)
                                  VALUES ('PJ','Aulas na CIA','Aluguel',400,5,'2026-01')""").lastrowid
    financeiro.baixar_recorrencia(con_temp, rid, "2026-11", 350, "2026-11-02")
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == ["das:2026-10"]


def test_guardar_o_das_sai_do_a_guardar_quando_o_automatico_e_lancado(con_temp):
    cenario_outubro(con_temp)
    assert financeiro.imposto_mes(con_temp, "2026-10", HOJE) == 480
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    assert financeiro.imposto_mes(con_temp, "2026-10", HOJE) == 0
    financeiro.salvar_saldos(con_temp, HOJE, {"Contabilizei Bank": 5000}, {"Contabilizei Bank": "PJ"})
    pj = financeiro.saldo_livre(con_temp, HOJE)["PJ"]
    assert pj["imposto"] == 0 and pj["comprometido"] >= 480        # o DAS está em Contas a pagar, não duas vezes


# ---------- a automática substitui a recorrência do mês ----------
def recorrencia(con, descricao, categoria="Aluguel", fixo=0, dia=5, inicio="2026-01", fim=None, excluida=False):
    with con:
        return con.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, conta, inicio, fim, excluido_em)
                              VALUES ('PJ',?,?,400,?,?,'Contabilizei Bank',?,?,?)""",
                           (descricao, categoria, dia, fixo, inicio, fim, "2026-10-01" if excluida else None)).lastrowid


def virtuais_novembro(con, rid=None):
    """Itens virtuais (recorrências sem lançamento) de novembro/2026, só os da recorrência `rid` se vier."""
    return [i for i in financeiro._recorrencias_abertas(con, "2026-11", HOJE) if rid is None or i["id"] == rid]


def eh_conta_cia(item):
    return contas_auto.eh_cia(item["descricao"])


def eh_conta_das(item):
    return financeiro.eh_das(item["descricao"], item["categoria"])


def contas_de_novembro(con, quem):
    """Itens em aberto de novembro/2026 (lançamentos e virtuais) que `quem` reconhece."""
    return [i for i in financeiro.em_aberto_ate(con, "2026-12-31", HOJE) if i["data"][:7] == "2026-11" and quem(i)]


def lixeira(con, rid, descricao="Crédito de aulas"):
    """Baixa da recorrência em novembro que foi para a lixeira: ainda ocupa a vaga (UNIQUE)."""
    with con:
        return con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, recorrencia_id, competencia, excluido_em)
                              VALUES ('PJ','saida','2026-11-05','2026-11-05',90,'Aluguel',?,?,'2026-11',datetime('now'))""",
                           (descricao, rid)).lastrowid


@pytest.mark.parametrize("texto", ["CIA", "Cia Fit", "Academia Cia Fit", "CIA 111", "111", "Crédito de aulas", "Créditos de aula",
                                   "credito das aulas", "CRÉDITOS DAS AULAS", "Aulas na CIA"])
def test_eh_cia_reconhece_as_variacoes(texto):
    assert contas_auto.eh_cia(texto)


def test_eh_cia_nao_reconhece_outra_conta():
    assert not contas_auto.eh_cia("Internet") and not contas_auto.eh_cia(None)


@pytest.mark.parametrize("descricao, categoria", [("DAS", "Impostos/Taxas"), ("Das Simples", "Impostos/Taxas"),
                                                  ("Simples Nacional", "Outros"), ("DAS", "Outros")])
@pytest.mark.parametrize("fixo", [0, 1])
def test_recorrencia_do_das_casa_fixa_ou_variavel(con_temp, descricao, categoria, fixo):
    rid = recorrencia(con_temp, descricao, categoria, fixo=fixo, dia=20)
    assert contas_auto._recorrencia(con_temp, "das", "2026-11")["id"] == rid
    assert contas_auto._recorrencia(con_temp, "cia", "2026-11") is None


@pytest.mark.parametrize("descricao", ["Crédito de aulas", "Créditos de aula", "CIA 111", "credito das aulas"])
@pytest.mark.parametrize("fixo", [0, 1])
def test_recorrencia_da_cia_casa_fixa_ou_variavel(con_temp, descricao, fixo):
    rid = recorrencia(con_temp, descricao, fixo=fixo)
    assert contas_auto._recorrencia(con_temp, "cia", "2026-11")["id"] == rid
    assert contas_auto._recorrencia(con_temp, "das", "2026-11") is None


def test_recorrencia_internet_nao_e_a_cia(con_temp):
    recorrencia(con_temp, "Internet", "Despesas Fixas")
    assert contas_auto._recorrencia(con_temp, "cia", "2026-11") is None


def test_recorrencia_credito_de_aulas_vira_a_conta_da_cia_do_mes(con_temp):
    cenario_outubro(con_temp)
    rid = recorrencia(con_temp, "Crédito de aulas")
    assert virtuais_novembro(con_temp, rid)                                           # antes: só o item virtual
    assert "cia:2026-10" in contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    cia = automaticas(con_temp, "cia:2026-10")[0]
    assert (cia["recorrencia_id"], cia["competencia"], cia["conta"]) == (rid, "2026-11", "Contabilizei Bank")
    assert virtuais_novembro(con_temp, rid) == []
    contas = contas_de_novembro(con_temp, eh_conta_cia)
    assert [(c["origem"], c["id"]) for c in contas] == [("lancamento", cia["id"])]     # exatamente 1 conta da CIA a pagar


def test_recorrencia_das_variavel_vira_o_das_do_mes(con_temp):
    cenario_outubro(con_temp)
    rid = recorrencia(con_temp, "DAS", "Impostos/Taxas", dia=20)
    assert virtuais_novembro(con_temp, rid)
    assert "das:2026-10" in contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    das = automaticas(con_temp, "das:2026-10")[0]
    assert (das["recorrencia_id"], das["competencia"]) == (rid, "2026-11")
    assert virtuais_novembro(con_temp, rid) == []
    assert [c["id"] for c in contas_de_novembro(con_temp, eh_conta_das)] == [das["id"]]


def test_pulo_do_mes_nao_impede_a_automatica(con_temp):
    cenario_outubro(con_temp)
    rid = recorrencia(con_temp, "Crédito de aulas")
    with con_temp:
        con_temp.execute("INSERT INTO recorrencia_pulos (recorrencia_id, competencia) VALUES (?, '2026-11')", (rid,))
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    assert automaticas(con_temp, "cia:2026-10")[0]["recorrencia_id"] == rid


def test_vaga_com_linha_na_lixeira_e_solta_e_a_automatica_nasce_ligada(con_temp):
    cenario_outubro(con_temp)
    rid = recorrencia(con_temp, "Crédito de aulas")
    velha = lixeira(con_temp, rid)
    assert "cia:2026-10" in contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    cia = automaticas(con_temp, "cia:2026-10")[0]
    assert (cia["recorrencia_id"], cia["competencia"]) == (rid, "2026-11")
    lix = con_temp.execute("SELECT recorrencia_id, competencia, excluido_em FROM lancamentos WHERE id=?", (velha,)).fetchone()
    assert lix["recorrencia_id"] is None and lix["competencia"] is None and lix["excluido_em"] is not None
    assert virtuais_novembro(con_temp, rid) == []


@pytest.mark.parametrize("pago_em", [None, "2026-11-01"])
def test_baixa_ativa_feita_a_mao_na_vaga_nao_cria_a_automatica(con_temp, pago_em):
    cenario_outubro(con_temp)
    rid = recorrencia(con_temp, "Crédito de aulas")
    with con_temp:
        con_temp.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, recorrencia_id, competencia)
                            VALUES ('PJ','saida','2026-11-05',?,350,'Aluguel','Boleto do espaço',?,'2026-11')""", (pago_em, rid))
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == ["das:2026-10"]
    assert automaticas(con_temp, "cia:2026-10") == []
    assert len([i for i in financeiro.em_aberto_ate(con_temp, "2026-12-31", HOJE)
                if i["data"][:7] == "2026-11" and i["categoria"] == "Aluguel"]) == (1 if pago_em is None else 0)
    assert virtuais_novembro(con_temp, rid) == []


def test_automatica_antiga_sem_vinculo_e_ligada_no_recalculo(con_temp):
    cenario_outubro(con_temp)
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)             # a versão antiga: criada sem recorrência
    rid = recorrencia(con_temp, "Crédito de aulas")                  # o usuário já tinha a recorrência
    antiga = automaticas(con_temp, "cia:2026-10")[0]
    assert antiga["recorrencia_id"] is None and virtuais_novembro(con_temp, rid)   # duplicidade
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == ["cia:2026-10"]    # valor e descrição não mudaram: só liga
    cia = automaticas(con_temp, "cia:2026-10")[0]
    assert (cia["id"], cia["recorrencia_id"], cia["competencia"]) == (antiga["id"], rid, "2026-11")
    assert cia["valor"] == antiga["valor"] and cia["auto"] == "cia:2026-10"
    assert virtuais_novembro(con_temp, rid) == []
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []


def test_automatica_antiga_paga_e_ligada_e_vaga_da_lixeira_e_solta(con_temp):
    cenario_outubro(con_temp)
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    with con_temp:
        con_temp.execute("UPDATE lancamentos SET pago_em='2026-11-04' WHERE auto='cia:2026-10'")
    rid = recorrencia(con_temp, "Crédito de aulas")
    velha = lixeira(con_temp, rid)
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == ["cia:2026-10"]
    cia = automaticas(con_temp, "cia:2026-10")[0]
    assert (cia["recorrencia_id"], cia["pago_em"]) == (rid, "2026-11-04")
    assert con_temp.execute("SELECT recorrencia_id FROM lancamentos WHERE id=?", (velha,)).fetchone()[0] is None
    assert virtuais_novembro(con_temp, rid) == []


def test_automatica_antiga_nao_liga_se_a_vaga_tem_baixa_ativa(con_temp):
    cenario_outubro(con_temp)
    contas_auto.gerar_contas_automaticas(con_temp, HOJE)
    rid = recorrencia(con_temp, "Crédito de aulas")
    with con_temp:
        con_temp.execute("""INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, descricao, recorrencia_id, competencia)
                            VALUES ('PJ','saida','2026-11-05',350,'Aluguel','Boleto do espaço',?,'2026-11')""", (rid,))
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []
    assert automaticas(con_temp, "cia:2026-10")[0]["recorrencia_id"] is None


@pytest.mark.parametrize("encerrada", ["excluida", "fim"])
def test_recorrencia_excluida_ou_encerrada_e_ignorada(con_temp, encerrada):
    cenario_outubro(con_temp)
    rid = recorrencia(con_temp, "Crédito de aulas", excluida=encerrada == "excluida", fim="2026-10" if encerrada == "fim" else None)
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == ["das:2026-10", "cia:2026-10"]
    cia = automaticas(con_temp, "cia:2026-10")[0]
    assert cia["recorrencia_id"] is None and cia["competencia"] is None
    assert virtuais_novembro(con_temp, rid) == []
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []


def test_rodar_duas_vezes_continua_com_uma_conta(con_temp):
    cenario_outubro(con_temp)
    recorrencia(con_temp, "Crédito de aulas")
    recorrencia(con_temp, "DAS", "Impostos/Taxas", dia=20)
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == ["das:2026-10", "cia:2026-10"]
    assert contas_auto.gerar_contas_automaticas(con_temp, HOJE) == []
    assert con_temp.execute("SELECT COUNT(*) FROM lancamentos WHERE auto='cia:2026-10'").fetchone()[0] == 1
    assert len(contas_de_novembro(con_temp, eh_conta_cia)) == 1
    assert len(contas_de_novembro(con_temp, eh_conta_das)) == 1


# ---------- telas ----------
def test_configuracoes_mostra_a_linha_do_simples_e_nao_tem_o_campo_fixo(con_temp, http, monkeypatch):
    congelar(monkeypatch, HOJE)
    receita_mensal(con_temp, 8000, "2025-11", "2026-10")
    pg = http.get("/configuracoes").text
    assert "DAS pela tabela do Simples (Anexo III): alíquota efetiva hoje 6% (faturamento dos últimos 12 meses: R$ 96.000,00)." in pg
    assert 'id="cfg-imposto"' not in pg and "Imposto (DAS)</h2>" in pg   # só o bloco de leitura
    assert 'id="cfg-contas_auto"' in pg and "dia_cia" in pg


def test_configuracoes_explica_quando_ainda_nao_ha_12_meses(con_temp, http, monkeypatch):
    congelar(monkeypatch, HOJE)
    entrada(con_temp, 8000, "2026-09-10")
    entrada(con_temp, 8000, "2026-10-10")
    pg = http.get("/configuracoes").text
    assert "Ainda não há 12 meses de uso: o valor é a média dos 2 meses anteriores × 12." in pg
    assert "faturamento dos últimos 12 meses: R$ 96.000,00" in pg


def test_financeiro_lanca_mostra_como_calculei_e_recalcula_ao_abrir(con_temp, http, monkeypatch):
    congelar(monkeypatch, HOJE)
    receita_mensal(con_temp, 8000, "2025-10", "2026-10")
    a = aluno(con_temp, "Ana")
    marca(con_temp, a, "2026-10-05")
    pg = http.get("/financeiro").text
    assert "Como calculei: 6% (tabela do Simples, faixa 1; R$ 96.000,00 nos últimos 12 meses) × R$ 8.000,00 recebidos em 10/2026" in pg
    assert "Como calculei: 1 aula de 1 pessoa × R$ 70,76" in pg
    assert "<strong>DAS 10/2026 (Simples)</strong>" in pg and "<strong>CIA 111: aulas de 10/2026</strong>" in pg
    assert "CIA este mês até agora: 0 aulas = R$ 0,00" in pg
    assert "DAS de 11/2026 (vence 18/12): R$ 0,00 até agora" in pg
    entrada(con_temp, 2000, "2026-10-28")                              # chegou atrasado: abrir o Financeiro recalcula
    assert "× R$ 10.000,00 recebidos em 10/2026" in http.get("/financeiro").text
    assert automaticas(con_temp, "das:2026-10")[0]["valor"] == 600


def test_livro_caixa_do_mes_do_vencimento_tambem_mostra_como_calculei(con_temp, http, monkeypatch):
    congelar(monkeypatch, HOJE)
    cenario_outubro(con_temp)
    pg = http.get("/financeiro?mes=2026-11&escopo=PJ").text
    livro = pg.split('id="livro-caixa"')[1]
    assert "DAS 10/2026 (Simples)" in livro and "Como calculei: 6% (tabela do Simples" in livro


def test_previa_do_mes_corrente(con_temp):
    a = aluno(con_temp, "Ana")
    marca(con_temp, a, "2026-11-02")
    entrada(con_temp, 5000, "2026-11-01")
    assert contas_auto.previa(con_temp, HOJE) == ["CIA este mês até agora: 1 aula = R$ 70,76",
                                                  "DAS de 11/2026 (vence 18/12): R$ 300,00 até agora"]


def test_painel_lanca_com_cache_por_dia_e_financeiro_recalcula(con_temp, http, monkeypatch):
    congelar(monkeypatch, HOJE)
    cenario_outubro(con_temp)
    assert http.get("/").status_code == 200
    assert automaticas(con_temp, "das:2026-10")[0]["valor"] == 480
    entrada(con_temp, 2000, "2026-10-28")
    http.get("/")                                                      # mesmo dia: o Painel não refaz a conta
    assert automaticas(con_temp, "das:2026-10")[0]["valor"] == 480
    http.get("/financeiro")                                            # o Financeiro recalcula o que está em aberto
    assert automaticas(con_temp, "das:2026-10")[0]["valor"] == 600


def test_alertas_sozinhos_nao_geram_contas(con_temp):
    cenario_outubro(con_temp)
    main.alertas(con_temp)
    assert automaticas(con_temp) == []
