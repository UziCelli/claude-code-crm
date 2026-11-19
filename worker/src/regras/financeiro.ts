/**
 * Financeiro PF + PJ (port de app/financeiro.py). Datas ISO (AAAA-MM-DD), competência AAAA-MM.
 * Até a fase do Financeiro: o que o motor de preços usa (DAS, custo pessoal, custos fixos) e o protótipo do teste de CPU.
 */
import type { Banco } from "../banco/banco.ts";
import type { Comando, Linha } from "../banco/tipos.ts";
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
export function coberturaAdiantada(b: Banco, mes: string): Promise<Map<number, { de: string; ate: string }>> {
  return b.memo(`coberturaAdiantada|${mes}`, () => calcularCobertura(b, mes));
}

async function calcularCobertura(b: Banco, mes: string): Promise<Map<number, { de: string; ate: string }>> {
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
const centavosPy = (v: number) => arred(v * 100, 0);

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
      if (x.escopo !== y.escopo || x.tipo !== y.tipo || centavosPy(x.valor) !== centavosPy(y.valor)) break;
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

// ---------- Mensalidades, renovação, cobrança e crédito dos alunos ----------
export const AVULSOS = ["Pacote de Aulas", "Avaliação Física"]; // venda que não se repete sozinha todo mês
export const CONFIRMA = 15; // Renovação marcada até 15 dias depois de renovar só confirma a renovação

/** A data mais n meses, sempre no mesmo dia (dia 31 vira o último dia nos meses curtos). */
export function proximaRenovacao(data: string, n = 1): string {
  return vencimento(Number(data.slice(8, 10)), somarMeses(data.slice(0, 7), n));
}

/** {cliente_id: 'AAAA-MM'}: até que mês um pagamento de 2+ meses (este mês ou o seguinte) cobre o aluno. */
export async function pagoAdiantadoAte(b: Banco, hoje: string): Promise<Map<number, string>> {
  const out = new Map<number, string>();
  const meses = [hoje.slice(0, 7), somarMeses(hoje.slice(0, 7), 1)];
  for (const cob of await Promise.all(meses.map((m) => coberturaAdiantada(b, m))))
    for (const [cid, c] of cob) out.set(cid, (out.get(cid) ?? "") > c.ate ? out.get(cid)! : c.ate);
  return out;
}

/** Meses 'AAAA-MM' em que o aluno de Pacote ou Avaliação deve; null = não é venda avulsa (ou sem datas). */
export function mesesDaVenda(c: Linha, renovacao: Renovacao | null | undefined): Set<string> | null {
  if (!AVULSOS.includes((c.tipo_servico ?? "").trim())) return null;
  const datas = [c.data_inicio, renovacao?.vence || c.data_renovacao];
  const out = new Set(datas.filter((d) => ISO_DATA.test(String(d ?? "").trim().slice(0, 10))).map((d) => String(d).trim().slice(0, 7)));
  return out.size ? out : null;
}

export interface Credito { id: number; mes: string; valor: number }

/** Créditos ainda não descontados: {cliente_id: [{id, mes, valor}]}, o mais antigo primeiro. */
export function creditos(b: Banco, clienteId: number | null = null): Promise<Map<number, Credito[]>> {
  return b.memo(`creditos|${clienteId ?? ""}`, () => calcularCreditos(b, clienteId));
}

async function calcularCreditos(b: Banco, clienteId: number | null): Promise<Map<number, Credito[]>> {
  const [filtro, args] = clienteId ? ["AND cliente_id=?", [clienteId]] : ["", []];
  const out = new Map<number, Credito[]>();
  for (const r of await b.query(`SELECT id, cliente_id, data, valor FROM cliente_eventos WHERE tipo='credito' AND excluido_em IS NULL
      AND usado_em IS NULL ${filtro} ORDER BY data, id`, args)) {
    if (!out.has(r.cliente_id)) out.set(r.cliente_id, []);
    out.get(r.cliente_id)!.push({ id: r.id, mes: String(r.data).slice(0, 7), valor: arred(flt(r.valor), 2) });
  }
  return out;
}

/** [total, ids] dos créditos que cabem no próximo pagamento: do mais antigo, sem passar da mensalidade. */
export function creditoAplicavel(lista: Credito[], valorMensal: unknown): [number, number[]] {
  let total = 0;
  const ids: number[] = [];
  for (const c of lista) {
    if (c.valor > 0 && total + c.valor <= flt(valorMensal) + 0.005) {
      total = arred(total + c.valor, 2);
      ids.push(c.id);
    }
  }
  return [total, ids];
}

export interface Mensalidade { id: number; nome: string; previsto: number; recebido: number; situacao: string; credito: number;
  abertos: Linha[]; aberto: number; quitado: boolean; coberto_ate: string | null; pago_em_mes: string | null; falta: number; entra: number }

/** Alunos ativos no mês: previsto, recebido, situação (recebido, em aberto, pago adiantado, pulou o mês), crédito e o que falta. */
export function mensalidades(b: Banco, mes: string, ren?: Map<number, Renovacao> | null): Promise<Mensalidade[]> {
  return b.memo(`mensalidades|${mes}`, () => calcularMensalidades(b, mes, ren));
}

async function calcularMensalidades(b: Banco, mes: string, ren?: Map<number, Renovacao> | null): Promise<Mensalidade[]> {
  const [abertosRows, puladosRows, livres, descRows, adiantados, alunos] = await Promise.all([
    b.query(`SELECT id, cliente_id, data, valor, descricao, categoria, conta FROM lancamentos WHERE escopo='PJ' AND tipo='entrada'
      AND excluido_em IS NULL AND pago_em IS NULL AND cliente_id IS NOT NULL AND substr(data,1,7)=? ORDER BY data, id`, [mes]),
    b.query(`SELECT DISTINCT cliente_id FROM cliente_eventos WHERE tipo='pausa' AND excluido_em IS NULL AND substr(data,1,7)=?`, [mes]),
    creditos(b),
    b.query(`SELECT e.cliente_id, e.valor FROM cliente_eventos e JOIN lancamentos l ON l.id = e.usado_lancamento_id
      WHERE e.tipo='credito' AND e.excluido_em IS NULL AND substr(l.data,1,7)=?`, [mes]),
    coberturaAdiantada(b, mes),
    b.query(`SELECT c.id, c.nome, c.data_inicio, c.tipo_servico, c.data_renovacao, COALESCE(c.valor, 0) AS previsto,
      (SELECT COALESCE(SUM(l.valor), 0) FROM lancamentos l WHERE l.cliente_id = c.id AND l.escopo='PJ' AND l.tipo='entrada'
       AND l.excluido_em IS NULL AND l.pago_em IS NOT NULL AND substr(l.data,1,7)=?) AS recebido
      FROM clientes c WHERE c.excluido_em IS NULL AND c.status='ativo' ORDER BY c.nome`, [mes]),
  ]);
  const abertos = new Map<number, Linha[]>();
  for (const r of abertosRows) {
    if (!abertos.has(r.cliente_id)) abertos.set(r.cliente_id, []);
    abertos.get(r.cliente_id)!.push({ ...r });
  }
  const pulados = new Set(puladosRows.map((r) => r.cliente_id as number));
  const descontados = new Map<number, number>();
  for (const r of descRows) descontados.set(r.cliente_id, (descontados.get(r.cliente_id) ?? 0) + r.valor);
  const itens: Mensalidade[] = [];
  for (const c of alunos) {
    const ini = String(c.data_inicio ?? "").trim().slice(0, 10);
    if (ISO_DATA.test(ini) && ini.slice(0, 7) > mes) continue; // começa depois do mês: não deve nada nele
    let previsto = arred(c.previsto, 2);
    const recebido = arred(c.recebido, 2);
    const pulou = pulados.has(c.id);
    let foraDaVenda = false;
    if (recebido <= 0 && !pulou && !adiantados.has(c.id) && AVULSOS.includes((c.tipo_servico ?? "").trim())) {
      if (!ren) ren = await renovacoes(b);
      const venda = mesesDaVenda(c, ren.get(c.id));
      foraDaVenda = venda !== null && !venda.has(mes);
    }
    if (foraDaVenda) previsto = 0;
    if (previsto <= 0 && recebido <= 0 && !(foraDaVenda && abertos.has(c.id))) continue;
    const credito = arred(Math.min(creditoAplicavel((livres.get(c.id) ?? []).filter((x) => x.mes < mes), previsto)[0]
      + (descontados.get(c.id) ?? 0), previsto), 2); // só vale para o mês seguinte ao não usado
    previsto = arred(previsto - credito, 2);
    if (pulou) previsto = 0;
    const adiantado = recebido <= 0 ? adiantados.get(c.id) : undefined;
    const sit = adiantado ? "pago adiantado" : pulou && recebido <= 0 ? "pulou o mês" : recebido > 0 ? "recebido" : "em aberto";
    const quitado = recebido > 0 || Boolean(adiantado);
    const meus = abertos.get(c.id) ?? [];
    const aberto = quitado ? 0 : arred(meus.reduce((a, x) => a + x.valor, 0), 2);
    itens.push({ id: c.id, nome: c.nome, previsto, recebido, situacao: sit, credito, abertos: meus, aberto, quitado,
      coberto_ate: adiantado ? adiantado.ate : null, pago_em_mes: adiantado ? adiantado.de : null,
      falta: quitado ? 0 : arred(Math.max(previsto - recebido - aberto, 0), 2),
      entra: recebido > 0 ? recebido : adiantado ? 0 : previsto });
  }
  return itens;
}

export interface Renovacao { gravada: unknown; efetiva: unknown; vence: unknown; dia: number | null; ciclos: number; falta: number;
  pendente: boolean; motivo: string | null; motivo_data: string | null; tipos: string[] }

/**
 * Renovação efetiva de cada aluno (não grava nada): parte da data do cadastro e anda um mês a cada pagamento, Renovação marcada
 * perto do vencimento ou mês pulado. Regras completas em app/financeiro.py (renovacoes e _renovacao).
 */
export function renovacoes(b: Banco, clienteId: number | null = null): Promise<Map<number, Renovacao>> {
  return b.memo(`renovacoes|${clienteId ?? ""}`, () => calcularRenovacoes(b, clienteId));
}

async function calcularRenovacoes(b: Banco, clienteId: number | null): Promise<Map<number, Renovacao>> {
  const [f1, a1] = clienteId ? ["AND id=?", [clienteId]] : ["", []];
  const f2 = clienteId ? "AND cliente_id=?" : "AND cliente_id IS NOT NULL";
  const [alunos, descRows, pagosRows, evRows] = await Promise.all([
    b.query(`SELECT id, valor, data_renovacao, renovacao_em FROM clientes WHERE excluido_em IS NULL AND data_renovacao IS NOT NULL ${f1}`, a1),
    b.query(`SELECT usado_lancamento_id AS lid, SUM(valor) AS total FROM cliente_eventos WHERE tipo='credito'
      AND excluido_em IS NULL AND usado_lancamento_id IS NOT NULL GROUP BY usado_lancamento_id`),
    b.query(`SELECT id, cliente_id, data, valor, meses, criado_em FROM lancamentos WHERE escopo='PJ' AND tipo='entrada'
      AND pago_em IS NOT NULL AND excluido_em IS NULL ${f2}`, a1),
    b.query(`SELECT cliente_id, tipo, data, valor, criado_em FROM cliente_eventos WHERE excluido_em IS NULL
      AND tipo IN ('pagamento','renovacao','pausa') ${f2}`, a1),
  ]);
  const descontos = new Map(descRows.map((r) => [r.lid as number, r.total as number]));
  const pagos = new Map<number, Linha[]>();
  for (const r of pagosRows) {
    if (!pagos.has(r.cliente_id)) pagos.set(r.cliente_id, []);
    pagos.get(r.cliente_id)!.push({ ...r, valor: (r.valor || 0) + (descontos.get(r.id) || 0) });
  }
  const eventos = new Map<number, Linha[]>();
  for (const r of evRows) {
    if (!eventos.has(r.cliente_id)) eventos.set(r.cliente_id, []);
    eventos.get(r.cliente_id)!.push(r);
  }
  return new Map(alunos.map((c) => [c.id as number, renovacao(c, pagos.get(c.id) ?? [], eventos.get(c.id) ?? [])]));
}

function renovacao(c: Linha, pagos: Linha[], eventos: Linha[]): Renovacao {
  const gravada = String(c.data_renovacao ?? "").trim().slice(0, 10);
  const out: Renovacao = { gravada: c.data_renovacao, efetiva: c.data_renovacao, vence: c.data_renovacao, dia: null, ciclos: 0,
    falta: 0, pendente: false, motivo: null, motivo_data: null, tipos: [] };
  if (numeroDoDia(gravada) === null) return out; // data torta no cadastro: fica como está
  const valor = flt(c.valor);
  const desde = diasAntes(gravada, ANTECEDENCIA);
  const trocada = c.renovacao_em;
  const mesesPagos = new Set(pagos.map((p) => String(p.data).slice(0, 7)));
  type Item = [string, unknown, unknown, unknown, unknown];
  const itens: Item[] = pagos.map((p) => ["pagamento", p.data, p.valor, p.criado_em, p.meses]);
  for (const e of eventos)
    if (!(e.tipo === "pagamento" && mesesPagos.has(String(e.data).slice(0, 7)))) itens.push([e.tipo, e.data, e.valor, e.criado_em, null]);
  const chave = (i: Item): [string, string] => [strPy(i[1]), strPy(i[3] || "")];
  itens.sort((x, y) => {
    const [a1, a2] = chave(x), [b1, b2] = chave(y);
    return a1 < b1 ? -1 : a1 > b1 ? 1 : a2 < b2 ? -1 : a2 > b2 ? 1 : 0;
  });
  let k = 0, pendente = false, ultimo: string | null = null, venceuPendente: string | null = null;
  for (const [tipo, dataBruta, vBruto, criado, explicito] of itens) {
    const data = String(dataBruta || "").trim().slice(0, 10);
    if (!ISO_DATA.test(data) || data < desde || (trocada && strPy(criado || "") <= trocada)) continue;
    if (numeroDoDia(data) === null) continue;
    const vence = proximaRenovacao(gravada, k);
    const perto = data >= diasAntes(vence, ANTECEDENCIA);
    let anda = 0;
    if (tipo === "pagamento") {
      const meses = mesesDoPagamento(flt(vBruto), valor, explicito as number | null);
      if (pendente) {
        pendente = false;
        anda = Math.max(meses - 1, 0);
      } else if (meses) anda = meses;
      else if (perto) anda = 1;
    } else if (tipo === "renovacao") {
      const confirma = ultimo !== null && data < vence && numeroDoDia(data)! - numeroDoDia(ultimo)! <= CONFIRMA;
      if (perto && !confirma) {
        if (valor > 0 && !pendente) venceuPendente = vence;
        anda = 1;
        pendente = pendente || valor > 0;
      }
    } else if (perto) {
      anda = 1;
      pendente = false;
    }
    if (anda) {
      k += anda;
      ultimo = data;
      for (let i = 0; i < anda; i++) out.tipos.push(tipo);
      out.motivo = tipo;
      out.motivo_data = data;
    }
  }
  const efetiva = k ? proximaRenovacao(gravada, k) : gravada;
  Object.assign(out, { efetiva, ciclos: k, pendente, falta: pendente ? valor : 0,
    vence: pendente && venceuPendente ? venceuPendente : efetiva, dia: Number(gravada.slice(8, 10)) });
  return out;
}

/** str() do Python para comparar textos como o sorted() de lá. */
function strPy(v: unknown): string {
  if (v === null || v === undefined) return "None";
  if (typeof v === "number" && Number.isInteger(v) && v !== 0 && !String(v).includes(".")) return String(v);
  return String(v);
}

/** Arredonda para o centavo, meio para cima (28,595 -> 28,60). */
export function centavos(v: number): number {
  return Math.floor(v * 100 + 0.5 + 1e-9) / 100;
}

export interface Cobranca { meses: number; dias: number; bruto: number; credito: number; valor: number; multa: number; juros: number; total: number }

/** Cobrança de quem está vencido: cada mês vencido com multa (uma vez) e juros proporcionais; o crédito sai antes da multa e dos juros. */
export function cobranca(valorBruto: unknown, vencida: string, hoje: string, par: Record<string, unknown>, creditoBruto: unknown = 0,
  dia: number | null = null): Cobranca | null {
  const valor = flt(valorBruto);
  if (numeroDoDia(String(vencida)) === null) return null;
  if (valor <= 0 || vencida >= hoje) return null;
  const multaPct = flt(par.multa), jurosMes = flt(par.juros_ao_mes);
  const h = numeroDoDia(hoje)!;
  const resto = Math.min(Math.max(flt(creditoBruto), 0), valor);
  const descontado = resto;
  let meses = 0, principal = 0, multa = 0, juros = 0, data = vencida;
  while (data < hoje && meses < 24) {
    const dias = h - numeroDoDia(data)!;
    const saldo = meses === 0 ? valor - resto : valor;
    principal += saldo;
    multa += saldo * multaPct;
    juros += (saldo * jurosMes * dias) / 30;
    meses += 1;
    data = dia ? vencimento(dia, somarMeses(vencida.slice(0, 7), meses)) : proximaRenovacao(vencida, meses);
  }
  if (principal <= 0.005) return null;
  principal = centavos(principal);
  multa = centavos(multa);
  juros = centavos(juros);
  return { meses, dias: h - numeroDoDia(vencida)!, bruto: arred(valor * meses, 2), credito: arred(descontado, 2), valor: principal,
    multa, juros, total: arred(principal + multa + juros, 2) };
}

/** Desconta o crédito do aluno (pagamento da mensalidade ou mês pulado coberto): [valor descontado, comandos de gravação]. */
export async function usarCredito(b: Banco, lancamentoId: number | null, clienteId: number | null, hoje: string): Promise<[number, Comando[]]> {
  let pago = 0;
  if (lancamentoId) {
    const p = await b.um(`SELECT cliente_id, valor, categoria FROM lancamentos WHERE id=? AND escopo='PJ' AND tipo='entrada' AND pago_em IS NOT NULL
      AND excluido_em IS NULL`, [lancamentoId]);
    if (!p || !p.cliente_id || p.categoria === EMPRESTIMO) return [0, []];
    clienteId = p.cliente_id;
    pago = flt(p.valor);
  }
  if (!clienteId) return [0, []];
  const [c, livres] = await Promise.all([b.um("SELECT valor FROM clientes WHERE id=?", [clienteId]), creditos(b, clienteId)]);
  const mensal = c ? flt(c.valor) : 0;
  const [total, ids] = creditoAplicavel(livres.get(clienteId) ?? [], mensal);
  if (!ids.length || (lancamentoId && pago < CHEIO * (mensal - total)) || (!lancamentoId && total < mensal - 0.005)) return [0, []];
  return [total, ids.map((i) => ({ sql: "UPDATE cliente_eventos SET usado_em=?, usado_lancamento_id=? WHERE id=? AND usado_em IS NULL", params: [hoje, lancamentoId, i] }))];
}

export interface Diferenca { id: number; valor: number; pago: number; pago_em: string }

/** Diferenças de multa e juros ainda em aberto: {cliente_id: [{id, valor, pago, pago_em}]}. */
export async function diferencas(b: Banco, clienteId: number | null = null): Promise<Map<number, Diferenca[]>> {
  const [filtro, args] = clienteId ? ["AND p.cliente_id=?", [MULTA_JUROS, clienteId]] : ["", [MULTA_JUROS]];
  const out = new Map<number, Diferenca[]>();
  for (const r of await b.query(`SELECT m.id, m.valor, p.cliente_id, p.valor AS pago, p.pago_em FROM lancamentos m
      JOIN lancamentos p ON m.origem = 'MULTA:' || p.id
      WHERE m.categoria=? AND m.pago_em IS NULL AND m.excluido_em IS NULL AND p.excluido_em IS NULL
      AND p.cliente_id IS NOT NULL ${filtro} ORDER BY m.data, m.id`, args)) {
    if (!out.has(r.cliente_id)) out.set(r.cliente_id, []);
    out.get(r.cliente_id)!.push({ id: r.id, valor: arred(r.valor, 2), pago: arred(r.pago, 2), pago_em: String(r.pago_em ?? "").slice(0, 10) });
  }
  return out;
}

/** Aluno que o texto do lançamento cita (nome completo, ou primeiro nome único); na dúvida, nenhum. */
export function sugerirAluno(texto: string | null | undefined, alunos: { id: number; nome: string }[]): number | null {
  const pal = new Set(palavras(texto));
  const completos: number[] = [], primeiros: number[] = [];
  for (const a of alunos) {
    const nome = palavras(a.nome);
    if (nome.length && nome.every((x) => pal.has(x))) completos.push(a.id);
    else if (nome.length && nome[0].length >= 3 && pal.has(nome[0])) primeiros.push(a.id);
  }
  if (completos.length === 1) return completos[0];
  return !completos.length && primeiros.length === 1 ? primeiros[0] : null;
}
