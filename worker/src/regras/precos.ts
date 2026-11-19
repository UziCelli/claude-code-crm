/**
 * Motor de preços (port de app/precos.py): o mesmo cálculo da Grade, das Propostas, do Explorador, da ficha e do Painel.
 * Tudo sai dos parâmetros de Configurações e dos custos dos locais; nada da planilha.
 */
import type { Banco } from "../banco/banco.ts";
import type { Linha, Valor } from "../banco/tipos.ts";
import { arred } from "../arred.ts";
import { relogioMes } from "./mes.ts";
import { custoPessoalMedio, custosFixosRateio, pctDas, type CustosFixos } from "./financeiro.ts";
import { parametros, parametrosEmOrdem } from "./parametros.ts";
import { flt } from "./texto.ts";
import { horasTrabalhoDetalhe, type Trabalho } from "./trabalho.ts";

export const SEMANAS_MES = 4.33;
export const PLANOS: [string, number, number][] = [["Pacote de Aulas", 4, 0], ["Pacote de Aulas", 8, 0], ["Pacote de Aulas", 12, 0],
  ["Pacote de Aulas", 16, 0], ["Mensalidade", 0, 1], ["Mensalidade", 0, 2], ["Mensalidade", 0, 3], ["Mensalidade", 0, 4],
  ["Mensalidade", 0, 5], ["Aula avulsa", 0, 0], ["Consultoria Online", 0, 0], ["Consultoria Híbrida", 0, 0], ["Avaliação Física", 0, 0]];
export const TIPOS_PLANO = new Set(PLANOS.map(([t]) => t));
export const PARTES_TRABALHO = ["aulas", "deslocamento", "planejamento", "consultoria", "avaliacao"] as const;
export type Parte = (typeof PARTES_TRABALHO)[number];
export const HORAS_GRADE = Array.from({ length: 19 }, (_, i) => i + 5);

export interface SalarioHora { ligado: boolean; usado: boolean; custo_pessoal: number; meses: number; horas: number; horas_cheia: number;
  horas_base: number; piso: boolean; partes: Record<string, number>; valor_hora: number; fixo: number }
export interface Rateio extends CustosFixos { horas: number; horas_trabalho: number; horas_cheia: number; piso: boolean; por_hora: number }

/** Os parâmetros do motor (carregar_parametros). Chaves numéricas (pessoas) em Map, como os dicts de int do Python. */
export interface Params {
  das: number;
  taxas: Record<string, number>;
  margens: Record<string, number>;
  margens_alvo: Record<string, number>;
  taxa_cia: Map<number, number>;
  cia_max: number;
  grupo_mo: Map<number, number>;
  locais: Map<string, Linha>;
  cia_desloc: Record<string, Valor>;
  cia_mensal: Record<string, Valor>;
  mo: Record<string, Valor>;
  salario_hora?: SalarioHora;
  rateio?: Rateio;
  rateio_hora?: number;
}

export interface Troca {
  locais?: Map<string, Linha>;
  taxa_cia?: Map<number, number>;
  cia_max?: number;
  cia_desloc?: Record<string, Valor>;
  cia_mensal?: Record<string, Valor>;
}

/** [{pessoas: preço da aula na CIA}, máximo de pessoas por horário], dos parâmetros taxa_cia. */
export async function taxasCia(b: Banco): Promise<[Map<number, number>, number]> {
  const cia = await parametrosEmOrdem(b, "taxa_cia");
  const precos = new Map<number, number>();
  let max: number | null = 3;
  for (const [k, v] of cia) {
    if (/^\d+$/.test(k)) precos.set(Number(k), v as number);
    if (k === "maximo_pessoas") max = v === null ? null : Math.trunc(Number(v));
  }
  if (max === null) throw new TypeError("taxa_cia.maximo_pessoas vazio");
  return [precos, max];
}

/** {local: custos} dos locais criados pelo "+ Novo local" (tabela locais_custos). */
export async function custosLocais(b: Banco): Promise<Map<string, Linha>> {
  return new Map((await b.query("SELECT * FROM locais_custos")).map((r) => [r.local as string, r]));
}

function numericas(o: Record<string, Valor>): Record<string, number> {
  return o as Record<string, number>;
}

/** Monta os parâmetros do motor. `troca`: custos simulados, sem gravar (a prévia do pop-up do local e da CIA). */
export async function carregarParametros(b: Banco, troca?: Troca): Promise<Params> {
  const hoje = relogioMes.hoje();
  const mes = relogioMes.mesAtual();
  // O que as horas de trabalho, o salário automático e o rateio vão ler sai já na 1ª ida (fica no cache do pedido).
  const preaquecer = Promise.all([horasTrabalhoDetalhe.leituras(b), custoPessoalMedio(b, mes), custosFixosRateio(b, mes), parametros(b, "metas")]);
  const [das, taxas, margens, margensAlvo, [taxaCia, ciaMax], grupoMo, locais, ciaDesloc, ciaMensal, mo] = await Promise.all([
    pctDas(b, hoje), parametros(b, "taxa_pagamento"), parametros(b, "margem_minima"), parametros(b, "margem_alvo"), taxasCia(b),
    parametrosEmOrdem(b, "grupo_mao_obra_extra"), custosLocais(b), parametros(b, "cia_deslocamento"), parametros(b, "cia_mensal"),
    parametros(b, "mao_obra"),
  ]);
  await preaquecer;
  const p: Params = {
    das, taxas: numericas(taxas), margens: numericas(margens), margens_alvo: numericas(margensAlvo), taxa_cia: taxaCia, cia_max: ciaMax,
    grupo_mo: new Map(grupoMo.map(([k, v]) => {
      if (!/^\s*[+-]?\d+\s*$/.test(k)) throw new TypeError(`grupo_mao_obra_extra: chave '${k}' não é número`);
      return [Number(k), v as number];
    })),
    locais, cia_desloc: ciaDesloc, cia_mensal: ciaMensal, mo,
  };
  if (troca) {
    if (troca.locais) p.locais = new Map([...p.locais, ...troca.locais]);
    if (troca.taxa_cia !== undefined) p.taxa_cia = troca.taxa_cia;
    if (troca.cia_max !== undefined) p.cia_max = troca.cia_max;
    if (troca.cia_desloc !== undefined) p.cia_desloc = troca.cia_desloc;
    if (troca.cia_mensal !== undefined) p.cia_mensal = troca.cia_mensal;
  }
  const trabalho = await horasTrabalhoDetalhe(b, p); // uma vez só: salário e custos fixos dividem pela mesma base
  const [auto, rateio] = await Promise.all([valorHoraAutomatico(b, p, trabalho), rateioFixos(b, p, trabalho.total)]);
  p.salario_hora = auto;
  if (auto.usado) p.mo = { ...p.mo, valor_hora: auto.valor_hora };
  p.rateio = rateio;
  p.rateio_hora = rateio.por_hora;
  return p;
}

/** [base que divide o salário e os custos fixos, horas da agenda cheia]: a agenda cheia é o piso. */
export async function horasBase(b: Banco, horas: number): Promise<[number, number]> {
  const cheia = flt((await parametros(b, "metas")).horas_vendaveis);
  return [Math.max(flt(horas), cheia), cheia];
}

/** Custos fixos do negócio divididos pelas mesmas horas do salário (horas_base). */
export async function rateioFixos(b: Banco, p: Params, horas = 0): Promise<Rateio> {
  const [fixos, [base, cheia]] = await Promise.all([custosFixosRateio(b, relogioMes.mesAtual(), [...p.locais.keys()]), horasBase(b, horas)]);
  return { ...fixos, horas: arred(base, 1), horas_trabalho: arred(flt(horas), 1), horas_cheia: arred(cheia, 1), piso: cheia > flt(horas),
    por_hora: base > 0 ? arred(fixos.total / base, 4) : 0 };
}

/** Salário por hora = custos pessoais do mês ÷ horas de trabalho (horas_base). Desligado: vale o valor_hora digitado. */
export async function valorHoraAutomatico(b: Banco, p: Params, trabalho?: Trabalho): Promise<SalarioHora> {
  const mo = p.mo ?? {};
  const fixo = flt(mo.valor_hora);
  const ligado = Boolean(flt(mo.valor_hora_auto)) && fixo > 0; // valor_hora 0 desliga a regra toda
  const [[custo, meses], t] = await Promise.all([
    ligado ? custoPessoalMedio(b, relogioMes.mesAtual()) : Promise.resolve<[number, number]>([0, 0]),
    trabalho ? Promise.resolve(trabalho) : horasTrabalhoDetalhe(b, p),
  ]);
  const horas = ligado ? t.total : 0;
  const [base, cheia] = await horasBase(b, horas);
  const usado = custo > 0 && horas > 0;
  const partes: Record<string, number> = {};
  for (const k of PARTES_TRABALHO) partes[k] = arred(t[k], 1);
  return { ligado, usado, custo_pessoal: arred(custo, 2), meses, horas: arred(horas, 1), horas_cheia: arred(cheia, 1),
    horas_base: arred(base, 1), piso: cheia > horas, partes, valor_hora: usado ? arred(custo / base, 2) : fixo, fixo };
}

// ---------- planos e tempo de trabalho ----------
export interface BaseMotor { tipo_servico: string; local: string | null; qtd_aulas: number; freq_semanal: number; sessoes_mes: number }

/** O plano que o motor precifica: tipo, aulas e local. Pacote = nº de aulas; Mensalidade = vezes por semana × 4,33. */
export function baseMotor(tipo: string, qtd = 0, freq = 0, local: string | null = null): BaseMotor {
  const q = Math.trunc(flt(qtd)), f = Math.trunc(flt(freq));
  const sessoes = tipo === "Pacote de Aulas" ? q : tipo === "Mensalidade" ? f * SEMANAS_MES : tipo === "Aula avulsa" || tipo === "Consultoria Híbrida" ? 1 : 0;
  return { tipo_servico: tipo, local, qtd_aulas: tipo === "Pacote de Aulas" ? q : 0, freq_semanal: tipo === "Mensalidade" ? f : 0, sessoes_mes: sessoes };
}

/** [R$ por aula, minutos por aula] da ida até o local. */
export function deslocamento(p: Params, local: string | null | undefined): [number, number] {
  if (local === "CIA") {
    const c = p.cia_desloc ?? {};
    return [flt(c.reais_por_aula), flt(c.minutos_por_aula)];
  }
  const c = (local !== null && local !== undefined && p.locais.get(local)) || {};
  return [flt(c.deslocamento), flt(c.tempo_deslocamento)];
}

/** A taxa mensal fixa do local dividida pelas aulas do mês (0 sem taxa ou sem aulas). */
export function mensalPorAula(p: Params, local: string | null | undefined): number {
  const c: Record<string, Valor> = local === "CIA" ? (p.cia_mensal ?? {}) : ((local !== null && local !== undefined && p.locais.get(local)) || {});
  return c.aulas_mes ? flt(c.taxa_mensal) / flt(c.aulas_mes) : 0;
}

/** R$ por aula de um local: taxa + deslocamento + taxa mensal ÷ aulas do mês. */
export function custoPorAula(c: Linha): number {
  const fixo = c.aulas_mes ? (c.taxa_mensal || 0) / c.aulas_mes : 0;
  return (c.taxa_aula || 0) + (c.deslocamento || 0) + fixo;
}

/** R$ por aula (1 pessoa) que o local custa. */
export function custoAulaLocal(p: Params, local: string | null | undefined): number {
  if (local === "CIA") return flt(p.taxa_cia.get(1) ?? 0) + deslocamento(p, "CIA")[0] + mensalPorAula(p, "CIA");
  const c = local !== null && local !== undefined ? p.locais.get(local) : undefined;
  return c ? custoPorAula(c) : 0;
}

const COM_AULA = ["Pacote de Aulas", "Aula avulsa", "Mensalidade"];
const CONSULTORIAS = ["Consultoria Online", "Consultoria Híbrida"];
const AVALIACOES = ["Avaliação Física", "Avaliação"];

/** Minutos do seu trabalho (1 pessoa) num plano, por parte, pela regra do tempo (Configurações > Mão de obra). */
export function partesMinutos(base: BaseMotor, p: Params, local?: string | null): Record<Parte, number> {
  const r = p.mo ?? {};
  const tipo = base.tipo_servico;
  const sessoes = flt(base.sessoes_mes);
  const desloc = deslocamento(p, local || base.local)[1];
  const out: Record<Parte, number> = { aulas: 0, deslocamento: 0, planejamento: 0, consultoria: 0, avaliacao: 0 };
  if (AVALIACOES.includes(tipo)) {
    out.avaliacao = flt(r.min_avaliacao);
    out.deslocamento = desloc;
    return out;
  }
  out.aulas = sessoes * flt(r.min_aula === undefined ? 60 : r.min_aula);
  out.deslocamento = sessoes * desloc;
  if (COM_AULA.includes(tipo)) out.planejamento = flt(r[tipo === "Mensalidade" ? "min_planejamento_mes" : "min_planejamento_pacote"]);
  else if (CONSULTORIAS.includes(tipo)) out.consultoria = flt(r.min_consultoria_mes);
  return out;
}

export function minutosTrabalho(base: BaseMotor, p: Params, local?: string | null): number {
  const m = partesMinutos(base, p, local);
  return PARTES_TRABALHO.reduce((a, k) => a + m[k], 0);
}

/** [custo do negócio, mão de obra (pró-labore), horas de trabalho] de 1 pessoa. */
export function custoServico(base: BaseMotor, p: Params, local?: string | null): [number, number, number] {
  const l = local || base.local;
  const sessoes = flt(base.sessoes_mes);
  const horas = minutosTrabalho(base, p, l) / 60;
  const mo = horas * flt(p.mo?.valor_hora);
  return [custoAulaLocal(p, l) * sessoes + flt(p.rateio_hora) * horas, mo, horas];
}

/** De onde vem o preço de 1 aula num local (Grade: "Por que esse preço?"). */
export function decompor(base: BaseMotor, p: Params, local?: string | null) {
  const l = local || base.local;
  const sessoes = flt(base.sessoes_mes) || 1;
  const [reais, minutosIda] = deslocamento(p, l);
  const taxa = l === "CIA" ? flt(p.taxa_cia.get(1) ?? 0) : flt(((l !== null && l !== undefined && p.locais.get(l)) || {}).taxa_aula);
  const mensal = mensalPorAula(p, l);
  const [resto, mo, horas] = custoServico(base, p, l);
  const rateio = flt(p.rateio_hora) * horas;
  const custo = resto + mo;
  const r = calcular(base, p, { local: l });
  const partes = { taxa, mensal, ida_reais: reais, salario: mo / sessoes, rateio: rateio / sessoes };
  return {
    ...Object.fromEntries(Object.entries(partes).map(([k, v]) => [k, arred(v, 2)])) as typeof partes,
    custo: arred(custo / sessoes, 2), minutos: arred((horas * 60) / sessoes, 1), minutos_ida: minutosIda,
    valor_hora: arred(flt(p.mo?.valor_hora), 2), preco: arred(r.preco_cheio / sessoes, 2), sessoes,
  };
}

/** Multiplicador do preço de cada horário (Grade > Multiplicadores): {hora: x}; abaixo de 1 = vale. */
export async function multHorario(b: Banco): Promise<Map<number, number>> {
  const m = new Map<number, number>();
  for (const [k, v] of await parametrosEmOrdem(b, "mult_horario")) {
    const h = /^\s*[+-]?\d+\s*$/.test(k) ? Number(k) : NaN;
    const x = v === null ? NaN : Number(v);
    if (!Number.isNaN(h) && !Number.isNaN(x)) m.set(h, x);
  }
  return new Map(HORAS_GRADE.map((h) => [h, m.get(h) || 1]));
}

/** Valor da tabela por nº de pessoas; grupo maior que a tabela usa o maior configurado. */
export function porGrupo(tabela: Map<number, number>, pessoas: number, padrao: number): number {
  if (tabela.has(pessoas)) return tabela.get(pessoas)!;
  const menores = [...tabela.keys()].filter((k) => k <= pessoas);
  return menores.length ? tabela.get(Math.max(...menores))! : padrao;
}

function componentes(base: BaseMotor, p: Params, pessoas: number, local?: string | null): [number, number, number] {
  const l = local || base.local;
  const outro = l !== null && l !== undefined ? p.locais.get(l) : undefined;
  if (l === "CIA" && pessoas > p.cia_max) throw new RangeError(`Na CIA o máximo é ${p.cia_max} pessoas`);
  if (outro && outro.max_pessoas && pessoas > outro.max_pessoas) throw new RangeError(`Em ${l} o máximo é ${outro.max_pessoas} pessoas`);
  const sessoes = flt(base.sessoes_mes);
  let [resto, mo, horas] = custoServico(base, p, l);
  // Com o salário automático, a hora já é o seu custo de vida: o grupo não aumenta esse custo (contaria 2 vezes).
  if (!p.salario_hora?.usado) mo *= 1 + porGrupo(p.grupo_mo, pessoas, 0);
  let custo = resto + mo;
  if (l === "CIA" && pessoas > 1) {
    const um = p.taxa_cia.get(1) ?? 0;
    custo += (porGrupo(p.taxa_cia, pessoas, um) - um) * sessoes;
  }
  if (outro) custo += (outro.taxa_pessoa_extra || 0) * (pessoas - 1) * sessoes;
  return [custo, mo, horas];
}

/** Margem do preço de tabela: a de Configurações > Margem alvo; sem ela, a mínima + 10 pontos. */
export function margemAlvo(p: Params, tipo: string): number {
  const minima = tipo in p.margens ? p.margens[tipo] : 0.15;
  const alvo = p.margens_alvo && tipo in p.margens_alvo ? p.margens_alvo[tipo] : minima + 0.1;
  return Math.max(flt(alvo), minima);
}

export interface Opcoes { pessoas?: number; mult_horario?: number; desconto?: number; forma_pagamento?: string; local?: string | null; preco_final?: number | null }

export function calcular(base: BaseMotor, p: Params, o: Opcoes = {}) {
  return calcularMisto([[base, o.mult_horario ?? 1, o.local ?? null]], p, { ...o });
}

/** Proposta com vários horários do mesmo plano: custo = média dos horários; preço = custo ÷ (1 − impostos − taxa − margem). */
export function calcularMisto(horarios: [BaseMotor, number | null, string | null][], p: Params,
  o: { pessoas?: number; desconto?: number; forma_pagamento?: string; preco_final?: number | null; extra?: number[] | null } = {}) {
  if (!horarios.length) throw new RangeError("Escolha pelo menos um horário");
  const pessoas = Math.max(1, Math.trunc(o.pessoas ?? 1));
  const forma = o.forma_pagamento ?? "PIX";
  let desconto = o.desconto ?? 0;
  const precoFinal = o.preco_final ?? null;
  if (!(forma in p.taxas)) throw new RangeError(`Forma de pagamento desconhecida: ${forma}`);
  const base = horarios[0][0];
  const taxa = p.das + p.taxas[forma];
  const margemMin = base.tipo_servico in p.margens ? p.margens[base.tipo_servico] : 0.15;
  const alvo = margemAlvo(p, base.tipo_servico);
  if (1 - taxa - alvo <= 1e-9) throw new RangeError("Imposto + taxa + margem passam de 100%: ajuste em Configurações");
  const comps = horarios.map(([b, , loc]) => componentes(b, p, pessoas, loc));
  let [custo, maoObra, horas] = [0, 1, 2].map((i) => comps.reduce((a, c) => a + c[i], 0) / comps.length);
  const mult = horarios.reduce((a, [, m]) => a + flt(m || 1), 0) / horarios.length;
  let precoCheio = (custo * mult) / (1 - taxa - alvo);
  if (o.extra) {
    const e = [...o.extra, 0, 0, 0, 0].slice(0, 4);
    precoCheio += flt(e[0]);
    custo += flt(e[1]);
    maoObra += flt(e[2]);
    horas += flt(e[3]);
  }
  if (precoFinal !== null && precoFinal > 0 && precoCheio) desconto = 1 - precoFinal / precoCheio;
  if (desconto >= 1 || desconto <= -9) throw new RangeError("Desconto deve ficar abaixo de 100% (e o acréscimo, no máximo 900%)");
  const sessoes = flt(base.sessoes_mes);
  const preco = precoFinal !== null && precoFinal > 0 ? precoFinal : precoCheio * (1 - desconto);
  const lucro = preco * (1 - taxa) - custo;
  const margem = preco ? lucro / preco : 0;
  const precoMinimo = custo / (1 - taxa - margemMin);
  const descontoMaximo = precoCheio ? Math.max(0, 1 - precoMinimo / precoCheio) : 0;
  const custoNegocio = custo - maoObra;
  const pisoNegocio = custoNegocio / (1 - taxa);
  const pisoSalario = custo / (1 - taxa);
  const ganhoHora = horas ? (preco * (1 - taxa) - custoNegocio) / horas : 0;
  const veredito = preco >= precoMinimo - 0.005 ? "fechar" : preco >= pisoSalario - 0.005 ? "so_salario"
    : preco >= pisoNegocio - 0.005 ? "parcial" : "recusar";
  return {
    desconto: arred(desconto, 4), preco_sugerido: Math.ceil(arred(precoMinimo, 2)), preco_total: arred(preco, 2),
    preco_pessoa: arred(preco / pessoas, 2), preco_cheio: arred(precoCheio, 2), custo_total: arred(custo, 2), mao_obra: arred(maoObra, 2),
    horas: arred(horas, 2), impostos_taxas: arred(preco * taxa, 2), lucro: arred(lucro, 2), margem: arred(margem, 4),
    lucro_hora: horas ? arred(lucro / horas, 2) : 0, preco_minimo: arred(precoMinimo, 2), desconto_maximo: arred(descontoMaximo, 4),
    margem_minima: margemMin, margem_alvo: alvo, abaixo_margem: margem < margemMin - 1e-9, sessoes,
    custo_negocio: arred(custoNegocio, 2), piso_negocio: arred(pisoNegocio, 2), piso_salario: arred(pisoSalario, 2),
    ganho_hora: arred(ganhoHora, 2), valor_hora: arred(flt(p.mo?.valor_hora), 2), veredito,
  };
}

/** Classe de cor da margem: verde / amarelo (até 5 pontos abaixo) / vermelho / prejuizo (< 0). */
export function corMargem(margem: number | null | undefined, minima = 0.15): string {
  if (margem === null || margem === undefined) return "neutro";
  if (margem < 0) return "prejuizo";
  if (margem < minima - 0.05 - 1e-9) return "vermelho";
  if (margem < minima - 1e-9) return "amarelo";
  return "verde";
}
