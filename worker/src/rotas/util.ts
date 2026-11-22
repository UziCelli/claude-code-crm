/** Ajudas das rotas (port de main.py: voltar, _num_br, _caminho_seguro). */
import type { Context } from "hono";

/** urllib.parse.quote(s) do Python (safe="/"): letras, números, _.-~ e / ficam como estão. */
export function quoteUrl(s: string, seguro = "/"): string {
  return Array.from(new TextEncoder().encode(s), (b) => {
    const ch = String.fromCharCode(b);
    return /[A-Za-z0-9_.~-]/.test(ch) || (b < 128 && seguro.includes(ch)) ? ch : "%" + b.toString(16).toUpperCase().padStart(2, "0");
  }).join("");
}

/** Redireciona (303) com o aviso em ?msg= ou ?erro=; a âncora (#hoje) fica no fim. */
export function voltar(c: Context, url: string, msg?: string | null, erro?: string | null): Response {
  const i = url.indexOf("#");
  let base = i >= 0 ? url.slice(0, i) : url;
  const ancora = i >= 0 ? url.slice(i + 1) : "";
  if (msg) base += (base.includes("?") ? "&" : "?") + "msg=" + quoteUrl(msg);
  if (erro) base += (base.includes("?") ? "&" : "?") + "erro=" + quoteUrl(erro);
  return c.redirect(base + (ancora ? "#" + ancora : ""), 303);
}

/** Erro de valor com a mesma frase do Python (vai para a tela em ?erro=). */
export class ErroValor extends Error {}

/** repr() de um texto do Python, para as mensagens de erro iguais. */
function reprTexto(s: string): string {
  const aspas = s.includes("'") && !s.includes('"') ? '"' : "'";
  return aspas + s.replaceAll("\\", "\\\\").replaceAll(aspas, "\\" + aspas) + aspas;
}

/** float() do Python para os textos das telas (aceita "1e3", " 12 ", "1_000"; recusa "0x10"). */
export function floatPy(texto: string): number {
  const s = texto.trim();
  if (/^[+-]?(?:\d(?:_?\d)*(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?$/.test(s)) return Number(s.replaceAll("_", ""));
  if (/^[+-]?(?:inf|infinity)$/i.test(s)) return s.startsWith("-") ? -Infinity : Infinity;
  if (/^[+-]?nan$/i.test(s)) return NaN;
  throw new ErroValor(`could not convert string to float: ${reprTexto(texto)}`);
}

/** Número digitado na tela: "1.234,56", "R$ 90", "1.500" (mil e quinhentos), "70,125". Vazio = 0. */
export function numBr(v: unknown): number {
  let s = String(v || "0").trim().replaceAll("R$", "").replaceAll(" ", "");
  if (s.includes(",")) s = s.replaceAll(".", "").replaceAll(",", ".");
  else if (/^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replaceAll(".", "");
  const n = s ? floatPy(s) : 0;
  if (!Number.isFinite(n)) throw new ErroValor(`could not convert string to float: ${reprTexto(s)}`);
  return n;
}

/** int() do Python para um texto de id. */
export function intPy(texto: string): number {
  const s = texto.trim();
  if (/^[+-]?\d(?:_?\d)*$/.test(s)) return Number(s.replaceAll("_", ""));
  throw new ErroValor(`invalid literal for int() with base 10: ${reprTexto(texto)}`);
}

/** Destino de volta aceito: caminho do próprio CRM ("/clientes/3"); esquema, "//host" e barra invertida viram "". */
export function caminhoSeguro(p: string | null | undefined): string {
  const s = (p ?? "").trim();
  // eslint-disable-next-line no-control-regex
  return s.startsWith("/") && !s.startsWith("//") && !s.includes("\\") && !/[\x00-\x1f\x7f-\x9f]/.test(s) ? s : "";
}
