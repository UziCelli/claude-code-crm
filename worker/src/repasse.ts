/**
 * Repasse ao CRM antigo (Render) enquanto ele existir.
 * O Worker fica numa rota do Cloudflare em crm.vfitcoachapp.com/*: um fetch() do próprio pedido segue para a origem
 * (o Render, pelo DNS de hoje) sem passar de novo pelo Worker, com o Host, o cookie e o token do Access intactos.
 * Assim o Render recebe exatamente o que recebia antes e confere o token como sempre (app/acesso.py).
 */
import type { Env } from "./tipos.ts";

/** Prefixos que voltam ao Render por emergência (variável ROTAS_RENDER, separada por vírgula). "/" sozinho = tudo. */
export function vaiProRender(caminho: string, env: Env): boolean {
  const prefixos = (env.ROTAS_RENDER ?? "").split(",").map((p) => p.trim()).filter(Boolean);
  return prefixos.some((p) => p === "/" || caminho === p || caminho.startsWith(p.endsWith("/") ? p : p + "/"));
}

export async function repassar(req: Request): Promise<Response> {
  // redirect "manual": o navegador segue os redirecionamentos do CRM, que são relativos
  return fetch(req, { redirect: "manual" });
}

/** Cron: acorda o Render (plano grátis dorme depois de 15 min parado). Sem RENDER_URL, não faz nada. */
export async function acordarRender(env: Env): Promise<number | null> {
  if (!env.RENDER_URL) return null;
  const r = await fetch(new URL("/saude", env.RENDER_URL), { method: "GET" });
  return r.status;
}
