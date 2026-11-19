/**
 * Vantagem da indicação (port de app/vantagens.py): o leque de presentes que cabe no local de quem indicou.
 * Num local que cobra por aula, a vantagem que gasta uma aula ali sai do leque. Local vazio ou desconhecido: lado seguro.
 */
import type { Banco } from "../banco/banco.ts";
import { ehCia, nomes, semEspaco } from "./locais.ts";
import { taxasCia } from "./precos.ts";
import { espacosSimples } from "./texto.ts";

const GRUPO = "vantagem_indicacao";
export const MAX_LEQUE = 3;

export async function cobraPorAula(b: Banco, local: string | null | undefined): Promise<boolean> {
  const nome = (local ?? "").trim();
  if (!nome) return true;
  if (ehCia(nome)) return Number((await taxasCia(b))[0].get(1) ?? 0) > 0;
  const chave = semEspaco(nome);
  for (const r of await b.query<{ local: string; taxa_aula: number | null; taxa_pessoa_extra: number | null }>(
    "SELECT local, taxa_aula, taxa_pessoa_extra FROM locais_custos")) {
    if (semEspaco(r.local) === chave) return Number(r.taxa_aula ?? 0) > 0 || Number(r.taxa_pessoa_extra ?? 0) > 0;
  }
  return !(await nomes(b)).includes(nome);
}

export interface Vantagem { id: number; texto: string; gasta_aula: boolean }

export async function lista(b: Banco): Promise<Vantagem[]> {
  const rows = await b.query<{ id: number; chave: string; valor: number | null }>(
    "SELECT id, chave, valor FROM parametros WHERE grupo=? ORDER BY ordem, id", [GRUPO]);
  return rows.map((r) => ({ id: r.id, texto: r.chave, gasta_aula: Boolean(r.valor) }));
}

export async function doLocal(b: Banco, local: string | null | undefined, itens?: Vantagem[]): Promise<string[]> {
  const [todos, cobra] = await Promise.all([itens ?? lista(b), cobraPorAula(b, local)]);
  return todos.filter((i) => !(cobra && i.gasta_aula)).map((i) => i.texto).slice(0, MAX_LEQUE);
}

/** O que entra no {vantagem}: 'X'; 'à sua escolha: X ou Y'; 'à sua escolha: X, Y ou Z'; '' sem nenhuma. */
export function texto(opcoes: string[]): string {
  if (opcoes.length <= 1) return opcoes[0] ?? "";
  return "à sua escolha: " + opcoes.slice(0, -1).join(", ") + " ou " + opcoes[opcoes.length - 1];
}

export async function doAluno(b: Banco, local: string | null | undefined): Promise<string> {
  return texto(await doLocal(b, local));
}

/** 'uma camiseta' -> 'Camiseta': como o presente fica anotado no histórico. */
export function rotulo(t: string | null | undefined): string {
  let s = espacosSimples(t ?? "");
  for (const artigo of ["uma ", "um ", "a ", "o "]) {
    if (s.toLowerCase().startsWith(artigo)) {
      s = s.slice(artigo.length);
      break;
    }
  }
  return s.slice(0, 1).toUpperCase() + s.slice(1);
}

export async function sugestoesPresente(b: Banco, local: string | null | undefined): Promise<string> {
  return (await doLocal(b, local)).map(rotulo).join("|");
}
