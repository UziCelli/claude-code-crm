/**
 * Estado do aluno (port de app/alunos.py): UM algoritmo olha cada aluno ativo, descobre a situação e traz os botões da solução.
 * Alertas, lista de Clientes, ficha, Mensalidades e Assistente leem daqui: nenhuma tela tem regra própria.
 */
import type { Banco } from "../banco/banco.ts";
import type { Linha, Valor } from "../banco/tipos.ts";
import { arred } from "../arred.ts";
import { dataBr, moeda } from "../formato.ts";
import { cartaoCobranca, cobrancaAtual, rotuloCobranca, textoCobranca } from "./cobranca.ts";
import { dataIso, isoDoDia, numeroDoDia } from "./datas.ts";
import { ANTECEDENCIA, cobranca, creditoAplicavel, creditos, mensalidades, mesesDoPagamento, proximaRenovacao, renovacoes,
  somarMeses, type Cobranca, type Credito, type Mensalidade, type Renovacao } from "./financeiro.ts";
import { dadosMensagem, type DadosMsg } from "./mensagens.ts";
import { parametros } from "./parametros.ts";
import { flt } from "./texto.ts";
import { aulasMes } from "./trabalho.ts";

export const ORDEM = ["cobrar", "pago_sem_aula", "sem_pagar_sem_aula", "vence_logo", "sem_aula_recente", "cadastro_incompleto", "em_dia"];
export const ROTULO: Record<string, string> = { cobrar: "Vencida", pago_sem_aula: "Pagou sem aula", sem_pagar_sem_aula: "Sem aula nem pagamento",
  vence_logo: "Vence logo", sem_aula_recente: "Sem aula", cadastro_incompleto: "Cadastro incompleto", em_dia: "Em dia" };
export const COR: Record<string, string> = { cobrar: "vermelho", pago_sem_aula: "amarelo", sem_pagar_sem_aula: "amarelo", vence_logo: "amarelo",
  sem_aula_recente: "vermelho", cadastro_incompleto: "azul", em_dia: "verde" };
export const GRAV: Record<string, number> = { vermelho: 1, amarelo: 2, azul: 3, verde: 4 };
export const SEM_AULA = ["pago_sem_aula", "sem_pagar_sem_aula", "sem_aula_recente"];
export const LIMITE_DIAS = 14, LIMITE_HIBRIDA = 35, DIAS_UTEIS_MIN = 14, JANELA_DADOS = 120;
export const RE_MES = /^\d{4}-(0[1-9]|1[0-2])$/;

const dia = (iso: string) => numeroDoDia(iso)!;
const somar = (iso: string, n: number) => isoDoDia(dia(iso) + n);
const mmAaaa = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
/** f"{x:.2f}".replace(".", ",") */
const virgula2 = (x: number) => arred(x, 2).toFixed(2).replace(".", ",");

// ---------- ajudas que eram do main.py ----------
/** Ids de quem tem algum horário fixo ativo na Agenda. */
export async function alunosComHorario(b: Banco): Promise<Set<number>> {
  return new Set((await b.query("SELECT DISTINCT cliente_id FROM agenda_fixos WHERE excluido_em IS NULL")).map((r) => r.cliente_id as number));
}

/** Regra única de "o aluno tem aula": Pacote e Mensalidade sempre; Consultoria e Avaliação só com horário fixo; sem tipo, vale o plano. */
export function temAulas(c: Linha, comHorario: Set<number>): boolean {
  const tipo = (c.tipo_servico || "").trim();
  return tipo === "Pacote de Aulas" || tipo === "Mensalidade" || comHorario.has(c.id) || (!tipo && aulasMes(c) > 0);
}

/** (início, fim) das fases de bloqueio das Campanhas. */
export async function fasesBloqueio(b: Banco): Promise<[unknown, unknown][]> {
  return (await b.query("SELECT inicio, fim FROM campanha_fases WHERE tipo='bloqueio' AND inicio IS NOT NULL AND fim IS NOT NULL"))
    .map((f) => [f.inicio, f.fim]);
}

/** {cliente_id: [(início, fim)]} dos meses pulados: da renovação pulada até a véspera da volta. */
export async function pausasPorAluno(b: Banco): Promise<Map<number, [string, string][]>> {
  const out = new Map<number, [string, string][]>();
  for (const e of await b.query("SELECT cliente_id, data, ate FROM cliente_eventos WHERE tipo='pausa' AND excluido_em IS NULL")) {
    const ini = dataIso(e.data);
    if (!ini) continue;
    let volta = dataIso(e.ate);
    if (!volta || volta <= ini) volta = proximaRenovacao(ini);
    if (!out.has(e.cliente_id)) out.set(e.cliente_id, []);
    out.get(e.cliente_id)!.push([ini, somar(volta, -1)]);
  }
  return out;
}

/** Quantos dias depois de `ultima` até `hoje` (inclusive) caem em algum intervalo [início, fim]; intervalos que se cruzam contam uma vez. */
export function diasParados(ultima: string, hoje: string, intervalos: [string, string][]): number {
  let total = 0, contado = dia(ultima);
  const h = dia(hoje);
  const ordenados = [...intervalos].sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : x[1] < y[1] ? -1 : x[1] > y[1] ? 1 : 0));
  for (const [i, f] of ordenados) {
    const ini = Math.max(dia(i), contado + 1);
    const fim = Math.min(dia(f), h);
    if (fim >= ini) {
      total += fim - ini + 1;
      contado = fim;
    }
  }
  return total;
}

// ---------- valores e botões ----------
/** Crédito sugerido pelas aulas não usadas: valor × (1 − feitas ÷ esperadas), entre 0 e o valor. Sem aula feita: o valor inteiro. */
export function sugerirCredito(valorBruto: unknown, feitas: number, esperadas: number): number {
  const valor = flt(valorBruto);
  if (valor <= 0) return 0;
  if (!feitas) return arred(valor, 2);
  if (!esperadas || esperadas <= 0) return 0;
  return arred(Math.min(Math.max(valor * (1 - feitas / esperadas), 0), valor), 2);
}

/** O {valor} da mensagem de renovação: 'R$ 400,00' ou 'R$ 280,00 (R$ 400,00 − R$ 120,00 de crédito das aulas não usadas em 10/2026)'. */
export function fraseValor(valorBruto: unknown, lista?: Credito[] | null): string {
  const valor = flt(valorBruto);
  if (valor <= 0) return "";
  const [total, ids] = creditoAplicavel(lista ?? [], valor);
  if (!total) return moeda(valor);
  const meses = (lista ?? []).filter((x) => ids.includes(x.id)).map((x) => mmAaaa(x.mes + "-01"));
  return `${moeda(Math.max(valor - total, 0))} (${moeda(valor)} − ${moeda(total)} de crédito das aulas não usadas em ${meses.join(" e ")})`;
}

export type Acao = Record<string, unknown>;

/** Botão "Registrar pagamento" com o valor e o mês da renovação; vencido, o mesmo total do "Cobrar". */
export function acaoPagamento(c: { id: number; nome: string }, efetiva: string, valor: unknown, credito: number = 0, cob: Cobranca | null = null): Acao {
  const aPagar = cob ? cob.total : Math.max(flt(valor) - flt(credito), 0);
  const cred = cob ? cob.credito : credito;
  const dados: Record<string, unknown> = { titulo: `Registrar pagamento de ${c.nome}`, cliente_id: c.id, valor: aPagar ? virgula2(aPagar) : "",
    descricao: `Mensalidade ${efetiva.slice(5, 7)}/${efetiva.slice(0, 4)}`, mensal: virgula2(flt(valor)) };
  const nota = cred ? [`Crédito de ${moeda(cred)} descontado`] : [];
  if (cob && (cob.multa || cob.juros)) {
    nota.push(`multa de ${moeda(cob.multa)} e juros de ${moeda(cob.juros)} incluídos`);
    dados.encargos = virgula2(cob.multa + cob.juros);
  }
  if (nota.length) dados.nota = nota.join(" · ");
  return { rotulo: "Registrar pagamento", dialogo: "dlg-pgto", classe: "verde", dados };
}

export const acaoAgenda = (cid: number): Acao => ({ rotulo: "Abrir agenda", href: `/agenda?aluno=${cid}` });
export const acaoAdiantado = (cid: number): Acao => ({ rotulo: "Já pagou adiantado", href: `/clientes/${cid}#pagamentos` });

export function acaoPulou(c: { id: number; nome: string }, efetiva: string): Acao {
  const nova = proximaRenovacao(efetiva);
  return { rotulo: "Pulou o mês", dialogo: "dlg-pulou", classe: "claro",
    dados: { titulo: `${c.nome} pulou o mês? A renovação de ${dataBr(efetiva)} vai para ${dataBr(nova)}, sem cobrança.`, acao: `/alunos/${c.id}/pulou` } };
}

export function acaoCredito(c: { id: number; nome: string }, valor: number, mes: string): Acao {
  return { rotulo: `Crédito na próxima (${moeda(valor)})`, dialogo: "dlg-credito", classe: "claro",
    dados: { titulo: `Crédito para ${c.nome}: não usou ${mmAaaa(mes + "-01")}`, acao: `/alunos/${c.id}/credito`, valor: virgula2(valor), mes } };
}

// ---------- o algoritmo ----------
export interface Ciclo { inicio: string; fim: string; mes: string; feitas: number; esperadas: number; uteis: number }
export interface Estado {
  id: number; nome: string; tel: unknown; valor: number; tem_aulas: boolean; consultoria: boolean;
  renovacao: { efetiva: string; vence: string | null; dias: number | null; vencida: boolean; pendente: boolean; dia: number | null } | null;
  pagamento: { mes: string; situacao: string | null; previsto: number; recebido: number; ultimo_pago: string | null; coberto_ate: string | null };
  uso: { ciclo: Ciclo | null; mes_atual: number; ultima: string | null; dias_sem: number | null };
  credito: number; credito_total: number; credito_sugerido: number | null; pausado_no_mes: boolean;
  situacao: string; rotulo: string; cor: string; grav: number; modelo: string | null; botao: string | null; extra: Record<string, unknown> | null;
  data_modelo: string | null; cobranca: Cobranca | null; cartao: ReturnType<typeof cartaoCobranca> | null; ordem: string;
  frase_valor: string; texto: string; acoes: Acao[];
}

/** {cliente_id: estado} dos alunos ativos (ou só dos `ids`), em poucas idas ao banco. `hoje` = 'AAAA-MM-DD'. */
export async function estado(b: Banco, hoje: string, ids?: Iterable<number> | null): Promise<Map<number, Estado>> {
  const h = hoje, lim7 = somar(h, 7);
  let lista: number[] | null = null;
  if (ids) {
    lista = [...new Set([...ids].map((i) => Math.trunc(i)))].sort((x, y) => x - y);
    if (!lista.length) return new Map();
  }
  // a lista vai num parâmetro só (JSON): o D1 aceita até 100 parâmetros por consulta
  const [so, argsSo] = lista === null || lista.length > 500 ? ["", [] as string[]] : [" AND cliente_id IN (SELECT value FROM json_each(?))", [JSON.stringify(lista)]];
  const um = lista && lista.length === 1 ? lista[0] : null;
  const desde = somar(h, -JANELA_DADOS);
  const [todos, ren, comHorario, fases, pausas, parCob, ultRows, aulaRows, pagoRows, evPag, evPc, livres] = await Promise.all([
    b.query(`SELECT id, nome, status, telefone, tipo_servico, plano, valor, data_inicio, data_renovacao FROM clientes
      WHERE excluido_em IS NULL AND status='ativo' ORDER BY nome`),
    renovacoes(b, um), alunosComHorario(b), fasesBloqueio(b), pausasPorAluno(b), parametros(b, "cobranca"),
    b.query(`SELECT cliente_id, MAX(data) AS ultima FROM cliente_eventos WHERE tipo='aula' AND excluido_em IS NULL${so} GROUP BY cliente_id`, argsSo),
    b.query(`SELECT cliente_id, data FROM cliente_eventos WHERE tipo='aula' AND excluido_em IS NULL AND data >= ?${so}`, [desde, ...argsSo]),
    b.query(`SELECT cliente_id, data, valor, meses FROM lancamentos WHERE escopo='PJ' AND tipo='entrada' AND pago_em IS NOT NULL AND excluido_em IS NULL
      AND cliente_id IS NOT NULL${so}`, argsSo),
    b.query(`SELECT cliente_id, data FROM cliente_eventos WHERE tipo='pagamento' AND excluido_em IS NULL${so}`, argsSo),
    b.query(`SELECT cliente_id, tipo, data FROM cliente_eventos WHERE tipo IN ('pausa','credito') AND excluido_em IS NULL${so}`, argsSo),
    creditos(b, um),
  ]);
  const alunos = todos.filter((c) => lista === null || lista.includes(c.id));
  if (!alunos.length) return new Map();
  const bloqueio = fases.map(([a, z]) => [dataIso(a), dataIso(z)] as [string | null, string | null]).filter(([i, f]) => i && f) as [string, string][];
  const ultima = new Map(ultRows.map((r) => [r.cliente_id as number, dataIso(r.ultima)]));
  const aulas = new Map<number, string[]>();
  for (const r of aulaRows) {
    if (!aulas.has(r.cliente_id)) aulas.set(r.cliente_id, []);
    aulas.get(r.cliente_id)!.push(String(r.data).slice(0, 10));
  }
  const pagos = new Map<number, string[]>(), ultimoPago = new Map<number, string>(), lotes = new Map<number, [string, number, number | null][]>();
  for (const r of pagoRows) {
    const d = String(r.data).slice(0, 10);
    if (!pagos.has(r.cliente_id)) pagos.set(r.cliente_id, []);
    pagos.get(r.cliente_id)!.push(d);
    ultimoPago.set(r.cliente_id, (ultimoPago.get(r.cliente_id) ?? "") > d ? ultimoPago.get(r.cliente_id)! : d);
    if (!lotes.has(r.cliente_id)) lotes.set(r.cliente_id, []);
    lotes.get(r.cliente_id)!.push([d, r.valor, r.meses]);
  }
  for (const r of evPag) {
    if (!pagos.has(r.cliente_id)) pagos.set(r.cliente_id, []);
    pagos.get(r.cliente_id)!.push(String(r.data).slice(0, 10));
  }
  const pulos = new Map<number, string[]>(), mesesCredito = new Map<number, Set<string>>();
  for (const r of evPc) {
    if (r.tipo === "pausa") {
      if (!pulos.has(r.cliente_id)) pulos.set(r.cliente_id, []);
      pulos.get(r.cliente_id)!.push(String(r.data).slice(0, 10));
    } else {
      if (!mesesCredito.has(r.cliente_id)) mesesCredito.set(r.cliente_id, new Set());
      mesesCredito.get(r.cliente_id)!.add(String(r.data).slice(0, 7));
    }
  }
  const mens = new Map((await mensalidades(b, h.slice(0, 7), lista === null || lista.length !== 1 ? ren : null)).map((i) => [i.id, i]));
  const msgs: { modelos?: Record<string, Valor>; dados?: DadosMsg } = {};

  const out = new Map<number, Estado>();
  for (const c of alunos) {
    const cid: number = c.id;
    const tipo = (c.tipo_servico || "").trim();
    const tem = temAulas(c, comHorario);
    const valor = flt(c.valor);
    const r = ren.get(cid);
    const efetiva = r ? dataIso(r.efetiva) : null;
    const vence = r ? dataIso(r.vence) || efetiva : null;
    const dias = vence ? dia(vence) - dia(h) : null;
    const vencida = Boolean(vence) && vence! < h;
    let parados: [string, string][] = [...bloqueio, ...(pausas.get(cid) ?? [])];
    const ult = ultima.get(cid) ?? null;
    const hibrida = tipo === "Consultoria Híbrida";

    let ciclo: Ciclo | null = null, julgar = false, pagou: boolean | null = null, sugerido: number | null = null;
    if (efetiva && tem && !vencida) {
      let i = 0;
      while (proximaRenovacao(efetiva, -i) > lim7 && i < 24) i++;
      const fim = proximaRenovacao(efetiva, -i);
      const ini = proximaRenovacao(efetiva, -i - 1);
      const menosHib = somar(fim, -LIMITE_HIBRIDA);
      const janela = hibrida ? (ini < menosHib ? ini : menosHib) : ini;
      const total = dia(fim) - dia(janela);
      const uteis = total - diasParados(somar(janela, -1), somar(fim, -1), parados);
      const feitas = (aulas.get(cid) ?? []).filter((d) => janela <= d && d < fim).length;
      const am = aulasMes(c);
      const esperadas = total && am ? (am * uteis) / total : 0;
      ciclo = { inicio: ini, fim, mes: ini.slice(0, 7), feitas, esperadas: arred(esperadas, 1), uteis };
      sugerido = sugerirCredito(valor, feitas, esperadas);
      const inicioAluno = dataIso(c.data_inicio);
      const fim7 = somar(fim, 7);
      const tratado = (mesesCredito.get(cid)?.has(ini.slice(0, 7)) ?? false) || (pulos.get(cid) ?? []).some((d) => ini <= d && d <= fim7);
      pagou = pagoNoCiclo(r ?? null, i, ini, fim, [...(pagos.get(cid) ?? []), ...datasCobertas(lotes.get(cid) ?? [], valor)]);
      julgar = feitas === 0 && uteis >= DIAS_UTEIS_MIN && !tratado && pagou !== null && (inicioAluno === null || inicioAluno <= janela);
      if (tratado) parados = [...parados, [janela, somar(fim, -1)]];
    }

    const limite = hibrida ? LIMITE_HIBRIDA : LIMITE_DIAS;
    let diasSem: number | null = null, recente = false;
    if (tem) {
      if (ult === null) {
        const iniAluno = dataIso(c.data_inicio);
        recente = !(iniAluno && iniAluno > somar(h, -limite));
      } else {
        diasSem = dia(h) - dia(ult) - diasParados(ult, h, parados);
        recente = diasSem > limite;
      }
    }
    const faltas = ([["telefone", !c.telefone], ["renovação", !c.data_renovacao]] as [string, boolean][]).filter(([, f]) => f).map(([t]) => t);
    const minhas = livres.get(cid) ?? [];
    const totalLivre = arred(minhas.reduce((a, x) => a + x.valor, 0), 2);
    const credito = creditoAplicavel(minhas, valor)[0];

    const sit = vencida ? "cobrar" : julgar && pagou ? "pago_sem_aula" : julgar ? "sem_pagar_sem_aula"
      : vence && dias! <= 7 ? "vence_logo" : recente ? "sem_aula_recente" : faltas.length ? "cadastro_incompleto" : "em_dia";

    const e: Estado = {
      id: cid, nome: c.nome, tel: c.telefone, valor, tem_aulas: tem, consultoria: tipo.startsWith("Consultoria"),
      renovacao: efetiva ? { efetiva, vence, dias, vencida, pendente: Boolean(r && r.pendente), dia: r!.dia } : null,
      pagamento: pagamento(mens.get(cid), h.slice(0, 7), ultimoPago.get(cid)),
      uso: { ciclo, mes_atual: (aulas.get(cid) ?? []).filter((d) => d.slice(0, 7) === h.slice(0, 7)).length, ultima: ult, dias_sem: diasSem },
      credito, credito_total: totalLivre, credito_sugerido: sugerido,
      pausado_no_mes: (pausas.get(cid) ?? []).some(([i, f]) => i <= h && f >= h.slice(0, 7) + "-01"),
      situacao: sit, rotulo: ROTULO[sit], cor: COR[sit], grav: GRAV[COR[sit]], modelo: null, botao: null, extra: null,
      data_modelo: null, cobranca: null, cartao: null, ordem: c.nome, frase_valor: fraseValor(valor, livres.get(cid)), texto: "", acoes: [],
    };
    const up = ultimoPago.get(cid);
    const recentePgto = Boolean(up) && up! >= somar(h, -365);
    textoEAcoes(e, c, sit, efetiva, ciclo, ult, faltas, parCob, h, tem && !comHorario.has(cid), recentePgto);
    await cartao(b, e, c, h, msgs);
    out.set(cid, e);
  }
  return out;
}

export async function estadoAluno(b: Banco, cid: number, hoje: string): Promise<Estado | null> {
  return (await estado(b, hoje, [cid])).get(cid) ?? null;
}

function pagamento(item: Mensalidade | undefined, mes: string, ultimo: string | undefined): Estado["pagamento"] {
  return { mes, situacao: item ? item.situacao : null, previsto: item ? item.previsto : 0, recebido: item ? item.recebido : 0,
    ultimo_pago: ultimo ? ultimo.slice(0, 7) : null, coberto_ate: item ? item.coberto_ate : null };
}

/** Pagamento que cobre N meses vale também nos N−1 meses seguintes. */
function datasCobertas(lotes: [string, number, number | null][], valor: number): string[] {
  const out: string[] = [];
  for (const [d, v, meses] of lotes) {
    const n = mesesDoPagamento(v, valor, meses);
    if (n >= 2) for (let k = 1; k < n; k++) out.push(proximaRenovacao(d, k));
  }
  return out;
}

/** O ciclo [ini, fim) foi pago? null se foi um mês pulado. i = quantos meses antes da renovação efetiva ele fechou. */
function pagoNoCiclo(r: Renovacao | null, i: number, ini: string, fim: string, datas: string[]): boolean | null {
  const j = r ? r.ciclos - 1 - i : -1;
  if (r && 0 <= j && j < r.tipos.length) {
    const tipo = r.tipos[j];
    if (tipo === "pausa") return null;
    return !(tipo === "renovacao" && r.pendente && j === r.ciclos - 1);
  }
  const a = somar(ini, -ANTECEDENCIA), z = somar(fim, -ANTECEDENCIA);
  return datas.some((d) => a <= d && d < z);
}

function textoEAcoes(e: Estado, c: Linha, sit: string, efetiva: string | null, ciclo: Ciclo | null, ult: string | null, faltas: string[],
  parCob: Record<string, Valor>, h: string, converter: boolean, recentePgto: boolean): void {
  const cid = c.id as number, valor = e.valor, credito = e.credito;
  const ren = e.renovacao;
  const vence = ren?.vence || efetiva;
  const cobreTudo = credito > 0 && credito >= valor - 0.005;
  const pagar = vence && !cobreTudo ? acaoPagamento(c as { id: number; nome: string }, vence, valor, credito) : null;
  const pulou = efetiva ? acaoPulou(c as { id: number; nome: string }, efetiva) : null;
  const wa = { wa: true };
  const naoTemAula = { rotulo: "Não tem aula (consultoria)", href: `/clientes?ids=${cid}&motivo=sem-aula` };
  const extras = converter && ult === null ? [naoTemAula] : [];
  const mesCiclo = ciclo ? mmAaaa(ciclo.inicio) : "";
  if (sit === "cobrar") {
    const cob = cobranca(valor, vence!, h, parCob, credito, ren?.dia ?? null);
    e.texto = `renovação venceu em ${dataBr(vence)}`;
    e.cobranca = cob;
    const terceiro = recentePgto ? acaoAdiantado(cid) : { rotulo: "Pular mês", href: `/clientes/${cid}#renovacao` };
    if (cob) {
      e.modelo = "cobranca";
      e.data_modelo = dataBr(vence);
      e.extra = textoCobranca(cob);
      e.botao = `Cobrar ${moeda(cob.total)}`;
      e.acoes = [acaoPagamento(c as { id: number; nome: string }, vence!, valor, credito, cob), wa, terceiro];
    } else if (cobreTudo) {
      e.texto += `: o crédito de ${moeda(credito)} cobre esse mês`;
      e.acoes = [pulou!];
    } else {
      e.modelo = "renovacao";
      e.data_modelo = dataBr(vence);
      e.extra = { valor: e.frase_valor };
      e.acoes = pagar ? [pagar, wa, terceiro] : [pulou!, wa];
    }
  } else if (sit === "pago_sem_aula") {
    e.texto = `pagou e não teve aula em ${mesCiclo}`;
    e.acoes = [pulou!, acaoCredito(c as { id: number; nome: string }, e.credito_sugerido!, ciclo!.mes), ...extras];
  } else if (sit === "sem_pagar_sem_aula") {
    e.texto = `sem aula e sem pagamento em ${mesCiclo}: pulou o mês?`;
    e.acoes = [...[pulou, pagar].filter((x): x is Acao => Boolean(x)), ...extras];
  } else if (sit === "vence_logo") {
    e.texto = `renovação em ${dataBr(vence)}`;
    e.modelo = "renovacao";
    e.data_modelo = dataBr(vence);
    e.extra = { valor: e.frase_valor };
    e.acoes = [pagar || pulou, wa, pagar && recentePgto ? acaoAdiantado(cid) : null].filter((x): x is Acao => Boolean(x));
  } else if (sit === "sem_aula_recente") {
    e.texto = ult ? `sem aula desde ${dataBr(ult)}` : "nenhuma aula registrada";
    if (ult) {
      e.modelo = "falta";
      e.data_modelo = dataBr(ult);
    }
    e.acoes = [acaoAgenda(cid), ...(ult ? [wa] : []), ...extras];
  } else if (sit === "cadastro_incompleto") {
    e.texto = "cadastro incompleto: falta " + faltas.join(" e ");
    e.acoes = [{ rotulo: "Completar cadastro", href: `/clientes/${cid}#cadastro` }];
  } else {
    e.texto = "em dia";
    e.acoes = [];
  }
  if (sit === "cobrar" && e.cobranca && e.cobranca.credito) e.texto += ` (crédito de ${moeda(e.cobranca.credito)} já descontado)`;
  else if (e.credito && ["pago_sem_aula", "sem_pagar_sem_aula", "vence_logo"].includes(sit)) e.texto += ` (crédito de ${moeda(e.credito)} no próximo pagamento)`;
  e.ordem = sit === "cobrar" || sit === "vence_logo" ? vence! : c.nome;
}

/** Cobrança do dia (vencido ou a até 2 dias): o botão do WhatsApp vira o cartão-imagem com o QR Pix. Sem telefone, pede o telefone. */
async function cartao(b: Banco, e: Estado, c: Linha, hoje: string, msgs: { modelos?: Record<string, Valor>; dados?: DadosMsg }): Promise<void> {
  const ren = e.renovacao;
  if ((e.modelo !== "cobranca" && e.modelo !== "renovacao") || !ren) return;
  if (!msgs.modelos) [msgs.modelos, msgs.dados] = await Promise.all([parametros(b, "msg_whatsapp"), dadosMensagem(b)]);
  const ca = cobrancaAtual(c as { status: string; valor: unknown; nome: string },
    { efetiva: ren.efetiva, vence: ren.vence, cob: e.cobranca, credito: e.credito }, hoje, msgs.modelos, msgs.dados!);
  if (!ca) return;
  if (/\d/.test(String(e.tel ?? ""))) {
    e.botao = rotuloCobranca(ca)[0];
    e.cartao = cartaoCobranca(e.id, ca.codigo);
  } else {
    e.modelo = null;
    e.acoes = e.acoes.map((x) => (x.wa ? { rotulo: "Cadastre o telefone", href: `/clientes/${e.id}#cadastro` } : x));
  }
}

/** Frase do alerta: 'Nome — situação'. */
export function frase(e: Estado): string {
  return `${e.nome} — ${e.texto}`;
}

export { RE_MES as RE_MES_ALUNO, somarMeses };

/**
 * Crédito do mês pago e não usado (dar_credito): vira desconto no próximo pagamento. valor vazio = o sugerido; não passa da
 * mensalidade. mes = 'AAAA-MM' (vazio = o ciclo analisado, senão o mês passado). [mensagem, erro].
 */
export async function darCredito(b: Banco, cid: number, valorBruto: number | null, mesBruto: string | null, hoje: string): Promise<[string | null, string | null]> {
  const c = await b.um("SELECT nome, valor FROM clientes WHERE id=? AND excluido_em IS NULL", [cid]);
  if (!c) return [null, "Aluno não encontrado."];
  const e = await estadoAluno(b, cid, hoje);
  const mes = mesBruto || ((e && e.uso.ciclo ? e.uso.ciclo.mes : null) || somarMeses(hoje.slice(0, 7), -1));
  if (!RE_MES.test(mes)) return [null, "Mês inválido."];
  let valor = valorBruto === null || valorBruto === undefined ? (e ? e.credito_sugerido : null) : valorBruto;
  if (!valor || valor <= 0) return [null, "Informe o valor do crédito (maior que zero)."];
  valor = arred(valor, 2);
  const teto = flt(c.valor);
  if (teto > 0) valor = Math.min(valor, teto);
  if (await b.um("SELECT 1 AS ja FROM cliente_eventos WHERE cliente_id=? AND tipo='credito' AND excluido_em IS NULL AND substr(data,1,7)=?", [cid, mes]))
    return [null, `${c.nome} já tem crédito de ${mmAaaa(mes + "-01")}: veja o histórico.`];
  await b.run("INSERT INTO cliente_eventos (cliente_id, tipo, data, valor, descricao) VALUES (?, 'credito', ?, ?, ?)",
    [cid, mes + "-01", valor, `Crédito: não usou ${mmAaaa(mes + "-01")}`]);
  return [`Crédito de ${moeda(valor)} para ${c.nome}: será descontado no próximo pagamento.`, null];
}
