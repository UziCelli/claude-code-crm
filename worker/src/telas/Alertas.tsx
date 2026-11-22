/** Lista de alertas (port de _alertas.html): o texto (link) e, embaixo, os botões na ordem. */
import type { Child } from "hono/jsx";
import { BotaoDialogo, BotaoPost, BotaoWa } from "./Acoes.tsx";
import type { Contexto } from "./contexto.ts";

export function Alertas({ ctx }: { ctx: Contexto }): Child {
  return (
    <ul class="lista-alertas">
      {ctx.alertas.map((a) => (
        <li class={a.cor}>
          <a href={a.url}>{a.texto}</a>
          <div class="acoes-alerta">
            {a.acoes.length
              ? a.acoes.map((x) =>
                x.wa ? <BotaoWa ctx={ctx} tel={a.tel} modelo={a.modelo} nome={a.nome} data={a.data} extra={a.extra}
                  botao={x.botao || a.botao} cartao={x.cartao || a.cartao} />
                  : x.post ? <BotaoPost x={x} voltar={ctx.caminho} />
                  : x.dialogo ? <BotaoDialogo x={x} voltar={ctx.caminho} />
                  : <a class="btn claro pequeno" href={x.href} target={x.externo ? "_blank" : undefined} rel={x.externo ? "noopener" : undefined}>{x.rotulo}</a>)
              : <a class="btn claro pequeno" href={a.url}>Resolver</a>}
          </div>
        </li>
      ))}
    </ul>
  );
}
