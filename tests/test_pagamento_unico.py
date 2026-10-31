"""Pagamento num lugar só: diálogo único (Mensalidades e ficha), baixa com data e conta, conta recorrente só pelo "Pagar"."""
import datetime as dt

import pytest

from app import db, financeiro, main
from tests.test_rotas import cliente_http  # noqa: F401  (fixture: cliente HTTP num banco temporário)


def aluno_renova(con, cid, renova, valor=500):
    with con:
        con.execute("UPDATE clientes SET valor=?, status='ativo', data_renovacao=? WHERE id=?", (valor, renova, cid))


def pendente(http, **extra):
    """Saída lançada ontem, ainda sem baixa. Devolve (conexão, id, data)."""
    ontem = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    http.post("/financeiro/lancamento", data={"escopo": "PJ", "tipo": "saida", "data": ontem, "valor": "80", "categoria": "Outros",
                                              "descricao": "Conta X", **extra}, follow_redirects=False)
    con = db.conectar()
    return con, con.execute("SELECT id FROM lancamentos ORDER BY id DESC").fetchone()[0], ontem


@pytest.mark.parametrize("caminho, esperado", [("/clientes/3", "/clientes/3"), ("/financeiro/mensalidades?mes=2026-10", "/financeiro/mensalidades?mes=2026-10"),
                                               ("//evil.com", ""), ("http://x", ""), ("https://evil.com", ""), ("/\\evil.com", ""), ("/a\nb", ""),
                                               ("clientes/3", ""), ("", ""), (None, "")])
def test_caminho_seguro(caminho, esperado):
    assert main._caminho_seguro(caminho) == esperado


def test_pagamento_pela_ficha_liga_ao_aluno_move_a_renovacao_e_volta_para_a_ficha(cliente_http):
    http, cid = cliente_http
    hoje = dt.date.today()
    con = db.conectar()
    aluno_renova(con, cid, hoje.isoformat())
    ficha = http.get(f"/clientes/{cid}").text
    assert 'id="dlg-pgto"' in ficha and f'data-voltar="/clientes/{cid}"' in ficha and 'data-valor="500,00"' in ficha
    assert "Sem pagamento registrado" in ficha and "Pago até" not in ficha
    r = http.post("/financeiro/lancamento", data={"escopo": "PJ", "tipo": "entrada", "data": hoje.isoformat(), "pago_em": hoje.isoformat(),
                  "valor": "500,00", "categoria": "Outros", "cliente_id": cid, "conta": "Inter", "voltar": f"/clientes/{cid}"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/clientes/{cid}?msg=")
    assert [tuple(x) for x in con.execute("SELECT cliente_id, valor, conta, pago_em FROM lancamentos")] == [(cid, 500, "Inter", hoje.isoformat())]
    proxima = financeiro.proxima_renovacao(hoje.isoformat())
    assert financeiro.renovacoes(con, cid)[cid]["efetiva"] == proxima
    ficha = http.get(r.headers["location"]).text
    assert f"Pago até <strong>{hoje:%m/%Y}</strong>" in ficha
    assert f"próxima renovação <strong>{proxima[8:]}/{proxima[5:7]}/{proxima[:4]}</strong>" in ficha
    con.close()


@pytest.mark.parametrize("voltar", ["//evil.com", "http://x", "https://evil.com/clientes/1", "/\\evil.com", "evil", ""])
def test_pagamento_com_voltar_inseguro_cai_no_padrao(cliente_http, voltar):
    http, cid = cliente_http
    hoje = dt.date.today().isoformat()
    r = http.post("/financeiro/lancamento", data={"escopo": "PJ", "tipo": "entrada", "data": hoje, "pago_em": hoje, "valor": "100",
                  "categoria": "Outros", "cliente_id": cid, "voltar": voltar, "volta": "mes=2026-10&escopo=todos"}, follow_redirects=False)
    loc = r.headers["location"]
    assert loc.startswith("/financeiro?mes=2026-10") and "evil" not in loc and "http" not in loc
    con = db.conectar()
    assert con.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 1       # salvou do mesmo jeito
    con.close()


def test_baixa_com_data_e_conta_grava_as_duas_e_volta_para_a_origem(cliente_http):
    http, _ = cliente_http
    con, lid, ontem = pendente(http)
    r = http.post(f"/financeiro/lancamento/{lid}/baixa", data={"pago_em": ontem, "conta": "Itaú", "voltar": "/financeiro/mensalidades?mes=2026-10"},
                  follow_redirects=False)
    assert r.headers["location"].startswith("/financeiro/mensalidades?mes=2026-10&msg=")
    assert tuple(con.execute("SELECT pago_em, conta FROM lancamentos WHERE id=?", (lid,)).fetchone()) == (ontem, "Itaú")
    con.close()


def test_baixa_com_voltar_inseguro_usa_o_volta_de_sempre(cliente_http):
    http, _ = cliente_http
    con, lid, _ = pendente(http)
    r = http.post(f"/financeiro/lancamento/{lid}/baixa", data={"voltar": "//evil.com", "volta": "mes=2026-10&escopo=todos"}, follow_redirects=False)
    assert r.headers["location"].startswith("/financeiro?mes=2026-10&escopo=todos&msg=")
    con.close()


def test_baixa_sem_data_nem_conta_continua_valendo_hoje(cliente_http):
    http, _ = cliente_http
    con, lid, _ = pendente(http, conta="Caixa")
    r = http.post(f"/financeiro/lancamento/{lid}/baixa", data={"volta": "mes=2026-10&escopo=todos"}, follow_redirects=False)
    assert r.headers["location"].startswith("/financeiro?mes=2026-10&escopo=todos&msg=")
    assert tuple(con.execute("SELECT pago_em, conta FROM lancamentos WHERE id=?", (lid,)).fetchone()) == (dt.date.today().isoformat(), "Caixa")
    con.close()


@pytest.mark.parametrize("pago_em", ["2999-01-01", "31/10/2026", "ontem"])
def test_baixa_recusa_data_futura_ou_torta(cliente_http, pago_em):
    http, _ = cliente_http
    con, lid, _ = pendente(http)
    r = http.post(f"/financeiro/lancamento/{lid}/baixa", data={"pago_em": pago_em, "conta": "Inter"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert tuple(con.execute("SELECT pago_em, conta FROM lancamentos WHERE id=?", (lid,)).fetchone()) == (None, None)
    con.close()


def test_dar_baixa_nas_tres_telas_abre_o_mesmo_dialogo_com_a_conta_do_lancamento(cliente_http):
    http, cid = cliente_http
    hoje = dt.date.today()
    con, lid, _ = pendente(http, conta="Itaú")
    with con:
        con.execute("UPDATE lancamentos SET data=? WHERE id=?", (hoje.isoformat(), lid))
        con.execute("UPDATE clientes SET valor=500, status='ativo' WHERE id=?", (cid,))
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, cliente_id, conta) VALUES ('PJ','entrada',?,500,'Outros',?,'Inter')",
                    (hoje.isoformat(), cid))
    aluno = con.execute("SELECT id FROM lancamentos WHERE cliente_id=?", (cid,)).fetchone()[0]
    fin = http.get(f"/financeiro?mes={hoje:%Y-%m}").text
    assert fin.count('data-abrir="dlg-baixa"') == 4 and fin.count('id="dlg-baixa"') == 1       # A pagar e a receber + Livro-caixa, 2 lançamentos cada
    assert f'data-acao="/financeiro/lancamento/{lid}/baixa"' in fin and 'data-conta="Itaú"' in fin
    assert '/baixa" class="inline"' not in fin                                                  # nenhum botão baixa direto
    men = http.get(f"/financeiro/mensalidades?mes={hoje:%Y-%m}").text
    assert f'data-acao="/financeiro/lancamento/{aluno}/baixa"' in men and 'data-conta="Inter"' in men and men.count('id="dlg-baixa"') == 1
    assert "Dar baixa R$ 500,00" in men and '/baixa" class="inline"' not in men
    con.close()


def test_novo_lancamento_nao_pergunta_se_e_conta_recorrente(cliente_http):
    http, _ = cliente_http
    fin = http.get("/financeiro").text
    assert 'id="dlg-lanc"' in fin and "É uma conta recorrente" not in fin and '<select name="recorrencia_id"' not in fin
    assert '<input type="hidden" name="recorrencia_id"' in fin       # editar um lançamento já ligado não solta a conta recorrente


def test_editar_lancamento_de_conta_recorrente_mantem_o_vinculo(cliente_http):
    http, _ = cliente_http
    hoje = dt.date.today()
    base = {"volta": f"mes={hoje:%Y-%m}&escopo=todos"}
    http.post("/financeiro/recorrencia", data={**base, "escopo": "PJ", "descricao": "Aluguel", "categoria": "Outros", "valor": "500",
                                               "dia_vencimento": "5", "fixo": "1", "inicio": f"{hoje:%Y-%m}"}, follow_redirects=False)
    con = db.conectar()
    rid = con.execute("SELECT id FROM recorrencias").fetchone()[0]
    http.post("/financeiro/recorrencia/baixa", data={**base, "rid": rid, "competencia": f"{hoje:%Y-%m}", "valor": "500", "pago_em": hoje.isoformat()},
              follow_redirects=False)
    lid = con.execute("SELECT id FROM lancamentos").fetchone()[0]
    # o diálogo de edição manda recorrencia_id no campo escondido (data-recorrencia_id do botão Editar)
    http.post("/financeiro/lancamento", data={**base, "id": lid, "escopo": "PJ", "tipo": "saida", "data": hoje.isoformat(), "valor": "520",
                                              "categoria": "Outros", "pago_em": hoje.isoformat(), "recorrencia_id": rid}, follow_redirects=False)
    assert tuple(con.execute("SELECT valor, recorrencia_id FROM lancamentos WHERE id=?", (lid,)).fetchone()) == (520, rid)
    con.close()


def test_mensalidades_continua_com_o_dialogo_de_pagamento(cliente_http):
    http, cid = cliente_http
    con = db.conectar()
    aluno_renova(con, cid, dt.date.today().isoformat())
    men = http.get("/financeiro/mensalidades").text
    assert men.count('id="dlg-pgto"') == 1 and 'name="voltar"' in men and 'name="pago_em"' in men and 'name="conta"' in men
    assert 'data-abrir="dlg-pgto"' in men and f'data-cliente_id="{cid}"' in men and 'data-valor="500,00"' in men
    con.close()
