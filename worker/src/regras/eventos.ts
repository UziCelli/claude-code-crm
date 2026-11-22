/** Histórico do aluno pela ficha: anotação e mês pulado (port de main.registrar_evento e alunos.pular_mes). */
import type { Banco } from "../banco/banco.ts";
import type { Comando } from "../banco/tipos.ts";
import { dataBr, moeda } from "../formato.ts";
import { numBr } from "../rotas/util.ts";
import { avisoLotados, GravaAgenda } from "./agenda.ts";
import { dataIso } from "./datas.ts";
import { ANTECEDENCIA, proximaRenovacao, renovacoes, usarCredito } from "./financeiro.ts";

type Resultado = [string | null, string | null];

/** Registra no histórico do aluno. Devolve [mensagem, erro]: um dos dois é null. Pausa e renovação deixam o aluno ativo. */
export async function registrarEvento(b: Banco, cid: number, tipo: string, data: string, valor: string, descricao: string,
  novaRenovacao: string, hoje: string): Promise<Resultado> {
  const v = valor ? numBr(valor) : null;
  const nova = dataIso(novaRenovacao);
  const [ren, st] = await Promise.all([renovacoes(b, cid), b.um<{ status: string | null }>("SELECT status FROM clientes WHERE id=?", [cid])]);
  const antes = ren.get(cid);
  const voltou = !!st && st.status !== "ativo" && (tipo === "pausa" || tipo === "renovacao");
  const g = voltou ? await GravaAgenda.abrir(b, hoje) : null;
  const tirar = () => (g ? g.tirarDosLotados(cid) : []);
  const cmds: Comando[] = [];
  if (tipo === "pausa") {
    // pulou o mês: a renovação que estava para vencer não é cobrada; a próxima é a volta (vazio = um mês depois)
    const pulada = (antes ? dataIso(antes.efetiva) : null) || dataIso(data) || hoje;
    const volta = nova || proximaRenovacao(pulada);
    if (volta <= pulada) return [null, `A volta precisa ser depois de ${dataBr(pulada)} (a renovação que foi pulada).`];
    const texto = `Renovação de ${dataBr(pulada)} sem cobrança; volta em ${dataBr(volta)}` + (descricao ? `. ${descricao}` : "");
    cmds.push({ sql: "INSERT INTO cliente_eventos (cliente_id, tipo, data, ate, descricao) VALUES (?,?,?,?,?)", params: [cid, "pausa", pulada, volta, texto] },
      { sql: "UPDATE clientes SET data_renovacao=?, renovacao_em=datetime('now','localtime'), status='ativo' WHERE id=?", params: [volta, cid] });
    const tirados = tirar();
    await b.batch([...cmds, ...(g?.cmds ?? [])]);
    return [`Mês pulado, sem cobrança. Próxima renovação: ${dataBr(volta)}.` + avisoLotados(tirados), null];
  }
  cmds.push({ sql: "INSERT INTO cliente_eventos (cliente_id, tipo, data, valor, descricao) VALUES (?,?,?,?,?)", params: [cid, tipo, data, v, descricao || null] });
  const renovar = "UPDATE clientes SET data_renovacao=?, renovacao_em=datetime('now','localtime'), status='ativo' WHERE id=?";
  if (tipo === "renovacao" && nova) cmds.push({ sql: renovar, params: [nova, cid] });
  else if (tipo === "renovacao" && !antes && dataIso(data)) cmds.push({ sql: renovar, params: [proximaRenovacao(dataIso(data)!), cid] });
  else if (tipo === "renovacao") cmds.push({ sql: "UPDATE clientes SET status='ativo' WHERE id=?", params: [cid] });
  const tirados = tirar();
  await b.batch([...cmds, ...(g?.cmds ?? [])]);
  if (tipo !== "renovacao") return ["Registrado.", null];
  const depois = (await renovacoes(b, cid)).get(cid);
  const proxima = depois ? dataBr(String(depois.efetiva)) : "—";
  if (nova || !antes || depois?.efetiva !== antes.efetiva) return [`Renovação registrada. Próxima: ${proxima}.` + avisoLotados(tirados), null];
  return [`Registrado. A renovação continua em ${proxima}: sem data, ela só anda quando faltam até ${ANTECEDENCIA} dias. `
    + "Para outra data, preencha a nova data de renovação." + avisoLotados(tirados), null];
}

/** "Pulou o mês": a renovação efetiva anda um mês, sem cobrança. Se um crédito já cobre a mensalidade inteira, ele é usado. */
export async function pularMes(b: Banco, cid: number, hoje: string): Promise<Resultado> {
  const r = (await renovacoes(b, cid)).get(cid);
  const efetiva = r ? dataIso(r.efetiva) : null;
  if (!efetiva) return [null, "Esse aluno não tem data de renovação: complete o cadastro."];
  let [msg, erro] = await registrarEvento(b, cid, "pausa", hoje, "", "", proximaRenovacao(efetiva), hoje);
  if (!erro) {
    const [usado, cmds] = await usarCredito(b, null, cid, hoje);
    await b.batch(cmds);
    if (usado) msg += ` O crédito de ${moeda(usado)} cobriu esse mês.`;
  }
  return [msg, erro];
}
