/**
 * Financeiro PF + PJ (port de app/financeiro.py). Datas ISO (AAAA-MM-DD), competência AAAA-MM.
 * Até a fase do Financeiro: o que o motor de preços usa (DAS, custo pessoal, custos fixos) e o protótipo do teste de CPU.
 */
import type { Banco } from "../banco/banco.ts";
import type { Linha } from "../banco/tipos.ts";
import { arred } from "../arred.ts";
import { ehCia } from "./contas_auto.ts";
import { divPy, modPy, numeroDoDia, somarDias, ultimoDiaDoMes, utilAnterior, zeros } from "./datas.ts";
import { parametros } from "./parametros.ts";
import { escaparRegex, flt, regexPalavra, semAcento, semAcentoLow } from "./texto.ts";

export const ISO_DATA = /^\d{4}-\d{2}-\d{2}$/;
export const RETIRADA = "Retirada";
export const EMPRESTIMO = "Empréstimo";
export const DEVOLUCAO = "Empréstimo (devolução)";
export const ANTECEDENCIA = 7;
export const CHEIO = 0.9;
export const JANELA_REPETIDO = 3;
export const MULTA_JUROS = "Multa e juros";

/** Vencimento no mês 'AAAA-MM': o dia pedido, ou o último dia do mês se ele não existir. */
export function vencimento(dia: number, mes: string): string {
  const ano = Number(mes.slice(0, 4)), m = Number(mes.slice(5, 7));
  return `${mes.slice(0, 4)}-${mes.slice(5, 7)}-${String(Math.min(dia, ultimoDiaDoMes(ano, m))).padStart(2, "0")}`;
}

/** 'AAAA-MM' mais n meses (n pode ser negativo). */
export function somarMeses(mes: string, n: number): string {
  const t = Number(mes.slice(0, 4)) * 12 + Number(mes.slice(5, 7)) - 1 + n;
  return `${zeros(divPy(t, 12), 4)}-${zeros(modPy(t, 12) + 1, 2)}`;
}

export function diasAntes(data: string, dias: number): string {
  return somarDias(data, -dias);
}

/** Quantos meses um pagamento cobre: o `meses` dito no lançamento ou as mensalidades inteiras do valor (90% já é mês inteiro). */
export function mesesDoPagamento(v: number | null, valor: number | null, explicito?: number | null): number {
  if (explicito) return Math.trunc(explicito);
  const val = Number(valor ?? 0);
  return val > 0 ? Math.trunc(Number(v ?? 0) / val + (1 - CHEIO) + 1e-9) : 0;
}

/** Mês que um pagamento começa a cobrir: o do pagamento, ou o seguinte se foi feito até 7 dias antes do vencimento do seguinte. */
export function mesQuePaga(data: string, dia: number | null | undefined): string {
  const mes = data.slice(0, 7);
  if (!dia || !ISO_DATA.test(data)) return mes;
  const seguinte = somarMeses(mes, 1);
  return data >= diasAntes(vencimento(dia, seguinte), ANTECEDENCIA) ? seguinte : mes;
}

/** {cliente_id: {de, ate}}: alunos cujo pagamento de um mês anterior (cobre 2+ meses) vai até `mes` ou além. */
export async function coberturaAdiantada(b: Banco, mes: string): Promise<Map<number, { de: string; ate: string }>> {
  const [clientes, pagos] = await Promise.all([
    b.query("SELECT id, COALESCE(valor, 0) AS valor, data_renovacao FROM clientes WHERE excluido_em IS NULL AND status='ativo'"),
    b.query(`SELECT cliente_id, data, valor, meses FROM lancamentos WHERE escopo='PJ' AND tipo='entrada' AND pago_em IS NOT NULL
             AND excluido_em IS NULL AND cliente_id IS NOT NULL AND substr(data,1,7) < ? AND substr(data,1,7) >= ?
             ORDER BY data, id`, [mes, somarMeses(mes, -24)]),
  ]);
  const valores = new Map<number, number>(), dias = new Map<number, number>();
  for (const r of clientes) {
    valores.set(r.id, r.valor);
    const d = String(r.data_renovacao ?? "").trim().slice(0, 10);
    if (ISO_DATA.test(d)) dias.set(r.id, Number(d.slice(8, 10)));
  }
  const out = new Map<number, { de: string; ate: string }>();
  for (const r of pagos) {
    if (!valores.has(r.cliente_id)) continue;
    const n = mesesDoPagamento(r.valor, valores.get(r.cliente_id)!, r.meses);
    const de = mesQuePaga(String(r.data).slice(0, 10), dias.get(r.cliente_id));
    const ate = n >= 2 ? somarMeses(de, n - 1) : null;
    if (ate && ate >= mes && ate >= (out.get(r.cliente_id)?.ate ?? "")) out.set(r.cliente_id, { de, ate });
  }
  return out;
}

/** Palavras sem acento e em minúsculas ('Giuliana Souza' -> ['giuliana', 'souza']). */
export function palavras(texto: string | null | undefined): string[] {
  return semAcento(texto ?? "").toLowerCase().match(/[a-z0-9]+/g) ?? [];
}

/** Dias entre duas datas ISO; data inválida nunca é "perto" (a tela não pode quebrar por causa de uma linha ruim). */
function diasEntreSeguro(a: string, b: string): number {
  const x = numeroDoDia(a), y = numeroDoDia(b);
  return x === null || y === null ? 10_000 : Math.abs(y - x);
}

const vazio = (v: unknown) => v === null || v === undefined || v === "";
const iguais = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);
const diferentes = (a: unknown, b: unknown) => !vazio(a) && !vazio(b) && a !== b;

function mesmaDescricao(a: Linha, b: Linha): boolean {
  const pa = palavras(a.descricao), pb = palavras(b.descricao);
  return pa.length > 0 && iguais(pa, pb);
}

function podeSerOMesmo(x: Linha, y: Linha): boolean {
  if (["parcela_num", "cliente_id", "conta", "recorrencia_id"].some((k) => diferentes(x[k], y[k]))) return false;
  if (x.recorrencia_id && x.recorrencia_id === y.recorrencia_id && x.competencia !== y.competencia) return false;
  if ((x.sem_recorrencia && y.recorrencia_id) || (y.sem_recorrencia && x.recorrencia_id)) return false;
  const px = palavras(x.contraparte).join(" "), py = palavras(y.contraparte).join(" ");
  return !diferentes(px || null, py || null);
}

/** round(x * 100) do Python (inteiro, empate para o par). */
const centavos = (v: number) => arred(v * 100, 0);

/** Compara tuplas como o Python. */
function cmp(a: (number | string)[], b: (number | string)[]): number {
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  return 0;
}

export interface GrupoRepetido { ids: number[]; manter: number; certeza: string; valor: number; escopo: string; tipo: string; itens: Linha[] }

/**
 * Grupos de lançamentos que parecem o mesmo lançamento feito duas vezes. `jaAvisadas`: ids das saídas que já aparecem
 * em saidas_parecidas (no protótipo vêm de fora; na fase do Financeiro, de saidasParecidas()).
 */
export async function duplicados(b: Banco, jaAvisadas: Set<number>): Promise<GrupoRepetido[]> {
  const [okRows, linhas] = await Promise.all([
    b.query("SELECT a, b FROM duplicados_ok"),
    b.query(`SELECT l.*, COALESCE(l.pago_em, l.data) AS quando, c.nome AS aluno FROM lancamentos l
             LEFT JOIN clientes c ON c.id = l.cliente_id WHERE l.excluido_em IS NULL AND l.categoria != ?
             ORDER BY l.escopo, l.tipo, ROUND(l.valor * 100), quando, l.id`, [RETIRADA]),
  ]);
  const ok = new Set(okRows.map((r) => `${r.a}|${r.b}`));
  const pai = new Map<number, number>(linhas.map((l) => [l.id, l.id]));
  const raiz = (i: number): number => {
    while (pai.get(i) !== i) {
      pai.set(i, pai.get(pai.get(i)!)!);
      i = pai.get(i)!;
    }
    return i;
  };
  for (let k = 0; k < linhas.length; k++) {
    const x = linhas[k];
    for (let j = k + 1; j < linhas.length; j++) {
      const y = linhas[j];
      if (x.escopo !== y.escopo || x.tipo !== y.tipo || centavos(x.valor) !== centavos(y.valor)) break;
      if (diasEntreSeguro(x.quando, y.quando) > JANELA_REPETIDO) break;
      if (ok.has(`${x.id}|${y.id}`) || jaAvisadas.has(x.id) || jaAvisadas.has(y.id) || !podeSerOMesmo(x, y)) continue;
      pai.set(raiz(y.id), raiz(x.id));
    }
  }
  const grupos = new Map<number, Linha[]>();
  for (const l of linhas) {
    const r = raiz(l.id);
    if (!grupos.has(r)) grupos.set(r, []);
    grupos.get(r)!.push(l);
  }
  const peso = (l: Linha): number[] => [
    ["recorrencia_id", "cliente_id", "pago_em"].filter((k) => l[k] !== null && l[k] !== undefined).length,
    ["descricao", "contraparte", "conta", "forma", "cliente_id", "observacao"].filter((k) => !vazio(l[k])).length,
    -l.id,
  ];
  let out: GrupoRepetido[] = [];
  for (const g of grupos.values()) {
    if (g.length < 2) continue;
    const manter = g.reduce((m, l) => (cmp(peso(l), peso(m)) > 0 ? l : m)); // max(): o primeiro maior
    const resto = g.filter((l) => l !== manter).sort((p, q) => cmp([p.quando, p.id], [q.quando, q.id]));
    const quase = resto.every((l) => l.quando === manter.quando && mesmaDescricao(l, manter));
    out.push({ ids: [manter, ...resto].map((l) => l.id), manter: manter.id, certeza: quase ? "quase certo" : "talvez",
      valor: manter.valor, escopo: manter.escopo, tipo: manter.tipo, itens: [manter, ...resto].map((l) => ({ ...l, manter: l === manter })) });
  }
  // sort estável do Python: mais recentes primeiro, depois os "quase certos" antes dos "talvez"
  out = out.map((g, i) => ({ g, i })).sort((p, q) => (q.g.itens[0].quando > p.g.itens[0].quando ? 1 : q.g.itens[0].quando < p.g.itens[0].quando ? -1 : p.i - q.i)).map((x) => x.g);
  out = out.map((g, i) => ({ g, i })).sort((p, q) => Number(p.g.certeza !== "quase certo") - Number(q.g.certeza !== "quase certo") || p.i - q.i).map((x) => x.g);
  return out;
}

// ---------- DAS (Simples Nacional, Anexo III) ----------
/** (RBT12 até, alíquota nominal, parcela a deduzir). Acima da última faixa vale a última. */
export const SIMPLES_ANEXO_III: [number, number, number][] = [[180_000, 0.06, 0], [360_000, 0.112, 9_360], [720_000, 0.135, 17_640],
  [1_800_000, 0.16, 35_640], [3_600_000, 0.21, 125_640], [4_800_000, 0.33, 648_000]];

const RECEITA_PJ = "escopo='PJ' AND tipo='entrada' AND excluido_em IS NULL AND pago_em IS NOT NULL AND categoria != ?";

/** Vencimento no dia pedido do mês, antecipado para a sexta se cair no fim de semana. */
export function vencimentoUtil(dia: number, mes: string): string {
  return utilAnterior(vencimento(dia, mes));
}

/** Entradas PJ recebidas no mês (por pago_em): a base do DAS. Empréstimo não é receita. */
export async function receitaPj(b: Banco, mes: string): Promise<number> {
  return (await b.valor<number>(`SELECT COALESCE(SUM(valor), 0) AS total FROM lancamentos WHERE ${RECEITA_PJ} AND substr(pago_em,1,7)=?`,
    [EMPRESTIMO, mes])) ?? 0;
}

/** [RBT12, como foi achado, meses usados] da competência: a receita PJ dos 12 meses anteriores (ou a média, no começo). */
export async function rbt12(b: Banco, mes: string): Promise<[number, string, number]> {
  const primeiro = await b.valor<string | null>(`SELECT MIN(substr(pago_em,1,7)) AS primeiro FROM lancamentos WHERE ${RECEITA_PJ}`, [EMPRESTIMO]);
  if (primeiro === null || primeiro === undefined || primeiro > mes) return [0, "sem receita", 0];
  if (primeiro === mes) return [(await receitaPj(b, mes)) * 12, "primeiro", 0];
  const de = primeiro > somarMeses(mes, -12) ? primeiro : somarMeses(mes, -12);
  const soma = (await b.valor<number>(`SELECT COALESCE(SUM(valor), 0) AS total FROM lancamentos WHERE ${RECEITA_PJ} AND substr(pago_em,1,7) BETWEEN ? AND ?`,
    [EMPRESTIMO, de, somarMeses(mes, -1)])) ?? 0;
  const n = (Number(mes.slice(0, 4)) - Number(de.slice(0, 4))) * 12 + Number(mes.slice(5, 7)) - Number(de.slice(5, 7));
  return n >= 12 ? [soma, "12 meses", n] : [(soma / n) * 12, "media", n];
}

export interface Das { mes: string; receita: number; rbt12: number; faixa: number; nominal: number; deducao: number; efetiva: number;
  valor: number; vencimento: string; base: string; meses_base: number }

/** DAS da competência (pago no mês seguinte) sobre a receita PJ recebida no mês. Sem receita ainda: faixa 1 (6%). */
export async function dasCompetencia(b: Banco, mes: string): Promise<Das> {
  const [receita, [r12, base, n], previsao] = await Promise.all([receitaPj(b, mes), rbt12(b, mes), parametros(b, "previsao")]);
  let faixa = SIMPLES_ANEXO_III.findIndex(([teto]) => r12 <= teto) + 1;
  if (faixa === 0) faixa = SIMPLES_ANEXO_III.length;
  const [, nominal, deducao] = SIMPLES_ANEXO_III[faixa - 1];
  const efetiva = r12 > 0 ? (r12 * nominal - deducao) / r12 : nominal;
  const dia = Math.trunc(flt(previsao.dia_das) || 20);
  return { mes, receita: arred(receita, 2), rbt12: arred(r12, 2), faixa, nominal, deducao, efetiva, valor: arred(receita * efetiva, 2),
    vencimento: vencimentoUtil(dia, somarMeses(mes, 1)), base, meses_base: n };
}

/** Alíquota efetiva do DAS do mês de `hoje` (fração: 0,06 = 6%). */
export async function pctDas(b: Banco, hoje: string): Promise<number> {
  return (await dasCompetencia(b, hoje.slice(0, 7))).efetiva;
}

/** 0,06 -> '6'; 0,045 -> '4,5'; 0,0753125 -> '7,53' (f"{round(x * 100, 2):g}"). */
export function textoPct(fracao: number): string {
  return formatoG(arred(fracao * 100, 2)).replace(".", ",");
}

/** f"{x:g}" do Python para os números das telas (6 algarismos significativos, sem zeros à direita). */
export function formatoG(x: number): string {
  if (x === 0) return Object.is(x, -0) ? "-0" : "0";
  const exp = Math.floor(Math.log10(Math.abs(x)));
  if (exp < -4 || exp >= 6) {
    const [m, e] = x.toExponential(5).split("e");
    const mant = m.includes(".") ? m.replace(/0+$/, "").replace(/\.$/, "") : m;
    const n = Number(e);
    return `${mant}e${n < 0 ? "-" : "+"}${String(Math.abs(n)).padStart(2, "0")}`;
  }
  const t = x.toPrecision(6);
  return t.includes(".") ? t.replace(/0+$/, "").replace(/\.$/, "") : t;
}

/** Saída que é o DAS: categoria 'DAS', 'DAS' na descrição, 'Simples Nacional', ou imposto sem descrição. */
export function ehDas(descricao: string | null | undefined, categoria: string | null | undefined): boolean {
  let d = (descricao ?? "").trim();
  if (d === (categoria ?? "").trim()) d = "";
  const pal = palavras(d);
  const cat = palavras(categoria);
  if ((cat.length === 1 && cat[0] === "das") || regexPalavra("DAS").test(d) || pal[0] === "das" || pal.join(" ").includes("simples nacional"))
    return true;
  return !d && (categoria ?? "").toLowerCase().includes("imposto");
}

// ---------- custo pessoal e custos fixos (motor de preços) ----------
/** [R$ por mês, nº de meses]: média das saídas pagas da PF nos 3 meses antes de `mes` (só meses com saída). */
export async function custoPessoalMedio(b: Banco, mes: string): Promise<[number, number]> {
  const meses = [3, 2, 1].map((k) => somarMeses(mes, -k));
  const rows = await b.query<{ mes: string; total: number | null }>(
    `SELECT substr(data,1,7) AS mes, SUM(valor) AS total FROM lancamentos WHERE escopo='PF' AND tipo='saida' AND excluido_em IS NULL
     AND pago_em IS NOT NULL AND substr(data,1,7) BETWEEN ? AND ? GROUP BY substr(data,1,7)`, [meses[0], meses[2]]);
  const totais = rows.map((r) => r.total).filter((t): t is number => (t ?? 0) > 0);
  return totais.length ? [totais.reduce((a, t) => a + t, 0) / totais.length, totais.length] : [0, 0];
}

export interface CustosFixos { total: number; itens: { descricao: string; valor: number }[] }

/** Custos fixos que o preço divide por hora: recorrências fixas da PJ do mês, sem Retirada, DAS, CIA e locais do motor. */
export async function custosFixosRateio(b: Banco, mes: string, locais: string[] = []): Promise<CustosFixos> {
  const nomes = locais.map(semAcentoLow).filter(Boolean);
  const rows = await b.query<{ descricao: string; categoria: string; valor: number }>(
    `SELECT descricao, categoria, valor FROM recorrencias WHERE excluido_em IS NULL AND escopo='PJ' AND fixo=1
     AND categoria != ? AND inicio <= ? AND (fim IS NULL OR fim >= ?) ORDER BY valor DESC, descricao`, [RETIRADA, mes, mes]);
  const itens: CustosFixos["itens"] = [];
  for (const r of rows) {
    const desc = semAcentoLow(r.descricao);
    // palavra inteira: um local "Box" não pode tirar a conta do "Dropbox"
    if (ehDas(r.descricao, r.categoria) || ehCia(r.descricao) || nomes.some((n) => new RegExp(`\\b${escaparRegex(n)}\\b`).test(desc))) continue;
    itens.push({ descricao: r.descricao, valor: arred(r.valor, 2) });
  }
  return { total: arred(itens.reduce((a, i) => a + i.valor, 0), 2), itens };
}
