"""PR 1: menu WhatsApp da ficha, renovação com valor e PIX, dados das mensagens, registro do envio e pedido de depoimento."""
from urllib.parse import parse_qs, urlparse

from app import alunos, db, financeiro, main
from tests.test_alertas import cliente, con_temp, dia  # noqa: F401  (con_temp: fixture de banco temporário)
from tests.test_alertas_acao import http  # noqa: F401

PIX = "vfitcoach@pix.com"
ITENS = ["renovacao", "boas_vindas", "reativacao", "indicacao", "dupla", "depoimento"]   # "falta" só com aula registrada


def definir(con, chave, valor, grupo="msg_dados"):
    with con:
        con.execute("UPDATE parametros SET valor_texto=? WHERE grupo=? AND chave=?", (valor, grupo, chave))


def evento(con, cid, tipo, data, desc=None):
    with con:
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?,?,?,?)", (cid, tipo, data, desc))


def menu(html):
    """Trecho do HTML do menu WhatsApp."""
    ini = html.index('<details class="menu-wa">')
    return html[ini:html.index("</details>", ini)]


def enviado(r):
    """(host, texto) do redirecionamento para o WhatsApp."""
    assert r.status_code == 303
    u = urlparse(r.headers["location"])
    return u.scheme + "://" + u.netloc, parse_qs(u.query)["text"][0]


# ---------- o menu ----------
def test_menu_tem_todos_os_itens_na_ordem(http, con_temp):
    cid = cliente(con_temp, "Ana", dia(5))
    m = menu(http.get(f"/clientes/{cid}").text)
    pos = [m.index(f"/clientes/{cid}/wa/{k}") for k in ITENS]
    assert pos == sorted(pos)
    assert "/wa/falta" not in m and "/wa/cobranca" not in m   # falta precisa de aula registrada; cobrança, de atraso
    assert "Pedir depoimento" in m and "Treino em dupla" in m and "Indicação" in m


def test_falta_aparece_quando_ha_aula(http, con_temp):
    cid = cliente(con_temp, "Ana", dia(5))
    evento(con_temp, cid, "aula", dia(-20))
    m = menu(http.get(f"/clientes/{cid}").text)
    assert m.index("/wa/renovacao") < m.index("/wa/falta") < m.index("/wa/boas_vindas")


def test_cobrar_vem_primeiro_quando_atrasado(http, con_temp):
    cid = cliente(con_temp, "Dora", dia(-20))
    m = menu(http.get(f"/clientes/{cid}").text)
    assert m.index("/wa/cobranca") < m.index("/wa/renovacao")
    assert "Cobrar R$ 410,67" in m and "destaque" in m


def test_sem_telefone_so_o_aviso(http, con_temp):
    with con_temp:
        cid = con_temp.execute("INSERT INTO clientes (nome, status, data_renovacao) VALUES ('Sem Tel', 'ativo', ?)", (dia(5),)).lastrowid
    html = http.get(f"/clientes/{cid}").text
    m = menu(html)
    assert "Cadastre o telefone" in m and 'href="#telefone"' in m and "/wa/" not in m
    assert 'id="telefone"' in html   # o link tem para onde ir


# ---------- {valor} e {pix} na renovação ----------
def test_renovacao_traz_valor_e_pix(http, con_temp):
    definir(con_temp, "pix", PIX)
    cid = cliente(con_temp, "Ana", dia(5), valor=400)
    host, texto = enviado(http.post(f"/clientes/{cid}/wa/renovacao", follow_redirects=False))
    assert host == "https://wa.me"
    assert texto == f"Oi, Ana! Sua renovação é em {main.data_br(dia(5))}: R$ 400,00. PIX: {PIX}. Pode me mandar o comprovante? Victor | VFITCOACH"


def test_renovacao_com_credito_mostra_a_conta(http, con_temp):
    definir(con_temp, "pix", PIX)
    cid = cliente(con_temp, "Alexei", dia(5), valor=400)
    mes = financeiro.somar_meses(dia(0)[:7], -1)
    msg, erro = alunos.dar_credito(con_temp, cid, 120, mes)
    assert not erro, erro
    esperado = f"R$ 280,00 (R$ 400,00 − R$ 120,00 de crédito das aulas não usadas em {mes[5:7]}/{mes[:4]})"
    _, texto = enviado(http.post(f"/clientes/{cid}/wa/renovacao", follow_redirects=False))
    assert esperado in texto
    # a ficha mostra o valor a pagar no item, e o alerta/lista manda o mesmo texto (um cálculo só)
    assert "R$ 280,00" in menu(http.get(f"/clientes/{cid}").text)
    e = alunos.estado_aluno(con_temp, cid)
    assert e["modelo"] == "renovacao" and e["extra"]["valor"] == esperado
    assert esperado in main.preencher(db.parametros(con_temp, "msg_whatsapp")["renovacao"], "Alexei", e["data_modelo"], e["extra"])


def test_pix_vazio_nao_deixa_a_chave_na_mensagem(http, con_temp):
    cid = cliente(con_temp, "Ana", dia(5))
    _, texto = enviado(http.post(f"/clientes/{cid}/wa/renovacao", follow_redirects=False))
    assert "{" not in texto and "PIX: ." in texto
    assert main.preencher("a {pix} b {link_avaliacao} c {vantagem} d {valor}", "x") == "a  b  c  d "


def test_telas_usam_os_dados_das_mensagens(http, con_temp):
    """Alertas e listas (filtro |preencher) também recebem o PIX, sem cada tela repetir a conta."""
    definir(con_temp, "pix", PIX)
    cid = cliente(con_temp, "Ana", dia(3))
    evento(con_temp, cid, "aula", dia(-2))
    evento(con_temp, cid, "aula", dia(-30))   # treina: o alerta é só o de renovação próxima
    assert alunos.estado_aluno(con_temp, cid)["modelo"] == "renovacao"
    assert "PIX%3A%20vfitcoach%40pix.com" in http.get("/").text


# ---------- textos padrão: migração só do texto que ainda é o antigo ----------
def test_migracao_troca_so_o_texto_antigo(tmp_path, monkeypatch):
    caminho = tmp_path / "c.db"
    monkeypatch.setattr(db, "DB_PATH", caminho)
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    definir(con, "renovacao", db.RENOVACAO_ANTIGA, "msg_whatsapp")             # banco de antes: ainda o padrão antigo
    definir(con, "indicacao", "Meu texto de indicação, {nome}!", "msg_whatsapp")  # editado por mim
    con.close()
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    m = db.parametros(con, "msg_whatsapp")
    con.close()
    assert m["renovacao"] == db.RENOVACAO_NOVA and "{valor}" in m["renovacao"] and "{pix}" in m["renovacao"]
    assert m["indicacao"] == "Meu texto de indicação, {nome}!"


def test_migracao_nao_sobrescreve_renovacao_editada(tmp_path, monkeypatch):
    caminho = tmp_path / "c.db"
    monkeypatch.setattr(db, "DB_PATH", caminho)
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    definir(con, "renovacao", "Renova logo, {nome}!", "msg_whatsapp")
    definir(con, "indicacao", db.INDICACAO_ANTIGA, "msg_whatsapp")
    con.close()
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    m = db.parametros(con, "msg_whatsapp")
    con.close()
    assert m["renovacao"] == "Renova logo, {nome}!"
    assert m["indicacao"] == db.INDICACAO_NOVA and "{vantagem}" in m["indicacao"]


def test_modelo_depoimento_e_dados_semeados(con_temp):
    assert "{link_avaliacao}" in db.parametros(con_temp, "msg_whatsapp")["depoimento"]
    assert db.parametros(con_temp, "msg_dados") == {"pix": "", "link_avaliacao": "", "vantagem": "uma avaliação física grátis"}


# ---------- a rota que registra e abre o WhatsApp ----------
def test_wa_registra_o_envio_e_vai_para_o_wa_me(http, con_temp):
    cid = cliente(con_temp, "Ana", dia(5))
    r = http.post(f"/clientes/{cid}/wa/indicacao", follow_redirects=False)
    host, texto = enviado(r)
    assert host == "https://wa.me" and r.headers["location"].startswith("https://wa.me/5511999990000?text=")
    assert texto.startswith("Oi, Ana!") and "{" not in texto and "uma avaliação física grátis" in texto
    [e] = con_temp.execute("SELECT * FROM cliente_eventos WHERE cliente_id=? AND tipo='mensagem'", (cid,)).fetchall()
    assert e["descricao"] == "WhatsApp: Indicação" and e["data"] == dia(0)
    assert "WhatsApp: Indicação" in http.get(f"/clientes/{cid}").text   # o histórico mostra, sem erro de tipo


def test_wa_ignora_texto_enviado_pelo_navegador(http, con_temp):
    cid = cliente(con_temp, "Ana", dia(5))
    r = http.post(f"/clientes/{cid}/wa/dupla", data={"texto": "EVIL", "url": "https://evil.example"}, follow_redirects=False)
    host, texto = enviado(r)
    assert host == "https://wa.me" and "EVIL" not in texto


def test_wa_modelo_desconhecido_nao_redireciona(http, con_temp):
    cid = cliente(con_temp, "Ana", dia(5))
    r = http.post(f"/clientes/{cid}/wa/nao_existe", follow_redirects=False)
    assert r.status_code == 404 and "location" not in r.headers
    assert not con_temp.execute("SELECT 1 FROM cliente_eventos WHERE tipo='mensagem'").fetchone()


def test_wa_sem_telefone_volta_para_a_ficha_com_erro(http, con_temp):
    with con_temp:
        cid = con_temp.execute("INSERT INTO clientes (nome, status, data_renovacao) VALUES ('Sem Tel', 'ativo', ?)", (dia(5),)).lastrowid
    r = http.post(f"/clientes/{cid}/wa/renovacao", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/clientes/{cid}?erro=")
    assert not con_temp.execute("SELECT 1 FROM cliente_eventos WHERE tipo='mensagem'").fetchone()


def test_wa_que_precisa_de_data_sem_data_volta_com_erro(http, con_temp):
    cid = cliente(con_temp, "Ana", None)
    r = http.post(f"/clientes/{cid}/wa/falta", follow_redirects=False)
    assert r.headers["location"].startswith(f"/clientes/{cid}?erro=")


def test_wa_cobrar_usa_o_texto_da_cobranca(http, con_temp):
    cid = cliente(con_temp, "Dora", dia(-20))
    host, texto = enviado(http.post(f"/clientes/{cid}/wa/cobranca", follow_redirects=False))
    assert "20 dias de atraso" in texto and "R$ 410,67" in texto
    assert con_temp.execute("SELECT descricao FROM cliente_eventos WHERE tipo='mensagem'").fetchone()[0] == "WhatsApp: Cobrar"
    sem_atraso = cliente(con_temp, "Ana", dia(5))
    assert http.post(f"/clientes/{sem_atraso}/wa/cobranca", follow_redirects=False).headers["location"].startswith(f"/clientes/{sem_atraso}?erro=")


# ---------- depoimento ----------
def test_depoimento_pedido_fica_marcado_por_90_dias(http, con_temp):
    cid = cliente(con_temp, "Ana", dia(5))
    m = menu(http.get(f"/clientes/{cid}").text)
    assert "pedido em" not in m and "Recebi o depoimento" not in m
    http.post(f"/clientes/{cid}/wa/depoimento", follow_redirects=False)
    m = menu(http.get(f"/clientes/{cid}").text)
    hoje = dia(0)
    assert f"pedido em {hoje[8:10]}/{hoje[5:7]}" in m and "Recebi o depoimento" in m
    assert f"/clientes/{cid}/wa/depoimento" in m   # continua clicável


def test_depoimento_pedido_ha_mais_de_90_dias_nao_marca(http, con_temp):
    cid = cliente(con_temp, "Ana", dia(5))
    evento(con_temp, cid, "mensagem", dia(-91), "WhatsApp: Pedir depoimento")
    m = menu(http.get(f"/clientes/{cid}").text)
    assert "pedido em" not in m and "Recebi o depoimento" not in m
    evento(con_temp, cid, "mensagem", dia(-89), "WhatsApp: Pedir depoimento")
    assert "pedido em" in menu(http.get(f"/clientes/{cid}").text)


def test_recebi_o_depoimento_registra_e_some_o_botao(http, con_temp):
    cid = cliente(con_temp, "Ana", dia(5))
    http.post(f"/clientes/{cid}/wa/depoimento", follow_redirects=False)
    r = http.post(f"/clientes/{cid}/depoimento", data={"descricao": ""}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/clientes/{cid}")
    [e] = con_temp.execute("SELECT * FROM cliente_eventos WHERE tipo='depoimento'").fetchall()
    assert e["cliente_id"] == cid and e["descricao"] == "Depoimento recebido"
    html = http.get(f"/clientes/{cid}").text
    assert "Recebi o depoimento" not in menu(html)
    assert "Depoimento recebido" in html   # o histórico mostra
    assert http.post("/clientes/9999/depoimento", follow_redirects=False).headers["location"].startswith("/clientes?erro=")


# ---------- aviso do PIX ----------
def alerta_pix(con):
    return [a for a in main.alertas(con) if "chave PIX" in a["texto"]]


def test_alerta_pede_a_chave_pix(con_temp):
    assert alerta_pix(con_temp) == []   # nenhum aluno ativo: nada a avisar
    cliente(con_temp, "Ana", dia(5))
    [a] = alerta_pix(con_temp)
    assert a["cor"] == "azul" and a["url"] == "/configuracoes#cfg-msg_dados"
    assert a["acoes"][0]["href"] == "/configuracoes#cfg-msg_dados"
    definir(con_temp, "pix", PIX)
    assert alerta_pix(con_temp) == []


def test_ancora_do_alerta_existe_em_configuracoes(http):
    assert 'id="cfg-msg_dados"' in http.get("/configuracoes").text


# ---------- Configurações ----------
def test_configuracoes_salva_os_dados_das_mensagens(http, con_temp):
    html = http.get("/configuracoes").text
    for rotulo in ("Chave PIX", "Link para avaliação", "Vantagem da indicação"):
        assert rotulo in html
    for v in ("{nome}", "{data}", "{valor}", "{pix}", "{link_avaliacao}", "{vantagem}"):
        assert v in html
    ids = {r["chave"]: r["id"] for r in con_temp.execute("SELECT id, chave FROM parametros WHERE grupo='msg_dados'")}
    r = http.post("/configuracoes", data={f"t_{ids['pix']}": f" {PIX} ", f"t_{ids['link_avaliacao']}": "https://g.page/r/abc",
                                          f"t_{ids['vantagem']}": "uma aula grátis"}, follow_redirects=False)
    assert r.status_code == 303
    assert main.dados_mensagem(con_temp) == {"pix": PIX, "link_avaliacao": "https://g.page/r/abc", "vantagem": "uma aula grátis"}


def test_configuracoes_nao_grava_texto_em_outro_grupo(http, con_temp):
    pid = con_temp.execute("SELECT id FROM parametros WHERE grupo='imposto'").fetchone()[0]
    http.post("/configuracoes", data={f"t_{pid}": "x"})
    assert con_temp.execute("SELECT valor_texto FROM parametros WHERE id=?", (pid,)).fetchone()[0] is None


def test_configuracoes_ainda_salva_os_modelos(http, con_temp):
    pid = con_temp.execute("SELECT id FROM parametros WHERE grupo='msg_whatsapp' AND chave='dupla'").fetchone()[0]
    http.post("/configuracoes", data={f"t_{pid}": "Oi, {nome}! Vem treinar com alguém?"})
    assert db.parametros(con_temp, "msg_whatsapp")["dupla"] == "Oi, {nome}! Vem treinar com alguém?"
