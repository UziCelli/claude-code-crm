/**
 * Horas de trabalho e plano do aluno (port de app/main.py: aulas_mes, base_do_cliente, fixos_atuais, horas_trabalho_detalhe).
 * A Agenda (agenda_fixos) é a fonte dos horários fixos: docs/mapa-agenda.md.
 */
import type { Banco } from "../banco/banco.ts";
import type { Linha } from "../banco/tipos.ts";
import { baseMotor, deslocamento, PARTES_TRABALHO, partesMinutos, SEMANAS_MES, TIPOS_PLANO, type BaseMotor, type Params, type Parte } from "./precos.ts";
import { flt } from "./texto.ts";

export type Trabalho = Record<Parte, number> & { total: number };

/** Sessões por mês estimadas a partir do plano do cliente. */
export function aulasMes(c: { plano?: string | null; tipo_servico?: string | null }): number {
  const plano = c.plano || "";
  let m = /Pacote (?:de )?(\d+)/.exec(plano); // "Pacote 8" (planilha) ou "Pacote de 8 aulas" (Propostas)
  if (m) return Number(m[1]);
  m = /Mensalidade (\d+)x/.exec(plano);
  if (m) return Number(m[1]) * SEMANAS_MES;
  if (c.tipo_servico === "Consultoria Híbrida") return 1;
  return 0;
}

/** Plano do aluno no motor de preços (tipo, aulas e local da ficha). null se o tipo de serviço não é precificável. */
export function baseDoCliente(c: Linha): BaseMotor | null {
  const tipo = (c.tipo_servico || "").trim();
  if (!TIPOS_PLANO.has(tipo)) return null;
  const qtd = tipo === "Pacote de Aulas" ? Math.trunc(aulasMes(c)) : 0;
  const m = /Mensalidade (\d+)x/.exec(c.plano || "");
  const freq = m ? Number(m[1]) : 0;
  if ((tipo === "Pacote de Aulas" && qtd < 1) || (tipo === "Mensalidade" && freq < 1)) return null;
  return baseMotor(tipo, qtd, freq, c.local ?? null);
}

export interface Fixo { cliente_id: number; dia: number; hora: number; local: string }

/** Horários fixos que valem hoje na Agenda, só de alunos ativos, um por (aluno, dia, hora), do mais antigo ao mais novo. */
export async function fixosAtuais(b: Banco, ids?: Set<number>): Promise<Fixo[]> {
  const rows = await b.query<Fixo>(`SELECT f.cliente_id, f.dia, f.hora, f.local FROM agenda_fixos f JOIN clientes c ON c.id=f.cliente_id
    WHERE f.excluido_em IS NULL AND f.dia BETWEEN 1 AND 6 AND f.hora BETWEEN 5 AND 23
    AND c.status='ativo' AND c.excluido_em IS NULL ORDER BY f.id`);
  const out: Fixo[] = [];
  const vistos = new Set<string>();
  for (const r of rows) {
    const k = `${r.cliente_id}|${r.dia}|${r.hora}`;
    if ((ids && !ids.has(r.cliente_id)) || vistos.has(k)) continue;
    vistos.add(k);
    out.push({ ...r });
  }
  return out;
}

/**
 * Suas horas de trabalho no mês, por parte e no total. Aulas e deslocamento vêm da Agenda: cada horário fixo vale 4,33 aulas
 * no mês, contado uma vez mesmo com 2 alunos juntos. Aluno com horário soma só planejamento, consultoria e avaliação pelo plano;
 * aluno sem horário conta tudo pelo plano; sem plano do motor e sem horário, só as aulas do plano.
 */
const SQL_ATIVOS = "SELECT * FROM clientes WHERE excluido_em IS NULL AND status='ativo'";

export async function horasTrabalhoDetalhe(b: Banco, p: Params): Promise<Trabalho> {
  const [fixos, clientes] = await horasTrabalhoDetalhe.leituras(b);
  const out: Record<Parte, number> = { aulas: 0, deslocamento: 0, planejamento: 0, consultoria: 0, avaliacao: 0 };
  const slots = new Map<string, string>();
  for (const f of fixos) {
    const k = `${f.dia}|${f.hora}`;
    if (!slots.has(k)) slots.set(k, f.local); // dupla no mesmo horário: uma hora de trabalho, no local do primeiro
  }
  const minAula = flt((p.mo ?? {}).min_aula === undefined ? 60 : p.mo.min_aula);
  out.aulas += (slots.size * SEMANAS_MES * minAula) / 60;
  out.deslocamento += ([...slots.values()].reduce((a, local) => a + deslocamento(p, local)[1], 0) * SEMANAS_MES) / 60;
  const comHorario = new Set(fixos.map((f) => f.cliente_id));
  for (const c of clientes) {
    const base = baseDoCliente(c);
    if (comHorario.has(c.id)) {
      if (base) {
        const partes = partesMinutos(base, p, c.local);
        for (const k of ["planejamento", "consultoria", "avaliacao"] as const) out[k] += partes[k] / 60;
      }
      continue;
    }
    if (!base) {
      out.aulas += aulasMes(c);
      continue;
    }
    const partes = partesMinutos(base, p, c.local);
    for (const k of PARTES_TRABALHO) out[k] += partes[k] / 60;
  }
  const total = PARTES_TRABALHO.reduce((a, k) => a + out[k], 0);
  return { ...out, total };
}

/** As leituras de horasTrabalhoDetalhe, para quem quiser pedi-las antes (na mesma ida ao banco de outras consultas). */
horasTrabalhoDetalhe.leituras = (b: Banco) => Promise.all([fixosAtuais(b), b.query(SQL_ATIVOS)]);
