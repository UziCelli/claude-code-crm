/** Botões de alerta e de aluno (port de _acoes.html): WhatsApp, POST com confirmação, diálogo ou link. */
import type { Child } from "hono/jsx";
import { preencher, strPy, wa } from "../formato.ts";
import type { Acao, Cartao, Contexto } from "./contexto.ts";

/** Atributos data-* de um botão de diálogo, na ordem do dicionário. */
export function dadosAttr(dados: Record<string, unknown> | undefined): Record<string, string> {
  return Object.fromEntries(Object.entries(dados ?? {}).map(([k, v]) => [`data-${k}`, strPy(v)]));
}

/** O botão do WhatsApp, igual em toda tela. Com cartão: formulário que gera o cartão-imagem com o QR Pix (app.js). */
export function BotaoWa(p: { ctx: Contexto; tel?: string | null; modelo?: string | null; nome?: string | null; data?: string | null;
  extra?: Record<string, unknown> | null; botao?: string | null; cartao?: Cartao | null }): Child {
  if (p.cartao)
    return (
      <form method="post" action={p.cartao.acao} target="_blank" class="inline" data-cartao={p.cartao.svg} data-codigo={p.cartao.codigo}>
        <button type="submit" class="claro pequeno">{p.botao}</button>
      </form>
    );
  const modelo = p.modelo ? String(p.ctx.modelos[p.modelo] ?? "") : "";
  const texto = preencher(modelo, p.nome ?? "", p.data ?? "", { ...p.ctx.dadosMsg, ...(p.extra ?? {}) });
  return <a class="btn claro pequeno" href={wa(p.tel, texto)} target="_blank" rel="noopener">{p.botao || "WhatsApp"}</a>;
}

/** Ação que muda algo no servidor: volta para a mesma tela. */
export function BotaoPost(p: { x: Acao; voltar: string }): Child {
  return (
    <form method="post" action={p.x.post} class="inline" data-confirmar={p.x.confirmar || undefined}>
      <input type="hidden" name="volta" value={p.voltar} />
      <input type="hidden" name="voltar" value={p.voltar} />
      <button type="submit" class={`${p.x.classe || "claro"} pequeno`}>{p.x.rotulo}</button>
    </form>
  );
}

export function BotaoDialogo(p: { x: Acao; voltar: string }): Child {
  return (
    <button type="button" class={`${p.x.classe || "claro"} pequeno`} data-abrir={p.x.dialogo} data-voltar={p.voltar} {...dadosAttr(p.x.dados)}>
      {p.x.rotulo}
    </button>
  );
}

export interface EstadoBotoes { tel?: string | null; modelo?: string | null; nome?: string | null; data_modelo?: string | null;
  extra?: Record<string, unknown> | null; botao?: string | null; cartao?: Cartao | null }

/** Os botões de um aluno (acoes do estado). */
export function Botoes(p: { ctx: Contexto; acoes: Acao[]; e: EstadoBotoes; voltar: string }): Child {
  return (
    <>
      {p.acoes.map((x) =>
        x.wa ? <BotaoWa ctx={p.ctx} tel={p.e.tel} modelo={p.e.modelo} nome={p.e.nome} data={p.e.data_modelo} extra={p.e.extra}
          botao={x.botao || p.e.botao} cartao={x.cartao || p.e.cartao} />
          : x.post ? <BotaoPost x={x} voltar={p.voltar} />
          : x.dialogo ? <BotaoDialogo x={x} voltar={p.voltar} />
          : <a class="btn claro pequeno" href={x.href}>{x.rotulo}</a>,
      )}
    </>
  );
}
