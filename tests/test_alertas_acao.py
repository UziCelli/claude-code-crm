"""Alertas que resolvem: cada alerta abre a ação certa (pagar, pular mês, agenda, lista filtrada, WhatsApp, diálogo de saldos)."""
import datetime as dt
import re
import types
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app import db, financeiro, main
from tests.test_alertas import cliente, con_temp, dia, do_aluno  # noqa: F401  (con_temp: fixture de banco temporário)


@pytest.fixture
def http(con_temp):
    # sem "with": o lifespan não roda; o app abre o mesmo banco temporário do con_temp
    return TestClient(main.app, base_url="http://localhost")


def alerta(con, trecho):
    [a] = [x for x in main.alertas(con) if trecho in x["texto"]]
    return a


def de_renovacao(con, nome):
    [a] = [x for x in do_aluno(con, nome) if "renovação" in x["texto"]]
    return a


def congelar(monkeypatch, iso):
    """Para o main, hoje é `iso` (o resto do código usa a data real)."""
    class Data(dt.date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(iso)
    ns = {k: getattr(dt, k) for k in dir(dt) if not k.startswith("__")}
    monkeypatch.setattr(main, "dt", types.SimpleNamespace(**{**ns, "date": Data}))


# ---------- renovação ----------
def test_renovacao_vencida_tem_registrar_pagamento_cobrar_e_pular_mes(con_temp, http):
    cid = cliente(con_temp, "Dora", dia(-20), valor=400)
    a = de_renovacao(con_temp, "Dora")
    pagar, wa, pular = a["acoes"]
    venceu = dt.date.today() - dt.timedelta(days=20)
    assert pagar["rotulo"] == "Registrar pagamento" and pagar["dialogo"] == "dlg-pgto"
    assert pagar["dados"] == {"titulo": "Registrar pagamento de Dora", "cliente_id": cid, "valor": "400,00",
                              "descricao": f"Mensalidade {venceu:%m/%Y}"}   # o mês que venceu, não o de hoje
    assert wa == {"wa": True} and a["botao"].startswith("Cobrar R$")        # a cobrança continua do jeito de antes
    assert pular == {"rotulo": "Pular mês", "href": f"/clientes/{cid}#renovacao"}

    painel = http.get("/").text
    assert painel.count('id="dlg-pgto"') == 1
    assert f'data-abrir="dlg-pgto" data-voltar="/" data-titulo="Registrar pagamento de Dora" data-cliente_id="{cid}" data-valor="400,00"' in painel
    assert f'data-descricao="Mensalidade {venceu:%m/%Y}"' in painel
    assert f'href="/clientes/{cid}#renovacao"' in painel and "Pular mês" in painel and "Cobrar R$" in painel


def test_pular_mes_leva_ao_cartao_da_ficha(con_temp, http):
    cid = cliente(con_temp, "Dora", dia(-20))
    ficha = http.get(f"/clientes/{cid}").text
    card = ficha.split('id="renovacao"')[1].split("</form>")[0]
    assert "Pular sem cobrança" in card
    assert 'id="cadastro"' in ficha and ficha.count('id="dlg-pgto"') == 1   # o diálogo vem do base.html, uma vez só


def test_renovacao_a_vencer_tem_registrar_pagamento_e_whatsapp_sem_pular(con_temp):
    cid = cliente(con_temp, "Proxima", dia(3), valor=300)
    with con_temp:
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', ?)", (cid, dia(-2)))   # veio neste ciclo
    a = de_renovacao(con_temp, "Proxima")
    assert [x.get("rotulo", "wa") for x in a["acoes"]] == ["Registrar pagamento", "wa"]
    assert a["acoes"][0]["dados"]["cliente_id"] == cid and a["acoes"][0]["dados"]["valor"] == "300,00"


def test_pagamento_pelo_alerta_volta_para_o_painel_e_tira_o_alerta(con_temp, http):
    cid = cliente(con_temp, "Dora", dia(-20), valor=400)
    hoje = dt.date.today().isoformat()
    r = http.post("/financeiro/lancamento", data={"escopo": "PJ", "tipo": "entrada", "data": hoje, "pago_em": hoje, "valor": "400,00",
                  "categoria": "Mensalidade (Aulas Presenciais)", "cliente_id": cid, "voltar": "/"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/?msg=")
    assert all(x["cor"] != "vermelho" for x in do_aluno(con_temp, "Dora"))


def test_botao_do_alerta_volta_para_a_tela_onde_esta(con_temp, http):
    cliente(con_temp, "Dora", dia(-20))
    assert 'data-voltar="/"' in http.get("/").text
    assert 'data-voltar="/clientes"' in http.get("/clientes").text    # lista recolhida das outras telas
    assert 'data-voltar="/agenda"' in http.get("/agenda").text


# ---------- contas vencidas ----------
def test_contas_vencidas_abre_lista_com_as_do_mes_seguinte(con_temp, http, monkeypatch):
    """29/09: a conta de 01/10 (vence em 3 dias) entra no alerta e a tela do mês (setembro) não a mostra; o card dá o botão de pagar."""
    congelar(monkeypatch, "2026-09-29")
    with con_temp:
        con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, descricao) VALUES ('PJ','saida','2026-09-20',100,'Outros','Conta atrasada')")
        con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, descricao) VALUES ('PJ','saida','2026-10-01',50,'Outros','Conta de outubro')")
        con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, descricao) VALUES ('PJ','saida','2026-10-05',70,'Outros','Conta longe')")
        con_temp.execute("INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, inicio) VALUES ('PJ','Aluguel','Aluguel',900,2,'2026-10')")
    a = alerta(con_temp, "vencida")
    assert a["texto"].startswith("3 contas vencidas ou vencendo em 3 dias") and a["url"] == "/financeiro?vencidas=1#vencidas"
    assert [p["descricao"] for p in main.contas_vencendo(con_temp, "2026-09-29")] == ["Conta atrasada", "Conta de outubro", "Aluguel"]

    sem = http.get("/financeiro").text
    assert 'id="vencidas"' not in sem and "Conta de outubro" not in sem       # a tela comum só mostra setembro
    pg = http.get("/financeiro?vencidas=1").text
    card = pg.split('id="vencidas"')[1].split("</table>")[0]
    assert "Contas vencidas ou vencendo" in card and card.index("Conta atrasada") < card.index("Conta de outubro")
    assert "Aluguel" in card and "Conta longe" not in pg
    assert card.count('data-abrir="dlg-baixa"') == 2 and card.count('data-abrir="dlg-pagar"') == 1   # lançamento: Dar baixa; recorrente: Pagar
    assert 'data-competencia="2026-10"' in card
    assert 'name="volta" value="mes=2026-09&amp;escopo=todos&amp;vencidas=1"' in pg                  # depois de pagar, continua na lista


def test_vencidas_sem_nada_diz_que_esta_em_dia(con_temp, http):
    pg = http.get("/financeiro?vencidas=1").text
    assert 'id="vencidas"' in pg and "Tudo em dia" in pg


# ---------- saldos ----------
def test_saldos_velhos_abrem_o_dialogo_de_saldos(con_temp, http):
    financeiro.salvar_saldos(con_temp, dia(-20), {"Inter": 1000.0}, {"Inter": "PJ"})
    a = alerta(con_temp, "Saldos das contas sem atualizar")
    assert a["url"] == "/financeiro?abrir=saldos"
    pg = http.get(a["url"]).text
    assert 'id="dlg-saldos"' in pg
    js = http.get("/static/app.js").text
    assert 'get("abrir")' in js and '"dlg-" + nome' in js          # o parâmetro abre o diálogo dlg-<nome>


def test_saldo_livre_negativo_leva_ao_cartao_quanto_da_para_gastar(con_temp, http):
    hoje = dt.date.today().isoformat()
    financeiro.salvar_saldos(con_temp, hoje, {"Itaú": 50.0}, {"Itaú": "PF"})
    with con_temp:
        con_temp.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria) VALUES ('PF','saida',?,500,'Outros')", (dia(-1),))
    a = alerta(con_temp, "Saldo livre PF negativo")
    assert a["url"] == "/financeiro#livre"
    assert 'id="livre"' in http.get("/financeiro").text


# ---------- sem aula ----------
def test_sem_aula_desde_tem_abrir_agenda_do_aluno(con_temp):
    cid = cliente(con_temp, "Fabio", dia(30))
    with con_temp:
        con_temp.execute("DELETE FROM campanha_fases WHERE tipo='bloqueio'")
        con_temp.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', ?)", (cid, dia(-16)))
    a = [x for x in do_aluno(con_temp, "Fabio") if "sem aula desde" in x["texto"]][0]
    assert [x.get("rotulo", "wa") for x in a["acoes"]] == ["Abrir agenda", "wa"]
    assert a["acoes"][0]["href"] == f"/agenda?aluno={cid}"


def test_sem_nenhuma_aula_vira_um_alerta_por_aluno_e_abre_a_lista_filtrada(con_temp, http):
    ids = {n: cliente(con_temp, n, dia(30), inicio=dia(-60)) for n in ("Bruno", "Ana")}
    cliente(con_temp, "Novato", dia(30), inicio=dia(-3))            # começou agora: fora do alerta
    cliente(con_temp, "Online", dia(30), tipo="Consultoria Online")
    for n, cid in ids.items():   # um alerta por aluno, com a saída "Não tem aula (consultoria)" que leva à lista dele
        a = alerta(con_temp, f"{n} —")
        assert a["acoes"][-1] == {"rotulo": "Não tem aula (consultoria)", "href": f"/clientes?ids={cid}&motivo=sem-aula"}
    lista = f"/clientes?ids={','.join(map(str, ids.values()))}&motivo=sem-aula"

    pg = http.get(lista).text
    assert "Alunos sem nenhuma aula registrada" in pg and 'href="/clientes">Ver todos' in pg
    assert "Bruno" in pg and "Ana" in pg and "Novato" not in pg and "Online" not in pg.replace("Consultoria Online", "")
    for cid in ids.values():
        assert f'href="/agenda?aluno={cid}"' in pg and f'action="/clientes/{cid}/consultoria"' in pg
    assert pg.count('name="tipo_servico"') == 2 and pg.count('class="btn pequeno" href="/agenda?aluno=') == 2
    assert "Novato" in http.get("/clientes").text                    # a lista normal continua inteira


def test_lista_filtrada_ignora_ids_tortos_e_corta_em_200(con_temp, http):
    with con_temp:
        con_temp.executemany("INSERT INTO clientes (nome, status, tipo_servico) VALUES (?, 'ativo', 'Pacote de Aulas')",
                             [(f"Aluno {i}",) for i in range(205)])
    pg = http.get("/clientes?motivo=sem-aula&ids=" + ",".join(str(i) for i in range(1, 206))).text
    assert pg.count('/consultoria"') == 200
    pg = http.get("/clientes?motivo=sem-aula&ids=" + quote("1,x,-3,1e3,,<b>,1")).text
    assert pg.count('/consultoria"') == 1 and "<b>" not in pg
    assert http.get("/clientes?motivo=sem-aula&ids=abc").status_code == 200   # sem id válido: lista normal


def test_nao_tem_aula_muda_o_tipo_de_servico_e_o_aluno_sai_da_lista(con_temp, http):
    a_id = cliente(con_temp, "Ana", dia(30), inicio=dia(-60))
    b_id = cliente(con_temp, "Bruno", dia(30), inicio=dia(-60))
    lista = f"/clientes?ids={a_id},{b_id}&motivo=sem-aula"
    r = http.post(f"/clientes/{a_id}/consultoria", data={"tipo_servico": "Consultoria Online", "voltar": lista}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(lista + "&msg=")
    assert con_temp.execute("SELECT tipo_servico FROM clientes WHERE id=?", (a_id,)).fetchone()[0] == "Consultoria Online"
    pg = http.get(r.headers["location"]).text
    assert "Bruno" in pg and "Ana</strong>" not in pg and "Ana: Consultoria Online" in pg
    assert not [x for x in main.alertas(con_temp) if "Ana" in x["texto"]]
    http.post(f"/clientes/{b_id}/consultoria", data={"tipo_servico": "Consultoria Híbrida", "voltar": lista})
    assert con_temp.execute("SELECT tipo_servico FROM clientes WHERE id=?", (b_id,)).fetchone()[0] == "Consultoria Híbrida"
    assert "Bruno</strong>" not in http.get(lista).text   # Híbrida sem horário fixo também não tem aula (mesma regra tem_aulas)


@pytest.mark.parametrize("valor", ["Pacote de Aulas", "Mensalidade", "", "consultoria online", "Consultoria Online; DROP"])
def test_nao_tem_aula_recusa_outros_valores(con_temp, http, valor):
    cid = cliente(con_temp, "Ana", dia(30), inicio=dia(-60))
    r = http.post(f"/clientes/{cid}/consultoria", data={"tipo_servico": valor, "voltar": "/clientes?ids=1&motivo=sem-aula"}, follow_redirects=False)
    assert r.status_code == 303 and "erro=" in r.headers["location"]
    assert con_temp.execute("SELECT tipo_servico FROM clientes WHERE id=?", (cid,)).fetchone()[0] == "Pacote de Aulas"


@pytest.mark.parametrize("voltar", ["//evil.com", "http://evil.com", "https://evil.com/clientes", "/\\evil.com", "evil", "", "/financeiro"])
def test_nao_tem_aula_com_voltar_inseguro_cai_em_clientes(con_temp, http, voltar):
    cid = cliente(con_temp, "Ana", dia(30), inicio=dia(-60))
    r = http.post(f"/clientes/{cid}/consultoria", data={"tipo_servico": "Consultoria Online", "voltar": voltar}, follow_redirects=False)
    loc = r.headers["location"]
    assert loc.startswith("/clientes?msg=") and "evil" not in loc
    assert http.post("/clientes/9999/consultoria", data={"tipo_servico": "Consultoria Online"}, follow_redirects=False).headers["location"].startswith("/clientes?erro=")


# ---------- cadastro incompleto ----------
def test_cadastro_incompleto_mostra_o_que_falta_e_leva_ao_cadastro(con_temp, http):
    with con_temp:
        sem_tel = con_temp.execute("INSERT INTO clientes (nome, status, data_renovacao) VALUES ('Sem Tel', 'ativo', ?)", (dia(60),)).lastrowid
        sem_ren = con_temp.execute("INSERT INTO clientes (nome, telefone, status) VALUES ('Sem Ren', '11999990000', 'ativo')").lastrowid
        nada = con_temp.execute("INSERT INTO clientes (nome, status) VALUES ('Sem Nada', 'ativo')").lastrowid
    cliente(con_temp, "Zeca Pronto", dia(60), tipo="Consultoria Online")
    a = alerta(con_temp, "cadastro incompleto")
    m = re.fullmatch(r"/clientes\?ids=([\d,]+)&motivo=incompleto", a["url"])
    assert m and {int(i) for i in m[1].split(",")} == {sem_tel, sem_ren, nada}

    pg = http.get(a["url"]).text
    assert "Cadastro incompleto" in pg and "Zeca Pronto" not in pg
    blocos = pg.split('<div class="card borda-')[1:]   # um por aluno
    cards = {n: next(b for b in blocos if f"<strong>{n}</strong>" in b) for n in ("Sem Tel", "Sem Ren", "Sem Nada")}
    assert "falta telefone" in cards["Sem Tel"] and "falta data de renovação" not in cards["Sem Tel"]
    assert "falta data de renovação" in cards["Sem Ren"] and "falta telefone" not in cards["Sem Ren"]
    assert "falta telefone" in cards["Sem Nada"] and "falta data de renovação" in cards["Sem Nada"]
    for cid in (sem_tel, sem_ren, nada):
        assert f'href="/clientes/{cid}#cadastro">Completar' in pg
    assert "Não tem aula" not in pg
    with con_temp:
        con_temp.execute("UPDATE clientes SET telefone='11988887777' WHERE id=?", (sem_tel,))
    assert "Sem Tel" not in http.get(a["url"]).text                   # completou: sai da lista


# ---------- leads ----------
def test_lead_com_telefone_tem_whatsapp_e_sem_telefone_nao(con_temp, http):
    with con_temp:
        con_temp.execute("""INSERT INTO leads (nome, telefone, canal_origem, proxima_acao, data_proxima_acao)
                            VALUES ('Lia', '(11) 98765-4321', 'Instagram', 'Ligar', ?)""", (dia(-1),))
        con_temp.execute("INSERT INTO leads (nome, canal_origem, proxima_acao, data_proxima_acao) VALUES ('Sem Fone', 'Instagram', 'Ligar', ?)", (dia(-1),))
    lia, sem = alerta(con_temp, "Lia —"), alerta(con_temp, "Sem Fone —")
    assert lia["acoes"] == [{"rotulo": "WhatsApp", "href": "https://wa.me/5511987654321?text=", "externo": True}]
    assert sem["acoes"] == []
    painel = http.get("/").text
    assert 'href="https://wa.me/5511987654321?text="' in painel and painel.count("wa.me") == 1
