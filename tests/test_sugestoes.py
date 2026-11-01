"""Sugestões (app/sugestoes.py): regras fixas a partir dos marcadores, ordem, "Já fiz", marketing sem desconto e telas sem beco sem saída."""
import datetime as dt
import json
import re
from urllib.parse import unquote

import pytest

from app import db, main, marcadores, sugestoes
from tests.test_marcadores import (HOJE, Contador, alunos_demais, cliente_http, con_temp, lancar, marcadores_de, montar,  # noqa: F401
                                   saldo)


def todas(con, hoje=HOJE):
    ctx, marc = marcadores_de(con, hoje)
    return {s["chave"]: s for s in sugestoes.calcular(ctx, marc)}


def aluno(con, nome="Ana", status="ativo", valor=300, pessoas=1, treinando=True, inicio="2026-01-10", renova="2027-02-20", tel="11999990000",
          tipo="Mensalidade", plano="Mensalidade 2x"):
    """Aluno em dia há meses (aula recente e outra um mês atrás, renovação longe)."""
    with con:
        cid = con.execute("""INSERT INTO clientes (nome, telefone, status, tipo_servico, plano, local, pessoas, valor, data_renovacao, data_inicio,
                             canal_origem) VALUES (?,?,?,?,?,'CIA',?,?,?,?, 'Instagram')""",
                          (nome, tel, status, tipo, plano, pessoas, valor, renova, inicio)).lastrowid
        if treinando:
            for d in ("2026-12-08", "2026-11-10"):
                con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', ?)", (cid, d))
    return cid


def sem_bloqueio(con):
    with con:
        con.execute("DELETE FROM campanha_fases WHERE tipo='bloqueio'")


# ---------- base: empresa e família saudáveis ----------
def test_base_saudavel_so_sugere_subir_o_salario(con_temp):
    montar(con_temp, reserva=40000)
    s = todas(con_temp)
    assert set(s) == {"subir_salario"} and s["subir_salario"]["cor"] == "azul"      # boa notícia, em azul
    assert s["subir_salario"]["titulo"] == "Você pode subir o salário para R$ 3.200."      # 80% do lucro médio dos 3 meses, em múltiplos de 50
    assert s["subir_salario"]["impacto"] == 3200 and s["subir_salario"]["impacto_tipo"] == "mes"


# ---------- finanças: cada regra dispara e não dispara ----------
def test_equilibrio_abaixo_do_minimo_com_tres_caminhos(con_temp):
    montar(con_temp, reserva=40000)
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=7000 WHERE grupo='salario' AND chave='valor'")
    alunos_demais(con_temp, 3)
    s = todas(con_temp)["equilibrio"]
    assert s["marcador"] == "pe_economico" and s["cor"] == "vermelho" and s["impacto_tipo"] == "mes"
    assert s["impacto"] == pytest.approx(10000 / 0.84 - 10000, abs=1)   # (fixos + salário) ÷ margem de contribuição − receita
    assert len(s["passos"]) == 3 and "10%" in s["passos"][0] and "aluno" in s["passos"][1] and "Cortar" in s["passos"][2]
    assert s["titulo"].startswith("Faltam R$ ") and s["porque"].startswith("Equilíbrio econômico")


def test_equilibrio_nao_dispara_com_a_receita_acima(con_temp):
    montar(con_temp, reserva=40000)
    assert "equilibrio" not in todas(con_temp)


def test_margem_de_contribuicao_baixa_lista_as_maiores_categorias(con_temp):
    montar(con_temp, variaveis=6000, reserva=40000)
    s = todas(con_temp)["margem_contribuicao"]
    assert "Material" in s["porque"] and s["impacto"] == 600 and s["cor"] == "vermelho"      # 10% dos 6.000
    con_temp.execute("DELETE FROM lancamentos WHERE categoria='Material'")
    assert "margem_contribuicao" not in todas(con_temp)


def test_caixa_negativo_da_empresa_e_da_familia(con_temp):
    montar(con_temp, saldo_pj=1000, saldo_pf=100, reserva=40000)
    lancar(con_temp, "saida", 3000, "2026-12-15", pago_em=None, escopo="PF", categoria="Moradia")
    s = todas(con_temp)
    assert s["caixa_pj"]["cor"] == "vermelho" and s["caixa_pj"]["impacto_tipo"] == "uma_vez" and "empresa" in s["caixa_pj"]["titulo"]
    assert s["caixa_pf"]["impacto"] == pytest.approx(2900, abs=1) and "vida pessoal" in s["caixa_pf"]["titulo"]
    assert [a["rotulo"] for a in s["caixa_pj"]["acoes"]][:2] == ["Ver 90 dias", "Contas"]
    assert not {"caixa_pj", "caixa_pf"} & set(todas(montar_novo(con_temp)))


def montar_novo(con):
    con.execute("DELETE FROM saldos")
    saldo(con, "Contabilizei Bank", 90000)
    saldo(con, "Inter", 90000)
    con.execute("DELETE FROM lancamentos WHERE escopo='PF' AND pago_em IS NULL")
    return con


def test_caixa_negativo_oferece_cobrar_vencidos(con_temp):
    montar(con_temp, saldo_pj=1000, reserva=40000)
    sem_bloqueio(con_temp)
    cid = aluno(con_temp, "Atrasada", valor=400, renova="2026-11-20")
    s = todas(con_temp)["caixa_pj"]
    assert s["acoes"][-1] == {"rotulo": "Cobrar vencidos (1)", "href": f"/clientes?ids={cid}&motivo=cobrar"}


def test_salario_maior_que_o_lucro_sugere_o_valor_do_crm(con_temp):
    montar(con_temp, reserva=40000)
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=7000 WHERE grupo='salario' AND chave='valor'")
    s = todas(con_temp)["salario_alto"]
    assert s["titulo"] == "Seu salário de R$ 7.000 é maior que o lucro da empresa." and "R$ 3.200" in s["porque"]
    assert s["impacto"] == 3800 and s["acoes"][0]["href"] == "/configuracoes#cfg-salario"
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=3000 WHERE grupo='salario' AND chave='valor'")
    assert "salario_alto" not in todas(con_temp)


def test_subir_salario_precisa_de_lucro_reserva_e_caixa_no_verde(con_temp):
    montar(con_temp, reserva=40000)
    assert "subir_salario" in todas(con_temp)
    montar_novo(con_temp)
    saldo(con_temp, "Contabilizei Bank", 1000)      # caixa fica negativo: não é hora de subir o salário
    assert "subir_salario" not in todas(con_temp)


def test_reserva_da_empresa_guarde_x_por_mes_em_multiplos_de_50(con_temp):
    montar(con_temp, reserva=1000)
    s = todas(con_temp)["reserva"]
    assert s["titulo"] == "Guarde R$ 650 por mês na reserva da empresa." and s["impacto"] == 650     # (3 × 3.000 − 1.000) ÷ 12 = 667
    assert s["marcador"] == "reserva_pj" and s["cor"] == "vermelho"
    montar_novo(con_temp)
    saldo(con_temp, "Caixa", 40000, "2026-12-11")
    assert "reserva" not in todas(con_temp, "2026-12-12")


def test_cortar_custos_lista_as_maiores_contas_com_10_por_cento(con_temp):
    montar(con_temp, variaveis=6000, reserva=40000)
    s = todas(con_temp)["cortar_custos"]
    assert s["impacto"] == 900 and s["marcador"] == "margem_lucro"                  # 10% de (3.000 de aluguel + 6.000 de material)
    assert any("Aluguel" in p and "R$ 300" in p for p in s["passos"]) and len(s["passos"]) <= 3


def test_cortar_custos_nao_aparece_com_margem_boa(con_temp):
    montar(con_temp, reserva=40000)
    assert "cortar_custos" not in todas(con_temp)


def test_gastos_pessoais_e_moradia_e_dividas_e_reserva_pf(con_temp):
    montar(con_temp, pf_saidas=8500, moradia=4000, reserva=2000)
    lancar(con_temp, "saida", 1500, "2026-12-20", pago_em=None, escopo="PF", categoria="Dívidas", descricao="Moto", parcela_num=1, parcela_total=4)
    s = todas(con_temp)
    assert s["gastos_pessoais"]["marcador"] == "sobra" and "Alimentação" in s["gastos_pessoais"]["porque"]
    assert s["moradia"]["impacto"] == pytest.approx(4000 - 0.30 * 9000, abs=1) and "44%" in s["moradia"]["porque"]
    assert s["dividas"]["titulo"] == "Quite primeiro Moto, a dívida mais cara."
    assert s["reserva_pf"]["titulo"].startswith("Guarde R$ ") and "6 meses" in s["reserva_pf"]["titulo"]


def test_reajuste_dos_alunos_abaixo_da_margem_minima(con_temp):
    montar(con_temp, reserva=40000)
    assert "reajuste" not in todas(con_temp)
    ids = alunos_demais_ids(con_temp, 3)
    s = todas(con_temp)["reajuste"]
    assert s["acoes"][0]["href"] == f"/clientes?ids={','.join(map(str, ids))}&motivo=reajuste" and s["impacto_tipo"] == "mes"
    assert s["impacto"] > 0 and s["titulo"] == "3 alunos pagam abaixo do preço mínimo."


def alunos_demais_ids(con, n):
    alunos_demais(con, n)
    return [r[0] for r in con.execute("SELECT id FROM clientes ORDER BY id")]


# ---------- marketing: cada regra dispara e não dispara ----------
def test_indicacao_para_quem_esta_em_dia_ha_3_meses(con_temp):
    montar(con_temp, reserva=40000)
    sem_bloqueio(con_temp)
    assert "indicacao" not in todas(con_temp)                       # ninguém para convidar
    cid = aluno(con_temp, "Ana")
    aluno(con_temp, "Novata", inicio="2026-11-20")                  # começou há menos de 3 meses
    s = todas(con_temp)["indicacao"]
    assert s["acoes"] == [{"rotulo": "Mandar convite (1)", "href": f"/clientes?ids={cid}&motivo=indicacao"}]
    assert "ninguém veio por indicação" in s["porque"] and s["marcador"] == "agenda"
    with con_temp:   # agenda no verde (meta de horas baixa): não precisa pedir indicação
        con_temp.execute("UPDATE parametros SET valor=1 WHERE grupo='metas' AND chave='horas_dez26'")
    assert "indicacao" not in todas(con_temp)


def test_indicacao_cita_quantos_vieram_por_indicacao(con_temp):
    montar(con_temp, reserva=40000)
    sem_bloqueio(con_temp)
    aluno(con_temp, "Ana")
    novo = aluno(con_temp, "Bruno", inicio="2026-11-20")
    with con_temp:
        con_temp.execute("UPDATE clientes SET canal_origem='Indicação' WHERE id=?", (novo,))
    assert "1 aluno novo vieram por indicação" in todas(con_temp)["indicacao"]["porque"]


def test_reativar_ex_alunos_ate_12_meses(con_temp):
    montar(con_temp, reserva=40000)
    assert "reativar_ex_alunos" not in todas(con_temp)
    recente = aluno(con_temp, "Recente", status="inativo", treinando=False)
    velho = aluno(con_temp, "Velho", status="inativo", treinando=False)
    with con_temp:
        for cid, quando in ((recente, "2026-09-10"), (velho, "2025-06-01")):
            con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'status', ?, 'Status alterado para inativo')",
                             (cid, quando))
    s = todas(con_temp)["reativar_ex_alunos"]
    assert s["acoes"] == [{"rotulo": "Mandar mensagem (1)", "href": f"/clientes?ids={recente}&motivo=reativar"}]      # o de 18 meses não entra
    assert s["marcador"] == "saidas" and s["impacto"] == 300


def test_reativar_leads_perdidos_dos_ultimos_90_dias(con_temp):
    montar(con_temp, reserva=40000)
    with con_temp:
        con_temp.execute("INSERT INTO leads (nome, canal_origem, etapa, data_mudanca_etapa) VALUES ('Antigo','Google','perdido','2026-06-01')")
    assert "reativar_leads" not in todas(con_temp)
    with con_temp:
        con_temp.execute("INSERT INTO leads (nome, canal_origem, etapa, data_mudanca_etapa) VALUES ('Recente','Google','perdido','2026-11-20')")
    s = todas(con_temp)["reativar_leads"]
    assert s["acoes"] == [{"rotulo": "Ver leads", "href": "/leads"}] and "1 lead perdido" in s["porque"]


def test_horarios_de_vale_livres(con_temp):
    montar(con_temp, reserva=40000)
    assert "horarios_de_vale" not in todas(con_temp)
    with con_temp:
        con_temp.execute("""INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador) VALUES
                            ('Pacotes', 2, 'CIA', 14, 'livre', 0.9), ('Mensalidades', 2, 'CIA', 14, 'livre', 0.9),
                            ('Pacotes', 3, 'CIA', 18, 'livre', 1.1), ('Pacotes', 4, 'CIA', 15, 'ocupado', 0.9)""")
    s = todas(con_temp)["horarios_de_vale"]
    assert s["titulo"] == "Ofereça os 1 horários de vale que estão livres." or "1 horário" in s["titulo"]
    assert s["acoes"][0]["href"] == "/grade?vale=1"


def test_espera_no_pico_sobe_o_preco_do_pico(con_temp):
    montar(con_temp, reserva=40000)
    assert "espera_no_pico" not in todas(con_temp)
    with con_temp:
        con_temp.execute("INSERT INTO lista_espera (nome, hora) VALUES ('Carla', 18)")
    s = todas(con_temp)["espera_no_pico"]
    assert s["cor"] == "azul" and s["titulo"] == "Suba o preço do horário de pico." and "1 pessoa" in s["porque"]


def test_treino_em_dupla_quando_grupos_estao_abaixo_da_meta(con_temp):
    montar(con_temp, reserva=40000)
    sem_bloqueio(con_temp)
    assert "treino_em_dupla" not in todas(con_temp)
    cid = aluno(con_temp, "Solo", valor=400)
    s = todas(con_temp)["treino_em_dupla"]
    assert s["acoes"] == [{"rotulo": "Mandar convite (1)", "href": f"/clientes?ids={cid}&motivo=dupla"}]
    assert s["impacto"] == pytest.approx(0.6 * 400, abs=0.01) and s["cor"] == "azul"      # a dupla paga 1,6× o treino de uma pessoa
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=0.01 WHERE grupo='metas' AND chave='pct_grupos_dez26'")
        con_temp.execute("UPDATE clientes SET pessoas=2")
    assert "treino_em_dupla" not in todas(con_temp)


def test_verba_por_canal_so_com_gasto_lancado(con_temp):
    montar(con_temp, reserva=40000)
    assert "verba_por_canal" not in todas(con_temp)
    with con_temp:
        con_temp.execute("INSERT INTO gastos_marketing (mes, canal, anuncios, clientes) VALUES ('2026-11', 'Instagram Ads', 900, 0)")
    s = todas(con_temp)["verba_por_canal"]
    assert s["cor"] == "vermelho" and "Instagram Ads" in s["titulo"] and "nenhum aluno novo" in s["porque"] and s["impacto"] == 300
    with con_temp:   # 3 alunos por R$ 900 = R$ 300 cada: dentro do limite
        con_temp.execute("UPDATE gastos_marketing SET clientes=4")
    assert "verba_por_canal" not in todas(con_temp)


# ---------- ordem, topo e "Já fiz" ----------
def fake(chave, marcador, cor, impacto):
    return {"chave": chave, "marcador": marcador, "cor": cor, "impacto": impacto}


def test_ordem_por_gravidade_depois_impacto_e_top_3_de_marcadores_diferentes():
    lista = [fake("a", "caixa_pj", "amarelo", 500), fake("b", "caixa_pj", "vermelho", 100), fake("c", "agenda", "vermelho", 900),
             fake("d", "agenda", "vermelho", 800), fake("e", "sobra", "azul", 5000), fake("f", "reserva_pj", "amarelo", 700),
             fake("g", "dividas", "amarelo", 600)]
    ordenada = sorted(lista, key=lambda s: (sugestoes.GRAV[s["cor"]], -s["impacto"]))
    assert [s["chave"] for s in ordenada] == ["c", "d", "b", "f", "g", "a", "e"]
    top, resto = sugestoes.escolher(ordenada)
    assert [s["chave"] for s in top] == ["c", "b", "f"]                       # um por marcador: o 2º da agenda e o 2º do caixa ficam de fora
    assert [s["chave"] for s in resto] == ["d", "g", "a", "e"] and len({s["marcador"] for s in top}) == 3
    assert [s["chave"] for s in sugestoes.escolher(ordenada, limite=1)[0]] == ["c"]


def test_painel_devolve_top_e_resto(con_temp):
    montar(con_temp, variaveis=6000, moradia=4000, saldo_pj=1000, reserva=1000)
    r = sugestoes.painel(con_temp, HOJE)
    assert len(r["sugestoes"]) == 3 and len({s["marcador"] for s in r["sugestoes"]}) == 3 and r["mais"]
    graves = [sugestoes.GRAV[s["cor"]] for s in r["sugestoes"]]
    assert graves == sorted(graves)
    assert r["marcadores"]["nota"]["PJ"]["total"] > 0 and r["janela"] == ["2026-09", "2026-10", "2026-11"]


def test_ja_fiz_esconde_por_30_dias(con_temp):
    montar(con_temp, reserva=1000)
    assert "reserva" in todas(con_temp)
    ate = sugestoes.adiar(con_temp, "reserva", HOJE)
    assert ate == "2027-01-09"
    assert db.parametros(con_temp, "sugestao_adiada") == {"reserva": "2027-01-09"}
    assert "reserva" not in todas(con_temp, HOJE) and "reserva" not in todas(con_temp, "2027-01-08")
    assert "reserva" in todas(con_temp, "2027-01-09")                          # passou os 30 dias: volta
    assert sugestoes.adiar(con_temp, "reserva", "2027-01-09") == "2027-02-08"   # adiar de novo troca a data, não duplica
    assert con_temp.execute("SELECT COUNT(*) FROM parametros WHERE grupo='sugestao_adiada'").fetchone()[0] == 1


def test_rota_ja_fiz(cliente_http):
    http, con = cliente_http
    r = http.post("/financeiro/sugestao/adiar", data={"chave": "reserva", "voltar": "/financeiro/painel?mes=2026-05"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/financeiro/painel?mes=2026-05&msg=")
    amanha = db.parametros(con, "sugestao_adiada")["reserva"]
    assert amanha == (dt.date.today() + dt.timedelta(days=30)).isoformat()
    r = http.post("/financeiro/sugestao/adiar", data={"chave": "x", "voltar": "https://mal.com/x"}, follow_redirects=False)
    assert r.headers["location"].startswith("/financeiro/painel?msg=")           # destino de fora do CRM não vale
    r = http.post("/financeiro/sugestao/adiar", data={"chave": "../x;", "voltar": "/"}, follow_redirects=False)
    assert "erro=" in r.headers["location"] and set(db.parametros(con, "sugestao_adiada")) == {"reserva", "x"}


# ---------- marketing nunca dá desconto ----------
def cenario_completo(con):
    """Quase todas as regras ao mesmo tempo."""
    montar(con, variaveis=6000, moradia=4000, saldo_pj=1000, reserva=1000, pf_saidas=8500)
    with con:
        con.execute("UPDATE parametros SET valor=7000 WHERE grupo='salario' AND chave='valor'")
        con.execute("INSERT INTO leads (nome, canal_origem, etapa, data_mudanca_etapa) VALUES ('Recente','Google','perdido','2026-11-20')")
        con.execute("INSERT INTO lista_espera (nome, hora) VALUES ('Carla', 18)")
        con.execute("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador) VALUES ('Pacotes', 2, 'CIA', 14, 'livre', 0.9)")
        con.execute("INSERT INTO gastos_marketing (mes, canal, anuncios, clientes) VALUES ('2026-11', 'Instagram Ads', 900, 0)")
    lancar(con, "saida", 1500, "2026-12-20", pago_em=None, escopo="PF", categoria="Dívidas", descricao="Moto", parcela_num=1, parcela_total=4)
    alunos_demais(con, 2)
    sem_bloqueio(con)
    aluno(con, "Ana")
    ex = aluno(con, "Ex", status="inativo", treinando=False)
    with con:
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'status', '2026-09-10', 'Status alterado para inativo')", (ex,))


def test_nenhuma_sugestao_fala_em_desconto(con_temp):
    cenario_completo(con_temp)
    s = todas(con_temp)
    assert {"equilibrio", "indicacao", "reativar_ex_alunos", "reativar_leads", "horarios_de_vale", "espera_no_pico", "treino_em_dupla",
            "verba_por_canal", "reajuste", "cortar_custos", "moradia", "dividas", "reserva_pf", "salario_alto"} <= set(s)
    for x in s.values():
        texto = json.dumps(x, ensure_ascii=False).lower()
        assert "desconto" not in texto and "abatimento" not in texto and "promoção" not in texto, x["chave"]
    modelos = db.parametros(con_temp, "msg_whatsapp")
    assert "{vantagem}" in modelos["indicacao"] and "{nome}" in modelos["indicacao"] and "amigo" in modelos["dupla"]
    for chave in ("indicacao", "dupla"):
        assert "desconto" not in modelos[chave].lower()


def test_toda_sugestao_tem_titulo_curto_botao_e_impacto(con_temp):
    cenario_completo(con_temp)
    for s in todas(con_temp).values():
        assert s["titulo"].endswith(".") and len(s["titulo"]) <= 90, s["titulo"]
        assert s["acoes"] and all(a["rotulo"] and (a.get("href", "").startswith("/") or a.get("dialogo")) for a in s["acoes"]), s["chave"]
        assert s["cor"] in ("vermelho", "amarelo", "azul") and s["impacto_tipo"] in ("mes", "uma_vez") and len(s["passos"]) <= 3
        assert s["porque"] and s["marcador"]


def test_sugestao_nao_repete_o_que_ja_e_alerta(con_temp):
    """Sem marcador não há sugestão: cinza e mensalidades vencidas não geram nada (o botão do marcador já leva à solução)."""
    ctx, marc = marcadores_de(con_temp)
    assert sugestoes.calcular(ctx, marc) == []
    montar(con_temp, reserva=40000)
    sem_bloqueio(con_temp)
    aluno(con_temp, "Atrasada", valor=400, renova="2026-11-20")
    assert marcadores_de(con_temp)[1]["todos"]["vencidas"]["cor"] != "cinza"
    assert all("vencid" not in s["chave"] for s in todas(con_temp).values())


# ---------- nenhum botão leva a um beco sem saída ----------
def todos_os_links(con, hoje=HOJE):
    r = sugestoes.painel(con, hoje, limite=99)
    achados = set()
    for s in r["sugestoes"] + r["mais"]:
        achados |= {a["href"] for a in s["acoes"] if a.get("href")}
    for e in ("PJ", "PF"):
        for g in r["marcadores"][e]:
            achados |= {m["acao"]["href"] for m in g["marcadores"]}
    return achados


def test_todo_botao_gerado_responde_200(cliente_http):
    http, con = cliente_http
    cenario_completo(con)
    links = todos_os_links(con)
    assert len(links) > 15
    for href in sorted(links):
        r = http.get(href.split("#")[0])
        assert r.status_code == 200, href
        if "#" in href:   # a âncora existe na tela
            ancora = href.split("#")[1]
            assert f'id="{ancora}"' in r.text or ancora == "livro-caixa", (href, ancora)
    # e com a base vazia (tudo cinza) também
    http2_links = todos_os_links(db.conectar(), "2026-10-15")
    assert http2_links and all(http.get(h.split("#")[0]).status_code == 200 for h in http2_links)


# ---------- telas ----------
def dia(n):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


def aluno_hoje(con, nome, valor=300, tel="11999990000", status="ativo", renova=None, pessoas=1, tipo="Mensalidade", plano="Mensalidade 2x"):
    with con:
        return con.execute("""INSERT INTO clientes (nome, telefone, status, tipo_servico, plano, local, pessoas, valor, data_renovacao, data_inicio)
                              VALUES (?,?,?,?,?,'CIA',?,?,?, '2025-01-10')""", (nome, tel, status, tipo, plano, pessoas, valor, renova or dia(60))).lastrowid


def treinou(con, cid):
    with con:
        for n in (-2, -30):
            con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', ?)", (cid, dia(n)))


def sem_bloqueio_http(con):
    with con:
        con.execute("DELETE FROM campanha_fases WHERE tipo='bloqueio'")


def test_card_no_painel_inicial_com_uma_sugestao_e_ver_tudo(cliente_http):
    http, con = cliente_http
    sem_bloqueio_http(con)
    cid = aluno_hoje(con, "Ana Veterana")
    treinou(con, cid)
    t = http.get("/").text
    assert 'id="saude-financeira"' in t and "Ver tudo" in t and 'href="/financeiro/painel"' in t
    assert "Peça indicação a quem já treina com você." in t and f"/clientes?ids={cid}&amp;motivo=indicacao" in t
    assert t.count('class="sugestao ') == 1                                                      # só uma sugestão no card
    assert 'action="/financeiro/sugestao/adiar"' in t and "Já fiz" in t
    assert re.search(r"no verde|sem dados ainda", t)


def test_painel_inicial_com_a_base_vazia_continua_abrindo(cliente_http):
    http, _ = cliente_http
    r = http.get("/")
    assert r.status_code == 200 and "Saúde financeira" in r.text


def test_tela_mostra_o_que_fazer_e_ver_mais(cliente_http):
    http, con = cliente_http
    cenario_completo(con)
    # os lançamentos são de 2026: a tela olha para hoje; o que importa aqui é o HTML das sugestões do cenário
    r = sugestoes.painel(con, HOJE)
    assert len(r["sugestoes"]) == 3 and r["mais"]


def test_motivos_da_lista_de_clientes(cliente_http):
    http, con = cliente_http
    sem_bloqueio_http(con)
    atrasado = aluno_hoje(con, "Dora Atrasada", valor=400, renova=dia(-20))
    pago = aluno_hoje(con, "Paula Em Dia")
    treinou(con, pago)
    inativo = aluno_hoje(con, "Ivo Inativo", status="inativo")
    solo = aluno_hoje(con, "Sara Solo")
    treinou(con, solo)
    with con:
        con.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, sessoes_mes, preco_base,
                       custo_operacional, mao_obra, custo_total) VALUES ('Mensalidade','CIA','PIX',0,2,8.66,900,500,300,800)""")

    def lista(motivo, *ids):
        r = http.get(f"/clientes?ids={','.join(map(str, ids))}&motivo={motivo}")
        assert r.status_code == 200
        return r.text

    t = lista("cobrar", atrasado, pago)
    assert "Mensalidades vencidas" in t and "Dora Atrasada" in t and "Paula Em Dia" not in t and "Cobre um por um" in t
    assert "Cobrar R$" in t                                                    # o WhatsApp da cobrança, com multa e juros

    t = lista("indicacao", pago, inativo)
    assert "Alunos para pedir indicação" in t and "Paula Em Dia" in t and "Ivo Inativo" not in t
    assert "presente" in unquote(t) and "Se%20voc%C3%AA%20conhece" in t or "Se você conhece" in unquote(t)

    t = lista("reativar", inativo, pago)
    assert "Ex-alunos para chamar de volta" in t and "Ivo Inativo" in t and "Paula Em Dia" not in t
    assert "Faz tempo que n" in unquote(t)                                     # modelo reativacao

    t = lista("reajuste", pago, solo)
    assert "Alunos abaixo do preço mínimo" in t and "mínimo" in t and "Paula Em Dia" in t and "R$ 300,00" in t

    t = lista("dupla", solo, inativo)
    assert "Alunos para convidar a treinar em dupla" in t and "Sara Solo" in t and "Ivo Inativo" not in t
    assert "treinar com um amigo" in unquote(t)
    for motivo in ("cobrar", "indicacao", "reativar", "reajuste", "dupla"):
        assert "Ver todos" in lista(motivo, 99999)                              # lista vazia: "Tudo resolvido", sem erro
    assert "Tudo resolvido" in lista("cobrar", pago)


# ---------- desempenho ----------
def test_estimativa_com_bases_carregadas_e_igual_a_consulta_por_aluno(con_temp):
    with con_temp:
        for forma, preco in (("PIX", 900), ("Cartão 1x", 950), ("Cartão 3x", 1000)):
            con_temp.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, sessoes_mes, preco_base,
                                custo_operacional, mao_obra, custo_total) VALUES ('Mensalidade','CIA',?,0,2,8.66,?,500,300,800)""", (forma, preco))
        con_temp.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, sessoes_mes, preco_base,
                            custo_operacional, mao_obra, custo_total) VALUES ('Pacote de Aulas','CIA','Cartão 6x',8,0,8,700,400,200,600)""")
    from app import precos
    p, bases = precos.carregar_parametros(con_temp), main.carregar_bases(con_temp)
    casos = [("Mensalidade", "Mensalidade 2x", "CIA", "PIX"), ("Mensalidade", "Mensalidade 2x", "CIA", "Cartão 3x"),
             ("Mensalidade", "Mensalidade 2x", "CIA", "Dinheiro"), ("Mensalidade", "Mensalidade 2x", "CIA", None),
             ("Pacote de Aulas", "Pacote 8", "CIA", "PIX"), ("Pacote de Aulas", "Pacote 8", "CIA", "Cartão 6x"),
             ("Mensalidade", "Mensalidade 3x", "CIA", "PIX"), ("Mensalidade", "Mensalidade 2x", "SmartFit", "PIX")]
    for tipo, plano, local, forma in casos:
        with con_temp:
            cid = con_temp.execute("INSERT INTO clientes (nome, tipo_servico, plano, local, valor, forma_pagamento) VALUES ('x',?,?,?,800,?)",
                                   (tipo, plano, local, forma)).lastrowid
        c = con_temp.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone()
        a, b = main.base_do_cliente(con_temp, c), main.base_do_cliente(con_temp, c, bases)
        assert (dict(a) if a else None) == (dict(b) if b else None), (tipo, plano, local, forma)
        assert main.estimativa_cliente(con_temp, c, p) == main.estimativa_cliente(con_temp, c, p, bases)


def test_painel_nao_faz_mais_consultas_com_mais_alunos(tmp_path, monkeypatch):
    contagens = []
    for n in (5, 30):
        monkeypatch.setattr(db, "DB_PATH", tmp_path / f"s{n}.db")
        monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
        db.iniciar_banco()
        con = db.conectar()
        montar(con)
        alunos_demais(con, n)
        c = Contador(con)
        sugestoes.painel(c, HOJE)
        contagens.append(len(c.consultas))
        con.close()
    assert contagens[0] == contagens[1], contagens
    c2 = Contador(db.conectar(tmp_path / "s30.db"))
    main.calcular_metricas(c2)
    assert len(c2.consultas) < 40      # antes era uma consulta por aluno em estimativa_cliente
