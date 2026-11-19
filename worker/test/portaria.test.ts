import { env } from "cloudflare:test";
import { createLocalJWKSet, exportJWK, generateKeyPair, SignJWT } from "jose";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { usarChavesDeTeste } from "../src/acesso.ts";
import { app } from "../src/index.ts";

const EQUIPE = "vfit.cloudflareaccess.com";
const AUD = "aud-do-crm";
const HOST = "crm.vfitcoachapp.com";
let chave: CryptoKey;
let outraChave: CryptoKey;

async function token(o: { aud?: string; iss?: string; minutos?: number | null; k?: CryptoKey } = {}) {
  const jwt = new SignJWT({ email: "dono@exemplo.com" }).setProtectedHeader({ alg: "RS256", kid: "k1" })
    .setAudience([o.aud ?? AUD]).setIssuer(o.iss ?? `https://${EQUIPE}`).setIssuedAt();
  if (o.minutos !== null) jwt.setExpirationTime(Math.floor(Date.now() / 1000) + 60 * (o.minutos ?? 10));
  return jwt.sign(o.k ?? chave);
}

function pedir(caminho: string, init: RequestInit & { headers?: Record<string, string> } = {}, e = env) {
  return app.fetch(new Request(`https://${HOST}${caminho}`, { ...init, headers: { host: HOST, ...init.headers } }), e);
}

beforeAll(async () => {
  const par = await generateKeyPair("RS256", { extractable: true });
  chave = par.privateKey;
  outraChave = (await generateKeyPair("RS256")).privateKey;
  const jwk = { ...(await exportJWK(par.publicKey)), kid: "k1", alg: "RS256" };
  usarChavesDeTeste(createLocalJWKSet({ keys: [jwk] }));
});
afterEach(() => vi.restoreAllMocks());

// O Render (rota não migrada) é substituído por um fetch falso: devolve "render" e guarda o pedido.
function renderFalso() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("render", { status: 200 }));
}

describe("portaria (port de tests/test_acesso.py, modo internet)", () => {
  it("sem login é barrado", async () => {
    const r = await pedir("/");
    expect(r.status).toBe(403);
    expect(await r.text()).toContain("Acesso restrito");
  });

  it.each(["/saude", "/health", "/healthz"])("%s responde sem login", async (c) => {
    expect(await (await pedir(c)).text()).toBe("ok");
    expect((await pedir(c, { method: "HEAD" })).status).toBe(200);
  });

  it("login válido passa (cabeçalho ou cookie)", async () => {
    const f = renderFalso();
    expect((await pedir("/", { headers: { "cf-access-jwt-assertion": await token() } })).status).toBe(200);
    expect((await pedir("/clientes", { headers: { cookie: `CF_Authorization=${await token()}` } })).status).toBe(200);
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("token errado é barrado", async () => {
    const ruins = [await token({ aud: "outro-app" }), await token({ iss: "https://outra.cloudflareaccess.com" }),
      await token({ minutos: -5 }), await token({ minutos: null }), await token({ k: outraChave }), "lixo"];
    for (const t of ruins) expect((await pedir("/", { headers: { "cf-access-jwt-assertion": t } })).status, t).toBe(403);
  });

  it("sem configuração bloqueia tudo", async () => {
    const r = await pedir("/", { headers: { "cf-access-jwt-assertion": await token() } }, { ...env, CF_ACCESS_AUD: "" });
    expect(r.status).toBe(403);
    expect(await r.text()).toContain("ainda não foi configurada");
  });

  it("POST de outro site é recusado; da própria tela passa", async () => {
    const f = renderFalso();
    const h = { "cf-access-jwt-assertion": await token() };
    for (const origem of ["https://site-malicioso.com", `https://${HOST}.malicioso.com`, "null"])
      expect((await pedir("/backup", { method: "POST", headers: { ...h, origin: origem } })).status, origem).toBe(403);
    expect((await pedir("/backup", { method: "POST", headers: h })).status).toBe(403); // sem Origin/Referer
    expect((await pedir("/backup", { method: "POST", headers: { ...h, "sec-fetch-site": "cross-site", origin: `https://${HOST}` } })).status).toBe(403);
    expect((await pedir("/backup", { method: "POST", headers: { ...h, origin: `https://${HOST}` } })).status).toBe(200);
    expect((await pedir("/backup", { method: "POST", headers: { ...h, referer: `https://${HOST}/dados` } })).status).toBe(200);
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("CRM_ENDERECOS libera outro endereço público no Origin", async () => {
    renderFalso();
    const h = { "cf-access-jwt-assertion": await token(), origin: "https://crm-reserva.vfitcoachapp.com" };
    expect((await pedir("/backup", { method: "POST", headers: h })).status).toBe(403);
    expect((await pedir("/backup", { method: "POST", headers: h }, { ...env, CRM_ENDERECOS: "crm-reserva.vfitcoachapp.com" })).status).toBe(200);
  });

  it("toda resposta sai sem cache e sem moldura", async () => {
    renderFalso();
    for (const r of [await pedir("/"), await pedir("/", { headers: { "cf-access-jwt-assertion": await token() } })]) {
      expect(r.headers.get("cache-control")).toBe("no-store");
      expect(r.headers.get("x-frame-options")).toBe("DENY");
      expect(r.headers.get("content-security-policy")).toContain("frame-ancestors 'none'");
    }
  });
});

describe("sem BANCO configurado (achado do Codex na PR #117)", () => {
  const semBanco = { ...env, BANCO: undefined };
  it.each(["/saude", "/health", "/healthz"])("%s continua respondendo ok", async (c) => {
    const r = await pedir(c, {}, semBanco);
    expect(r.status).toBe(200);
    expect(await r.text()).toBe("ok");
  });
  it("rota não migrada continua indo ao Render", async () => {
    renderFalso();
    const r = await pedir("/clientes", { headers: { "cf-access-jwt-assertion": await token() } }, semBanco);
    expect(await r.text()).toBe("render");
  });
});

describe("repasse ao Render", () => {
  it("rota não migrada vai ao Render com o pedido intacto (método, corpo, token)", async () => {
    const f = renderFalso();
    const t = await token();
    const r = await pedir("/clientes/novo", { method: "POST", body: "nome=Ana", headers: { "cf-access-jwt-assertion": t, origin: `https://${HOST}`, "content-type": "application/x-www-form-urlencoded" } });
    expect(await r.text()).toBe("render");
    const [enviado, opcoes] = f.mock.calls[0] as [Request, RequestInit];
    expect(enviado.url).toBe(`https://${HOST}/clientes/novo`);
    expect(enviado.method).toBe("POST");
    expect(enviado.headers.get("cf-access-jwt-assertion")).toBe(t);
    expect(await enviado.text()).toBe("nome=Ana");
    expect(opcoes.redirect).toBe("manual");
  });

  it("ROTAS_RENDER devolve uma tela ao Render por emergência", async () => {
    const f = renderFalso();
    const h = { "cf-access-jwt-assertion": await token() };
    const e = { ...env, ROTAS_RENDER: "/saude-nao, /financeiro" };
    expect(await (await pedir("/financeiro/painel", { headers: h }, e)).text()).toBe("render");
    expect(await (await pedir("/financeiros", { headers: h }, e)).text()).toBe("render"); // não migrada: Render de qualquer jeito
    expect(f).toHaveBeenCalledTimes(2);
  });
});
