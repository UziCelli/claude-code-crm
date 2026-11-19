/** Layout de toda tela (port de base.html): menu, avisos, alertas do topo, diálogos comuns e app.js. */
import type { Child } from "hono/jsx";
import { raw } from "hono/html";
import { LOGO_SVG, VERSOES } from "../gerado/estaticos.ts";
import { Alertas } from "./Alertas.tsx";
import type { Contexto } from "./contexto.ts";
import { DlgEstado, DlgOferta, DlgPagamento, DlgPremio } from "./Dialogos.tsx";

const MENU: [string, string][] = [
  ["/assistente", "Assistente"], ["/clientes", "Clientes"], ["/leads", "Leads"], ["/grade", "Grade"], ["/agenda", "Agenda"],
  ["/propostas", "Propostas"], ["/explorador", "Explorador"], ["/campanhas", "Campanhas"], ["/financeiro", "Financeiro"], ["/rotina", "Rotina"],
];

export function Base(p: { ctx: Contexto; titulo?: string; volta?: string; caminho?: string; children?: Child }): Child {
  const c = p.caminho ?? p.ctx.caminho;
  const n = p.ctx.alertas.length;
  return (
    <>
      {raw("<!doctype html>")}
      <html lang="pt-BR">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>{p.titulo ?? "VFITCOACH CRM"}</title>
          <link rel="icon" type="image/svg+xml" href="/static/favicon.svg" />
          <link rel="alternate icon" type="image/png" href="/static/favicon.png" />
          <link rel="apple-touch-icon" href="/static/favicon.png" />
          <meta name="apple-mobile-web-app-title" content="VFIT CRM" />
          <link rel="stylesheet" href={`/static/style.css?v=${VERSOES["style.css"]}`} />
        </head>
        <body>
          <nav class="menu">
            <a class="marca" href="/" aria-label="VFITCOACH">{raw(LOGO_SVG)}</a>
            <a href="/" class={c === "/" ? "ativo" : ""}>Painel</a>
            {MENU.map(([href, nome]) => <a href={href} class={c.startsWith(href) ? "ativo" : ""}>{nome}</a>)}
            <span class="espaco"></span>
            <a href="/configuracoes" class={c.startsWith("/configuracoes") ? "ativo" : ""}>Configurações</a>
            <a href="/dados" class={c.startsWith("/dados") ? "ativo" : ""}>Dados</a>
            {/* pela internet: sai do login do Cloudflare Access neste aparelho; na próxima vez pede o código do e-mail */}
            <a href="/cdn-cgi/access/logout" class="sair" onclick="return confirm('Sair do CRM neste aparelho? Para entrar de novo, vai pedir o código do e-mail.')">Sair</a>
          </nav>
          <main>
            {p.ctx.msg && <div class="aviso ok">{p.ctx.msg}</div>}
            {p.ctx.erro && <div class="aviso erro">{p.ctx.erro}</div>}
            {n > 0 && c !== "/" && (
              <details class="alertas-topo">
                <summary>{n} alerta{n > 1 ? "s" : ""}</summary>
                <Alertas ctx={p.ctx} />
              </details>
            )}
            {p.children}
          </main>
          <DlgPagamento ctx={p.ctx} volta={p.volta ?? ""} />
          <DlgEstado />
          <DlgPremio />
          <DlgOferta />
          <script src={`/static/app.js?v=${VERSOES["app.js"]}`}></script>
        </body>
      </html>
    </>
  );
}
