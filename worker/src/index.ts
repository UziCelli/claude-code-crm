import { criarApp } from "./app.ts";
import { acordarRender } from "./repasse.ts";
import { rotasClientes } from "./rotas/clientes.tsx";
import { rotasConfiguracoes } from "./rotas/configuracoes.tsx";
import { rotasGrade } from "./rotas/grade.tsx";
import { rotasLeads } from "./rotas/leads.tsx";
import type { Env } from "./tipos.ts";

/** Telas migradas: cada fase acrescenta as suas aqui. */
export const app = criarApp((a) => {
  rotasConfiguracoes(a);
  rotasClientes(a);
  rotasLeads(a);
  rotasGrade(a);
  // rotasAgenda (./rotas/agenda.tsx) entra quando a paridade da 3c estiver pronta; até lá /agenda vai ao Render
});

export default {
  fetch: app.fetch,
  async scheduled(evento: ScheduledController, env: Env, ctx: ExecutionContext) {
    if (evento.cron === "*/10 * * * *") ctx.waitUntil(acordarRender(env).then(() => undefined));
    // "7 9 * * *": tarefas do dia (contas automáticas) entram com o Financeiro
  },
} satisfies ExportedHandler<Env>;
