"""Editar e excluir qualquer local na Grade (os do "+ Novo local" e os da lista, como SmartFit), a CIA no mesmo pop-up e a prévia do preço."""
import pytest
from fastapi.testclient import TestClient

from app import contas_auto, db, financeiro, locais, main, precos
from tests.test_contas_automaticas import aluno, marca
from tests.test_locais import _pacote, con  # noqa: F401  (banco temporário, hora fixa de R$ 53)
from tests.test_rateio_fixos import conta


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


def test_cia_nao_exclui_e_local_que_nao_existe_nao_edita(con):  # noqa: F811
    with pytest.raises(ValueError, match="CIA não dá para excluir"):
        locais.excluir_local(con, "cia")
    with pytest.raises(ValueError, match="não existe"):
        locais.excluir_local(con, "Outro")
    with pytest.raises(ValueError, match="não existe"):
        locais.editar_local(con, "Outro", taxa_aula=1)


def test_editar_local_da_lista_cria_os_custos_e_o_preco_acompanha(con):  # noqa: F811
    """SmartFit vem da lista inicial, sem custos: o Editar local cria a linha e o preço passa a cobrar a taxa e a ida."""
    assert "SmartFit" in db.lista(con, "lista_locais") and "SmartFit" not in precos.custos_locais(con)
    antes, _ = _pacote(con, "SmartFit")
    r = locais.editar_local(con, "SmartFit", taxa_aula=20, deslocamento=5)
    depois, _ = _pacote(con, "SmartFit")
    assert precos.custos_locais(con)["SmartFit"]["taxa_aula"] == 20
    assert depois["custo_total"] == pytest.approx(antes["custo_total"] + 25 * 8, abs=0.01)
    assert depois["preco_total"] > antes["preco_total"]
    assert r["horarios"] == 2   # sem grade: copia a da CIA (2 horários na fixture), todos livres
    assert {s[0] for s in con.execute("SELECT status FROM grade_slots WHERE local='SmartFit'")} == {"livre"}
    assert locais.editar_local(con, "SmartFit", taxa_aula=25)["horarios"] == 0   # a grade que já existe fica


def test_excluir_local_da_lista_e_ele_nao_volta(con):  # noqa: F811
    locais.editar_local(con, "SmartFit", taxa_aula=20)
    with con:
        cid = con.execute("INSERT INTO clientes (nome, status, local) VALUES ('Ana', 'ativo', 'SmartFit')").lastrowid
    with pytest.raises(ValueError, match="em uso"):
        locais.excluir_local(con, "SmartFit")
    with con:
        con.execute("UPDATE clientes SET status='inativo' WHERE id=?", (cid,))
    locais.excluir_local(con, "SmartFit")
    assert "SmartFit" not in locais.nomes(con) and "SmartFit" not in precos.custos_locais(con)
    db.iniciar_banco()   # o app abrindo de novo não põe a SmartFit de volta na lista
    assert "SmartFit" not in db.lista(con, "lista_locais")
    locais.criar_local(con, "SmartFit", taxa_aula=10)   # e dá para criar de novo
    assert "SmartFit" in db.lista(con, "lista_locais")


def test_remover_da_lista_em_configuracoes_nao_volta(http, con):  # noqa: F811
    pid = con.execute("SELECT id FROM parametros WHERE grupo='lista_locais' AND chave='Condomínio'").fetchone()[0]
    http.post(f"/configuracoes/lista/{pid}/remover", follow_redirects=False)
    db.iniciar_banco()
    assert "Condomínio" not in db.lista(con, "lista_locais")


def test_novo_local_com_nome_parecido_recusa(con):  # noqa: F811
    with pytest.raises(ValueError, match="'SmartFit' já existe"):
        locais.criar_local(con, "Smart Fit", taxa_aula=10)
    locais.criar_local(con, "SmartFit", taxa_aula=10)   # o mesmo nome, ainda sem custos: ganha os custos
    with pytest.raises(ValueError, match="já existe"):
        locais.criar_local(con, "smartfit", taxa_aula=10)


def test_editar_local_da_cia_usa_os_mesmos_campos_e_grava_nos_parametros(con):  # noqa: F811
    """A CIA usa o Editar local de todo local; a pessoa a mais vira o preço da aula com 2 e 3 pessoas (grupo)."""
    antes, _ = _pacote(con, "CIA")
    r = locais.editar_local(con, "CIA", {2: 110, 3: 160}, taxa_aula=80, max_pessoas=3, deslocamento=4, tempo_deslocamento=10)
    assert r == {"horarios": 0}
    assert precos.taxas_cia(con) == ({1: 80, 2: 110, 3: 160}, 3)
    assert db.parametros(con, "cia_deslocamento") == {"reais_por_aula": 4, "minutos_por_aula": 10}
    assert locais.cia_atual(con) == {"taxa_aula": 80, "grupo": {2: 110, 3: 160}, "max_pessoas": 3, "deslocamento": 4,
                                     "tempo_deslocamento": 10, "taxa_mensal": 0, "aulas_mes": 0}
    depois, _ = _pacote(con, "CIA")
    assert depois["custo_total"] > antes["custo_total"] + (80 - 70.76 + 4) * 8 - 0.01
    locais.editar_local(con, "cia", None, taxa_aula=85, max_pessoas=3)   # sem grupo: 2 e 3 pessoas ficam como estão
    assert precos.taxas_cia(con) == ({1: 85, 2: 110, 3: 160}, 3)
    erros = [({}, {"taxa_aula": 0, "max_pessoas": 3}, "1 pessoa"), ({2: 0}, {"taxa_aula": 80, "max_pessoas": 3}, "2 pessoas"),
             ({}, {"taxa_aula": 80, "max_pessoas": 0}, "pelo menos 1"),
             ({}, {"taxa_aula": 80, "max_pessoas": 3, "taxa_mensal": 100}, "quantas aulas")]
    for grupo, custos, frase in erros:
        with pytest.raises(ValueError, match=frase):
            locais.editar_local(con, "CIA", grupo, **custos)
    assert precos.taxas_cia(con)[0][1] == 85   # o erro não gravou nada


def test_taxa_mensal_da_cia_entra_no_preco_e_na_conta_do_mes(con):  # noqa: F811
    antes, _ = _pacote(con, "CIA")
    locais.editar_local(con, "CIA", taxa_aula=70.76, max_pessoas=3, taxa_mensal=200, aulas_mes=20)
    depois, _ = _pacote(con, "CIA")
    assert depois["custo_total"] == pytest.approx(antes["custo_total"] + 10 * 8, abs=0.01)   # 200 ÷ 20 = R$ 10 por aula
    assert precos.decompor(precos.base_motor("Pacote de Aulas", qtd=8, local="CIA"), precos.carregar_parametros(con), "CIA")["mensal"] == 10
    assert contas_auto.cia_mes(con, "2026-10")["valor"] == 0   # mês sem aula: sem taxa mensal
    marca(con, aluno(con, "Ana"), "2026-10-05")
    r = contas_auto.cia_mes(con, "2026-10")
    assert r["valor"] == pytest.approx(70.76 + 200) and r["texto"].endswith("+ taxa mensal R$ 200,00")


def test_previa_e_igual_ao_preco_depois_de_salvar_e_nao_grava(con):  # noqa: F811
    r = locais.previa(con, "SmartFit", {"taxa_aula": 20, "deslocamento": 5, "tempo_deslocamento": 20})
    assert "SmartFit" not in precos.custos_locais(con)   # nada gravado
    assert r["hoje"]["preco"] < r["agora"]["preco"] and r["agora"]["taxa"] == 20
    locais.editar_local(con, "SmartFit", taxa_aula=20, deslocamento=5, tempo_deslocamento=20)
    real = precos.decompor(precos.base_motor("Pacote de Aulas", qtd=8, local="SmartFit"), precos.carregar_parametros(con), "SmartFit")
    assert r["agora"]["preco"] == real["preco"] and r["agora"]["custo"] == real["custo"]
    assert r["agora"]["minimo"] < r["agora"]["preco"]
    assert locais.previa(con, "Prédio novo", {})["hoje"] is None   # local novo: não há "hoje"
    with pytest.raises(ValueError, match="aulas por mês"):
        locais.previa(con, "SmartFit", {"taxa_mensal": 100})


def test_previa_da_cia(con):  # noqa: F811
    r = locais.previa(con, "CIA", {"taxa_aula": 90, "max_pessoas": 3}, {2: 120, 3: 170}, cia=True)
    assert r["local"] == "CIA" and r["agora"]["taxa"] == 90 and r["agora"]["preco"] > r["hoje"]["preco"]
    assert [g["pessoas"] for g in r["agora"]["grupo"]] == [2, 3]
    assert precos.taxas_cia(con)[0][1] == pytest.approx(70.76)   # nada gravado
    with pytest.raises(ValueError, match="CIA já existe"):   # no "+ Novo local", digitar CIA não vira a prévia da CIA
        locais.previa(con, "cia", {"taxa_aula": 90})


def test_conta_fixa_do_local_aparece_e_sai_do_rateio(con):  # noqa: F811
    conta(con, "SmartFit mensalidade", 150)
    conta(con, "MFIT", 100)
    assert [c["descricao"] for c in locais.contas_fixas_do_local(con, "SmartFit")] == ["SmartFit mensalidade"]
    assert locais.contas_fixas_do_local(con, "CIA") == []
    mes = main.mes_atual()
    assert financeiro.custos_fixos_rateio(con, mes, list(precos.custos_locais(con)))["total"] == 250
    locais.editar_local(con, "SmartFit", taxa_mensal=150, aulas_mes=20)
    assert financeiro.custos_fixos_rateio(con, mes, list(precos.custos_locais(con)))["total"] == 100


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


def _botao_editar(html: str) -> str:
    i = html.index('data-acao="/locais/editar"')
    return html[html.rindex("<button", 0, i):html.index("</button>", i)]


def test_grade_mostra_o_mesmo_editar_em_todo_local_cia_inclusive(http, con):  # noqa: F811
    locais.criar_local(con, "Prédio", "CIA", taxa_aula=30.5)
    r = http.get("/grade", params={"local": "Prédio"})
    assert 'data-taxa_aula="30,50"' in _botao_editar(r.text) and "Excluir local" in r.text
    smart = http.get("/grade", params={"local": "SmartFit"}).text   # da lista, sem custos: também edita e exclui
    assert 'data-taxa_aula="0,00"' in _botao_editar(smart) and "data-cia" not in _botao_editar(smart) and "Excluir local" in smart
    cia = http.get("/grade", params={"local": "CIA"}).text   # o mesmo botão e o mesmo pop-up; a CIA não exclui
    b = _botao_editar(cia)
    assert 'data-cia="1"' in b and 'data-taxa_aula="70,76"' in b and 'data-taxa_2="99,69"' in b and 'data-taxa_3="151,47"' in b
    assert 'data-max_pessoas="3"' in b and 'data-taxa_mensal="0,00"' in b and 'data-tempo_deslocamento="0"' in b
    assert "Excluir local" not in cia and "dlg-cia" not in cia and 'data-titulo="Editar CIA"' in b
    dlg = cia[cia.index('id="dlg-local"'):]
    for campo in ("taxa_aula", "taxa_2", "taxa_3", "taxa_pessoa_extra", "max_pessoas", "deslocamento", "tempo_deslocamento",
                  "taxa_mensal", "aulas_mes"):
        assert f'name="{campo}"' in dlg
    assert "data-so-cia" in dlg and "data-nao-cia" in dlg and "data-previa" in dlg


def test_rota_editar_da_cia_grava_e_recusa_erro(http, con):  # noqa: F811
    r = http.post("/locais/editar", data={"nome": "CIA", "taxa_aula": "85,50", "taxa_2": "120", "taxa_3": "170", "max_pessoas": "3",
                                          "deslocamento": "3", "tempo_deslocamento": "15", "taxa_mensal": "", "aulas_mes": ""},
                  follow_redirects=False)
    assert r.headers["location"].startswith("/grade?local=CIA&msg=")
    assert precos.taxas_cia(con) == ({1: 85.5, 2: 120, 3: 170}, 3)
    assert db.parametros(con, "cia_deslocamento") == {"reais_por_aula": 3, "minutos_por_aula": 15}
    r = http.post("/locais/editar", data={"nome": "CIA", "taxa_aula": "abc", "max_pessoas": "3"}, follow_redirects=False)
    assert r.headers["location"].startswith("/grade?local=CIA&erro=") and precos.taxas_cia(con)[0][1] == 85.5
    r = http.post("/locais/editar", data={"nome": "CIA", "taxa_aula": "90", "taxa_2": "", "max_pessoas": "3"}, follow_redirects=False)
    assert "msg=" in r.headers["location"] and precos.taxas_cia(con) == ({1: 90, 2: 120, 3: 170}, 3)   # vazio fica como está
    assert http.post("/locais/cia", data={"taxa_1": "1"}, follow_redirects=False).status_code in (404, 405)   # a rota velha saiu


def test_rota_da_previa(http, con):  # noqa: F811
    r = http.post("/locais/previa", data={"nome": "SmartFit", "taxa_aula": "20", "tipo": "Pacotes", "ref": "8"})
    assert r.status_code == 200 and "Preço de tabela por aula" in r.text and "R$ 20,00" in r.text and "hoje" in r.text
    r = http.post("/locais/previa", data={"nome": "SmartFit", "taxa_mensal": "100"})
    assert "previa-erro" in r.text and "aulas por mês" in r.text
    r = http.post("/locais/previa", data={"cia": "1", "nome": "CIA", "taxa_aula": "90", "taxa_2": "120", "taxa_3": "170", "max_pessoas": "3",
                                          "taxa_mensal": "200", "aulas_mes": "20", "tipo": "Mensalidades"})
    assert "Taxa da CIA (1 pessoa)" in r.text and "mensalidade 2x/semana" in r.text and "Taxa mensal ÷ aulas do mês" in r.text
    assert "2 pessoas" in r.text and precos.taxas_cia(con)[0][1] == pytest.approx(70.76)
    conta(con, "Aluguel SmartFit", 150)
    assert "Aluguel SmartFit" in http.post("/locais/previa", data={"nome": "SmartFit"}).text
    assert "SmartFit" not in precos.custos_locais(con)   # a prévia não grava


def test_rotas_editar_e_excluir(http, con):  # noqa: F811
    locais.criar_local(con, "Prédio", "CIA", taxa_aula=30)
    r = http.post("/locais/editar", data={"nome": "Prédio", "taxa_aula": "45,5"}, follow_redirects=False)
    assert "msg=" in r.headers["location"]
    assert con.execute("SELECT taxa_aula FROM locais_custos WHERE local='Prédio'").fetchone()[0] == 45.5
    r = http.post("/locais/excluir", data={"nome": "Prédio"}, follow_redirects=False)
    assert r.headers["location"].startswith("/grade?msg=")
