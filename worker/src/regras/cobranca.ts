/**
 * Cobrança do dia e cartão (port de main.py: texto_cobranca, estagio_cobranca, cobranca_atual, cartao_cobranca, rotulo_cobranca,
 * diferenca_cartao, pendencia_diferenca). O estágio vem dos dias até o vencimento (negativo = atraso).
 */
import { dataBr, moeda, preencher } from "../formato.ts";
import type { Valor } from "../banco/tipos.ts";
import { arred } from "../arred.ts";
import { numeroDoDia, dataIso } from "./datas.ts";
import type { Cobranca, Diferenca } from "./financeiro.ts";
import type { DadosMsg } from "./mensagens.ts";
import { brCode } from "./pix.ts";
import { flt } from "./texto.ts";

export const ESTAGIOS: Record<string, [string, string]> = {
  lembrete: ["Lembrete", "cobranca_lembrete"], hoje: ["Vence hoje", "cobranca_hoje"], esquecimento: ["Esquecimento", "cobranca"],
  moderada: ["Moderada", "cobranca_moderada"], critica: ["Crítica", "cobranca_critica"],
};

/** Valores da cobrança já escritos para a mensagem do WhatsApp. */
export function textoCobranca(cob: Cobranca): Record<string, string | number> {
  return { valor: moeda(cob.valor), dias: cob.dias, multa: moeda(cob.multa), juros: moeda(cob.juros), total: moeda(cob.total) };
}

/** O estágio pelo número de dias até o vencimento; null quando ainda falta mais de 2 dias. */
export function estagioCobranca(d: number): string | null {
  if (d > 2) return null;
  if (d >= 1) return "lembrete";
  if (d === 0) return "hoje";
  return d > -10 ? "esquecimento" : d > -30 ? "moderada" : "critica";
}

export interface CobrancaAtual { estagio: string; nome: string; modelo: string; faltam: number; dias: number; vencimento: string; valor: number;
  rotulo_valor: string; cob: Cobranca | null; texto: string; credito: number; mensalidade: number; valido_ate: string; codigo: string; dados: DadosMsg }

/** A cobrança do dia (estágio, modelo, valor, texto do cartão e código Pix) ou null se não há o que cobrar. */
export function cobrancaAtual(c: { status: string; valor: unknown; nome: string }, ctx: { vence?: string | null; efetiva?: string | null;
  cob?: Cobranca | null; credito?: number | null }, hoje: string, modelos: Record<string, Valor>, dados: DadosMsg): CobrancaAtual | null {
  const efetiva = ctx.vence || ctx.efetiva;
  if (c.status !== "ativo" || !dataIso(efetiva)) return null;
  const d = numeroDoDia(efetiva!)! - numeroDoDia(hoje)!;
  const estagio = estagioCobranca(d);
  if (!estagio) return null;
  const cob = ctx.cob ?? null;
  if (d < 0 && !cob) return null;
  const valor = d < 0 ? cob!.total : Math.max(flt(c.valor) - flt(ctx.credito), 0);
  if (valor <= 0) return null;
  const [nome, modelo] = ESTAGIOS[estagio];
  const extra = { ...dados, ...(cob ? textoCobranca(cob) : {}), valor: moeda(valor), total: moeda(valor), faltam: Math.max(d, 0), dias: Math.max(-d, 0) };
  const texto = preencher(String(modelos[modelo] || modelos.cobranca || ""), c.nome, dataBr(efetiva), extra);
  const credito = d < 0 ? cob!.credito : Math.min(flt(ctx.credito), flt(c.valor));
  return { estagio, nome, modelo, faltam: Math.max(d, 0), dias: Math.max(-d, 0), vencimento: efetiva!, valor,
    rotulo_valor: d < 0 ? "Total atualizado" : "Valor", cob, texto, credito, mensalidade: flt(c.valor),
    valido_ate: d >= 0 ? efetiva! : hoje, codigo: brCode(dados.pix, dados.pix_nome, dados.pix_cidade, valor), dados };
}

export interface CartaoBotao { cid: number; codigo: string; acao: string; svg: string }

/** O botão-cartão: o POST que registra e abre o WhatsApp e o SVG que vira a imagem. */
export function cartaoCobranca(cid: number, codigo: string, tipo = "cobranca"): CartaoBotao {
  const modelo = tipo === "cobranca" ? "cobranca" : "cobranca_diferenca";
  return { cid, codigo, acao: `/clientes/${cid}/wa/${modelo}`, svg: `/clientes/${cid}/${tipo}/cartao.svg` };
}

/** [rótulo, sub] do item de cobrança no menu WhatsApp. */
export function rotuloCobranca(ca: CobrancaAtual): [string, string] {
  const v = moeda(ca.valor);
  if (ca.estagio === "lembrete") return [`Lembrete: vence em ${ca.faltam} dia${ca.faltam > 1 ? "s" : ""}`, v];
  if (ca.estagio === "hoje") return [`Vence hoje · ${v}`, ""];
  if (ca.estagio === "critica") return [`Cobrança crítica · ${v}`, `${ca.dias} dias`];
  return [`Cobrar ${v} · ${ca.dias} dia${ca.dias > 1 ? "s" : ""}`, ""];
}

/** O cartão da diferença de multa e juros: texto do modelo, QR do total e uma linha por Pix que veio curto. */
export function diferencaCartao(c: { nome: string }, itens: Diferenca[], dados: DadosMsg, modelos: Record<string, Valor>) {
  const total = arred(itens.reduce((a, i) => a + i.valor, 0), 2);
  const ult = itens[itens.length - 1];
  const texto = preencher(String(modelos.cobranca_diferenca || ""), c.nome, dataBr(ult.pago_em), { ...dados, valor: moeda(total), pago: moeda(ult.pago) });
  const linhas: [string, string, boolean][] = itens.map((i) => [`Pix de ${moeda(i.pago)} em ${dataBr(i.pago_em).slice(0, 5)}: faltou`, moeda(i.valor), false]);
  linhas.push(["Falta pagar", moeda(total), true]);
  return { nome: "Multa e juros", texto, codigo: brCode(dados.pix, dados.pix_nome, dados.pix_cidade, total), dados, linhas, total };
}

/** A diferença de multa e juros pronta para o alerta e a ficha: Cobrar (cartão), Recebi e Dispensar. */
export function pendenciaDiferenca(c: { id: number; nome: string; telefone: unknown }, itens: Diferenca[], dados: DadosMsg) {
  const total = arred(itens.reduce((a, i) => a + i.valor, 0), 2);
  const pagos = itens.map((i) => `Pix de ${moeda(i.pago)} em ${dataBr(i.pago_em).slice(0, 5)}`).join(", ");
  const temTel = /\d/.test(String(c.telefone ?? ""));
  const botao = `Cobrar diferença ${moeda(total)}`;
  const cartao = temTel ? cartaoCobranca(c.id, brCode(dados.pix, dados.pix_nome, dados.pix_cidade, total), "diferenca") : null;
  const acoes: Record<string, unknown>[] = [temTel ? { wa: true, botao, cartao } : { rotulo: "Cadastre o telefone", href: `/clientes/${c.id}#cadastro` }];
  for (const i of itens) {
    const v = moeda(i.valor);
    acoes.push({ rotulo: itens.length > 1 ? `Recebi ${v}` : "Recebi", post: `/financeiro/lancamento/${i.id}/baixa`, classe: "verde",
      confirmar: `Recebeu hoje os ${v} de multa e juros de ${c.nome}?` });
    acoes.push({ rotulo: "Dispensar", post: `/financeiro/lancamento/${i.id}/excluir`,
      confirmar: `Dispensar os ${v} de multa e juros de ${c.nome}? O lançamento vai para a lixeira.` });
  }
  const frase = `faltou ${moeda(total)} de multa e juros (${pagos}, depois do vencimento)`;
  return { texto: `${c.nome}: ${frase}`, frase, total, botao, cartao, acoes };
}
