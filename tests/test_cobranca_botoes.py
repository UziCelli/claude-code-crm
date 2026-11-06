"""O botão "Cobrar" do WhatsApp é o mesmo em toda tela: Alertas/Painel, lista de Clientes, lista "Cobrar vencidos", ficha (Situação)
e Financeiro › Mensalidades. Sempre o cartão-imagem com o QR Pix e o total da cobrança (crédito descontado, multa e juros incluídos);
nunca o link antigo com o texto e o saldo sem multa."""
import html
import re
from urllib.parse import unquote

from app import alunos
from tests.test_alertas import cliente, con_temp, dia, do_aluno, pix_completo  # noqa: F401  (con_temp: fixture de banco temporário)
from tests.test_alertas_acao import http  # noqa: F401
from tests.test_cobranca_credito import credito


def links_wa(pagina) -> list[str]:
    """Os textos dos links wa.me da página, já decodificados."""
    return [unquote(html.unescape(u)) for u in re.findall(r'href="(https://wa\.me/[^"]+)"', pagina)]


def botao_cartao(cid) -> str:
    """O começo do formulário que gera o cartão (o mesmo em toda tela)."""
    return (f'<form method="post" action="/clientes/{cid}/wa/cobranca" target="_blank" class="inline" '
            f'data-cartao="/clientes/{cid}/cobranca/cartao.svg" data-codigo="')


def alexei(con):
    """O caso do print: mensalidade R$ 2.042,50, crédito R$ 612,75, 1 dia de atraso -> Cobrar R$ 1.458,83."""
    pix_completo(con)
    cid = cliente(con, "Alexei", dia(-1), valor=2042.50)
    credito(con, cid, 612.75)
    return cid


def test_alexei_mesmo_botao_com_cartao_em_toda_tela(con_temp, http):
    cid = alexei(con_temp)
    rotulo = "Cobrar R$ 1.458,83 · 1 dia"
    # cada tela recortada no seu próprio conteúdo (os alertas do topo também têm o botão, mas não contam aqui)
    telas = {"/clientes": '<div class="grid c3 mt">', f"/clientes?ids={cid}&motivo=cobrar": '<div class="grid c3 mt">',
             f"/clientes/{cid}": 'id="situacao"', "/": "card-hoje", "/financeiro/mensalidades": "<tbody>"}
    for url, marca in telas.items():
        pg = http.get(url).text
        trecho = pg.split(marca, 1)[1]
        assert botao_cartao(cid) in trecho, url
        assert f'<button type="submit" class="claro pequeno">{rotulo}</button></form>' in trecho, url
        # nenhum link antigo de cobrança, em parte nenhuma da página (nem o saldo sem multa)
        assert not [t for t in links_wa(pg) if "mensalidade" in t.lower() or "1.429,75" in t], url


def test_alexei_whatsapp_leva_o_pix_com_multa_e_juros(con_temp, http):
    cid = alexei(con_temp)
    r = http.post(f"/clientes/{cid}/wa/cobranca", follow_redirects=False)
    destino = unquote(r.headers["location"])
    assert destino.startswith("https://wa.me/5511999990000?text=000201")   # o código Pix, o texto vai no cartão
    assert "54071458.83" in destino and "1429.75" not in destino            # o total: saldo 1.429,75 + multa 28,60 + juros 0,48
    assert "R$ 1.458,83" in http.get(f"/clientes/{cid}/cobranca/cartao.svg").text


def test_lembrete_tem_cartao_e_renovacao_longe_segue_o_texto(con_temp, http):
    pix_completo(con_temp)
    perto = cliente(con_temp, "Ana", dia(2), inicio=dia(-3))   # aluno novo: não cai em "pulou o mês"
    longe = cliente(con_temp, "Caio", dia(6), inicio=dia(-3))
    e = alunos.estado_aluno(con_temp, perto)
    assert e["botao"] == "Lembrete: vence em 2 dias" and e["cartao"]["cid"] == perto
    e = alunos.estado_aluno(con_temp, longe)
    assert (e["modelo"], e["botao"], e["cartao"]) == ("renovacao", None, None)   # 6 dias: o WhatsApp de renovação de sempre
    pg = http.get("/clientes").text.split('<div class="grid c3 mt">', 1)[1]
    assert botao_cartao(perto) in pg
    assert [t for t in links_wa(pg) if "Caio" in t]   # Caio continua com o link de renovação


def test_sem_telefone_pede_o_telefone_e_nao_manda_texto_antigo(con_temp, http):
    pix_completo(con_temp)
    with con_temp:
        cid = con_temp.execute("""INSERT INTO clientes (nome, telefone, status, tipo_servico, valor, data_renovacao)
                                  VALUES ('Sem Fone', '', 'ativo', 'Pacote de Aulas', 400, ?)""", (dia(-5),)).lastrowid
    e = alunos.estado_aluno(con_temp, cid)
    assert e["situacao"] == "cobrar" and e["cartao"] is None and e["modelo"] is None
    assert {"rotulo": "Cadastre o telefone", "href": f"/clientes/{cid}#cadastro"} in e["acoes"]
    assert not [x for x in e["acoes"] if x.get("wa")]
    [al] = do_aluno(con_temp, "Sem Fone")
    assert not [x for x in al["acoes"] if x.get("wa")] and not al["cartao"]   # o alerta não põe de volta o WhatsApp antigo
    pg = http.get("/clientes").text
    assert f'href="/clientes/{cid}#cadastro">Cadastre o telefone</a>' in pg
    assert not [t for t in links_wa(pg) if "Sem Fone" in t]
