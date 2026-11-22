/** Locais (port de partes de app/locais.py usadas por toda tela). */
import type { Banco } from "../banco/banco.ts";
import { lista } from "./parametros.ts";
import { semAcento } from "./texto.ts";

/** Locais de onde copiar a grade: a CIA e os que têm custos. */
export async function referencias(b: Banco): Promise<string[]> {
  const feitos = (await b.query<{ local: string }>("SELECT local FROM locais_custos ORDER BY local")).map((r) => r.local);
  return ["CIA", ...feitos.filter((x) => x !== "CIA")];
}

/** Nome do local sem acento, maiúsculas nem espaços nas pontas: como a agenda e as contas automáticas comparam. */
export function chaveNome(nome: string | null | undefined): string {
  return semAcento(nome ?? "").trim().toLowerCase();
}

/** Para achar o mesmo local escrito de outro jeito: 'Smart Fit' e 'SmartFit' são o mesmo. */
export function semEspaco(nome: string | null | undefined): string {
  return chaveNome(nome).split(/\s+/).join("");
}

export function ehCia(nome: string | null | undefined): boolean {
  return chaveNome(nome) === "cia";
}

/** Todos os locais que existem: a lista de Configurações, os da Grade e os que têm custos. */
export async function nomes(b: Banco): Promise<string[]> {
  const [l, grade, custos] = await Promise.all([
    lista(b, "lista_locais"),
    b.query<{ local: string }>("SELECT DISTINCT local FROM grade_slots"),
    b.query<{ local: string }>("SELECT local FROM locais_custos"),
  ]);
  const todos = [...l, ...grade.map((r) => r.local), ...custos.map((r) => r.local)];
  return [...new Set(todos.filter((x) => x && x.trim()))];
}
