/**
 * Cartão de cobrança (SVG 1080 px), port de app/cartao.py: texto do estágio, QR Pix, valores, favorecido, copia-e-cola e logo.
 * O QR sai da biblioteca uqr: o desenho pode diferir do segno do Python, mas o conteúdo lido é o mesmo (teste decodifica).
 */
import { encode } from "uqr";
import { LOGO_SVG, MONTSERRAT_B64 } from "../gerado/estaticos.ts";
import { dataBr, moeda } from "../formato.ts";
import type { Valor } from "../banco/tipos.ts";
import { arred } from "../arred.ts";
import type { CobrancaAtual } from "./cobranca.ts";
import type { DadosMsg } from "./mensagens.ts";
import { flt } from "./texto.ts";
import { splitlines, wrap } from "./textwrap.ts";

const LARGURA = 1080, MARGEM = 72;
const FUNDO = "#0B1E3D", TEXTO = "#FFFFFF", APAGADO = "#9FB3CF", DESTAQUE = "#7FB2E5";
const ASSINATURA = "Victor | VFITCOACH";
const FONTE = `@font-face{font-family:M;font-weight:100 900;src:url(data:font/woff2;base64,${MONTSERRAT_B64}) format('woff2')}`;
const LOGO_G = /<g\b[\s\S]*?<\/g>/.exec(LOGO_SVG)?.[0] ?? "";

/** html.escape do Python (com aspas). */
function escapar(s: string): string {
  return s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#x27;");
}

function texto(x: number, y: number, conteudo: string, tam: number, cor = TEXTO, peso = 400, ancora = "start"): string {
  return `<text x="${x}" y="${y}" font-size="${tam}" font-weight="${peso}" fill="${cor}" text-anchor="${ancora}">${escapar(conteudo)}</text>`;
}

/** 0.02 -> '2%'; 0.025 -> '2,5%'. */
function pctCartao(v: unknown): string {
  return arred(flt(v) * 100, 2).toFixed(2).replace(/0+$/, "").replace(/\.$/, "").replace(".", ",") + "%";
}

export type LinhaCartao = [string, string, boolean];

/** As linhas do valor: depois do vencimento, as partes do total; antes, a mensalidade e o crédito (se houver) e o valor. */
export function linhasCobranca(ca: CobrancaAtual, par: Record<string, Valor> = {}): LinhaCartao[] {
  const cob = ca.cob, out: LinhaCartao[] = [];
  if (cob && ca.dias) {
    const meses = cob.meses || 1;
    out.push([meses === 1 ? "Mensalidade" : `Mensalidades (${meses})`, moeda(cob.bruto), false]);
    if (cob.credito) out.push(["Crédito descontado", "− " + moeda(cob.credito), false]);
    if (cob.multa) out.push([par.multa ? `Multa (${pctCartao(par.multa)})` : "Multa", moeda(cob.multa), false]);
    if (cob.juros) {
      const dias = cob.dias || ca.dias;
      out.push([`Juros (${dias} dia${dias > 1 ? "s" : ""} de atraso)`, moeda(cob.juros), false]);
    }
  } else if (ca.credito) {
    if (ca.mensalidade) out.push(["Mensalidade", moeda(ca.mensalidade), false]);
    out.push(["Crédito descontado", "− " + moeda(ca.credito), false]);
  }
  out.push([ca.rotulo_valor, moeda(ca.valor), true]);
  out.push(["Vencimento", dataBr(ca.vencimento), false]);
  return out;
}

/** [frase, observação] do prazo do Pix: o QR estático não expira, então o cartão diz até quando o valor vale. */
export function validade(ca: { valido_ate?: string | null; dias?: number }): [string, string] | null {
  const ate = ca.valido_ate;
  if (!ate) return null;
  if (ca.dias) return [`Vale só hoje, ${dataBr(ate).slice(0, 5)}, até 23:59`, "Amanhã os juros mudam: peça o Pix atualizado"];
  return [`Pague até 23:59 de ${dataBr(ate)}`, "Depois do vencimento entram multa e juros"];
}

/** O QR como um `d` de <path> (um quadrado 1x1 por módulo escuro) e o lado em módulos. */
export function qrCaminho(conteudo: string): [string, number] {
  const m = encode(conteudo, { ecc: "M", border: 0 }).data;
  const partes: string[] = [];
  m.forEach((linha, y) => linha.forEach((escuro, x) => escuro && partes.push(`M${x} ${y}h1v1h-1z`)));
  return [partes.join(""), m.length];
}

/** Cartão pronto: a cobrança do dia (cobrancaAtual) ou a diferença de multa e juros (com `linhas`). */
export interface DadosCartao { nome: string; texto: string; codigo: string; dados: DadosMsg; linhas?: LinhaCartao[];
  valido_ate?: string | null; dias?: number }

export function svg(ca: DadosCartao, par: Record<string, Valor> = {}): string {
  const partes: string[] = [];
  let y = MARGEM + 20;
  partes.push(texto(MARGEM, y, ca.nome.toUpperCase(), 26, DESTAQUE, 700));
  y += 70;
  const paragrafos = splitlines(ca.texto || "");
  for (const p of paragrafos.length ? paragrafos : [""]) {
    const linhas = wrap(p, 36);
    for (const linha of linhas.length ? linhas : [""]) {
      partes.push(texto(MARGEM, y, linha, 42, TEXTO, 500));
      y += 58;
    }
  }
  y += 30;
  if (ca.codigo) {
    const [caminho, lado] = qrCaminho(ca.codigo);
    const caixa = 520, borda = 32;
    const x0 = Math.floor((LARGURA - caixa) / 2);
    const escala = (caixa - 2 * borda) / lado;
    partes.push(`<rect x="${x0}" y="${y}" width="${caixa}" height="${caixa}" rx="28" fill="#FFFFFF"/>`);
    partes.push(`<path transform="translate(${x0 + borda} ${y + borda}) scale(${arred(escala, 4).toFixed(4)})" d="${caminho}" fill="#000000"/>`);
    y += caixa + 40;
    partes.push(texto(LARGURA / 2, y, "Aponte a câmera do app do banco", 26, APAGADO, 500, "middle"));
    y += 60;
  }
  const prazo = validade(ca);
  if (prazo) {
    partes.push(texto(LARGURA / 2, y, prazo[0], 34, DESTAQUE, 700, "middle"));
    y += 44;
    partes.push(texto(LARGURA / 2, y, prazo[1], 24, APAGADO, 500, "middle"));
    y += 64;
  }
  const d = ca.dados;
  const linhas: LinhaCartao[] = [...(ca.linhas ?? linhasCobranca(ca as CobrancaAtual, par))];
  for (const [r, v] of [["Favorecido", d.pix_nome], ["Banco", d.pix_banco], ["Chave Pix", d.pix]] as [string, string][]) if (v) linhas.push([r, v, false]);
  partes.push(`<line x1="${MARGEM}" y1="${y - 20}" x2="${LARGURA - MARGEM}" y2="${y - 20}" stroke="#2C5C8F" stroke-width="2"/>`);
  y += 30;
  for (const [rotulo, valor, destaque] of linhas) {
    partes.push(texto(MARGEM, y, rotulo, destaque ? 32 : 30, destaque ? TEXTO : APAGADO, destaque ? 700 : 500));
    const base = destaque ? 40 : 34;
    const n = Array.from(valor).length;
    const t = n <= 30 ? base : Math.max(22, Math.trunc((base * 30) / n));
    partes.push(texto(LARGURA - MARGEM, y, valor, t, TEXTO, 700, "end"));
    y += destaque ? 62 : 56;
  }
  if (ca.codigo) {
    y += 20;
    partes.push(texto(MARGEM, y, "Pix copia e cola", 26, APAGADO, 600));
    y += 40;
    for (const linha of wrap(ca.codigo, 62, false)) {
      partes.push(texto(MARGEM, y, linha, 22, TEXTO, 400));
      y += 32;
    }
  }
  y += 40;
  partes.push(`<line x1="${MARGEM}" y1="${y}" x2="${LARGURA - MARGEM}" y2="${y}" stroke="#2C5C8F" stroke-width="2"/>`);
  y += 40;
  const altLogo = 64;
  if (LOGO_G) partes.push(`<svg x="${MARGEM}" y="${y}" width="${Math.floor((altLogo * 570) / 140)}" height="${altLogo}" viewBox="191 399 570 140">${LOGO_G}</svg>`);
  partes.push(texto(LARGURA - MARGEM, y + 44, ASSINATURA, 30, TEXTO, 700, "end"));
  const altura = y + altLogo + MARGEM;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${LARGURA}" height="${altura}" viewBox="0 0 ${LARGURA} ${altura}">`
    + `<style>${FONTE}text{font-family:M,Montserrat,Arial,sans-serif}</style>`
    + `<rect width="${LARGURA}" height="${altura}" fill="${FUNDO}"/>` + partes.join("") + "</svg>";
}
