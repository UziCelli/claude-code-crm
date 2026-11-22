/** Agenda (port de app/main.py: /agenda, /agenda/pendentes, /agenda/marcar, marcar-lote, incluir, horario, copiar-grade, evento e avulsa; tela agenda.html). */
import type { Hono } from "hono";
import { html, raw } from "hono/html";
import type { Child } from "hono/jsx";
import { banco, type Ambiente } from "../app.ts";
import type { Banco } from "../banco/banco.ts";
import type { Comando, Linha } from "../banco/tipos.ts";
import { dataBr, moeda } from "../formato.ts";
import { agoraTxt } from "../relogio.ts";
import { avisoDeslocamento, fixoVale, GravaAgenda, maxAlunos, nomesCurtos, quando } from "../regras/agenda.ts";
import { alunosComHorario, fasesBloqueio, temAulas } from "../regras/alunos.ts";
import {
  aulasDaSemana, controleAluno, descricaoMarca, emBloqueio, ESTADO_MSG, ESTADO_TIPO, gravarMarcas, idValido, inicioSemana, mesValido, norm,
  resumoAulasMes, saldosReposicao, sugerirCliente, TIPOS_MARCA, urlAgenda, type Aula, type Controle, type ResumoMes,
} from "../regras/aulas.ts";
import { dataIso, diaDaSemana, diasEntre, fromIsoPy, somarDias } from "../regras/datas.ts";
import { DIAS, DIAS_CURTO } from "../regras/ficha.ts";
import { formatoG } from "../regras/financeiro.ts";
import { relogioMes } from "../regras/mes.ts";
import { lista, parametros } from "../regras/parametros.ts";
import { Base } from "../telas/Base.tsx";
import { contextoBase, type Contexto } from "../telas/contexto.ts";
import { DlgLocal } from "../telas/DlgLocal.tsx";
import { tojson } from "../telas/json.ts";
import { SCRIPT_AGENDA } from "./agenda-script.ts";
import { intForm, intQuery, intsForm, lerForm, txt, um, verdadePy, type Form } from "./form.ts";
import { intPy, voltar } from "./util.ts";

const hoje = () => relogioMes.hoje();
const h2 = (h: number) => String(h).padStart(2, "0");
const ddmm = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
const plural = (n: number, um_: string, varios: string) => `${n} ${n === 1 ? um_ : varios}`;
const primeiroNome = (nome: string) => nome.split(/\s+/).filter(Boolean)[0] ?? nome;
const ROT: Record<string, string> = { feita: "feita", faltou: "faltou", desmarcou: "desmarcou", cancelada: "cancelada", pausa: "pausa", pendente: "sem marcar", futura: "", agendada: "agendada" };
const COR: Record<string, string> = { feita: "verde", faltou: "vermelho", desmarcou: "amarelo", cancelada: "neutro", agendada: "azul" };

interface AulaTela extends Aula { deve: number; marca: Record<string, unknown>; base: string; curto?: string }
interface Repor { id: number; nome: string; saldo: number; a_agendar: number; agendadas: number }
interface Dia { n: number; iso: string; hoje: boolean; bloqueio: boolean }

interface DadosAgenda {
  dias: Dia[]; horas: number[]; celulas: Map<string, AulaTela[]>; infos: Map<string, unknown>; todas: number; atual: boolean; hoje: string; segunda: string;
  anterior: string; proxima: string; semanaTxt: string; temAulas: boolean; vazia: boolean; hojeAulas: AulaTela[]; multiLocal: boolean;
  controle: Controle | null; extra: string; extraAluno: string; hojeSegunda: string; pendentes: AulaTela[]; repor: Repor[]; aulasMes: ResumoMes;
  semanasContratadas: number; locais: string[]; clientes: Linha[]; comAulas: Linha[]; dataPadrao: string; voltarLocal: string;
}

async function dados(b: Banco, semana: string, todas: number, aluno: string, mes: string, voltarLocal: string): Promise<DadosAgenda> {
  const h = hoje();
  const segunda = inicioSemana(semana, h), hojeSegunda = inicioSemana(h, h);
  const atual = segunda === hojeSegunda;
  const cid = idValido(aluno), mesOk = mesValido(mes) || h.slice(0, 7);
  const [fases, aulas, saldos, fixosRows, clientes, comHorario, vaziaRow, listaLocais, outrosLocais, controle, aulasMes, par] = await Promise.all([
    fasesBloqueio(b), aulasDaSemana(b, segunda, h), saldosReposicao(b, null, h),
    b.query(`SELECT f.dia, f.hora, f.local, c.id AS cliente_id, c.nome FROM agenda_fixos f JOIN clientes c ON c.id=f.cliente_id
             WHERE f.excluido_em IS NULL AND f.dia BETWEEN 1 AND 6 AND f.hora BETWEEN 5 AND 23
             AND c.status='ativo' AND c.excluido_em IS NULL ORDER BY f.id`),
    b.query("SELECT id, nome, local, tipo_servico, plano FROM clientes WHERE excluido_em IS NULL AND status='ativo' ORDER BY nome"),
    alunosComHorario(b),
    b.um("SELECT 1 AS um FROM agenda_fixos WHERE excluido_em IS NULL LIMIT 1"),
    lista(b, "lista_locais"),
    b.query<{ local: string }>("SELECT local FROM grade_slots UNION SELECT local FROM agenda_fixos WHERE excluido_em IS NULL ORDER BY 1"),
    cid ? controleAluno(b, cid, mesOk, h) : Promise.resolve(null),   // aluno ou mês inválidos: página normal
    resumoAulasMes(b, h.slice(0, 7), h),
    parametros(b, "agenda"),
  ]);
  const dias: Dia[] = [1, 2, 3, 4, 5, 6].map((n) => {
    const iso = somarDias(segunda, n - 1);
    return { n, iso, hoje: iso === h, bloqueio: emBloqueio(fases, iso) };
  });
  const celulas = new Map<string, AulaTela[]>();
  const tela: AulaTela[] = aulas.map((a) => {
    const base = a.bloqueio ? "bloq" : a.pausa ? "pausa" : a.data < h ? "pendente" : "futura";   // cor da aula sem marcação
    const marca = { cliente_id: a.cliente_id, data: a.data, hora: a.hora, local: a.local, avulsa: a.avulsa, reposicao: a.reposicao, estado: a.estado, base };
    const x: AulaTela = { ...a, deve: saldos.get(a.cliente_id)?.saldo ?? 0, marca, base };
    const k = `${a.dia}-${a.hora}`;
    if (!celulas.has(k)) celulas.set(k, []);
    celulas.get(k)!.push(x);
    return x;
  });
  for (const lst of celulas.values()) nomesCurtos(lst.map((a) => a.nome)).forEach((c, i) => (lst[i].curto = c));
  const fixos = new Map<string, { cliente_id: number; nome: string; local: string }[]>();   // quem tem o horário fixo: preenche o seletor
  for (const r of fixosRows) {
    const k = `${r.dia}-${r.hora}`;
    if (!fixos.has(k)) fixos.set(k, []);
    const l = fixos.get(k)!;
    if (l.every((x) => x.cliente_id !== r.cliente_id)) l.push({ cliente_id: r.cliente_id, nome: r.nome, local: r.local });
  }
  const pendentes = tela.filter((a) => a.situacao === "pendente" && !a.bloqueio);
  const repor: Repor[] = [];
  for (const c of clientes) {
    const s = saldos.get(c.id);
    if (s && s.saldo > 0) repor.push({ id: c.id, nome: c.nome, saldo: s.saldo, a_agendar: s.a_agendar, agendadas: s.sem_marca });
  }
  repor.sort((x, y) => y.a_agendar - x.a_agendar || (x.nome.toLowerCase() < y.nome.toLowerCase() ? -1 : x.nome.toLowerCase() > y.nome.toLowerCase() ? 1 : 0));
  const comAulas = clientes.filter((c) => temAulas(c, comHorario));
  const horas = todas || !celulas.size ? Array.from({ length: 19 }, (_, i) => i + 5)
    : [...new Set([...celulas.keys()].map((k) => Number(k.split("-")[1])))].sort((x, y) => x - y);
  const infos = new Map<string, unknown>();   // dados do card para a janelinha (JSON no data-info)
  for (const d of dias) {
    for (const hr of horas) {
      const k = `${d.n}-${hr}`, lst = celulas.get(k) ?? [], fx = fixos.get(k) ?? [];
      infos.set(k, {
        dia: d.n, hora: hr, data: d.iso, titulo: `${DIAS_CURTO[d.n]} ${ddmm(d.iso)} · ${h2(hr)}h`, local: (fx[0] ?? lst[0] ?? { local: "" }).local,
        alunos: lst.map((a) => ({ cliente_id: a.cliente_id, nome: a.nome, estado: a.estado, situacao: a.situacao, avulsa: a.avulsa, avulsa_id: a.avulsa_id,
          reposicao: a.reposicao, repoe: a.repoe, local: a.local, bloqueio: a.bloqueio, pausa: a.pausa, deve: a.deve, base: a.base })),
        fixos: fx,
      });
    }
  }
  const locais = [...listaLocais, ...outrosLocais.map((r) => r.local).filter((l) => !listaLocais.includes(l))];
  const extraAluno = controle ? `&aluno=${controle.id}&mes=${controle.mes}` : "";
  return {
    dias, horas, celulas, infos, todas: todas ? 1 : 0, atual, hoje: h, segunda, anterior: somarDias(segunda, -7), proxima: somarDias(segunda, 7),
    semanaTxt: `${ddmm(segunda)} a ${ddmm(somarDias(segunda, 5))}`, temAulas: celulas.size > 0, vazia: !vaziaRow,
    hojeAulas: atual ? tela.filter((a) => a.data === h) : [], multiLocal: new Set(tela.map((a) => a.local)).size > 1,
    controle, extra: (todas ? "&todas=1" : "") + extraAluno, extraAluno, hojeSegunda, pendentes, repor, aulasMes,
    semanasContratadas: Number(par.semanas_contratadas || 4), locais, clientes, comAulas, dataPadrao: atual ? h : segunda, voltarLocal,
  };
}

/** unique do Jinja: sem diferenciar maiúsculas, fica o primeiro. */
function unicos(xs: string[]): string[] {
  const vistos = new Set<string>(), out: string[] = [];
  for (const x of xs) {
    const k = x.toLowerCase();
    if (!vistos.has(k)) {
      vistos.add(k);
      out.push(x);
    }
  }
  return out;
}

/** A grade da semana, com `html` (parte grande da tela). */
function grade(d: DadosAgenda) {
  const linhas = d.horas.map((h) => {
    const tds = d.dias.map((dia) => {
      const k = `${dia.n}-${h}`, lst = d.celulas.get(k) ?? [];
      const cls = `${dia.hoje ? "hoje" : ""} ${dia.bloqueio ? "bloq" : ""}`;
      const info = tojson(d.infos.get(k));
      if (!lst.length) {
        return html`<td class="${cls}"><button type="button" class="cel vazio" data-dh="${k}" data-info="${info}" aria-label="Escolher aluno de ${DIAS[dia.n]} às ${h2(h)}h">+</button></td>`;
      }
      const rots: string[] = [];
      for (const a of lst) {
        const r = a.bloqueio && !a.estado ? "" : ROT[a.situacao];
        if (r && !rots.includes(r)) rots.push(r);
      }
      const locs = unicos(lst.map((a) => a.local));
      const classe = lst.length > 1 ? "dupla" : lst[0].bloqueio && !lst[0].estado ? "bloq" : lst[0].situacao;
      const nomes = lst.map((a, i) => {
        const tag = a.reposicao ? html` <span class="av">reposição</span>` : a.avulsa ? html` <span class="av">avulsa</span>` : "";
        const n = html`<span class="n ${a.bloqueio && !a.estado ? "bloq" : a.situacao}">${a.curto}${tag}</span>`;
        return i ? html` <span class="seg"><span class="mais">+</span> ${n}</span>` : n;
      });
      const rodape = rots.length || d.multiLocal
        ? html`<small class="miudo"><span class="rots">${rots.join(" · ")}${rots.length && d.multiLocal ? " · " : ""}</span>${d.multiLocal ? locs.join(" / ") : ""}</small>` : "";
      return html`<td class="${cls}"><button type="button" class="cel aula ${classe}" data-dh="${k}" data-info="${info}" title="${lst.map((a) => a.nome).join(" + ")} · ${locs.join(" / ")}"><span class="nomes">${raw(nomes.join(""))}</span>${rodape}</button></td>`;
    });
    return html`<tr><td class="hora">${h2(h)}h</td>${raw(tds.join(""))}</tr>`;
  });
  const cab = d.dias.map((dia) => html`<th class="${dia.hoje ? "hoje" : ""} ${dia.bloqueio ? "bloq" : ""}">${DIAS_CURTO[dia.n]}<small>${ddmm(dia.iso)}</small>${dia.bloqueio ? html`<small class="rot-bloq">bloqueio</small>` : ""}</th>`);
  return html`<div class="rolagem mt"><table class="grade agenda"><tr><th></th>${raw(cab.join(""))}</tr>${raw(linhas.join(""))}</table></div>`;
}

function TelaAgenda({ ctx, d }: { ctx: Contexto; d: DadosAgenda }): Child {
  const { controle, segunda, todas } = d;
  const ctl = controle ? <><input type="hidden" name="aluno" value={String(controle.id)} /><input type="hidden" name="mes" value={controle.mes} /></> : "";
  const tds = todas ? "&todas=1" : "";
  const nPend = d.pendentes.length, nAgendar = d.repor.reduce((s, r) => s + r.a_agendar, 0);
  const fazer = d.repor.filter((r) => r.a_agendar > 0), ok = d.repor.filter((r) => r.a_agendar === 0);
  const am = d.aulasMes, tm = am.total;
  const hojeDia = diaDaSemana(d.hoje);
  const r = controle?.resumo;
  const marcaHidden = (a: AulaTela) => (
    <>
      <input type="hidden" name="cliente_id" value={String(a.cliente_id)} /><input type="hidden" name="data" value={a.data} /><input type="hidden" name="hora" value={String(a.hora)} />
      <input type="hidden" name="local" value={a.local} /><input type="hidden" name="avulsa" value={a.avulsa ? "1" : "0"} /><input type="hidden" name="reposicao" value={a.reposicao ? "1" : "0"} />
      <input type="hidden" name="semana" value={segunda} /><input type="hidden" name="todas" value={String(todas)} /><input type="hidden" name="ancora" value="hoje" />{ctl}
    </>
  );
  return (
    <Base ctx={ctx} titulo="Agenda · VFITCOACH CRM">
      <div class="linha topo">
        <h1 style="margin:0">Agenda</h1>
        <div class="topo-acoes">
          <button type="button" class="claro" id="btn-lote">Marcar várias</button>
          <button type="button" class="claro" data-abrir="dlg-local" data-voltar={d.voltarLocal}>+ Novo local</button>
          <button type="button" data-abrir="dlg-incluir" data-titulo="Incluir aula">+ Incluir aula</button>
        </div>
      </div>
      <div class="card pendencias" id="pendencias">
        {!nPend && !nAgendar ? <h2 class="pend-titulo">Pendências <span class="tag verde">Tudo em dia.</span></h2> : (
          <h2 class="pend-titulo">Pendências
            <span class={`tag ${nPend ? "vermelho" : "neutro"}`}>{nPend} sem marcar</span>
            <span class={`tag ${nAgendar ? "amarelo" : "neutro"}`}>{nAgendar} a agendar</span></h2>
        )}
        <div class="pend-colunas">
          <section class="pend-bloco" aria-label="Sem marcar">
            <h3>{d.atual ? "Sem marcar nesta semana" : `Sem marcar na semana de ${segunda.slice(8, 10)}/${segunda.slice(5, 7)}`}</h3>
            {d.pendentes.length ? d.pendentes.map((a) => (
              <div class="pend-linha" data-marca={tojson(a.marca)} data-dh={`${a.dia}-${a.hora}`} role="button" tabindex={0}>
                <span class="pend-quando">{DIAS_CURTO[a.dia]} {ddmm(a.data)} · {h2(a.hora)}h</span>
                <strong>{a.nome}</strong>
                {a.reposicao ? <span class="tag azul">reposição</span> : a.avulsa ? <span class="tag azul">avulsa</span> : ""}
                <span class="tag estado-lote" hidden></span>
              </div>
            )) : <p class="muted" style="margin:0">Nada sem marcar.</p>}
            {nPend ? <div class="pend-acoes"><button type="button" class="claro pequeno" id="pend-todas">Marcar todas como feitas</button></div> : ""}
            <div id="pend-anteriores" class="pend-anteriores" data-extra={d.extra}></div>
          </section>
          <section class="pend-bloco" aria-label="Reposições a fazer">
            <h3>Reposições a fazer</h3>
            {fazer.length ? fazer.map((x) => (
              <div class="repor-linha">
                <span class="repor-quem"><strong>{x.nome}</strong> <span class="muted">—</span> <b>{x.a_agendar} a agendar</b>{x.agendadas ? <> <span class="muted">· {x.agendadas} já agendada{x.agendadas > 1 ? "s" : ""}</span></> : ""}</span>
                <span class="repor-acoes">
                  <button type="button" class="claro pequeno btn-repor-aluno" data-aluno={String(x.id)}>Agendar reposição</button>
                  <a class="muted" href={`/agenda?semana=${segunda}${tds}&aluno=${x.id}`}>Ver controle</a>
                </span>
              </div>
            )) : (!ok.length ? <p class="muted" style="margin:0">Nenhuma reposição a fazer.</p> : "")}
            {ok.length ? (
              <details class="repor-ok"><summary>Já agendadas ({ok.length})</summary>
                {ok.map((x) => (
                  <div class="repor-linha">
                    <span class="repor-quem"><strong>{x.nome}</strong> <span class="muted">· {x.agendadas} já agendada{x.agendadas !== 1 ? "s" : ""}</span></span>
                    <span class="repor-acoes"><a class="muted" href={`/agenda?semana=${segunda}${tds}&aluno=${x.id}`}>Ver controle</a></span>
                  </div>
                ))}
              </details>
            ) : ""}
          </section>
        </div>
      </div>

      <div class="card aulas-mes" id="aulas-mes">
        <h2 class="pend-titulo">Aulas de {am.mes_txt.toLowerCase()}
          {tm.contratadas ? <><span class={`tag ${!tm.faltam ? "verde" : "neutro"}`}>{tm.feitas} feitas de {tm.contratadas} contratadas</span>
            {tm.faltam ? <span class="tag amarelo">faltam {tm.faltam}</span> : ""}</> : ""}
          {tm.passou ? <span class="tag vermelho">passou +{tm.passou}{tm.custo_extra ? ` · ${moeda(tm.custo_extra)} na CIA` : ""}</span> : ""}</h2>
        <p class="muted" style="margin:0 0 8px">Contratadas: Mensalidade = vezes por semana × {formatoG(d.semanasContratadas)} (Configurações &gt; Agenda); Pacote = nº de aulas.
          Previstas: os horários fixos do mês na Agenda (reposição não conta). "Passou": aula a mais que o plano não paga; na CIA ela custa a taxa da aula.</p>
        {am.alunos.length ? (
          <table class="aulas-mes-tab">
            <thead><tr><th>Aluno</th><th class="num">Feitas</th><th class="num">Contratadas</th><th class="num">Previstas</th><th>Situação</th></tr></thead>
            <tbody>
              {am.alunos.map((a) => (
                <tr>
                  <td><a href={`/agenda?aluno=${a.id}&semana=${segunda}${tds}#controle`}>{a.nome}</a></td>
                  <td class="num">{a.feitas}</td>
                  <td class="num">{a.contratadas !== null ? a.contratadas : "—"}</td>
                  <td class="num">{a.previstas}</td>
                  <td>{a.passou ? <span class="tag vermelho">passou +{a.passou}{a.custo_extra ? ` · ${moeda(a.custo_extra)} na CIA` : ""}</span>
                    : a.completo ? <span class="tag verde">mês 100%</span>
                      : a.contratadas ? <span class="tag neutro">faltam {a.faltam}</span>
                        : <span class="muted">sem meta (plano sem nº de aulas)</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p class="muted" style="margin:0">Nenhum aluno com aulas neste mês.</p>}
      </div>

      {d.atual ? (
        <div class="card card-hoje" id="hoje">
          <h2>Hoje — {DIAS[hojeDia]} {ddmm(d.hoje)}</h2>
          {d.hojeAulas.length ? d.hojeAulas.map((a) => (
            <div class={`aula-hoje ${a.estado || ""}`} data-marca={tojson(a.marca)}>
              <div class="quem">
                <span class="hora">{h2(a.hora)}h</span><strong>{a.nome}</strong> <span class="tag estado-lote" hidden></span>
                <div class="muted">{a.local}{a.reposicao ? <> <span class="tag azul">reposição</span></> : a.avulsa ? <> <span class="tag azul">avulsa</span></> : ""}{a.pausa && !a.estado ? <> <span class="tag neutro">pausa</span></> : ""}</div>
                {a.bloqueio && !a.estado ? <div class="dica-bloq">Dia de bloqueio: use Cancelada (não repõe)</div> : ""}
              </div>
              <form method="post" action="/agenda/marcar">
                {marcaHidden(a)}
                {a.estado ? <><span class={`tag ${COR[a.estado] ?? ""}`}>{ROT[a.estado] ?? ""}</span>
                  <button name="estado" value="" class="claro btn-estado">Desfazer</button></> : <>
                  <button name="estado" value="feita" class="btn-estado feita">Feita</button>
                  <button name="estado" value="faltou" class="btn-estado faltou">Faltou</button>
                  {a.reposicao ? <button name="estado" value="cancelada" class="btn-estado cancelada" title="Só cancela esta reposição: não gera outra">Cancelar reposição</button> : <>
                    <button name="estado" value="desmarcou" class="btn-estado desmarcou">Desmarcou (repõe)</button>
                    <button name="estado" value="cancelada" class="btn-estado cancelada">Cancelada (não repõe)</button></>}
                </>}
              </form>
            </div>
          )) : <p class="muted" style="margin:0">{hojeDia === 7 ? "Domingo: sem aulas na agenda." : "Nenhuma aula hoje."}</p>}
        </div>
      ) : ""}

      <div class={`card controle${d.atual ? " mt" : ""}`} id="controle">
        <form method="get" action="/agenda" class="linha controle-form" id="f-controle">
          <input type="hidden" name="semana" value={segunda} />{todas ? <input type="hidden" name="todas" value="1" /> : ""}
          <div class="campo"><label for="sel-aluno">Controle do aluno</label>
            <select name="aluno" id="sel-aluno"><option value="">Escolha um aluno</option>
              {d.comAulas.map((c) => <option value={String(c.id)} selected={!!controle && controle.id === c.id}>{c.nome}</option>)}
              {controle && !d.comAulas.some((c) => c.id === controle.id) ? <option value={String(controle.id)} selected>{controle.nome} ({controle.status ?? "None"})</option> : ""}
            </select></div>
          <button class="claro">Ver</button>
        </form>
        {controle ? (
          <div class="painel-aluno">
            <div class={`saldo ${controle.saldo ? "deve" : ""}`}>
              <div class="saldo-n" aria-hidden="true">{controle.saldo}</div>
              <div><strong>Reposições a fazer: {controle.saldo}</strong>
                <div class="muted">agendadas: {controle.agendadas} · desmarcou no total: {controle.devidas} · usadas no total (feita ou faltou): {controle.usadas}</div></div>
            </div>
            <div class="linha mes-nav">
              <a class="btn claro pequeno" href={`/agenda?semana=${segunda}${tds}&aluno=${controle.id}&mes=${controle.mes_ant}`} aria-label="Mês anterior">←</a>
              <strong>{controle.mes_txt}</strong>
              <a class="btn claro pequeno" href={`/agenda?semana=${segunda}${tds}&aluno=${controle.id}&mes=${controle.mes_prox}`} aria-label="Próximo mês">→</a>
            </div>
            <div class="contadores">
              <div class="contador feita"><b>{controle.feitas}</b><span>Feitas</span></div>
              <div class="contador faltou"><b>{controle.faltou}</b><span>Faltou</span></div>
              <div class="contador desmarcou"><b>{controle.desmarcou}</b><span>Desmarcou</span></div>
              <div class="contador cancelada"><b>{controle.canceladas}</b><span>Canceladas</span></div>
              <div class="contador reposta"><b>{controle.repostas}</b><span>Repostas</span></div>
              {r && r.contratadas ? <>
                <div class="contador"><b>{r.contratadas}</b><span>Contratadas</span></div>
                <div class="contador"><b>{r.previstas}</b><span>Previstas</span></div>
                <div class={`contador ${r.completo ? "feita" : ""}`}><b>{r.faltam}</b><span>{r.completo ? "Mês 100%" : "Faltam"}</span></div>
                {r.passou ? <div class="contador cancelada"><b>+{r.passou}</b><span>Passou{r.custo_extra ? ` (${moeda(r.custo_extra)} CIA)` : ""}</span></div> : ""}
              </> : ""}
            </div>
            <ul class="aulas-aluno">
              {controle.linhas.length ? controle.linhas.map((l) => (
                <li class={`aula-linha ${l.estado}`}><span class="quando">{l.dia} {l.data_br}{l.hora !== null && l.hora !== undefined ? ` · ${h2(l.hora)}h` : ""}</span>
                  <span class={`tag ${COR[l.estado] ?? ""}`}>{ROT[l.estado] ?? ""}</span>{l.reposicao ? <> <span class="tag neutro">reposição</span></> : ""}
                  {l.repoe_br ? <span class="muted">repõe a de {l.repoe_br}</span> : ""}
                  {l.local ? <span class="muted">{l.local}</span> : ""}
                  {l.estado === "desmarcou" ? (
                    <div class="acoes-linha">
                      <button type="button" class="claro pequeno btn-repor-evento" data-aluno={String(controle.id)} data-evento={String(l.eid)} data-quando={l.data_br}>Agendar reposição</button>
                      <form method="post" action={`/agenda/evento/${l.eid}/nao-repoe`} class="inline" data-confirmar={`A aula de ${l.data_br} não será reposta: ela sai das reposições a fazer. Continuar?`}>
                        <input type="hidden" name="semana" value={segunda} /><input type="hidden" name="todas" value={String(todas)} />{ctl}<button class="claro pequeno">Não repõe</button></form>
                      <form method="post" action={`/agenda/evento/${l.eid}/excluir`} class="inline" data-confirmar={`Desfazer a marcação de ${l.data_br}? Dá para restaurar em Dados.`}>
                        <input type="hidden" name="semana" value={segunda} /><input type="hidden" name="todas" value={String(todas)} />{ctl}<button class="claro pequeno">Desfazer</button></form>
                    </div>
                  ) : ""}</li>
              )) : <li class="muted">Nenhuma aula marcada neste mês.</li>}
            </ul>
            <div class="linha mt-p">
              <button type="button" id="btn-repor" data-aluno={String(controle.id)}>Agendar reposição</button>
              <a class="btn claro" href={`/clientes/${controle.id}`}>Abrir ficha</a>
            </div>
          </div>
        ) : ""}
      </div>

      <div class="agenda-nav mt">
        <a class="btn claro" href={`/agenda?semana=${d.anterior}${d.extra}`}>← Semana anterior</a>
        <a class={`btn ${d.atual ? "" : "claro"}`} href={`/agenda?semana=${d.hojeSegunda}${d.extra}`}>Esta semana</a>
        <a class="btn claro" href={`/agenda?semana=${d.proxima}${d.extra}`}>Próxima →</a>
      </div>
      <div class="linha" style="justify-content:space-between;margin-top:10px">
        <strong>{d.semanaTxt}</strong>
        <a href={`/agenda?semana=${segunda}${todas ? "" : "&todas=1"}${d.extraAluno}`}>{todas ? "Só horários com aula" : "Ver todos os horários"}</a>
      </div>
      {d.vazia ? (
        <div class="card mt copiar-grade">
          <p>Sua agenda está vazia. Copie os alunos da Grade uma vez — cada aluno vira um horário só, sem repetir por local.</p>
          <form method="post" action="/agenda/copiar-grade" data-confirmar="Copiar os alunos da Grade para a Agenda? Isso é feito uma vez só.">
            <input type="hidden" name="semana" value={segunda} /><input type="hidden" name="todas" value={String(todas)} />{ctl}
            <button>Copiar da Grade</button>
          </form>
        </div>
      ) : ""}

      <div class="legenda mt">
        <span><i class="l-feita"></i> feita</span><span><i class="l-faltou"></i> faltou</span><span><i class="l-desmarcou"></i> desmarcou (repõe)</span><span><i class="l-cancelada"></i> cancelada (não repõe)</span>
        <span><i class="l-pausa"></i> mês pulado</span><span><i class="l-pendente"></i> passou sem marcar</span><span><i class="l-futura"></i> ainda vai acontecer</span>
      </div>
      <p class="muted lote-info" hidden>Escolha o pincel na barra de baixo e toque nos nomes da grade ou nas aulas de hoje. Na dupla, tocar fora dos nomes marca os dois. Nada é salvo até apertar Salvar.</p>
      {!d.temAulas ? <p class="muted" style="margin:6px 0 0">Nenhuma aula nesta semana. Use <b>+ Incluir aula</b> ou toque em um horário para escolher o aluno.</p> : ""}
      {grade(d)}

      <dialog id="dlg-horario">
        <h2 id="h-titulo">Horário</h2>
        <section id="h-alunos" class="h-secao"></section>
        <section class="h-secao h-fixo">
          <h3>Horário fixo (toda semana)</h3>
          <form method="post" action="/agenda/horario" id="f-horario">
            <input type="hidden" name="dia" /><input type="hidden" name="hora" />
            <input type="hidden" name="semana" value={segunda} /><input type="hidden" name="todas" value={String(todas)} />{ctl}
            <div class="campo"><label for="h-aluno1">Aluno</label>
              <select name="aluno1" id="h-aluno1"><option value="">— sem aula —</option>{d.clientes.map((c) => <option value={String(c.id)} data-local={c.local || ""}>{c.nome}</option>)}</select></div>
            <div class="campo"><label for="h-aluno2">2º aluno (opcional)</label>
              <select name="aluno2" id="h-aluno2"><option value="">— ninguém —</option>{d.clientes.map((c) => <option value={String(c.id)}>{c.nome}</option>)}</select></div>
            <input type="hidden" name="extras" id="h-extras" value="" />
            <p class="muted" id="h-extras-txt" hidden></p>
            <div class="campo"><label for="h-local">Local</label>
              <select name="local" id="h-local"><option value="">Escolha o local</option>{d.locais.map((l) => <option>{l}</option>)}</select></div>
            <div class="linha"><button>Salvar</button><button type="button" class="claro" data-fechar="">Fechar</button></div>
          </form>
        </section>
      </dialog>

      <dialog id="dlg-incluir">
        <h2 data-titulo="">Incluir aula</h2>
        <form method="post" action="/agenda/incluir" id="f-incluir">
          <input type="hidden" name="semana" value={segunda} /><input type="hidden" name="todas" value={String(todas)} />{ctl}
          <input type="hidden" name="repoe_evento_id" value="" />
          <p class="muted" id="repoe-aviso" hidden></p>
          <div class="campo"><label>Aluno</label>
            <select name="cliente_id" required><option value="">—</option>{d.clientes.map((c) => <option value={String(c.id)} data-local={c.local || ""}>{c.nome}</option>)}</select></div>
          <div class="campo opcoes">
            <label><input type="radio" name="repetir" value="1" checked /> Toda semana (horário fixo, vai para a Grade)</label>
            <label><input type="radio" name="repetir" value="0" /> Só neste dia (aula avulsa)</label>
          </div>
          <div class="campo" id="campo-dia">
            <label>Dias e hora</label>
            <div id="linhas-horario">
              <div class="linha-horario">
                <div class="dias-chips" role="group" aria-label="Dias da semana">
                  {[1, 2, 3, 4, 5, 6].map((n) => <label class="chip-dia"><input type="checkbox" value={String(n)} /><span>{DIAS_CURTO[n]}</span></label>)}
                </div>
                <select class="hora-linha" aria-label="Hora"><option value="">Hora</option>{Array.from({ length: 19 }, (_, i) => i + 5).map((n) => <option value={String(n)}>{h2(n)}h</option>)}</select>
                <button type="button" class="claro pequeno tirar-linha" aria-label="Tirar este horário" hidden>Tirar</button>
              </div>
            </div>
            <button type="button" class="claro pequeno" id="mais-horario">+ outro horário</button>
          </div>
          <div id="campo-avulsa" hidden>
            <div class="duas">
              <div class="campo" id="campo-data"><label>Data</label><input type="date" name="data" value={d.dataPadrao} /></div>
              <div class="campo"><label>Hora</label>
                <select name="hora"><option value="">—</option>{Array.from({ length: 19 }, (_, i) => i + 5).map((n) => <option value={String(n)}>{h2(n)}h</option>)}</select></div>
            </div>
            <div class="campo opcoes"><label><input type="checkbox" name="reposicao" value="1" /> É reposição (desconta do saldo do aluno quando fica Feita ou Faltou)</label></div>
          </div>
          <div class="campo"><label>Local</label>
            <select name="local" required>{d.locais.map((l) => <option>{l}</option>)}</select></div>
          <div class="linha"><button>Incluir</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
        </form>
      </dialog>

      <div class="barra-lote" id="barra-lote" hidden role="region" aria-label="Marcar várias aulas"
        data-semana={segunda} data-todas={String(todas)} data-aluno={controle ? String(controle.id) : ""} data-mes={controle ? controle.mes : ""}>
        <div class="interno">
          <div class="pinceis" role="group" aria-label="Pincel">
            <button type="button" class="btn-estado feita" data-pincel="feita" aria-pressed="true">Feita</button>
            <button type="button" class="btn-estado faltou" data-pincel="faltou" aria-pressed="false">Faltou</button>
            <button type="button" class="btn-estado desmarcou" data-pincel="desmarcou" aria-pressed="false">Desmarcou</button>
            <button type="button" class="btn-estado cancelada" data-pincel="cancelada" aria-pressed="false">Cancelada</button>
            <button type="button" class="btn-estado claro" data-pincel="" aria-pressed="false">Limpar</button>
          </div>
          <div class="acoes-lote">
            <button type="button" class="verde" id="lote-salvar" disabled>Salvar (0)</button>
            <button type="button" class="claro" id="lote-cancelar">Cancelar</button>
          </div>
          <span class="muted" id="lote-aviso" hidden>Máximo de 300 aulas por vez.</span>
        </div>
      </div>
      {raw(SCRIPT_AGENDA)}
      <DlgLocal ctx={ctx} />
    </Base>
  );
}

/** Os campos de volta que toda rota da Agenda recebe (semana, todas, aluno e mês do painel). */
function volta(f: Form) {
  return { semana: txt(f, "semana"), todas: intForm(f, "todas"), aluno: txt(f, "aluno"), mes: txt(f, "mes") };
}

/** int() do Python para um valor de JSON (número, texto ou booleano); o resto é erro. */
function intJson(v: unknown): number | null {
  if (typeof v === "boolean") return v ? 1 : 0;
  if (typeof v === "number") return Number.isFinite(v) ? Math.trunc(v) : null;
  if (typeof v === "string") {
    try {
      return intPy(v);
    } catch {
      return null;
    }
  }
  return null;
}

export function rotasAgenda(app: Hono<Ambiente>): void {
  app.get("/agenda", async (c) => {
    const todas = intQuery(c, "todas");
    const b = banco(c);
    const u = new URL(c.req.url);
    const [ctx, d] = await Promise.all([contextoBase(b, c.req.raw),
      dados(b, c.req.query("semana") ?? "", todas, c.req.query("aluno") ?? "", c.req.query("mes") ?? "", u.pathname + (u.search.length > 1 ? u.search : ""))]);
    return c.html(String(<TelaAgenda ctx={ctx} d={d} />));
  });

  app.get("/agenda/pendentes", async (c) => {
    const h = hoje();
    const inicio = somarDias(inicioSemana(h, h), -28);
    const n = [0, 0, 0, 0];
    for (const a of await aulasDaSemana(banco(c), inicio, h, 4)) {
      if (a.data < h && !a.estado && !a.bloqueio && !a.pausa) n[Math.floor(diasEntre(inicio, a.data) / 7)] += 1;
    }
    const semanas = [];
    for (const w of [3, 2, 1, 0]) {
      const seg = somarDias(inicio, 7 * w);
      if (n[w]) semanas.push({ segunda: seg, txt: `${ddmm(seg)} a ${ddmm(somarDias(seg, 5))}`, n: n[w] });
    }
    return c.json({ semanas });
  });

  app.post("/agenda/marcar", async (c) => {
    const b = banco(c);
    const f = await lerForm(c);
    const v = volta(f), data = txt(f, "data"), estado = txt(f, "estado"), local = txt(f, "local");
    const cid = intForm(f, "cliente_id"), hora = intForm(f, "hora"), avulsa = intForm(f, "avulsa"), reposicao = intForm(f, "reposicao");
    const url = urlAgenda(v.semana || data, v.todas, v.aluno, v.mes, hoje()) + (txt(f, "ancora") === "hoje" ? "#hoje" : "");   // o card Hoje volta para o próprio card
    const d = fromIsoPy(data.trim());
    if (!d) return voltar(c, url, null, "Data inválida.");
    if (estado && !(estado in ESTADO_TIPO)) return voltar(c, url, null, "Situação inválida.");
    if (!(hora >= 5 && hora <= 23)) return voltar(c, url, null, "Hora inválida.");
    const cli = await b.um("SELECT nome FROM clientes WHERE id=? AND excluido_em IS NULL", [cid]);
    if (!cli) return voltar(c, url, null, "Aluno não encontrado.");
    const [cmds, trocadas] = await gravarMarcas(b, [[cid, d, hora, estado, descricaoMarca(d, hora, local, !!avulsa, !!reposicao)]]);
    await b.batch(cmds);
    const p = primeiroNome(cli.nome);
    if (trocadas.size || (reposicao && estado === "cancelada")) return voltar(c, url, `${p}: reposição cancelada (não gera outra reposição).`);
    return voltar(c, url, estado ? `${p}: ${ESTADO_MSG[estado]}.` : `${p}: marcação desfeita.`);
  });

  app.post("/agenda/marcar-lote", async (c) => {
    const b = banco(c);
    const f = await lerForm(c);
    const v = volta(f), h = hoje();
    let lista: unknown;
    try {
      lista = JSON.parse(txt(f, "itens"));
    } catch {
      lista = null;
    }
    if (!Array.isArray(lista) || !lista.length) return voltar(c, urlAgenda(v.semana, v.todas, v.aluno, v.mes, h), null, "Nenhuma aula para salvar.");
    const prim = lista[0];
    const url = urlAgenda(v.semana || (prim && typeof prim === "object" && !Array.isArray(prim) ? String(prim.data ?? "") : ""), v.todas, v.aluno, v.mes, h);
    if (lista.length > 300) return voltar(c, url, null, "Muitas aulas de uma vez (máximo 300).");
    const marcas = new Map<string, [number, string, number, string, string]>();   // aluno|data|hora -> item; repetido: vale o último
    for (const it of lista) {
      if (!it || typeof it !== "object" || Array.isArray(it)) return voltar(c, url, null, "Dados inválidos.");
      const o = it as Record<string, unknown>;
      const d = fromIsoPy(String(o.data ?? "").trim());
      if (!d) return voltar(c, url, null, "Data inválida.");
      const estado = verdadePy(o.estado) ? o.estado : "";
      if (typeof estado !== "string" || !(estado === "" || estado in ESTADO_TIPO)) return voltar(c, url, null, "Situação inválida.");
      const cid = intJson(o.cliente_id), hora = intJson(o.hora);
      if (cid === null || hora === null) return voltar(c, url, null, "Dados inválidos.");
      if (!(hora >= 5 && hora <= 23)) return voltar(c, url, null, "Hora inválida.");
      marcas.set(`${cid}|${d}|${hora}`, [cid, d, hora, estado, descricaoMarca(d, hora, verdadePy(o.local) ? String(o.local) : "", verdadePy(o.avulsa), verdadePy(o.reposicao))]);
    }
    const ids = [...new Set([...marcas.values()].map((m) => m[0]))];
    const achados = await b.query("SELECT id FROM clientes WHERE excluido_em IS NULL AND id IN (SELECT value FROM json_each(?))", [JSON.stringify(ids)]);
    if (achados.length !== ids.length) return voltar(c, url, null, "Aluno não encontrado.");
    const [cmds, trocadas] = await gravarMarcas(b, [...marcas.values()]);
    await b.batch(cmds);
    for (const k of trocadas) marcas.get(k)![3] = "cancelada";   // desmarcou numa reposição: contou como cancelada
    const n: Record<string, number> = Object.fromEntries(Object.keys(ESTADO_TIPO).map((e) => [e, [...marcas.values()].filter((m) => m[3] === e).length]));
    const feitas = Object.values(n).reduce((s, x) => s + x, 0);
    const partes = [n.feita ? `${n.feita} ${n.feita === 1 ? "feita" : "feitas"}` : "", n.faltou ? `${n.faltou} ${n.faltou === 1 ? "faltou" : "faltaram"}` : "",
      n.desmarcou ? `${n.desmarcou} ${n.desmarcou === 1 ? "desmarcou" : "desmarcaram"}` : "", n.cancelada ? `${n.cancelada} ${n.cancelada === 1 ? "cancelada" : "canceladas"}` : "",
      marcas.size > feitas ? plural(marcas.size - feitas, "desfeita", "desfeitas") : ""].filter(Boolean);
    if (!feitas) return voltar(c, url, `${plural(marcas.size, "marcação desfeita", "marcações desfeitas")}.`);
    return voltar(c, url, `${plural(feitas, "aula marcada", "aulas marcadas")}: ${partes.join(", ")}.`);
  });

  app.post("/agenda/incluir", async (c) => {
    const b = banco(c);
    const f = await lerForm(c);
    const v = volta(f), h = hoje();
    const url = urlAgenda(v.semana, v.todas, v.aluno, v.mes, h);
    const cid = intForm(f, "cliente_id"), dia = intForm(f, "dia"), hora = intForm(f, "hora"), repetir = intForm(f, "repetir", 1), reposicao = intForm(f, "reposicao");
    const dias = intsForm(f, "dias"), horas = intsForm(f, "horas");
    const local = txt(f, "local").trim(), data = txt(f, "data"), repoe = txt(f, "repoe_evento_id");
    const cli = await b.um("SELECT nome FROM clientes WHERE id=? AND excluido_em IS NULL AND status='ativo'", [cid]);
    if (!cli) return voltar(c, url, null, "Escolha um aluno ativo.");
    if (!local) return voltar(c, url, null, "Escolha o local.");
    let pares: [number, number][];
    if (repetir && dias.length) {
      if (dias.length !== horas.length) return voltar(c, url, null, "Escolha o dia e a hora de cada horário.");
      pares = [];
      dias.forEach((d, i) => { if (!pares.some(([a, z]) => a === d && z === horas[i])) pares.push([d, horas[i]]); });
      if (pares.length > 12) return voltar(c, url, null, "No máximo 12 horários de uma vez.");
    } else pares = [[dia, hora]];
    if (!pares.every(([, hr]) => hr >= 5 && hr <= 23)) return voltar(c, url, null, "Escolha a hora (05h a 23h).");
    const nome = cli.nome as string;
    if (repetir) {   // horário fixo: soma o aluno aos que já estão (cabem max_alunos) e avisa a Grade
      if (!pares.every(([d]) => d >= 1 && d <= 6)) return voltar(c, url, null, "Escolha o dia (segunda a sábado).");
      const g = await GravaAgenda.abrir(b, h);
      const ja: [number, number][] = [], cheios: [number, number][] = [], mudam: [number, number, Map<number, string>][] = [], novos: [number, number][] = [];
      for (const [d, hr] of pares) {
        const locais = g.membros(d, hr);
        if (locais.get(cid) === local) ja.push([d, hr]);
        else if (locais.has(cid)) mudam.push([d, hr, locais]);
        else if (locais.size >= g.cabe) cheios.push([d, hr]);
        else novos.push([d, hr]);
      }
      if (mudam.length || novos.length) {
        for (const [d, hr, locais] of mudam) {   // já está em outro local (raro): troca o local, com a Grade
          locais.set(cid, local);
          g.definirHorario(d, hr, [...locais.keys()], locais);
        }
        if (novos.length) {   // todos os horários novos: 1 INSERT na Agenda + 1 upsert na Grade
          g.inserirFixos(novos.map(([d, hr]) => [cid, d, hr, local]), g.vigencias([cid]));
          g.gradeOcuparLote(cid, nome, novos.map(([d, hr]) => [d, local, hr]));
        }
        await b.batch(g.cmds);
      }
      const q = (lst: [number, number, ...unknown[]][]) => lst.map(([d, hr]) => quando(d, hr)).join(", ");
      const aviso = novos.length || mudam.length ? await avisoDeslocamento(b, g, [...novos, ...mudam].map(([d, hr]) => [d, hr, local]), cid) : "";
      if (pares.length === 1) {
        const qd = q(pares);
        if (cheios.length) return voltar(c, url, null, `${qd} já tem ${g.cabe} alunos.`);
        if (ja.length) return voltar(c, url, `${nome} já está no horário fixo de ${qd} (${local}).`);
        const acao = mudam.length ? `agora fica em ${local} no horário fixo de ${qd}` : `entrou no horário fixo de ${qd} (${local})`;
        return voltar(c, url, `${nome} ${acao}. A Grade também foi atualizada.${aviso}`);
      }
      const p = primeiroNome(nome);
      const frases = [novos.length ? `${p} entrou em ${q(novos)} (${local}).` : "", mudam.length ? `${p} agora fica em ${local} em ${q(mudam)}.` : "",
        ja.length ? `${q(ja)} já ${ja.length === 1 ? "estava" : "estavam"}.` : "", cheios.length ? `${q(cheios)} já ${cheios.length === 1 ? "tem" : "têm"} ${g.cabe} alunos.` : ""];
      const texto = frases.filter(Boolean).join(" ") + aviso;
      return cheios.length && !(novos.length || mudam.length || ja.length) ? voltar(c, url, null, texto) : voltar(c, url, texto);
    }
    const d = fromIsoPy(data.trim());
    if (!d) return voltar(c, url, null, "Escolha a data da aula avulsa.");
    if (diaDaSemana(d) === 7) return voltar(c, url, null, "Domingo não aparece na agenda.");
    let origem: Linha | undefined;   // a desmarcação que esta reposição repõe (só informativo)
    if (reposicao && idValido(repoe)) {
      origem = await b.um("SELECT id, data FROM cliente_eventos WHERE id=? AND cliente_id=? AND tipo='desmarcou' AND excluido_em IS NULL", [idValido(repoe), cid]);
      if (!origem) return voltar(c, url, null, "Essa aula desmarcada não existe mais.");
    }
    const qd = `${DIAS_CURTO[diaDaSemana(d)]} ${ddmm(d)} às ${h2(hora)}h`;
    const [dupla, semana, cabe] = await Promise.all([
      b.um("SELECT 1 AS um FROM agenda_avulsas WHERE cliente_id=? AND data=? AND hora=? AND excluido_em IS NULL LIMIT 1", [cid, d, hora]),
      aulasDaSemana(b, inicioSemana(d, h), h), maxAlunos(b),
    ]);
    if (dupla) return voltar(c, url, null, `${nome} já tem aula avulsa em ${qd}.`);   // 2º clique no salvar: não duplica
    const naHora = new Map<number, Aula>();
    for (const a of semana) if (a.data === d && a.hora === hora) naHora.set(a.cliente_id, a);
    const minha = naHora.get(cid);
    const fora = (a: Aula) => a.situacao === "desmarcou" || a.situacao === "cancelada";
    if (minha && !minha.avulsa && !fora(minha)) return voltar(c, url, null, `${nome} já tem aula fixa em ${qd}.`);
    if (reposicao && minha && !minha.avulsa) return voltar(c, url, null, `${qd} é o horário fixo de ${nome}: marque a reposição em outro dia ou hora.`);
    if (minha && !minha.avulsa) {
      return voltar(c, url, null, `${qd} é o horário fixo de ${nome} (marcado como ${minha.situacao}). Se ele vem mesmo assim, toque no horário e marque Feita.`);
    }
    const outros = [...naHora].filter(([x, a]) => x !== cid && !fora(a)).map(([, a]) => a);
    if (outros.length >= cabe) return voltar(c, url, null, `Horário cheio: ${qd} já tem ${outros.map((a) => a.nome).join(" e ")}.`);
    await b.run("INSERT INTO agenda_avulsas (cliente_id, data, hora, local, reposicao, repoe_evento_id) VALUES (?,?,?,?,?,?)",
      [cid, d, hora, local, reposicao ? 1 : 0, origem ? origem.id : null]);
    return voltar(c, urlAgenda(d, v.todas, v.aluno, v.mes, h), `${reposicao ? "Reposição" : "Aula avulsa"} de ${nome} em ${ddmm(d)} às ${h2(hora)}h`
      + (origem ? ` (repõe a de ${dataBr(origem.data).slice(0, 5)}).` : "."));
  });

  app.post("/agenda/horario", async (c) => {
    const b = banco(c);
    const f = await lerForm(c);
    const v = volta(f), h = hoje();
    const url = urlAgenda(v.semana, v.todas, v.aluno, v.mes, h);
    const dia = intForm(f, "dia"), hora = intForm(f, "hora"), local = txt(f, "local").trim();
    if (!(dia >= 1 && dia <= 6)) return voltar(c, url, null, "Escolha o dia (segunda a sábado).");
    if (!(hora >= 5 && hora <= 23)) return voltar(c, url, null, "Escolha a hora (05h a 23h).");
    let ids: number[] = [];
    for (const t of [txt(f, "aluno1").trim(), txt(f, "aluno2").trim()]) {
      if (!t) continue;
      if (!/^[0-9]+$/.test(t)) return voltar(c, url, null, "Escolha um aluno ativo.");
      if (!ids.includes(Number(t))) ids.push(Number(t));   // o mesmo aluno nos dois campos vale uma vez
    }
    const g = await GravaAgenda.abrir(b, h);
    const ativo = (x: number) => { const k = g.clientes.get(x); return !!k && k.excluido_em == null && k.status === "ativo"; };
    if (ids.length) {
      if (!ids.every(ativo)) return voltar(c, url, null, "Escolha um aluno ativo.");
      if (!local) return voltar(c, url, null, "Escolha o local.");
    }
    const atuais = g.membros(dia, hora);
    // com o limite maior, quem já está no horário além dos 2 do seletor vem em `extras` e continua, no local dele
    const mais = ids.length ? txt(f, "extras").split(",").filter((x) => /^[0-9]+$/.test(x.trim()) && atuais.has(Number(x.trim())) && !ids.includes(Number(x.trim())))
      .map((x) => Number(x.trim())) : [];
    const locais = new Map<number, string>([...ids.map((x) => [x, local] as [number, string]), ...mais.map((x) => [x, atuais.get(x)!] as [number, string])]);
    ids = [...ids, ...mais];
    if (ids.length > g.cabe && ids.some((x) => !atuais.has(x))) {   // aluno novo passando do limite: recusa sem mexer em ninguém
      return voltar(c, url, null, `${quando(dia, hora)}: cabem ${g.cabe} alunos (Configurações > Agenda). Nada foi gravado.`);
    }
    g.definirHorario(dia, hora, ids, locais);
    await b.batch(g.cmds);
    if (!ids.length) return voltar(c, url, `${quando(dia, hora)} ficou sem aula.`);
    return voltar(c, url, `${quando(dia, hora)}: ${nomesCurtos(ids.map((x) => g.clientes.get(x)!.nome)).join(" + ")} (${local}).`);
  });

  app.post("/agenda/copiar-grade", async (c) => {
    const b = banco(c);
    const f = await lerForm(c);
    const v = volta(f), h = hoje();
    const url = urlAgenda(v.semana, v.todas, v.aluno, v.mes, h);
    const [tem, ativos, slots, cabe] = await Promise.all([
      b.um("SELECT 1 AS um FROM agenda_fixos WHERE excluido_em IS NULL LIMIT 1"),
      b.query("SELECT id, nome, local FROM clientes WHERE excluido_em IS NULL AND status='ativo' ORDER BY nome"),
      b.query(`SELECT dia, hora, local, cliente_id, TRIM(COALESCE(cliente_nome, '')) AS nome FROM grade_slots
               WHERE status='ocupado' AND dia BETWEEN 1 AND 6 AND hora BETWEEN 5 AND 23 ORDER BY dia, hora, local, tipo_calculo, id`),
      maxAlunos(b),
    ]);
    if (tem) return voltar(c, url, null, "A Agenda já tem horários fixos. Copiar da Grade só vale com a Agenda vazia.");
    const cadastro = new Map(ativos.map((a) => [a.id as number, String(a.local ?? "").trim()]));
    const horarios = new Map<string, Map<number, string[]>>();   // dia-hora -> {aluno: locais onde a Grade tem o aluno}
    const semAluno = new Map<string, string>(), achados = new Map<string, number | null>();
    for (const s of slots) {
      let cid: number | null;
      if (s.cliente_id) cid = cadastro.has(s.cliente_id) ? s.cliente_id : null;   // aluno inativo ou excluído não entra
      else {
        const chave = norm(s.nome);
        if (!achados.has(chave)) achados.set(chave, sugerirCliente(s.nome, ativos));
        cid = achados.get(chave)!;
        if (cid === null && chave && !semAluno.has(chave)) semAluno.set(chave, s.nome);
      }
      if (cid === null) continue;
      const k = `${s.dia}-${s.hora}`;
      if (!horarios.has(k)) horarios.set(k, new Map());
      const m = horarios.get(k)!;
      if (!m.has(cid)) m.set(cid, []);
      m.get(cid)!.push(s.local);
    }
    const linhas: [number, number, number, string][] = [];
    let deFora = 0;
    for (const [k, alunos] of horarios) {
      const [dia, hora] = k.split("-").map(Number);
      for (const cid of [...alunos.keys()].slice(0, cabe)) {   // a Agenda comporta max_alunos por horário
        const locs = alunos.get(cid)!;
        linhas.push([cid, dia, hora, locs.includes(cadastro.get(cid)!) ? cadastro.get(cid)! : locs[0]]);   // prefere o local do cadastro
      }
      deFora += Math.max(alunos.size - 2, 0);
    }
    const nomes = [...semAluno.values()];
    const lista5 = `${nomes.slice(0, 5).join(", ")}${nomes.length > 5 ? "…" : "."}`;
    if (!linhas.length) return voltar(c, url, null, "Não achei alunos ativos na Grade para copiar." + (nomes.length ? ` Nomes sem aluno no CRM: ${lista5}` : ""));
    const g = await GravaAgenda.abrir(b, h);
    g.inserirFixos(linhas);
    await b.batch(g.cmds);
    const n = new Set(linhas.map((l) => `${l[1]}-${l[2]}`)).size;   // um card por horário
    let msg = `${plural(n, "horário copiado", "horários copiados")} da Grade` + (linhas.length !== n ? ` (${plural(linhas.length, "aluno", "alunos")})` : "") + ".";
    if (nomes.length) msg += ` ${plural(nomes.length, "nome não reconhecido", "nomes não reconhecidos")}: ${lista5}`;
    if (deFora) msg += ` ${plural(deFora, "aluno ficou", "alunos ficaram")} de fora (cabem ${cabe} por horário).`;
    return voltar(c, url, msg);
  });

  const eventoAtivo = (b: Banco, eid: number) => b.um("SELECT id, cliente_id, tipo, data FROM cliente_eventos WHERE id=? AND excluido_em IS NULL", [eid]);

  app.post("/agenda/evento/:eid{[0-9]+}/nao-repoe", async (c) => {
    const b = banco(c);
    const eid = Number(c.req.param("eid"));
    const f = await lerForm(c);
    const v = volta(f);
    const e = await eventoAtivo(b, eid);
    const url = urlAgenda(v.semana, v.todas, v.aluno || (e ? e.cliente_id : ""), v.mes || (e ? String(e.data).slice(0, 7) : ""), hoje());
    if (!e || e.tipo !== "desmarcou") return voltar(c, url, null, "Essa aula desmarcada não existe mais.");
    await b.run("UPDATE cliente_eventos SET tipo='cancelada' WHERE id=? AND tipo='desmarcou' AND excluido_em IS NULL", [eid]);
    return voltar(c, url, `Aula de ${dataBr(e.data).slice(0, 5)} agora é Cancelada (não repõe).`);
  });

  app.post("/agenda/evento/:eid{[0-9]+}/excluir", async (c) => {
    const b = banco(c);
    const eid = Number(c.req.param("eid"));
    const f = await lerForm(c);
    const v = volta(f);
    const e = await eventoAtivo(b, eid);
    let url = urlAgenda(v.semana, v.todas, v.aluno || (e ? e.cliente_id : ""), v.mes || (e ? String(e.data).slice(0, 7) : ""), hoje());
    if (e && txt(f, "destino") === "ficha") url = `/clientes/${e.cliente_id}`;
    if (!e) return voltar(c, url, null, "Esse registro não existe mais.");
    await b.run("UPDATE cliente_eventos SET excluido_em=datetime('now','localtime') WHERE id=? AND excluido_em IS NULL", [eid]);
    return voltar(c, url, "Registro enviado para a lixeira (dá para restaurar em Dados).");
  });

  app.post("/agenda/avulsa/:aid{[0-9]+}/excluir", async (c) => {
    const b = banco(c);
    const aid = Number(c.req.param("aid"));
    const f = await lerForm(c);
    const v = volta(f);
    const url = urlAgenda(v.semana, v.todas, v.aluno, v.mes, hoje());
    const a = await b.um("SELECT cliente_id, data, hora FROM agenda_avulsas WHERE id=? AND excluido_em IS NULL", [aid]);
    if (!a) return voltar(c, url, null, "Essa aula avulsa já foi excluída.");
    const d = dataIso(a.data);
    // a marcação fica se o aluno ainda tem aula nesse dia e hora (outra avulsa viva ou o horário fixo)
    const rows = await b.query(`SELECT id, vigente_de, criado_em, excluido_em FROM agenda_fixos WHERE cliente_id=? AND dia=? AND hora=?
           UNION ALL SELECT NULL, NULL, NULL, NULL FROM agenda_avulsas WHERE cliente_id=? AND data=? AND hora=? AND id != ? AND excluido_em IS NULL`,
    [a.cliente_id, d ? diaDaSemana(d) : 0, a.hora, a.cliente_id, a.data, a.hora, aid]);
    const fica = !d || rows.some((r) => r.id === null || fixoVale(r, d));
    const agora = agoraTxt();
    const cmds: Comando[] = [{ sql: "UPDATE agenda_avulsas SET excluido_em=? WHERE id=?", params: [agora, aid] }];
    if (!fica) cmds.push({ sql: `UPDATE cliente_eventos SET excluido_em=? WHERE cliente_id=? AND data=? AND hora=? AND excluido_em IS NULL
                                 AND tipo IN (${TIPOS_MARCA})`, params: [agora, a.cliente_id, a.data, a.hora] });
    const g = await b.batch(cmds);
    const n = fica ? 0 : g[1].mudancas;
    return voltar(c, url, "Aula avulsa" + (n ? " e a marcação dela foram" : " enviada") + " para a lixeira (dá para restaurar em Dados).");
  });
}

