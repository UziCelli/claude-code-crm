/**
 * Ajudas da lista de Clientes, da ficha e dos Leads (port de main.py): estimativa do aluno, horários em texto, menu e texto do
 * WhatsApp, renovação e cobrança da ficha, leads parados e previsão do funil.
 */
import type { Banco } from "../banco/banco.ts";
import type { Linha, Valor } from "../banco/tipos.ts";
import { dataBr, moeda, preencher } from "../formato.ts";
import { fraseValor } from "./alunos.ts";
import { cobrancaAtual, diferencaCartao, rotuloCobranca, type CobrancaAtual } from "./cobranca.ts";
import { WA_ROTULOS } from "./config.ts";
import { dataIso, isoDoDia, numeroDoDia } from "./datas.ts";
import { cobranca, creditoAplicavel, creditos, diferencas, renovacoes, type Cobranca, type Renovacao } from "./financeiro.ts";
import { dadosMensagem } from "./mensagens.ts";
import { parametros, parametrosEmOrdem } from "./parametros.ts";
import { calcular, type Params } from "./precos.ts";
import { capitalizar } from "../formato.ts";
import { flt } from "./texto.ts";
import { baseDoCliente, fixosAtuais } from "./trabalho.ts";
import { doAluno as vantagemDoAluno } from "./vantagens.ts";

export const DIAS_CURTO: Record<number, string> = { 1: "Seg", 2: "Ter", 3: "Qua", 4: "Qui", 5: "Sex", 6: "Sáb", 7: "Dom" };
/** Filtro `dia` das telas (main.DIAS). */
export const DIAS: Record<number, string> = { 1: "Segunda", 2: "Terça", 3: "Quarta", 4: "Quinta", 5: "Sexta", 6: "Sábado", 7: "Domingo" };
export const ETAPAS: [string, string][] = [["lead", "Lead"], ["conversa", "Conversa"], ["avaliacao", "Avaliação marcada"], ["cliente", "Cliente"], ["perdido", "Perdido"]];
export const WA_ORDEM = ["renovacao", "falta", "boas_vindas", "reativacao", "indicacao", "dupla", "depoimento"];
export const DEPOIMENTO_DIAS = 90;

export function waRotulo(modelo: string): string {
  return WA_ROTULOS[modelo] || capitalizar(modelo.replaceAll("_", " "));
}

/** Id numérico de um campo de texto (vazio ou torto: 0). */
export function idValido(texto: unknown): number {
  const t = String(texto ?? "").trim();
  return /^[0-9]+$/.test(t) && t.length < 10 ? Number(t) : 0;
}

/** Preço, custo e lucro do aluno pelo motor (o valor da ficha entra como preço final). null sem plano ou sem valor. */
export function estimativaCliente(c: Linha, p: Params) {
  const base = baseDoCliente(c);
  if (!(base && c.valor)) return null;
  const pessoas = c.pessoas || 1;
  const forma = c.forma_pagamento in p.taxas ? c.forma_pagamento : "PIX";
  try {
    return calcular(base, p, { pessoas, forma_pagamento: forma, preco_final: c.valor });
  } catch {
    return null;
  }
}

/** {cliente_id: "Seg 13h · Qui 17h"}: os horários fixos da Agenda de cada aluno ativo. */
export async function horariosTexto(b: Banco, ids?: Set<number>): Promise<Map<number, string>> {
  const fixos = (await fixosAtuais(b, ids)).sort((x, y) => x.dia - y.dia || x.hora - y.hora);
  const por = new Map<number, string[]>();
  for (const f of fixos) {
    if (!por.has(f.cliente_id)) por.set(f.cliente_id, []);
    por.get(f.cliente_id)!.push(`${DIAS_CURTO[f.dia]} ${String(f.hora).padStart(2, "0")}h`);
  }
  return new Map([...por].map(([c, v]) => [c, v.join(" · ")]));
}

/** [renovação efetiva, cobrança] do aluno, com o crédito descontado antes da multa e dos juros; quem saiu não recebe cobrança. */
export async function renovacaoECobranca(b: Banco, c: Linha, hoje: string): Promise<[Renovacao | null, Cobranca | null]> {
  const [ren, livres, par] = await Promise.all([renovacoes(b, c.id), creditos(b, c.id), parametros(b, "cobranca")]);
  const r = ren.get(c.id) ?? null;
  if (!r || c.status !== "ativo") return [r, null];
  const credito = creditoAplicavel(livres.get(c.id) ?? [], c.valor)[0];
  return [r, cobranca(c.valor, String(r.vence || r.efetiva), hoje, par, credito, r.dia)];
}

export interface CtxWa { renova: string; efetiva: string; vence: string; cob: Cobranca | null; ultima_aula: string | null; credito: number; valor: string }

/** O que as mensagens de um aluno precisam: renovação, cobrança, última aula, crédito e o {valor} da renovação. */
export async function waContexto(b: Banco, c: Linha, hoje: string, ren?: [Renovacao | null, Cobranca | null]): Promise<CtxWa> {
  const [[renovacao, cob], ult, livres] = await Promise.all([ren ? Promise.resolve(ren) : renovacaoECobranca(b, c, hoje),
    b.valor<string | null>("SELECT MAX(data) AS ultima FROM cliente_eventos WHERE cliente_id=? AND tipo='aula' AND excluido_em IS NULL", [c.id]),
    creditos(b, c.id)]);
  const minhas = livres.get(c.id) ?? [];
  return { renova: String((renovacao ? renovacao.efetiva : c.data_renovacao) || ""), efetiva: renovacao ? String(renovacao.efetiva) : "",
    vence: renovacao ? String(renovacao.vence || renovacao.efetiva) : "", cob, ultima_aula: ult ?? null,
    credito: creditoAplicavel(minhas, c.valor)[0], valor: fraseValor(c.valor, minhas) };
}

export const waDataModelo = (modelo: string, ctx: CtxWa) => (modelo === "falta" ? ctx.ultima_aula : ctx.renova);

export async function cobrancaAtualDe(b: Banco, c: Linha, ctx: CtxWa, hoje: string): Promise<CobrancaAtual | null> {
  const [modelos, dados] = await Promise.all([parametros(b, "msg_whatsapp"), dadosMensagem(b)]);
  return cobrancaAtual(c as never, { efetiva: ctx.efetiva, vence: ctx.vence, cob: ctx.cob, credito: ctx.credito }, hoje, modelos, dados);
}

/** O texto pronto do WhatsApp para o aluno (nunca vem do navegador). [texto, erro]. */
export async function waTexto(b: Banco, c: Linha, modelo: string, hoje: string): Promise<[string | null, string | null]> {
  const modelos = await parametros(b, "msg_whatsapp");
  if (!(modelo in modelos)) return [null, "Mensagem desconhecida."];
  if (modelo === "cobranca_diferenca") {
    const itens = (await diferencas(b, c.id)).get(c.id);
    if (!itens) return [null, "Esse aluno não tem diferença de multa e juros em aberto."];
    const ca = diferencaCartao(c as never, itens, await dadosMensagem(b), modelos);
    return [ca.codigo || ca.texto, null];
  }
  const ctx = await waContexto(b, c, hoje);
  const d = waDataModelo(modelo, ctx);
  if (String(modelos[modelo]).includes("{data}") && !dataIso(d)) return [null, "Falta a data para essa mensagem: complete o cadastro."];
  if (modelo === "cobranca") {
    const ca = await cobrancaAtualDe(b, c, ctx, hoje);
    if (!ca) return [null, "Esse aluno não tem cobrança em aberto."];
    return [ca.codigo || ca.texto, null];
  }
  const [extra, vantagem] = await Promise.all([dadosMensagem(b), vantagemDoAluno(b, c.local)]);
  const e: Record<string, unknown> = { ...extra, vantagem };
  if (modelo === "renovacao") e.valor = ctx.valor;
  return [preencher(String(modelos[modelo]), c.nome, d ? dataBr(d) : "", e), null];
}

export interface ItemWa { modelo: string; rotulo: string; sub: string; destaque: boolean; pedido_em: string | null }

/** Menu WhatsApp da ficha: itens na ordem e se há um pedido de depoimento esperando resposta. */
export async function waMenu(b: Banco, c: Linha, ren: [Renovacao | null, Cobranca | null], eventos: Linha[], hoje: string) {
  const [ctx, modelos] = await Promise.all([waContexto(b, c, hoje, ren), parametros(b, "msg_whatsapp")]);
  const limite = isoDoDia(numeroDoDia(hoje)! - DEPOIMENTO_DIAS);
  const pedido = eventos.find((e) => e.tipo === "mensagem" && e.descricao === "WhatsApp: " + waRotulo("depoimento") && e.data >= limite)?.data ?? null;
  const recebido = Boolean(pedido) && eventos.some((e) => e.tipo === "depoimento" && e.data >= pedido);
  const ca = await cobrancaAtualDe(b, c, ctx, hoje);
  const itens: ItemWa[] = [];
  for (const k of [...(ca ? ["cobranca"] : []), ...WA_ORDEM.filter((k) => k in modelos)]) {
    if (k !== "cobranca" && String(modelos[k]).includes("{data}") && !dataIso(waDataModelo(k, ctx))) continue;
    let rotulo = waRotulo(k), sub = "";
    if (k === "cobranca") [rotulo, sub] = rotuloCobranca(ca!);
    else if (k === "renovacao" && ctx.valor) sub = moeda(Math.max(flt(c.valor) - ctx.credito, 0));
    itens.push({ modelo: k, rotulo, sub, destaque: k === "cobranca", pedido_em: k === "depoimento" ? pedido : null });
  }
  return { itens, depoimento_aberto: Boolean(pedido) && !recebido, cobranca: ca };
}

/** Dias que um lead ficou parado na etapa; null se ainda não atingiu o limite. */
export function diasParado(lead: Linha, hoje: string, limites: Record<string, Valor>): number | null {
  const datas = [lead.data_mudanca_etapa, String(lead.atualizado_em).slice(0, 10)].filter((d) => d);
  if (!datas.length) return null;
  const nums = datas.map((d) => {
    const z = numeroDoDia(d);
    if (z === null) throw new RangeError(`data inválida: ${d}`);
    return z;
  });
  const dias = numeroDoDia(hoje)! - Math.max(...nums);
  const limite = limites[lead.etapa] as number | null | undefined;
  return limite && dias >= limite ? dias : null;
}

/** Receita provável dos leads em aberto: cada lead pesado pela chance da etapa × ticket médio. */
export async function previsaoFunil(b: Banco) {
  const [chance, ticketBruto, etapas] = await Promise.all([parametrosEmOrdem(b, "funil_chance"),
    b.valor<number | null>("SELECT AVG(valor) AS t FROM clientes WHERE status='ativo' AND excluido_em IS NULL AND valor > 0"),
    b.query("SELECT etapa, COUNT(*) AS n FROM leads WHERE excluido_em IS NULL GROUP BY etapa")]);
  const ch = new Map(chance);
  const ticket = ticketBruto || 0;
  const n = etapas.filter((r) => ch.has(r.etapa)).reduce((a, r) => a + r.n, 0);
  return { receita: etapas.filter((r) => ch.has(r.etapa)).reduce((a, r) => a + (ch.get(r.etapa) as number) * r.n, 0) * ticket, leads: n, ticket };
}

export async function motivosPerda(b: Banco): Promise<Linha[]> {
  return b.query(`SELECT COALESCE(NULLIF(LOWER(TRIM(motivo_perda)), ''), 'sem motivo') AS m, COUNT(*) AS n FROM leads
    WHERE etapa='perdido' AND excluido_em IS NULL GROUP BY m ORDER BY n DESC, m`);
}
