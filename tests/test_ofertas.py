"""Ofertas de upsell (app/ofertas.py): cadastro em Campanhas, mensagem transparente, card da ficha, aceitou/recusou, alerta do fim do
valor da oferta, sugestão, resultado, lista de Clientes e lixeira."""
import datetime as dt
import re
import sqlite3
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from app import alunos, db, main, ofertas
from tests.test_marcadores import HOJE, cliente_http, con_temp, montar  # noqa: F401
from tests.test_sugestoes import aluno, sem_bloqueio, todas

HOJE_REAL = dt.date.today()
DADOS = {"titulo_oferta": "Passar para 3x por semana", "inclui": "3 treinos por semana e avaliação todo mês", "valor_normal": "400,00",
         "valor_oferta": "350,00", "meses_desconto": "3", "valida_ate": "2027-12-31"}


def criar(http, **mudar):
    return http.post("/campanhas/ofertas", data={**DADOS, **mudar}, follow_redirects=False)


def oferta(con, **mudar):
    d = {"titulo": "Passar para 3x", "inclui": "3 treinos por semana", "valor_normal": 400.0, "valor_oferta": 350.0, "meses_desconto": 3,
         "valida_ate": None, **mudar}
    return ofertas.salvar(con, None, d)


def cliente(con, nome="Ana", valor=300, tel="11999990000", status="ativo"):
    with con:
        return con.execute("INSERT INTO clientes (nome, telefone, status, valor, data_renovacao) VALUES (?,?,?,?, '2027-06-20')",
                           (nome, tel, status, valor)).lastrowid


def resposta(con, oid, cid):
    r = con.execute("SELECT * FROM oferta_respostas WHERE oferta_id=? AND cliente_id=?", (oid, cid)).fetchone()
    return dict(r) if r else None


def eventos(con, cid, tipo):
    return [r["descricao"] for r in con.execute("SELECT descricao FROM cliente_eventos WHERE cliente_id=? AND tipo=? AND excluido_em IS NULL", (cid, tipo))]


def valor(con, cid):
    return con.execute("SELECT valor FROM clientes WHERE id=?", (cid,)).fetchone()[0]


def alertas_desconto(con):
    return [a for a in main.alertas(con) if a["texto"].startswith("O desconto de")]


# ---------- banco ----------
def test_tabelas_criadas_em_banco_antigo(tmp_path):
    caminho = tmp_path / "antigo.db"
    raw = sqlite3.connect(caminho)
    raw.executescript(db.SCHEMA.read_text(encoding="utf-8"))
    raw.executescript("DROP TABLE oferta_respostas; DROP TABLE ofertas;")
    raw.commit()
    raw.close()
    db.iniciar_banco(caminho)
    raw = sqlite3.connect(caminho)
    assert {"ofertas", "oferta_respostas"} <= {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "upsell" in {r[0] for r in raw.execute("SELECT chave FROM parametros WHERE grupo='msg_whatsapp'")}
    raw.close()


def test_uma_resposta_por_oferta_e_aluno_e_status_valido(con_temp):
    oid, cid = oferta(con_temp), cliente(con_temp)
    ofertas._gravar(con_temp, oid, cid, "enviada", "2026-11-01")
    ofertas._gravar(con_temp, oid, cid, "recusou", "2026-11-02")   # upsert: continua uma linha
    assert con_temp.execute("SELECT COUNT(*), MIN(status) FROM oferta_respostas").fetchone()[:] == (1, "recusou")
    with pytest.raises(sqlite3.IntegrityError):
        con_temp.execute("INSERT INTO oferta_respostas (oferta_id, cliente_id, status) VALUES (?,?, 'talvez')", (oid, cliente(con_temp, "Bia")))


# ---------- Campanhas: criar, editar, pausar, excluir ----------
def test_criar_editar_pausar_e_excluir_oferta(cliente_http):
    http, con = cliente_http
    r = criar(http)
    assert r.status_code == 303 and "msg=" in r.headers["location"] and "erro=" not in r.headers["location"]
    o = dict(con.execute("SELECT * FROM ofertas").fetchone())
    assert (o["titulo"], o["valor_normal"], o["valor_oferta"], o["meses_desconto"], o["valida_ate"], o["ativa"]) == (
        "Passar para 3x por semana", 400.0, 350.0, 3, "2027-12-31", 1)
    r = criar(http, id=str(o["id"]), titulo_oferta="Passar para 2x", valor_oferta="360", meses_desconto="", valida_ate="")
    assert "msg=" in r.headers["location"]
    o = dict(con.execute("SELECT * FROM ofertas").fetchone())
    assert con.execute("SELECT COUNT(*) FROM ofertas").fetchone()[0] == 1
    assert (o["titulo"], o["valor_oferta"], o["meses_desconto"], o["valida_ate"]) == ("Passar para 2x", 360.0, None, None)   # vazio = sempre
    http.post(f"/campanhas/ofertas/{o['id']}/ativa")
    assert con.execute("SELECT ativa FROM ofertas").fetchone()[0] == 0 and ofertas.ativas(con) == []
    http.post(f"/campanhas/ofertas/{o['id']}/ativa")
    assert con.execute("SELECT ativa FROM ofertas").fetchone()[0] == 1 and len(ofertas.ativas(con)) == 1
    http.post(f"/campanhas/ofertas/{o['id']}/excluir")
    assert con.execute("SELECT excluido_em FROM ofertas").fetchone()[0] is not None and ofertas.todas(con) == []


@pytest.mark.parametrize("mudar, trecho", [
    ({"titulo_oferta": "  "}, "título"), ({"inclui": ""}, "inclui"), ({"valor_normal": "0"}, "valor normal"),
    ({"valor_oferta": "400"}, "menor que o valor normal"), ({"valor_oferta": "450"}, "menor que o valor normal"),
    ({"valor_oferta": "0"}, "menor que o valor normal"), ({"valor_oferta": "abc"}, "Valor inválido"),
    ({"meses_desconto": "0"}, "Meses"), ({"meses_desconto": "x"}, "Meses"), ({"valida_ate": "31/12/2027"}, "Validade")])
def test_oferta_invalida_nao_salva(cliente_http, mudar, trecho):
    http, con = cliente_http
    r = criar(http, **mudar)
    assert "erro=" in unquote(r.headers["location"]) and trecho in unquote(r.headers["location"])
    assert con.execute("SELECT COUNT(*) FROM ofertas").fetchone()[0] == 0


def test_editar_oferta_inexistente_da_erro(cliente_http):
    http, con = cliente_http
    assert "erro=" in criar(http, id="99").headers["location"]
    assert "erro=" in http.post("/campanhas/ofertas/99/ativa", follow_redirects=False).headers["location"]
    assert "erro=" in http.post("/campanhas/ofertas/99/excluir", follow_redirects=False).headers["location"]


# ---------- a mensagem ----------
def modelo(con):
    return db.parametros(con, "msg_whatsapp")["upsell"]


def test_mensagem_transparente_com_prazo_e_validade(con_temp):
    o = oferta(con_temp, valida_ate="2027-12-31", inclui="3 treinos por semana.")
    t = ofertas.texto(ofertas.obter(con_temp, o), "Ana", modelo(con_temp))
    assert t == ("Oi, Ana! Tenho uma proposta: Passar para 3x. Inclui: 3 treinos por semana. De R$ 400,00 por R$ 350,00/mês nos primeiros 3 meses "
                 "(depois volta para R$ 400,00). Válida até 31/12/2027. Quer aproveitar? Victor | VFITCOACH")


def test_mensagem_sem_prazo_e_sem_validade_nao_deixa_texto_pendurado(con_temp):
    o = ofertas.obter(con_temp, oferta(con_temp, meses_desconto=None))
    t = ofertas.texto(o, "Ana", modelo(con_temp))
    assert t == ("Oi, Ana! Tenho uma proposta: Passar para 3x. Inclui: 3 treinos por semana. De R$ 400,00 por R$ 350,00/mês. "
                 "Quer aproveitar? Victor | VFITCOACH")
    for sobra in ("{", "}", "primeiros", "depois", "Válida", "  ", ".."):
        assert sobra not in t
    um = ofertas.obter(con_temp, oferta(con_temp, meses_desconto=1))
    assert "no primeiro mês (depois volta para R$ 400,00)" in ofertas.texto(um, "Ana", modelo(con_temp))


def test_previa_usa_o_mesmo_texto_e_aceita_formulario_pela_metade(cliente_http):
    http, con = cliente_http
    r = http.get("/campanhas/ofertas/previa", params={"titulo": "Passar para 3x", "inclui": "3 treinos", "valor_normal": "400", "valor_oferta": "350",
                                                       "meses_desconto": "2", "valida_ate": "2027-12-31"})
    assert r.status_code == 200 and r.text.startswith("Oi, Maria! Tenho uma proposta: Passar para 3x. Inclui: 3 treinos. De R$ 400,00 por R$ 350,00/mês")
    assert "nos primeiros 2 meses (depois volta para R$ 400,00). Válida até 31/12/2027." in r.text
    vazio = http.get("/campanhas/ofertas/previa").text
    assert "(título da oferta)" in vazio and "(o que inclui)" in vazio and "{" not in vazio
    assert "Válida" not in http.get("/campanhas/ofertas/previa", params={"valida_ate": "lixo"}).text


def test_mensagem_usa_o_modelo_editado(cliente_http):
    http, con = cliente_http
    with con:
        con.execute("UPDATE parametros SET valor_texto='Olá {nome}: {titulo} por {valor_oferta}{ate}' WHERE grupo='msg_whatsapp' AND chave='upsell'")
    assert http.get("/campanhas/ofertas/previa", params={"titulo": "X", "valor_oferta": "10"}).text == "Olá Maria: X por R$ 10,00"


def test_campanhas_mostra_card_com_resultado_e_botoes(cliente_http):
    http, con = cliente_http
    html = http.get("/campanhas").text
    assert "Ofertas (upsell)" in html and "Nenhuma oferta ainda" in html and "Nova oferta" in html
    o = oferta(con)
    a, b = cliente(con, "Ana", 300), cliente(con, "Bia", 300)
    ofertas.registrar_envio(con, a, o)
    ofertas.registrar_envio(con, b, o)
    ofertas.aceitou(con, a, o)
    html = http.get("/campanhas").text
    assert "Passar para 3x" in html and "Enviada a 2 · 1 aceitou (50%) · +R$ 50,00/mês" in html
    assert "De R$ 400,00 por <strong>R$ 350,00/mês</strong>" in html and "nos primeiros 3 meses" in html
    for botao in ("Pausar", "Editar", "Excluir"):
        assert botao in html
    http.post(f"/campanhas/ofertas/{o}/ativa")
    assert "pausada" in http.get("/campanhas").text and ">Ativar<" in http.get("/campanhas").text


# ---------- enviar ----------
def test_enviar_grava_status_evento_e_vai_so_para_o_whatsapp(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con), cliente(con, "Ana")
    r = http.post(f"/clientes/{cid}/oferta/{o}/enviar", follow_redirects=False)
    assert r.status_code == 303
    url = r.headers["location"]
    assert url.startswith("https://wa.me/5511999990000?text=")
    texto = parse_qs(urlparse(url).query)["text"][0]
    assert texto.startswith("Oi, Ana! Tenho uma proposta: Passar para 3x. Inclui: 3 treinos por semana. De R$ 400,00 por R$ 350,00/mês")
    r1 = resposta(con, o, cid)
    assert r1["status"] == "enviada" and r1["data"] == HOJE_REAL.isoformat()
    assert eventos(con, cid, "mensagem") == ["Oferta enviada: Passar para 3x"]
    r = http.post(f"/clientes/{cid}/oferta/{o}/enviar", data={"voltar": "https://mal.com"}, follow_redirects=False)   # de novo: continua wa.me
    assert r.headers["location"].startswith("https://wa.me/")
    assert con.execute("SELECT COUNT(*) FROM oferta_respostas").fetchone()[0] == 1


def test_enviar_sem_telefone_volta_com_erro_e_nao_registra(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con), cliente(con, "Sem fone", tel="")
    r = http.post(f"/clientes/{cid}/oferta/{o}/enviar", follow_redirects=False)
    loc = unquote(r.headers["location"])
    assert loc.startswith(f"/clientes/{cid}?erro=") and "telefone" in loc and "wa.me" not in loc
    assert resposta(con, o, cid) is None and eventos(con, cid, "mensagem") == []


def test_enviar_oferta_pausada_ou_quem_ja_aceitou_nao_envia(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con), cliente(con)
    ofertas.aceitou(con, cid, o)
    r = http.post(f"/clientes/{cid}/oferta/{o}/enviar", follow_redirects=False)
    assert "erro=" in r.headers["location"] and not r.headers["location"].startswith("https://")
    assert resposta(con, o, cid)["status"] == "aceitou"
    con.execute("UPDATE ofertas SET ativa=0")
    con.commit()
    outro = cliente(con, "Bia")
    assert "erro=" in http.post(f"/clientes/{outro}/oferta/{o}/enviar", follow_redirects=False).headers["location"]


# ---------- aceitou e recusou ----------
def test_aceitou_atualiza_a_mensalidade_e_guarda_ate_quando(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con), cliente(con, "Ana", valor=300)
    r = http.post(f"/clientes/{cid}/oferta/{o}/aceitou", data={"atualizar": "1"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/clientes/{cid}?msg=")
    assert valor(con, cid) == 350
    r1 = resposta(con, o, cid)
    assert r1["status"] == "aceitou" and r1["valor_antes"] == 300 and r1["data"] == HOJE_REAL.isoformat()
    assert r1["ate_desconto"] == main.financeiro.proxima_renovacao(HOJE_REAL.isoformat(), 3)
    ate = f"{r1['ate_desconto'][8:]}/{r1['ate_desconto'][5:7]}"
    assert eventos(con, cid, "anotacao") == [f"Aceitou a oferta: Passar para 3x (R$ 350,00/mês até {ate})"]


def test_aceitou_sem_marcar_nao_mexe_na_mensalidade(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con), cliente(con, "Ana", valor=300)
    http.post(f"/clientes/{cid}/oferta/{o}/aceitou", data={}, follow_redirects=False)   # caixa desmarcada: o navegador não envia o campo
    assert valor(con, cid) == 300
    r1 = resposta(con, o, cid)
    assert r1["status"] == "aceitou" and r1["valor_antes"] is None and "não alterada" in eventos(con, cid, "anotacao")[0]
    assert ofertas.resultado(con, o)["mais_mes"] == 0     # nada mudou na mensalidade: não conta como receita a mais
    assert alertas_desconto(con) == []                   # e o aviso de fim do valor só vale para quem paga o valor da oferta


def test_aceitou_oferta_sempre_nao_tem_data_de_fim(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con, meses_desconto=None), cliente(con, "Ana", valor=300)
    http.post(f"/clientes/{cid}/oferta/{o}/aceitou", data={"atualizar": "1"})
    assert resposta(con, o, cid)["ate_desconto"] is None and valor(con, cid) == 350
    assert "R$ 350,00/mês)" in eventos(con, cid, "anotacao")[0]


def test_recusou_grava_e_pode_enviar_de_novo(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con), cliente(con)
    r = http.post(f"/clientes/{cid}/oferta/{o}/recusou", follow_redirects=False)
    assert r.headers["location"].startswith(f"/clientes/{cid}?msg=")
    assert resposta(con, o, cid)["status"] == "recusou" and valor(con, cid) == 300
    assert http.post(f"/clientes/{cid}/oferta/{o}/enviar", follow_redirects=False).headers["location"].startswith("https://wa.me/")
    assert resposta(con, o, cid)["status"] == "enviada"


def test_rotas_com_aluno_ou_oferta_que_nao_existem(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con), cliente(con)
    for rota in ("aceitou", "recusou", "enviar", "encerrar-desconto"):
        assert "erro=" in http.post(f"/clientes/999/oferta/{o}/{rota}", follow_redirects=False).headers["location"]
        assert "erro=" in http.post(f"/clientes/{cid}/oferta/999/{rota}", follow_redirects=False).headers["location"]


# ---------- ficha ----------
def test_ficha_so_mostra_o_card_com_oferta_ativa_e_aluno_ativo(cliente_http):
    http, con = cliente_http
    cid = cliente(con, "Ana")
    assert 'id="ofertas"' not in http.get(f"/clientes/{cid}").text            # sem oferta, sem card
    o = oferta(con)
    assert 'id="ofertas"' in http.get(f"/clientes/{cid}").text
    inativo = cliente(con, "Saiu", status="inativo")
    assert 'id="ofertas"' not in http.get(f"/clientes/{inativo}").text
    con.execute("UPDATE ofertas SET ativa=0")
    con.commit()
    assert 'id="ofertas"' not in http.get(f"/clientes/{cid}").text
    con.execute("UPDATE ofertas SET ativa=1, valida_ate=?", ((HOJE_REAL - dt.timedelta(days=1)).isoformat(),))
    con.commit()
    assert 'id="ofertas"' not in http.get(f"/clientes/{cid}").text            # validade vencida: some


def test_ficha_mostra_cada_situacao_com_seus_botoes(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con), cliente(con, "Ana", valor=300)

    def card():
        html = http.get(f"/clientes/{cid}").text
        i = html.index('id="ofertas"')
        return html[i:html.index('<div class="grid c2">', i)]
    c = card()
    assert "Passar para 3x" in c and "De R$ 400,00 por R$ 350,00/mês, nos primeiros 3 meses" in c and "não enviada" in c
    assert "Enviar (WhatsApp)" in c and f'action="/clientes/{cid}/oferta/{o}/enviar"' in c and 'target="_blank"' in c
    assert 'data-abrir="dlg-oferta-aceitou"' in c and f'data-acao="/clientes/{cid}/oferta/{o}/aceitou"' in c and "Recusou" in c
    assert 'data-novo="R$ 350,00"' in c and "Volta para R$ 400,00 em " in c
    http.post(f"/clientes/{cid}/oferta/{o}/enviar")
    c = card()
    assert f"enviada em {HOJE_REAL.strftime('%d/%m/%Y')}" in c and "Enviar de novo" in c
    http.post(f"/clientes/{cid}/oferta/{o}/recusou")
    c = card()
    assert "recusou em" in c and "Enviar de novo" in c and f"/oferta/{o}/recusou" not in c
    http.post(f"/clientes/{cid}/oferta/{o}/aceitou", data={"atualizar": "1"})
    c = card()
    assert "aceitou em" in c and "Vale até" in c and "depois volta para R$ 400,00" in c and "Voltar para R$ 400,00" in c
    assert "Enviar" not in c and "Recusou" not in c
    assert "Aceitou a oferta: Passar para 3x" in http.get(f"/clientes/{cid}").text      # no histórico
    http.post(f"/clientes/{cid}/oferta/{o}/encerrar-desconto")
    c = card()
    assert "encerrado em" in c and "mensalidade em R$ 400,00" in c and "Voltar para" not in c


def test_ficha_historico_mostra_o_envio_sem_quebrar(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con), cliente(con)
    http.post(f"/clientes/{cid}/oferta/{o}/enviar")
    r = http.get(f"/clientes/{cid}")
    assert r.status_code == 200 and "Oferta enviada: Passar para 3x" in r.text


def test_ficha_sem_telefone_leva_ao_cadastro(cliente_http):
    http, con = cliente_http
    oferta(con)
    cid = cliente(con, "Sem fone", tel="")
    c = http.get(f"/clientes/{cid}").text
    assert "Sem telefone: completar" in c and "Enviar (WhatsApp)" not in c


# ---------- alerta do fim do valor da oferta ----------
def aceita_com_fim(con, ate, nome="Ana", valor_atual=350):
    o = oferta(con)
    cid = cliente(con, nome, valor=valor_atual)
    with con:
        con.execute("""INSERT INTO oferta_respostas (oferta_id, cliente_id, status, data, ate_desconto, valor_antes)
                       VALUES (?,?, 'aceitou', ?, ?, 300)""", (o, cid, HOJE_REAL.isoformat(), ate))
    return o, cid


def test_alerta_aparece_7_dias_antes_e_some_ao_atualizar_o_valor(cliente_http):
    http, con = cliente_http
    fim = HOJE_REAL + dt.timedelta(days=8)
    o, cid = aceita_com_fim(con, fim.isoformat())
    assert alertas_desconto(con) == []                                   # faltam 8 dias: ainda não
    con.execute("UPDATE oferta_respostas SET ate_desconto=?", ((HOJE_REAL + dt.timedelta(days=7)).isoformat(),))
    con.commit()
    (a,) = alertas_desconto(con)
    quando = (HOJE_REAL + dt.timedelta(days=7)).strftime("%d/%m")
    assert a["cor"] == "azul" and a["texto"] == f"O desconto de Ana acaba em {quando}: volta para R$ 400,00"
    assert a["url"] == f"/clientes/{cid}#ofertas"
    (acao,) = a["acoes"]
    assert acao["rotulo"] == "Atualizar valor" and acao["dialogo"] == "dlg-oferta-encerrar"
    assert acao["dados"]["acao"] == f"/clientes/{cid}/oferta/{o}/encerrar-desconto" and "R$ 350,00 para R$ 400,00" in acao["dados"]["titulo"]
    html = http.get("/campanhas").text                                    # o botão aparece nas telas e o diálogo existe
    assert 'id="dlg-oferta-encerrar"' in html and 'data-abrir="dlg-oferta-encerrar"' in html and "Atualizar valor" in html
    r = http.post(f"/clientes/{cid}/oferta/{o}/encerrar-desconto", follow_redirects=False)
    assert r.headers["location"].startswith(f"/clientes/{cid}?msg=")
    assert valor(con, cid) == 400 and resposta(con, o, cid)["encerrado_em"] == HOJE_REAL.isoformat()
    assert alertas_desconto(con) == []
    assert "mensalidade voltou para R$ 400,00" in eventos(con, cid, "anotacao")[0]


def test_alerta_continua_depois_do_fim_ate_resolver_e_some_se_o_valor_ja_voltou(cliente_http):
    http, con = cliente_http
    o, cid = aceita_com_fim(con, (HOJE_REAL - dt.timedelta(days=2)).isoformat())
    (a,) = alertas_desconto(con)
    assert "acabou em" in a["texto"]
    with con:
        con.execute("UPDATE clientes SET valor=400")                   # o valor foi ajustado na mão: nada a avisar
    assert alertas_desconto(con) == []


def test_alerta_so_para_aluno_ativo_e_oferta_nao_excluida(cliente_http):
    http, con = cliente_http
    o, cid = aceita_com_fim(con, HOJE_REAL.isoformat())
    assert len(alertas_desconto(con)) == 1
    with con:
        con.execute("UPDATE clientes SET status='inativo'")
    assert alertas_desconto(con) == []
    with con:
        con.execute("UPDATE clientes SET status='ativo'")
    ofertas.excluir(con, o)
    assert alertas_desconto(con) == []


def test_encerrar_desconto_de_quem_nao_aceitou_da_erro(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con), cliente(con, valor=300)
    r = http.post(f"/clientes/{cid}/oferta/{o}/encerrar-desconto", follow_redirects=False)
    assert "erro=" in r.headers["location"] and valor(con, cid) == 300


# ---------- quem recebe, sugestão ----------
def test_elegiveis_sao_so_os_em_dia_com_telefone_que_ainda_nao_responderam(con_temp):
    montar(con_temp, reserva=40000)
    sem_bloqueio(con_temp)
    o = oferta(con_temp)
    ana, bia = aluno(con_temp, "Ana"), aluno(con_temp, "Bia")
    aluno(con_temp, "Sem fone", tel="")
    aluno(con_temp, "Ex", status="inativo")
    aluno(con_temp, "Parada", treinando=False)                           # sem aula recente: tem outra solução antes
    assert [e["nome"] for e in ofertas.elegiveis(con_temp, o, hoje=HOJE)] == ["Ana", "Bia"]
    ofertas.registrar_envio(con_temp, ana, o, hoje=HOJE)
    assert [e["nome"] for e in ofertas.elegiveis(con_temp, o, hoje=HOJE)] == ["Bia"]
    ofertas.recusou(con_temp, bia, o, hoje=HOJE)
    assert ofertas.elegiveis(con_temp, o, hoje=HOJE) == []
    assert ofertas.elegiveis(con_temp, 999, hoje=HOJE) == []


def test_sugestao_aparece_e_some_quando_todos_ja_receberam(con_temp):
    montar(con_temp, reserva=40000)
    sem_bloqueio(con_temp)
    assert "upsell" not in todas(con_temp)                                # sem oferta
    ana, bia = aluno(con_temp, "Ana", valor=300), aluno(con_temp, "Bia", valor=200)
    o = oferta(con_temp, titulo="Passar para 3x por semana")
    s = todas(con_temp)["upsell"]
    assert s["titulo"] == "Oferta 'Passar para 3x por semana': 2 alunos em dia ainda não receberam."
    assert s["acoes"] == [{"rotulo": "Enviar (2)", "href": f"/clientes?ids={ana},{bia}&motivo=upsell&oferta={o}"}]
    assert s["impacto"] == pytest.approx(2 * (350 - 250) * 0.3) and s["impacto_tipo"] == "mes" and s["cor"] == "azul" and s["marcador"] == "faturamento"
    assert len(s["titulo"]) <= 90 and s["porque"] and len(s["passos"]) <= 3
    ofertas.registrar_envio(con_temp, ana, o, hoje=HOJE)
    s = todas(con_temp)["upsell"]
    assert s["titulo"] == "Oferta 'Passar para 3x por semana': 1 aluno em dia ainda não recebeu." and s["acoes"][0]["rotulo"] == "Enviar (1)"
    ofertas.recusou(con_temp, bia, o, hoje=HOJE)
    assert "upsell" not in todas(con_temp)
    with con_temp:
        con_temp.execute("DELETE FROM oferta_respostas")
    con_temp.execute("UPDATE ofertas SET ativa=0")
    assert "upsell" not in todas(con_temp)                                # oferta pausada


def test_sugestao_com_titulo_longo_cabe_em_90_letras(con_temp):
    montar(con_temp, reserva=40000)
    sem_bloqueio(con_temp)
    aluno(con_temp, "Ana")
    oferta(con_temp, titulo="Pacote completo de treino com avaliação física e acompanhamento nutricional")
    s = todas(con_temp)["upsell"]
    assert len(s["titulo"]) <= 90 and s["titulo"].endswith(".") and "…" in s["titulo"]


def test_sugestao_escolhe_a_oferta_de_mais_impacto(con_temp):
    montar(con_temp, reserva=40000)
    sem_bloqueio(con_temp)
    aluno(con_temp, "Ana", valor=300)
    oferta(con_temp, titulo="Pequena", valor_normal=330.0, valor_oferta=320.0)
    grande = oferta(con_temp, titulo="Grande", valor_normal=600.0, valor_oferta=500.0)
    s = todas(con_temp)["upsell"]
    assert "Grande" in s["titulo"] and s["acoes"][0]["href"].endswith(f"&oferta={grande}")


# ---------- resultado ----------
def test_resultado_enviadas_aceitas_taxa_e_receita_a_mais(con_temp):
    o = oferta(con_temp)
    assert ofertas.resultado(con_temp, o) == {"enviadas": 0, "aceitas": 0, "recusadas": 0, "taxa": 0.0, "mais_mes": 0}
    assert ofertas.resumo(ofertas.resultado(con_temp, o)) == "Ainda não enviada."
    ids = [cliente(con_temp, n, valor=v) for n, v in (("A", 300), ("B", 250), ("C", 300), ("D", 300), ("E", 300))]
    for cid in ids:
        ofertas.registrar_envio(con_temp, cid, o)
    ofertas.aceitou(con_temp, ids[0], o)                                 # 300 -> 350 (+50)
    ofertas.aceitou(con_temp, ids[1], o)                                 # 250 -> 350 (+100)
    ofertas.recusou(con_temp, ids[2], o)
    r = ofertas.resultado(con_temp, o)
    assert r == {"enviadas": 5, "aceitas": 2, "recusadas": 1, "taxa": 0.4, "mais_mes": 150}
    assert ofertas.resumo(r) == "Enviada a 5 · 2 aceitaram (40%) · +R$ 150,00/mês"
    ofertas.encerrar_desconto(con_temp, ids[0], o)                       # voltou ao valor normal: o ganho é o normal menos o de antes
    assert ofertas.resultado(con_temp, o)["mais_mes"] == (400 - 300) + (350 - 250)


# ---------- lista de Clientes ----------
def test_lista_upsell_tem_enviar_oferta_em_cada_card_e_quem_recebeu_sai(cliente_http):
    http, con = cliente_http
    o = oferta(con)
    a, b = cliente(con, "Ana"), cliente(con, "Bia")
    c = cliente(con, "Sem fone", tel="")
    url = f"/clientes?ids={a},{b},{c}&motivo=upsell&oferta={o}"
    r = http.get(url)
    assert r.status_code == 200 and "Alunos para receber a oferta: Passar para 3x" in r.text
    assert f'action="/clientes/{a}/oferta/{o}/enviar"' in r.text and f'action="/clientes/{b}/oferta/{o}/enviar"' in r.text
    assert r.text.count("Enviar oferta") == 2 and "Completar telefone" in r.text and 'target="_blank"' in r.text
    assert "Hoje <strong>R$ 300,00</strong> · oferta <strong>R$ 350,00</strong>" in r.text
    http.post(f"/clientes/{a}/oferta/{o}/enviar")
    r = http.get(url)
    assert f'action="/clientes/{a}/oferta/{o}/enviar"' not in r.text and f'action="/clientes/{b}/oferta/{o}/enviar"' in r.text
    http.post(f"/clientes/{b}/oferta/{o}/recusou")
    assert http.get(url).text.count("Enviar oferta") == 0


def test_lista_upsell_com_oferta_pausada_ou_inexistente_explica_e_leva_a_campanhas(cliente_http):
    http, con = cliente_http
    o, a = oferta(con), cliente(con, "Ana")
    con.execute("UPDATE ofertas SET ativa=0")
    con.commit()
    for oid in (o, 999):
        r = http.get(f"/clientes?ids={a}&motivo=upsell&oferta={oid}")
        assert r.status_code == 200 and "Essa oferta não está ativa" in r.text and "/campanhas#ofertas" in r.text and "Enviar oferta" not in r.text
    assert http.get(f"/clientes?ids={a}&motivo=upsell").status_code == 200       # sem o parâmetro oferta: não quebra


# ---------- lixeira ----------
def test_oferta_excluida_vai_para_a_lixeira_e_volta(cliente_http):
    http, con = cliente_http
    o = oferta(con, titulo="Oferta da lixeira")
    http.post(f"/campanhas/ofertas/{o}/excluir")
    assert ofertas.todas(con) == [] and "Oferta da lixeira" in http.get("/dados").text and "Oferta" in http.get("/dados").text
    r = http.post("/lixeira/restaurar", data={"tabela": "ofertas", "rid": o}, follow_redirects=False)
    assert "msg=" in r.headers["location"]
    assert [x["titulo"] for x in ofertas.todas(con)] == ["Oferta da lixeira"]


# ---------- layout ----------
def test_paginas_com_ofertas_renderizam_em_todas_as_situacoes(cliente_http):
    http, con = cliente_http
    o, cid = oferta(con, valida_ate=(HOJE_REAL + dt.timedelta(days=5)).isoformat()), cliente(con)
    for rota in ("/", "/campanhas", f"/clientes/{cid}", "/clientes", "/dados", "/financeiro/painel"):
        assert http.get(rota).status_code == 200, rota
    assert 'id="dlg-oferta-aceitou"' in http.get("/").text
