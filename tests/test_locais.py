"""+ Novo local: grava os custos do local (taxas, deslocamento) e copia a grade. O preço não fica guardado: o motor lê os custos."""
import pytest
from fastapi.testclient import TestClient

from app import db, locais, main, precos


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    c = db.conectar()
    with c:
        c.execute("UPDATE parametros SET valor=0 WHERE grupo='mao_obra' AND chave='valor_hora_auto'")
        c.execute("UPDATE parametros SET valor=53 WHERE grupo='mao_obra' AND chave='valor_hora'")
        c.execute("""INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador)
                     VALUES ('Pacotes', 1, 'CIA', 7, 'ocupado', 0.86), ('Pacotes', 3, 'CIA', 19, 'livre', 1.2)""")
    yield c
    c.close()


def _pacote(con, local, qtd=8, **kw):
    p = precos.carregar_parametros(con)
    return precos.calcular(precos.base_motor("Pacote de Aulas", qtd, local=local), p, **kw), p


def test_cria_o_local_com_os_custos_e_sem_preco_guardado(con):
    r = locais.criar_local(con, "Prédio", "CIA", taxa_aula=30, deslocamento=10)
    assert r == {"horarios": 2}
    assert con.execute("SELECT COUNT(*) FROM precos_base").fetchone()[0] == 0
    assert locais.custo_aula_local(con, "Prédio") == 40
    assert "Prédio" in db.lista(con, "lista_locais")
    r, p = _pacote(con, "Prédio")
    horas = (8 * 60 + 60) / 60
    assert r["custo_total"] == pytest.approx(40 * 8 + horas * 53 + horas * p["rateio_hora"], abs=0.01)
    assert r["margem"] == pytest.approx(p["margens_alvo"]["Pacote de Aulas"], abs=0.001)


def test_taxa_mensal_divide_pelas_aulas_e_exige_quantas(con):
    with pytest.raises(ValueError, match="quantas aulas"):
        locais.criar_local(con, "Cond", taxa_mensal=200)
    locais.criar_local(con, "Cond", "CIA", taxa_mensal=200, aulas_mes=20)
    assert locais.custo_aula_local(con, "Cond") == 10


def test_grade_copia_horarios_livres(con):
    r = locais.criar_local(con, "Prédio", taxa_aula=30)
    assert r["horarios"] == 2
    slots = {(s["dia"], s["hora"]): (s["status"], s["multiplicador"])
             for s in con.execute("SELECT * FROM grade_slots WHERE local='Prédio'")}
    assert slots == {(1, 7): ("livre", 0.86), (3, 19): ("livre", 1.2)}


def test_sem_grade_na_referencia_cria_seg_a_sab(con):
    with con:
        con.execute("DELETE FROM grade_slots")
    r = locais.criar_local(con, "Prédio")
    assert r["horarios"] == 2 * 6 * 19


def test_cia_repetido_e_nome_vazio_dao_erro(con):
    with pytest.raises(ValueError, match="CIA já existe"):
        locais.criar_local(con, "cia")
    with pytest.raises(ValueError, match="nome"):
        locais.criar_local(con, "  ")
    locais.criar_local(con, "Prédio")
    with pytest.raises(ValueError, match="'Prédio' já existe"):
        locais.criar_local(con, "predio ")


def test_local_da_planilha_pode_ganhar_custos(con):
    """SmartFit vinha só da planilha (sem custos): agora dá para criar e o motor passa a cobrar a taxa dele."""
    with con:
        con.execute("INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem) VALUES ('lista_locais','SmartFit','SmartFit',99)")
    antes, _ = _pacote(con, "SmartFit")
    locais.criar_local(con, "SmartFit", taxa_aula=20)
    depois, _ = _pacote(con, "SmartFit")
    assert depois["custo_total"] == pytest.approx(antes["custo_total"] + 20 * 8, abs=0.01)


def test_maximo_de_pessoas_e_pessoa_extra(con):
    locais.criar_local(con, "Studio", taxa_aula=30, taxa_pessoa_extra=15, max_pessoas=2)
    um, _ = _pacote(con, "Studio")
    dois, _ = _pacote(con, "Studio", pessoas=2)
    assert dois["custo_total"] - um["custo_total"] >= 15 * 8
    with pytest.raises(ValueError, match="máximo é 2"):
        _pacote(con, "Studio", pessoas=3)


def test_tempo_de_deslocamento_e_trabalho_pago(con):
    """30 min de deslocamento por aula = 4 h a mais no pacote de 8: entram no pró-labore, no rateio e nas horas."""
    locais.criar_local(con, "A", "CIA", taxa_aula=40)
    locais.criar_local(con, "B", "CIA", taxa_aula=40, tempo_deslocamento=30)
    a, p = _pacote(con, "A")
    b, _ = _pacote(con, "B")
    assert b["horas"] == pytest.approx(a["horas"] + 4)
    assert b["mao_obra"] - a["mao_obra"] == pytest.approx(4 * 53, abs=0.01)
    assert b["custo_total"] - a["custo_total"] == pytest.approx(4 * (53 + p["rateio_hora"]), abs=0.01)
    assert b["preco_cheio"] > a["preco_cheio"]


def test_local_sem_taxa_nao_nasce_no_prejuizo(con):
    """O caso da academia sem taxa: o preço sai do custo (pró-labore + deslocamento), então a margem é a de tabela."""
    locais.criar_local(con, "Barata", "CIA", tempo_deslocamento=30)
    r, p = _pacote(con, "Barata")
    assert r["lucro"] > 0
    assert r["margem"] == pytest.approx(p["margens_alvo"]["Pacote de Aulas"], abs=0.001)


def test_editar_local_muda_o_preco_na_hora(con):
    locais.criar_local(con, "Prédio", taxa_aula=10)
    antes, _ = _pacote(con, "Prédio")
    locais.editar_local(con, "Prédio", taxa_aula=30)
    depois, _ = _pacote(con, "Prédio")
    assert depois["custo_total"] == pytest.approx(antes["custo_total"] + 20 * 8, abs=0.01)


@pytest.fixture
def http(con):
    return TestClient(main.app, base_url="http://localhost")


@pytest.mark.parametrize("tela", ["/grade", "/agenda", "/propostas"])
def test_botao_novo_local_nas_tres_telas(http, tela):
    r = http.get(tela)
    assert r.status_code == 200
    assert 'data-abrir="dlg-local"' in r.text and 'id="dlg-local"' in r.text
    assert "Manter a margem" not in r.text and 'value="custo"' not in r.text


def test_rota_cria_e_volta_para_a_grade_do_local(http, con):
    r = http.post("/locais/novo", data={"nome": "Prédio Azul", "taxa_aula": "30,50", "deslocamento": "10", "voltar": "/grade"},
                  follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/grade?local=Pr%C3%A9dio%20Azul&msg=")
    assert con.execute("SELECT taxa_aula FROM locais_custos WHERE local='Prédio Azul'").fetchone()[0] == 30.5
    g = http.get("/grade", params={"local": "Prédio Azul"})
    assert "<option selected>Prédio Azul</option>" in g.text


def test_rota_erro_volta_para_a_tela_com_a_frase(http):
    r = http.post("/locais/novo", data={"nome": "CIA", "voltar": "/propostas"}, follow_redirects=False)
    assert r.headers["location"].startswith("/propostas?erro=")
    r = http.post("/locais/novo", data={"nome": "X", "voltar": "https://mal.com"}, follow_redirects=False)
    assert r.headers["location"].startswith("/grade")


def test_referencia_so_cia_ou_local_criado_aqui(con):
    with pytest.raises(ValueError, match="CIA ou um local criado aqui"):
        locais.criar_local(con, "Novo", "SmartFit")
    locais.criar_local(con, "Prédio", taxa_aula=30)
    assert locais.referencias(con) == ["CIA", "Prédio"]
    assert locais.criar_local(con, "Prédio 2", "Prédio")["horarios"] == 2


def test_dialogo_so_oferece_bases_validas(http, con):
    with con:
        con.execute("INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem) VALUES ('lista_locais','SmartFit','SmartFit',99)")
    t = http.get("/grade").text
    dlg = t[t.index('id="dlg-local"'):]
    sel = dlg[dlg.index('name="referencia"'):dlg.index("</select>", dlg.index('name="referencia"'))]
    assert "<option selected>CIA</option>" in sel and "SmartFit" not in sel
