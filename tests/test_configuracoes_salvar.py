"""Salvar Configurações (issue #118): grava só o que mudou, num UPDATE só, sem arredondar o resto e sem gravação parcial."""
import html
import re

import pytest
from fastapi.testclient import TestClient

from app import db, main
from tests.test_locais import con  # noqa: F401  (banco temporário)


@pytest.fixture
def gravacoes(monkeypatch):
    """Comandos que mudam parametros, de todas as conexões que o app abre durante o teste."""
    feitos = []
    anota = lambda sql: feitos.append(sql) if re.match(r"\s*(UPDATE|INSERT|DELETE)\b.*parametros", sql, re.I | re.S) else None  # noqa: E731
    if db.nuvem.ativo():   # CRM_BANCO=libsql: o cliente não tem trace; anota pelo adaptador
        executar = db.nuvem.Conexao.execute
        monkeypatch.setattr(db.nuvem.Conexao, "execute", lambda self, sql, params=(): (anota(sql), executar(self, sql, params))[1])
        return feitos
    original = db.conectar

    def conectar(*a, **kw):
        c = original(*a, **kw)
        c.set_trace_callback(anota)
        return c
    monkeypatch.setattr(db, "conectar", conectar)
    return feitos


@pytest.fixture
def http(con, gravacoes):  # noqa: F811
    return TestClient(main.app, base_url="http://localhost")


def _formulario(texto: str) -> dict:
    """Os campos p_/f_/t_ como o navegador mandaria de volta, sem mexer em nada."""
    campos = {n: html.unescape(v) for n, v in re.findall(r'<input[^>]*name="([pft]_\d+)"[^>]*value="([^"]*)"', texto)}
    campos.update({n: html.unescape(v) for n, v in re.findall(r'<textarea name="(t_\d+)"[^>]*>(.*?)</textarea>', texto, re.S)})
    return campos


def _tudo(con):  # noqa: F811
    return con.execute("SELECT id, valor, valor_texto FROM parametros ORDER BY id").fetchall()


def _pid(con, grupo, chave):  # noqa: F811
    return con.execute("SELECT id FROM parametros WHERE grupo=? AND chave=?", (grupo, chave)).fetchone()[0]


@pytest.fixture
def precisos(con):  # noqa: F811
    """Valores com mais casas do que a tela mostra: reenviar o formulário não pode arredondá-los."""
    with con:
        con.execute("UPDATE parametros SET valor=0.123456 WHERE grupo='margem_minima' AND chave='Pacote de Aulas'")
        con.execute("UPDATE parametros SET valor=53.123456789 WHERE grupo='mao_obra' AND chave='valor_hora'")
    return {"pct": _pid(con, "margem_minima", "Pacote de Aulas"), "num": _pid(con, "mao_obra", "valor_hora")}


@pytest.mark.parametrize("tela", ["/configuracoes", "/calculos"])
def test_reenviar_sem_mudar_nao_grava_nada(http, con, gravacoes, precisos, tela):  # noqa: F811
    form = _formulario(http.get(tela).text)
    assert f"p_{precisos['pct']}" in form and form[f"p_{precisos['pct']}"] == "12,35"   # a tela arredonda...
    antes, gravacoes[:] = _tudo(con), []
    r = http.post("/configuracoes", data={**form, "voltar": tela}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"] and r.headers["location"].startswith(tela)
    assert gravacoes == []   # ...mas nada vai para o banco
    assert _tudo(con) == antes   # e o 0,123456 guardado continua igual


def test_mudanca_unica_grava_um_update_e_preserva_os_outros(http, con, gravacoes, precisos):  # noqa: F811
    form = _formulario(http.get("/configuracoes").text)
    pid = _pid(con, "taxa_pagamento", next(iter(db.parametros(con, "taxa_pagamento"))))
    antes, gravacoes[:] = {r["id"]: tuple(r) for r in _tudo(con)}, []
    r = http.post("/configuracoes", data={**form, f"p_{pid}": "3,5"}, follow_redirects=False)
    assert "msg=" in r.headers["location"]
    assert len(gravacoes) == 1   # um comando só, com a única linha que mudou
    depois = {r["id"]: tuple(r) for r in _tudo(con)}
    assert depois.pop(pid)[1] == pytest.approx(0.035)
    antes.pop(pid)
    assert depois == antes
    assert depois[precisos["pct"]][1] == 0.123456 and depois[precisos["num"]][1] == 53.123456789


def test_varias_mudancas_numero_e_texto_vao_num_update_so(http, con, gravacoes):  # noqa: F811
    pix, margem = _pid(con, "msg_dados", "pix"), _pid(con, "margem_minima", "Pacote de Aulas")
    r = http.post("/configuracoes", data={f"p_{margem}": "20", f"f_{margem}": "pct", f"t_{pix}": " chave@pix "},
                  follow_redirects=False)
    assert "msg=" in r.headers["location"] and len(gravacoes) == 1
    assert con.execute("SELECT valor FROM parametros WHERE id=?", (margem,)).fetchone()[0] == pytest.approx(0.20)
    assert db.parametros(con, "msg_dados")["pix"] == "chave@pix"


def test_mesmo_numero_escrito_de_outro_jeito_nao_regrava(http, con, gravacoes):  # noqa: F811
    pid = _pid(con, "mao_obra", "valor_hora")   # 53 na fixture
    http.post("/configuracoes", data={f"p_{pid}": "53,00", f"f_{pid}": "num"})
    assert gravacoes == []


def test_margem_invalida_nao_grava_nada(http, con, gravacoes):  # noqa: F811
    margem, taxa, pix = (_pid(con, "margem_minima", "Pacote de Aulas"),
                         _pid(con, "taxa_pagamento", next(iter(db.parametros(con, "taxa_pagamento")))), _pid(con, "msg_dados", "pix"))
    antes = _tudo(con)
    r = http.post("/configuracoes", data={f"p_{taxa}": "2", f"f_{taxa}": "pct", f"t_{pix}": "nova",
                                          f"p_{margem}": "99", f"f_{margem}": "pct", "voltar": "/calculos"}, follow_redirects=False)
    assert r.headers["location"].startswith("/calculos?erro=") and "100%25" in r.headers["location"]
    assert gravacoes == [] and _tudo(con) == antes


def test_numero_invalido_nao_grava_nada(http, con, gravacoes):  # noqa: F811
    taxa, pix = _pid(con, "taxa_pagamento", next(iter(db.parametros(con, "taxa_pagamento")))), _pid(con, "msg_dados", "pix")
    antes = _tudo(con)
    r = http.post("/configuracoes", data={f"t_{pix}": "nova", f"p_{taxa}": "abc", f"f_{taxa}": "pct"}, follow_redirects=False)
    assert "erro=" in r.headers["location"] and gravacoes == [] and _tudo(con) == antes


@pytest.mark.parametrize("voltar,destino", [("/calculos", "/calculos"), ("", "/configuracoes"),
                                            ("https://exemplo.com", "/configuracoes"), ("//exemplo.com", "/configuracoes")])
def test_destinos_continuam_os_mesmos(http, con, voltar, destino):  # noqa: F811
    pid = _pid(con, "mao_obra", "valor_hora")
    for valor in ("53", "54"):   # sem mudança e com mudança
        r = http.post("/configuracoes", data={f"p_{pid}": valor, f"f_{pid}": "num", "voltar": voltar}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].split("?")[0] == destino


def test_texto_em_grupo_que_nao_e_de_mensagem_continua_ignorado(http, con, gravacoes):  # noqa: F811
    pid = _pid(con, "taxa_pagamento", next(iter(db.parametros(con, "taxa_pagamento"))))
    http.post("/configuracoes", data={f"t_{pid}": "x"})
    assert gravacoes == [] and con.execute("SELECT valor_texto FROM parametros WHERE id=?", (pid,)).fetchone()[0] is None


@pytest.mark.parametrize("valor,fmt,tela", [(0.15, "pct", "15,0"), (0.123456, "pct", "12,35"), (53, "num", "53"),
                                            (53.123456789, "num", "53,1235"), (None, "num", "")])
def test_valor_tela_igual_ao_campo_antigo(valor, fmt, tela):
    assert main.valor_tela(valor, fmt) == tela


def test_duas_mudancas_validas_que_juntas_passam_de_100_sao_recusadas(http, con, monkeypatch):  # noqa: F811
    """Outro aparelho salva uma taxa alta entre a leitura e a gravação: a margem alta desta tela, válida sozinha, não pode entrar."""
    taxa = _pid(con, "taxa_pagamento", next(iter(db.parametros(con, "taxa_pagamento"))))
    margem = _pid(con, "margem_alvo", next(iter(db.parametros(con, "margem_alvo"))))
    gravar = main._gravar_mudancas_parametros

    def outro_aparelho_salva_antes(c, numeros, textos):
        outro = db.conectar()
        with outro:
            outro.execute("UPDATE parametros SET valor=0.5 WHERE id=?", (taxa,))
        outro.close()
        gravar(c, numeros, textos)
    monkeypatch.setattr(main, "_gravar_mudancas_parametros", outro_aparelho_salva_antes)
    antes = con.execute("SELECT valor FROM parametros WHERE id=?", (margem,)).fetchone()[0]
    r = http.post("/configuracoes", data={f"p_{margem}": "45", f"f_{margem}": "pct"}, follow_redirects=False)
    assert "erro=" in r.headers["location"] and "100%25" in r.headers["location"]
    assert con.execute("SELECT valor FROM parametros WHERE id=?", (margem,)).fetchone()[0] == antes   # a margem não entrou
    assert con.execute("SELECT valor FROM parametros WHERE id=?", (taxa,)).fetchone()[0] == 0.5   # a do outro aparelho fica
