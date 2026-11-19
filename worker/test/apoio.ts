import { env } from "cloudflare:test";
import semente from "./dados/semente.sql?raw";
import { Banco } from "../src/banco/banco.ts";
import { DriverD1 } from "../src/banco/d1.ts";

/** Os dados que o Python grava num banco novo (parâmetros, listas...), uma vez por arquivo de teste. */
let semeado = false;
export async function semear(): Promise<void> {
  if (semeado) return;
  const cmds = semente.split("\n").filter((l) => l.startsWith("INSERT"));
  await env.DB.batch(cmds.map((sql) => env.DB.prepare(sql)));
  semeado = true;
}

export function banco(teto?: number): Banco {
  return new Banco(new DriverD1(env.DB), teto);
}
