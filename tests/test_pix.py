"""Pix copia-e-cola, QR, cartão de cobrança e migração do texto da cobrança."""
from datetime import date

from app import cartao, db, pix

CA = {"nome": "Esquecimento", "texto": "Oi, Ana, tudo bem?", "rotulo_valor": "Valor", "valor": 410.67,
      "vencimento": date(2026, 11, 1),
      "dados": {"pix": "vfitcoach@pix.com", "pix_nome": "Victor Célli", "pix_banco": "Nubank"}}


def moeda(v):
    return f"R$ {v:.2f}".replace(".", ",")


def data_br(d):
    return d.strftime("%d/%m/%Y")


def test_crc16_valor_de_verificacao():
    assert pix.crc16("123456789") == "29B1"


def test_br_code_tem_chave_valor_e_crc():
    c = pix.br_code("vfitcoach@pix.com", "Victor Célli", "São Paulo", 410.67)
    assert c.startswith("000201")
    assert "0117vfitcoach@pix.com" in c
    assert "5406410.67" in c
    assert "5912VICTOR CELLI" in c and "6009SAO PAULO" in c
    assert c[-8:-4] == "6304" and c[-4:] == pix.crc16(c[:-4])


def test_br_code_sem_valor_nao_tem_campo_54():
    assert "54" + "06" not in pix.br_code("chave", "Nome", "Cidade")


def test_br_code_vazio_sem_nome_ou_cidade():
    assert pix.br_code("chave", "", "Cidade", 10) == ""
    assert pix.br_code("chave", "Nome", "", 10) == ""
    assert pix.br_code("", "Nome", "Cidade", 10) == ""


def test_qr_svg():
    assert pix.qr_svg("000201teste").startswith("<svg")


def test_cartao_com_qr():
    codigo = pix.br_code("vfitcoach@pix.com", "Victor Célli", "São Paulo", 410.67)
    s = cartao.svg({**CA, "codigo": codigo}, moeda, data_br)
    assert s.startswith("<svg")
    for trecho in ("ESQUECIMENTO", "Oi, Ana, tudo bem?", "R$ 410,67", "01/11/2026", "Nubank", "Victor Célli",
                   "Victor | VFITCOACH", "Aponte a câmera", 'rx="28"', codigo[:40]):
        assert trecho in s


def test_cartao_sem_codigo_sai_sem_qr():
    s = cartao.svg({**CA, "codigo": ""}, moeda, data_br)
    assert "vfitcoach@pix.com" in s
    assert 'rx="28"' not in s and "Aponte a câmera" not in s and "Pix copia e cola" not in s


def _cobranca(con):
    return con.execute("SELECT valor_texto FROM parametros WHERE grupo='msg_whatsapp' AND chave='cobranca'").fetchone()[0]


def _definir(con, texto):
    with con:
        con.execute("UPDATE parametros SET valor_texto=? WHERE grupo='msg_whatsapp' AND chave='cobranca'", (texto,))


def test_migracao_troca_o_texto_original(tmp_path):
    caminho = tmp_path / "crm.db"
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    _definir(con, db.COBRANCA_ANTIGA)
    con.close()
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    assert _cobranca(con) == db.COBRANCA_NOVA
    con.close()


def test_migracao_mantem_o_texto_editado(tmp_path):
    caminho = tmp_path / "crm.db"
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    _definir(con, "Meu texto, {nome}.")
    con.close()
    db.iniciar_banco(caminho)
    con = db.conectar(caminho)
    assert _cobranca(con) == "Meu texto, {nome}."
    con.close()
