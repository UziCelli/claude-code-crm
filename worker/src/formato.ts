/** Formatos da tela (port de main.py: moeda, data_br, pct, num, wa, preencher). */
import { arred } from "./arred.ts";
import { dataValida } from "./regras/datas.ts";

function milhar(inteiro: string): string {
  return inteiro.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

/** "R$ 1.234,56"; negativo "−R$ 1.234,56" (sinal de menos tipográfico); null "—". */
export function moeda(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const r = arred(Number(v), 2) + 0; // "-0,00" vira "0,00"
  const [i, d] = Math.abs(r).toFixed(2).split(".");
  const s = `${milhar(i)},${d}`;
  return r < 0 ? `−R$ ${s}` : `R$ ${s}`;
}

/** "AAAA-MM-DD..." -> "DD/MM/AAAA"; vazio "—"; texto que não é data volta como veio. */
export function dataBr(v: string | null | undefined): string {
  if (!v) return "—";
  const s = String(v);
  const d = s.slice(0, 10);
  return dataValida(d) ? `${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)}` : s;
}

export function pct(v: number | null | undefined, casas = 0): string {
  return v === null || v === undefined ? "—" : `${fixo(Number(v) * 100, casas)}%`.replace(".", ",");
}

export function num(v: number | null | undefined, casas = 1): string {
  return v === null || v === undefined ? "—" : fixo(Number(v), casas).replace(".", ",");
}

/** f"{x:.Nf}" do Python: arredonda o valor exato, empate exato para o par. */
function fixo(x: number, casas: number): string {
  const r = arred(x, casas);
  return r.toFixed(casas);
}

/** Link do WhatsApp; sem telefone o WhatsApp pede para escolher o contato. */
export function wa(tel: string | number | null | undefined, texto = ""): string {
  let n = String(tel ?? "").replace(/\D/g, "");
  if (n.length === 10 || n.length === 11) n = "55" + n;
  return `https://wa.me/${n}?text=${quotePy(texto ?? "")}`;
}

/** urllib.parse.quote(s, safe=""): só letras, números e _.-~ ficam como estão. */
export function quotePy(s: string): string {
  return Array.from(new TextEncoder().encode(s), (b) =>
    /[A-Za-z0-9_.~-]/.test(String.fromCharCode(b)) ? String.fromCharCode(b) : "%" + b.toString(16).toUpperCase().padStart(2, "0"),
  ).join("");
}

const VARIAVEIS_DADOS = /\{(?:valor|pix|link_avaliacao|vantagem)\}/g;

/** Troca {nome}, {data} e as variáveis extras; {valor}, {pix}, {link_avaliacao} e {vantagem} sem valor ficam vazias. */
export function preencher(texto: string | null | undefined, nome = "", data = "", extra: Record<string, unknown> = {}): string {
  let t = (texto ?? "").replaceAll("{nome}", nome ?? "").replaceAll("{data}", data ?? "");
  for (const [k, v] of Object.entries(extra)) t = t.replaceAll(`{${k}}`, strPy(v));
  return t.replace(VARIAVEIS_DADOS, "");
}

/** str() do Python para os valores que entram nas mensagens. */
export function strPy(v: unknown): string {
  if (v === null || v === undefined) return "None";
  if (typeof v === "boolean") return v ? "True" : "False";
  if (typeof v === "number" && Number.isInteger(v) && !Object.is(v, -0)) return String(v);
  return String(v);
}
