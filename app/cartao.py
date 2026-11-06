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


def _pct(v) -> str:
    """0.02 -> '2%'; 0.025 -> '2,5%'."""
    return f"{float(v) * 100:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "%"


def linhas_cobranca(ca: dict, moeda, data_br, par: dict | None = None) -> list[tuple[str, str, bool]]:
    """As linhas do valor no cartão: (rótulo, valor, destaque). Depois do vencimento, as partes do total (mensalidade, crédito,
    multa e juros: financeiro.cobranca); antes, a mensalidade e o crédito (se houver) e o valor. par = parâmetros 'cobranca' (o % da multa)."""
    cob, par, out = ca.get("cob"), par or {}, []
    if cob and ca.get("dias"):
        meses = cob.get("meses") or 1
        out.append(("Mensalidade" if meses == 1 else f"Mensalidades ({meses})", moeda(cob["bruto"]), False))
        if cob.get("credito"):
            out.append(("Crédito descontado", "− " + moeda(cob["credito"]), False))
        if cob.get("multa"):
            out.append((f"Multa ({_pct(par['multa'])})" if par.get("multa") else "Multa", moeda(cob["multa"]), False))
        if cob.get("juros"):
            dias = cob.get("dias") or ca["dias"]
            out.append((f"Juros ({dias} dia{'s' if dias > 1 else ''} de atraso)", moeda(cob["juros"]), False))
    elif ca.get("credito"):
        if ca.get("mensalidade"):
            out.append(("Mensalidade", moeda(ca["mensalidade"]), False))
        out.append(("Crédito descontado", "− " + moeda(ca["credito"]), False))
    out.append((ca["rotulo_valor"], moeda(ca["valor"]), True))
    out.append(("Vencimento", data_br(ca["vencimento"]), False))
    return out


def validade(ca: dict, data_br) -> tuple[str, str] | None:
    """(frase, observação) do prazo do Pix: o QR estático não expira sozinho, então o cartão diz até quando o valor vale.
    Até o vencimento, vale até 23:59 dele; depois, só no dia (amanhã os juros mudam e sai um QR novo)."""
    ate = ca.get("valido_ate")
    if not ate:
        return None
    if ca.get("dias"):
        return f"Vale só hoje, {data_br(ate)[:5]}, até 23:59", "Amanhã os juros mudam: peça o Pix atualizado"
    return f"Pague até 23:59 de {data_br(ate)}", "Depois do vencimento entram multa e juros"


def svg(ca: dict, moeda, data_br, par: dict | None = None) -> str:
    """ca = main.cobranca_atual(...) ou um cartão pronto com ca['linhas'] (a diferença de multa e juros).
    moeda e data_br vêm do main (o mesmo formato da tela). par = parâmetros 'cobranca' (o % da multa na linha)."""
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
    # até quando o valor vale (o QR estático não expira: o cartão avisa)
    if prazo := validade(ca, data_br):
        partes.append(_texto(LARGURA // 2, y, prazo[0], 34, DESTAQUE, 700, "middle"))
        y += 44
        partes.append(_texto(LARGURA // 2, y, prazo[1], 24, APAGADO, 500, "middle"))
        y += 64
    # dados de pagamento: o valor (com multa e juros separados, depois do vencimento) e o favorecido
    d = ca["dados"]
    linhas = list(ca.get("linhas") or linhas_cobranca(ca, moeda, data_br, par))
    linhas += [(r, v, False) for r, v in (("Favorecido", d.get("pix_nome")), ("Banco", d.get("pix_banco")), ("Chave Pix", d.get("pix"))) if v]
    partes.append(f'<line x1="{MARGEM}" y1="{y - 20}" x2="{LARGURA - MARGEM}" y2="{y - 20}" stroke="#2C5C8F" stroke-width="2"/>')
    y += 30
    for rotulo, valor, destaque in linhas:
        partes.append(_texto(MARGEM, y, rotulo, 32 if destaque else 30, TEXTO if destaque else APAGADO, 700 if destaque else 500))
        base = 40 if destaque else 34
        tam = base if len(valor) <= 30 else max(22, int(base * 30 / len(valor)))
        partes.append(_texto(LARGURA - MARGEM, y, valor, tam, TEXTO, 700, "end"))
        y += 62 if destaque else 56
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
