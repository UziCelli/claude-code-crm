import { type Context, Hono } from "hono";
import { motivoBloqueio, paginaBloqueio, protegerResposta } from "./acesso.ts";
import { abrirBanco, type Banco, ErroConfig } from "./banco/banco.ts";
import { repassar, vaiProRender } from "./repasse.ts";
import type { Env } from "./tipos.ts";

export type Ambiente = { Bindings: Env; Variables: { banco?: Banco } };

/** O banco do pedido, aberto só quando a rota precisa: saúde e repasse ao Render funcionam mesmo sem BANCO configurado. */
export function banco(c: Context<Ambiente>): Banco {
  let b = c.get("banco");
  if (!b) {
    b = abrirBanco(c.env);
    c.set("banco", b);
  }
  return b;
}

/** O CRM: portaria em tudo, telas já migradas aqui, o resto repassado ao Render (app/ em Python) até a última fase. */
export function criarApp(registrar: (app: Hono<Ambiente>) => void): Hono<Ambiente> {
  const app = new Hono<Ambiente>();

  app.use("*", async (c, next) => {
    const motivo = await motivoBloqueio(c.req.raw, c.env);
    if (motivo) {
      c.res = protegerResposta(paginaBloqueio(motivo));
      return;
    }
    if (vaiProRender(c.req.path, c.env)) {
      c.res = protegerResposta(await repassar(c.req.raw));
      return;
    }
    await next();
    const resp = protegerResposta(c.res);
    const b = c.get("banco");
    if (b) resp.headers.set("x-crm-idas", String(b.idas)); // idas ao banco deste pedido (o limite grátis é 50)
    c.res = resp;
  });

  for (const caminho of ["/saude", "/health", "/healthz"]) app.on(["GET", "HEAD"], caminho, (c) => c.text("ok"));
  registrar(app);

  // rota que ainda não foi migrada: o Render atende
  app.notFound(async (c) => repassar(c.req.raw));
  app.onError((erro, c) => {
    console.error(erro);
    const texto = erro instanceof ErroConfig ? erro.message : "Erro inesperado. Tente de novo; se continuar, chame o Claude.";
    return c.html(`<!doctype html><meta charset="utf-8"><title>VFITCOACH CRM</title><h1>Erro</h1><p>${texto.replace(/</g, "&lt;")}</p>`, 500);
  });
  return app;
}
