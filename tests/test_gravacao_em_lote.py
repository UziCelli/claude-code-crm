"""Regra do AGENTS.md (filas do banco): no modo nuvem (Turso) cada instrução é uma ida ao servidor com o banco travado.
Importar fatura/extrato grava em lote, e nenhuma rota que usa o banco é "async def" (travava o servidor: 502/503)."""
import inspect

import pytest
from fastapi.routing import APIRoute

from app import db, extrato, faturas, main


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    db.iniciar_banco(tmp_path / "crm.db")
    c = db.conectar(tmp_path / "crm.db")
    yield c
    c.close()


def _gravacoes(con, fazer):
    sqls = []
    con.set_trace_callback(lambda s: sqls.append(s) if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) else None)
    try:
        r = fazer()
    finally:
        con.set_trace_callback(None)
    return r, sqls


def _fatura(n):
    compras = [{"chave": f"Cartão Inter:2026-11-25:1111:2026-11-{1 + i % 28:02d}:{100 + i}:LOJA {i}:1", "cartao": "1111",
                "data": f"2026-11-{1 + i % 28:02d}", "descricao": f"LOJA {i}", "valor": 1.0 + i, "parcela_num": None, "parcela_total": None,
                "categoria": "Outros", "categoria_sugerida": "Outros", "ramo": None, "nota": None} for i in range(n)]
    compras[0]["categoria"] = "Mercado"   # uma corrigida: vira regra
    return {"conta": "Cartão Inter", "vencimento": "2026-11-25", "fechamento": "2026-11-18", "total": 100.0, "limite_total": 1000.0,
            "limite_usado": 100.0, "limite_disponivel": 900.0, "arquivo": "f.pdf", "compras": compras}


def test_fatura_grande_grava_em_poucas_instrucoes(con):
    r, sqls = _gravacoes(con, lambda: faturas.salvar(con, [_fatura(300)], set()))
    assert (r["compras"], r["existentes"], r["regras"]) == (300, 0, 1)
    assert con.execute("SELECT COUNT(*) FROM cartao_compras").fetchone()[0] == 300
    assert len(sqls) <= 8, sqls   # antes: uma instrução por compra (300+)
    r, sqls = _gravacoes(con, lambda: faturas.salvar(con, [_fatura(300)], set()))   # de novo: nada duplica
    assert (r["compras"], r["existentes"], r["atualizadas"]) == (0, 300, 1) and len(sqls) <= 4


def _linhas(n):
    return [{"origem": f"OFX:Inter:k{i}", "conta": "Inter", "escopo": "PF", "tipo": "saida", "data": "2026-11-10", "valor": 10.0 + i,
             "descricao": f"COMPRA {i}", "contraparte": None, "forma": None, "cliente_id": None, "categoria": "Outros",
             "categoria_sugerida": "Outros", "emprestimo": False, "acao": "ignorar" if i % 10 == 0 else "novo"} for i in range(n)]


def test_extrato_grande_grava_em_poucas_instrucoes(con):
    r, sqls = _gravacoes(con, lambda: extrato.salvar(con, _linhas(300), [{"conta": "Inter", "saldo": 50.0, "data": "2026-11-10"}]))
    assert (r["novos"], r["ignorados"], r["saldos"]) == (270, 30, 1)
    assert con.execute("SELECT COUNT(*) FROM lancamentos WHERE origem LIKE 'OFX:Inter:%'").fetchone()[0] == 270
    assert len(sqls) <= 8, sqls   # antes: uma ou duas instruções por linha (500+)
    r, _ = _gravacoes(con, lambda: extrato.salvar(con, _linhas(300), []))
    assert r["novos"] == 0 and r["pulados"] + r["existentes"] == 270


def test_ignorado_antes_e_lancado_agora_sai_da_lista_de_ignorados(con):
    linhas = _linhas(2)
    extrato.salvar(con, [{**linhas[1], "acao": "ignorar"}], [])
    extrato.salvar(con, [linhas[1]], [])
    assert "OFX:Inter:k1" not in db.parametros(con, extrato.GRUPO_IGNORADO)


def test_nenhuma_rota_com_banco_e_async():
    """Rota "async def" roda no laço do servidor: enquanto ela espera o banco, nenhuma outra página (nem o /saude) responde.
    Formulário: Depends(main.formulario(...)) antes do banco, e a rota é "def"."""
    def deps(d):
        for x in d.dependencies:
            yield x.call
            yield from deps(x)
    for rota in main.app.routes:
        if isinstance(rota, APIRoute) and {main.get_db, main.get_db_previa} & set(deps(rota.dependant)):
            assert not inspect.iscoroutinefunction(rota.endpoint), f"{rota.path} é async def e usa o banco"


def test_inserir_varios_divide_em_blocos(con):
    linhas = [("teste_lote", f"c{i}", i, 0) for i in range(1000)]
    _, sqls = _gravacoes(con, lambda: db.inserir_varios(con, "INSERT INTO parametros (grupo, chave, valor, ordem)", linhas))
    assert len(sqls) == 5   # 900 parâmetros por instrução / 4 colunas = 225 linhas
    assert con.execute("SELECT COUNT(*) FROM parametros WHERE grupo='teste_lote'").fetchone()[0] == 1000
