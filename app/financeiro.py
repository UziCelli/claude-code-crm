"""Financeiro PF + PJ — lógica pura sobre lancamentos e recorrencias. Datas ISO (AAAA-MM-DD), competência AAAA-MM."""
import calendar
import datetime as dt
import math
import sqlite3

from . import db


def vencimento(dia: int, mes: str) -> str:
    """Vencimento no mês 'AAAA-MM': o dia pedido, ou o último dia do mês se ele não existir (31 em fevereiro)."""
    ano, m = int(mes[:4]), int(mes[5:7])
    return dt.date(ano, m, min(dia, calendar.monthrange(ano, m)[1])).isoformat()


def status(lanc, hoje: str) -> str:
    """'pago' | 'atrasado' | 'pendente', calculado de pago_em e data."""
    if lanc["pago_em"]:
        return "pago"
    return "atrasado" if lanc["data"] < hoje else "pendente"


def pendencias(con: sqlite3.Connection, mes: str, hoje: str) -> list[dict]:
    """Em aberto até o fim do mês: lançamentos sem pago_em + recorrências ativas sem lançamento na competência.
    Vencidas primeiro, depois por data."""
    itens = []
    for r in con.execute(
        "SELECT * FROM lancamentos WHERE pago_em IS NULL AND excluido_em IS NULL AND data <= ?", (vencimento(31, mes),)
    ):
        itens.append({"origem": "lancamento", "id": r["id"], "escopo": r["escopo"], "tipo": r["tipo"], "data": r["data"],
                      "descricao": r["descricao"] or r["categoria"], "categoria": r["categoria"], "valor": r["valor"],
                      "status": status(r, hoje)})
    # ponytail: olha até 3 competências para trás (conta não paga não some na virada do mês); mais antigo que isso, só pelo livro-caixa
    ano, m = int(mes[:4]), int(mes[5:7])
    for k in range(4):
        comp = f"{(ano * 12 + m - 1 - k) // 12:04d}-{(ano * 12 + m - 1 - k) % 12 + 1:02d}"
        for r in con.execute(
            """SELECT * FROM recorrencias WHERE excluido_em IS NULL AND inicio <= ? AND (fim IS NULL OR fim >= ?)
               AND NOT EXISTS (SELECT 1 FROM lancamentos l WHERE l.recorrencia_id = recorrencias.id AND l.competencia = ?
                               AND l.excluido_em IS NULL)""",
            (comp, comp, comp),
        ):
            data = vencimento(r["dia_vencimento"], comp)
            itens.append({"origem": "recorrencia", "id": r["id"], "escopo": r["escopo"], "tipo": "saida", "data": data,
                          "descricao": r["descricao"], "categoria": r["categoria"], "valor": r["valor"], "competencia": comp,
                          "status": status({"pago_em": None, "data": data}, hoje)})
    itens.sort(key=lambda i: (i["status"] != "atrasado", i["data"]))
    return itens


def baixar_recorrencia(con: sqlite3.Connection, rid: int, competencia: str, valor: float, pago_em: str) -> int:
    """Cria o lançamento pago da recorrência naquela competência. ValueError se o valor é inválido ou já foi baixada."""
    valor = round(float(valor), 2)
    if not math.isfinite(valor) or valor <= 0:
        raise ValueError("O valor precisa ser maior que zero.")
    r = con.execute("SELECT * FROM recorrencias WHERE id=? AND excluido_em IS NULL", (rid,)).fetchone()
    if r is None:
        raise ValueError("Conta recorrente não encontrada.")
    # baixa que foi para a lixeira ainda ocupa o UNIQUE: reaproveita a linha em vez de dar "já baixada"
    antiga = con.execute("SELECT id FROM lancamentos WHERE recorrencia_id=? AND competencia=? AND excluido_em IS NOT NULL",
                         (rid, competencia)).fetchone()
    if antiga:
        with con:
            con.execute("UPDATE lancamentos SET excluido_em=NULL, valor=?, pago_em=? WHERE id=?", (valor, pago_em, antiga["id"]))
        return antiga["id"]
    try:
        with con:
            cur = con.execute(
                """INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, conta, recorrencia_id, competencia)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (r["escopo"], "saida", vencimento(r["dia_vencimento"], competencia), pago_em, valor, r["categoria"],
                 r["descricao"], r["conta"], rid, competencia),
            )
    except sqlite3.IntegrityError:
        raise ValueError("Esta conta já foi baixada neste mês.") from None
    return cur.lastrowid


def resumo_mes(con: sqlite3.Connection, mes: str, escopo: str = "PJ") -> dict:
    """Números do mês, só com lançamentos pagos. Fixo = saída vinda de recorrência fixa; o resto das saídas é variável."""
    soma = {}   # (tipo, fixo) -> total
    for tipo, fixo, total in con.execute(
        """SELECT l.tipo, r.fixo, SUM(l.valor) FROM lancamentos l LEFT JOIN recorrencias r ON r.id = l.recorrencia_id
           WHERE l.escopo=? AND l.excluido_em IS NULL AND l.pago_em IS NOT NULL AND substr(l.data,1,7)=?
           GROUP BY l.tipo, r.fixo""", (escopo, mes)):
        soma[(tipo, fixo)] = total
    receita = sum(v for (t, _), v in soma.items() if t == "entrada")
    fixos = sum(v for (t, f), v in soma.items() if t == "saida" and f == 1)
    variaveis = sum(v for (t, f), v in soma.items() if t == "saida" and f != 1)
    margem = (receita - variaveis) / receita if receita else 0   # margem de contribuição
    fiscal = db.parametros(con, "fiscal")
    pro_labore = max(fiscal["pro_labore_pct"] * receita, fiscal["salario_minimo"]) if receita > 0 else 0
    pf = {}
    for tipo, total in con.execute(
        """SELECT tipo, SUM(valor) FROM lancamentos WHERE escopo='PF' AND excluido_em IS NULL AND pago_em IS NOT NULL
           AND substr(data,1,7)=? GROUP BY tipo""", (mes,)):
        pf[tipo] = total
    entradas, saidas = pf.get("entrada", 0), pf.get("saida", 0)
    return {
        "mes": mes, "escopo": escopo,
        "receita": round(receita, 2), "custos_fixos": round(fixos, 2), "custos_variaveis": round(variaveis, 2),
        "lucro": round(receita - fixos - variaveis, 2),
        "ponto_equilibrio": round(fixos / margem, 2) if margem > 0 and fixos > 0 else None,
        "das": round(db.parametros(con, "imposto").get("DAS", 0.06) * receita, 2),
        "pro_labore": round(pro_labore, 2), "inss": round(fiscal["inss_pct"] * pro_labore, 2),
        "pf": {"entradas": round(entradas, 2), "saidas": round(saidas, 2), "saldo": round(entradas - saidas, 2)},
    }


def mensalidades(con: sqlite3.Connection, mes: str) -> list[dict]:
    """Alunos ativos: previsto = clientes.valor; recebido = entradas PJ pagas do cliente no mês.
    Situação: 'recebido' (recebido >= previsto), 'parcial' ou 'em aberto'."""
    itens = []
    for c in con.execute(
        """SELECT c.id, c.nome, COALESCE(c.valor, 0) AS previsto,
                  (SELECT COALESCE(SUM(l.valor), 0) FROM lancamentos l WHERE l.cliente_id = c.id AND l.escopo='PJ' AND l.tipo='entrada'
                   AND l.excluido_em IS NULL AND l.pago_em IS NOT NULL AND substr(l.data,1,7)=?) AS recebido
           FROM clientes c WHERE c.excluido_em IS NULL AND c.status='ativo' ORDER BY c.nome""", (mes,)):
        previsto, recebido = round(c["previsto"], 2), round(c["recebido"], 2)
        if previsto <= 0 and recebido <= 0:
            continue
        sit = "recebido" if recebido >= previsto else ("parcial" if recebido > 0 else "em aberto")
        itens.append({"id": c["id"], "nome": c["nome"], "previsto": previsto, "recebido": recebido, "situacao": sit})
    return itens
