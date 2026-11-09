"""Auditoria de 16/10, D21: o servidor recusa o segundo envio igual (clique duplo com rede lenta) e restaurar da lixeira
o que já foi recriado. A trava do botão (app.js) destrava em 8 s: não basta."""
from urllib.parse import unquote

import pytest

from app import db
from tests.test_rotas import cliente_http  # noqa: F401  (fixture: cliente HTTP num banco temporário)

LANC = {"escopo": "PJ", "tipo": "saida", "data": "2026-11-03", "pago_em": "2026-11-03", "valor": "80,00", "categoria": "Outros",
        "descricao": "Conta X"}
REC = {"escopo": "PJ", "descricao": "Internet", "categoria": "Internet/Telefone", "valor": "120,00", "dia_vencimento": "10",
       "fixo": "1", "inicio": "2026-11"}


def conta(tabela, ativos=True):
    con = db.conectar()
    n = con.execute(f"SELECT COUNT(*) FROM {tabela}" + (" WHERE excluido_em IS NULL" if ativos else "")).fetchone()[0]
    con.close()
    return n


def sql(comando, *args):
    con = db.conectar()
    with con:
        con.execute(comando, args)
    con.close()


def enviar(http, url, dados):
    return unquote(http.post(url, data=dados, follow_redirects=False).headers["location"])


# ---------- clique duplo ----------
def test_lancamento_enviado_duas_vezes_grava_um_so(cliente_http):
    http, _ = cliente_http
    assert "Lançamento salvo" in enviar(http, "/financeiro/lancamento", LANC)
    volta = enviar(http, "/financeiro/lancamento", LANC)
    assert "msg=" in volta and "não criei outro" in volta and conta("lancamentos") == 1
    enviar(http, "/financeiro/lancamento", {**LANC, "valor": "81,00"})   # outro valor é outro lançamento
    assert conta("lancamentos") == 2


def test_pagamento_de_aluno_enviado_duas_vezes_grava_um_so(cliente_http):
    http, cid = cliente_http
    pgto = {**LANC, "tipo": "entrada", "categoria": "Pacotes de Aulas", "cliente_id": str(cid), "valor": "500,00"}
    enviar(http, "/financeiro/lancamento", pgto)
    assert "não criei outro" in enviar(http, "/financeiro/lancamento", pgto) and conta("lancamentos") == 1


def test_lancamento_igual_de_mais_tempo_atras_nao_e_envio_repetido(cliente_http):
    http, _ = cliente_http
    enviar(http, "/financeiro/lancamento", LANC)
    sql("UPDATE lancamentos SET criado_em=datetime('now','localtime','-5 minutes')")
    assert "Lançamento salvo" in enviar(http, "/financeiro/lancamento", LANC) and conta("lancamentos") == 2   # dois cafés no mesmo dia


def test_conta_recorrente_enviada_duas_vezes_grava_uma_so(cliente_http):
    http, _ = cliente_http
    assert "Conta recorrente salva" in enviar(http, "/financeiro/recorrencia", REC)
    volta = enviar(http, "/financeiro/recorrencia", REC)
    assert "msg=" in volta and "não criei outra" in volta and conta("recorrencias") == 1
    enviar(http, "/financeiro/recorrencia", {**REC, "descricao": "Internet do estúdio"})
    assert conta("recorrencias") == 2


def test_aluno_enviado_duas_vezes_grava_um_so(cliente_http):
    http, _ = cliente_http
    novo = {"nome": "Maria Dupla", "telefone": "11999990000"}
    primeira, segunda = enviar(http, "/clientes", novo), enviar(http, "/clientes", novo)
    assert "não criei outro" in segunda and primeira.split("?")[0] == segunda.split("?")[0]   # volta para a mesma ficha
    assert conta("clientes") == 2   # o da fixture + a Maria
    sql("UPDATE clientes SET criado_em=datetime('now','localtime','-5 minutes')")
    enviar(http, "/clientes", novo)   # homônimo cadastrado mais tarde é outra pessoa
    assert conta("clientes") == 3


# ---------- restaurar o que já foi recriado ----------
@pytest.mark.parametrize("tabela, url, dados", [("lancamentos", "/financeiro/lancamento", LANC), ("recorrencias", "/financeiro/recorrencia", REC),
                                                ("clientes", "/clientes", {"nome": "Maria Dupla"})])
def test_restaurar_o_que_ja_foi_recriado_pede_confirmacao(cliente_http, tabela, url, dados):
    http, _ = cliente_http
    enviar(http, url, dados)
    con = db.conectar()
    rid = con.execute(f"SELECT MAX(id) FROM {tabela}").fetchone()[0]
    con.close()
    sql(f"UPDATE {tabela} SET excluido_em=datetime('now','localtime','-1 hour') WHERE id=?", rid)
    antes = conta(tabela)
    assert "erro=" not in enviar(http, url, dados) and conta(tabela) == antes + 1          # recriou à mão
    volta = enviar(http, "/lixeira/restaurar", {"tabela": tabela, "rid": str(rid)})
    assert "erro=" in volta and "em dobro" in volta and conta(tabela) == antes + 1           # recusou: nada em dobro
    pagina = http.get(volta).text
    assert "Restaurar mesmo assim" in pagina and 'name="forcar" value="1"' in pagina
    volta = enviar(http, "/lixeira/restaurar", {"tabela": tabela, "rid": str(rid), "forcar": "1"})
    assert "erro=" not in volta and conta(tabela) == antes + 2                               # é outro mesmo: você manda


def test_restaurar_sem_nada_igual_valendo_segue_direto(cliente_http):
    http, cid = cliente_http
    sql("UPDATE clientes SET excluido_em=datetime('now','localtime') WHERE id=?", cid)
    assert "erro=" not in enviar(http, "/lixeira/restaurar", {"tabela": "clientes", "rid": str(cid)}) and conta("clientes") == 1
