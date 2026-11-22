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

/** Carrega um cenário SQL gerado pelo Python (test/dados/*.sql) no D1 do arquivo de teste. */
export async function carregarCenario(sql: string): Promise<void> {
  const cmds = sql.split("\n").filter((l) => /^(INSERT|UPDATE|DELETE)/.test(l));
  await env.DB.batch(cmds.map((s) => env.DB.prepare(s)));
}

/** Estruturas do TS como o JSON do Python: Map vira objeto de chaves texto. */
export function jsonavel(x: unknown): unknown {
  if (x instanceof Map) return Object.fromEntries([...x].map(([k, v]) => [String(k), jsonavel(v)]));
  if (x instanceof Set) return [...x].sort().map(jsonavel);
  if (Array.isArray(x)) return x.map(jsonavel);
  if (x && typeof x === "object") return Object.fromEntries(Object.entries(x).map(([k, v]) => [k, jsonavel(v)]));
  return x;
}

// ---------- pedidos de quem entrou pelo Cloudflare Access (chaves de teste) ----------
import { createLocalJWKSet, exportJWK, generateKeyPair, SignJWT } from "jose";
import { usarChavesDeTeste } from "../src/acesso.ts";
import { app } from "../src/index.ts";

export const HOST = "crm.vfitcoachapp.com";
let chavePrivada: CryptoKey | null = null;

/** Token válido do Access (equipe e AUD de teste do vitest.config.ts). */
export async function tokenValido(): Promise<string> {
  if (!chavePrivada) {
    const par = await generateKeyPair("RS256", { extractable: true });
    chavePrivada = par.privateKey;
    usarChavesDeTeste(createLocalJWKSet({ keys: [{ ...(await exportJWK(par.publicKey)), kid: "k1", alg: "RS256" }] }));
  }
  return new SignJWT({ email: "dono@exemplo.com" }).setProtectedHeader({ alg: "RS256", kid: "k1" }).setAudience(["aud-do-crm"])
    .setIssuer("https://vfit.cloudflareaccess.com").setIssuedAt().setExpirationTime(Math.floor(Date.now() / 1000) + 600).sign(chavePrivada);
}

/** GET de uma tela, logado. */
export async function abrir(caminho: string): Promise<Response> {
  return app.fetch(new Request(`https://${HOST}${caminho}`, { headers: { host: HOST, "cf-access-jwt-assertion": await tokenValido() } }), env);
}

/** POST de formulário da própria tela, logado (sem seguir o redirecionamento). */
export async function enviar(caminho: string, dados: Record<string, string | string[]> = {}): Promise<Response> {
  // campo repetido (dia=1&dia=2) vem como lista, como o httpx do Python manda
  const corpo = new URLSearchParams(Object.entries(dados).flatMap(([k, v]) => [v].flat().map((x) => [k, x])));
  return app.fetch(new Request(`https://${HOST}${caminho}`, {
    method: "POST", body: corpo.toString(), redirect: "manual",
    headers: { host: HOST, origin: `https://${HOST}`, "content-type": "application/x-www-form-urlencoded", "cf-access-jwt-assertion": await tokenValido() },
  }), env);
}

/** O aviso (?msg= ou ?erro=) de um redirecionamento, já decodificado. */
export function aviso(r: Response): { destino: string; msg: string | null; erro: string | null } {
  const u = new URL(r.headers.get("location") ?? "", `https://${HOST}`);
  return { destino: u.pathname + u.hash, msg: u.searchParams.get("msg"), erro: u.searchParams.get("erro") };
}

/** Roteiro gerado pelo Python (paridade/gerar.py: telas_e_roteiro): telas iguais, mesmas respostas e as tabelas iguais no fim. */
export interface Roteiro { telas: Record<string, string>; respostas: [string, string, Record<string, string | string[]>, number, string | null][]; tabelas: Record<string, Record<string, unknown>[]> }

export async function pedido(metodo: string, url: string, dados: Record<string, string | string[]> = {}): Promise<Response> {
  return metodo === "GET" ? abrir(url) : enviar(url, dados);
}

/** Como normalizar_tabela do gerar.py: carimbo de agora (relógio do servidor) vira '<agora>'. */
export function normalizarTabela(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  const limite = new Date(Date.now() - 2 * 86_400_000).toISOString().slice(0, 10);
  return rows.map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) =>
    [k, typeof v === "string" && v.length === 19 && v[10] === " " && v.slice(0, 10) >= limite ? "<agora>" : v])));
}
