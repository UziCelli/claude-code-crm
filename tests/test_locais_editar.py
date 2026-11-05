"""Editar e excluir um local criado pelo "+ Novo local" (Grade)."""
import pytest
from fastapi.testclient import TestClient

from app import db, locais, main
from tests.test_locais import _pacote, con  # noqa: F401  (banco temporário, hora fixa de R$ 53)


@pytest.fixture
def http(con):  # noqa: F811
    return TestClient(main.app, base_url="http://localhost")


def test_editar_grava_os_custos_e_o_preco_acompanha(con):  # noqa: F811
    locais.criar_local(con, "Prédio", "CIA", taxa_aula=30, deslocamento=10)
    antes, _ = _pacote(con, "Prédio")
    locais.editar_local(con, "Prédio", taxa_aula=40, deslocamento=10)
    depois, _ = _pacote(con, "Prédio")
    assert con.execute("SELECT taxa_aula FROM locais_custos WHERE local='Prédio'").fetchone()[0] == 40
    assert depois["custo_total"] == pytest.approx(antes["custo_total"] + 10 * 8, abs=0.01)
    assert depois["margem"] == pytest.approx(antes["margem"], abs=0.001)   # o preço de tabela sobe junto


def test_cia_e_local_da_planilha_nao_editam(con):  # noqa: F811
    with pytest.raises(ValueError, match="Novo local"):
        locais.editar_local(con, "CIA", taxa_aula=1)
    with pytest.raises(ValueError, match="Novo local"):
        locais.excluir_local(con, "Outro")


def test_excluir_recusa_com_aluno_e_apaga_sem(con):  # noqa: F811
    locais.criar_local(con, "Prédio", "CIA", taxa_aula=30)
    with con:
        cid = con.execute("INSERT INTO clientes (nome, status, local) VALUES ('Ana', 'ativo', 'Prédio')").lastrowid
    with pytest.raises(ValueError, match="em uso"):
        locais.excluir_local(con, "Prédio")
    with con:
        con.execute("UPDATE clientes SET status='inativo' WHERE id=?", (cid,))
    locais.excluir_local(con, "Prédio")
    for t in ("grade_slots", "locais_custos"):
        assert con.execute(f"SELECT COUNT(*) FROM {t} WHERE local='Prédio'").fetchone()[0] == 0
    assert "Prédio" not in db.lista(con, "lista_locais")
    assert con.execute("SELECT COUNT(*) FROM grade_slots WHERE local='CIA'").fetchone()[0] == 2


def test_grade_mostra_editar_so_em_local_criado_aqui(http, con):  # noqa: F811
    locais.criar_local(con, "Prédio", "CIA", taxa_aula=30.5)
    r = http.get("/grade", params={"local": "Prédio"})
    assert 'data-acao="/locais/editar"' in r.text and 'data-taxa_aula="30,50"' in r.text and "Excluir local" in r.text
    assert "Editar local" not in http.get("/grade", params={"local": "CIA"}).text


def test_rotas_editar_e_excluir(http, con):  # noqa: F811
    locais.criar_local(con, "Prédio", "CIA", taxa_aula=30)
    r = http.post("/locais/editar", data={"nome": "Prédio", "taxa_aula": "45,5"}, follow_redirects=False)
    assert "msg=" in r.headers["location"]
    assert con.execute("SELECT taxa_aula FROM locais_custos WHERE local='Prédio'").fetchone()[0] == 45.5
    r = http.post("/locais/excluir", data={"nome": "Prédio"}, follow_redirects=False)
    assert r.headers["location"].startswith("/grade?msg=")
