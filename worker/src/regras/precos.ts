/** Preços (port de app/precos.py). Por enquanto só o que toda tela usa; o resto vem com Propostas/Cálculos. */
import type { Banco } from "../banco/banco.ts";
import { parametrosEmOrdem } from "./parametros.ts";

/** [{pessoas: preço da aula na CIA}, máximo de pessoas por horário], dos parâmetros taxa_cia. */
export async function taxasCia(b: Banco): Promise<[Map<number, number>, number]> {
  const cia = await parametrosEmOrdem(b, "taxa_cia");
  const precos = new Map<number, number>();
  let max = 3;
  for (const [k, v] of cia) {
    if (/^\d+$/.test(k)) precos.set(Number(k), v as number);
    if (k === "maximo_pessoas") max = Math.trunc(Number(v));
  }
  return [precos, max];
}
