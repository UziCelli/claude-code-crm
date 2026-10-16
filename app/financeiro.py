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
    for k in range(4):
        itens += _recorrencias_abertas(con, somar_meses(mes, -k), hoje)
    itens.sort(key=lambda i: (i["status"] != "atrasado", i["data"]))
    return itens


def somar_meses(mes: str, n: int) -> str:
    """'AAAA-MM' mais n meses (n pode ser negativo)."""
    t = int(mes[:4]) * 12 + int(mes[5:7]) - 1 + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def _recorrencias_abertas(con: sqlite3.Connection, comp: str, hoje: str) -> list[dict]:
    """Recorrências ativas na competência que ainda não têm lançamento nela (nem pago nem em aberto)."""
    itens = []
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
    return itens


# ---------- Saldo livre ----------
FRENTES = ("PF", "PJ", "Reserva", "Fora")   # Reserva = colchão (fica fora do livre); Fora = cartão, não guarda dinheiro
DIAS_SALDO_VELHO = 7


def frentes_contas(con: sqlite3.Connection) -> dict:
    """{conta: frente ou None} para todas as contas da lista. Conta nova sem frente: cartão vai para Fora, o resto fica None."""
    escolhidas = db.parametros(con, "conta_escopo")
    out = {}
    for conta in db.lista(con, "lista_contas"):
        f = escolhidas.get(conta)
        out[conta] = f if f in FRENTES else ("Fora" if conta.lower().startswith("cartão") else None)
    return out


def saldos_atuais(con: sqlite3.Connection) -> dict:
    """{conta: {saldo, data, escopo}} com a foto mais recente de cada conta da lista (saldo/data None se nunca digitado)."""
    ultimos = {}
    for r in con.execute("""SELECT conta, saldo, data FROM saldos WHERE excluido_em IS NULL ORDER BY data, id"""):
        ultimos[r["conta"]] = r   # a última linha de cada conta vence
    return {conta: {"saldo": ultimos[conta]["saldo"] if conta in ultimos else None,
                    "data": ultimos[conta]["data"] if conta in ultimos else None, "escopo": f}
            for conta, f in frentes_contas(con).items()}


def em_aberto_ate(con: sqlite3.Connection, ate: str, hoje: str) -> list[dict]:
    """Tudo em aberto com data até 'ate' (inclui atrasado): lançamentos sem pago_em + recorrências não baixadas,
    da competência de 3 meses atrás até a de 'ate'."""
    itens = [{"origem": "lancamento", "id": r["id"], "escopo": r["escopo"], "tipo": r["tipo"], "data": r["data"],
              "descricao": r["descricao"] or r["categoria"], "categoria": r["categoria"], "valor": r["valor"],
              "status": status(r, hoje)}
             for r in con.execute("SELECT * FROM lancamentos WHERE pago_em IS NULL AND excluido_em IS NULL AND data <= ?", (ate,))]
    comp, fim = somar_meses(hoje[:7], -3), ate[:7]
    while comp <= fim:
        itens += [i for i in _recorrencias_abertas(con, comp, hoje) if i["data"] <= ate]
        comp = somar_meses(comp, 1)
    itens.sort(key=lambda i: i["data"])
    return itens


def saldo_livre(con: sqlite3.Connection, hoje: str, dias: int = 30) -> dict:
    """Quanto dá para gastar de verdade, por frente (PF e PJ).
    livre = tem nas contas − saídas em aberto até hoje+dias − imposto a guardar (só PJ).
    Conservador: entrada prevista não conta; só o dinheiro que já está na conta.
    Imposto a guardar = DAS% da receita PJ recebida no mês (o DAS dela vence no mês seguinte),
    menos impostos PJ do mês seguinte que já estão nas saídas em aberto (não conta duas vezes)."""
    ate = (dt.date.fromisoformat(hoje) + dt.timedelta(days=dias)).isoformat()
    saldos = saldos_atuais(con)
    abertos = [i for i in em_aberto_ate(con, ate, hoje) if i["tipo"] == "saida"]
    receita_pj = con.execute("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE escopo='PJ' AND tipo='entrada'
                                AND excluido_em IS NULL AND pago_em IS NOT NULL AND substr(pago_em,1,7)=?""", (hoje[:7],)).fetchone()[0]
    das = db.parametros(con, "imposto").get("DAS", 0.06) * receita_pj
    prox = somar_meses(hoje[:7], 1)
    das -= sum(i["valor"] for i in abertos if i["escopo"] == "PJ" and i["data"][:7] == prox and "imposto" in i["categoria"].lower())
    out = {}
    for frente in ("PF", "PJ"):
        contas = {c: v for c, v in saldos.items() if v["escopo"] == frente}
        datas = [v["data"] for v in contas.values() if v["data"]]
        tem = sum(v["saldo"] for v in contas.values() if v["saldo"] is not None)
        comprometido = sum(i["valor"] for i in abertos if i["escopo"] == frente)
        imposto = max(das, 0) if frente == "PJ" else 0
        dias_velho = (dt.date.fromisoformat(hoje) - dt.date.fromisoformat(min(datas))).days if datas else None
        out[frente] = {
            "tem": round(tem, 2), "comprometido": round(comprometido, 2), "imposto": round(imposto, 2),
            "livre": round(tem - comprometido - imposto, 2), "ate": ate,
            "itens": [i for i in abertos if i["escopo"] == frente],
            "sem_saldo": not datas,   # nenhuma conta da frente com saldo digitado: o número não vale
            "dias_velho": dias_velho, "desatualizado": dias_velho is not None and dias_velho > DIAS_SALDO_VELHO,
        }
    out["reserva"] = round(sum(v["saldo"] for v in saldos.values() if v["escopo"] == "Reserva" and v["saldo"] is not None), 2)
    out["sem_frente"] = [c for c, v in saldos.items() if v["escopo"] is None]
    return out


def salvar_saldos(con: sqlite3.Connection, data: str, valores: dict, frentes: dict) -> int:
    """Grava a foto do dia. valores = {conta: saldo} (só as contas digitadas); frentes = {conta: frente}.
    Digitar de novo no mesmo dia troca a foto do dia (não acumula). Devolve quantas contas gravou."""
    with con:
        for conta, frente in frentes.items():
            if frente in FRENTES:
                con.execute("""INSERT INTO parametros (grupo, chave, valor_texto, ordem) VALUES ('conta_escopo', ?, ?,
                               (SELECT COALESCE(MAX(ordem), 0) + 1 FROM parametros WHERE grupo='conta_escopo'))
                               ON CONFLICT (grupo, chave) DO UPDATE SET valor_texto=excluded.valor_texto""", (conta, frente))
        for conta, saldo in valores.items():
            con.execute("UPDATE saldos SET excluido_em=datetime('now','localtime') WHERE conta=? AND data=? AND excluido_em IS NULL",
                        (conta, data))
            con.execute("INSERT INTO saldos (conta, saldo, data) VALUES (?,?,?)", (conta, round(saldo, 2), data))
    return len(valores)


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
    # salário da PJ para a PF: sai do lucro, não é custo do negócio
    retirada = con.execute("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE escopo=? AND tipo='saida' AND categoria=?
                              AND excluido_em IS NULL AND pago_em IS NOT NULL AND substr(data,1,7)=?""", (escopo, RETIRADA, mes)).fetchone()[0]
    soma[("saida", None)] = soma.get(("saida", None), 0) - retirada   # retirada nunca vem de recorrência (r.fixo é NULL)
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
        "lucro": round(receita - fixos - variaveis, 2), "retirada": round(retirada, 2),
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


# ---------- Salário fixo PJ -> PF ----------
RETIRADA = "Retirada"


def salario_mes(con: sqlite3.Connection, mes: str, hoje: str) -> dict:
    """Salário do mês: valor e dia (parâmetros), se já foi pago, se já pode pagar e quanto a PF já gastou do salário."""
    p = db.parametros(con, "salario")
    valor, dia = round(p.get("valor") or 0, 2), int(p.get("dia") or 5)
    pago = con.execute("SELECT pago_em FROM lancamentos WHERE origem=? AND excluido_em IS NULL", (f"SAL:{mes}:PJ",)).fetchone()
    gasto = con.execute("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE escopo='PF' AND tipo='saida' AND excluido_em IS NULL
                           AND pago_em IS NOT NULL AND substr(pago_em,1,7)=?""", (mes,)).fetchone()[0]
    data = vencimento(min(max(dia, 1), 31), mes)
    return {"mes": mes, "valor": valor, "dia": dia, "data": data, "ligado": valor > 0,
            "pago_em": pago["pago_em"] if pago else None, "pode_pagar": valor > 0 and not pago and hoje >= data,
            "gasto_pf": round(gasto, 2), "pct_gasto": round(100 * gasto / valor) if valor > 0 else None,
            "sugestao": sugestao_salario(con, mes)}


def sugestao_salario(con: sqlite3.Connection, mes: str) -> float:
    """80% do lucro PJ médio dos 3 meses fechados antes de 'mes' (os 20% restantes vão para o colchão), em múltiplos de 50."""
    lucros = [resumo_mes(con, somar_meses(mes, -k))["lucro"] for k in (1, 2, 3)]
    media = sum(lucros) / 3
    return max(0, math.floor(0.8 * media / 50) * 50)


def pagar_salario(con: sqlite3.Connection, mes: str, pago_em: str) -> None:
    """Saída PJ (Retirada) + entrada PF (Salário) do mês, numa transação. ValueError se desligado ou já pago."""
    valor = round(db.parametros(con, "salario").get("valor") or 0, 2)
    if valor <= 0:
        raise ValueError("Defina o valor do salário em Configurações.")
    nome = f"Salário {mes[5:]}/{mes[:4]}"
    antigo = con.execute("SELECT id FROM lancamentos WHERE origem=?", (f"SAL:{mes}:PJ",)).fetchone()
    try:
        with con:
            if antigo:   # pagamento que foi para a lixeira: volta com o valor de hoje
                cur = con.execute("""UPDATE lancamentos SET excluido_em=NULL, valor=?, data=?, pago_em=?
                                     WHERE origem IN (?, ?) AND excluido_em IS NOT NULL""", (valor, pago_em, pago_em, f"SAL:{mes}:PJ", f"SAL:{mes}:PF"))
                if cur.rowcount == 0:   # as duas linhas estão ativas: já pago
                    raise sqlite3.IntegrityError
                return
            con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, conta, origem)
                           VALUES ('PJ','saida',?,?,?,?,?, 'Contabilizei Bank', ?)""", (pago_em, pago_em, valor, RETIRADA, nome, f"SAL:{mes}:PJ"))
            con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, origem)
                           VALUES ('PF','entrada',?,?,?, 'Salário', ?, ?)""", (pago_em, pago_em, valor, nome, f"SAL:{mes}:PF"))
    except sqlite3.IntegrityError:
        raise ValueError("O salário deste mês já foi pago.") from None


# ---------- Potes ----------
POTES = (("imposto", "Imposto"), ("contas", "Contas da PJ"), ("salario", "Salário PF"), ("colchao", "Colchão"))


def _fixos_mes(con: sqlite3.Connection, mes: str, escopo: str, so_fixos: bool) -> float:
    """Soma prevista das recorrências ativas do escopo na competência (sem a Retirada)."""
    return con.execute(f"""SELECT COALESCE(SUM(valor), 0) FROM recorrencias WHERE excluido_em IS NULL AND escopo=? AND categoria != ?
                           AND inicio <= ? AND (fim IS NULL OR fim >= ?){' AND fixo=1' if so_fixos else ''}""",
                       (escopo, RETIRADA, mes, mes)).fetchone()[0]


def potes_mes(con: sqlite3.Connection, mes: str) -> dict:
    """Divide cada entrada PJ recebida no mês em cascata: imposto (DAS% de cada entrada, sempre primeiro),
    contas da PJ (até as recorrências PJ do mês), salário da PF (até o salário fixo) e o resto no colchão."""
    das = db.parametros(con, "imposto").get("DAS", 0.06)
    alvo = {"contas": _fixos_mes(con, mes, "PJ", False), "salario": db.parametros(con, "salario").get("valor") or 0}
    cheio = dict.fromkeys(dict(POTES), 0.0)
    entradas = []
    for e in con.execute("""SELECT id, valor, descricao, categoria, contraparte, pago_em FROM lancamentos WHERE escopo='PJ' AND tipo='entrada'
                            AND excluido_em IS NULL AND pago_em IS NOT NULL AND substr(pago_em,1,7)=? ORDER BY pago_em, id""", (mes,)):
        resto = e["valor"]
        div = {"imposto": round(das * resto, 2)}
        resto -= div["imposto"]
        for k in ("contas", "salario"):
            div[k] = round(max(0, min(resto, alvo[k] - cheio[k])), 2)
            resto -= div[k]
        div["colchao"] = round(max(resto, 0), 2)
        for k, v in div.items():
            cheio[k] += v
        entradas.append({"id": e["id"], "valor": e["valor"], "descricao": e["descricao"] or e["contraparte"] or e["categoria"],
                         "pago_em": e["pago_em"], "divisao": div})
    alvo["imposto"] = cheio["imposto"]   # imposto não tem teto: é sempre a fração da entrada
    alvo["colchao"] = None               # colchão não tem teto no mês
    potes = [{"chave": k, "nome": nome, "alvo": round(alvo[k], 2) if alvo[k] is not None else None, "cheio": round(cheio[k], 2),
              "falta": round(max(alvo[k] - cheio[k], 0), 2) if alvo[k] is not None else 0,
              "pct": min(100, round(100 * cheio[k] / alvo[k])) if alvo[k] else (100 if cheio[k] else 0)}
             for k, nome in POTES if k != "salario" or alvo["salario"]]
    return {"mes": mes, "potes": potes, "entradas": entradas}


def texto_divisao(div: dict) -> str:
    """'R$ 30,00 imposto · R$ 400,00 contas da PJ · ...', só os potes com valor."""
    nomes = dict(POTES)
    return " · ".join(f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " " + nomes[k].lower()
                      for k, v in div.items() if v > 0)


def colchao(con: sqlite3.Connection, mes: str) -> dict:
    """Custo fixo de 1 mês para o colchão: recorrências fixas da PJ + o salário da PF
    (sem salário fixo, as recorrências fixas da PF). Mostra 1 e 3 meses, o guardado e a meta."""
    sal = db.parametros(con, "salario").get("valor") or 0
    mensal = _fixos_mes(con, mes, "PJ", True) + (sal if sal > 0 else _fixos_mes(con, mes, "PF", True))
    guardado = sum(v["saldo"] for v in saldos_atuais(con).values() if v["escopo"] == "Reserva" and v["saldo"] is not None)
    meses = db.parametros(con, "colchao").get("meses") or 0
    meta = round(mensal * meses, 2) if meses else None
    return {"mensal": round(mensal, 2), "um": round(mensal, 2), "tres": round(3 * mensal, 2), "guardado": round(guardado, 2),
            "meses_meta": meses, "meta": meta, "pct": min(100, round(100 * guardado / meta)) if meta else None,
            "cobre_meses": round(guardado / mensal, 1) if mensal else None}


# ---------- Linha do tempo (previsão) ----------
def _mensalidades_a_receber(con: sqlite3.Connection, mes: str) -> float:
    """Quanto dos alunos ativos ainda falta entrar no mês: previsto − recebido − entradas já lançadas em aberto, por aluno."""
    total = 0.0
    for m in mensalidades(con, mes):
        aberto = con.execute("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE cliente_id=? AND escopo='PJ' AND tipo='entrada'
                                AND excluido_em IS NULL AND pago_em IS NULL AND substr(data,1,7)=?""", (m["id"], mes)).fetchone()[0]
        total += max(m["previsto"] - m["recebido"] - aberto, 0)
    return round(total, 2)


def previsao(con: sqlite3.Connection, hoje: str, semanas: int = 13) -> dict:
    """Saldo previsto semana a semana, PF e PJ, a partir dos saldos digitados.
    Entra: tudo em aberto (lançamentos e recorrências), salário ainda não pago (sai da PJ, entra na PF),
    mensalidades que faltam receber (estimado, no dia previsao.dia_recebimento) e o DAS estimado
    (DAS% da receita do mês anterior, no dia previsao.dia_das, se o mês ainda não tem imposto PJ lançado).
    O que já venceu e não foi pago entra na primeira semana."""
    h = dt.date.fromisoformat(hoje)
    fim = (h + dt.timedelta(days=7 * semanas - 1)).isoformat()
    meses = []
    m = hoje[:7]
    while m <= fim[:7]:
        meses.append(m)
        m = somar_meses(m, 1)
    par = db.parametros(con, "previsao")
    das_pct = db.parametros(con, "imposto").get("DAS", 0.06)
    sal = db.parametros(con, "salario")
    itens = [dict(i, estimado=False) for i in em_aberto_ate(con, fim, hoje)]

    def add(escopo, tipo, data, descricao, valor, estimado=True):
        if valor > 0 and data <= fim:
            itens.append({"escopo": escopo, "tipo": tipo, "data": max(data, hoje), "descricao": descricao,
                          "categoria": "", "valor": round(valor, 2), "estimado": estimado})

    receita = {}   # receita PJ esperada por mês (recebida + a receber), base do DAS do mês seguinte
    for mes in meses:
        recebido = con.execute("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE escopo='PJ' AND tipo='entrada'
                                  AND excluido_em IS NULL AND pago_em IS NOT NULL AND substr(pago_em,1,7)=?""", (mes,)).fetchone()[0]
        falta = _mensalidades_a_receber(con, mes)
        abertas = sum(i["valor"] for i in itens if i["escopo"] == "PJ" and i["tipo"] == "entrada" and i["data"][:7] == mes)
        receita[mes] = recebido + falta + abertas
        add("PJ", "entrada", vencimento(int(par.get("dia_recebimento") or 10), mes), "Mensalidades a receber", falta)
        if (sal.get("valor") or 0) > 0 and not con.execute("SELECT 1 FROM lancamentos WHERE origem=? AND excluido_em IS NULL",
                                                           (f"SAL:{mes}:PJ",)).fetchone():
            data = vencimento(int(sal.get("dia") or 5), mes)
            add("PJ", "saida", data, "Salário para a PF", sal["valor"], estimado=False)
            add("PF", "entrada", data, "Salário da PJ", sal["valor"], estimado=False)
        tem_imposto = con.execute("""SELECT 1 FROM lancamentos WHERE escopo='PJ' AND tipo='saida' AND excluido_em IS NULL
                                     AND lower(categoria) LIKE '%imposto%' AND substr(data,1,7)=?""", (mes,)).fetchone() or any(
            i["escopo"] == "PJ" and i["tipo"] == "saida" and "imposto" in i["categoria"].lower() and i["data"][:7] == mes for i in itens)
        if not tem_imposto:
            anterior = somar_meses(mes, -1)
            base = receita.get(anterior)
            if base is None:   # mês anterior a hoje: só o que entrou de fato
                base = con.execute("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE escopo='PJ' AND tipo='entrada'
                                      AND excluido_em IS NULL AND pago_em IS NOT NULL AND substr(pago_em,1,7)=?""", (anterior,)).fetchone()[0]
            add("PJ", "saida", vencimento(int(par.get("dia_das") or 20), mes), f"DAS estimado ({anterior[5:]}/{anterior[:4]})", das_pct * base)

    livre = saldo_livre(con, hoje)
    saldo = {f: livre[f]["tem"] for f in ("PF", "PJ")}
    linhas, aperto = [], {}
    for k in range(semanas):
        ini = (h + dt.timedelta(days=7 * k)).isoformat()
        fim_sem = (h + dt.timedelta(days=7 * k + 6)).isoformat()
        da_semana = sorted((i for i in itens if (i["data"] <= fim_sem and (k == 0 or i["data"] >= ini))), key=lambda i: i["data"])
        linha = {"inicio": ini, "fim": fim_sem, "itens": da_semana}
        for f in ("PF", "PJ"):
            ent = sum(i["valor"] for i in da_semana if i["escopo"] == f and i["tipo"] == "entrada")
            sai = sum(i["valor"] for i in da_semana if i["escopo"] == f and i["tipo"] == "saida")
            saldo[f] += ent - sai
            linha[f] = {"entradas": round(ent, 2), "saidas": round(sai, 2), "saldo": round(saldo[f], 2)}
            if saldo[f] < 0 and f not in aperto:
                aperto[f] = {"inicio": ini, "saldo": round(saldo[f], 2)}
        linha["negativo"] = any(linha[f]["saldo"] < 0 for f in ("PF", "PJ"))
        linhas.append(linha)
    menor = {f: min(l[f]["saldo"] for l in linhas) for f in ("PF", "PJ")}
    return {"semanas": linhas, "aperto": aperto, "menor": menor, "inicio": {f: livre[f]["tem"] for f in ("PF", "PJ")},
            "sem_saldo": {f: livre[f]["sem_saldo"] for f in ("PF", "PJ")}, "fim": fim}
