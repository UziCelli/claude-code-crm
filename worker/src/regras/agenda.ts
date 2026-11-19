/**
 * Agenda: a fonte dos horários fixos (port de app/main.py e app/vigencia.py; mapa em docs/mapa-agenda.md).
 *
 * No Python cada gravação lê e grava várias vezes na mesma transação, e a decisão seguinte depende do que acabou de gravar
 * (ex.: soltar a Grade e depois ver se a célula ainda é do aluno). O D1 não tem transação interativa, então aqui a
 * `GravaAgenda` lê antes, numa ida, e refaz as mesmas decisões sobre uma cópia em memória das linhas; as gravações saem
 * na mesma ordem do Python, num batch só (tudo ou nada). Mesma ordem = mesmos ids e as mesmas tabelas no fim.
 * O D1 aceita até 100 parâmetros por consulta: as gravações em lote vão em blocos menores (o resultado é o mesmo).
 */
import type { Banco } from "../banco/banco.ts";
import type { Comando, Valor } from "../banco/tipos.ts";
import { agoraTxt } from "../relogio.ts";
import { formatoG } from "./financeiro.ts";
import { DIAS_CURTO } from "./ficha.ts";
import { chaveNome } from "./locais.ts";
import { parametros } from "./parametros.ts";
import { custosLocais } from "./precos.ts";
import { zeros } from "./datas.ts";

export const TIPOS_GRADE = ["Pacotes", "Mensalidades"];
/** Parâmetros por consulta no D1. */
export const MAX_PARAMS = 100;

/** "Seg 07h". */
export const quando = (dia: number, hora: number): string => `${DIAS_CURTO[dia]} ${zeros(hora, 2)}h`;

/** Quantos alunos cabem num horário fixo (Configurações > Agenda; padrão 2). */
export async function maxAlunos(b: Banco): Promise<number> {
  const n = Math.trunc(Number((await parametros(b, "agenda")).max_alunos_horario || 2));
  return Number.isNaN(n) ? 2 : Math.max(n, 1);
}

interface Vigencia { vigente_de?: string | null; criado_em?: string | null; excluido_em?: string | null }

/**
 * A linha do horário fixo vale na data? De vigente_de (ou sempre) até o dia da exclusão, inclusive. Criada e excluída no
 * mesmo dia foi engano: nunca vale.
 */
export function fixoVale(r: Vigencia, data: string): boolean {
  const exc = String(r.excluido_em ?? "").slice(0, 10);
  if (exc && exc <= String(r.criado_em ?? "").slice(0, 10)) return false;
  return (!r.vigente_de || data >= r.vigente_de) && (!exc || data <= exc);
}

/** Excluída na data e o aluno tem outra linha que começa nesse dia: vale a nova. comecam = {"aluno|dia da semana"}. */
export function trocadaNoDia(r: Vigencia & { cliente_id: number; dia: number }, data: string, comecam: Set<string>): boolean {
  return String(r.excluido_em ?? "").slice(0, 10) === data && comecam.has(`${r.cliente_id}|${r.dia}`);
}

/** Primeiro nome de cada um; se dois começam igual ("Ana Silva" e "Ana Lima"), o nome inteiro. */
export function nomesCurtos(nomes: (string | null | undefined)[]): string[] {
  const cur = nomes.map((n) => String(n ?? "").split(/\s+/).filter(Boolean)[0] ?? "");
  const baixo = cur.map((x) => x.toLowerCase());
  return nomes.map((n, i) => (baixo.filter((x) => x === baixo[i]).length > 1 ? String(n ?? "") : cur[i]));
}

export function avisoLotados(tirados: string[]): string {
  return tirados.length
    ? ` Saiu do horário fixo de ${tirados.join(", ")}: já ${tirados.length === 1 ? "está cheio" : "estão cheios"}. Escolha outro horário na Agenda.`
    : "";
}

/** Blocos de linhas para um INSERT/UPSERT de várias linhas sem passar de 100 parâmetros. */
function blocos<T>(linhas: T[], porLinha: number): T[][] {
  const n = Math.max(Math.floor(MAX_PARAMS / porLinha), 1), out: T[][] = [];
  for (let i = 0; i < linhas.length; i += n) out.push(linhas.slice(i, i + n));
  return out;
}

export interface LinhaFixo { id: number; cliente_id: number; dia: number; hora: number; local: string; vigente_de: string | null; criado_em: string | null }
export interface LinhaGrade { tipo_calculo: string; dia: number; local: string; hora: number; status: string; cliente_id: number | null;
  cliente_nome: string | null; multiplicador: number | null }
interface Cli { nome: string; status: string | null; excluido_em: string | null }
type Slot = [string, number, string, number, string, number | null, string | null, number];

/** Uma gravação de Agenda (e da cópia na Grade) montada em memória: `cmds` vai num batch só. */
export class GravaAgenda {
  readonly cmds: Comando[] = [];
  private proximo: number;
  private constructor(
    private fixos: LinhaFixo[],
    private grade: LinhaGrade[],
    private antigos: Set<number>,
    readonly clientes: Map<number, Cli>,
    readonly cabe: number,
    readonly hoje: string,
    readonly agora: string,
  ) {
    this.proximo = fixos.reduce((m, f) => Math.max(m, f.id), 0) + 1;
  }

  /** Lê numa ida o que as regras de gravação precisam: horários fixos ativos, a Grade, os alunos e o limite. */
  static async abrir(b: Banco, hoje: string): Promise<GravaAgenda> {
    const [fixos, grade, antigos, clientes, cabe] = await Promise.all([
      b.query<LinhaFixo>("SELECT id, cliente_id, dia, hora, local, vigente_de, criado_em FROM agenda_fixos WHERE excluido_em IS NULL ORDER BY id"),
      b.query<LinhaGrade>("SELECT tipo_calculo, dia, local, hora, status, cliente_id, cliente_nome, multiplicador FROM grade_slots ORDER BY id"),
      b.query<{ cliente_id: number }>("SELECT DISTINCT cliente_id FROM agenda_fixos WHERE substr(criado_em,1,10) < ?", [hoje]),
      b.query<{ id: number } & Cli>("SELECT id, nome, status, excluido_em FROM clientes"),
      maxAlunos(b),
    ]);
    return new GravaAgenda(fixos.map((f) => ({ ...f })), grade.map((g) => ({ ...g })), new Set(antigos.map((r) => r.cliente_id)),
      new Map(clientes.map((c) => [c.id, { nome: c.nome, status: c.status, excluido_em: c.excluido_em }])), cabe, hoje, agoraTxt());
  }

  private ativo(cid: number): boolean {
    const c = this.clientes.get(cid);
    return !!c && c.status === "ativo" && c.excluido_em == null;
  }

  /** O status do aluno mudou neste pedido (as leituras seguintes do Python já o veem). */
  mudarStatus(cid: number, status: string): void {
    const c = this.clientes.get(cid);
    if (c) c.status = status;
  }

  /** Linhas ativas do horário (dia, hora) dos alunos ativos, da mais antiga à mais nova (fixos_do_horario). */
  fixosDoHorario(dia: number, hora: number): (LinhaFixo & { nome: string })[] {
    return this.fixos.filter((f) => f.dia === dia && f.hora === hora && this.ativo(f.cliente_id))
      .map((f) => ({ ...f, nome: this.clientes.get(f.cliente_id)!.nome }));
  }

  /** {aluno: local} de quem está no horário (o primeiro local de cada um). */
  membros(dia: number, hora: number): Map<number, string> {
    const m = new Map<number, string>();
    for (const r of this.fixosDoHorario(dia, hora)) if (!m.has(r.cliente_id)) m.set(r.cliente_id, r.local);
    return m;
  }

  /** Horários fixos ativos do aluno (sem olhar o status dele), na ordem das linhas. */
  doAluno(cid: number): LinhaFixo[] {
    return this.fixos.filter((f) => f.cliente_id === cid);
  }

  /** Horários fixos ativos de alunos ativos, para o aviso de deslocamento (depois das gravações). */
  ativosNosDias(dias: Set<number>): LinhaFixo[] {
    return this.fixos.filter((f) => dias.has(f.dia) && this.ativo(f.cliente_id));
  }

  /** A partir de quando vale o horário novo: hoje para quem já tinha horário antes de hoje; senão desde a data de início (null). */
  vigencias(ids: number[]): Map<number, string | null> {
    return new Map(ids.map((c) => [c, this.antigos.has(c) ? this.hoje : null]));
  }

  /** Manda linhas da agenda_fixos para a lixeira (UPDATE excluido_em). */
  excluir(ids: number[]): void {
    if (!ids.length) return;
    for (let i = 0; i < ids.length; i += MAX_PARAMS - 1) {
      const parte = ids.slice(i, i + MAX_PARAMS - 1);
      this.cmds.push({ sql: `UPDATE agenda_fixos SET excluido_em=? WHERE id IN (${parte.map(() => "?").join(",")})`, params: [this.agora, ...parte] });
    }
    const fora = new Set(ids);
    this.fixos = this.fixos.filter((f) => !fora.has(f.id));
  }

  /** INSERT de (aluno, dia, hora, local) com a vigência de cada aluno (inserir_fixos). */
  inserirFixos(linhas: [number, number, number, string][], vigente: Map<number, string | null> = new Map()): void {
    for (const parte of blocos(linhas, 6)) {
      this.cmds.push({ sql: "INSERT INTO agenda_fixos (cliente_id, dia, hora, local, vigente_de, criado_em) VALUES " + parte.map(() => "(?,?,?,?,?,?)").join(","),
        params: parte.flatMap((l) => [...l, vigente.get(l[0]) ?? null, this.agora]) });
    }
    for (const [cid, dia, hora, local] of linhas) {
      this.fixos.push({ id: this.proximo++, cliente_id: cid, dia, hora, local, vigente_de: vigente.get(cid) ?? null, criado_em: this.agora });
    }
  }

  // ---------- cópia na Grade (grade_slots): melhor esforço, como no Python ----------

  private celulas(dia: number, hora: number): LinhaGrade[] {
    return this.grade.filter((g) => g.dia === dia && g.hora === hora);
  }

  private soltar(linhas: LinhaGrade[]): void {
    for (const g of linhas) Object.assign(g, { status: "livre", cliente_id: null, cliente_nome: null });
  }

  /** UPSERT de células (salvar_slots), em blocos de 12 linhas. */
  salvarSlots(slots: Slot[]): void {
    for (const parte of blocos(slots, 8)) {
      this.cmds.push({ sql: "INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, cliente_id, cliente_nome, multiplicador) VALUES "
        + parte.map(() => "(?,?,?,?,?,?,?,?)").join(",") + ` ON CONFLICT(tipo_calculo, dia, local, hora) DO UPDATE SET
        status=excluded.status, cliente_id=excluded.cliente_id, cliente_nome=excluded.cliente_nome,
        multiplicador=excluded.multiplicador`, params: parte.flat() });
    }
    for (const [tipo, dia, local, hora, status, cid, nome, mult] of slots) {
      const g = this.grade.find((x) => x.tipo_calculo === tipo && x.dia === dia && x.local === local && x.hora === hora);
      if (g) Object.assign(g, { status, cliente_id: cid, cliente_nome: nome, multiplicador: mult });
      else this.grade.push({ tipo_calculo: tipo, dia, local, hora, status, cliente_id: cid, cliente_nome: nome, multiplicador: mult });
    }
  }

  /** Solta as células que a Grade dá a este aluno (parado/inativo não ocupa a Grade). */
  soltarAluno(cid: number): void {
    this.cmds.push({ sql: "UPDATE grade_slots SET status='livre', cliente_id=NULL, cliente_nome=NULL WHERE cliente_id=?", params: [cid] });
    this.soltar(this.grade.filter((g) => g.cliente_id === cid));
  }

  /** Solta as células desses horários em todos os locais (a Grade não guarda mais aluno). Blocos de 50 horários. */
  soltarHorarios(pares: [number, number][]): void {
    for (const parte of blocos(pares, 2)) {
      this.cmds.push({ sql: "UPDATE grade_slots SET status='livre', cliente_id=NULL, cliente_nome=NULL WHERE ("
        + parte.map(() => "(dia=? AND hora=?)").join(" OR ") + ")", params: parte.flat() });
    }
    const k = new Set(pares.map(([d, h]) => `${d}-${h}`));
    this.soltar(this.grade.filter((g) => k.has(`${g.dia}-${g.hora}`)));
  }

  /** Solta a célula (Pacotes e Mensalidades) se ainda é deste aluno; sem célula dele, não grava nada. */
  gradeLiberar(cid: number, dia: number, local: string, hora: number): boolean {
    const dele = this.grade.filter((g) => g.cliente_id === cid && g.dia === dia && g.local === local && g.hora === hora);
    if (!dele.length) return false;
    this.cmds.push({ sql: `UPDATE grade_slots SET status='livre', cliente_id=NULL, cliente_nome=NULL
                   WHERE cliente_id=? AND dia=? AND local=? AND hora=?`, params: [cid, dia, local, hora] });
    this.soltar(dele);
    return true;
  }

  /**
   * Põe o aluno no horário da Grade (Pacotes e Mensalidades, mantendo o multiplicador). Outro aluno ou indisponível em
   * qualquer local é conflito (devolve o texto); o mesmo horário em outro local fica livre.
   */
  ocuparFixo(cid: number, nome: string, dia: number, local: string, hora: number): string | null {
    const rows = this.celulas(dia, hora);
    const dono = rows.find((r) => r.status === "ocupado" && r.cliente_id && r.cliente_id !== cid);
    if (dono) {
      const quem = this.clientes.get(dono.cliente_id!)?.nome ?? dono.cliente_nome;
      return `Esse horário já é de ${quem} na Grade${dono.local === local ? "" : " (em " + dono.local + ")"}. Tire ele de lá antes.`;
    }
    const ind = rows.find((r) => r.status === "indisponivel");
    if (ind) return `${quando(dia, hora)} em ${ind.local} está indisponível na Grade. Libere o horário lá antes.`;
    if (rows.some((r) => r.status === "ocupado" && r.local !== local)) {
      this.cmds.push({ sql: "UPDATE grade_slots SET status='livre', cliente_id=NULL, cliente_nome=NULL WHERE dia=? AND hora=? AND local != ? AND status='ocupado'",
        params: [dia, hora, local] });
      this.soltar(rows.filter((r) => r.local !== local && r.status === "ocupado"));
    }
    const mult = new Map(rows.filter((r) => r.local === local).map((r) => [r.tipo_calculo, r.multiplicador || 1.0]));
    this.salvarSlots(TIPOS_GRADE.map((t) => [t, dia, local, hora, "ocupado", cid, nome, mult.get(t) ?? 1.0]));
    return null;
  }

  /** Avisa a Grade que o aluno tem este horário; se os dois tipos já são dele, não grava nada. */
  gradeOcupar(cid: number, nome: string, dia: number, local: string, hora: number): void {
    const ja = new Set(this.grade.filter((g) => g.dia === dia && g.local === local && g.hora === hora && g.status === "ocupado" && g.cliente_id === cid
      && TIPOS_GRADE.includes(g.tipo_calculo)).map((g) => g.tipo_calculo));
    if (ja.size < 2) this.ocuparFixo(cid, nome, dia, local, hora);
  }

  /** gradeOcupar para vários horários do mesmo aluno: pares = [dia, local, hora]. Lê uma vez, solta e grava em lote. */
  gradeOcuparLote(cid: number, nome: string, pares: [number, string, number][]): void {
    if (!pares.length) return;
    const k = new Set(pares.map(([d, , h]) => `${d}-${h}`));
    const por = new Map<string, LinhaGrade[]>();
    for (const g of this.grade) {
      const kk = `${g.dia}-${g.hora}`;
      if (!TIPOS_GRADE.includes(g.tipo_calculo) || !k.has(kk)) continue;
      if (!por.has(kk)) por.set(kk, []);
      por.get(kk)!.push({ ...g });
    }
    const slots: Slot[] = [], soltar: [number, number, string][] = [];
    for (const [d, l, h] of pares) {
      const todas = por.get(`${d}-${h}`) ?? [];
      if (todas.some((r) => r.status === "ocupado" && r.cliente_id && r.cliente_id !== cid) || todas.some((r) => r.status === "indisponivel")) continue;
      const cel = todas.filter((r) => r.local === l);
      const fora = todas.filter((r) => r.local !== l && r.status === "ocupado");
      if (new Set(cel.filter((r) => r.status === "ocupado" && r.cliente_id === cid).map((r) => r.tipo_calculo)).size >= 2 && !fora.length) continue;
      if (fora.length) soltar.push([d, h, l]);
      const mult = new Map(cel.map((r) => [r.tipo_calculo, r.multiplicador || 1.0]));
      for (const t of TIPOS_GRADE) slots.push([t, d, l, h, "ocupado", cid, nome, mult.get(t) ?? 1.0]);
    }
    for (const parte of blocos(soltar, 3)) {
      this.cmds.push({ sql: "UPDATE grade_slots SET status='livre', cliente_id=NULL, cliente_nome=NULL WHERE status='ocupado' AND ("
        + parte.map(() => "(dia=? AND hora=? AND local != ?)").join(" OR ") + ")", params: parte.flat() });
    }
    for (const [d, h, l] of soltar) this.soltar(this.grade.filter((g) => g.status === "ocupado" && g.dia === d && g.hora === h && g.local !== l));
    if (slots.length) this.salvarSlots(slots);
  }

  // ---------- regras da Agenda ----------

  /**
   * Deixa o horário (dia, hora) com estes alunos e grava só a diferença: sai = lixeira, troca de local = lixeira + linha nova,
   * entra = INSERT. Depois atualiza a cópia na Grade. O limite de alunos é conferido por quem chama. `local`: um texto
   * (vale para todos) ou {aluno: local}.
   */
  definirHorario(dia: number, hora: number, alunosIn: number[], local: string | Map<number, string>): { entrou: number[]; saiu: number[]; mudou: number[] } {
    const alunos = [...new Set(alunosIn)];
    const locais = typeof local === "string" ? new Map(alunos.map((c) => [c, local])) : local;
    const atual = new Map<number, LinhaFixo>(), apagar: number[] = [];
    for (const r of this.fixosDoHorario(dia, hora)) {
      if (atual.has(r.cliente_id)) apagar.push(r.id);
      else atual.set(r.cliente_id, r);
    }
    const saiu = [...atual.keys()].filter((c) => !alunos.includes(c));
    const mudou = alunos.filter((c) => atual.has(c) && atual.get(c)!.local !== locais.get(c));
    const entrou = alunos.filter((c) => !atual.has(c));
    apagar.push(...[...saiu, ...mudou].map((c) => atual.get(c)!.id));
    this.excluir(apagar);
    if (entrou.length || mudou.length) {
      const vig = this.vigencias(entrou);
      for (const c of mudou) {
        const r = atual.get(c)!;
        vig.set(c, String(r.criado_em ?? "").slice(0, 10) < this.hoje ? this.hoje : r.vigente_de);
      }
      this.inserirFixos([...mudou, ...entrou].map((c) => [c, dia, hora, locais.get(c)!]), vig);
    }
    const soltos = new Set<string>();
    for (const c of [...saiu, ...mudou]) if (this.gradeLiberar(c, dia, atual.get(c)!.local, hora)) soltos.add(atual.get(c)!.local);
    const ocupar = [...entrou, ...mudou, ...alunos.filter((c) => atual.has(c) && !mudou.includes(c) && soltos.has(locais.get(c)!))];
    for (const c of ocupar) {
      const cli = this.clientes.get(c);
      if (cli) this.gradeOcupar(c, cli.nome, dia, locais.get(c)!, hora);
    }
    return { entrou, saiu, mudou };
  }

  /**
   * O aluno voltou a ficar ativo: horário dele que encheu com outros enquanto estava parado fica cheio demais. Sai desses
   * horários (lixeira) e solta a célula dele na Grade. Devolve os horários ("Seg 07h") para avisar.
   */
  tirarDosLotados(cid: number): string[] {
    const meus = this.doAluno(cid);
    if (!meus.length) return [];
    const chaves = new Set(meus.map((m) => `${m.dia}-${m.hora}`));
    const outros = new Map<string, Set<number>>();
    for (const f of this.fixos) {
      const k = `${f.dia}-${f.hora}`;
      if (f.cliente_id === cid || !chaves.has(k) || !this.ativo(f.cliente_id)) continue;
      if (!outros.has(k)) outros.set(k, new Set());
      outros.get(k)!.add(f.cliente_id);
    }
    const sair = meus.filter((m) => (outros.get(`${m.dia}-${m.hora}`)?.size ?? 0) >= this.cabe);
    if (!sair.length) return [];
    this.excluir(sair.map((m) => m.id));
    for (const m of sair) this.gradeLiberar(cid, m.dia, m.local, m.hora);
    return [...new Set(sair.filter((m) => m.dia >= 1 && m.dia <= 6).map((m) => quando(m.dia, m.hora)))].sort();
  }

  /** Voltou a ativo: marca na Grade os horários fixos que ficaram com ele. */
  gradeReocupar(cid: number): void {
    const nome = this.clientes.get(cid)?.nome ?? "";
    const vistos = new Set<string>();
    for (const f of this.doAluno(cid)) {
      const k = `${f.dia}|${f.hora}|${f.local}`;
      if (vistos.has(k)) continue;
      vistos.add(k);
      this.gradeOcupar(cid, nome, f.dia, f.local, f.hora);
    }
  }
}

/** Ordena como as tuplas do Python: (hora, local). */
function cmpPar(a: [number, string], b: [number, string]): number {
  return a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0);
}

/**
 * Aviso (não bloqueia) quando um horário (dia, hora, local) cai na mesma hora ou colado (1h antes/depois) de uma aula fixa
 * em OUTRO local. "" se está tudo certo. Lê os horários depois das gravações (a cópia em memória já está como o banco).
 */
export async function avisoDeslocamento(b: Banco, g: GravaAgenda, horariosIn: [number, number, string | null][], clienteId = 0): Promise<string> {
  const horarios = horariosIn.filter(([d, h, l]) => d && h && (l ?? "").trim()).map(([d, h, l]) => [d, h, (l ?? "").trim()] as [number, number, string]);
  if (!horarios.length) return "";
  const ocupado = new Map<string, Map<string, Set<number>>>();
  const marcar = (d: number, h: number, l: string, c: number) => {
    const k = `${d}-${h}`;
    if (!ocupado.has(k)) ocupado.set(k, new Map());
    const m = ocupado.get(k)!;
    if (!m.has(l)) m.set(l, new Set());
    m.get(l)!.add(c);
  };
  for (const r of g.ativosNosDias(new Set(horarios.map(([d]) => d)))) marcar(r.dia, r.hora, r.local, r.cliente_id);
  for (const [d, h, l] of horarios) marcar(d, h, l, -1);
  const tempo = new Map([...(await custosLocais(b))].map(([k, v]) => [k, Number(v.tempo_deslocamento) || 0]));
  const achados: [number, [[number, string], [number, string]]][] = [];
  for (const [d, h, l] of horarios) {
    for (const h2 of [h - 1, h, h + 1]) {
      for (const [l2, quem] of ocupado.get(`${d}-${h2}`) ?? []) {
        if (chaveNome(l2) === chaveNome(l) || (h2 === h && [...quem].every((x) => x === clienteId || x === -1))) continue;
        const par = ([[h, l], [h2, l2]] as [number, string][]).sort(cmpPar) as [[number, string], [number, string]];
        if (achados.some(([dd, p]) => dd === d && cmpPar(p[0], par[0]) === 0 && cmpPar(p[1], par[1]) === 0)) continue;
        achados.push([d, par]);
      }
    }
  }
  if (!achados.length) return "";
  const frases = achados.slice(0, 3).map(([d, [[ha, la], [hb, lb]]]) => {
    if (ha === hb) return `${DIAS_CURTO[d]} ${zeros(ha, 2)}h em ${la} e em ${lb} ao mesmo tempo`;
    const m = Math.max(tempo.get(la) ?? 0, tempo.get(lb) ?? 0);
    return `${DIAS_CURTO[d]} ${zeros(ha, 2)}h em ${la} e ${zeros(hb, 2)}h em ${lb}` + (m ? ` (deslocamento de ${formatoG(m)} min)` : "");
  });
  return " Atenção: " + frases.join("; ") + (achados.length > 3 ? ` e mais ${achados.length - 3}` : "") + ".";
}

export type { Valor };
