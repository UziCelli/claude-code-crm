/** Formulários e parâmetros como o FastAPI lê: int de formulário vazio vale o padrão; texto que não é int dá 422 (app.onError). */
import type { Context } from "hono";
import { intPy } from "./util.ts";

export class Erro422 extends Error {}
export type Form = Record<string, string | string[]>;

/** O formulário inteiro; campo repetido vira lista. */
export async function lerForm(c: Context): Promise<Form> {
  const corpo = await c.req.parseBody({ all: true });
  return Object.fromEntries(Object.entries(corpo).map(([k, v]) =>
    [k, Array.isArray(v) ? v.map((x) => (typeof x === "string" ? x : "")) : typeof v === "string" ? v : ""]));
}

/** Um valor (repetido: vale o último, como o Starlette). */
export const um = (v: string | string[] | undefined): string | undefined => (Array.isArray(v) ? v[v.length - 1] : v);
export const varios = (v: string | string[] | undefined): string[] => (v === undefined ? [] : [v].flat());
/** Texto de formulário com padrão (Form("")). */
export const txt = (f: Form, k: string, padrao = ""): string => um(f[k]) ?? padrao;

function inteiro(s: string): number {
  try {
    return intPy(s);
  } catch {
    throw new Erro422();
  }
}

/** int de formulário: ausente ou vazio = padrão. */
export function intForm(f: Form, k: string, padrao = 0): number {
  const s = um(f[k]);
  return s === undefined || s === "" ? padrao : inteiro(s);
}

/** list[int] de formulário: cada item tem de ser int. */
export function intsForm(f: Form, k: string): number[] {
  return varios(f[k]).map(inteiro);
}

/** int da URL: ausente = padrão; vazio ou torto = 422. */
export function intQuery(c: Context, k: string, padrao = 0): number {
  const s = c.req.query(k);
  return s === undefined ? padrao : inteiro(s);
}

/** Verdade do Python para um valor de JSON (lista e objeto vazios são falsos). */
export function verdadePy(v: unknown): boolean {
  if (Array.isArray(v)) return v.length > 0;
  if (v && typeof v === "object") return Object.keys(v).length > 0;
  return !!v;
}
