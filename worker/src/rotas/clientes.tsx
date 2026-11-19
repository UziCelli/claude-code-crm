/**
 * Clientes: lista (com as listas filtradas dos alertas), novo cliente, ficha e as ações da ficha que não mexem na Agenda.
 * Port de main.py (clientes, cliente_novo, cliente_criar, cliente_ficha, cliente_wa, cartões, depoimento, crédito, consultoria,
 * excluir, presente e ofertas). Salvar a ficha, status, evento, pular mês e horários entram com a Agenda (Fase 3).
 */
import type { Context, Hono } from "hono";
import { html, raw } from "hono/html";
import type { Child } from "hono/jsx";
import { banco, type Ambiente } from "../app.ts";
import type { Banco } from "../banco/banco.ts";
import type { Linha } from "../banco/tipos.ts";
import { arred } from "../arred.ts";
import { capitalizar, dataBr, moeda, num, pct, preencher, reprFloat, wa } from "../formato.ts";
import { darCredito, estado, estadoAluno, SEM_AULA, type Estado } from "../regras/alunos.ts";
import { svg } from "../regras/cartao.ts";
import { diferencaCartao, pendenciaDiferenca } from "../regras/cobranca.ts";
import { dataIso } from "../regras/datas.ts";
import { diferencas, pagoAdiantadoAte, proximaRenovacao, renovacoes } from "../regras/financeiro.ts";
import { alunosParaEscolher, CANAL, doAluno, quemIndicou, registrarPresente, validar as validarIndicacao } from "../regras/indicacoes.ts";
import { nomes } from "../regras/locais.ts";
import { dadosMensagem } from "../regras/mensagens.ts";
import { relogioMes } from "../regras/mes.ts";
import * as ofertas from "../regras/ofertas.ts";
import { parametros } from "../regras/parametros.ts";
import { carregarParametros, corMargem } from "../regras/precos.ts";
import { fixosAtuais } from "../regras/trabalho.ts";
import { doLocal, lista as listaVantagens, sugestoesPresente, texto as textoVantagem } from "../regras/vantagens.ts";
import { estimativaCliente, horariosTexto, idValido, renovacaoECobranca, waContexto, waMenu, waRotulo, waTexto, cobrancaAtualDe } from "../regras/ficha.ts";
import { Botoes } from "../telas/Acoes.tsx";
import { Base } from "../telas/Base.tsx";
import { contextoBase, type Contexto } from "../telas/contexto.ts";
import { caminhoSeguro, ErroValor, intPy, numBr, quoteUrl, voltar } from "./util.ts";

export const CAMPOS_CLIENTE = ["nome", "telefone", "local", "tipo_servico", "plano", "pessoas", "dias_horarios", "valor",
  "forma_pagamento", "status", "canal_origem", "data_inicio", "data_renovacao", "observacoes", "indicado_por"];
export const MAX_IDS = 200;
export const MOTIVOS_LISTA: Record<string, string> = { "sem-aula": "Alunos sem nenhuma aula registrada", incompleto: "Cadastro incompleto",
  cobrar: "Mensalidades vencidas", indicacao: "Alunos para pedir indicação", reativar: "Ex-alunos para chamar de volta",
  reajuste: "Alunos abaixo do preço mínimo", dupla: "Alunos para convidar a treinar em dupla", upsell: "Alunos para receber a oferta" };
export const AJUDA_LISTA: Record<string, string> = { cobrar: "Cobre um por um: quem pagar sai da lista.",
  indicacao: "Mande a mensagem: quando a pessoa indicada fechar, dê um presente a quem indicou.",
  reativar: "Mande a mensagem; se voltar, abra a ficha e mude o status para ativo.",
  reajuste: "Veja o valor de hoje e o mínimo, abra a ficha e ajuste o valor.",
  dupla: "Mande o convite: em dupla o treino rende mais para você e é mais animado para eles.",
  upsell: "Envie a proposta: quem recebe sai da lista. Depois marque Aceitou ou Recusou na ficha." };
export const MODELO_LISTA: Record<string, string> = { indicacao: "indicacao", reativar: "reativacao", dupla: "dupla" };
export const STATUS_LISTA: Record<string, string | null> = { reativar: "inativo", cobrar: "ativo", indicacao: "ativo", dupla: "ativo", reajuste: "ativo",
  "sem-aula": null, incompleto: "ativo", upsell: "ativo" };
export const TIPOS_SEM_AULA = ["Consultoria Online", "Consultoria Híbrida"];

const hoje = () => relogioMes.hoje();
const virgula2 = (x: number) => arred(x, 2).toFixed(2).replace(".", ",");
/** str() do Jinja para um valor do banco: None vira "None", float vira "600.0". */
const strJinja = (v: unknown) => (v === null || v === undefined ? "None" : typeof v === "number" ? reprFloat(v) : String(v));

async function formulario(c: Context<Ambiente>): Promise<Record<string, string>> {
  const corpo = await c.req.parseBody();
  return Object.fromEntries(Object.entries(corpo).map(([k, v]) => [k, typeof v === "string" ? v : ""]));
}

// ---------- lista ----------
interface ItemLista extends Linha { alerta: string | null; faltas: string[]; estado: Estado | undefined; minimo: number | undefined; vantagem: string | null }

async function lista(b: Banco, url: URL) {
  const q = (k: string, padrao = "") => url.searchParams.get(k) ?? padrao;
  const status = q("status", "ativo"), busca = q("busca"), ids = q("ids"), motivo = q("motivo");
  const oferta = Number(q("oferta", "0")) || 0;
  const filtro = [...new Set(ids.split(",").map(idValido).filter(Boolean))].slice(0, MAX_IDS);
  let sql = "SELECT * FROM clientes WHERE excluido_em IS NULL";
  const args: (string | number)[] = [];
  if (filtro.length) {
    sql += ` AND id IN (${filtro.map(() => "?").join(",")})`;
    args.push(...filtro);
    if (motivo === "incompleto") sql += " AND status='ativo' AND (telefone IS NULL OR telefone='' OR data_renovacao IS NULL)";
    else if (STATUS_LISTA[motivo]) {
      sql += " AND status=?";
      args.push(STATUS_LISTA[motivo]!);
    }
  } else {
    if (status !== "todos") {
      sql += " AND status=?";
      args.push(status);
    }
    if (busca) {
      sql += " AND nome LIKE ?";
      args.push(`%${busca}%`);
    }
  }
  const h = hoje();
  let rows = await b.query(sql + " ORDER BY status='ativo' DESC, nome", args);
  const [estados, ren, totaisRows, adiantado, horarios, leque, ativas, ja, p] = await Promise.all([
    estado(b, h, rows.filter((c) => c.status === "ativo").map((c) => c.id)),
    renovacoes(b),
    b.query("SELECT status, COUNT(*) AS n FROM clientes WHERE excluido_em IS NULL GROUP BY status"),
    pagoAdiantadoAte(b, h), horariosTexto(b),
    motivo === "indicacao" ? listaVantagens(b) : Promise.resolve(null),
    filtro.length && motivo === "upsell" ? ofertas.ativas(b, h) : Promise.resolve([] as Linha[]),
    filtro.length && motivo === "upsell" ? b.query("SELECT cliente_id FROM oferta_respostas WHERE oferta_id=? AND excluido_em IS NULL", [oferta]) : Promise.resolve([] as Linha[]),
    filtro.length && motivo === "reajuste" ? carregarParametros(b) : Promise.resolve(null),
  ]);
  if (filtro.length && motivo === "sem-aula") rows = rows.filter((c) => estados.has(c.id) && SEM_AULA.includes(estados.get(c.id)!.situacao));
  if (filtro.length && motivo === "cobrar") rows = rows.filter((c) => estados.has(c.id) && estados.get(c.id)!.situacao === "cobrar");
  let ofertaLista: Linha | null = null;
  if (filtro.length && motivo === "upsell") {
    ofertaLista = ativas.find((o) => o.id === oferta) ?? null;
    const jaSet = new Set(ja.map((r) => r.cliente_id as number));
    rows = rows.filter((c) => ofertaLista && !jaSet.has(c.id));
  }
  const minimos = new Map<number, number>();
  if (filtro.length && motivo === "reajuste" && p) {
    for (const c of rows) {
      const est = estimativaCliente(c, p);
      if (est && est.abaixo_margem && est.preco_minimo > (c.valor || 0)) minimos.set(c.id, est.preco_minimo);
    }
    rows = rows.filter((c) => minimos.has(c.id));
  }
  const vantagens = leque ? await Promise.all(rows.map((c) => doLocal(b, c.local, leque))) : null;
  const itens: ItemLista[] = rows.map((c, i) => {
    const renova = ren.has(c.id) ? ren.get(c.id)!.efetiva : c.data_renovacao;
    let alerta: string | null = null;
    const r = dataIso(renova);
    if (r && c.status === "ativo") {
      const dias = Number(new Date(r + "T00:00:00Z")) / 86_400_000 - Number(new Date(h + "T00:00:00Z")) / 86_400_000;
      alerta = dias < 0 ? "vermelho" : dias <= 7 ? "amarelo" : null;
    }
    const faltas = ([["falta telefone", !c.telefone], ["falta data de renovação", !c.data_renovacao]] as [string, boolean][]).filter(([, f]) => f).map(([t]) => t);
    return { ...c, data_renovacao: renova, alerta, faltas, estado: estados.get(c.id), minimo: minimos.get(c.id),
      vantagem: vantagens ? textoVantagem(vantagens[i]) : null };
  });
  const totais = Object.fromEntries(totaisRows.map((r) => [r.status as string, r.n as number]));
  const motivoOk = motivo in MOTIVOS_LISTA ? motivo : "";
  return { itens, status, busca, totais, filtrado: filtro.length > 0, adiantado, horarios, motivo: motivoOk,
    titulo: MOTIVOS_LISTA[motivo] ?? "Alunos selecionados", ajuda: AJUDA_LISTA[motivo] ?? "", modeloLista: MODELO_LISTA[motivo] ?? "", ofertaLista,
    voltarLista: `/clientes?ids=${filtro.join(",")}&motivo=${motivoOk}` + (motivoOk === "upsell" ? `&oferta=${oferta}` : "") };
}

type DadosLista = Awaited<ReturnType<typeof lista>>;

/**
 * O cartão de cada aluno da lista, com `html` do Hono (texto direto): é a parte grande da tela e, em JSX, passava do
 * orçamento de CPU (docs/reescrita-workers.md). Mesmo HTML do clientes.html.
 */
function cartaoAluno(ctx: Contexto, d: DadosLista, c: ItemLista) {
  const a = d.adiantado.get(c.id);
  const est = c.estado;
  const pacote = c.tipo_servico === "Pacote de Aulas" || (c.plano || "").startsWith("Pacote");
  return html`<div class="card cartao-aluno borda-${c.alerta || (c.status === "ativo" ? "verde" : "neutro")}">
  <a href="/clientes/${c.id}" style="color:inherit;display:block;text-decoration:none">
    <div class="linha" style="justify-content:space-between"><strong>${c.nome}</strong><span class="tag status-${c.status}">${c.status}</span></div>
    <div class="muted">${c.local || "—"} · ${c.plano || c.tipo_servico || "—"}${c.pessoas && c.pessoas > 1 ? ` · ${c.pessoas} pessoas` : ""}</div>
    <div class="linha mt" style="margin-top:8px;justify-content:space-between">
      <span><strong>${moeda(c.valor)}</strong> <span class="muted">${pacote ? "/ pacote" : "/ mês"}</span>${a ? html` <span class="tag azul" title="Pagou vários meses de uma vez; depois volta a pagar por mês">Pago adiantado até ${a.slice(5)}/${a.slice(0, 4)}</span>` : ""}</span>
      <span class="muted">${d.horarios.get(c.id) || c.dias_horarios || "sem horário"}</span>
    </div>
    ${c.data_renovacao ? html`<div class="muted" style="margin-top:6px">Renova em ${dataBr(c.data_renovacao)}</div>` : ""}
    ${est && est.situacao !== "em_dia" ? html`<div style="margin-top:6px"><span class="tag ${est.cor}">${est.rotulo}</span> <span class="muted">${est.texto}</span></div>` : ""}
  </a>
  ${est && est.acoes.length ? html`<div class="acoes-alerta">${raw(String(<Botoes ctx={ctx} acoes={est.acoes} e={est as never} voltar={ctx.caminho} />))}</div>` : ""}
</div>`;
}

function TelaLista({ ctx, d }: { ctx: Contexto; d: DadosLista }): Child {
  const borda = (c: ItemLista) => `card borda-${c.alerta || (c.status === "ativo" ? "verde" : "neutro")}`;
  return (
    <Base ctx={ctx}>
      <div class="linha topo">
        <h1 style="margin:0">Clientes</h1>
        <a class="btn" href="/clientes/novo">Novo cliente</a>
      </div>
      {d.filtrado ? (
        <div class="card atencao linha topo">
          <div><strong>{d.titulo}{d.motivo === "upsell" && d.ofertaLista ? `: ${d.ofertaLista.titulo}` : ""}</strong> <span class="muted">{`(${d.itens.length})`}</span>
            <div class="muted">{d.motivo === "upsell" && !d.ofertaLista ? "Essa oferta não está ativa (pausada, vencida ou excluída). Veja em Campanhas."
              : d.itens.length ? d.ajuda || (d.motivo ? "Resolva um por um: quem fica certo sai da lista." : "Só os alunos escolhidos no alerta.") : "Tudo resolvido por aqui."}</div></div>
          <div class="linha">{d.motivo === "upsell" && <a class="btn" href="/campanhas#ofertas">Ver ofertas</a>}<a class="btn claro" href="/clientes">Ver todos</a></div>
        </div>
      ) : (
        <form class="linha" method="get">
          {([["ativo", "Ativos"], ["pausado", "Pausados"], ["inativo", "Inativos"], ["todos", "Todos"]] as [string, string][]).map(([s, r]) => (
            <a class={`btn ${d.status !== s ? "claro" : ""}`} href={`/clientes?status=${s}&busca=${d.busca}`}>{r} {s !== "todos" ? `(${d.totais[s] ?? 0})` : ""}</a>
          ))}
          <input type="hidden" name="status" value={d.status} />
          <input name="busca" value={d.busca} placeholder="Buscar por nome" class="busca" />
          <button class="claro">Buscar</button>
        </form>
      )}
      <div class="grid c3 mt">
        {d.itens.length ? d.itens.map((c) => d.filtrado ? (
          <div class={borda(c)}>
            <div class="linha" style="justify-content:space-between">
              <a href={`/clientes/${c.id}`}><strong>{c.nome}</strong></a>
              <span class={`tag status-${c.status}`}>{c.status}</span>
            </div>
            <div class="muted">{`${c.local || "—"} · ${c.plano || c.tipo_servico || "—"}` + (c.data_inicio ? ` · começou em ${dataBr(c.data_inicio)}` : "")}</div>
            {c.estado && c.estado.situacao !== "em_dia" && <div style="margin-top:6px"><span class={`tag ${c.estado.cor}`}>{c.estado.rotulo}</span> <span class="muted">{c.estado.texto}</span></div>}
            {d.motivo === "sem-aula" ? (
              <div class="linha mt" style="margin-top:10px">
                <a class="btn pequeno" href={`/agenda?aluno=${c.id}`}>Abrir agenda</a>
                {c.estado && <Botoes ctx={ctx} acoes={c.estado.acoes.filter((x) => !["Abrir agenda", "Não tem aula (consultoria)"].includes(String(x.rotulo)))} e={c.estado as never} voltar={d.voltarLista} />}
                <form method="post" action={`/clientes/${c.id}/consultoria`} class="linha" style="gap:6px">
                  <input type="hidden" name="voltar" value={d.voltarLista} />
                  <label for={`ts${c.id}`} style="margin:0">Não tem aula:</label>
                  <select id={`ts${c.id}`} name="tipo_servico" style="width:auto">{TIPOS_SEM_AULA.map((t) => <option>{t}</option>)}</select>
                  <button class="claro pequeno">Salvar</button>
                </form>
              </div>
            ) : d.motivo === "cobrar" ? (
              <div class="acoes-alerta" style="margin-top:10px">{c.estado && <Botoes ctx={ctx} acoes={c.estado.acoes} e={c.estado as never} voltar={d.voltarLista} />}</div>
            ) : ["indicacao", "dupla", "reativar", "reajuste"].includes(d.motivo) ? (
              <>
                {d.motivo === "reajuste" && <div style="margin-top:6px">Hoje <strong>{moeda(c.valor)}</strong> · mínimo <strong>{moeda(c.minimo)}</strong></div>}
                <div class="linha mt" style="margin-top:10px">
                  <a class="btn pequeno" href={wa(c.telefone, d.modeloLista ? preencher(String(ctx.modelos[d.modeloLista]), c.nome, "",
                    { ...ctx.dadosMsg, ...(c.vantagem !== null ? { vantagem: c.vantagem } : {}) }) : "")} target="_blank" rel="noopener">WhatsApp</a>
                  <a class="btn claro pequeno" href={`/clientes/${c.id}`}>Abrir ficha</a>
                </div>
              </>
            ) : d.motivo === "upsell" ? (
              <>
                <div style="margin-top:6px">Hoje <strong>{moeda(c.valor)}</strong> · oferta <strong>{moeda(d.ofertaLista!.valor_oferta)}</strong></div>
                <div class="linha mt" style="margin-top:10px">
                  {c.telefone
                    ? <form method="post" action={`/clientes/${c.id}/oferta/${d.ofertaLista!.id}/enviar`} target="_blank" class="inline" onsubmit="setTimeout(function(){location.reload()},1500)"><button class="pequeno">Enviar oferta</button></form>
                    : <a class="btn pequeno" href={`/clientes/${c.id}#cadastro`}>Completar telefone</a>}
                  <a class="btn claro pequeno" href={`/clientes/${c.id}#ofertas`}>Abrir ficha</a>
                </div>
              </>
            ) : d.motivo === "incompleto" ? (
              <div class="linha mt" style="margin-top:10px">
                {c.faltas.map((f) => <span class="tag amarelo">{f}</span>)}
                <a class="btn pequeno" href={`/clientes/${c.id}#cadastro`}>Completar</a>
              </div>
            ) : null}
          </div>
        ) : cartaoAluno(ctx, d, c)) : !d.filtrado && (
          <div>
            <p class="muted">{d.busca ? `Nenhum cliente com “${d.busca}”. Confira o nome ou veja Todos.` : "Nenhum cliente aqui. Cadastre um ou importe da planilha em Configurações."}</p>
            <a class="btn" href="/clientes/novo">Novo cliente</a> <a class="btn claro" href="/configuracoes">Importar planilha</a>
          </div>
        )}
      </div>
    </Base>
  );
}

// ---------- ficha ----------
const TAG_EVENTO: Record<string, string> = { aula: "azul", falta: "vermelho", desmarcou: "amarelo", cancelada: "neutro", pagamento: "verde", renovacao: "amarelo",
  pausa: "azul", credito: "verde", brinde: "verde", mensagem: "neutro", depoimento: "verde", status: "neutro", anotacao: "neutro" };
const NOME_EVENTO: Record<string, string> = { aula: "aula dada", falta: "faltou", pausa: "pulou o mês", cancelada: "cancelada (não repõe)", credito: "crédito",
  brinde: "presente", mensagem: "mensagem enviada" };
const DCURTO: Record<number, string> = { 1: "Seg", 2: "Ter", 3: "Qua", 4: "Qui", 5: "Sex", 6: "Sáb" };
const PLANOS_DATALIST = ["Pacote 4 aulas", "Pacote 8 aulas", "Pacote 12 aulas", "Pacote 16 aulas", "Pacote 20 aulas", "Mensalidade 1x/semana", "Mensalidade 2x/semana",
  "Mensalidade 3x/semana", "Mensalidade 4x/semana", "Mensalidade 5x/semana", "Consultoria Online", "Consultoria Híbrida", "Avaliação Física"];
const SCRIPT_HORARIOS = `
    (function () {
      var card = document.getElementById("horarios"), lista = card.querySelector("[data-horarios]");
      card.addEventListener("click", function (e) {
        if (e.target.closest("[data-mais-horario]")) {
          lista.appendChild(card.querySelector("[data-modelo-horario]").content.cloneNode(true));
          var vazio = card.querySelector("[data-sem-horario]"); if (vazio) vazio.hidden = true;
        } else if (e.target.closest("[data-tirar-horario]")) {
          e.target.closest(".horario-linha").remove();
        }
      });
    })();
    `;

async function maxAlunos(b: Banco): Promise<number> {
  const v = (await parametros(b, "agenda")).max_alunos_horario;
  const n = Math.trunc(Number(v || 2));
  return Number.isNaN(n) ? 2 : Math.max(n, 1);
}

async function dadosFicha(b: Banco, c: Linha) {
  const cid = c.id as number, h = hoje();
  const [eventos, p, propostas, pagamentos, rc, temPago, difs, dados, adiantado, horarios, locais, max, est, indicadores, indicou, indicadoPor, sugestoes, ofertasFicha] = await Promise.all([
    b.query("SELECT * FROM cliente_eventos WHERE cliente_id=? AND excluido_em IS NULL ORDER BY data DESC, id DESC", [cid]),
    carregarParametros(b),
    b.query("SELECT * FROM propostas WHERE cliente_id=? AND excluido_em IS NULL ORDER BY id DESC", [cid]),
    b.query("SELECT * FROM lancamentos WHERE cliente_id=? AND excluido_em IS NULL ORDER BY data DESC, id DESC LIMIT 8", [cid]),
    renovacaoECobranca(b, c, h),
    b.um(`SELECT 1 AS um FROM lancamentos WHERE cliente_id=? AND escopo='PJ' AND tipo='entrada' AND pago_em IS NOT NULL AND excluido_em IS NULL
      UNION ALL SELECT 1 FROM cliente_eventos WHERE cliente_id=? AND tipo='pagamento' AND excluido_em IS NULL LIMIT 1`, [cid, cid]),
    diferencas(b, cid), dadosMensagem(b), pagoAdiantadoAte(b, h),
    fixosAtuais(b, new Set([cid])), nomes(b), maxAlunos(b), estadoAluno(b, cid, h),
    alunosParaEscolher(b, cid), doAluno(b, cid), quemIndicou(b, cid), sugestoesPresente(b, c.local),
    c.status === "ativo" ? ofertas.situacaoAluno(b, cid, h) : Promise.resolve([] as ofertas.SituacaoOferta[]),
  ]);
  const [renovacao, cob] = rc;
  let pagoAte: string | null = null;
  if (renovacao && renovacao.ciclos && temPago) {
    const m = proximaRenovacao(String(renovacao.efetiva), -1);
    pagoAte = `${m.slice(5, 7)}/${m.slice(0, 4)}`;
  }
  const minhas = difs.get(cid);
  const menu = await waMenu(b, c, rc, eventos, h);
  return { c, eventos, estimativa: estimativaCliente(c, p), propostas, pagamentos, renovacao, cobranca: cob, pagoAte,
    diferenca: minhas ? pendenciaDiferenca(c as never, minhas, dados) : null, adiantadoAte: adiantado.get(cid) ?? null,
    horarios: horarios.sort((x, y) => x.dia - y.dia || x.hora - y.hora), locais, max, estado: est, menu, indicadores, indicou, indicadoPor, sugestoes, ofertasFicha };
}

type DadosFicha = Awaited<ReturnType<typeof dadosFicha>>;

function FormCadastro({ ctx, c, renova, indicadores }: { ctx: Contexto; c: Linha | null; renova: string; indicadores: Linha[] }): Child {
  const l = ctx.listas;
  return (
    <form method="post" action={c ? `/clientes/${c.id}` : "/clientes"} class="form-grid">
      <div class="largo"><label>Nome</label><input name="nome" required value={c ? c.nome : ""} /></div>
      <div><label>Telefone / WhatsApp</label><input id="telefone" name="telefone" value={c ? c.telefone || "" : ""} /></div>
      <div><label>Local</label><select name="local"><option value="">—</option>{l.lista_locais.map((x) => <option selected={Boolean(c && c.local === x)}>{x}</option>)}</select></div>
      <div><label>Tipo de serviço</label><select name="tipo_servico"><option value="">—</option>{l.lista_tipos_servico.map((t) => <option selected={Boolean(c && c.tipo_servico === t)}>{t}</option>)}</select></div>
      <div><label>Plano (ex.: Pacote 8 aulas, Mensalidade 2x/semana)</label><input name="plano" value={c ? c.plano || "" : ""} list="planos" /><datalist id="planos">{PLANOS_DATALIST.map((x) => <option>{x}</option>)}</datalist></div>
      <div><label>Nº de pessoas no horário</label><input name="pessoas" type="number" min="1" max="4" value={String(c ? c.pessoas || 1 : 1)} /></div>
      <div><label>Valor (R$ por mês, ou do pacote)</label><input name="valor" value={c ? strJinja(c.valor) : ""} /></div>
      <div><label>Forma de pagamento</label><select name="forma_pagamento"><option value="">—</option>{l.lista_formas_venda.map((f) => <option selected={Boolean(c && c.forma_pagamento === f)}>{f}</option>)}
        {c && c.forma_pagamento && !l.lista_formas_venda.includes(c.forma_pagamento) && <option selected>{c.forma_pagamento}</option>}</select></div>
      <div><label>Status</label><select name="status">{["ativo", "pausado", "inativo"].map((s) => <option selected={Boolean(c && c.status === s)}>{s}</option>)}</select></div>
      <div><label>Canal de origem</label><select name="canal_origem"><option value="">—</option>{l.lista_canais.map((k) => <option selected={Boolean(c && c.canal_origem === k)}>{k}</option>)}</select></div>
      <div><label>Indicado por (se alguém indicou)</label><select name="indicado_por" onchange="if (this.value) this.form.elements['canal_origem'].value = 'Indicação'"><option value="">—</option>
        {indicadores.map((a) => <option value={String(a.id)} selected={Boolean(c && c.indicado_por === a.id)}>{a.nome + (a.status !== "ativo" ? ` (${a.status})` : "")}</option>)}</select></div>
      <div><label>Data de início</label><input name="data_inicio" type="date" value={c ? c.data_inicio || "" : hoje()} /></div>
      <div><label>Data de renovação</label><input name="data_renovacao" type="date" value={renova} /></div>
      <div class="largo"><label>Observações</label><textarea name="observacoes" rows={3}>{c ? c.observacoes || "" : ""}</textarea></div>
      <div class="largo"><button>Salvar</button> <a class="btn claro" href="/clientes">Voltar</a></div>
    </form>
  );
}

function TelaNovo({ ctx, indicadores }: { ctx: Contexto; indicadores: Linha[] }): Child {
  return (
    <Base ctx={ctx}>
      <div class="linha topo"><h1 style="margin:0">Novo cliente</h1></div>
      <div class="grid c2">
        <div>
          <div class="card" id="cadastro">
            <h2>Cadastro</h2>
            <FormCadastro ctx={ctx} c={null} renova="" indicadores={indicadores} />
          </div>
        </div>
      </div>
    </Base>
  );
}

function TelaFicha({ ctx, d }: { ctx: Contexto; d: DadosFicha }): Child {
  const c = d.c, cid = c.id as number;
  const renova = String((d.renovacao ? d.renovacao.efetiva : c.data_renovacao) || "");
  const vence = d.renovacao && d.renovacao.vence ? String(d.renovacao.vence) : renova;
  const cred = d.cobranca ? d.cobranca.credito : d.estado ? d.estado.credito : 0;
  const aPagar = d.cobranca ? d.cobranca.total : Math.max(Number(c.valor || 0) - cred, 0);
  let notaPgto = cred ? `Crédito de ${moeda(cred)} descontado` : "";
  if (d.cobranca && (d.cobranca.multa || d.cobranca.juros))
    notaPgto = (notaPgto ? notaPgto + " · " : "") + `multa de ${moeda(d.cobranca.multa)} e juros de ${moeda(d.cobranca.juros)} incluídos`;
  const valorPgto = aPagar ? virgula2(aPagar) : "";
  const mensal = virgula2(Number(c.valor || 0));
  const h = hoje();
  const vIso = dataIso(vence);
  const est = d.estado;
  const texto = est ? est.texto.slice(0, 1).toUpperCase() + est.texto.slice(1) + ("?!.".includes(est.texto.slice(-1)) ? "" : ".") : "";
  return (
    <Base ctx={ctx}>
      <div class="linha topo">
        <h1 style="margin:0">{c.nome}{d.adiantadoAte && <> <a class="tag azul" href="#pagamentos" style="font-size:12px;vertical-align:middle">{`Pago adiantado até ${d.adiantadoAte.slice(5)}/${d.adiantadoAte.slice(0, 4)}`}</a></>}</h1>
        <div class="linha">
          {["ativo", "pausado", "inativo"].filter((s) => s !== c.status).map((s) => (
            <form method="post" action={`/clientes/${cid}/status`} class="inline"><input type="hidden" name="status" value={s} /><button class="claro pequeno">Marcar {s}</button></form>
          ))}
          <details class="menu-wa">
            <summary class="btn claro pequeno">WhatsApp ▾</summary>
            <div class="menu-wa-lista">
              {!c.telefone ? <a class="menu-wa-item" href="#telefone">Cadastre o telefone</a> : (
                <>
                  {d.menu.itens.map((it) => (
                    <form method="post" action={`/clientes/${cid}/wa/${it.modelo}`} target="_blank" class="inline"
                      {...(it.modelo === "cobranca" && d.menu.cobranca ? { "data-cartao": `/clientes/${cid}/cobranca/cartao.svg`, "data-codigo": d.menu.cobranca.codigo } : {})}>
                      <button type="submit" class={`menu-wa-item${it.destaque ? " destaque" : ""}${it.pedido_em ? " feito" : ""}`}>
                        <span>{it.rotulo}{it.sub && <> <small>{it.sub}</small></>}</span>
                        {it.pedido_em && <small>{`pedido em ${it.pedido_em.slice(8, 10)}/${it.pedido_em.slice(5, 7)}`}</small>}
                      </button>
                    </form>
                  ))}
                  {d.menu.depoimento_aberto && <form method="post" action={`/clientes/${cid}/depoimento`} class="inline"><button type="submit" class="menu-wa-item verde-claro">Recebi o depoimento</button></form>}
                </>
              )}
            </div>
          </details>
          <a class="btn claro pequeno" href={`/propostas?cliente_id=${cid}&local=${quoteUrl(c.local || "CIA")}`}>Nova proposta</a>
          <form method="post" action={`/clientes/${cid}/excluir`} class="inline" data-confirmar={`Enviar ${c.nome} para a lixeira?`}><button class="perigo pequeno">Excluir</button></form>
        </div>
      </div>

      {est && (
        <div class={`card borda-${est.cor}`} id="situacao" style="margin-bottom:14px">
          <div class="linha" style="justify-content:space-between"><h2 style="margin:0">Situação</h2><span class={`tag ${est.cor}`}>{est.rotulo}</span></div>
          <p style="margin:8px 0">{texto}</p>
          {est.acoes.length > 0 && <div class="acoes-alerta"><Botoes ctx={ctx} acoes={est.acoes} e={est as never} voltar={`/clientes/${cid}`} /></div>}
        </div>
      )}

      {d.diferenca && (
        <div class="card borda-amarelo" id="diferenca" style="margin-bottom:14px">
          <div class="linha" style="justify-content:space-between"><h2 style="margin:0">Multa e juros</h2><span class="tag amarelo">a receber</span></div>
          <p style="margin:8px 0">{d.diferenca.frase.slice(0, 1).toUpperCase() + d.diferenca.frase.slice(1)}.</p>
          <div class="acoes-alerta"><Botoes ctx={ctx} acoes={d.diferenca.acoes} e={d.diferenca as never} voltar={`/clientes/${cid}`} /></div>
        </div>
      )}

      {d.ofertasFicha.length > 0 && (
        <div class="card" id="ofertas" style="margin-bottom:14px">
          <h2>Ofertas</h2>
          {d.ofertasFicha.map((it) => {
            const o = it.oferta;
            const volta = o.meses_desconto ? proximaRenovacao(h, o.meses_desconto) : "";
            const corTag = ({ nao_enviada: "neutro", enviada: "amarelo", aceitou: "verde", recusou: "vermelho" } as Record<string, string>)[it.status];
            const tag = it.status === "nao_enviada" ? "não enviada" : it.status === "enviada" ? `enviada em ${dataBr(it.data)}`
              : it.status === "aceitou" ? `aceitou em ${dataBr(it.data)}` : `recusou em ${dataBr(it.data)}`;
            return (
              <div class="oferta-item">
                <div class="linha" style="justify-content:space-between;gap:6px 10px">
                  <strong>{o.titulo}</strong>
                  <span class={`tag ${corTag}`}>{tag}</span>
                </div>
                <div class="muted">{`De ${moeda(o.valor_normal)} por ${moeda(o.valor_oferta)}/mês` + (o.meses_desconto ? `, ${o.meses_desconto === 1 ? "no primeiro mês" : `nos primeiros ${o.meses_desconto} meses`}` : "")}</div>
                {it.status === "aceitou" ? (
                  <>
                    <div class="muted">{it.encerrado_em ? `Valor da oferta encerrado em ${dataBr(it.encerrado_em)}: mensalidade em ${moeda(o.valor_normal)}.`
                      : it.ate_desconto ? `Vale até ${dataBr(it.ate_desconto)}; depois volta para ${moeda(o.valor_normal)}.` : "Vale sempre."}</div>
                    {it.ate_desconto && !it.encerrado_em && (
                      <div class="acoes-alerta"><button type="button" class="claro pequeno" data-abrir="dlg-oferta-encerrar" data-acao={`/clientes/${cid}/oferta/${o.id}/encerrar-desconto`}
                        data-titulo={`${c.nome}: a mensalidade volta de ${moeda(c.valor)} para ${moeda(o.valor_normal)}.`} data-voltar={`/clientes/${cid}#ofertas`}>{`Voltar para ${moeda(o.valor_normal)}`}</button></div>
                    )}
                  </>
                ) : (
                  <div class="acoes-alerta">
                    {c.telefone
                      ? <form method="post" action={`/clientes/${cid}/oferta/${o.id}/enviar`} target="_blank" class="inline" onsubmit="setTimeout(function(){location.reload()},1500)"><button class="pequeno">{it.status !== "nao_enviada" ? "Enviar de novo" : "Enviar (WhatsApp)"}</button></form>
                      : <a class="btn claro pequeno" href="#cadastro">Sem telefone: completar</a>}
                    <button type="button" class="verde pequeno" data-abrir="dlg-oferta-aceitou" data-acao={`/clientes/${cid}/oferta/${o.id}/aceitou`} data-titulo={`${c.nome} aceitou: ${o.titulo}`}
                      data-novo={moeda(o.valor_oferta)} data-nota={volta ? `Volta para ${moeda(o.valor_normal)} em ${dataBr(volta)}.` : ""} data-voltar={`/clientes/${cid}#ofertas`}>Aceitou</button>
                    {it.status !== "recusou" && <form method="post" action={`/clientes/${cid}/oferta/${o.id}/recusou`} class="inline"><button class="claro pequeno">Recusou</button></form>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {(d.indicou.length > 0 || d.indicadoPor) && (
        <div class="card" id="indicacoes" style="margin-bottom:14px">
          <h2>Indicações</h2>
          {d.indicadoPor && <p style="margin:8px 0">Indicado por <a href={`/clientes/${d.indicadoPor.id}`}>{d.indicadoPor.nome}</a>.</p>}
          {d.indicou.map((i) => (
            <div class="linha" style="justify-content:space-between;padding:6px 0;border-top:1px solid var(--borda)">
              <span>Indicou: <a href={`/clientes/${i.indicado_id}`}>{i.indicado}</a> —
                {i.status === "pendente" ? <strong>presente pendente</strong> : i.status === "entregue" ? ` presente entregue em ${dataBr(i.data)}` + (i.o_que ? ` (${i.o_que})` : "")
                  : <span class="muted">aguardando o 1º pagamento</span>}</span>
              {i.status === "pendente" && <button type="button" class="verde pequeno" data-abrir="dlg-presente" data-acao={`/clientes/${cid}/indicacao/${i.indicado_id}/presente`}
                data-titulo={`Presente para ${c.nome}, que indicou ${i.indicado}`} data-sugestoes={d.sugestoes} data-voltar={`/clientes/${cid}`}>Registrar presente</button>}
            </div>
          ))}
        </div>
      )}

      <div class="grid c2">
        <div>
          {dataIso(renova) && (
            <div class={`card${d.cobranca ? " borda-vermelho" : ""}`} id="renovacao">
              <h2>Renovação</h2>
              <div class="linha" style="justify-content:space-between"><strong>{dataBr(renova)}</strong>{d.cobranca && <span class="tag vermelho">{`${d.cobranca.dias} dia${d.cobranca.dias !== 1 ? "s" : ""} de atraso`}</span>}</div>
              {d.renovacao && d.renovacao.ciclos > 0 && <p class="muted">{`Andou com ${({ pagamento: "o pagamento", renovacao: "a renovação marcada", pausa: "o mês pulado" } as Record<string, string>)[d.renovacao.motivo!]} de ${dataBr(d.renovacao.motivo_data)} (no cadastro: ${dataBr(String(d.renovacao.gravada))}).`}</p>}
              {d.renovacao && d.renovacao.pendente && <p class="muted">{`Renovação marcada${vIso ? ` (vencimento ${dataBr(vence)})` : ""}, pagamento ainda não lançado: falta ${moeda(Math.max(d.renovacao.falta - (est ? est.credito : 0), 0))}.`}</p>}
              <div class="linha" style="margin:8px 0"><button class="verde pequeno" data-abrir="dlg-pgto" data-titulo={`Registrar pagamento de ${c.nome}`} data-cliente_id={String(cid)} data-valor={valorPgto}
                data-mensal={mensal} {...(notaPgto ? { "data-nota": notaPgto } : {})} data-descricao={`Mensalidade ${vIso ? vIso.slice(5, 7) : h.slice(5, 7)}/${vIso ? vIso.slice(0, 4) : h.slice(0, 4)}`}
                data-voltar={`/clientes/${cid}`}>Registrar pagamento</button><span class="muted">a renovação anda sozinha</span></div>
              {d.cobranca && (
                <p class="muted conta-cobranca">Total atualizado: <strong><span>{moeda(d.cobranca.total)}</span></strong> = saldo <span>{moeda(d.cobranca.valor)}</span>
                  {d.cobranca.credito ? <> (<span>{moeda(d.cobranca.bruto)}</span> − crédito <span>{moeda(d.cobranca.credito)}</span>)</> : null} + multa <span>{moeda(d.cobranca.multa)}</span> + juros <span>{moeda(d.cobranca.juros)}</span></p>
              )}
              {d.menu.cobranca && (
                <div class="cartao-cobranca">
                  <img src={`/clientes/${cid}/cobranca/cartao.svg`} alt={`Cartão de cobrança (${d.menu.cobranca.nome})`} loading="lazy" />
                  {d.menu.cobranca.codigo && <button type="button" class="claro pequeno" data-copiar={d.menu.cobranca.codigo}>Copiar código Pix</button>}
                </div>
              )}
              <form method="post" action={`/clientes/${cid}/evento`} class="linha" data-confirmar={`Pular a renovação de ${dataBr(renova)} sem cobrança?`}>
                <input type="hidden" name="tipo" value="pausa" /><input type="hidden" name="data" value={h} />
                <label for="volta" style="margin:0">Pulou o mês? Volta em</label>
                <input id="volta" name="nova_renovacao" type="date" value={proximaRenovacao(dataIso(renova)!)} style="width:auto" />
                <button class="claro pequeno">Pular sem cobrança</button>
              </form>
            </div>
          )}
          <div class={`card${dataIso(renova) ? " mt" : ""}`} id="cadastro">
            <h2>Cadastro</h2>
            <FormCadastro ctx={ctx} c={c} renova={renova} indicadores={d.indicadores} />
          </div>
          <div class="card mt" id="horarios">
            <h2>Dias e horários fixos</h2>
            {c.status !== "ativo" && <p class="muted">Só aluno ativo tem horário fixo na Agenda.</p>}
            <form method="post" action={`/clientes/${cid}/horarios`}>
              <div class="horarios-lista" data-horarios="">
                {d.horarios.map((f) => (
                  <div class="horario-linha">
                    <select name="dia" aria-label="Dia">{[1, 2, 3, 4, 5, 6].map((n) => <option value={String(n)} selected={n === f.dia}>{DCURTO[n]}</option>)}</select>
                    <select name="hora" aria-label="Hora">{Array.from({ length: 19 }, (_, i) => i + 5).map((x) => <option value={String(x)} selected={x === f.hora}>{String(x).padStart(2, "0")}h</option>)}</select>
                    <select name="local" aria-label="Local">{d.locais.map((l) => <option selected={l === f.local}>{l}</option>)}{!d.locais.includes(f.local) && <option selected>{f.local}</option>}</select>
                    <button type="button" class="claro pequeno" data-tirar-horario="" aria-label="Remover este horário" title="Remover">✕</button>
                  </div>
                ))}
              </div>
              <template data-modelo-horario="">
                <div class="horario-linha">
                  <select name="dia" aria-label="Dia">{[1, 2, 3, 4, 5, 6].map((n) => <option value={String(n)}>{DCURTO[n]}</option>)}</select>
                  <select name="hora" aria-label="Hora">{Array.from({ length: 19 }, (_, i) => i + 5).map((x) => <option value={String(x)} selected={x === 7}>{String(x).padStart(2, "0")}h</option>)}</select>
                  <select name="local" aria-label="Local">{d.locais.map((l) => <option selected={l === c.local}>{l}</option>)}</select>
                  <button type="button" class="claro pequeno" data-tirar-horario="" aria-label="Remover este horário" title="Remover">✕</button>
                </div>
              </template>
              {!d.horarios.length && <p class="muted" data-sem-horario="">{"Sem horário fixo na Agenda." + (c.dias_horarios ? ` Texto antigo: "${c.dias_horarios}".` : "")}</p>}
              <div class="linha mt">
                <button type="button" class="claro" data-mais-horario="" disabled={c.status !== "ativo"}>+ adicionar dia e horário</button>
                <button disabled={c.status !== "ativo"}>Salvar horários</button>
              </div>
              <p class="muted" style="margin:6px 0 0">{`Grava direto na Agenda (e a Grade acompanha). Cabem ${d.max} alunos por horário (Configurações > Agenda). Reposições e aulas avulsas ficam na Agenda.`}</p>
            </form>
            <script dangerouslySetInnerHTML={{ __html: SCRIPT_HORARIOS }} />
          </div>
        </div>

        <div>
          {d.estimativa && (
            <div class={`card borda-${corMargem(d.estimativa.margem)}`}>
              <h2>Rentabilidade estimada</h2>
              <div class="linha" style="gap:24px">
                <div><div class="muted">Lucro / mês</div><strong>{moeda(d.estimativa.lucro)}</strong></div>
                <div><div class="muted">Margem</div><strong>{pct(d.estimativa.margem, 1)}</strong></div>
                <div><div class="muted">Lucro / hora</div><strong>{moeda(d.estimativa.lucro_hora)}</strong></div>
                <div><div class="muted">Preço mínimo</div><strong>{moeda(d.estimativa.preco_minimo)}</strong></div>
              </div>
              <div class="muted mt" style="margin-top:8px">{`Base: ${num(d.estimativa.sessoes, 0)} sessões/mês, custos do plano equivalente na planilha.`}</div>
            </div>
          )}

          <div class="card mt">
            <h2>Registrar no histórico</h2>
            <p><a href={`/agenda?aluno=${cid}`}>Aulas: marque na Agenda.</a></p>
            <form method="post" action={`/clientes/${cid}/evento`} class="form-grid">
              <input type="hidden" name="tipo" value="anotacao" />
              <div><label>Data</label><input name="data" type="date" value={h} required /></div>
              <div class="largo"><label>Anotação</label><input name="descricao" placeholder="O que aconteceu?" required /></div>
              <div class="largo"><button>Registrar anotação</button></div>
            </form>
          </div>

          <div class="card mt">
            <h2>Histórico</h2>
            {d.eventos.length ? d.eventos.map((e) => (
              <div class="linha" style="justify-content:space-between;border-bottom:1px solid var(--borda);padding:6px 0">
                <span><span class={`tag ${TAG_EVENTO[e.tipo]}`}>{NOME_EVENTO[e.tipo] ?? e.tipo}</span>{` ${e.descricao || ""}`}{e.tipo === "credito" && e.usado_em && <> <span class="muted">{`(já descontado em ${dataBr(e.usado_em)})`}</span></>}</span>
                <div class="linha" style="gap:8px"><span class="muted">{dataBr(e.data) + (e.valor ? ` · ${moeda(e.valor)}` : "")}</span>
                  <form method="post" action={`/agenda/evento/${e.id}/excluir`} class="inline" data-confirmar="Excluir este registro do histórico? Dá para restaurar em Dados."><input type="hidden" name="destino" value="ficha" /><button class="claro pequeno">excluir</button></form></div>
              </div>
            )) : <p class="muted">Nada registrado ainda.</p>}
          </div>

          <div class="card mt" id="pagamentos">
            <div class="linha topo" style="margin-bottom:8px"><h2 style="margin:0">Pagamentos</h2>
              <button class="verde pequeno" data-abrir="dlg-pgto" data-titulo={`Registrar pagamento de ${c.nome}`} data-cliente_id={String(cid)} data-valor={valorPgto} data-mensal={mensal}
                {...(notaPgto ? { "data-nota": notaPgto } : {})} data-descricao={`Mensalidade ${h.slice(5, 7)}/${h.slice(0, 4)}`} data-voltar={`/clientes/${cid}`}>Registrar pagamento</button></div>
            {d.adiantadoAte && <p style="margin:0 0 8px"><span class="tag azul">{`Pago adiantado até ${d.adiantadoAte.slice(5)}/${d.adiantadoAte.slice(0, 4)}`}</span> <span class="muted">Pagou vários meses de uma vez. Depois disso volta a pagar por mês (venda nova é só mensal).</span></p>}
            <p style="margin:0 0 8px">{d.pagoAte ? <>Pago até <strong>{d.pagoAte}</strong></> : <span class="muted">Sem pagamento registrado</span>}
              {d.renovacao && dataIso(d.renovacao.efetiva) && <> · próxima renovação <strong>{dataBr(String(d.renovacao.efetiva))}</strong></>}</p>
            {d.pagamentos.length ? d.pagamentos.map((p) => (
              <div style="padding:4px 0">
                <div class="linha" style="justify-content:space-between"><span>{p.descricao || p.categoria} <span class={`tag ${p.pago_em ? "verde" : "amarelo"}`}>{p.pago_em ? "pago" : "pendente"}</span>{p.meses && p.meses > 1 && <> <span class="tag azul">{`cobre ${p.meses} meses`}</span></>}</span><span class="muted">{dataBr(p.data)} · <span class={`v-${p.tipo}`}>{moeda(p.valor)}</span></span></div>
                {p.pago_em && p.tipo === "entrada" && p.escopo === "PJ" && (
                  <form method="post" action={`/financeiro/lancamento/${p.id}/meses`} class="linha" style="margin-top:4px"><input type="hidden" name="cliente_id" value={String(cid)} /><input type="hidden" name="voltar" value={`/clientes/${cid}#pagamentos`} />
                    <label class="muted" for={`meses-${p.id}`} style="margin:0">Cobre</label>
                    <select id={`meses-${p.id}`} name="meses" style="width:auto">{Array.from({ length: 24 }, (_, i) => i + 1).map((n) => <option value={String(n)} selected={n === (p.meses || 1)}>{`${n} ${n === 1 ? "mês" : "meses"}`}</option>)}</select>
                    <button class="claro pequeno">Salvar</button></form>
                )}
              </div>
            )) : <p class="muted">Nenhum lançamento financeiro deste aluno. Use Registrar pagamento para lançar o primeiro.</p>}
            {est && est.credito_total ? <p style="margin:0 0 8px">Crédito disponível <strong>{moeda(est.credito_total)}</strong> <span class="muted">· sai sozinho do próximo pagamento</span></p> : null}
            <p class="muted" style="margin:8px 0 0"><a href="/financeiro/mensalidades">Mensalidades</a></p>
          </div>

          {d.propostas.length > 0 && (
            <div class="card mt"><h2>Propostas</h2>
              {d.propostas.map((p) => <div class="linha" style="justify-content:space-between;padding:4px 0"><span>{`#${p.id} ${p.tipo_servico} · ${moeda(p.preco_total)} · margem ${pct(p.margem)}`}</span><span class="tag neutro">{p.status}</span></div>)}
            </div>
          )}
        </div>
      </div>
    </Base>
  );
}

// ---------- rotas ----------
function formCliente(f: Record<string, string>): Record<string, unknown> {
  const d: Record<string, unknown> = Object.fromEntries(CAMPOS_CLIENTE.map((k) => [k, f[k] || null]));
  d.pessoas = d.pessoas ? intPy(String(d.pessoas)) : 1;
  d.valor = numBr(d.valor);
  d.status = d.status || "ativo";
  return d;
}

export function rotasClientes(app: Hono<Ambiente>): void {
  app.get("/clientes", async (c) => {
    const b = banco(c);
    const [ctx, d] = await Promise.all([contextoBase(b, c.req.raw), lista(b, new URL(c.req.url))]);
    return c.html(String(<TelaLista ctx={ctx} d={d} />));
  });

  app.get("/clientes/novo", async (c) => {
    const b = banco(c);
    const [ctx, indicadores] = await Promise.all([contextoBase(b, c.req.raw), alunosParaEscolher(b)]);
    return c.html(String(<TelaNovo ctx={ctx} indicadores={indicadores} />));
  });

  app.post("/clientes", async (c) => {
    const b = banco(c);
    const d = formCliente(await formulario(c));
    if (!d.nome) return voltar(c, "/clientes/novo", null, "Informe o nome.");
    const [iid, erro] = await validarIndicacao(b, d.indicado_por);
    if (erro) return voltar(c, "/clientes/novo", null, erro);
    d.indicado_por = iid;
    if (iid) d.canal_origem = CANAL;
    const ja = await b.um(`SELECT id FROM clientes WHERE excluido_em IS NULL AND criado_em >= datetime('now','localtime','-60 seconds') AND nome IS ? AND telefone IS ?
      ORDER BY id DESC`, [d.nome as string, d.telefone as string | null]);
    if (ja) return voltar(c, `/clientes/${ja.id}`, "Esse cliente já tinha sido cadastrado agora há pouco: não criei outro.");
    const g = await b.run(`INSERT INTO clientes (${CAMPOS_CLIENTE.join(",")}) VALUES (${CAMPOS_CLIENTE.map(() => "?").join(",")})`,
      CAMPOS_CLIENTE.map((k) => d[k] as string | number | null));
    return voltar(c, `/clientes/${g.id}`, "Cliente cadastrado.");
  });

  app.get("/clientes/:cid{[0-9]+}", async (c) => {
    const b = banco(c);
    const cid = Number(c.req.param("cid"));
    const cli = await b.um("SELECT * FROM clientes WHERE id=?", [cid]);
    if (!cli) return voltar(c, "/clientes", null, "Cliente não encontrado.");
    const [ctx, d] = await Promise.all([contextoBase(b, c.req.raw), dadosFicha(b, cli)]);
    return c.html(String(<TelaFicha ctx={ctx} d={d} />));
  });

  app.post("/clientes/:cid{[0-9]+}/wa/:modelo", async (c) => {
    const b = banco(c);
    const cid = Number(c.req.param("cid")), modelo = c.req.param("modelo");
    const [cli, modelos] = await Promise.all([b.um("SELECT * FROM clientes WHERE id=? AND excluido_em IS NULL", [cid]), parametros(b, "msg_whatsapp")]);
    if (!cli) return voltar(c, "/clientes", null, "Cliente não encontrado.");
    if (!(modelo in modelos)) return c.text("Mensagem desconhecida.", 404);
    if (!/\d/.test(String(cli.telefone ?? ""))) return voltar(c, `/clientes/${cid}`, null, "Cadastre o telefone para abrir o WhatsApp.");
    const [texto, erro] = await waTexto(b, cli, modelo, hoje());
    if (erro) return voltar(c, `/clientes/${cid}`, null, erro);
    let rotulo = waRotulo(modelo);
    if (modelo === "cobranca") rotulo += ` (${(await cobrancaAtualDe(b, cli, await waContexto(b, cli, hoje()), hoje()))!.nome})`;
    await b.run("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'mensagem', ?, ?)", [cid, hoje(), "WhatsApp: " + rotulo]);
    return c.redirect(wa(cli.telefone, texto!), 303);
  });

  app.get("/clientes/:cid{[0-9]+}/diferenca/cartao.svg", async (c) => {
    const b = banco(c);
    const cid = Number(c.req.param("cid"));
    const cli = await b.um("SELECT * FROM clientes WHERE id=? AND excluido_em IS NULL", [cid]);
    const itens = cli ? (await diferencas(b, cid)).get(cid) : undefined;
    if (!itens) return c.text("Sem diferença de multa e juros em aberto.", 404);
    const [dados, modelos] = await Promise.all([dadosMensagem(b), parametros(b, "msg_whatsapp")]);
    return c.body(svg(diferencaCartao(cli as never, itens, dados, modelos)), 200, { "content-type": "image/svg+xml", "cache-control": "no-store" });
  });

  app.get("/clientes/:cid{[0-9]+}/cobranca/cartao.svg", async (c) => {
    const b = banco(c);
    const cid = Number(c.req.param("cid"));
    const cli = await b.um("SELECT * FROM clientes WHERE id=? AND excluido_em IS NULL", [cid]);
    const ca = cli ? await cobrancaAtualDe(b, cli, await waContexto(b, cli, hoje()), hoje()) : null;
    if (!ca) return c.text("Sem cobrança em aberto.", 404);
    return c.body(svg(ca, await parametros(b, "cobranca")), 200, { "content-type": "image/svg+xml", "cache-control": "no-store" });
  });

  app.post("/clientes/:cid{[0-9]+}/depoimento", async (c) => {
    const b = banco(c);
    const cid = Number(c.req.param("cid"));
    const f = await formulario(c);
    if (!(await b.um("SELECT 1 AS um FROM clientes WHERE id=? AND excluido_em IS NULL", [cid]))) return voltar(c, "/clientes", null, "Cliente não encontrado.");
    await b.run("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'depoimento', ?, ?)", [cid, hoje(), (f.descricao ?? "").trim() || "Depoimento recebido"]);
    return voltar(c, `/clientes/${cid}`, "Depoimento registrado. Obrigado!");
  });

  app.post("/alunos/:cid{[0-9]+}/credito", async (c) => {
    const b = banco(c);
    const cid = Number(c.req.param("cid"));
    const f = await formulario(c);
    const url = caminhoSeguro(f.voltar) || `/clientes/${cid}`;
    let v: number | null = null;
    try {
      v = (f.valor ?? "").trim() ? numBr(f.valor) : null;
    } catch (e) {
      if (e instanceof ErroValor) return voltar(c, url, null, "Valor inválido.");
      throw e;
    }
    const [msg, erro] = await darCredito(b, cid, v, (f.mes ?? "").trim() || null, hoje());
    return voltar(c, url, msg, erro);
  });

  app.post("/clientes/:cid{[0-9]+}/consultoria", async (c) => {
    const b = banco(c);
    const cid = Number(c.req.param("cid"));
    const f = await formulario(c);
    let url = caminhoSeguro(f.voltar);
    url = url.startsWith("/clientes") ? url : "/clientes";
    const tipo = f.tipo_servico ?? "";
    if (!TIPOS_SEM_AULA.includes(tipo)) return voltar(c, url, null, "Escolha Consultoria Online ou Consultoria Híbrida.");
    const cli = await b.um("SELECT nome FROM clientes WHERE id=? AND excluido_em IS NULL", [cid]);
    if (!cli) return voltar(c, url, null, "Aluno não encontrado.");
    await b.run("UPDATE clientes SET tipo_servico=?, atualizado_em=datetime('now','localtime') WHERE id=?", [tipo, cid]);
    return voltar(c, url, `${cli.nome}: ${tipo}.`);
  });

  app.post("/clientes/:cid{[0-9]+}/excluir", async (c) => {
    await banco(c).run("UPDATE clientes SET excluido_em=datetime('now','localtime') WHERE id=?", [Number(c.req.param("cid"))]);
    return voltar(c, "/clientes", "Cliente enviado para a lixeira (restaurável em Dados).");
  });

  app.post("/clientes/:cid{[0-9]+}/indicacao/:iid{[0-9]+}/presente", async (c) => {
    const b = banco(c);
    const cid = Number(c.req.param("cid")), iid = Number(c.req.param("iid"));
    const f = await formulario(c);
    const url = caminhoSeguro(f.voltar) || `/clientes/${cid}`;
    let v: number | null = null;
    try {
      v = (f.custo ?? "").trim() ? numBr(f.custo) : null;
    } catch (e) {
      if (e instanceof ErroValor) return voltar(c, url, null, "Custo inválido: use só números, como 35,90.");
      throw e;
    }
    const [msg, erro] = await registrarPresente(b, cid, iid, f.o_que ?? "", dataIso(f.data) || hoje(), v || null);
    return voltar(c, url, msg, erro);
  });

  app.post("/clientes/:cid{[0-9]+}/oferta/:oid{[0-9]+}/enviar", async (c) => {
    const b = banco(c);
    const cid = Number(c.req.param("cid")), oid = Number(c.req.param("oid"));
    const f = await formulario(c);
    const modelo = (await parametros(b, "msg_whatsapp")).upsell as string | undefined;
    const [link, erro] = await ofertas.registrarEnvio(b, cid, oid, modelo ?? null, hoje());
    if (erro) return voltar(c, caminhoSeguro(f.voltar) || `/clientes/${cid}#ofertas`, null, erro);
    return c.redirect(link!, 303);
  });

  for (const [acao, fazer] of [
    ["aceitou", (b: Banco, cid: number, oid: number, f: Record<string, string>) => ofertas.aceitou(b, cid, oid, Boolean(f.atualizar), hoje())],
    ["recusou", (b: Banco, cid: number, oid: number) => ofertas.recusou(b, cid, oid, hoje())],
    ["encerrar-desconto", (b: Banco, cid: number, oid: number) => ofertas.encerrarDesconto(b, cid, oid, hoje())],
  ] as [string, (b: Banco, cid: number, oid: number, f: Record<string, string>) => Promise<[string | null, string | null]>][]) {
    app.post(`/clientes/:cid{[0-9]+}/oferta/:oid{[0-9]+}/${acao}`, async (c) => {
      const cid = Number(c.req.param("cid")), oid = Number(c.req.param("oid"));
      const f = await formulario(c);
      const [msg, erro] = await fazer(banco(c), cid, oid, f);
      return voltar(c, caminhoSeguro(f.voltar) || `/clientes/${cid}#ofertas`, msg, erro);
    });
  }
}

export { capitalizar };
