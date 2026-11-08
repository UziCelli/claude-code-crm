"""Vantagem da indicação que cabe no local de quem indica: num local que cobra por aula (CIA), nada que gaste uma aula."""
from urllib.parse import parse_qs, urlparse

from app import db, main, vantagens
from tests.test_indicacoes import con_temp, http, pagar  # noqa: F401  (fixtures e ajudantes)

TODAS = ["uma avaliação física grátis", "uma camiseta", "uma garrafa"]   # as 3 primeiras da lista inicial
SEM_AULA = ["uma camiseta", "uma garrafa", "um treino extra para fazer em casa"]


def aluno(con, nome, local=None, indicado_por=None):
    with con:
        return con.execute("INSERT INTO clientes (nome, telefone, status, valor, local, indicado_por) VALUES (?, '11999990000', 'ativo', 400, ?, ?)",
                           (nome, local, indicado_por)).lastrowid


def custos(con, local, taxa_aula=0, taxa_pessoa_extra=0):
    with con:
        con.execute("INSERT INTO locais_custos (local, taxa_aula, taxa_pessoa_extra) VALUES (?,?,?)", (local, taxa_aula, taxa_pessoa_extra))


def texto_wa(http, cid):
    r = http.post(f"/clientes/{cid}/wa/indicacao", follow_redirects=False)
    assert r.status_code == 303
    return parse_qs(urlparse(r.headers["location"]).query)["text"][0]


# ---------- quem cobra por aula ----------
def test_cia_com_taxa_cobra_e_sem_taxa_nao(con_temp):
    assert vantagens.cobra_por_aula(con_temp, "CIA")
    with con_temp:
        con_temp.execute("UPDATE parametros SET valor=0 WHERE grupo='taxa_cia' AND chave='1'")
    assert not vantagens.cobra_por_aula(con_temp, "CIA")


def test_local_com_custos(con_temp):
    custos(con_temp, "Academia X", taxa_aula=30)
    custos(con_temp, "Academia Y", taxa_pessoa_extra=10)
    custos(con_temp, "Studio Z")
    assert vantagens.cobra_por_aula(con_temp, "Academia X")
    assert vantagens.cobra_por_aula(con_temp, "AcademiaX")   # o mesmo local escrito de outro jeito
    assert vantagens.cobra_por_aula(con_temp, "Academia Y")
    assert not vantagens.cobra_por_aula(con_temp, "Studio Z")


def test_local_da_lista_sem_custos_nao_cobra_e_vazio_ou_estranho_e_o_lado_seguro(con_temp):
    assert not vantagens.cobra_por_aula(con_temp, "Condomínio")
    assert vantagens.cobra_por_aula(con_temp, None)
    assert vantagens.cobra_por_aula(con_temp, "")
    assert vantagens.cobra_por_aula(con_temp, "Lugar que ninguém cadastrou")


# ---------- o leque e o texto ----------
def test_leque_por_local(con_temp):
    assert vantagens.do_local(con_temp, "CIA") == SEM_AULA
    assert vantagens.do_local(con_temp, "Condomínio") == TODAS   # até 3, na ordem
    assert vantagens.do_local(con_temp, None) == SEM_AULA


def test_texto():
    assert vantagens.texto([]) == ""
    assert vantagens.texto(["uma garrafa"]) == "uma garrafa"
    assert vantagens.texto(["a", "b"]) == "à sua escolha: a ou b"
    assert vantagens.texto(["a", "b", "c"]) == "à sua escolha: a, b ou c"


def test_rotulo_do_presente():
    assert vantagens.rotulo("uma avaliação física grátis") == "Avaliação física grátis"
    assert vantagens.rotulo("um treino extra para fazer em casa") == "Treino extra para fazer em casa"
    assert vantagens.rotulo("Camiseta") == "Camiseta"


# ---------- a mensagem ----------
def test_mensagem_de_aluno_da_cia_nao_oferece_aula(con_temp, http):
    t = texto_wa(http, aluno(con_temp, "Ana", "CIA"))
    assert "avaliação física" not in t and "à sua escolha: uma camiseta, uma garrafa ou um treino extra" in t and "{" not in t


def test_mensagem_de_aluno_do_condominio_oferece_avaliacao(con_temp, http):
    t = texto_wa(http, aluno(con_temp, "Bia", "Condomínio"))
    assert "à sua escolha: uma avaliação física grátis, uma camiseta ou uma garrafa" in t


def test_indicacao_indireta_so_olha_quem_indicou(con_temp, http):
    """O amigo vai treinar em outro local (sem taxa): a vantagem de quem indicou (CIA) continua sem aula."""
    ana = aluno(con_temp, "Ana", "CIA")
    aluno(con_temp, "Caio", "Condomínio", indicado_por=ana)
    assert "avaliação física" not in texto_wa(http, ana)


def test_lista_de_pedir_indicacao_usa_o_local_de_cada_um(con_temp, http):
    ana, bia = aluno(con_temp, "Ana", "CIA"), aluno(con_temp, "Bia", "Condomínio")
    html = http.get(f"/clientes?ids={ana},{bia}&motivo=indicacao").text
    links = [parse_qs(urlparse(h.replace("&amp;", "&")).query)["text"][0] for h in
             [p.split('"')[0] for p in html.split('href="https://wa.me/')[1:]]]
    ana_txt = next(t for t in links if "Ana" in t)
    bia_txt = next(t for t in links if "Bia" in t)
    assert "avaliação física" not in ana_txt and "avaliação física" in bia_txt


def test_sem_vantagem_nenhuma_a_mensagem_nao_mostra_a_chave(con_temp, http):
    with con_temp:
        con_temp.execute("DELETE FROM parametros WHERE grupo=?", (vantagens.GRUPO,))
    t = texto_wa(http, aluno(con_temp, "Ana", "CIA"))
    assert "{vantagem}" not in t


# ---------- presente ----------
def test_presente_sugere_o_que_cabe_no_local_de_quem_indicou(con_temp, http):
    ana = aluno(con_temp, "Ana", "CIA")
    bruno = aluno(con_temp, "Bruno", "Condomínio", indicado_por=ana)
    pagar(con_temp, bruno)
    [a] = [a for a in main.alertas(con_temp) if a["texto"].startswith("Dar o presente")]
    assert a["acoes"][0]["dados"]["sugestoes"] == "Camiseta|Garrafa|Treino extra para fazer em casa"
    assert 'data-sugestoes="Camiseta|Garrafa|Treino extra para fazer em casa"' in http.get(f"/clientes/{ana}").text


# ---------- Configurações ----------
def test_configuracoes_adiciona_marca_e_remove(con_temp, http):
    html = http.get("/configuracoes").text
    assert 'id="cfg-vantagens"' in html and "Gasta uma aula" in html
    r = http.post("/configuracoes/vantagem", data={"texto": "  um   squeeze ", "gasta_aula": ""}, follow_redirects=False)
    assert r.status_code == 303
    v = next(i for i in vantagens.lista(con_temp) if i["texto"] == "um squeeze")
    assert v["gasta_aula"] is False
    http.post(f"/configuracoes/vantagem/{v['id']}/marcar")
    assert next(i for i in vantagens.lista(con_temp) if i["id"] == v["id"])["gasta_aula"] is True
    r = http.post("/configuracoes/vantagem", data={"texto": "um squeeze"}, follow_redirects=False)
    assert "erro=" in r.headers["location"]   # repetida


def test_vantagem_inicial_removida_nao_volta(con_temp, http, tmp_path):
    v = vantagens.lista(con_temp)[1]
    http.post(f"/configuracoes/vantagem/{v['id']}/remover")
    db.iniciar_banco(db.DB_PATH)
    assert v["texto"] not in [i["texto"] for i in vantagens.lista(con_temp)]


def test_marcar_nao_mexe_em_outro_grupo(con_temp, http):
    pid, antes = con_temp.execute("SELECT id, valor FROM parametros WHERE grupo='taxa_cia' AND chave='1'").fetchone()
    http.post(f"/configuracoes/vantagem/{pid}/marcar")
    http.post(f"/configuracoes/vantagem/{pid}/remover")
    assert con_temp.execute("SELECT valor FROM parametros WHERE id=?", (pid,)).fetchone()[0] == antes


# ---------- migração ----------
def test_texto_antigo_editado_vira_vantagem_que_gasta_aula(tmp_path, monkeypatch):
    caminho = tmp_path / "crm.db"
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    with con:   # banco de antes: sem a lista e com a vantagem editada à mão
        con.execute("DELETE FROM parametros WHERE grupo=?", (vantagens.GRUPO,))
        con.execute("DELETE FROM parametros WHERE grupo='migracao' AND chave='vantagem_lista'")
        con.execute("UPDATE parametros SET valor_texto='uma aula de mobilidade' WHERE grupo='msg_dados' AND chave='vantagem'")
    db.iniciar_banco(caminho)
    db.iniciar_banco(caminho)   # de novo: não duplica
    itens = vantagens.lista(con)
    assert itens[0] == {"id": itens[0]["id"], "texto": "uma aula de mobilidade", "gasta_aula": True}
    assert [i["texto"] for i in itens].count("uma aula de mobilidade") == 1
    con.close()
