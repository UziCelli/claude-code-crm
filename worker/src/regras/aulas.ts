/**
 * Aulas da Agenda: a semana (fixos + avulsas, com a marcação), reposições, aulas do mês e o painel do aluno
 * (port de app/main.py: aulas_da_semana, saldos_reposicao, resumo_aulas_mes, controle_aluno, gravar_marcas).
 */
import type { Banco } from "../banco/banco.ts";
import type { Comando, Linha } from "../banco/tipos.ts";
import { arred } from "../arred.ts";
import { dataBr } from "../formato.ts";
import { fixoVale, trocadaNoDia } from "./agenda.ts";
import { fasesBloqueio, pausasPorAluno } from "./alunos.ts";
import { ehLocalCia } from "./contas_auto.ts";
import { diaDaSemana, fromIsoPy, numeroDoDia, isoDoDia, somarDias, ultimoDiaDoMes, zeros } from "./datas.ts";
import { DIAS_CURTO } from "./ficha.ts";
import { parametros } from "./parametros.ts";
import { taxasCia } from "./precos.ts";

/** estado na tela -> tipo em cliente_eventos */
export const ESTADO_TIPO: Record<string, string> = { feita: "aula", faltou: "falta", desmarcou: "desmarcou", cancelada: "cancelada" };
export const TIPO_ESTADO: Record<string, string> = Object.fromEntries(Object.entries(ESTADO_TIPO).map(([e, t]) => [t, e]));
/** Para o IN (...) do SQL: tudo o que a Agenda marca. */
export const TIPOS_MARCA = Object.values(ESTADO_TIPO).map((t) => `'${t}'`).join(",");
export const ESTADO_MSG: Record<string, string> = { feita: "aula feita", faltou: "faltou", desmarcou: "desmarcou (repõe)", cancelada: "cancelada (não repõe)" };
export const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const ISO_DATA = /^\d{4}-\d{2}-\d{2}$/;

/** Segunda-feira da semana de uma data ISO (vazia ou inválida: a semana de hoje). */
export function inicioSemana(texto: unknown, hoje: string): string {
  const d = fromIsoPy(String(texto ?? "").trim().slice(0, 10)) ?? hoje;
  return somarDias(d, -(diaDaSemana(d) - 1));
}

export function emBloqueio(fases: [unknown, unknown][], iso: string): boolean {
  return fases.some(([i, f]) => String(i) <= iso && iso <= String(f));
}

/** "AAAA-MM" de 2000 a 2100; senão "". */
export function mesValido(texto: unknown): string {
  const t = String(texto ?? "").trim();
  return /^\d{4}-\d{2}$/.test(t) && Number(t.slice(0, 4)) >= 2000 && Number(t.slice(0, 4)) <= 2100 && Number(t.slice(5)) >= 1 && Number(t.slice(5)) <= 12 ? t : "";
}

/** Id de um campo de texto (vazio ou torto: 0). */
export function idValido(texto: unknown): number {
  const t = String(texto ?? "").trim();
  return /^[0-9]+$/.test(t) && t.length < 10 ? Number(t) : 0;
}

/** Endereço da Agenda; mantém o aluno do painel de controle (e o mês dele). */
export function urlAgenda(semana: unknown, todas: number, aluno: unknown, mes: unknown, hoje: string): string {
  let url = `/agenda?semana=${inicioSemana(semana, hoje)}` + (todas ? "&todas=1" : "");
  if (idValido(aluno)) url += `&aluno=${idValido(aluno)}` + (mesValido(mes) ? `&mes=${mesValido(mes)}` : "");
  return url;
}

export function descricaoMarca(d: string, hora: number, local: string | null, avulsa = false, reposicao = false): string {
  return [`Agenda — ${DIAS_CURTO[diaDaSemana(d)]} ${zeros(hora, 2)}h`, (local ?? "").trim(), reposicao ? "(reposição)" : avulsa ? "(avulsa)" : ""]
    .filter(Boolean).join(" ");
}

/** Minúsculas, sem acento e com espaços simples. */
export function norm(texto: unknown): string {
  return String(texto ?? "").toLowerCase().normalize("NFKD").replace(/\p{Mn}/gu, "").split(/\s+/).filter(Boolean).join(" ");
}

/** Aluno ativo que bate com um nome escrito à mão: nome igual, ou o único que começa com ele ("Ana" -> "Ana Silva"). */
export function sugerirCliente(nome: unknown, clientes: Linha[]): number | null {
  const n = norm(nome);
  if (!n) return null;
  const cands = clientes.filter((c) => !("status" in c) || c.status === "ativo").map((c) => [c.id as number, norm(c.nome)] as const);
  for (const bate of [(x: string) => x === n, (x: string) => x.startsWith(n + " ")]) {
    const achou = cands.filter(([, x]) => bate(x)).map(([i]) => i);
    if (achou.length === 1) return achou[0];
  }
  return null;
}

export interface Aula {
  data: string; dia: number; hora: number; local: string; cliente_id: number; nome: string; telefone: string | null; avulsa: boolean;
  avulsa_id: number | null; reposicao: boolean; repoe: string; estado: string | null; pausa: boolean; situacao: string; bloqueio: boolean;
}

/**
 * Aulas de segunda a sábado: horários fixos que valiam em cada dia (aluno ativo, desde a data de início) + avulsas, com o
 * estado marcado. semanas > 1: várias semanas seguidas com as mesmas leituras. situacao: feita | faltou | desmarcou |
 * cancelada | pausa | pendente (passou sem marcar) | futura.
 */
export async function aulasDaSemana(b: Banco, segunda: string, hoje: string, semanasIn = 1): Promise<Aula[]> {
  const h = hoje, semanas = Math.max(Math.trunc(semanasIn), 1);
  const porSemana = Array.from({ length: semanas }, (_, w) => Object.fromEntries([1, 2, 3, 4, 5, 6].map((n) => [n, somarDias(segunda, 7 * w + n - 1)])) as Record<number, string>);
  const primeiro = porSemana[0][1], ultimo = porSemana[semanas - 1][6];
  // aluno que não está mais ativo: só entra com aula marcada no período (o histórico não some)
  const marcado = `EXISTS (SELECT 1 FROM cliente_eventos e WHERE e.cliente_id=c.id AND e.excluido_em IS NULL
                  AND e.tipo IN (${TIPOS_MARCA}) AND e.data BETWEEN ? AND ?)`;
  const [linhas, marcasRows, avulsas, fases, pausas] = await Promise.all([
    b.query(`SELECT f.dia, f.hora, f.local, f.vigente_de, f.criado_em, f.excluido_em, c.id AS cliente_id, c.nome, c.telefone,
             c.data_inicio, c.status FROM agenda_fixos f JOIN clientes c ON c.id=f.cliente_id
             WHERE (f.excluido_em IS NULL OR substr(f.excluido_em,1,10) >= ?) AND (f.vigente_de IS NULL OR f.vigente_de <= ?)
             AND f.dia BETWEEN 1 AND 6 AND f.hora BETWEEN 5 AND 23
             AND (c.status='ativo' OR ${marcado}) AND c.excluido_em IS NULL ORDER BY f.excluido_em IS NOT NULL, f.id`, [primeiro, ultimo, primeiro, ultimo]),
    b.query(`SELECT cliente_id, data, hora, tipo FROM cliente_eventos WHERE excluido_em IS NULL
             AND tipo IN (${TIPOS_MARCA}) AND data BETWEEN ? AND ? ORDER BY id`, [primeiro, ultimo]),
    b.query(`SELECT a.id, a.data, a.hora, a.local, a.reposicao, c.id AS cliente_id, c.nome, c.telefone, c.status,
             (SELECT o.data FROM cliente_eventos o WHERE o.id=a.repoe_evento_id AND o.excluido_em IS NULL) AS repoe
             FROM agenda_avulsas a JOIN clientes c ON c.id=a.cliente_id
             WHERE a.excluido_em IS NULL AND a.data BETWEEN ? AND ? AND (c.status='ativo' OR ${marcado}) AND c.excluido_em IS NULL`,
    [primeiro, ultimo, primeiro, ultimo]),
    fasesBloqueio(b), pausasPorAluno(b),
  ]);
  const marcas = new Map<string, [number | null, string][]>();   // "aluno|data" -> [(hora, estado)] do mais antigo ao mais novo
  for (const e of marcasRows) {
    const k = `${e.cliente_id}|${e.data}`;
    if (!marcas.has(k)) marcas.set(k, []);
    marcas.get(k)!.push([e.hora, TIPO_ESTADO[e.tipo]]);
  }
  const comHora = new Set<string>();   // marcação desta hora (a da ficha, sem hora, não decide)
  for (const [k, lst] of marcas) for (const [hr] of lst) if (hr !== null && hr !== undefined) comHora.add(`${k}|${hr}`);
  const aulas: (Aula & { ativo: boolean })[] = [];
  const diaDe = new Map<string, number>();
  for (const datas of porSemana) {
    for (const [n, d] of Object.entries(datas)) diaDe.set(d, Number(n));
    const comecam = new Set(linhas.filter((r) => r.vigente_de === datas[r.dia]).map((r) => `${r.cliente_id}|${r.dia}`));
    // mudou de hora no dia em que a aula antiga já foi marcada: nesse dia vale a antiga, e a nova começa na semana seguinte
    const ficou = new Set(linhas.filter((r) => trocadaNoDia(r as never, datas[r.dia], comecam) && fixoVale(r, datas[r.dia])
      && comHora.has(`${r.cliente_id}|${datas[r.dia]}|${r.hora}`)).map((r) => `${r.cliente_id}|${r.dia}`));
    const vistos = new Set<string>();
    for (const r of linhas) {
      const d = datas[r.dia], kd = `${r.cliente_id}|${r.dia}`;
      if (vistos.has(`${r.dia}|${r.hora}|${r.cliente_id}`) || !fixoVale(r, d)   // linha repetida (voltou da lixeira): conta uma vez só
        || (trocadaNoDia(r as never, d, comecam) && !ficou.has(kd))
        || (r.vigente_de === d && ficou.has(kd) && !comHora.has(`${r.cliente_id}|${d}|${r.hora}`))) continue;
      vistos.add(`${r.dia}|${r.hora}|${r.cliente_id}`);
      const ini = String(r.data_inicio ?? "").trim().slice(0, 10);
      if (ISO_DATA.test(ini) && d < ini) continue;
      aulas.push({ data: d, dia: r.dia, hora: r.hora, local: r.local, cliente_id: r.cliente_id, nome: r.nome, telefone: r.telefone, avulsa: false,
        avulsa_id: null, reposicao: false, repoe: "", ativo: r.status === "ativo", estado: null, pausa: false, situacao: "", bloqueio: false });
    }
  }
  for (const r of avulsas) {
    if (!diaDe.has(r.data)) continue;   // domingo (ou data torta) não entra
    aulas.push({ data: r.data, dia: diaDe.get(r.data)!, hora: r.hora, local: r.local, cliente_id: r.cliente_id, nome: r.nome, telefone: r.telefone,
      avulsa: true, avulsa_id: r.id, reposicao: !!r.reposicao, repoe: r.reposicao && r.repoe ? dataBr(r.repoe).slice(0, 5) : "",
      ativo: r.status === "ativo", estado: null, pausa: false, situacao: "", bloqueio: false });
  }
  for (const a of aulas) {
    // vale a marca mais nova do aluno no dia com a mesma hora, ou sem hora (aula lançada pela ficha)
    const lst = marcas.get(`${a.cliente_id}|${a.data}`) ?? [];
    let estado: string | null = null;
    for (let i = lst.length - 1; i >= 0; i--) {
      const [hr, est] = lst[i];
      if (hr === null || hr === undefined || hr === a.hora) {
        estado = est;
        break;
      }
    }
    if (a.reposicao && estado === "desmarcou") estado = "cancelada";   // marcação antiga: na reposição, desmarcou é só cancelar
    a.estado = estado;
    a.pausa = (pausas.get(a.cliente_id) ?? []).some(([i, f]) => i <= a.data && a.data <= f);   // "Pulou o mês" cobre o dia
    a.situacao = a.estado || (a.pausa ? "pausa" : a.data < h ? "pendente" : "futura");
    a.bloqueio = emBloqueio(fases, a.data);
  }
  const fica = aulas.filter((a) => a.ativo || (a.estado && a.data < h)).map(({ ativo: _, ...a }) => a);   // inativo: só o histórico marcado
  const chave = (a: Aula) => [a.data, a.hora, a.nome.toLowerCase()] as const;
  return fica.sort((x, y) => {
    const [a, b2] = [chave(x), chave(y)];
    return a[0] < b2[0] ? -1 : a[0] > b2[0] ? 1 : a[1] - b2[1] || (a[2] < b2[2] ? -1 : a[2] > b2[2] ? 1 : 0);
  });
}

export interface Saldo { devidas: number; usadas: number; saldo: number; agendadas: number; sem_marca: number; a_agendar: number }
const zeroSaldo = (): Saldo => ({ devidas: 0, usadas: 0, saldo: 0, agendadas: 0, sem_marca: 0, a_agendar: 0 });

/** Reposição agendada no horário: avulsa de reposição não excluída do mesmo aluno, data e hora (e = cliente_eventos). */
const NA_REPOSICAO = `EXISTS (SELECT 1 FROM agenda_avulsas r WHERE r.cliente_id=e.cliente_id AND r.data=e.data AND r.hora=e.hora
                  AND r.reposicao=1 AND r.excluido_em IS NULL)`;

/**
 * Reposições de cada aluno, só leitura: devidas (desmarcou de aula normal), usadas (reposição com Feita ou Faltou), saldo,
 * agendadas (de hoje em diante sem marcação), sem_marca e a_agendar. Com ids, devolve todos eles; sem ids, só quem tem algo.
 */
export async function saldosReposicao(b: Banco, idsIn: number[] | null, hoje: string): Promise<Map<number, Saldo>> {
  const ids = idsIn === null ? null : [...new Set(idsIn)];
  const out = new Map<number, Saldo>((ids ?? []).map((c) => [c, zeroSaldo()]));
  if (ids !== null && !ids.length) return out;
  const filtro = (col: string) => (ids !== null ? ` AND ${col} IN (SELECT value FROM json_each(?))` : "");
  const arg = ids !== null ? [JSON.stringify(ids)] : [];
  const marca = (tipos: string) => `(SELECT COUNT(*) FROM cliente_eventos e WHERE e.cliente_id=a.cliente_id AND e.data=a.data AND (e.hora=a.hora OR e.hora IS NULL)
               AND e.excluido_em IS NULL AND e.tipo IN (${tipos}))`;
  const [dev, us] = await Promise.all([
    b.query(`SELECT e.cliente_id, COUNT(*) AS n FROM cliente_eventos e WHERE e.excluido_em IS NULL AND e.tipo='desmarcou' AND NOT ${NA_REPOSICAO}`
      + filtro("e.cliente_id") + " GROUP BY e.cliente_id", arg),
    b.query(`SELECT cliente_id, SUM(CASE WHEN com_af > 0 THEN 1 ELSE 0 END) AS usadas,
             SUM(CASE WHEN com_qualquer = 0 AND data >= ? THEN 1 ELSE 0 END) AS agendadas,
             SUM(CASE WHEN com_qualquer = 0 THEN 1 ELSE 0 END) AS sem_marca
             FROM (SELECT a.cliente_id, a.data, ${marca("'aula','falta'")} AS com_af, ${marca(TIPOS_MARCA)} AS com_qualquer
                   FROM (SELECT DISTINCT cliente_id, data, hora FROM agenda_avulsas WHERE reposicao=1 AND excluido_em IS NULL${filtro("cliente_id")}) a)
             GROUP BY cliente_id`, [hoje, ...arg]),
  ]);
  const de = (c: number) => {
    if (!out.has(c)) out.set(c, zeroSaldo());
    return out.get(c)!;
  };
  for (const r of dev) de(r.cliente_id).devidas = r.n;
  for (const r of us) Object.assign(de(r.cliente_id), { usadas: r.usadas || 0, agendadas: r.agendadas || 0, sem_marca: r.sem_marca || 0 });
  for (const d of out.values()) {
    d.saldo = Math.max(d.devidas - d.usadas, 0);
    d.a_agendar = Math.max(d.saldo - d.sem_marca, 0);
  }
  return out;
}

/** Aulas contratadas no mês pelo plano: Mensalidade Nx = N × semanas; Pacote N = N; outros = null (sem meta). */
export function aulasContratadas(c: Linha, semanas: number): number | null {
  const plano = String(c.plano || "");
  const m = /Mensalidade (\d+)x/.exec(plano);
  if (m) return arred(Number(m[1]) * semanas, 0);
  const p = /Pacote (?:de )?(\d+)/.exec(plano);
  return p ? Number(p[1]) : null;
}

export interface ResumoAluno { id: number; nome: string; contratadas: number | null; previstas: number; feitas: number; faltam: number | null;
  completo: boolean; passou: number; cia: boolean; custo_extra: number }
export interface ResumoMes { mes: string; mes_txt: string; alunos: ResumoAluno[]; total: Record<string, number> }

function totalDe(alunos: ResumoAluno[]): Record<string, number> {
  const total: Record<string, number> = {};
  for (const k of ["contratadas", "previstas", "feitas", "faltam", "passou", "custo_extra"] as const) {
    total[k] = alunos.reduce((s, a) => s + (a[k] || 0), 0);
  }
  total.custo_extra = arred(total.custo_extra, 2);
  return total;
}

/** Aulas do mês de cada aluno ativo (contratadas, previstas, feitas, faltam, passou e o custo extra na CIA). */
export async function resumoAulasMes(b: Banco, mes: string, hoje: string, ids?: Set<number>): Promise<ResumoMes> {
  const todos = await b.memo(`resumo-aulas|${mes}|${hoje}`, () => calcularResumo(b, mes, hoje));
  if (!ids) return todos;
  const alunos = todos.alunos.filter((a) => ids.has(a.id));
  return { ...todos, alunos, total: totalDe(alunos) };
}

async function calcularResumo(b: Banco, mes: string, hoje: string): Promise<ResumoMes> {
  const ano = Number(mes.slice(0, 4)), m = Number(mes.slice(5, 7));
  const primeiro = `${mes}-01`, ultimo = `${mes}-${zeros(ultimoDiaDoMes(ano, m), 2)}`;
  const segunda = somarDias(primeiro, -(diaDaSemana(primeiro) - 1));
  const semanas = Math.floor((numeroDoDia(ultimo)! - numeroDoDia(segunda)!) / 7) + 1;
  const [aulas, feitasRows, par, [taxaCia, ciaMax], pessoasRows, clientes] = await Promise.all([
    aulasDaSemana(b, segunda, hoje, semanas),
    b.query("SELECT cliente_id, COUNT(*) AS n FROM cliente_eventos WHERE tipo='aula' AND excluido_em IS NULL AND substr(data,1,7)=? GROUP BY cliente_id", [mes]),
    parametros(b, "agenda"), taxasCia(b),
    b.query("SELECT id, pessoas FROM clientes WHERE excluido_em IS NULL"),
    b.query("SELECT id, nome, plano, pessoas FROM clientes WHERE excluido_em IS NULL AND status='ativo' ORDER BY nome"),
  ]);
  const previstas = new Map<number, number>(), locais = new Map<number, [string, string, number][]>(), juntos = new Map<string, Set<number>>();
  for (const a of aulas) {
    if (a.data.slice(0, 7) !== mes || a.avulsa || a.pausa || a.bloqueio) continue;
    previstas.set(a.cliente_id, (previstas.get(a.cliente_id) ?? 0) + 1);
    if (!locais.has(a.cliente_id)) locais.set(a.cliente_id, []);
    locais.get(a.cliente_id)!.push([a.local, a.data, a.hora]);
    const k = `${a.data}|${a.hora}`;
    if (!juntos.has(k)) juntos.set(k, new Set());
    juntos.get(k)!.add(a.cliente_id);
  }
  const feitas = new Map(feitasRows.map((r) => [r.cliente_id as number, r.n as number]));
  const semanasPlano = Number(par.semanas_contratadas || 4);
  const pessoasDe = new Map(pessoasRows.map((r) => [r.id as number, Math.max(Math.trunc(Number(r.pessoas || 1)), 1)]));
  // R$ de uma aula da CIA que cabe ao aluno: a CIA cobra pelo nº de pessoas no horário e a dupla divide (média das aulas dele)
  const parteDaAula = (cid: number, lst: [string, string, number][]) => {
    const partes = lst.map(([, data, hora]) => {
      const quem = juntos.get(`${data}|${hora}`) ?? new Set([cid]);
      const n = [...quem].reduce((s, x) => s + (pessoasDe.get(x) ?? 1), 0);
      return (taxaCia.get(Math.min(n, ciaMax || n)) ?? 0) * (pessoasDe.get(cid) ?? 1) / n;
    });
    return partes.length ? partes.reduce((s, x) => s + x, 0) / partes.length : 0;
  };
  const alunos: ResumoAluno[] = [];
  for (const c of clientes) {
    const contr = aulasContratadas(c, semanasPlano), prev = previstas.get(c.id) ?? 0, feit = feitas.get(c.id) ?? 0;
    if (!(contr || prev || feit)) continue;
    const lst = locais.get(c.id) ?? [];
    const naCia = lst.filter((x) => ehLocalCia(x[0]));
    const cia = lst.length > 0 && naCia.length * 2 > lst.length;   // a maioria das aulas é na CIA
    const passou = contr ? Math.max(Math.max(prev, feit) - contr, 0) : 0;
    alunos.push({ id: c.id, nome: c.nome, contratadas: contr, previstas: prev, feitas: feit, faltam: contr ? Math.max(contr - feit, 0) : null,
      completo: !!contr && feit >= contr, passou, cia, custo_extra: cia ? arred(passou * parteDaAula(c.id, naCia), 2) : 0.0 });
  }
  return { mes, mes_txt: `${MESES[m - 1]} de ${ano}`, alunos, total: totalDe(alunos) };
}

export interface LinhaControle { eid: number | null; data: string; hora: number | null; estado: string; reposicao: boolean; repoe: string | null; local: string;
  data_br?: string; dia?: string; repoe_br?: string }

/** Painel do aluno na Agenda: saldo de reposições e as aulas do mês (feitas, faltas, desmarcadas, canceladas e reposições agendadas). */
export async function controleAluno(b: Banco, cid: number, mes: string, hoje: string) {
  const ano = Number(mes.slice(0, 4)), m = Number(mes.slice(5));
  const primeiro = `${mes}-01`;
  const prox = m === 12 ? `${ano + 1}-01-01` : `${zeros(ano, 4)}-${zeros(m + 1, 2)}-01`;
  const ant = somarDias(primeiro, -1).slice(0, 7);
  const deQuem = "(SELECT o.data FROM cliente_eventos o WHERE o.id=a.repoe_evento_id AND o.excluido_em IS NULL)";
  const rep = "FROM agenda_avulsas a WHERE a.cliente_id=e.cliente_id AND a.data=e.data AND a.hora=e.hora AND a.reposicao=1 AND a.excluido_em IS NULL";
  const [c, fixos, eventos, futuras, resumo, saldos] = await Promise.all([
    b.um("SELECT id, nome, status FROM clientes WHERE id=? AND excluido_em IS NULL", [cid]),
    b.query("SELECT dia, hora, local FROM agenda_fixos WHERE cliente_id=? AND excluido_em IS NULL ORDER BY id DESC", [cid]),
    b.query(`SELECT e.id, e.data, e.hora, e.tipo, (SELECT a.local ${rep} ORDER BY a.id LIMIT 1) AS local,
             EXISTS (SELECT 1 ${rep}) AS repos, (SELECT ${deQuem} ${rep} ORDER BY a.id LIMIT 1) AS repoe FROM cliente_eventos e
             WHERE e.cliente_id=? AND e.excluido_em IS NULL AND e.tipo IN (${TIPOS_MARCA}) AND e.data >= ? AND e.data < ?
             ORDER BY e.data, e.hora, e.id`, [cid, primeiro, prox]),
    b.query(`SELECT a.data, a.hora, a.local, ${deQuem} AS repoe FROM agenda_avulsas a
             WHERE a.cliente_id=? AND a.reposicao=1 AND a.excluido_em IS NULL
             AND a.data >= ? AND a.data < ? AND a.data >= ? AND NOT EXISTS (SELECT 1 FROM cliente_eventos e WHERE e.cliente_id=a.cliente_id
             AND e.data=a.data AND e.hora=a.hora AND e.excluido_em IS NULL AND e.tipo IN (${TIPOS_MARCA}))`, [cid, primeiro, prox, hoje]),
    resumoAulasMes(b, mes, hoje, new Set([cid])),
    saldosReposicao(b, [cid], hoje),
  ]);
  if (!c) return null;
  const locais = new Map<string, string>();
  for (const r of fixos) locais.set(`${r.dia}|${r.hora}`, r.local);
  const linhas: LinhaControle[] = [];
  for (const e of eventos) {
    const dia = diaDaSemana(e.data);
    let estado = TIPO_ESTADO[e.tipo];
    if (e.repos && estado === "desmarcou") estado = "cancelada";   // marcação antiga: na reposição, desmarcou é só cancelar
    linhas.push({ eid: e.id, data: e.data, hora: e.hora, estado, reposicao: !!e.repos, repoe: e.repoe, local: e.local || locais.get(`${dia}|${e.hora}`) || "" });
  }
  for (const a of futuras) linhas.push({ eid: null, data: a.data, hora: a.hora, estado: "agendada", reposicao: true, repoe: a.repoe, local: a.local });
  const k = (l: LinhaControle) => [l.data, l.hora ?? -1] as const;
  linhas.sort((x, y) => (k(x)[0] < k(y)[0] ? -1 : k(x)[0] > k(y)[0] ? 1 : k(x)[1] - k(y)[1]));
  for (const l of linhas) {
    l.data_br = `${l.data.slice(8, 10)}/${l.data.slice(5, 7)}`;
    l.dia = DIAS_CURTO[diaDaSemana(l.data)];
    l.repoe_br = l.repoe ? dataBr(l.repoe).slice(0, 5) : "";
  }
  const contar = (est: string) => linhas.filter((l) => l.estado === est).length;
  return { id: c.id as number, nome: c.nome as string, status: c.status as string | null, mes, mes_txt: `${MESES[m - 1]} de ${ano}`, mes_ant: ant,
    mes_prox: prox.slice(0, 7), eh_atual: mes === hoje.slice(0, 7), feitas: contar("feita"), faltou: contar("faltou"), desmarcou: contar("desmarcou"),
    canceladas: contar("cancelada"), repostas: linhas.filter((l) => l.estado === "feita" && l.reposicao).length, linhas,
    resumo: resumo.alunos[0] ?? null, ...saldos.get(cid)! };
}
export type Controle = NonNullable<Awaited<ReturnType<typeof controleAluno>>>;

/**
 * Marcações da Agenda: itens = [aluno, data, hora, estado, descrição]; estado "" só desfaz. A nova substitui as anteriores da
 * mesma aula (e a da ficha, sem hora); repetido, vale o último. Desmarcou numa reposição vira Cancelada. Devolve os comandos
 * e as (aluno|data|hora) trocadas assim.
 */
export async function gravarMarcas(b: Banco, itens: [number, string, number, string, string][]): Promise<[Comando[], Set<string>]> {
  const ultimo = new Map<string, [number, string, number, string, string]>();
  for (const it of itens) {
    ultimo.set(`${it[0]}|${it[1]}|${it[2]}`, [...it]);   // como o dict do Python: a chave repetida fica na posição da primeira
  }
  const desm = [...ultimo.values()].filter((x) => x[3] === "desmarcou");
  const trocadas = new Set<string>();
  if (desm.length) {
    for (const r of await b.query(`SELECT DISTINCT cliente_id, data, hora FROM agenda_avulsas WHERE reposicao=1 AND excluido_em IS NULL
        AND cliente_id || '|' || data || '|' || hora IN (SELECT value FROM json_each(?))`, [JSON.stringify(desm.map((x) => `${x[0]}|${x[1]}|${x[2]}`))])) {
      trocadas.add(`${r.cliente_id}|${r.data}|${r.hora}`);
    }
  }
  for (const k of trocadas) ultimo.get(k)![3] = "cancelada";   // desmarcar uma reposição é só cancelar a reposição: não gera outra
  const todos = [...ultimo.values()], cmds: Comando[] = [];
  for (let i = 0; i < todos.length; i += 33) {
    const parte = todos.slice(i, i + 33);
    cmds.push({ sql: `UPDATE cliente_eventos SET excluido_em=datetime('now','localtime') WHERE excluido_em IS NULL AND tipo IN (${TIPOS_MARCA}) AND (`
      + parte.map(() => "(cliente_id=? AND data=? AND (hora=? OR hora IS NULL))").join(" OR ") + ")", params: parte.flatMap((x) => [x[0], x[1], x[2]]) });
  }
  const novas = todos.filter((x) => x[3]).map((x) => [x[0], ESTADO_TIPO[x[3]], x[1], x[4], x[2]] as const);
  for (let i = 0; i < novas.length; i += 20) {
    const parte = novas.slice(i, i + 20);
    cmds.push({ sql: "INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao, hora) VALUES " + parte.map(() => "(?,?,?,?,?)").join(","),
      params: parte.flat() });
  }
  return [cmds, trocadas];
}

export { isoDoDia };
