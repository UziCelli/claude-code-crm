/** Grade semanal (port de app/main.py: /grade, /grade/multiplicadores, /grade/slot, /grade/passar-para-agenda; tela grade.html). */
import type { Context, Hono } from "hono";
import { raw } from "hono/html";
import type { Child } from "hono/jsx";
import { banco, type Ambiente } from "../app.ts";
import type { Banco } from "../banco/banco.ts";
import type { Linha } from "../banco/tipos.ts";
import { arred } from "../arred.ts";
import { moeda, num, pct } from "../formato.ts";
import { avisoDeslocamento, GravaAgenda, maxAlunos, nomesCurtos, quando, TIPOS_GRADE } from "../regras/agenda.ts";
import { DIAS } from "../regras/ficha.ts";
import { bloqueiosGerais, ciaAtual, planoReferencia, soNaGrade, type CustosLocal, type SoNaGrade } from "../regras/grade.ts";
import { ehCia } from "../regras/locais.ts";
import { lista } from "../regras/parametros.ts";
import { calcular, carregarParametros, corMargem, decompor, HORAS_GRADE, multHorario, PLANOS, type BaseMotor } from "../regras/precos.ts";
import { relogioMes } from "../regras/mes.ts";
import { fixosAtuais as fixosAtuaisDe } from "../regras/trabalho.ts";
import { Base } from "../telas/Base.tsx";
import { contextoBase, type Contexto } from "../telas/contexto.ts";
import { DlgLocal } from "../telas/DlgLocal.tsx";
import { intPy, numBr, quoteUrl, voltar } from "./util.ts";
import { SCRIPT_GRADE } from "./grade-script.ts";

const hoje = () => relogioMes.hoje();
const h2 = (h: number) => String(h).padStart(2, "0");
/** ('%.2f'|format(v or 0))|replace('.', ','). */
const f2 = (v: unknown) => num(Number(v) || 0, 2);
const plural = (n: number, um: string, varios: string) => `${n} ${n === 1 ? um : varios}`;

interface Celula extends Linha { multiplicador: number; preco_aula: number | null; margem: number | null; preco_total: number | null; lucro: number | null;
  outro_local: string | null; vagas: number | null; apagado: boolean; ids: number[] }

interface DadosGrade {
  celulas: Map<string, Celula>; minima: number; tipo: string; local: string; vale: number; locais: string[]; maxAlunos: number; soGrade: SoNaGrade[];
  clientes: Linha[]; base: BaseMotor; resumo: { livres: number; ocupados: number; vale: number }; refs: number[]; refAtual: number;
  custosLocal: CustosLocal | Linha; mults: Map<number, number>; comparar: (ReturnType<typeof decompor> & { local: string })[]; cia: boolean; refGrade: number;
}

async function dados(b: Banco, tipo: string, local: string, vale: number, ref: number): Promise<DadosGrade> {
  const [slots, p, mults, gerais, locaisLista, locaisGrade, clientes, cabe, soGrade, cia] = await Promise.all([
    b.query("SELECT * FROM grade_slots WHERE tipo_calculo=? AND local=? AND dia BETWEEN 1 AND 6", [tipo, local]),
    carregarParametros(b), multHorario(b), bloqueiosGerais(b), lista(b, "lista_locais"),
    b.query<{ local: string }>("SELECT DISTINCT local FROM grade_slots ORDER BY local"),
    b.query("SELECT id, nome FROM clientes WHERE excluido_em IS NULL AND status='ativo' ORDER BY nome"),
    maxAlunos(b), soNaGrade(b), ehCia(local) ? ciaAtual(b) : Promise.resolve(null),
  ]);
  const base = planoReferencia(tipo, local, ref);
  const [col, servico] = tipo === "Mensalidades" ? ["freq_semanal", "Mensalidade"] as const : ["qtd_aulas", "Pacote de Aulas"] as const;
  const refs = [...new Set([...PLANOS.filter(([t]) => t === servico).map(([, q, fr]) => (servico === "Pacote de Aulas" ? q : fr)), ...(ref ? [ref] : [])])]
    .sort((x, y) => x - y);
  const minima = base.tipo_servico in p.margens ? p.margens[base.tipo_servico] : 0.15;   // as cores seguem a margem mínima do plano
  const precosHora = new Map<number, ReturnType<typeof calcular>>();   // o preço só depende do multiplicador da hora
  const celulas = new Map<string, Celula>();
  for (const s of slots) {
    const cel: Celula = { ...s, multiplicador: mults.get(s.hora) ?? 1.0, preco_aula: null, margem: null, preco_total: null, lucro: null,
      outro_local: null, vagas: null, apagado: false, ids: [] };
    if (s.status === "ocupado" && s.cliente_id) Object.assign(cel, { status: "livre", cliente_id: null, cliente_nome: null });   // cópia antiga: a Agenda manda
    const fora = gerais.get(`${s.dia}-${s.hora}`)?.[0];
    // a Agenda vale sempre; o resto (indisponível, nome digitado) só cobre o horário livre aqui
    if (fora && (cel.status === "livre" || fora.agenda)) {
      Object.assign(cel, { status: fora.status, cliente_id: fora.cliente_id, cliente_nome: fora.nome, ids: fora.ids, vagas: fora.vagas ?? null,
        outro_local: fora.local !== local ? fora.local : null });
    }
    if (cel.status === "livre") {
      const m = cel.multiplicador;
      if (!precosHora.has(m)) precosHora.set(m, calcular({ ...base }, p, { mult_horario: m }));
      const r = precosHora.get(m)!;
      Object.assign(cel, { preco_aula: r.preco_total / (base.sessoes_mes || 1), margem: r.margem, preco_total: r.preco_total, lucro: r.lucro });
    }
    if (vale && !(cel.status === "livre" && cel.multiplicador < 1)) cel.apagado = true;
    celulas.set(`${s.dia}-${s.hora}`, cel);
  }
  const locais = [...new Set([...locaisLista, ...locaisGrade.map((r) => r.local)])];
  const todas = [...celulas.values()];
  const resumo = { livres: todas.filter((c) => c.status === "livre").length, ocupados: todas.filter((c) => c.status === "ocupado").length,
    vale: todas.filter((c) => c.status === "livre" && c.multiplicador < 1).length };
  // "Por que esse preço?": as partes do preço de 1 aula em cada local, no mesmo plano de referência
  const comparar = locais.map((l) => ({ local: l, ...decompor({ ...planoReferencia(tipo, l, ref) }, p, l) }));
  return { celulas, minima, tipo, local, vale, locais, maxAlunos: cabe, soGrade, clientes, base, resumo, refs, refAtual: base[col],
    custosLocal: cia ?? (p.locais.get(local) || {}), mults, comparar, cia: ehCia(local), refGrade: ref };
}

/** int() da URL ou do formulário: inválido = 422, como o FastAPI. */
class Erro422 extends Error {}
function inteiro(v: string | undefined, padrao = 0): number {
  if (v === undefined) return padrao;
  try {
    return intPy(v);
  } catch {
    throw new Erro422();
  }
}

function cor(c: Celula, minima: number): string {
  return c.status !== "livre" ? c.status : corMargem(c.margem, minima);
}

function CelulaGrade({ d, h, c, local, minima }: { d: number; h: number; c: Celula | undefined; local: string; minima: number }): Child {
  const titulo = `${DIAS[d]} ${h2(h)}h — ${local}`;
  if (!c) return <button class="cel indisponivel" data-abrir="dlg-slot" data-titulo={titulo} data-dia={String(d)} data-hora={String(h)} data-status="livre">—</button>;
  const classe = `cel ${cor(c, minima)} ${c.apagado ? "apagado" : ""} ${c.status === "livre" && c.multiplicador < 1 ? "vale" : ""}`;
  const nota = c.outro_local ? { "data-nota": `Hoje esse horário está em ${c.outro_local}. Salvar como ocupado ou indisponível passa ele para ${local}; Livre solta em todos os locais.` } : {};
  let corpo: Child;
  if (c.status === "ocupado") {
    corpo = <><span class="t">{c.cliente_nome || "Ocupado"}</span>{c.vagas ? <small class="miudo">{c.vagas} vaga{c.vagas > 1 ? "s" : ""}</small> : ""}</>;
  } else if (c.status === "indisponivel") {
    corpo = <><span class="t">Indisponível</span>{!c.outro_local ? <><br />{c.bloqueio || ""}</> : ""}</>;
  } else if (c.preco_aula) {
    corpo = <><span class="t">{moeda(c.preco_aula)}</span>
      <small class="miudo">Total {moeda(c.preco_total)}<br />Lucro {moeda(c.lucro)} · {pct(c.margem)}{c.multiplicador !== 1 ? ` · x${num(c.multiplicador, 2)}` : ""}</small></>;
  } else corpo = <span class="t">Livre</span>;
  return (
    <button class={classe} data-abrir="dlg-slot" data-titulo={titulo} data-dia={String(d)} data-hora={String(h)} data-status={c.status}
      data-cliente_id={c.cliente_id ? String(c.cliente_id) : ""} data-alunos={c.ids.join(",")} data-quem={c.cliente_nome || ""} {...nota}>
      {corpo}
      {c.outro_local ? <small class="miudo">em {c.outro_local}</small> : ""}
    </button>
  );
}

function TelaGrade({ ctx, d }: { ctx: Contexto; d: DadosGrade }): Child {
  const { tipo, local, minima, base } = d;
  const c = d.custosLocal as CustosLocal;
  const grupo = d.cia && c.grupo ? Object.fromEntries([...c.grupo].map(([n, v]) => [`data-taxa_${n}`, f2(v)])) : {};
  const m100 = (x: number) => Math.trunc(arred(x * 100, 0));
  const refHidden = String(d.refAtual ? Math.trunc(d.refAtual) : 0);
  const qs = `?tipo=${quoteUrl(tipo)}&local=${quoteUrl(local)}&ref=${refHidden}`;
  const cls = (l: string) => (l === local ? "atual" : "");
  return (
    <Base ctx={ctx}>
      <div class="linha topo">
        <h1 style="margin:0">Grade semanal — {local} ({tipo})</h1>
        <form method="get" class="linha">
          <select name="local" onchange="this.form.submit()">{d.locais.map((l) => <option selected={l === local}>{l}</option>)}</select>
          <select name="tipo" onchange="if (this.form.ref) this.form.ref.disabled = true; this.form.submit()"><option selected={tipo === "Pacotes"}>Pacotes</option><option selected={tipo === "Mensalidades"}>Mensalidades</option></select>
          {d.refs.length ? <select name="ref" onchange="this.form.submit()" aria-label="Plano de referência">{d.refs.map((r) => <option value={String(Math.trunc(r))} selected={r === d.refAtual}>{Math.trunc(r)}{tipo === "Mensalidades" ? "x/semana" : " aulas"}</option>)}</select> : ""}
          <label style="display:flex;align-items:center;gap:6px;margin:0"><input type="checkbox" name="vale" value="1" checked={!!d.vale} onchange="this.form.submit()" /> Só horários de vale</label>
        </form>
        <button type="button" class="claro" id="modo-sel" aria-pressed="false">Selecionar vários</button>
        <button type="button" class="claro" data-abrir="dlg-mult">Multiplicadores</button>
        <button type="button" class="claro" data-abrir="dlg-local" data-voltar="/grade">+ Novo local</button>
        <button type="button" class="claro" data-abrir="dlg-local" data-acao="/locais/editar" data-titulo={`Editar ${local}`} data-nome={local} data-nome_original={local}
          data-taxa_aula={f2(c.taxa_aula)} data-taxa_pessoa_extra={f2(c.taxa_pessoa_extra)} data-max_pessoas={String(c.max_pessoas || 0)}
          {...(d.cia ? { "data-cia": "1", ...grupo } : {})}
          data-deslocamento={f2(c.deslocamento)} data-tempo_deslocamento={String(Math.trunc(Number(c.tempo_deslocamento) || 0))} data-taxa_mensal={f2(c.taxa_mensal)}
          data-aulas_mes={String(Math.trunc(Number(c.aulas_mes) || 0))}>Editar local</button>
        {!d.cia ? (
          <form method="post" action="/locais/excluir" style="margin:0" data-confirmar={`Excluir o local ${local}? Custos e grade dele somem. Aulas e contas antigas ficam.`}>
            <input type="hidden" name="nome" value={local} /><button class="claro">Excluir local</button></form>
        ) : ""}
      </div>
      <div class="linha" style="justify-content:space-between">
        <div class="legenda">
          <span><i style="background:var(--verde-f)"></i> margem ≥ {m100(minima)}%</span><span><i style="background:var(--amarelo-f)"></i> {m100(minima - 0.05)}–{m100(minima)}%</span>
          <span><i style="background:var(--vermelho-f)"></i> &lt; {m100(minima - 0.05)}%</span><span><i style="background:#f5c9c5"></i> prejuízo</span>
          <span><i style="background:var(--aco)"></i> ocupado</span><span><i style="background:#dfe3ea"></i> indisponível</span>
        </div>
        <div class="muted">{d.resumo.livres} livres · {d.resumo.ocupados} ocupados · {d.resumo.vale} de vale · referência: {base.tipo_servico} {base.qtd_aulas || `${base.freq_semanal}x/sem`}</div>
      </div>
      <p class="muted" style="margin:6px 0 0"><b>Em cada horário livre:</b> número grande = preço por aula · Total = valor do {tipo === "Pacotes" ? "pacote" : "mês"} de referência · Lucro = quanto sobra desse total (R$ e %) · x0,90 = multiplicador do horário (abaixo de 1 = vale; muda em <b>Multiplicadores</b>)<br />
        <b>Vale para todos os locais:</b> horário ocupado ou indisponível em outro local aparece aqui com o nome dele.</p>
      {d.soGrade.length ? (
        <div class="aviso atencao mt" id="so-grade">
          <p style="margin:0 0 6px"><strong>{d.soGrade.length} horário{d.soGrade.length > 1 ? "s" : ""} só na Grade</strong>: a Grade agora mostra a ocupação da Agenda,
            e estes alunos estão na Grade antiga mas não têm o horário na Agenda.</p>
          <p class="muted" style="margin:0 0 6px">{d.soGrade.slice(0, 8).map((x, i, a) => `${x.nome} ${DIAS[x.dia] ?? ""} ${h2(x.hora)}h (${x.local})${i < a.length - 1 ? ", " : ""}`).join("")}{d.soGrade.length > 8 ? ` e mais ${d.soGrade.length - 8}` : ""}.</p>
          <form method="post" action="/grade/passar-para-agenda" style="margin:0" data-confirmar="Criar na Agenda o horário fixo desses alunos? Nada é apagado.">
            <input type="hidden" name="tipo" value={tipo} /><input type="hidden" name="local" value={local} /><input type="hidden" name="ref" value={refHidden} />
            <button class="pequeno">Passar para a Agenda</button></form>
        </div>
      ) : ""}
      <div class="rolagem mt">
        <table class="grade">
          <tr><th></th>{[1, 2, 3, 4, 5, 6].map((n) => <th>{DIAS[n]}</th>)}</tr>
          {HORAS_GRADE.map((h) => (
            <tr><td class="hora">{h2(h)}h</td>
              {[1, 2, 3, 4, 5, 6].map((n) => <td><CelulaGrade d={n} h={h} c={d.celulas.get(`${n}-${h}`)} local={local} minima={minima} /></td>)}
            </tr>
          ))}
        </table>
      </div>
      {d.comparar.length ? (
        <details class="card mt" id="porque">
          <summary><b>Por que esse preço? Compare os locais</b></summary>
          <p class="muted" style="margin:6px 0">De onde vem o preço de <b>1 aula</b> (1 pessoa, x1,00) no plano de referência
            ({base.tipo_servico} {tipo === "Pacotes" ? `${Math.trunc(base.qtd_aulas)} aulas` : `${Math.trunc(base.freq_semanal)}x/semana`}).
            A linha que mais muda de um local para o outro é a que deixa o preço mais alto.</p>
          <div class="rolagem">
            <table class="comparar">
              <tr><th>Por aula</th>{d.comparar.map((x) => <th class={cls(x.local)}>{x.local}</th>)}</tr>
              <tr class="total"><td>Preço por aula</td>{d.comparar.map((x) => <td class={cls(x.local)}>{moeda(x.preco)}</td>)}</tr>
              <tr class="total"><td>Custo por aula<br /><small class="muted">a soma das linhas abaixo</small></td>{d.comparar.map((x) => <td class={cls(x.local)}>{moeda(x.custo)}</td>)}</tr>
              <tr><td>Taxa do local</td>{d.comparar.map((x) => <td class={cls(x.local)}>{moeda(x.taxa)}</td>)}</tr>
              <tr><td>Taxa mensal ÷ aulas do mês</td>{d.comparar.map((x) => <td class={cls(x.local)}>{moeda(x.mensal)}</td>)}</tr>
              <tr><td>Deslocamento (R$)</td>{d.comparar.map((x) => <td class={cls(x.local)}>{moeda(x.ida_reais)}</td>)}</tr>
              <tr><td>Seu tempo<br /><small class="muted">minutos × R$/hora</small></td>{d.comparar.map((x) => <td class={cls(x.local)}>{moeda(x.salario)}<br /><small class="muted">{num(x.minutos, 0)} min{x.minutos_ida ? ` (ida ${num(x.minutos_ida, 0)})` : ""}</small></td>)}</tr>
              <tr><td>Custos fixos rateados</td>{d.comparar.map((x) => <td class={cls(x.local)}>{moeda(x.rateio)}</td>)}</tr>
            </table>
          </div>
          <p class="muted" style="margin:6px 0 0">Taxa, taxa mensal e deslocamento de qualquer local (CIA inclusive): escolha o local e clique em <b>Editar local</b>.
            Seu tempo e os custos fixos: Configurações.</p>
        </details>
      ) : ""}
      <div class="barra-sel" id="barra-sel">
        <span id="sel-txt" aria-live="polite"></span>
        <button type="button" id="sel-editar">Editar selecionados</button>
        <button type="button" class="claro" id="sel-limpar">Limpar</button>
      </div>

      <dialog id="dlg-slot">
        <h2 data-titulo="">Horário</h2>
        <form method="post" action="/grade/slot">
          <input type="hidden" name="tipo" value={tipo} /><input type="hidden" name="local" value={local} /><input type="hidden" name="ref" value={refHidden} />
          <input type="hidden" name="dia" /><input type="hidden" name="hora" />
          <p class="nota-grade" data-nota="" hidden></p>
          <div class="campo"><label>Situação</label><select name="status" required><option value="" hidden>Escolha a situação</option><option value="livre">Livre</option><option value="ocupado">Ocupado</option><option value="indisponivel">Indisponível</option></select></div>
          <div class="campo" data-alunos-grade=""><label>Aluno{d.maxAlunos > 1 ? "s" : ""} (se ocupado; até {d.maxAlunos} no mesmo horário)</label>
            {Array.from({ length: d.maxAlunos }, (_, n) => <select name="cliente_id" aria-label={`${n + 1}º aluno`} hidden={n > 0} style="margin-bottom:6px"><option value="">{!n ? "—" : "— ninguém —"}</option>{d.clientes.map((cl) => <option value={String(cl.id)}>{cl.nome}</option>)}</select>)}
            {d.maxAlunos > 1 ? <button type="button" class="claro pequeno" data-mais-aluno="">+ outro aluno</button> : ""}
          </div>
          <p class="muted" style="margin:0 0 8px">Ocupado grava o horário fixo na Agenda (é ela que manda); Livre tira da Agenda quem estiver no horário.
            Vale para todos os locais, em Pacotes e Mensalidades.
            Preço do horário: <button type="button" class="claro pequeno" data-abrir="dlg-mult" onclick="this.closest('dialog').close()">Multiplicadores</button></p>
          <div class="linha"><button>Salvar</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
        </form>
      </dialog>
      <dialog id="dlg-mult">
        <h2 data-titulo="">Multiplicadores</h2>
        <form method="post" action={`/grade/multiplicadores${qs}`}>
          <p class="muted" style="margin:0 0 8px">Vale para <b>todos os locais e todos os dias</b>, em Pacotes e Mensalidades.
            1,00 = preço normal · acima de 1 = mais caro · abaixo de 1 = vale (horário para encher).</p>
          <div class="mults">
            {[...d.mults].map(([h, m]) => <label>{h2(h)}h <input name={`m_${h2(h)}`} value={num(m, 2)} inputmode="decimal" size={5} aria-label={`Multiplicador das ${h2(h)}h`} /></label>)}
          </div>
          <div class="linha mt"><button>Salvar</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
        </form>
      </dialog>
      {raw(SCRIPT_GRADE)}
      <DlgLocal ctx={ctx} tipo={tipo} refGrade={d.refGrade} />
    </Base>
  );
}

async function formulario(c: Context<Ambiente>): Promise<Record<string, string | string[]>> {
  const corpo = await c.req.parseBody({ all: true });
  return Object.fromEntries(Object.entries(corpo).map(([k, v]) => [k, Array.isArray(v) ? v.map((x) => (typeof x === "string" ? x : "")) : typeof v === "string" ? v : ""]));
}
const um = (v: string | string[] | undefined) => (Array.isArray(v) ? v[v.length - 1] : v);
const varios = (v: string | string[] | undefined) => (v === undefined ? [] : [v].flat());

export function rotasGrade(app: Hono<Ambiente>): void {
  app.get("/grade", async (c) => {
    const q = (k: string) => c.req.query(k);
    let vale: number, ref: number;
    try {
      vale = inteiro(q("vale"));
      ref = inteiro(q("ref"));
    } catch {
      return c.text("Campo inválido", 422);
    }
    const b = banco(c);
    const [ctx, d] = await Promise.all([contextoBase(b, c.req.raw), dados(b, q("tipo") ?? "Pacotes", q("local") ?? "CIA", vale, ref)]);
    return c.html(String(<TelaGrade ctx={ctx} d={d} />));
  });

  app.post("/grade/multiplicadores", async (c) => {
    const q = (k: string) => c.req.query(k);
    let ref: number;
    try {
      ref = inteiro(q("ref"));
    } catch {
      return c.text("Campo inválido", 422);
    }
    const tipo = q("tipo") ?? "Pacotes", local = q("local") ?? "CIA";
    const url = `/grade?tipo=${quoteUrl(tipo)}&local=${quoteUrl(local)}&ref=${ref}`;
    const f = await formulario(c);
    const novos = new Map<number, number>();
    for (const h of HORAS_GRADE) {
      const txt = String(um(f[`m_${h2(h)}`]) ?? "").trim();
      if (!txt) continue;
      let v: number | null;
      try {
        v = numBr(txt);
      } catch {
        v = null;
      }
      if (v === null || !(v >= 0.1 && v <= 5)) return voltar(c, url, null, `${h2(h)}h: use um número de 0,10 a 5,00 (1,00 = preço normal).`);
      novos.set(h, arred(v, 2));
    }
    if (!novos.size) return voltar(c, url, null, "Nenhum multiplicador para salvar.");
    await banco(c).batch([...novos].map(([h, v]) => ({ sql: "INSERT INTO parametros (grupo, chave, valor, ordem) VALUES ('mult_horario', ?, ?, ?) "
      + "ON CONFLICT(grupo, chave) DO UPDATE SET valor=excluded.valor", params: [h2(h), v, h] })));
    return voltar(c, url, "Multiplicadores salvos: valem para todos os locais e dias.");
  });

  app.post("/grade/slot", async (c) => {
    const b = banco(c);
    const f = await formulario(c);
    const tipo = um(f.tipo), local = um(f.local);
    if (tipo === undefined || local === undefined) return c.text("Campo obrigatório faltando", 422);
    let dia: number, hora: number, ref: number;
    try {
      [dia, hora, ref] = [inteiro(um(f.dia)), inteiro(um(f.hora)), inteiro(um(f.ref))];
    } catch {
      return c.text("Campo inválido", 422);
    }
    const status = um(f.status) ?? "";
    const celulasForm = varios(f.celulas);
    const lote = celulasForm.length > 0;
    const pares: [number, number][] = [];
    for (const x of (lote ? celulasForm : [`${dia}-${hora}`]).slice(0, 300)) {
      const partes = x.split("-");
      if (partes.length !== 2) continue;
      let d: number, h: number;
      try {
        [d, h] = [intPy(partes[0]), intPy(partes[1])];
      } catch {
        continue;
      }
      if (d >= 1 && d <= 6 && h >= 5 && h <= 23 && !pares.some(([a, z]) => a === d && z === h)) pares.push([d, h]);
    }
    const url = `/grade?tipo=${quoteUrl(tipo)}&local=${quoteUrl(local)}&ref=${ref}`;
    if (!pares.length || !["livre", "ocupado", "indisponivel"].includes(status)) {
      return voltar(c, url, null, !pares.length ? "Nenhum horário selecionado." : "Escolha a situação do horário.");
    }
    const ids = [...new Set(varios(f.cliente_id).map(idValido).filter(Boolean))];
    const [g, mults] = await Promise.all([GravaAgenda.abrir(b, hoje()), multHorario(b)]);
    if (status === "ocupado") {
      if (!ids.length) return voltar(c, url, null, "Escolha o aluno (ou marque como livre).");
      if (!ids.every((i) => { const x = g.clientes.get(i); return x && x.excluido_em == null && x.status === "ativo"; })) {
        return voltar(c, url, null, "Escolha alunos ativos: só eles têm horário fixo na Agenda.");
      }
    }
    const agenda = new Map(pares.map(([d, h]) => [`${d}-${h}`, g.membros(d, h)]));   // quem está no horário na Agenda
    if (status === "ocupado") {   // passar do limite só com quem já está (limite reduzido depois): ninguém sai, ninguém novo entra
      const passa = ([d, h]: [number, number]) => {
        const m = agenda.get(`${d}-${h}`)!;
        const junto = new Set(lote ? [...m.keys(), ...ids] : ids);
        return junto.size > g.cabe && ![...junto].every((x) => m.has(x));
      };
      const cheio = pares.find(passa);
      if (cheio) {
        const quem = g.fixosDoHorario(...cheio).map((r) => r.nome).join(" e ") || "ninguém";
        return voltar(c, url, null, `${quando(...cheio)}: cabem ${g.cabe} alunos (hoje: ${quem}). Nada foi gravado.`);
      }
    }
    if (status === "indisponivel") {
      const com = pares.find(([d, h]) => agenda.get(`${d}-${h}`)!.size);
      if (com) return voltar(c, url, null, `${quando(...com)} tem aula na Agenda: marque como livre (tira da Agenda) antes de deixar indisponível.`);
    }
    // a Grade não guarda mais aluno: solta o que ela tinha nesses horários (em todos os locais)
    g.soltarHorarios(pares);
    if (status === "indisponivel") {
      g.salvarSlots(TIPOS_GRADE.flatMap((t) => pares.map(([d, h]) => [t, d, local, h, status, null, null, mults.get(h) ?? 1.0] as [string, number, string, number, string, null, null, number])));
    }
    for (const [d, h] of pares) {
      const m = agenda.get(`${d}-${h}`)!;
      if (status === "ocupado") {
        if (lote) {   // vários horários: soma os escolhidos a quem já está (sem tirar ninguém)
          const junto = [...m.keys(), ...ids.filter((x) => !m.has(x))];
          g.definirHorario(d, h, junto, new Map([...m, ...ids.filter((x) => !m.has(x)).map((x) => [x, local] as [number, string])]));
        } else g.definirHorario(d, h, ids, local);   // um horário: a lista escolhida é a do horário, neste local
      } else if (m.size) g.definirHorario(d, h, [], new Map());   // livre: tira da Agenda quem estava
    }
    await b.batch(g.cmds);
    let msg: string;
    if (status === "ocupado") {
      const quem = nomesCurtos(ids.map((x) => g.clientes.get(x)!.nome)).join(" + ");
      msg = (lote ? `${pares.length} horários` : quando(...pares[0])) + `: ${quem} na Agenda (${local}).`;
      if (ids.length === 1) msg += await avisoDeslocamento(b, g, pares.map(([d, h]) => [d, h, local]), ids[0]);
    } else if (status === "livre") {
      const tirados = pares.filter(([d, h]) => agenda.get(`${d}-${h}`)!.size).length;
      msg = (lote ? `${pares.length} horários livres.` : `${quando(...pares[0])} livre.`) + (tirados ? ` Saiu da Agenda em ${tirados} horário(s).` : "");
    } else msg = lote ? `${pares.length} horários indisponíveis.` : `${quando(...pares[0])} indisponível.`;
    return voltar(c, url, msg + " Vale para todos os locais.");
  });

  app.post("/grade/passar-para-agenda", async (c) => {
    const b = banco(c);
    const f = await formulario(c);
    let ref: number;
    try {
      ref = inteiro(um(f.ref));
    } catch {
      return c.text("Campo inválido", 422);
    }
    const tipo = um(f.tipo) ?? "Pacotes", local = um(f.local) ?? "CIA";
    const url = `/grade?tipo=${quoteUrl(tipo)}&local=${quoteUrl(local)}&ref=${ref}`;
    const [falta, g] = await Promise.all([soNaGrade(b), GravaAgenda.abrir(b, hoje())]);
    if (!falta.length) return voltar(c, url, "A Agenda já tem todos os horários da Grade.");
    const ocupados = new Map<string, Set<number>>();
    for (const x of await fixosAtuaisDe(b)) {
      const k = `${x.dia}-${x.hora}`;
      if (!ocupados.has(k)) ocupados.set(k, new Set());
      ocupados.get(k)!.add(x.cliente_id);
    }
    const novos: [number, number, number, string][] = [], criados: SoNaGrade[] = [], cheios: SoNaGrade[] = [];
    for (const x of falta) {
      const k = `${x.dia}-${x.hora}`;
      if ((ocupados.get(k)?.size ?? 0) >= g.cabe) {
        cheios.push(x);
        continue;
      }
      if (!ocupados.has(k)) ocupados.set(k, new Set());
      ocupados.get(k)!.add(x.cliente_id);
      novos.push([x.cliente_id, x.dia, x.hora, x.local]);
      criados.push(x);
    }
    if (novos.length) {
      g.inserirFixos(novos, g.vigencias(novos.map((n) => n[0])));
      await b.batch(g.cmds);
    }
    let msg = `${plural(criados.length, "horário passou", "horários passaram")} para a Agenda.`;
    if (cheios.length) {
      msg += ` ${plural(cheios.length, "ficou de fora", "ficaram de fora")} (horário cheio): `
        + cheios.slice(0, 5).map((x) => `${x.nome} ${quando(x.dia, x.hora)}`).join(", ") + ".";
    }
    return voltar(c, url, msg);
  });
}

/** Id de um campo de texto (vazio ou torto: 0), como main.id_valido. */
function idValido(t: string): number {
  const s = t.trim();
  return /^[0-9]+$/.test(s) && s.length < 10 ? Number(s) : 0;
}
