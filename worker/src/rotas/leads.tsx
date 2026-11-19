/** Leads: o funil (kanban), novo lead, editar, mudar de etapa (virar aluno) e lixeira. Port de main.py (leads, lead_*). */
import type { Context, Hono } from "hono";
import type { Child } from "hono/jsx";
import { banco, type Ambiente } from "../app.ts";
import type { Linha } from "../banco/tipos.ts";
import { capitalizar, dataBr, moeda, preencher, wa } from "../formato.ts";
import { diasParado, ETAPAS, motivosPerda, previsaoFunil } from "../regras/ficha.ts";
import { alunosParaEscolher, CANAL, validar } from "../regras/indicacoes.ts";
import { relogioMes } from "../regras/mes.ts";
import { parametros } from "../regras/parametros.ts";
import { Base } from "../telas/Base.tsx";
import { contextoBase, type Contexto } from "../telas/contexto.ts";
import { voltar } from "./util.ts";

const NOME_ETAPA = Object.fromEntries(ETAPAS);
const ORDEM = ["lead", "conversa", "avaliacao", "cliente"];

async function formulario(c: Context<Ambiente>): Promise<Record<string, string>> {
  const corpo = await c.req.parseBody();
  return Object.fromEntries(Object.entries(corpo).map(([k, v]) => [k, typeof v === "string" ? v : ""]));
}

interface Lead extends Linha { atrasado: boolean; dias: number | null; parado: boolean }

function Tela({ ctx, colunas, destaque, previsao, motivos, indicadores }: { ctx: Contexto; colunas: Record<string, Lead[]>; destaque: string;
  previsao: Awaited<ReturnType<typeof previsaoFunil>>; motivos: Linha[]; indicadores: Linha[] }): Child {
  return (
    <Base ctx={ctx}>
      <div class="linha topo">
        <h1 style="margin:0">Funil de vendas</h1>
        <button data-abrir="dlg-lead" data-titulo="Novo lead">Novo lead</button>
      </div>
      {previsao.ticket && previsao.leads ? <p class="muted">{`Receita provável dos leads em aberto: ${moeda(previsao.receita)}/mês (${previsao.leads} leads em aberto, cada um pesado pela chance de fechar da sua etapa, x ticket médio ${moeda(previsao.ticket)})`}</p> : null}
      <div class="kanban">
        {ETAPAS.map(([chave, nome]) => (
          <div class={`coluna ${chave}`}>
            <h3>{nome} <span>{colunas[chave].length}</span></h3>
            {colunas[chave].length ? colunas[chave].map((l) => {
              const chegou = destaque === String(l.id);
              const prox = ORDEM.includes(chave) && chave !== "cliente" ? ORDEM[ORDEM.indexOf(chave) + 1] : null;
              const indicador = l.indicado_por ? indicadores.filter((a) => a.id === l.indicado_por).map((a) => a.nome).join("") : "";
              return (
                <div class={`lead ${l.atrasado ? "atrasado" : ""} ${l.parado ? "parado" : ""} ${chegou ? "chegou" : ""} ${chave === "cliente" && chegou ? "cliente" : ""}`}>
                  <div class="nome">{l.nome}</div>
                  <div class="muted">{l.canal_origem + (l.interesse ? ` · ${l.interesse}` : "")}</div>
                  {l.indicado_por && <div class="muted">{`Indicado por ${indicador}`}</div>}
                  {l.telefone && <div class="muted"><a href={wa(l.telefone, chave === "perdido" ? preencher(String(ctx.modelos.reativacao ?? ""), l.nome, "", { ...ctx.dadosMsg }) : "")} target="_blank" rel="noopener">{l.telefone}</a></div>}
                  {(l.proxima_acao || l.data_proxima_acao) && <div style="margin-top:4px"><span class={`tag ${l.atrasado ? "vermelho" : "azul"}`}>{`${l.proxima_acao || "Próxima ação"} · ${dataBr(l.data_proxima_acao)}`}</span></div>}
                  {l.parado && <div style="margin-top:4px"><span class="tag vermelho">{`parado há ${l.dias} dias`}</span></div>}
                  {l.motivo_perda && <div class="muted">{`Motivo: ${l.motivo_perda}`}</div>}
                  {l.cliente_id && <div><a href={`/clientes/${l.cliente_id}`}>Ver cliente</a></div>}
                  <div class="acoes">
                    {prox && <form method="post" action={`/leads/${l.id}/etapa`} class="inline"><input type="hidden" name="etapa" value={prox} /><button class="verde">{`→ ${NOME_ETAPA[prox]}`}</button></form>}
                    {!["cliente", "perdido"].includes(chave) && <button class="perigo" data-abrir="dlg-perdido" data-acao={`/leads/${l.id}/etapa`} data-id={String(l.id)} data-titulo={`Perder ${l.nome}`}>Perdido</button>}
                    {chave === "perdido" && <form method="post" action={`/leads/${l.id}/etapa`} class="inline"><input type="hidden" name="etapa" value="lead" /><button class="claro">Reabrir</button></form>}
                    <button class="claro" data-abrir="dlg-lead" data-acao={`/leads/${l.id}`} data-titulo="Editar lead" data-id={String(l.id)} data-nome={l.nome} data-telefone={l.telefone || ""}
                      data-canal_origem={l.canal_origem ?? "None"} data-indicado_por={l.indicado_por ? String(l.indicado_por) : ""} data-interesse={l.interesse || ""} data-proxima_acao={l.proxima_acao || ""}
                      data-data_proxima_acao={l.data_proxima_acao || ""} data-observacoes={l.observacoes || ""}>Editar</button>
                    <a class="btn claro" style="padding:4px 8px;font-size:11px" href={`/propostas?lead_id=${l.id}`}>Proposta</a>
                    <form method="post" action={`/leads/${l.id}/excluir`} class="inline" data-confirmar="Enviar este lead para a lixeira?"><button class="claro">x</button></form>
                  </div>
                </div>
              );
            }) : chave === "lead" ? (
              <>
                <p class="muted">Nenhum lead novo. Cadastre quem chamou no WhatsApp ou Instagram para acompanhar até virar cliente.</p>
                <button class="claro pequeno" data-abrir="dlg-lead" data-titulo="Novo lead">Novo lead</button>
              </>
            ) : <p class="muted">{`Ninguém nesta etapa${chave !== "perdido" ? ". Avance um lead com o botão → do card" : ""}.`}</p>}
          </div>
        ))}
      </div>
      {motivos.length > 0 && (
        <div class="card">
          <h3>Por que perco leads</h3>
          {motivos.map((m) => <div class="linha"><span>{capitalizar(String(m.m))}</span><span class="muted">{m.n}</span></div>)}
        </div>
      )}
      <dialog id="dlg-lead">
        <h2 data-titulo="">Novo lead</h2>
        <form method="post" action="/leads" id="form-lead">
          <input type="hidden" name="id" value="" />
          <div class="campo"><label>Nome</label><input name="nome" required /></div>
          <div class="campo"><label>Telefone / WhatsApp</label><input name="telefone" /></div>
          <div class="campo"><label>Canal de origem (obrigatório)</label><select name="canal_origem" required>{ctx.listas.lista_canais.map((k) => <option>{k}</option>)}</select></div>
          <div class="campo"><label>Indicado por (se alguém indicou)</label><select name="indicado_por" onchange="if (this.value) this.form.elements['canal_origem'].value = 'Indicação'"><option value="">—</option>
            {indicadores.map((a) => <option value={String(a.id)}>{a.nome + (a.status !== "ativo" ? ` (${a.status})` : "")}</option>)}</select></div>
          <div class="campo"><label>Interesse (tipo / local)</label><input name="interesse" placeholder="ex.: Pacote de Aulas / CIA" list="interesses" /><datalist id="interesses">
            {ctx.listas.lista_tipos_servico.flatMap((t) => ctx.listas.lista_locais.map((l) => <option>{`${t} / ${l}`}</option>))}</datalist></div>
          <div class="campo"><label>Próxima ação</label><input name="proxima_acao" placeholder="ex.: mandar mensagem, marcar avaliação" /></div>
          <div class="campo"><label>Data da próxima ação</label><input name="data_proxima_acao" type="date" /></div>
          <div class="campo"><label>Observações</label><textarea name="observacoes" rows={2}></textarea></div>
          <div class="linha"><button>Salvar</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
        </form>
      </dialog>
      <dialog id="dlg-perdido">
        <h2 data-titulo="">Marcar como perdido</h2>
        <form method="post" action="/leads">
          <input type="hidden" name="id" value="" /><input type="hidden" name="etapa" value="perdido" />
          <div class="campo"><label>Motivo</label><select name="motivo_perda">{["Preço", "Horário", "Local", "Sem resposta", "Escolheu outro personal", "Desistiu", "Outro"].map((m) => <option>{m}</option>)}</select></div>
          <div class="linha"><button class="perigo">Confirmar</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
        </form>
      </dialog>
    </Base>
  );
}

export function rotasLeads(app: Hono<Ambiente>): void {
  app.get("/leads", async (c) => {
    const b = banco(c);
    const h = relogioMes.hoje();
    const [ctx, rows, limites, previsao, motivos, indicadores] = await Promise.all([contextoBase(b, c.req.raw),
      b.query("SELECT * FROM leads WHERE excluido_em IS NULL ORDER BY data_proxima_acao IS NULL, data_proxima_acao, id DESC"),
      parametros(b, "lead_parado_dias"), previsaoFunil(b), motivosPerda(b), alunosParaEscolher(b)]);
    const colunas: Record<string, Lead[]> = Object.fromEntries(ETAPAS.map(([e]) => [e, []]));
    for (const l of rows) {
      const atrasado = Boolean(l.data_proxima_acao && l.data_proxima_acao < h && !["cliente", "perdido"].includes(l.etapa));
      const parado = diasParado(l, h, limites);
      colunas[l.etapa].push({ ...l, atrasado, dias: parado, parado: Boolean(parado) });
    }
    const destaque = c.req.query("destaque") ?? "None";
    return c.html(String(<Tela ctx={ctx} colunas={colunas} destaque={destaque} previsao={previsao} motivos={motivos} indicadores={indicadores} />));
  });

  app.post("/leads", async (c) => {
    const b = banco(c);
    const f = await formulario(c);
    if (f.nome === undefined || f.canal_origem === undefined) return c.text("Campo obrigatório faltando", 422);
    const [indicador, erro] = await validar(b, f.indicado_por ?? "");
    if (erro) return voltar(c, "/leads", null, erro);
    const h = relogioMes.hoje();
    const g = await b.run(`INSERT INTO leads (nome, telefone, canal_origem, interesse, proxima_acao, data_proxima_acao, observacoes, indicado_por,
      data_entrada, data_mudanca_etapa) VALUES (?,?,?,?,?,?,?,?,?,?)`,
      [f.nome, f.telefone || null, indicador ? CANAL : f.canal_origem, f.interesse || null, f.proxima_acao || null, f.data_proxima_acao || null,
        f.observacoes || null, indicador, h, h]);
    await b.run("INSERT INTO lead_etapas_log (lead_id, etapa) VALUES (?, 'lead')", [g.id]);
    return voltar(c, "/leads", "Lead adicionado.");
  });

  app.post("/leads/:lid{[0-9]+}", async (c) => {
    const b = banco(c);
    const lid = Number(c.req.param("lid"));
    const f = await formulario(c);
    if (f.nome === undefined || f.canal_origem === undefined) return c.text("Campo obrigatório faltando", 422);
    const antigo = await b.um("SELECT cliente_id FROM leads WHERE id=?", [lid]);
    const [indicador, erro] = await validar(b, f.indicado_por ?? "", antigo ? antigo.cliente_id : null);
    if (erro) return voltar(c, "/leads", null, erro);
    await b.run(`UPDATE leads SET nome=?, telefone=?, canal_origem=?, interesse=?, proxima_acao=?, data_proxima_acao=?,
      observacoes=?, indicado_por=?, atualizado_em=datetime('now','localtime') WHERE id=?`,
      [f.nome, f.telefone || null, indicador ? CANAL : f.canal_origem, f.interesse || null, f.proxima_acao || null, f.data_proxima_acao || null,
        f.observacoes || null, indicador, lid]);
    return voltar(c, "/leads", "Lead salvo.");
  });

  app.post("/leads/:lid{[0-9]+}/etapa", async (c) => {
    const b = banco(c);
    const lid = Number(c.req.param("lid"));
    const f = await formulario(c);
    const etapa = f.etapa ?? "";
    const l = await b.um("SELECT * FROM leads WHERE id=?", [lid]);
    if (!l || !(etapa in NOME_ETAPA)) return voltar(c, "/leads", null, "Etapa inválida.");
    const h = relogioMes.hoje();
    const vira = etapa === "cliente" && !l.cliente_id;
    const partes = String(l.interesse || "").split("/");
    await b.batch([   // tudo numa transação, como o "with con" do Python
      { sql: "UPDATE leads SET etapa=?, motivo_perda=?, data_mudanca_etapa=? WHERE id=?", params: [etapa, etapa === "perdido" ? f.motivo_perda || null : null, h, lid] },
      { sql: "INSERT INTO lead_etapas_log (lead_id, etapa) VALUES (?, ?)", params: [lid, etapa] },
      ...(vira ? [
        { sql: `INSERT INTO clientes (nome, telefone, canal_origem, observacoes, lead_id, tipo_servico, local, indicado_por, data_inicio) VALUES (?,?,?,?,?,?,?,?,?)`,
          params: [l.nome, l.telefone, l.canal_origem, l.observacoes, lid, partes[0].trim() || null, partes.length > 1 ? partes[1].trim() : null, l.indicado_por, h] },
        { sql: "UPDATE leads SET cliente_id=last_insert_rowid() WHERE id=?", params: [lid] },
      ] : []),
    ]);
    return voltar(c, `/leads?destaque=${lid}`, vira ? `Novo aluno: ${l.nome}` : "Etapa atualizada.");
  });

  app.post("/leads/:lid{[0-9]+}/excluir", async (c) => {
    await banco(c).run("UPDATE leads SET excluido_em=datetime('now','localtime') WHERE id=?", [Number(c.req.param("lid"))]);
    return voltar(c, "/leads", "Lead enviado para a lixeira.");
  });
}
