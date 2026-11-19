/**
 * Ofertas de upsell (port de app/ofertas.py): proposta com valor de oferta, por quantos meses vale e até quando, e o que cada aluno
 * respondeu (enviada -> aceitou | recusou). Telas, alertas e sugestões leem daqui.
 */
import type { Banco } from "../banco/banco.ts";
import type { Comando, Linha } from "../banco/tipos.ts";
import { arred } from "../arred.ts";
import { dataBr, moeda, preencher, wa } from "../formato.ts";
import { numBr } from "../rotas/util.ts";
import type { Estado } from "./alunos.ts";
import { estado as estadoAlunos } from "./alunos.ts";
import { dataIso, isoDoDia, numeroDoDia } from "./datas.ts";
import { proximaRenovacao } from "./financeiro.ts";
import { espacosSimples, flt } from "./texto.ts";

export const SITUACOES_ELEGIVEIS = ["em_dia", "vence_logo"];
export const MAX_MESES = 36;
export const TAXA_ESTIMADA = 0.3;
export const PADRAO_UPSELL = "Oi, {nome}! Tenho uma proposta: {titulo}. Inclui: {inclui}. De {valor_normal} por {valor_oferta}/mês{duracao}{depois}.{ate} Quer aproveitar? Victor | VFITCOACH";

const limpo = (t: unknown) => espacosSimples(String(t ?? ""));
const semPontuacaoFinal = (s: string) => s.replace(/[.;,: ]+$/, "");

export interface DadosOferta { titulo: string; inclui: string; valor_normal: number; valor_oferta: number; meses_desconto: number | null; valida_ate: string | null }

/** Confere o formulário da oferta: [dados, erro]. Meses vazio = o valor da oferta vale sempre. */
export function validar(titulo: unknown, inclui: unknown, valorNormal: unknown, valorOferta: unknown, meses: unknown, validaAte: unknown): [DadosOferta | null, string | null] {
  const t = limpo(titulo), inc = limpo(inclui);
  if (!t) return [null, "Escreva o título da oferta."];
  if (!inc) return [null, "Diga o que a oferta inclui."];
  let normal: number, oferta: number;
  try {
    normal = numBr(valorNormal);
    oferta = numBr(valorOferta);
  } catch {
    return [null, "Valor inválido: use só números, como 350,00."];
  }
  if (normal <= 0) return [null, "Informe o valor normal (maior que zero)."];
  if (oferta <= 0 || oferta >= normal) return [null, "O valor da oferta precisa ser maior que zero e menor que o valor normal."];
  const mt = String(meses ?? "").trim();
  let n: number | null = null;
  if (mt) {
    if (!/^\d+$/.test(mt) || !(Number(mt) >= 1 && Number(mt) <= MAX_MESES)) return [null, `Meses: use um número de 1 a ${MAX_MESES}, ou deixe vazio para valer sempre.`];
    n = Number(mt);
  }
  let ate: string | null = null;
  if (String(validaAte ?? "").trim()) {
    ate = dataIso(validaAte);
    if (!ate) return [null, "Validade inválida: escolha a data no calendário."];
  }
  return [{ titulo: t, inclui: inc, valor_normal: arred(normal, 2), valor_oferta: arred(oferta, 2), meses_desconto: n, valida_ate: ate }, null];
}

export async function obter(b: Banco, oid: number): Promise<Linha | null> {
  return (await b.um("SELECT * FROM ofertas WHERE id=? AND excluido_em IS NULL", [oid])) ?? null;
}

export async function todas(b: Banco): Promise<Linha[]> {
  return b.query("SELECT * FROM ofertas WHERE excluido_em IS NULL ORDER BY ativa DESC, id DESC");
}

/** Ofertas que podem ser enviadas hoje: ativas, não excluídas e dentro da validade. */
export async function ativas(b: Banco, hoje: string): Promise<Linha[]> {
  return b.query("SELECT * FROM ofertas WHERE excluido_em IS NULL AND ativa=1 AND (valida_ate IS NULL OR valida_ate >= ?) ORDER BY id", [hoje]);
}

export function duracaoTxt(o: Linha): string {
  const n = o.meses_desconto;
  if (!n) return "";
  return n === 1 ? " no primeiro mês" : ` nos primeiros ${n} meses`;
}

/** A mensagem do WhatsApp (modelo 'upsell'). */
export function texto(o: Linha, nome = "", modelo?: string | null): string {
  const n = o.meses_desconto, ate = o.valida_ate;
  const extra = { titulo: semPontuacaoFinal(limpo(o.titulo)), inclui: semPontuacaoFinal(limpo(o.inclui)), valor_normal: moeda(o.valor_normal),
    valor_oferta: moeda(o.valor_oferta), duracao: duracaoTxt(o), depois: n ? ` (depois volta para ${moeda(o.valor_normal)})` : "",
    ate: ate ? ` Válida até ${dataBr(ate)}.` : "" };
  return preencher(modelo || PADRAO_UPSELL, nome, "", extra);
}

export interface SituacaoOferta { oferta: Linha; status: string; data: string | null; ate_desconto: string | null; encerrado_em: string | null }

/** Por oferta ativa: status do aluno (nao_enviada | enviada | aceitou | recusou). */
export async function situacaoAluno(b: Banco, cid: number, hoje: string): Promise<SituacaoOferta[]> {
  const [respostas, lista] = await Promise.all([b.query("SELECT * FROM oferta_respostas WHERE cliente_id=? AND excluido_em IS NULL", [cid]), ativas(b, hoje)]);
  const resp = new Map(respostas.map((r) => [r.oferta_id as number, r]));
  return lista.map((o) => {
    const r = resp.get(o.id);
    return { oferta: o, status: r ? r.status : "nao_enviada", data: r ? r.data : null, ate_desconto: r ? r.ate_desconto : null, encerrado_em: r ? r.encerrado_em : null };
  });
}

function gravar(oid: number, cid: number, status: string, data: string, extra: { ate_desconto?: string | null; valor_antes?: number | null; encerrado_em?: string | null } = {}): Comando {
  return { sql: `INSERT INTO oferta_respostas (oferta_id, cliente_id, status, data, ate_desconto, valor_antes, encerrado_em)
    VALUES (?,?,?,?,?,?,?) ON CONFLICT(oferta_id, cliente_id) DO UPDATE SET status=excluded.status, data=excluded.data,
    ate_desconto=excluded.ate_desconto, valor_antes=excluded.valor_antes, encerrado_em=excluded.encerrado_em, excluido_em=NULL`,
    params: [oid, cid, status, data, extra.ate_desconto ?? null, extra.valor_antes ?? null, extra.encerrado_em ?? null] };
}

async function par(b: Banco, cid: number, oid: number): Promise<[Linha | undefined, Linha | null]> {
  return Promise.all([b.um("SELECT * FROM clientes WHERE id=? AND excluido_em IS NULL", [cid]), obter(b, oid)]);
}

const resposta = (b: Banco, cid: number, oid: number) =>
  b.um("SELECT * FROM oferta_respostas WHERE oferta_id=? AND cliente_id=? AND excluido_em IS NULL", [oid, cid]);

/** Marca como enviada e devolve [link do WhatsApp, erro]. Quem já aceitou não recebe de novo. */
export async function registrarEnvio(b: Banco, cid: number, oid: number, modelo: string | null, hoje: string): Promise<[string | null, string | null]> {
  const [[c, o], r] = await Promise.all([par(b, cid, oid), resposta(b, cid, oid)]);
  if (!c || !o) return [null, "Aluno ou oferta não encontrado."];
  if (!o.ativa) return [null, "Essa oferta está pausada: ative em Campanhas para enviar."];
  if (!/\d/.test(String(c.telefone ?? ""))) return [null, `${c.nome} está sem telefone: complete o cadastro para enviar.`];
  if (r && r.status === "aceitou") return [null, `${c.nome} já aceitou essa oferta.`];
  await b.batch([gravar(oid, cid, "enviada", hoje),
    { sql: "INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'mensagem', ?, ?)", params: [cid, hoje, `Oferta enviada: ${o.titulo}`] }]);
  return [wa(c.telefone, texto(o, c.nome, modelo)), null];
}

/** Dia em que o valor da oferta acaba se for aceita hoje (null = sempre). */
export function prazoDoDesconto(o: Linha, hoje: string): string | null {
  return o.meses_desconto ? proximaRenovacao(hoje, o.meses_desconto) : null;
}

/** Aceitou a oferta; com `atualizar`, a mensalidade passa para o valor da oferta. */
export async function aceitou(b: Banco, cid: number, oid: number, atualizar: boolean, hoje: string): Promise<[string | null, string | null]> {
  const [c, o] = await par(b, cid, oid);
  if (!c || !o) return [null, "Aluno ou oferta não encontrado."];
  const ate = prazoDoDesconto(o, hoje);
  const antes = atualizar ? arred(flt(c.valor), 2) : null;
  const quando = ate ? ` até ${dataBr(ate).slice(0, 5)}` : "";
  const cmds: Comando[] = [gravar(oid, cid, "aceitou", hoje, { ate_desconto: ate, valor_antes: antes })];
  if (atualizar) cmds.push({ sql: "UPDATE clientes SET valor=?, atualizado_em=datetime('now','localtime') WHERE id=?", params: [o.valor_oferta, cid] });
  cmds.push({ sql: "INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'anotacao', ?, ?)",
    params: [cid, hoje, `Aceitou a oferta: ${o.titulo} (${moeda(o.valor_oferta)}/mês${quando})` + (atualizar ? "" : "; mensalidade não alterada")] });
  await b.batch(cmds);
  return [atualizar ? `${c.nome} aceitou: mensalidade em ${moeda(o.valor_oferta)}.` : `${c.nome} aceitou. A mensalidade continua ${moeda(c.valor)}.`, null];
}

export async function recusou(b: Banco, cid: number, oid: number, hoje: string): Promise<[string | null, string | null]> {
  const [[c, o], r] = await Promise.all([par(b, cid, oid), resposta(b, cid, oid)]);
  if (!c || !o) return [null, "Aluno ou oferta não encontrado."];
  if (r && r.status === "aceitou") return [null, `${c.nome} já aceitou essa oferta.`];
  await b.batch([gravar(oid, cid, "recusou", hoje)]);
  return [`${c.nome} recusou: anotado.`, null];
}

/** O valor da oferta acabou: a mensalidade volta ao valor normal. */
export async function encerrarDesconto(b: Banco, cid: number, oid: number, hoje: string): Promise<[string | null, string | null]> {
  const [[c, o], r] = await Promise.all([par(b, cid, oid), resposta(b, cid, oid)]);
  if (!c || !o || !r || r.status !== "aceitou") return [null, "Essa oferta não está aceita por esse aluno."];
  await b.batch([
    { sql: "UPDATE oferta_respostas SET encerrado_em=? WHERE id=?", params: [hoje, r.id] },
    { sql: "UPDATE clientes SET valor=?, atualizado_em=datetime('now','localtime') WHERE id=?", params: [o.valor_normal, cid] },
    { sql: "INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'anotacao', ?, ?)",
      params: [cid, hoje, `Fim do valor da oferta ${o.titulo}: mensalidade voltou para ${moeda(o.valor_normal)}`] },
  ]);
  return [`Mensalidade de ${c.nome} voltou para ${moeda(o.valor_normal)}.`, null];
}

/** Por oferta ativa: quem pode receber (ativo, em dia ou vencendo, com telefone e sem resposta). */
export async function pendentes(b: Banco, hoje: string, estados?: Map<number, Estado>): Promise<{ oferta: Linha; elegiveis: Estado[] }[]> {
  const lista = await ativas(b, hoje);
  if (!lista.length) return [];
  const [est, resp] = await Promise.all([estados ? Promise.resolve(estados) : estadoAlunos(b, hoje),
    b.query("SELECT oferta_id, cliente_id FROM oferta_respostas WHERE excluido_em IS NULL")]);
  const respondeu = new Map<number, Set<number>>();
  for (const r of resp) {
    if (!respondeu.has(r.oferta_id)) respondeu.set(r.oferta_id, new Set());
    respondeu.get(r.oferta_id)!.add(r.cliente_id);
  }
  const bons = [...est.values()].filter((e) => SITUACOES_ELEGIVEIS.includes(e.situacao) && String(e.tel ?? "").trim())
    .sort((x, y) => (x.nome.toLowerCase() < y.nome.toLowerCase() ? -1 : x.nome.toLowerCase() > y.nome.toLowerCase() ? 1 : 0));
  return lista.map((o) => ({ oferta: o, elegiveis: bons.filter((e) => !(respondeu.get(o.id)?.has(e.id))) }));
}

/** Quem aceitou uma oferta com prazo que acaba em até `dias` dias (ou já acabou) e ainda paga o valor da oferta. */
export async function descontosAcabando(b: Banco, hoje: string, dias = 7): Promise<Linha[]> {
  const lim = isoDoDia(numeroDoDia(hoje)! + dias);
  const rows = await b.query(`SELECT r.cliente_id, r.oferta_id, r.ate_desconto, c.nome, c.telefone, c.valor, o.titulo, o.valor_normal, o.valor_oferta
    FROM oferta_respostas r JOIN ofertas o ON o.id=r.oferta_id AND o.excluido_em IS NULL
    JOIN clientes c ON c.id=r.cliente_id AND c.excluido_em IS NULL AND c.status='ativo'
    WHERE r.excluido_em IS NULL AND r.status='aceitou' AND r.encerrado_em IS NULL
    AND r.ate_desconto IS NOT NULL AND r.ate_desconto <= ? ORDER BY r.ate_desconto, c.nome`, [lim]);
  return rows.filter((r) => Math.abs(flt(r.valor) - flt(r.valor_oferta)) < 0.005).map((r) => ({ ...r }));
}
