"""+ Novo local: custos do local (taxas, deslocamento), preços copiados da referência (mantendo margem ou preço) e a grade."""
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
        c.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, preco_base,
                     custo_operacional, mao_obra, custo_total, sessoes_mes) VALUES ('Pacote de Aulas', 'CIA', 'PIX', 8, 0, 1100, 900, 415.5, 900, 8)""")
        c.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, preco_base,
                     custo_operacional, mao_obra, custo_total, sessoes_mes) VALUES ('Avaliação', 'CIA', 'PIX', 0, 0, 150, 0, 0, 0, 1)""")
        c.execute("""INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador)
                     VALUES ('Pacotes', 1, 'CIA', 7, 'ocupado', 0.86), ('Pacotes', 3, 'CIA', 19, 'livre', 1.2)""")
    yield c
    c.close()


def _base(con, local):
    return dict(con.execute("SELECT * FROM precos_base WHERE local=? AND tipo_servico='Pacote de Aulas'", (local,)).fetchone())


def test_manter_a_margem_baixa_preco_e_custo_juntos(con):
    taxa_cia = precos.taxas_cia(con)[0][1]
    r = locais.criar_local(con, "Prédio", "CIA", "margem", taxa_aula=30, deslocamento=10)
    assert r["precos"] == 1   # só planos com aula; a Avaliação não vem
    b = _base(con, "Prédio")
    custo = 900 + (40 - taxa_cia) * 8
    assert b["custo_operacional"] == pytest.approx(custo, abs=0.01)
    assert b["preco_base"] == pytest.approx(1100 * custo / 900, abs=0.01)
    assert b["origem"] == "local:CIA"
    p = precos.carregar_parametros(con)
    m_cia = precos.calcular(_base(con, "CIA"), p)["margem"]
    assert precos.calcular(b, p)["margem"] == pytest.approx(m_cia, abs=0.001)
    assert "Prédio" in db.lista(con, "lista_locais")


def test_manter_o_preco_so_muda_a_margem(con):
    locais.criar_local(con, "Longe", "CIA", "preco", taxa_aula=70.76, deslocamento=25)
    b = _base(con, "Longe")
    assert b["preco_base"] == 1100
    p = precos.carregar_parametros(con)
    assert precos.calcular(b, p)["margem"] < precos.calcular(_base(con, "CIA"), p)["margem"]


def test_taxa_mensal_divide_pelas_aulas_e_exige_quantas(con):
    with pytest.raises(ValueError, match="quantas aulas"):
        locais.criar_local(con, "Cond", taxa_mensal=200)
    locais.criar_local(con, "Cond", "CIA", "preco", taxa_mensal=200, aulas_mes=20)
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


def test_local_que_ja_tem_preco_e_nome_vazio_dao_erro(con):
    with pytest.raises(ValueError, match="já tem preços"):
        locais.criar_local(con, "CIA")
    with pytest.raises(ValueError, match="nome"):
        locais.criar_local(con, "  ")


def test_maximo_de_pessoas_e_pessoa_extra(con):
    locais.criar_local(con, "Studio", taxa_aula=30, taxa_pessoa_extra=15, max_pessoas=2)
    p = precos.carregar_parametros(con)
    b = _base(con, "Studio")
    um, dois = precos.calcular(b, p, pessoas=1), precos.calcular(b, p, pessoas=2)
    assert dois["custo_total"] - um["custo_total"] >= 15 * 8
    with pytest.raises(ValueError, match="máximo é 2"):
        precos.calcular(b, p, pessoas=3)


def test_tempo_de_deslocamento_baixa_o_lucro_por_hora(con):
    locais.criar_local(con, "A", "CIA", "preco", taxa_aula=40)
    locais.criar_local(con, "B", "CIA", "preco", taxa_aula=40, tempo_deslocamento=30)
    p = precos.carregar_parametros(con)
    a, b = precos.calcular(_base(con, "A"), p), precos.calcular(_base(con, "B"), p)
    assert a["lucro"] == b["lucro"]
    assert b["lucro_hora"] == pytest.approx(a["lucro_hora"] / 1.5, abs=0.01)


@pytest.fixture
def http(con):
    return TestClient(main.app, base_url="http://localhost")


@pytest.mark.parametrize("tela", ["/grade", "/agenda", "/propostas"])
def test_botao_novo_local_nas_tres_telas(http, tela):
    r = http.get(tela)
    assert r.status_code == 200
    assert 'data-abrir="dlg-local"' in r.text and 'id="dlg-local"' in r.text
    assert "Manter a margem" in r.text and "Manter o preço" in r.text


def test_rota_cria_e_volta_para_a_grade_do_local(http, con):
    r = http.post("/locais/novo", data={"nome": "Prédio Azul", "taxa_aula": "30,50", "deslocamento": "10", "modo": "margem",
                                        "voltar": "/grade"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/grade?local=Pr%C3%A9dio%20Azul&msg=")
    assert con.execute("SELECT taxa_aula FROM locais_custos WHERE local='Prédio Azul'").fetchone()[0] == 30.5
    g = http.get("/grade", params={"local": "Prédio Azul"})
    assert "<option selected>Prédio Azul</option>" in g.text


def test_rota_erro_volta_para_a_tela_com_a_frase(http):
    r = http.post("/locais/novo", data={"nome": "CIA", "voltar": "/propostas"}, follow_redirects=False)
    assert r.headers["location"].startswith("/propostas?erro=")
    r = http.post("/locais/novo", data={"nome": "X", "voltar": "https://mal.com"}, follow_redirects=False)
    assert r.headers["location"].startswith("/grade")


def test_nome_igual_com_outra_caixa_da_erro(con):
    with pytest.raises(ValueError, match="'CIA' já tem preços"):
        locais.criar_local(con, "cia")


def test_base_so_cia_ou_local_criado_aqui(con):
    with con:   # local da planilha: a taxa dele está dentro do custo, copiar cobraria duas vezes
        con.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, preco_base,
                     custo_operacional, mao_obra, custo_total, sessoes_mes) VALUES ('Pacote de Aulas', 'SmartFit', 'PIX', 8, 0, 932, 736, 415.5, 736, 8)""")
    with pytest.raises(ValueError, match="CIA ou um local criado aqui"):
        locais.criar_local(con, "Novo", "SmartFit")
    locais.criar_local(con, "Prédio", taxa_aula=30)
    assert locais.referencias(con) == ["CIA", "Prédio"]
    locais.criar_local(con, "Prédio 2", "Prédio", "preco", taxa_aula=30)
    assert _base(con, "Prédio 2")["custo_operacional"] == _base(con, "Prédio")["custo_operacional"]


def test_dialogo_so_oferece_bases_validas(http, con):
    with con:
        con.execute("INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem) VALUES ('lista_locais','SmartFit','SmartFit',99)")
    t = http.get("/grade").text
    dlg = t[t.index('id="dlg-local"'):]
    sel = dlg[dlg.index('name="referencia"'):dlg.index("</select>", dlg.index('name="referencia"'))]
    assert "<option selected>CIA</option>" in sel and "SmartFit" not in sel
