/**
 * Orçamento de CPU (decisão do Victor: ficar no Cloudflare e otimizar). Mede no V8 (o motor do Worker) a CPU de um pedido
 * inteiro (portaria, banco, cálculo e HTML) de cada tela migrada, no cenário com 3x o volume real, e falha acima do teto.
 * O tempo do próprio banco não conta (no Worker é espera, não CPU): as respostas ficam guardadas e o Worker só as lê.
 * Rodar: npm run cpu (também no CI). Tela nova entra em TELAS.
 */
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { createLocalJWKSet, exportJWK, generateKeyPair, SignJWT } from "jose";
import { usarChavesDeTeste } from "../src/acesso.ts";
import { app } from "../src/index.ts";
import { definirAgora } from "../src/relogio.ts";

const TETO_MS = 7; // limite grátis: 10 ms por pedido; o resto é folga
const TELAS = ["/configuracoes"];

const db = new DatabaseSync(":memory:");
for (const f of ["migrations/0001_inicial.sql", "test/dados/semente.sql", "test/dados/cenario-financeiro.sql"]) db.exec(readFileSync(f, "utf8"));

type Params = (string | number | null)[];
/** D1 de mentira sobre o SQLite do Node, com as leituras guardadas em texto (o Worker paga para ler a resposta). */
class Stmt {
  constructor(public sql: string, public params: Params = []) {}
  bind(...p: Params) { return new Stmt(this.sql, p); }
  executar() {
    const k = this.sql + JSON.stringify(this.params);
    let j = guardadas.get(k);
    if (j === undefined) {
      const s = db.prepare(this.sql);
      j = JSON.stringify(s.columns().length ? s.all(...this.params) : (s.run(...this.params), []));
      if (/^\s*select/i.test(this.sql)) guardadas.set(k, j);
    }
    return { results: JSON.parse(j), meta: { changes: 0, last_row_id: 0 } };
  }
  async all() { return this.executar(); }
  async first() { return this.executar().results[0] ?? null; }
  async run() { return this.executar(); }
}
const guardadas = new Map<string, string>();
const d1 = { prepare: (sql: string) => new Stmt(sql), batch: async (s: Stmt[]) => s.map((x) => x.executar()) };

const par = await generateKeyPair("RS256", { extractable: true });
usarChavesDeTeste(createLocalJWKSet({ keys: [{ ...(await exportJWK(par.publicKey)), kid: "k1", alg: "RS256" }] }));
const token = await new SignJWT({ email: "dono@exemplo.com" }).setProtectedHeader({ alg: "RS256", kid: "k1" }).setAudience(["aud"])
  .setIssuer("https://equipe.cloudflareaccess.com").setIssuedAt().setExpirationTime("1h").sign(par.privateKey);
const env = { DB: d1, BANCO: "d1", CF_ACCESS_TEAM_DOMAIN: "equipe.cloudflareaccess.com", CF_ACCESS_AUD: "aud" };
definirAgora(new Date("2026-11-19T15:00:00Z"));

async function pedir(caminho: string): Promise<[number, number]> {
  const r = await app.fetch(new Request(`https://crm.vfitcoachapp.com${caminho}`, { headers: { host: "crm.vfitcoachapp.com", "cf-access-jwt-assertion": token } }), env);
  return [r.status, (await r.text()).length];
}

let estourou = false;
console.log(`CPU por pedido, cenário 3x (teto ${TETO_MS} ms; limite grátis 10 ms):`);
for (const tela of TELAS) {
  const [status, tamanho] = await pedir(tela);
  if (status !== 200) throw new Error(`${tela} respondeu ${status}`);
  for (let i = 0; i < 5; i++) await pedir(tela);
  const t: number[] = [];
  for (let i = 0; i < 30; i++) {
    const c0 = process.cpuUsage();
    await pedir(tela);
    const c = process.cpuUsage(c0);
    t.push((c.user + c.system) / 1000);
  }
  t.sort((a, b) => a - b);
  const med = t[15];
  const ok = med <= TETO_MS;
  estourou ||= !ok;
  console.log(`  ${ok ? "ok " : "ESTOUROU"} ${tela.padEnd(24)} ${med.toFixed(2).padStart(6)} ms  (HTML ${(tamanho / 1024).toFixed(0)} KB)`);
}
if (estourou) {
  console.error("Alguma tela passou do teto: veja as regras de CPU em docs/reescrita-workers.md.");
  process.exit(1);
}
