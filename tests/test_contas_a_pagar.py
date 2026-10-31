"""Financeiro: uma lista só de Contas a pagar, com Excluir (lançamento: lixeira; conta recorrente: só este mês ou encerrar)."""
from urllib.parse import unquote

import pytest

from app import financeiro, main
from tests.test_alertas import con_temp  # noqa: F401  (banco temporário)
from tests.test_alertas_acao import congelar, http  # noqa: F401  (hoje congelado no main; cliente HTTP do mesmo banco)

HOJE = "2026-09-15"
SEM_LIVRO = "/financeiro?mes=2026-01"   # livro-caixa de janeiro vazio: cada conta aparece só na lista de Contas a pagar


def na_lista(pg, nome):
    """Quantas vezes a conta aparece como linha da lista de Contas a pagar (o nome em destaque), não em diálogos nem em outras tabelas."""
    return pg.count(f"<strong>{nome}</strong>")


def lanc(con, escopo, data, valor, descricao, tipo="saida", categoria="Outros"):
    with con:
        return con.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, descricao) VALUES (?,?,?,?,?,?)",
                           (escopo, tipo, data, valor, categoria, descricao)).lastrowid


def recorrencia(con, descricao="Empréstimo MP", valor=561.45, dia=25, inicio="2026-09", escopo="PF"):
    with con:
        return con.execute("INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio) VALUES (?,?,?,?,?,?)",
                           (escopo, descricao, "Outros", valor, dia, inicio)).lastrowid


@pytest.fixture
def cenario(con_temp, monkeypatch):
    congelar(monkeypatch, HOJE)
    ids = {"luz": lanc(con_temp, "PF", "2026-09-10", 100, "Conta da luz"),
           "net": lanc(con_temp, "PJ", "2026-09-20", 80, "Internet do estúdio"),
           "longe": lanc(con_temp, "PJ", "2026-12-01", 999, "Seguro anual"),
           "receber": lanc(con_temp, "PJ", "2026-09-12", 300, "Mensalidade da Ana", tipo="entrada"),
           "emp": recorrencia(con_temp)}
    return con_temp, ids


def test_financeiro_tem_uma_lista_so_com_cada_conta_uma_vez(cenario, http):
    con, _ = cenario
    pg = http.get(SEM_LIVRO).text
    assert pg.count("Contas a pagar</h2>") == 1
    for nome in ("Conta da luz", "Internet do estúdio", "Empréstimo MP"):
        assert na_lista(pg, nome) == 1
    assert "Seguro anual" not in pg                                   # fora dos 30 dias
    assert "Para pagar até 15/10: <strong>R$ 741,45</strong>" in pg   # 100 + 80 + 561,45
    assert pg.index("<strong>Conta da luz") < pg.index("<strong>Internet do estúdio")  # atrasada primeiro
    # o que sumiu: os cards "Livre", a fila repetida e a lista "A pagar e a receber"
    for velho in ("Quanto dá para gastar", "Livre pessoal", "Livre empresa", "Pague nesta ordem", "falta dinheiro", "A pagar e a receber"):
        assert velho not in pg
    assert "atrasada há 5 dias" in pg and "vence em 5 dias" in pg
    # Pagar: recorrente abre o Pagar; lançamento abre o Dar baixa
    assert pg.count('data-abrir="dlg-pagar"') == 1 and pg.count('data-abrir="dlg-baixa"') >= 2
    # A receber continua, separado, só com a entrada
    receber = http.get("/financeiro?mes=2026-09").text.split("<h3>A receber</h3>")[1].split("</table>")[0]
    assert "Mensalidade da Ana" in receber and "Conta da luz" not in receber


def test_saldo_digitado_aparece_so_se_recente(cenario, http):
    con, _ = cenario
    sem = http.get(SEM_LIVRO).text
    assert "Nas contas:" not in sem and 'data-abrir="dlg-saldos"' in sem          # sem saldo: só o botão
    financeiro.salvar_saldos(con, "2026-09-14", {"Inter": 1500.0}, {"Inter": "PF"})
    pg = http.get(SEM_LIVRO).text
    assert "Nas contas: R$ 1.500,00 (atualizado em 14/09)" in pg
    with con:
        con.execute("UPDATE saldos SET data='2026-09-01'")                              # 14 dias: velho
    velho = http.get(SEM_LIVRO).text
    assert "Nas contas:" not in velho and 'data-abrir="dlg-saldos"' in velho


def test_excluir_lancamento_tira_da_lista_do_total_e_do_alerta(cenario, http):
    con, ids = cenario
    pg = http.get(SEM_LIVRO).text
    assert f'action="/financeiro/lancamento/{ids["luz"]}/excluir"' in pg and "data-confirmar=" in pg
    [antes] = [a for a in main.alertas(con) if "vencida" in a["texto"]]
    assert antes["texto"].startswith("1 conta vencida") and antes["texto"].endswith("(R$ 100,00)")
    r = http.post(f"/financeiro/lancamento/{ids['luz']}/excluir", data={"volta": "mes=2026-01&escopo=todos"}, follow_redirects=False)
    assert "lixeira" in unquote(r.headers["location"]) and r.headers["location"].startswith("/financeiro?mes=2026-01")
    depois = http.get(SEM_LIVRO).text
    assert na_lista(depois, "Conta da luz") == 0 and "Para pagar até 15/10: <strong>R$ 641,45</strong>" in depois
    assert not [a for a in main.alertas(con) if "vencida" in a["texto"]]
    assert con.execute("SELECT excluido_em FROM lancamentos WHERE id=?", (ids["luz"],)).fetchone()[0]   # lixeira, não apagado


def test_conta_recorrente_so_este_mes_pula_so_a_competencia(cenario, http):
    con, ids = cenario
    pg = http.get(SEM_LIVRO).text
    assert f'data-abrir="dlg-excluir-rec"' in pg and f'data-rid="{ids["emp"]}"' in pg and 'data-competencia="2026-09"' in pg
    r = http.post("/financeiro/recorrencia/pular", data={"rid": ids["emp"], "competencia": "2026-09", "volta": "mes=2026-01&escopo=todos"},
                  follow_redirects=False)
    assert "saiu da lista" in unquote(r.headers["location"])
    depois = http.get(SEM_LIVRO).text
    assert na_lista(depois, "Empréstimo MP") == 0 and "Para pagar até 15/10: <strong>R$ 180,00</strong>" in depois
    # só setembro: a conta segue viva e outubro ainda aparece
    assert con.execute("SELECT fim, excluido_em FROM recorrencias WHERE id=?", (ids["emp"],)).fetchone()[:] == (None, None)
    assert [i["descricao"] for i in financeiro.pendencias(con, "2026-10", HOJE) if i["origem"] == "recorrencia"] == ["Empréstimo MP"]
    assert [i["competencia"] for i in financeiro.contas_a_pagar(con, "2026-10-20")["itens"] if i["origem"] == "recorrencia"] == ["2026-10"]
    # repetir não quebra e mês inválido dá erro
    http.post("/financeiro/recorrencia/pular", data={"rid": ids["emp"], "competencia": "2026-09"}, follow_redirects=False)
    assert con.execute("SELECT COUNT(*) FROM recorrencia_pulos").fetchone()[0] == 1
    r = http.post("/financeiro/recorrencia/pular", data={"rid": ids["emp"], "competencia": "setembro"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]


def test_encerrar_conta_recorrente_para_todos_os_meses_seguintes(cenario, http):
    con, ids = cenario
    rid = recorrencia(con, "Plano de saúde", 300, dia=28, inicio="2026-08")
    financeiro.baixar_recorrencia(con, rid, "2026-08", 300, "2026-08-28")            # já teve pagamento: não vai para a lixeira
    r = http.post("/financeiro/recorrencia/encerrar", data={"rid": rid, "competencia": "2026-09", "volta": "mes=2026-01&escopo=todos"},
                  follow_redirects=False)
    assert "encerrada" in unquote(r.headers["location"])
    assert con.execute("SELECT fim, excluido_em FROM recorrencias WHERE id=?", (rid,)).fetchone()[:] == ("2026-08", None)
    assert na_lista(http.get(SEM_LIVRO).text, "Plano de saúde") == 0
    for mes in ("2026-09", "2026-10", "2026-11", "2027-03"):
        assert "Plano de saúde" not in [i["descricao"] for i in financeiro.pendencias(con, mes, HOJE)]
    assert con.execute("SELECT COUNT(*) FROM lancamentos WHERE recorrencia_id=? AND pago_em IS NOT NULL", (rid,)).fetchone()[0] == 1
    # nunca pagou: a conta inteira vai para a lixeira (e os outros meses também somem)
    http.post("/financeiro/recorrencia/encerrar", data={"rid": ids["emp"], "competencia": "2026-09"}, follow_redirects=False)
    assert con.execute("SELECT excluido_em FROM recorrencias WHERE id=?", (ids["emp"],)).fetchone()[0]
    assert "Empréstimo MP" not in [i["descricao"] for i in financeiro.pendencias(con, "2026-10", HOJE)]


def test_excluir_lancamento_de_conta_recorrente_nao_deixa_a_conta_voltar(cenario, http):
    """A saída em aberto ligada à conta recorrente abre a escolha Só este mês / Encerrar, e some de verdade (não volta como recorrência)."""
    con, ids = cenario
    lid = lanc(con, "PF", "2026-09-26", 50, "Academia avulsa")
    rid = recorrencia(con, "Academia", 50, dia=26, inicio="2026-09")
    with con:
        con.execute("UPDATE lancamentos SET recorrencia_id=?, competencia='2026-09' WHERE id=?", (rid, lid))
    pg = http.get(SEM_LIVRO).text
    assert f'data-rid="{rid}"' in pg and f"/financeiro/lancamento/{lid}/excluir" not in pg
    http.post("/financeiro/recorrencia/pular", data={"rid": rid, "competencia": "2026-09"}, follow_redirects=False)
    depois = http.get(SEM_LIVRO).text
    assert na_lista(depois, "Academia avulsa") == 0 and na_lista(depois, "Academia") == 0 and con.execute("SELECT excluido_em FROM lancamentos WHERE id=?", (lid,)).fetchone()[0]


def test_painel_nao_tem_mais_saldo_livre_negativo(cenario, http):
    con, _ = cenario
    financeiro.salvar_saldos(con, HOJE, {"Itaú": 50.0}, {"Itaú": "PF"})              # tem R$ 50 e deve R$ 661: o alerta antigo dispararia
    assert not [a for a in main.alertas(con) if "Saldo livre" in a["texto"]]
    assert "Saldo livre" not in http.get("/").text
    assert [a for a in main.alertas(con) if "vencida" in a["texto"]]                  # o alerta de contas vencidas continua


def test_vencidas_mostra_so_vencidas_ou_vencendo(cenario, http):
    con, _ = cenario
    lanc(con, "PJ", "2026-09-17", 40, "Taxa em 2 dias")
    tudo = http.get(SEM_LIVRO).text
    assert 'id="vencidas"' not in tudo and na_lista(tudo, "Internet do estúdio") == 1 and "Ver todas" not in tudo
    pg = http.get("/financeiro?mes=2026-01&vencidas=1#vencidas").text
    assert 'id="vencidas"' in pg and pg.count("Contas a pagar</h2>") == 1           # a mesma seção, sem card duplicado
    assert na_lista(pg, "Conta da luz") == 1 and na_lista(pg, "Taxa em 2 dias") == 1
    assert not any(na_lista(pg, n) for n in ("Internet do estúdio", "Empréstimo MP", "Seguro anual"))
    assert "Ver todas" in pg and 'href="/financeiro"' in pg and "<strong>R$ 140,00</strong>" in pg
    assert pg.index("<strong>Conta da luz") < pg.index("<strong>Taxa em 2 dias")                      # vencida antes da que vence
    assert 'name="volta" value="mes=2026-01&amp;escopo=todos&amp;vencidas=1"' in pg    # depois de pagar/excluir, continua filtrado


def test_vencidas_sem_nada_diz_que_esta_em_dia(con_temp, http):
    pg = http.get("/financeiro?vencidas=1").text
    assert 'id="vencidas"' in pg and "Tudo em dia" in pg
