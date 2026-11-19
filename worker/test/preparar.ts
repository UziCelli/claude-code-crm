import { applyD1Migrations, env } from "cloudflare:test";

// Cada arquivo de teste começa com o esquema do CRM (migrations/) no D1 local.
await applyD1Migrations(env.DB, env.TEST_MIGRATIONS);

// Nenhum teste fala com a internet de verdade (o repasse ao Render iria ao site real): quem precisa, troca o fetch com vi.spyOn.
const fetchDeVerdade = globalThis.fetch;
globalThis.fetch = (async (entrada: RequestInfo | URL) => {
  const url = entrada instanceof Request ? entrada.url : String(entrada);
  throw new Error(`Teste tentou acessar a internet: ${url}`);
}) as typeof fetch;
void fetchDeVerdade;
