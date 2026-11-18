"""Dias e horários fixos na ficha do aluno: a lista é a da Agenda (mesma tabela), com as regras dela."""
from tests.test_agenda import aluno, consulta, fixo, fixos_ativos, grava, http  # noqa: F401  (http é fixture)


def salvar(http, cid, *horarios):  # noqa: F811
    dados = {"dia": [str(d) for d, _, _ in horarios], "hora": [str(h) for _, h, _ in horarios], "local": [l for _, _, l in horarios]}
    return http.post(f"/clientes/{cid}/horarios", data=dados, follow_redirects=False)


def test_incluir_dois_horarios_cria_na_agenda(http):  # noqa: F811
    ana = aluno("Ana")
    r = salvar(http, ana, (1, 13, "CIA"), (4, 17, "CIA"))
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    assert fixos_ativos() == [("Ana", 1, 13, "CIA"), ("Ana", 4, 17, "CIA")]
    ficha = http.get(f"/clientes/{ana}").text
    assert 'id="horarios"' in ficha and '<option value="13" selected>13h</option>' in ficha
    assert "Seg 13h · Qui 17h" in http.get("/clientes").text


def test_terceiro_aluno_no_horario_e_recusado_sem_gravar_nada(http):  # noqa: F811
    a, b, c = aluno("Ana"), aluno("Bia"), aluno("Caio")
    fixo(a, 2, 18), fixo(b, 2, 18)
    r = salvar(http, c, (2, 18, "CIA"), (3, 9, "CIA"))
    assert "erro=" in r.headers["location"] and "cheio" in r.headers["location"].replace("%20", " ")
    assert [x for x in fixos_ativos() if x[0] == "Caio"] == []


def test_remover_vai_para_a_lixeira_e_mantem_o_outro_aluno(http):  # noqa: F811
    a, b = aluno("Ana"), aluno("Bia")
    fixo(a, 2, 18), fixo(b, 2, 18), fixo(a, 4, 7)
    salvar(http, a, (4, 7, "CIA"))
    assert fixos_ativos() == [("Bia", 2, 18, "CIA"), ("Ana", 4, 7, "CIA")]
    assert consulta("SELECT COUNT(*) FROM agenda_fixos WHERE cliente_id=? AND excluido_em IS NOT NULL", a)[0][0] == 1


def test_trocar_o_local_exclui_e_cria_linha_nova(http):  # noqa: F811
    a = aluno("Ana")
    fixo(a, 1, 7, "CIA")
    salvar(http, a, (1, 7, "SmartFit"))
    assert fixos_ativos() == [("Ana", 1, 7, "SmartFit")]


def test_salvar_cadastro_nao_apaga_o_texto_antigo(http):  # noqa: F811
    a = aluno("Ana")
    grava("UPDATE clientes SET dias_horarios='Seg 07:00' WHERE id=?", a)
    http.post(f"/clientes/{a}", data={"nome": "Ana", "status": "ativo"}, follow_redirects=False)
    assert consulta("SELECT dias_horarios FROM clientes WHERE id=?", a)[0][0] == "Seg 07:00"
    ficha = http.get(f"/clientes/{a}").text
    assert 'name="dias_horarios"' not in ficha and 'Texto antigo: "Seg 07:00"' in ficha
    assert "Seg 07:00" in http.get("/clientes").text   # sem horário na Agenda, a lista ainda mostra o texto antigo


def test_valores_invalidos_sao_recusados(http):  # noqa: F811
    a = aluno("Ana")
    for h in [(7, 7, "CIA"), (1, 4, "CIA"), (1, 7, "Lugar que não existe")]:
        assert "erro=" in salvar(http, a, h).headers["location"]
    assert "erro=" in salvar(http, a, (1, 7, "CIA"), (1, 7, "CIA")).headers["location"]   # repetido
    assert fixos_ativos() == []


def test_aluno_inativo_nao_ganha_horario(http):  # noqa: F811
    a = aluno("Ana", status="inativo")
    assert "erro=" in salvar(http, a, (1, 7, "CIA")).headers["location"]
