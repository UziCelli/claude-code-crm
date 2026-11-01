"""Estado do aluno (app/alunos.py): um algoritmo detecta a situação de cada aluno e traz as soluções; alertas, Clientes, ficha,
Mensalidades e Assistente leem dele. Crédito (mês pago e não usado) e "Pulou o mês" fecham os becos."""
import datetime as dt
import json
import re
from urllib.parse import unquote

from app import alunos, assistente, financeiro, main
from tests.test_alertas import cliente, con_temp, dia, do_aluno  # noqa: F401  (con_temp: fixture de banco temporário)
from tests.test_alertas_acao import http  # noqa: F401


# ---------- montagem ----------
def sem_bloqueio(con):
    with con:
        con.execute("DELETE FROM campanha_fases WHERE tipo='bloqueio'")   # a fase de bloqueio inicial pode cair em qualquer dia de hoje


def aula(con, cid, n):
    with con:
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', ?)", (cid, dia(n)))


def treinando(con, cid):
    """Aluno que vem: aula recente e outra um mês atrás (qualquer ciclo que o algoritmo analise hoje tem aula)."""
    aula(con, cid, -2)
    aula(con, cid, -30)


def pagou(con, cid, renova, valor=400):
    """Pagamento no começo do ciclo que fecha em `renova` (antes da data gravada: a renovação não anda por ele)."""
    inicio = financeiro.proxima_renovacao(renova, -1)
    with con:
        return con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id)
                              VALUES ('PJ','entrada',?,?,?,'Pacotes de Aulas',?)""", (inicio, inicio, valor, cid)).lastrowid


def estado(con, cid):
    return alunos.estado_aluno(con, cid)


def rotulos(e):
    return [x.get("rotulo", "wa") for x in e["acoes"]]


def mes_do_ciclo(renova):
    ini = financeiro.proxima_renovacao(renova, -1)
    return f"{ini[5:7]}/{ini[:4]}"


def aluno_pago_sem_aula(con, nome="Paula", renova=None, valor=400, **kw):
    renova = renova or dia(3)
    cid = cliente(con, nome, renova, valor=valor, **kw)
    pagou(con, cid, renova, valor)
    aula(con, cid, -60)   # já teve aula, mas antes deste ciclo
    return cid, renova


# ---------- cada estado é detectado ----------
def test_cobrar_renovacao_vencida_com_multa_e_juros(con_temp):
    sem_bloqueio(con_temp)
    cid = cliente(con_temp, "Dora", dia(-20), valor=400)
    e = estado(con_temp, cid)
    assert (e["situacao"], e["cor"], e["rotulo"]) == ("cobrar", "vermelho", "Vencida")
    assert e["texto"] == f"renovação venceu em {main.data_br(dia(-20))}"
    assert e["renovacao"]["vencida"] and e["renovacao"]["dias"] == -20
    assert rotulos(e) == ["Registrar pagamento", "wa", "Pular mês"] and e["botao"] == "Cobrar R$ 410,67"


def test_pago_sem_aula_oferece_pulou_e_credito(con_temp):
    sem_bloqueio(con_temp)
    cid, renova = aluno_pago_sem_aula(con_temp)
    e = estado(con_temp, cid)
    assert (e["situacao"], e["cor"]) == ("pago_sem_aula", "amarelo")
    assert e["texto"] == f"pagou e não teve aula em {mes_do_ciclo(renova)}"
    assert rotulos(e) == ["Pulou o mês", "Crédito na próxima (R$ 400,00)"]
    assert e["uso"]["ciclo"]["feitas"] == 0 and e["credito_sugerido"] == 400.0
    credito = e["acoes"][1]
    assert credito["dialogo"] == "dlg-credito" and credito["dados"]["valor"] == "400,00" and credito["dados"]["acao"] == f"/alunos/{cid}/credito"
    pulou = e["acoes"][0]
    assert pulou["dialogo"] == "dlg-pulou" and pulou["dados"]["acao"] == f"/alunos/{cid}/pulou"


def test_sem_pagar_sem_aula_pergunta_se_pulou_o_mes(con_temp):
    sem_bloqueio(con_temp)
    renova = dia(3)
    cid = cliente(con_temp, "Sumiu", renova, valor=400)
    e = estado(con_temp, cid)
    assert (e["situacao"], e["cor"]) == ("sem_pagar_sem_aula", "amarelo")
    assert e["texto"] == f"sem aula e sem pagamento em {mes_do_ciclo(renova)}: pulou o mês?"
    assert rotulos(e) == ["Pulou o mês", "Registrar pagamento", "Não tem aula (consultoria)"]   # nunca teve aula: a saída "consultoria" também
    assert e["acoes"][1]["dados"]["valor"] == "400,00" and e["acoes"][1]["dados"]["descricao"] == f"Mensalidade {renova[5:7]}/{renova[:4]}"


def test_vence_logo_com_aula_no_ciclo(con_temp):
    sem_bloqueio(con_temp)
    cid, renova = aluno_pago_sem_aula(con_temp, "Vera")
    aula(con_temp, cid, -2)
    e = estado(con_temp, cid)
    assert (e["situacao"], e["cor"]) == ("vence_logo", "amarelo") and e["texto"] == f"renovação em {main.data_br(renova)}"
    assert rotulos(e) == ["Registrar pagamento", "wa"] and e["modelo"] == "renovacao"


def test_sem_aula_recente_conta_14_dias_e_35_para_hibrida(con_temp):
    sem_bloqueio(con_temp)
    cid = cliente(con_temp, "Fabio", dia(60))
    aula(con_temp, cid, -20)
    aula(con_temp, cid, -40)   # uma aula em qualquer ciclo possível: o que vale aqui é o tempo sem aula
    e = estado(con_temp, cid)
    assert (e["situacao"], e["cor"]) == ("sem_aula_recente", "vermelho") and e["texto"] == f"sem aula desde {main.data_br(dia(-20))}"
    assert rotulos(e) == ["Abrir agenda", "wa"] and e["modelo"] == "falta"
    h = cliente(con_temp, "Hibrida", dia(60), tipo="Consultoria Híbrida")
    with con_temp:
        con_temp.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?, 2, 7, 'CIA')", (h,))
    aula(con_temp, h, -30)
    assert estado(con_temp, h)["situacao"] == "em_dia"


def test_cadastro_incompleto_e_em_dia(con_temp):
    sem_bloqueio(con_temp)
    sem_tel = cliente(con_temp, "Sem Tel", dia(60))
    ok = cliente(con_temp, "Tudo Certo", dia(60))
    for cid in (sem_tel, ok):
        treinando(con_temp, cid)
    with con_temp:
        con_temp.execute("UPDATE clientes SET telefone=NULL WHERE id=?", (sem_tel,))
    e = estado(con_temp, sem_tel)
    assert (e["situacao"], e["cor"]) == ("cadastro_incompleto", "azul") and "telefone" in e["texto"]
    assert e["acoes"] == [{"rotulo": "Completar cadastro", "href": f"/clientes/{sem_tel}#cadastro"}]
    e = estado(con_temp, ok)
    assert (e["situacao"], e["cor"], e["acoes"]) == ("em_dia", "verde", [])


def test_estado_so_de_alunos_ativos_e_em_poucas_consultas(con_temp):
    sem_bloqueio(con_temp)
    ids = [cliente(con_temp, f"Aluno {i}", dia(60)) for i in range(30)]
    inativo = cliente(con_temp, "Inativo", dia(-20))
    with con_temp:
        con_temp.execute("UPDATE clientes SET status='inativo' WHERE id=?", (inativo,))
    class Contador:   # conta as consultas feitas (o adaptador do Turso não tem set_trace_callback)
        def __init__(self, con):
            self.con, self.consultas = con, []

        def execute(self, sql, *args):
            self.consultas.append(sql)
            return self.con.execute(sql, *args)

        def __getattr__(self, nome):
            return getattr(self.con, nome)

    con = Contador(con_temp)
    todos = alunos.estado(con)
    assert set(todos) == set(ids) and estado(con_temp, inativo) is None
    assert len(con.consultas) < 25, len(con.consultas)   # agrupado: não cresce com o número de alunos


# ---------- quem não tem aula não é julgado por ela ----------
def test_consultoria_sem_horario_nunca_e_pago_sem_aula(con_temp):
    sem_bloqueio(con_temp)
    cid, _ = aluno_pago_sem_aula(con_temp, "Online", tipo="Consultoria Online")
    e = estado(con_temp, cid)
    assert e["consultoria"] and not e["tem_aulas"] and e["situacao"] == "vence_logo"
    assert e["uso"]["ciclo"] is None and "Crédito" not in " ".join(rotulos(e))
    com_horario, _ = aluno_pago_sem_aula(con_temp, "Online com horario", tipo="Consultoria Online")
    with con_temp:
        con_temp.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?, 2, 7, 'CIA')", (com_horario,))
    assert estado(con_temp, com_horario)["situacao"] == "pago_sem_aula"


def test_dias_de_bloqueio_e_mes_pulado_nao_contam_como_sem_aula(con_temp):
    sem_bloqueio(con_temp)
    cid, renova = aluno_pago_sem_aula(con_temp, "Viajante")
    inicio = financeiro.proxima_renovacao(renova, -1)
    assert estado(con_temp, cid)["situacao"] == "pago_sem_aula"
    with con_temp:   # uma viagem de 5 dias no ciclo: ainda sobram dias úteis de sobra
        con_temp.execute("INSERT INTO campanha_fases (nome, inicio, fim, tipo, ordem) VALUES ('Viagem', ?, ?, 'bloqueio', 9)",
                         (inicio, (dt.date.fromisoformat(inicio) + dt.timedelta(days=4)).isoformat()))
    assert estado(con_temp, cid)["situacao"] == "pago_sem_aula"
    with con_temp:   # o ciclo inteiro bloqueado: o aluno não podia ter aula
        con_temp.execute("INSERT INTO campanha_fases (nome, inicio, fim, tipo, ordem) VALUES ('Fechado', ?, ?, 'bloqueio', 10)", (inicio, renova))
    e = estado(con_temp, cid)
    assert e["situacao"] == "vence_logo" and e["uso"]["ciclo"]["uteis"] < alunos.DIAS_UTEIS_MIN
    pulou = cliente(con_temp, "Pausado", dia(3))   # mês pulado cobrindo o ciclo
    with con_temp:
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, ate) VALUES (?, 'pausa', ?, ?)",
                         (pulou, financeiro.proxima_renovacao(dia(3), -1), dia(3)))
    e = estado(con_temp, pulou)
    assert e["situacao"] == "vence_logo" and e["pausado_no_mes"] and e["uso"]["ciclo"]["uteis"] < alunos.DIAS_UTEIS_MIN


# ---------- crédito ----------
def test_credito_sugerido_e_proporcional_as_aulas_nao_usadas():
    assert alunos.sugerir_credito(400, 0, 8) == 400.0            # nenhuma aula: o valor inteiro
    assert alunos.sugerir_credito(400, 2, 8) == 300.0            # usou 2 de 8: perde 6/8
    assert alunos.sugerir_credito(400, 6, 8) == 100.0
    assert alunos.sugerir_credito(400, 9, 8) == 0.0              # usou mais do que o combinado: nada
    assert alunos.sugerir_credito(100, 1, 3) == 66.67            # 2 casas
    assert alunos.sugerir_credito(400, 0, 0) == 400.0 and alunos.sugerir_credito(400, 3, 0) == 0.0 and alunos.sugerir_credito(0, 0, 8) == 0.0


def test_credito_do_ciclo_usa_as_sessoes_do_plano(con_temp):
    sem_bloqueio(con_temp)
    cid, _ = aluno_pago_sem_aula(con_temp, "Pacote8")
    with con_temp:
        con_temp.execute("UPDATE clientes SET plano='Pacote 8 aulas' WHERE id=?", (cid,))
    c = estado(con_temp, cid)["uso"]["ciclo"]
    assert c["feitas"] == 0 and 7 <= c["esperadas"] <= 8 and c["uteis"] >= alunos.DIAS_UTEIS_MIN


def test_post_credito_cria_o_credito_e_o_proximo_pagamento_sai_com_desconto(con_temp, http):
    sem_bloqueio(con_temp)
    cid, renova = aluno_pago_sem_aula(con_temp)
    mes = estado(con_temp, cid)["uso"]["ciclo"]["mes"]
    r = http.post(f"/alunos/{cid}/credito", data={"valor": "150,00", "mes": mes, "voltar": f"/clientes/{cid}"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/clientes/{cid}?msg=")
    ev = con_temp.execute("SELECT tipo, data, valor, descricao, usado_em FROM cliente_eventos WHERE cliente_id=? AND tipo='credito'", (cid,)).fetchone()
    assert tuple(ev) == ("credito", f"{mes}-01", 150.0, f"Crédito: não usou {mes[5:]}/{mes[:4]}", None)

    e = estado(con_temp, cid)
    assert e["credito"] == 150.0 and e["situacao"] == "vence_logo"          # já tratado: não pergunta de novo
    pagar = e["acoes"][0]
    assert pagar["dados"]["valor"] == "250,00" and pagar["dados"]["nota"] == "Crédito de R$ 150,00 descontado"
    assert 'data-nota="Crédito de R$ 150,00 descontado"' in http.get(f"/clientes/{cid}").text
    proximo = financeiro.somar_meses(dt.date.today().isoformat()[:7], 1)
    assert {i["nome"]: i for i in financeiro.mensalidades(con_temp, proximo)}["Paula"]["previsto"] == 250.0   # Falta receber e previsão de caixa certos

    hoje = dt.date.today().isoformat()
    r = http.post("/financeiro/lancamento", data={"escopo": "PJ", "tipo": "entrada", "data": hoje, "pago_em": hoje, "valor": "250,00",
                  "categoria": "Pacotes de Aulas", "cliente_id": cid, "voltar": f"/clientes/{cid}"}, follow_redirects=False)
    assert r.status_code == 303 and "descontado" in unquote(r.headers["location"])
    lid = con_temp.execute("SELECT id FROM lancamentos WHERE cliente_id=? AND valor=250", (cid,)).fetchone()[0]
    usado = con_temp.execute("SELECT usado_em, usado_lancamento_id FROM cliente_eventos WHERE cliente_id=? AND tipo='credito'", (cid,)).fetchone()
    assert tuple(usado) == (hoje, lid)
    assert estado(con_temp, cid)["credito"] == 0.0
    assert financeiro.renovacoes(con_temp, cid)[cid]["efetiva"] == financeiro.proxima_renovacao(renova)   # pagou valor − crédito e renovou
    item = {i["nome"]: i for i in financeiro.mensalidades(con_temp, hoje[:7])}["Paula"]
    assert (item["previsto"], item["quitado"], item["falta"]) == (250.0, True, 0.0)   # o recebido soma também o pagamento do começo do ciclo


def test_renovacao_aceita_valor_menos_credito_e_pagamento_pequeno_nao_gasta_o_credito(con_temp):
    sem_bloqueio(con_temp)
    mes_passado = financeiro.somar_meses(dt.date.today().isoformat()[:7], -1) + "-01"

    def credito(cid, valor=100):
        with con_temp:
            con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, valor) VALUES (?, 'credito', ?, ?)", (cid, mes_passado, valor))

    def paga(cid, valor, categoria="Pacotes de Aulas"):
        with con_temp:
            return con_temp.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id)
                                       VALUES ('PJ','entrada',?,?,?,?,?)""", (dia(0), dia(0), valor, categoria, cid)).lastrowid

    longe = cliente(con_temp, "Rita", dia(20), valor=400)
    credito(longe)
    aula_extra = paga(longe, 80, "Outros")
    with con_temp:
        assert financeiro.usar_credito(con_temp, aula_extra) == 0.0               # aula extra de 80 não gasta o crédito
    assert financeiro.creditos(con_temp, longe)[longe][0]["valor"] == 100.0

    perto = cliente(con_temp, "Ugo", dia(3), valor=400)                           # mensalidade − crédito, perto do vencimento: renova um mês
    credito(perto)
    lid = paga(perto, 300)
    assert financeiro.renovacoes(con_temp, perto)[perto]["efetiva"] == financeiro.proxima_renovacao(dia(3))
    with con_temp:
        assert financeiro.usar_credito(con_temp, lid) == 100.0
    assert financeiro.renovacoes(con_temp, perto)[perto]["efetiva"] == financeiro.proxima_renovacao(dia(3))   # continua um mês só

    dois = cliente(con_temp, "Tânia", dia(3), valor=400)                          # 2 mensalidades − 1 crédito = 700: com o crédito são 2 meses
    credito(dois)
    lid = paga(dois, 700)
    assert financeiro.renovacoes(con_temp, dois)[dois]["efetiva"] == financeiro.proxima_renovacao(dia(3))
    with con_temp:
        assert financeiro.usar_credito(con_temp, lid) == 100.0
    assert financeiro.renovacoes(con_temp, dois)[dois]["efetiva"] == financeiro.proxima_renovacao(dia(3), 2)


def test_credito_valida_valor_mes_duplicado_e_voltar_seguro(con_temp, http):
    sem_bloqueio(con_temp)
    cid, _ = aluno_pago_sem_aula(con_temp)
    r = http.post(f"/alunos/{cid}/credito", data={"valor": "abc"}, follow_redirects=False)
    assert "erro=" in r.headers["location"] and r.headers["location"].startswith(f"/clientes/{cid}?")
    r = http.post(f"/alunos/{cid}/credito", data={"valor": "-5"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]
    r = http.post(f"/alunos/{cid}/credito", data={"valor": "", "voltar": "//evil.com"}, follow_redirects=False)   # vazio: o sugerido
    assert r.headers["location"].startswith(f"/clientes/{cid}?msg=") and "evil" not in r.headers["location"]
    assert con_temp.execute("SELECT valor FROM cliente_eventos WHERE tipo='credito'").fetchone()[0] == 400.0
    r = http.post(f"/alunos/{cid}/credito", data={"valor": "10"}, follow_redirects=False)
    assert "erro=" in r.headers["location"] and con_temp.execute("SELECT COUNT(*) FROM cliente_eventos WHERE tipo='credito'").fetchone()[0] == 1
    outro = cliente(con_temp, "Teto", dia(60), valor=300)
    http.post(f"/alunos/{outro}/credito", data={"valor": "999", "mes": "2026-01"})
    assert con_temp.execute("SELECT valor FROM cliente_eventos WHERE cliente_id=?", (outro,)).fetchone()[0] == 300.0   # não passa da mensalidade
    assert "erro=" in http.post("/alunos/9999/credito", data={"valor": "10"}, follow_redirects=False).headers["location"]


def test_credito_aparece_no_historico_e_na_lixeira_e_pode_ser_apagado(con_temp, http):
    sem_bloqueio(con_temp)
    cid, _ = aluno_pago_sem_aula(con_temp)
    http.post(f"/alunos/{cid}/credito", data={"valor": "100"})
    ficha = http.get(f"/clientes/{cid}").text
    assert "crédito" in ficha and "Crédito: não usou" in ficha and "Crédito disponível" in ficha
    eid = con_temp.execute("SELECT id FROM cliente_eventos WHERE tipo='credito'").fetchone()[0]
    http.post(f"/agenda/evento/{eid}/excluir", data={"destino": "ficha"})
    assert estado(con_temp, cid)["credito"] == 0.0 and estado(con_temp, cid)["situacao"] == "pago_sem_aula"   # sem crédito, pergunta de novo
    assert "crédito" in http.get("/dados").text and "Crédito: não usou" in http.get("/dados").text


# ---------- pulou o mês ----------
def test_pulou_o_mes_move_a_renovacao_e_o_aluno_volta_ao_normal(con_temp, http):
    sem_bloqueio(con_temp)
    cid = cliente(con_temp, "Dora", dia(-20), valor=400)
    aula(con_temp, cid, -2)
    assert estado(con_temp, cid)["situacao"] == "cobrar"
    r = http.post(f"/alunos/{cid}/pulou", data={"voltar": "/"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/?msg=")
    nova = financeiro.proxima_renovacao(dia(-20))
    ev = con_temp.execute("SELECT data, ate FROM cliente_eventos WHERE cliente_id=? AND tipo='pausa'", (cid,)).fetchone()
    assert tuple(ev) == (dia(-20), nova)
    assert financeiro.renovacoes(con_temp, cid)[cid]["efetiva"] == nova
    assert estado(con_temp, cid)["situacao"] == "em_dia"


def test_pulou_o_mes_de_quem_pagou_sem_aula_nao_pergunta_de_novo_e_usa_credito_que_cobre_o_mes(con_temp, http):
    sem_bloqueio(con_temp)
    cid, renova = aluno_pago_sem_aula(con_temp)
    aula(con_temp, cid, -35)
    http.post(f"/alunos/{cid}/credito", data={"valor": "400"})
    e = estado(con_temp, cid)
    assert e["credito"] == 400.0 and rotulos(e) == ["Pulou o mês", "wa"]        # crédito cobre tudo: não há o que registrar, só pular
    http.post(f"/alunos/{cid}/pulou", data={})
    assert financeiro.renovacoes(con_temp, cid)[cid]["efetiva"] == financeiro.proxima_renovacao(renova)
    assert estado(con_temp, cid)["credito"] == 0.0                            # o crédito cobriu o mês pulado
    assert estado(con_temp, cid)["situacao"] == "em_dia"
    sem_data = cliente(con_temp, "Sem data", None)
    assert "erro=" in http.post(f"/alunos/{sem_data}/pulou", data={}, follow_redirects=False).headers["location"]


# ---------- as telas leem do estado ----------
def test_alertas_vem_do_estado_um_por_aluno_com_as_acoes(con_temp):
    sem_bloqueio(con_temp)
    cobrar = cliente(con_temp, "Dora", dia(-20))
    pago, _ = aluno_pago_sem_aula(con_temp, "Paula")
    sem_pagar = cliente(con_temp, "Sumiu", dia(3))
    ok = cliente(con_temp, "Tudo Certo", dia(60))
    treinando(con_temp, ok)
    incompletos = [cliente(con_temp, n, dia(60)) for n in ("Sem Tel 1", "Sem Tel 2")]
    for cid in incompletos:
        treinando(con_temp, cid)
        with con_temp:
            con_temp.execute("UPDATE clientes SET telefone=NULL WHERE id=?", (cid,))
    lista = main.alertas(con_temp)
    for cid, situacao in ((cobrar, "cobrar"), (pago, "pago_sem_aula"), (sem_pagar, "sem_pagar_sem_aula")):
        e = estado(con_temp, cid)
        [a] = [x for x in lista if x["nome"] == e["nome"]]
        assert e["situacao"] == situacao and a["texto"] == alunos.frase(e) and a["acoes"] == e["acoes"] and a["cor"] == e["cor"]
        assert a["url"] == f"/clientes/{cid}"
    assert not [x for x in lista if x.get("nome") == "Tudo Certo"]               # em dia: sem alerta
    [grupo] = [x for x in lista if "cadastro incompleto" in x["texto"]]
    assert grupo["texto"].startswith("2 alunos") and grupo["url"] == "/clientes?ids=" + ",".join(map(str, sorted(incompletos))) + "&motivo=incompleto"
    assert [a["grav"] for a in lista] == sorted(a["grav"] for a in lista)


def test_painel_mostra_os_botoes_pulou_e_credito(con_temp, http):
    sem_bloqueio(con_temp)
    cid, _ = aluno_pago_sem_aula(con_temp)
    painel = http.get("/").text
    assert f'data-abrir="dlg-pulou" data-voltar="/" data-titulo=' in painel and f'data-acao="/alunos/{cid}/pulou"' in painel
    assert 'data-abrir="dlg-credito"' in painel and "Crédito na próxima (R$ 400,00)" in painel and 'data-valor="400,00"' in painel
    assert painel.count('id="dlg-credito"') == 1 and painel.count('id="dlg-pulou"') == 1 and 'data-nota hidden' in painel


def test_clientes_mostra_o_estado_e_os_botoes_em_cada_card(con_temp, http):
    sem_bloqueio(con_temp)
    cid, _ = aluno_pago_sem_aula(con_temp)
    pg = http.get("/clientes").text
    card = pg[pg.index('<div class="card cartao-aluno'):]
    card = card[:card.index("</div>\n  </div>") + 6]
    assert "Pagou sem aula" in card and "pagou e não teve aula em" in card and 'data-abrir="dlg-credito"' in card and "Pulou o mês" in card
    lista = http.get(f"/clientes?ids={cid}&motivo=sem-aula").text           # o filtro por motivo usa o estado
    assert "Paula" in lista and "Pagou sem aula" in lista and 'data-abrir="dlg-credito"' in lista
    cliente(con_temp, "Em Dia", dia(60))
    ok = [c for c in main.alertas(con_temp)]
    assert ok and "Em Dia</strong>" not in http.get(f"/clientes?ids={cid}&motivo=sem-aula").text


def test_ficha_tem_o_card_situacao_com_os_botoes(con_temp, http):
    sem_bloqueio(con_temp)
    cid, renova = aluno_pago_sem_aula(con_temp)
    pg = http.get(f"/clientes/{cid}").text
    card = pg.split('id="situacao"')[1].split("</div>\n</div>")[0]
    assert "Situação" in card and "Pagou sem aula" in card and f"Pagou e não teve aula em {mes_do_ciclo(renova)}." in card
    assert 'data-abrir="dlg-credito"' in card and 'data-abrir="dlg-pulou"' in card
    assert pg.index('id="situacao"') < pg.index('id="renovacao"') < pg.index('id="cadastro"')   # no topo
    novo = http.get("/clientes/novo")
    assert novo.status_code == 200 and 'id="situacao"' not in novo.text
    http.post(f"/alunos/{cid}/credito", data={"valor": "100"})
    pg = http.get(f"/clientes/{cid}").text
    assert 'data-valor="300,00"' in pg and "Crédito de R$ 100,00 descontado" in pg and "Crédito disponível" in pg


def test_mensalidades_usa_o_estado_e_mostra_credito(con_temp, http):
    sem_bloqueio(con_temp)
    cid, _ = aluno_pago_sem_aula(con_temp)
    mes = dt.date.today().isoformat()[:7]
    pg = http.get(f"/financeiro/mensalidades?mes={mes}").text
    assert "Pagou sem aula" in pg and 'data-abrir="dlg-pulou"' in pg and 'data-abrir="dlg-credito"' in pg
    http.post(f"/alunos/{cid}/credito", data={"valor": "100,00", "mes": financeiro.somar_meses(mes, -1)})
    proximo = financeiro.somar_meses(mes, 1)
    pg = http.get(f"/financeiro/mensalidades?mes={proximo}").text
    assert "crédito R$ 100,00" in pg and 'data-valor="300,00"' in pg and 'data-nota="Crédito de R$ 100,00 descontado"' in pg


# ---------- Assistente ----------
def test_assistente_situacao_alunos_e_dar_credito(con_temp):
    sem_bloqueio(con_temp)
    cid, _ = aluno_pago_sem_aula(con_temp, "Paula")
    treinando(con_temp, cliente(con_temp, "Tudo Certo", dia(60)))
    saida, erro = assistente.executar(con_temp, "situacao_alunos", {})
    r = json.loads(saida)
    assert not erro and [a["nome"] for a in r["alunos"]] == ["Paula"] and r["total_ativos"] == 2     # sem filtro: só quem precisa de atenção
    p = r["alunos"][0]
    assert p["situacao"] == "pago_sem_aula" and p["credito_sugerido"] == 400.0 and p["solucoes"] == ["Pulou o mês", "Crédito na próxima (R$ 400,00)"]
    r = json.loads(assistente.executar(con_temp, "situacao_alunos", {"situacao": "em_dia"})[0])
    assert [(a["nome"], a["situacao"]) for a in r["alunos"]] == [("Tudo Certo", "em_dia")]
    assert assistente.executar(con_temp, "situacao_alunos", {"situacao": "inventada"})[1]

    saida, erro = assistente.executar(con_temp, "dar_credito", {"aluno": "paula", "valor": 120})
    assert not erro and json.loads(saida)["ok"]
    assert tuple(con_temp.execute("SELECT valor, descricao FROM cliente_eventos WHERE tipo='credito'").fetchone())[0] == 120.0
    assert estado(con_temp, cid)["credito"] == 120.0
    saida, erro = assistente.executar(con_temp, "dar_credito", {"aluno": "paula", "valor": 50})
    assert erro and "já tem crédito" in saida
    assert assistente.executar(con_temp, "dar_credito", {"aluno": "ninguém"})[1] and assistente.executar(con_temp, "dar_credito", {"aluno": "paula", "valor": -1})[1]
    ver = json.loads(assistente.executar(con_temp, "ver_aluno", {"cliente_id": cid})[0])
    assert ver["situacao"]["credito_a_descontar"] == 120.0


def test_assistente_avisa_que_a_situacao_vem_do_algoritmo_central():
    assert "algoritmo central" in assistente.SISTEMA and "situacao_alunos" in assistente.SISTEMA and "dar_credito" in assistente.SISTEMA
    nomes = [f["name"] for f in assistente.FERRAMENTAS]
    assert nomes[-3:-1] == ["situacao_alunos", "dar_credito"]
    assert assistente.rotulo("situacao_alunos") != "situacao_alunos" and assistente.rotulo("dar_credito") != "dar_credito"
    esquema = next(f for f in assistente.FERRAMENTAS if f["name"] == "dar_credito")["input_schema"]
    assert esquema["required"] == ["aluno"] and set(esquema["properties"]) == {"aluno", "valor", "mes"}


def test_pagina_do_painel_e_telas_continuam_abrindo_com_credito_e_pulo(con_temp, http):
    sem_bloqueio(con_temp)
    cid, _ = aluno_pago_sem_aula(con_temp)
    http.post(f"/alunos/{cid}/credito", data={"valor": "100"})
    http.post(f"/alunos/{cid}/pulou", data={})
    for url in ("/", "/clientes", f"/clientes/{cid}", "/financeiro/mensalidades", "/financeiro/previsao", "/dados", "/assistente"):
        assert http.get(url).status_code == 200, url
    assert re.search(r"pulou o mês", http.get(f"/clientes/{cid}").text)
