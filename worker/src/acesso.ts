/**
 * Portaria do CRM (port de app/acesso.py): só passa quem entrou pelo Cloudflare Access.
 * O Access pede o e-mail e manda um código; depois envia em cada pedido um token assinado (cabeçalho
 * Cf-Access-Jwt-Assertion ou cookie CF_Authorization). Aqui conferimos assinatura, emissor, AUD e validade.
 * Sem CF_ACCESS_TEAM_DOMAIN / CF_ACCESS_AUD, tudo fica bloqueado (falha fechada).
 * No Worker não existe o "CRM no PC": vale sempre o modo da nuvem.
 */
import { createRemoteJWKSet, jwtVerify, type JWTVerifyGetKey } from "jose";
import type { Env } from "./tipos.ts";

const METODOS_SEGUROS = new Set(["GET", "HEAD", "OPTIONS"]);
export const LIVRES = new Set(["/saude", "/health", "/healthz"]); // checagem de saúde: não mostra dado nenhum

export const MENSAGENS = {
  config: "A portaria do Cloudflare Access ainda não foi configurada (CF_ACCESS_TEAM_DOMAIN e CF_ACCESS_AUD, " +
    "nas variáveis do Worker). Por segurança, nada é mostrado pela internet.",
  sem: "Entre pelo endereço do CRM (crm.vfitcoachapp.com) para fazer o login com o seu e-mail.",
  invalido: "Login expirado ou inválido. Abra crm.vfitcoachapp.com de novo para entrar.",
  origem: "Pedido recusado: ele não veio de uma tela do próprio CRM.",
} as const;
export type Motivo = keyof typeof MENSAGENS;

// Chaves públicas do Access: ficam em cache no isolate (o jose também guarda e renova sozinho).
const chavesPorEquipe = new Map<string, JWTVerifyGetKey>();
let chavesDeTeste: JWTVerifyGetKey | null = null;

/** Só nos testes: troca https://<equipe>/cdn-cgi/access/certs por chaves locais. */
export function usarChavesDeTeste(k: JWTVerifyGetKey | null): void {
  chavesDeTeste = k;
}

function chaves(equipe: string): JWTVerifyGetKey {
  if (chavesDeTeste) return chavesDeTeste;
  let k = chavesPorEquipe.get(equipe);
  if (!k) {
    k = createRemoteJWKSet(new URL(`https://${equipe}/cdn-cgi/access/certs`));
    chavesPorEquipe.set(equipe, k);
  }
  return k;
}

export function equipe(env: Env): string {
  return (env.CF_ACCESS_TEAM_DOMAIN ?? "").trim().replace(/^https:\/\//, "").replace(/\/+$/, "").replace(/^\/+/, "");
}

/** Dados do token (com o e-mail), ou erro se assinatura/AUD/emissor/validade não baterem. Token sem validade não serve. */
export async function verificar(token: string, env: Env) {
  const eq = equipe(env);
  const { payload } = await jwtVerify(token, chaves(eq), {
    algorithms: ["RS256"], audience: (env.CF_ACCESS_AUD ?? "").trim(), issuer: `https://${eq}`, requiredClaims: ["exp"],
  });
  return payload;
}

/** netloc do urlparse do Python: o que vem entre "esquema://" e a primeira "/", "?" ou "#"; sem esquema, vazio. */
function netloc(url: string): string {
  const m = /^[A-Za-z][A-Za-z0-9+.-]*:\/\/([^/?#]*)/.exec(url);
  return m ? m[1].toLowerCase() : "";
}

function cookie(cab: Headers, nome: string): string | undefined {
  for (const parte of (cab.get("cookie") ?? "").split(";")) {
    const i = parte.indexOf("=");
    if (i > 0 && parte.slice(0, i).trim() === nome) return decodeURIComponent(parte.slice(i + 1).trim());
  }
  return undefined;
}

/** POST que diz vir de outro site (Origin ou Referer com outro endereço): CSRF. Sem nenhum dos dois não há como saber. */
function origemEstranha(cab: Headers, env: Env): boolean {
  const origem = cab.get("origin") || cab.get("referer");
  if (origem === null) return false;
  const deOnde = netloc(origem);
  const enderecos = new Set((env.CRM_ENDERECOS ?? "").split(",").map((e) => e.trim().toLowerCase()).filter(Boolean));
  return deOnde !== (cab.get("host") ?? "").toLowerCase() && !enderecos.has(deOnde);
}

/** null = pode passar; senão, a chave de MENSAGENS que explica o bloqueio. */
export async function motivoBloqueio(req: Request, env: Env): Promise<Motivo | null> {
  const metodo = req.method.toUpperCase();
  const caminho = new URL(req.url).pathname;
  const cab = req.headers;
  if (LIVRES.has(caminho) && (metodo === "GET" || metodo === "HEAD")) return null;
  const altera = !METODOS_SEGUROS.has(metodo);
  // Fetch Metadata cobre formulários com Referrer-Policy: no-referrer (sem Origin/Referer).
  if (altera && cab.get("sec-fetch-site") === "cross-site") return "origem";
  if (!(equipe(env) && (env.CF_ACCESS_AUD ?? "").trim())) return "config";
  const token = cab.get("cf-access-jwt-assertion") || cookie(cab, "CF_Authorization");
  if (!token) return "sem";
  try {
    await verificar(token, env);
  } catch {
    return "invalido";
  }
  // pela internet o POST sem Origin/Referer também é recusado
  if (altera && (origemEstranha(cab, env) || !(cab.get("origin") || cab.get("referer")))) return "origem";
  return null;
}

export function paginaBloqueio(motivo: Motivo): Response {
  return new Response(
    "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>" +
      "<title>VFITCOACH CRM</title><body style='font-family:system-ui;padding:24px;background:#E8F0FA;color:#0F2A52'>" +
      `<h1>Acesso restrito</h1><p>${MENSAGENS[motivo]}</p>`,
    { status: 403, headers: { "content-type": "text/html; charset=utf-8" } },
  );
}

/** Todo o CRM é privado, inclusive exportações, redirects e respostas de erro. */
export function protegerResposta(r: Response): Response {
  const resp = new Response(r.body, r); // cabeçalhos de uma resposta repassada são imutáveis: copia
  resp.headers.set("Cache-Control", "no-store");
  resp.headers.set("X-Content-Type-Options", "nosniff");
  resp.headers.set("Referrer-Policy", "same-origin");
  resp.headers.set("X-Frame-Options", "DENY");
  resp.headers.set("Content-Security-Policy", "frame-ancestors 'none'; object-src 'none'; base-uri 'self'");
  return resp;
}
