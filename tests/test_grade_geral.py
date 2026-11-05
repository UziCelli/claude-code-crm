"""Grade única para todos os locais: um multiplicador por hora (igual em todos os dias e locais), ocupado/indisponível
valendo em todos os locais, deslocamento até a CIA e o quadro "Por que esse preço?" (as partes do preço de cada local)."""
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import db, locais, main, precos

ALL = "All Fit"


@pytest.fixture
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    con = db.conectar()
    with con:   # grade da CIA (a All Fit copia dela)
        main.salvar_slots(con, [(t, d, "CIA", h, "livre", None, None, 1.0) for t in main.TIPOS_GRADE for d in range(1, 7) for h in range(5, 24)])
    locais.criar_local(con, ALL, "CIA", taxa_aula=40, deslocamento=8, tempo_deslocamento=20)
    con.close()
    return TestClient(main.app, base_url="http://localhost")


def q(sql, *args):
    con = db.conectar()
    try:
        return [tuple(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def grava(sql, *args):
    con = db.conectar()
    try:
        with con:
            return con.execute(sql, args).lastrowid
    finally:
        con.close()


def aluno(nome):
    return grava("INSERT INTO clientes (nome, status, tipo_servico) VALUES (?, 'ativo', 'Pacote de Aulas')", nome)


def slot(http, local, dia, hora, status, cid=""):
    return http.post("/grade/slot", data={"tipo": "Pacotes", "local": local, "dia": dia, "hora": hora, "status": status, "cliente_id": cid},
                     follow_redirects=False)


def situacao(dia, hora, local):
    """(status, cliente_id) de Pacotes e Mensalidades nesse horário e local."""
    return q("SELECT tipo_calculo, status, cliente_id FROM grade_slots WHERE dia=? AND hora=? AND local=? ORDER BY tipo_calculo", dia, hora, local)


def erro(r):
    loc = unquote(r.headers.get("location", ""))
    return loc.split("erro=", 1)[1] if "erro=" in loc else None


# ---------- multiplicador por hora ----------
def test_comeca_tudo_em_1(http):
    con = db.conectar()
    try:
        assert precos.mult_horario(con) == {h: 1.0 for h in range(5, 24)}
    finally:
        con.close()


def test_salvar_multiplicadores_muda_o_preco_em_todos_os_locais(http):
    antes = {l: http.get("/grade", params={"local": l}).context["celulas"][(1, 7)]["preco_total"] for l in ("CIA", ALL)}
    r = http.post("/grade/multiplicadores", params={"tipo": "Pacotes", "local": ALL}, data={"m_07": "0,8", "m_19": "1,25"},
                  follow_redirects=False)
    assert r.status_code == 303 and erro(r) is None and f"local={ALL.replace(' ', '%20')}" in r.headers["location"]
    con = db.conectar()
    try:
        m = precos.mult_horario(con)
    finally:
        con.close()
    assert (m[7], m[19], m[8]) == (0.8, 1.25, 1.0)
    for l in ("CIA", ALL):
        ctx = http.get("/grade", params={"local": l}).context
        c7, c8 = ctx["celulas"][(1, 7)], ctx["celulas"][(6, 7)]
        assert c7["multiplicador"] == c8["multiplicador"] == 0.8   # todos os dias
        assert c7["preco_total"] == pytest.approx(antes[l] * 0.8, rel=1e-3)
        assert ctx["resumo"]["vale"] == 6   # 7h de Seg a Sáb
    assert 'name="m_07" value="0,80"' in http.get("/grade").text   # a janela mostra o valor salvo


@pytest.mark.parametrize("valor", ["9", "0", "abc"])
def test_multiplicador_fora_da_faixa_nao_salva_nada(http, valor):
    r = http.post("/grade/multiplicadores", data={"m_06": "0,9", "m_07": valor}, follow_redirects=False)
    assert "07h" in erro(r)
    assert q("SELECT valor FROM parametros WHERE grupo='mult_horario' AND chave IN ('06','07')") == [(1.0,), (1.0,)]


def test_janela_do_horario_nao_tem_mais_multiplicador(http):
    t = http.get("/grade").text
    assert 'name="multiplicador"' not in t and 'name="so_este"' not in t and 'id="dlg-mult"' in t


def test_explorador_e_proposta_usam_o_multiplicador_da_hora(http):
    grava("UPDATE parametros SET valor=0.9 WHERE grupo='mult_horario' AND chave='14'")
    linhas = http.get("/explorador", params={"local": ALL, "tipo_servico": "Pacote de Aulas", "so_vale": 1}).context["linhas"]
    assert linhas and {(l["hora"], l["mult"]) for l in linhas} == {(14, 0.9)}
    con = db.conectar()
    try:
        r = main.simular(con, "Pacote de Aulas|8|0", [{"dia": 2, "hora": 14, "local": ALL}], "PIX", 1)
    finally:
        con.close()
    assert r["horarios"][0]["mult"] == 0.9


# ---------- ocupado e indisponível em todos os locais ----------
def test_aluno_ocupado_na_cia_aparece_na_all_fit(http):
    alexei = aluno("Alexei Alba")
    r = slot(http, "CIA", 1, 8, "ocupado", alexei)
    assert erro(r) is None
    ctx = http.get("/grade", params={"local": ALL})
    c = ctx.context["celulas"][(1, 8)]
    assert (c["status"], c["cliente_nome"], c["outro_local"], c["preco_total"]) == ("ocupado", "Alexei Alba", "CIA", None)
    assert "em CIA" in ctx.text and ctx.context["resumo"]["ocupados"] == 1
    assert situacao(1, 8, ALL) == [("Mensalidades", "livre", None), ("Pacotes", "livre", None)]   # só a CIA guarda


def test_livre_na_all_fit_solta_a_cia(http):
    alexei = aluno("Alexei Alba")
    slot(http, "CIA", 1, 8, "ocupado", alexei)
    r = slot(http, ALL, 1, 8, "livre")
    assert erro(r) is None and "todos os locais" in unquote(r.headers["location"])
    assert situacao(1, 8, "CIA") == [("Mensalidades", "livre", None), ("Pacotes", "livre", None)]


def test_outro_aluno_no_mesmo_horario_em_outro_local_e_recusado(http):
    alexei, bia = aluno("Alexei Alba"), aluno("Bia Costa")
    slot(http, "CIA", 1, 8, "ocupado", alexei)
    r = slot(http, ALL, 1, 8, "ocupado", bia)
    assert "Alexei Alba" in erro(r) and "CIA" in erro(r)
    assert situacao(1, 8, "CIA") == [("Mensalidades", "ocupado", alexei), ("Pacotes", "ocupado", alexei)]
    assert situacao(1, 8, ALL) == [("Mensalidades", "livre", None), ("Pacotes", "livre", None)]
    r = slot(http, ALL, 1, 8, "indisponivel")   # indisponível também não passa por cima de aluno
    assert "Alexei Alba" in erro(r)


def test_mesmo_aluno_muda_de_local(http):
    alexei = aluno("Alexei Alba")
    slot(http, "CIA", 1, 8, "ocupado", alexei)
    assert erro(slot(http, ALL, 1, 8, "ocupado", alexei)) is None
    assert situacao(1, 8, ALL) == [("Mensalidades", "ocupado", alexei), ("Pacotes", "ocupado", alexei)]
    assert situacao(1, 8, "CIA") == [("Mensalidades", "livre", None), ("Pacotes", "livre", None)]


def test_indisponivel_vale_em_todos_os_locais(http):
    slot(http, "CIA", 2, 9, "indisponivel")
    c = http.get("/grade", params={"local": ALL}).context["celulas"][(2, 9)]
    assert (c["status"], c["outro_local"]) == ("indisponivel", "CIA")
    linhas = http.get("/explorador", params={"local": ALL, "tipo_servico": "Pacote de Aulas", "dia": 2}).context["linhas"]
    assert linhas and 9 not in {l["hora"] for l in linhas}   # o explorador não oferece
    assert erro(slot(http, ALL, 2, 9, "ocupado", aluno("Bia Costa"))) is None   # ocupar aqui tira o indisponível de lá
    assert situacao(2, 9, "CIA") == [("Mensalidades", "livre", None), ("Pacotes", "livre", None)]


def test_agenda_ve_conflito_em_outro_local(http):
    ana, bia = aluno("Ana Silva"), aluno("Bia Costa")
    con = db.conectar()
    try:
        with con:
            assert main.ocupar_fixo(con, ana, "Ana Silva", 1, "CIA", 7) is None
            msg = main.ocupar_fixo(con, bia, "Bia Costa", 1, ALL, 7)
            assert "Ana Silva" in msg and "CIA" in msg
            main.salvar_slots(con, [(t, 3, "CIA", 10, "indisponivel", None, None, 1.0) for t in main.TIPOS_GRADE])
            assert "indisponível" in main.ocupar_fixo(con, bia, "Bia Costa", 3, ALL, 10)
            assert main.ocupar_fixo(con, ana, "Ana Silva", 1, ALL, 7) is None   # a própria aluna troca de local
            main.grade_ocupar_lote(con, bia, "Bia Costa", [(1, ALL, 7), (4, ALL, 7)])   # Seg 7h é da Ana: só a Qui entra
    finally:
        con.close()
    assert situacao(1, 7, "CIA") == [("Mensalidades", "livre", None), ("Pacotes", "livre", None)]
    assert situacao(1, 7, ALL) == [("Mensalidades", "ocupado", ana), ("Pacotes", "ocupado", ana)]
    assert situacao(4, 7, ALL) == [("Mensalidades", "ocupado", bia), ("Pacotes", "ocupado", bia)]


def test_proposta_avisa_ocupado_em_outro_local(http):
    slot(http, "CIA", 1, 8, "ocupado", aluno("Alexei Alba"))
    con = db.conectar()
    try:
        r = main.simular(con, "Pacote de Aulas|8|0", [{"dia": 1, "hora": 8, "local": ALL}], "PIX", 1)
    finally:
        con.close()
    assert any("ocupado na grade (em CIA)" in a for a in r["avisos"])


# ---------- deslocamento até a CIA ----------
def test_deslocamento_da_cia_entra_no_custo_e_nas_horas(http):
    base = precos.base_motor("Pacote de Aulas", 8, local="CIA")
    con = db.conectar()
    try:
        p0 = precos.carregar_parametros(con)
        custo0, _, horas0 = precos.custo_servico(base, p0, "CIA")
        with con:
            con.execute("UPDATE parametros SET valor=12 WHERE grupo='cia_deslocamento' AND chave='reais_por_aula'")
            con.execute("UPDATE parametros SET valor=30 WHERE grupo='cia_deslocamento' AND chave='minutos_por_aula'")
        p1 = precos.carregar_parametros(con)
        custo1, _, horas1 = precos.custo_servico(base, p1, "CIA")
        assert locais.custo_aula_local(con, "CIA") == pytest.approx(p1["taxa_cia"][1] + 12)
    finally:
        con.close()
    assert horas1 - horas0 == pytest.approx(8 * 30 / 60)
    assert custo1 - custo0 == pytest.approx(8 * 12 + p1["rateio_hora"] * 4, rel=1e-6)
    assert 'id="cfg-cia_deslocamento"' in http.get("/configuracoes").text


# ---------- "Por que esse preço?" ----------
def test_partes_do_preco_somam_o_custo_e_batem_com_a_grade(http):
    con = db.conectar()
    try:
        p = precos.carregar_parametros(con)
        for l in ("CIA", ALL):
            base = main.plano_referencia(con, "Pacotes", l)
            d = precos.decompor(dict(base), p, l)
            assert d["taxa"] + d["mensal"] + d["ida_reais"] + d["salario"] + d["rateio"] == pytest.approx(d["custo"], abs=0.05)
            assert d["preco"] == pytest.approx(precos.calcular(dict(base), p)["preco_cheio"] / base["sessoes_mes"], abs=0.01)
        allfit = precos.decompor(dict(main.plano_referencia(con, "Pacotes", ALL)), p, ALL)
    finally:
        con.close()
    assert (allfit["taxa"], allfit["ida_reais"], allfit["minutos_ida"]) == (40, 8, 20)
    r = http.get("/grade", params={"local": ALL})
    assert "Por que esse preço?" in r.text and {"CIA", ALL} <= {x["local"] for x in r.context["comparar"]}
    assert r.context["celulas"][(1, 9)]["preco_aula"] == pytest.approx(allfit["preco"], abs=0.01)
