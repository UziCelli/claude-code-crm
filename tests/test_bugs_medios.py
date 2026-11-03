"""Bugs médios: cores da Grade pela margem mínima, '&' no nome do local, margem mínima + taxas >= 100%,
inativo solta a Grade e o "+ Novo local" volta para a mesma tela."""
import pytest
from fastapi.testclient import TestClient

from app import main, precos
from tests.test_locais import con  # noqa: F401  (banco temporário com preços da CIA)


@pytest.fixture
def http(con):  # noqa: F811
    return TestClient(main.app, base_url="http://localhost")


@pytest.mark.parametrize("margem,minima,cor", [
    (0.16, 0.15, "verde"), (0.12, 0.15, "amarelo"), (0.09, 0.15, "vermelho"), (-0.01, 0.15, "prejuizo"),
    (0.27, 0.30, "amarelo"), (0.20, 0.30, "vermelho"), (0.30, 0.30, "verde"), (0.08, 0.08, "verde"), (None, 0.15, "neutro"),
])
def test_cor_segue_a_margem_minima(margem, minima, cor):
    assert precos.cor_margem(margem, minima) == cor


def test_legenda_da_grade_mostra_a_margem_minima_do_plano(http, con):  # noqa: F811
    with con:
        con.execute("UPDATE parametros SET valor=0.3 WHERE grupo='margem_minima' AND chave='Pacote de Aulas'")
    r = http.get("/grade", params={"tipo": "Pacotes", "local": "CIA"})
    assert r.status_code == 200 and "margem ≥ 30%" in r.text and "25–30%" in r.text


def test_margem_minima_mais_taxas_acima_de_100_vira_mensagem(con):  # noqa: F811
    p = precos.carregar_parametros(con)
    p["margens"]["Pacote de Aulas"] = 0.99
    base = dict(con.execute("SELECT * FROM precos_base WHERE tipo_servico='Pacote de Aulas'").fetchone())
    with pytest.raises(ValueError, match="100%"):
        precos.calcular(base, p)


def test_configuracoes_recusa_margem_minima_de_100(http, con):  # noqa: F811
    pid = con.execute("SELECT id FROM parametros WHERE grupo='margem_minima' AND chave='Pacote de Aulas'").fetchone()[0]
    r = http.post("/configuracoes", data={f"p_{pid}": "99", f"f_{pid}": "pct"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    assert con.execute("SELECT valor FROM parametros WHERE id=?", (pid,)).fetchone()[0] == pytest.approx(0.15)
    r = http.post("/configuracoes", data={f"p_{pid}": "20", f"f_{pid}": "pct"}, follow_redirects=False)
    assert "msg=" in r.headers["location"]
    assert con.execute("SELECT valor FROM parametros WHERE id=?", (pid,)).fetchone()[0] == pytest.approx(0.20)


def test_links_com_e_comercial_no_local_vao_codificados(http, con):  # noqa: F811
    with con:
        cid = con.execute("INSERT INTO clientes (nome, status, local) VALUES ('Ana', 'ativo', 'Corpo & Mente')").lastrowid
    r = http.get(f"/clientes/{cid}")
    assert "local=Corpo%20%26%20Mente" in r.text


def _celulas(con, cid):
    return con.execute("SELECT COUNT(*) FROM grade_slots WHERE cliente_id=? AND status='ocupado'", (cid,)).fetchone()[0]


def test_inativo_solta_a_grade_e_ativo_retoma(http, con):  # noqa: F811
    with con:
        cid = con.execute("INSERT INTO clientes (nome, status) VALUES ('Bia', 'ativo')").lastrowid
        con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?, 2, 8, 'CIA')", (cid,))
        con.execute("""INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador)
                       VALUES ('Pacotes', 2, 'CIA', 8, 'livre', 1), ('Mensalidades', 2, 'CIA', 8, 'livre', 1)""")
        main.grade_ocupar(con, cid, "Bia", 2, "CIA", 8)
    assert _celulas(con, cid) == 2
    http.post(f"/clientes/{cid}/status", data={"status": "inativo"}, follow_redirects=False)
    assert _celulas(con, cid) == 0
    assert con.execute("SELECT COUNT(*) FROM agenda_fixos WHERE cliente_id=? AND excluido_em IS NULL", (cid,)).fetchone()[0] == 1
    http.post(f"/clientes/{cid}/status", data={"status": "ativo"}, follow_redirects=False)
    assert _celulas(con, cid) == 2


def test_novo_local_volta_para_a_mesma_tela_sem_o_aviso_velho(http):
    r = http.post("/locais/novo", data={"nome": "Prédio", "voltar": "/agenda?semana=2026-11-02&msg=velho"}, follow_redirects=False)
    loc = r.headers["location"]
    assert loc.startswith("/agenda?semana=2026-11-02&msg=Local") and "velho" not in loc


def test_botao_novo_local_leva_a_url_atual(http):
    r = http.get("/agenda", params={"semana": "2026-11-02"})
    assert 'data-voltar="/agenda?semana=2026-11-02"' in r.text
