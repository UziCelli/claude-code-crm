"""Editar e excluir um local criado pelo "+ Novo local" (Grade)."""
import pytest
from fastapi.testclient import TestClient

from app import db, locais, main
from tests.test_locais import _base, con  # noqa: F401  (banco temporário com preços da CIA)


@pytest.fixture
def http(con):  # noqa: F811
    return TestClient(main.app, base_url="http://localhost")


def test_editar_refaz_os_precos_pela_diferenca_do_custo(con):  # noqa: F811
    locais.criar_local(con, "Prédio", "CIA", "margem", taxa_aula=30, deslocamento=10)
    antes = _base(con, "Prédio")
    r = locais.editar_local(con, "Prédio", "margem", taxa_aula=40, deslocamento=10)
    depois = _base(con, "Prédio")
    custo = antes["custo_operacional"] + 10 * 8
    assert r["precos"] == 1
    assert depois["custo_operacional"] == pytest.approx(custo, abs=0.01)
    assert depois["preco_base"] == pytest.approx(antes["preco_base"] * custo / antes["custo_operacional"], abs=0.02)
    assert con.execute("SELECT taxa_aula FROM locais_custos WHERE local='Prédio'").fetchone()[0] == 40


def test_editar_mantendo_o_preco(con):  # noqa: F811
    locais.criar_local(con, "Prédio", "CIA", "margem", taxa_aula=30)
    preco = _base(con, "Prédio")["preco_base"]
    locais.editar_local(con, "Prédio", "preco", taxa_aula=50)
    assert _base(con, "Prédio")["preco_base"] == preco


def test_cia_e_local_da_planilha_nao_editam(con):  # noqa: F811
    with pytest.raises(ValueError, match="Novo local"):
        locais.editar_local(con, "CIA", "margem", taxa_aula=1)
    with pytest.raises(ValueError, match="Novo local"):
        locais.excluir_local(con, "Outro")


def test_excluir_recusa_com_aluno_e_apaga_sem(con):  # noqa: F811
    locais.criar_local(con, "Prédio", "CIA", "margem", taxa_aula=30)
    with con:
        cid = con.execute("INSERT INTO clientes (nome, status, local) VALUES ('Ana', 'ativo', 'Prédio')").lastrowid
    with pytest.raises(ValueError, match="em uso"):
        locais.excluir_local(con, "Prédio")
    with con:
        con.execute("UPDATE clientes SET status='inativo' WHERE id=?", (cid,))
    locais.excluir_local(con, "Prédio")
    for t in ("precos_base", "grade_slots", "locais_custos"):
        assert con.execute(f"SELECT COUNT(*) FROM {t} WHERE local='Prédio'").fetchone()[0] == 0
    assert "Prédio" not in db.lista(con, "lista_locais")
    assert _base(con, "CIA")["preco_base"] == 1100


def test_grade_mostra_editar_so_em_local_criado_aqui(http, con):  # noqa: F811
    locais.criar_local(con, "Prédio", "CIA", "margem", taxa_aula=30.5)
    r = http.get("/grade", params={"local": "Prédio"})
    assert 'data-acao="/locais/editar"' in r.text and 'data-taxa_aula="30,50"' in r.text and "Excluir local" in r.text
    assert "Editar local" not in http.get("/grade", params={"local": "CIA"}).text


def test_rotas_editar_e_excluir(http, con):  # noqa: F811
    locais.criar_local(con, "Prédio", "CIA", "margem", taxa_aula=30)
    r = http.post("/locais/editar", data={"nome": "Prédio", "modo": "margem", "taxa_aula": "45,5"}, follow_redirects=False)
    assert "msg=" in r.headers["location"]
    assert con.execute("SELECT taxa_aula FROM locais_custos WHERE local='Prédio'").fetchone()[0] == 45.5
    r = http.post("/locais/excluir", data={"nome": "Prédio"}, follow_redirects=False)
    assert r.headers["location"].startswith("/grade?msg=")
