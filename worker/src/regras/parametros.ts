/** Tabela parametros (port de app/db.py: parametros e lista). */
import type { Banco } from "../banco/banco.ts";
import type { Valor } from "../banco/tipos.ts";

/** As listas de Configurações que toda tela recebe (db.LISTAS_INICIAIS, na mesma ordem). */
export const LISTAS = ["lista_canais", "lista_locais", "lista_tipos_servico", "lista_formas_pagamento", "lista_formas_venda",
  "lista_categorias_pj", "lista_categorias_pf", "lista_formas_lancamento", "lista_contas"] as const;
export type Listas = Record<(typeof LISTAS)[number], string[]>;

const SQL = "SELECT chave, valor, valor_texto FROM parametros WHERE grupo=? ORDER BY ordem, chave";

/** Linhas do grupo na ordem cadastrada: [chave, valor (ou valor_texto quando valor é NULL)]. */
export async function parametrosEmOrdem(b: Banco, grupo: string): Promise<[string, Valor][]> {
  const rows = await b.query<{ chave: string; valor: Valor; valor_texto: Valor }>(SQL, [grupo]);
  return rows.map((r) => [r.chave, r.valor !== null ? r.valor : r.valor_texto]);
}

/** {chave: valor} como db.parametros. Atenção: objeto JS põe chaves numéricas ("1", "2") primeiro; para a ordem, use parametrosEmOrdem. */
export async function parametros(b: Banco, grupo: string): Promise<Record<string, Valor>> {
  return Object.fromEntries(await parametrosEmOrdem(b, grupo));
}

export async function lista(b: Banco, nome: string): Promise<string[]> {
  return (await parametrosEmOrdem(b, nome)).map(([, v]) => v as string);
}

export async function todasAsListas(b: Banco): Promise<Listas> {
  const valores = await Promise.all(LISTAS.map((n) => lista(b, n)));
  return Object.fromEntries(LISTAS.map((n, i) => [n, valores[i]])) as Listas;
}
