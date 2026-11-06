"""Cartão de cobrança (SVG 1080 px): texto do estágio, QR Pix, dados de pagamento, código copia-e-cola e a logo."""
import base64
import functools
import re
import textwrap
from html import escape
from pathlib import Path

from . import pix

ROOT = Path(__file__).resolve().parent
LARGURA, MARGEM = 1080, 72
FUNDO, TEXTO, APAGADO, DESTAQUE = "#0B1E3D", "#FFFFFF", "#9FB3CF", "#7FB2E5"
ASSINATURA = "Victor | VFITCOACH"


@functools.cache
def _fonte() -> str:
    try:
        dados = (ROOT / "static" / "fonts" / "montserrat.woff2").read_bytes()
    except OSError:
        return ""
    return ("@font-face{font-family:M;font-weight:100 900;src:url(data:font/woff2;base64,"
            + base64.b64encode(dados).decode() + ") format('woff2')}")


@functools.cache
def _logo() -> str:
    """O <g> da logo (branca) de _logo.html, para entrar num <svg> com o viewBox dela."""
    try:
        m = re.search(r"<g\b.*?</g>", (ROOT / "templates" / "_logo.html").read_text(encoding="utf-8"), re.S)
    except OSError:
        return ""
    return m.group(0) if m else ""


def _texto(x, y, conteudo, tam, cor=TEXTO, peso=400, ancora="start") -> str:
    return (f'<text x="{x}" y="{y}" font-size="{tam}" font-weight="{peso}" fill="{cor}" text-anchor="{ancora}">'
            f"{escape(conteudo)}</text>")


def svg(ca: dict, moeda, data_br) -> str:
    """ca = main.cobranca_atual(...). moeda e data_br vêm do main (o mesmo formato da tela)."""
    partes, y = [], 0
    # o texto do estágio
    y = MARGEM + 20
    partes.append(_texto(MARGEM, y, ca["nome"].upper(), 26, DESTAQUE, 700))
    y += 70
    for paragrafo in (ca["texto"] or "").splitlines() or [""]:
        for linha in textwrap.wrap(paragrafo, 36) or [""]:
            partes.append(_texto(MARGEM, y, linha, 42, TEXTO, 500))
            y += 58
    y += 30
    # o QR (só com nome e cidade do favorecido; sem eles o Pix vai pela chave)
    if ca["codigo"]:
        caminho, lado = pix.qr_caminho(ca["codigo"])
        caixa, borda = 520, 32
        x0 = (LARGURA - caixa) // 2
        escala = (caixa - 2 * borda) / lado
        partes.append(f'<rect x="{x0}" y="{y}" width="{caixa}" height="{caixa}" rx="28" fill="#FFFFFF"/>')
        partes.append(f'<path transform="translate({x0 + borda} {y + borda}) scale({escala:.4f})" d="{caminho}" fill="#000000"/>')
        y += caixa + 40
        partes.append(_texto(LARGURA // 2, y, "Aponte a câmera do app do banco", 26, APAGADO, 500, "middle"))
        y += 60
    # dados de pagamento
    d = ca["dados"]
    # crédito do aluno (aula paga e não usada): o valor abaixo já vem sem ele; a linha mostra para o aluno o desconto
    linhas = [("Crédito descontado", "− " + moeda(ca["credito"]))] if ca.get("credito") else []
    linhas += [(ca["rotulo_valor"], moeda(ca["valor"])), ("Vencimento", data_br(ca["vencimento"]))]
    linhas += [(r, v) for r, v in (("Favorecido", d.get("pix_nome")), ("Banco", d.get("pix_banco")), ("Chave Pix", d.get("pix"))) if v]
    partes.append(f'<line x1="{MARGEM}" y1="{y - 20}" x2="{LARGURA - MARGEM}" y2="{y - 20}" stroke="#2C5C8F" stroke-width="2"/>')
    y += 30
    for rotulo, valor in linhas:
        partes.append(_texto(MARGEM, y, rotulo, 30, APAGADO, 500))
        tam = 34 if len(valor) <= 30 else max(22, int(34 * 30 / len(valor)))
        partes.append(_texto(LARGURA - MARGEM, y, valor, tam, TEXTO, 700, "end"))
        y += 56
    # o código copia-e-cola
    if ca["codigo"]:
        y += 20
        partes.append(_texto(MARGEM, y, "Pix copia e cola", 26, APAGADO, 600))
        y += 40
        for linha in textwrap.wrap(ca["codigo"], 62, break_on_hyphens=False):
            partes.append(_texto(MARGEM, y, linha, 22, TEXTO, 400))
            y += 32
    # rodapé: logo + assinatura
    y += 40
    partes.append(f'<line x1="{MARGEM}" y1="{y}" x2="{LARGURA - MARGEM}" y2="{y}" stroke="#2C5C8F" stroke-width="2"/>')
    y += 40
    alt_logo = 64
    if _logo():
        partes.append(f'<svg x="{MARGEM}" y="{y}" width="{alt_logo * 570 // 140}" height="{alt_logo}" viewBox="191 399 570 140">{_logo()}</svg>')
    partes.append(_texto(LARGURA - MARGEM, y + 44, ASSINATURA, 30, TEXTO, 700, "end"))
    altura = y + alt_logo + MARGEM
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{LARGURA}" height="{altura}" viewBox="0 0 {LARGURA} {altura}">'
            f"<style>{_fonte()}text{{font-family:M,Montserrat,Arial,sans-serif}}</style>"
            f'<rect width="{LARGURA}" height="{altura}" fill="{FUNDO}"/>' + "".join(partes) + "</svg>")
