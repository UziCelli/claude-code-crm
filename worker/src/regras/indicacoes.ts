/**
 * Indicações (port de app/indicacoes.py): quem indicou quem e o presente que o indicador ganha (brinde, nunca desconto).
 * O presente é devido no 1º pagamento de verdade do indicado; no máximo 1 por indicado.
 */
import type { Banco } from "../banco/banco.ts";
import type { Linha } from "../banco/tipos.ts";
import { EMPRESTIMO } from "./financeiro.ts";
import { espacosSimples } from "./texto.ts";

export const CANAL = "Indicação";

const BASE = `
SELECT r.id AS indicador_id, r.nome AS indicador, r.local AS indicador_local, i.id AS indicado_id, i.nome AS indicado,
       (SELECT MIN(l.pago_em) FROM lancamentos l WHERE l.cliente_id = i.id AND l.escopo='PJ' AND l.tipo='entrada'
           AND l.pago_em IS NOT NULL AND l.excluido_em IS NULL AND l.categoria != '${EMPRESTIMO}') AS pago_em,
       (SELECT MIN(e.id) FROM cliente_eventos e WHERE e.tipo='brinde' AND e.indicado_id = i.id AND e.excluido_em IS NULL) AS brinde_id,
       (SELECT e.data FROM cliente_eventos e WHERE e.tipo='brinde' AND e.indicado_id = i.id AND e.excluido_em IS NULL ORDER BY e.id LIMIT 1) AS brinde_data,
       (SELECT e.descricao FROM cliente_eventos e WHERE e.tipo='brinde' AND e.indicado_id = i.id AND e.excluido_em IS NULL ORDER BY e.id LIMIT 1) AS brinde_desc
FROM clientes i JOIN clientes r ON r.id = i.indicado_por
WHERE i.excluido_em IS NULL AND r.excluido_em IS NULL AND i.id != r.id
`;

/** Presentes a dar: o indicado já pagou e o indicador ainda não ganhou nada por ele. Mais antigo primeiro. */
export async function pendentes(b: Banco): Promise<Linha[]> {
  const out = (await b.query(BASE)).filter((r) => r.pago_em && !r.brinde_id).map((r) => ({ ...r }));
  return out.sort((x, y) => (x.pago_em < y.pago_em ? -1 : x.pago_em > y.pago_em ? 1 : x.indicado_id - y.indicado_id));
}

/** Quem este aluno indicou: 'aguardando' (sem 1º pagamento), 'pendente' (falta o presente) ou 'entregue'. */
export async function doAluno(b: Banco, cid: number): Promise<Linha[]> {
  return (await b.query(BASE + " AND r.id = ? ORDER BY i.id", [cid])).map((linha) => {
    const r: Linha = { ...linha, status: "aguardando" };
    if (r.brinde_id) {
      const prefixo = `Presente pela indicação de ${r.indicado}: `;
      const desc: string = r.brinde_desc || "";
      Object.assign(r, { status: "entregue", data: r.brinde_data, o_que: desc.startsWith(prefixo) ? desc.slice(prefixo.length) : desc });
    } else if (r.pago_em) r.status = "pendente";
    return r;
  });
}

/** {id, nome} de quem indicou este aluno (null se ninguém ou se foi para a lixeira). */
export async function quemIndicou(b: Banco, cid: number): Promise<{ id: number; nome: string } | null> {
  const r = await b.um("SELECT r.id, r.nome FROM clientes i JOIN clientes r ON r.id = i.indicado_por WHERE i.id=? AND r.excluido_em IS NULL", [cid]);
  return r ? { id: r.id, nome: r.nome } : null;
}

/** Confere o campo 'Indicado por': [id ou null, erro ou null]. Ninguém indica a si mesmo. */
export async function validar(b: Banco, textoBruto: unknown, proprioId: number | null = null): Promise<[number | null, string | null]> {
  const texto = String(textoBruto ?? "").trim();
  if (!texto) return [null, null];
  if (!/^\d+$/.test(texto)) return [null, "Escolha quem indicou na lista."];
  const iid = Number(texto);
  if (proprioId !== null && iid === proprioId) return [null, "Ninguém pode indicar a si mesmo."];
  if (!(await b.um("SELECT 1 AS ok FROM clientes WHERE id=? AND excluido_em IS NULL", [iid]))) return [null, "Quem indicou não está no cadastro de alunos."];
  return [iid, null];
}

/** Alunos (ativos e inativos) para o campo 'Indicado por', em ordem alfabética. */
export async function alunosParaEscolher(b: Banco, excluir: number | null = null): Promise<Linha[]> {
  return b.query("SELECT id, nome, status FROM clientes WHERE excluido_em IS NULL AND id != ? ORDER BY nome COLLATE NOCASE", [excluir || 0]);
}

/** Grava o presente do indicador pelo indicado. [mensagem, erro]: um dos dois é null. */
export async function registrarPresente(b: Banco, cid: number, iid: number, oQue: string, data: string, custo: number | null): Promise<[string | null, string | null]> {
  const o = espacosSimples(oQue || "");
  if (!o) return [null, "Diga o que você deu."];
  const r = await b.um(BASE + " AND r.id = ? AND i.id = ?", [cid, iid]);
  if (!r) return [null, "Essa indicação não existe."];
  if (r.brinde_id) return [null, `O presente pela indicação de ${r.indicado} já foi registrado.`];
  if (!r.pago_em) return [null, `${r.indicado} ainda não fez o 1º pagamento: registre o pagamento primeiro.`];
  await b.run("INSERT INTO cliente_eventos (cliente_id, tipo, data, valor, descricao, indicado_id) VALUES (?, 'brinde', ?, ?, ?, ?)",
    [cid, data, custo, `Presente pela indicação de ${r.indicado}: ${o}`, iid]);
  return [`Presente registrado: ${o} para ${r.indicador}.`, null];
}
