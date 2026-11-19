/** Grade: quem segura cada horário (a Agenda manda) e os custos da CIA no pop-up do local (port de app/main.py e app/locais.py). */
import type { Banco } from "../banco/banco.ts";
import { maxAlunos, nomesCurtos } from "./agenda.ts";
import { parametros } from "./parametros.ts";
import { baseMotor, taxasCia, type BaseMotor } from "./precos.ts";
import { fixosAtuais } from "./trabalho.ts";
import { flt } from "./texto.ts";

/** Plano do motor que a Grade precifica. ref = vezes por semana (Mensalidades) ou nº de aulas (Pacotes); 0 = 2x/sem ou 8 aulas. */
export function planoReferencia(tipo: string, local: string, ref = 0): BaseMotor {
  return tipo === "Mensalidades" ? baseMotor("Mensalidade", 0, ref || 2, local) : baseMotor("Pacote de Aulas", ref || 8, 0, local);
}

export interface Bloqueio { status: string; cliente_id: number | null; nome: string; local: string; ids: number[]; nomes: string[]; agenda: boolean;
  vagas?: number }

/**
 * Quem segura cada horário, em qualquer local e tipo: {"dia-hora": [bloqueio]}, ocupado antes de indisponível. A ocupação
 * vem da Agenda (um item por horário com todos os alunos); da Grade só vale indisponível e ocupado sem aluno.
 */
export async function bloqueiosGerais(b: Banco): Promise<Map<string, Bloqueio[]>> {
  const [fixos, nomesRows, cabe, grade] = await Promise.all([
    fixosAtuais(b),
    b.query<{ id: number; nome: string }>("SELECT id, nome FROM clientes WHERE id IN (SELECT cliente_id FROM agenda_fixos WHERE excluido_em IS NULL)"),
    maxAlunos(b),
    b.query(`SELECT dia, hora, local, status, cliente_id, cliente_nome FROM grade_slots WHERE dia BETWEEN 1 AND 6
             AND (status='indisponivel' OR (status='ocupado' AND cliente_id IS NULL)) ORDER BY status='indisponivel', local, tipo_calculo`),
  ]);
  const out = new Map<string, Bloqueio[]>();
  for (const f of fixos) {
    const k = `${f.dia}-${f.hora}`;
    if (!out.has(k)) out.set(k, [{ status: "ocupado", cliente_id: f.cliente_id, nome: "", local: f.local, ids: [], nomes: [], agenda: true }]);
    out.get(k)![0].ids.push(f.cliente_id);
  }
  const nomes = new Map(nomesRows.map((r) => [r.id, r.nome]));
  for (const [b0] of out.values()) {
    b0.nomes = b0.ids.map((c) => nomes.get(c) ?? "");
    b0.nome = b0.nomes.length > 1 ? nomesCurtos(b0.nomes).join(" + ") : b0.nomes[0];
    b0.vagas = Math.max(cabe - b0.ids.length, 0);
  }
  for (const r of grade) {
    const k = `${r.dia}-${r.hora}`;
    if (!out.has(k)) out.set(k, []);
    const lista = out.get(k)!;
    if (!lista.some((x) => x.local === r.local)) {
      lista.push({ status: r.status, cliente_id: null, nome: r.cliente_nome, local: r.local, ids: [], nomes: [], agenda: false });
    }
  }
  // ocupado vence indisponível, mesmo vindo de outro local; a Agenda primeiro
  const chave = (x: Bloqueio) => (x.status !== "ocupado" ? 2 : 0) + (x.agenda ? 0 : 1);
  for (const lista of out.values()) lista.sort((x, y) => chave(x) - chave(y));
  return out;
}

export interface SoNaGrade { dia: number; hora: number; local: string; cliente_id: number; nome: string }

/** Horários que a Grade antiga dá a um aluno ativo e que a Agenda não tem (aviso "Passar para a Agenda"). */
export async function soNaGrade(b: Banco): Promise<SoNaGrade[]> {
  const [fixos, rows] = await Promise.all([
    fixosAtuais(b),
    b.query<SoNaGrade>(`SELECT g.dia, g.hora, g.local, g.cliente_id, c.nome FROM grade_slots g JOIN clientes c ON c.id=g.cliente_id
                        WHERE g.status='ocupado' AND g.dia BETWEEN 1 AND 6 AND g.hora BETWEEN 5 AND 23
                        AND c.status='ativo' AND c.excluido_em IS NULL ORDER BY g.dia, g.hora, g.local`),
  ]);
  const naAgenda = new Set(fixos.map((f) => `${f.cliente_id}|${f.dia}|${f.hora}`));
  const out: SoNaGrade[] = [], vistos = new Set<string>();
  for (const r of rows) {
    const k = `${r.cliente_id}|${r.dia}|${r.hora}`;
    if (naAgenda.has(k) || vistos.has(k)) continue;
    vistos.add(k);
    out.push({ ...r });
  }
  return out;
}

const PESSOAS_CIA = [1, 2, 3];

export interface CustosLocal { taxa_aula?: number; taxa_pessoa_extra?: number; max_pessoas?: number; deslocamento?: number;
  tempo_deslocamento?: number; taxa_mensal?: number; aulas_mes?: number; grupo?: Map<number, number> }

/** Os custos da CIA nos campos de um local + grupo {pessoas: R$ da aula com elas} (a CIA cobra a aula pelo nº de pessoas). */
export async function ciaAtual(b: Banco): Promise<CustosLocal> {
  const [[taxas, maximo], ida, mensal] = await Promise.all([taxasCia(b), parametros(b, "cia_deslocamento"), parametros(b, "cia_mensal")]);
  const grupo = new Map([...new Set([...taxas.keys(), ...PESSOAS_CIA])].sort((x, y) => x - y).filter((n) => n > 1)
    .map((n) => [n, flt(taxas.get(n) || 0)]));
  return { taxa_aula: flt(taxas.get(1) || 0), grupo, max_pessoas: maximo, deslocamento: flt(ida.reais_por_aula || 0),
    tempo_deslocamento: flt(ida.minutos_por_aula || 0), taxa_mensal: flt(mensal.taxa_mensal || 0), aulas_mes: flt(mensal.aulas_mes || 0) };
}
