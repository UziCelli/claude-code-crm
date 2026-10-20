"""Financeiro PF + PJ — lógica pura sobre lancamentos e recorrencias. Datas ISO (AAAA-MM-DD), competência AAAA-MM."""
import calendar
import datetime as dt
import math
import re
import sqlite3
import unicodedata

from . import db

ISO_DATA = re.compile(r"\d{4}-\d{2}-\d{2}")


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
    da competência de 3 meses atrás até a de 'ate'. Pago com data no futuro (agendado) ainda está na conta:
    conta como aberto, na data do pagamento."""
    itens = []
    for r in con.execute("""SELECT * FROM lancamentos WHERE (pago_em IS NULL OR pago_em > ?) AND excluido_em IS NULL
                            AND COALESCE(pago_em, data) <= ?""", (hoje, ate)):
        data = r["pago_em"] or r["data"]
        itens.append({"origem": "lancamento", "id": r["id"], "escopo": r["escopo"], "tipo": r["tipo"], "data": data,
                      "descricao": r["descricao"] or r["categoria"], "categoria": r["categoria"], "valor": r["valor"],
                      "status": status({"pago_em": None, "data": data}, hoje)})
    comp, fim = somar_meses(hoje[:7], -3), ate[:7]
    while comp <= fim:
        itens += [i for i in _recorrencias_abertas(con, comp, hoje) if i["data"] <= ate]
        comp = somar_meses(comp, 1)
    itens.sort(key=lambda i: i["data"])
    return itens


# ---------- DAS ----------
def eh_das(descricao: str | None, categoria: str | None) -> bool:
    """Saída que é o DAS (Simples Nacional): categoria 'DAS', 'DAS' na descrição (em maiúsculas ou como primeira palavra),
    'Simples Nacional', ou imposto sem descrição (como era antes). 'Imposto' na categoria não basta: DARF, INSS e taxas
    também caem em 'Impostos/Taxas' e não são o DAS. Descrição igual à categoria conta como vazia (as telas usam a
    categoria quando não há descrição)."""
    descricao = (descricao or "").strip()
    if descricao == (categoria or "").strip():
        descricao = ""
    palavras = _palavras(descricao)
    if _palavras(categoria) == ["das"] or re.search(r"\bDAS\b", descricao) or palavras[:1] == ["das"] \
            or "simples nacional" in " ".join(palavras):
        return True
    return not descricao and "imposto" in (categoria or "").lower()


def _receita_pj(con: sqlite3.Connection, mes: str) -> float:
    """Entradas PJ recebidas no mês (por pago_em): a base do DAS que vence no mês seguinte. Empréstimo não é receita."""
    return con.execute("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE escopo='PJ' AND tipo='entrada'
                          AND excluido_em IS NULL AND pago_em IS NOT NULL AND substr(pago_em,1,7)=? AND categoria != ?""",
                       (mes, EMPRESTIMO)).fetchone()[0]


def _das_do_mes(con: sqlite3.Connection, mes: str, abertos: list[dict]) -> tuple[bool, float]:
    """O que já se sabe do DAS que vence no mês: (tem DAS de verdade, pago ou lançado entre os abertos;
    soma das recorrências de DAS ainda não baixadas, que são só um valor previsto). Itens estimados pelo app não contam."""
    pago = any(eh_das(r["descricao"], r["categoria"]) for r in con.execute(
        """SELECT descricao, categoria FROM lancamentos WHERE escopo='PJ' AND tipo='saida' AND excluido_em IS NULL
           AND pago_em IS NOT NULL AND substr(data,1,7)=?""", (mes,)))
    meus = [i for i in abertos if i.get("origem") and i["escopo"] == "PJ" and i["tipo"] == "saida" and i["data"][:7] == mes
            and eh_das(i["descricao"], i["categoria"])]
    return pago or any(i["origem"] == "lancamento" for i in meus), sum(i["valor"] for i in meus if i["origem"] == "recorrencia")


def _das_a_guardar(con: sqlite3.Connection, mes: str, abertos: list[dict], base: float, das_pct: float) -> float:
    """DAS que vence no mês e ainda não está em lugar nenhum: DAS% × base menos o que a recorrência de DAS já prevê.
    Com DAS de verdade (pago ou em aberto), nada a guardar."""
    real, previsto = _das_do_mes(con, mes, abertos)
    return 0.0 if real else max(das_pct * base - previsto, 0)


def _tem(con: sqlite3.Connection, contas: dict, frente: str, hoje: str) -> float:
    """Saldo de partida da frente: a foto mais recente de cada conta + entradas − saídas pagas depois dela, até hoje.
    Pago no dia da foto já está nela (por isso 'depois'); pago no futuro ainda não saiu da conta.
    Lançamento com conta só mexe nela: cartão, Reserva e conta de outra frente ficam de fora. Sem conta, vai pelo escopo,
    do lado seguro: saída conta depois da foto mais antiga da frente; entrada, só depois da mais recente."""
    fotos = {c: v for c, v in contas.items() if v["data"]}
    if not fotos:
        return 0.0
    datas = [v["data"] for v in fotos.values()]
    tem = sum(v["saldo"] for v in fotos.values())
    for r in con.execute("""SELECT escopo, tipo, valor, conta, pago_em FROM lancamentos WHERE excluido_em IS NULL
                            AND pago_em > ? AND pago_em <= ?""", (min(datas), hoje)):
        entrada = r["tipo"] == "entrada"
        if r["conta"]:
            corte = fotos[r["conta"]]["data"] if r["conta"] in fotos else None
        else:
            corte = (max(datas) if entrada else min(datas)) if r["escopo"] == frente else None
        if corte and r["pago_em"] > corte:
            tem += r["valor"] if entrada else -r["valor"]
    return tem


def saldo_livre(con: sqlite3.Connection, hoje: str, dias: int = 30) -> dict:
    """Quanto dá para gastar de verdade, por frente (PF e PJ).
    livre = tem nas contas − saídas em aberto até hoje+dias − imposto a guardar e salário ainda não pago (só PJ).
    Conservador: entrada prevista não conta; só o dinheiro que já está na conta (ver _tem).
    Imposto a guardar = DAS do mês que vem (DAS% da receita PJ recebida neste mês) + DAS deste mês, enquanto não for
    lançado (DAS% da receita do mês passado). DAS já em aberto está no comprometido e não conta duas vezes.
    Salário: o que falta tirar da PJ em cada salário que vence até hoje+dias (deste mês em diante)."""
    ate = (dt.date.fromisoformat(hoje) + dt.timedelta(days=dias)).isoformat()
    saldos = saldos_atuais(con)
    abertos = [i for i in em_aberto_ate(con, ate, hoje) if i["tipo"] == "saida"]
    mes, das_pct = hoje[:7], db.parametros(con, "imposto").get("DAS", 0.06)
    das = (_das_a_guardar(con, somar_meses(mes, 1), abertos, _receita_pj(con, mes), das_pct)
           + _das_a_guardar(con, mes, abertos, _receita_pj(con, somar_meses(mes, -1)), das_pct))
    sal_valor, sal_dia = _salario_parametros(con)
    salario, m = 0.0, mes
    while m <= ate[:7]:
        if vencimento(sal_dia, m) <= ate:
            salario += _salario_falta(con, m, sal_valor)
        m = somar_meses(m, 1)
    out = {}
    for frente in ("PF", "PJ"):
        contas = {c: v for c, v in saldos.items() if v["escopo"] == frente}
        datas = [v["data"] for v in contas.values() if v["data"]]
        tem = _tem(con, contas, frente, hoje)
        comprometido = sum(i["valor"] for i in abertos if i["escopo"] == frente)
        imposto, sal = (das, salario) if frente == "PJ" else (0, 0)
        dias_velho = (dt.date.fromisoformat(hoje) - dt.date.fromisoformat(min(datas))).days if datas else None
        out[frente] = {
            "tem": round(tem, 2), "comprometido": round(comprometido, 2), "imposto": round(imposto, 2), "salario": round(sal, 2),
            "livre": round(tem - comprometido - imposto - sal, 2), "ate": ate,
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


def _mes_br(comp: str) -> str:
    return f"{comp[5:7]}/{comp[:4]}"


def liberar_vaga(con: sqlite3.Connection, rid: int, comp: str, lid: int | None) -> None:
    """Confere se a recorrência `rid` pode ser baixada em `comp` pelo lançamento `lid` (UNIQUE recorrencia_id+competencia).
    ValueError em português se o mês já tem outra baixa ativa. Baixa que está na lixeira só ocupa a vaga: é solta dela
    (volta como lançamento comum se for restaurada). Não faz commit: quem chama já está em `with con`."""
    outra = con.execute(
        """SELECT l.id, l.excluido_em, l.pago_em, l.data, r.descricao FROM lancamentos l JOIN recorrencias r ON r.id = l.recorrencia_id
           WHERE l.recorrencia_id=? AND l.competencia=? AND l.id IS NOT ?""", (rid, comp, lid)).fetchone()
    if outra is None:
        return
    if outra["excluido_em"] is None:
        quando = f" (dia {outra['pago_em'][8:10]}/{outra['pago_em'][5:7]})" if outra["pago_em"] else " (ainda em aberto)"
        raise ValueError(f"{outra['descricao']} de {_mes_br(comp)} já tem um lançamento{quando}. "
                         "Se pagou duas vezes, exclua um dos dois.")
    con.execute("UPDATE lancamentos SET recorrencia_id=NULL, competencia=NULL WHERE id=?", (outra["id"],))


def ligar_recorrencia(con: sqlite3.Connection, lid: int, rid: int) -> str:
    """Liga uma saída lançada à mão à conta recorrente (a competência é o mês da data). Devolve a descrição da conta.
    ValueError em português se não pode: não é saída, escopo diferente ou o mês já tem baixa."""
    lanc = con.execute("SELECT * FROM lancamentos WHERE id=? AND excluido_em IS NULL", (lid,)).fetchone()
    if lanc is None:
        raise ValueError("Lançamento não encontrado.")
    r = con.execute("SELECT * FROM recorrencias WHERE id=? AND excluido_em IS NULL", (rid,)).fetchone()
    if r is None:
        raise ValueError("Conta recorrente não encontrada.")
    if lanc["tipo"] != "saida":
        raise ValueError("Só saída pode ser uma conta recorrente.")
    if lanc["escopo"] != r["escopo"]:
        raise ValueError(f"{r['descricao']} é da {r['escopo']} e este lançamento é da {lanc['escopo']}.")
    comp = lanc["data"][:7]
    with con:
        liberar_vaga(con, rid, comp, lid)
        con.execute("UPDATE lancamentos SET recorrencia_id=?, competencia=?, sem_recorrencia=NULL WHERE id=?", (rid, comp, lid))
    return r["descricao"]


def saidas_parecidas(con: sqlite3.Connection) -> list[dict]:
    """Saídas lançadas à mão (sem recorrencia_id) que parecem ser uma conta recorrente ativa da mesma frente: mesma descrição
    ou mesma categoria e valor. Só sugere, nunca liga sozinho (despesa avulsa de mesmo valor é falso positivo).
    `ja_baixada` = a recorrência já tem baixa naquele mês: a conta foi paga duas vezes."""
    achados: dict[int, dict] = {}
    for x in con.execute(
        """SELECT l.id, l.data, l.pago_em, l.escopo, l.valor, l.categoria, l.descricao,
                  r.id AS rid, r.descricao AS rdescricao, r.valor AS rvalor, r.dia_vencimento,
                  CASE WHEN lower(trim(coalesce(l.descricao,''))) = lower(trim(r.descricao)) THEN 'descricao' ELSE 'categoria+valor' END AS casou_por,
                  EXISTS (SELECT 1 FROM lancamentos b WHERE b.recorrencia_id = r.id AND b.competencia = substr(l.data,1,7)
                          AND b.excluido_em IS NULL) AS ja_baixada
           FROM lancamentos l
           JOIN recorrencias r ON r.excluido_em IS NULL AND r.escopo = l.escopo
                AND r.inicio <= substr(l.data,1,7) AND (r.fim IS NULL OR r.fim >= substr(l.data,1,7))
                AND (lower(trim(coalesce(l.descricao,''))) = lower(trim(r.descricao))
                     OR (l.categoria = r.categoria AND abs(l.valor - r.valor) < 0.005))
           WHERE l.tipo = 'saida' AND l.excluido_em IS NULL AND l.recorrencia_id IS NULL AND l.categoria <> ?
                 AND COALESCE(l.sem_recorrencia, 0) = 0
           ORDER BY l.data, l.id, r.id""", (RETIRADA,)):
        item = achados.setdefault(x["id"], {
            "id": x["id"], "data": x["data"], "pago_em": x["pago_em"], "escopo": x["escopo"], "valor": x["valor"],
            "categoria": x["categoria"], "descricao": x["descricao"] or x["categoria"], "candidatos": []})
        item["candidatos"].append({"id": x["rid"], "descricao": x["rdescricao"], "valor": x["rvalor"],
                                   "dia_vencimento": x["dia_vencimento"], "casou_por": x["casou_por"], "ja_baixada": bool(x["ja_baixada"])})
    return list(achados.values())


def recorrencias_retirada(con: sqlite3.Connection) -> list:
    """Recorrências ativas cadastradas como Retirada: salário não é conta recorrente (usa 'Pagar salário')."""
    return con.execute("SELECT * FROM recorrencias WHERE excluido_em IS NULL AND categoria=? ORDER BY escopo, descricao",
                       (RETIRADA,)).fetchall()


def resumo_mes(con: sqlite3.Connection, mes: str, escopo: str = "PJ") -> dict:
    """Números do mês, só com lançamentos pagos. Fixo = saída vinda de recorrência fixa; o resto das saídas é variável."""
    soma = {}   # (tipo, fixo) -> total
    # salário da PJ para a PF: sai do lucro, não é custo do negócio (nem fixo, nem variável), venha de recorrência ou não.
    # Empréstimo (entrada) e a devolução (saída) também ficam fora: dinheiro emprestado não é receita nem custo
    for tipo, fixo, total in con.execute(
        """SELECT l.tipo, r.fixo, SUM(l.valor) FROM lancamentos l LEFT JOIN recorrencias r ON r.id = l.recorrencia_id
           WHERE l.escopo=? AND l.excluido_em IS NULL AND l.pago_em IS NOT NULL AND substr(l.data,1,7)=?
                 AND NOT (l.tipo='saida' AND l.categoria IN (?, ?)) AND NOT (l.tipo='entrada' AND l.categoria=?)
           GROUP BY l.tipo, r.fixo""", (escopo, mes, RETIRADA, DEVOLUCAO, EMPRESTIMO)):
        soma[(tipo, fixo)] = total
    retirada = con.execute("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE escopo=? AND tipo='saida' AND categoria=?
                              AND excluido_em IS NULL AND pago_em IS NOT NULL AND substr(data,1,7)=?""", (escopo, RETIRADA, mes)).fetchone()[0]
    emprestimos, devolucoes = (con.execute("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE escopo=? AND tipo=? AND categoria=?
                                              AND excluido_em IS NULL AND pago_em IS NOT NULL AND substr(data,1,7)=?""",
                                           (escopo, tipo, cat, mes)).fetchone()[0] for tipo, cat in (("entrada", EMPRESTIMO), ("saida", DEVOLUCAO)))
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
        "emprestimos": round(emprestimos, 2), "devolucoes": round(devolucoes, 2),
        "ponto_equilibrio": round(fixos / margem, 2) if margem > 0 and fixos > 0 else None,
        "das": round(db.parametros(con, "imposto").get("DAS", 0.06) * receita, 2),
        "pro_labore": round(pro_labore, 2), "inss": round(fiscal["inss_pct"] * pro_labore, 2),
        "pf": {"entradas": round(entradas, 2), "saidas": round(saidas, 2), "saldo": round(entradas - saidas, 2)},
    }


def mensalidades(con: sqlite3.Connection, mes: str) -> list[dict]:
    """Alunos ativos: previsto = clientes.valor; recebido = entradas PJ pagas do cliente no mês;
    abertos = entradas PJ do cliente no mês já lançadas e ainda sem baixa; falta = previsto − recebido − em aberto (nem foi lançado).
    Aluno que só começa depois do mês fica de fora. Situação: 'recebido' (recebido >= previsto), 'parcial' ou 'em aberto'."""
    abertos = {}
    for r in con.execute("""SELECT id, cliente_id, data, valor, descricao, categoria FROM lancamentos WHERE escopo='PJ' AND tipo='entrada'
                            AND excluido_em IS NULL AND pago_em IS NULL AND cliente_id IS NOT NULL AND substr(data,1,7)=? ORDER BY data, id""", (mes,)):
        abertos.setdefault(r["cliente_id"], []).append(dict(r))
    itens = []
    for c in con.execute(
        """SELECT c.id, c.nome, c.data_inicio, COALESCE(c.valor, 0) AS previsto,
                  (SELECT COALESCE(SUM(l.valor), 0) FROM lancamentos l WHERE l.cliente_id = c.id AND l.escopo='PJ' AND l.tipo='entrada'
                   AND l.excluido_em IS NULL AND l.pago_em IS NOT NULL AND substr(l.data,1,7)=?) AS recebido
           FROM clientes c WHERE c.excluido_em IS NULL AND c.status='ativo' ORDER BY c.nome""", (mes,)):
        ini = str(c["data_inicio"] or "").strip()[:10]
        if ISO_DATA.fullmatch(ini) and ini[:7] > mes:   # começa depois do mês: não deve nada nele
            continue
        previsto, recebido = round(c["previsto"], 2), round(c["recebido"], 2)
        if previsto <= 0 and recebido <= 0:
            continue
        sit = "recebido" if recebido >= previsto else ("parcial" if recebido > 0 else "em aberto")
        meus = abertos.get(c["id"], [])
        aberto = round(sum(a["valor"] for a in meus), 2)
        itens.append({"id": c["id"], "nome": c["nome"], "previsto": previsto, "recebido": recebido, "situacao": sit,
                      "abertos": meus, "aberto": aberto, "falta": round(max(previsto - recebido - aberto, 0), 2)})
    return itens


def entradas_sem_aluno(con: sqlite3.Connection, mes: str) -> list[dict]:
    """Entradas PJ do mês (pagas ou em aberto) sem aluno ligado. Podem ser o pagamento de alguém que aparece 'em aberto'
    nas mensalidades: a previsão as desconta do estimado e as telas pedem para ligar ao aluno.
    Empréstimo não entra: não é pagamento de aluno."""
    return [dict(r) for r in con.execute(
        """SELECT id, data, pago_em, valor, descricao, contraparte, categoria FROM lancamentos WHERE escopo='PJ' AND tipo='entrada'
           AND excluido_em IS NULL AND cliente_id IS NULL AND categoria != ? AND substr(data,1,7)=? ORDER BY data, id""",
        (EMPRESTIMO, mes))]


def parece_emprestimo(texto: str) -> bool:
    """O texto do lançamento fala de empréstimo? Só sugere: quem decide é o usuário (nunca troca a categoria sozinho)."""
    t = " ".join(_palavras(texto))
    return any(p in t for p in ("emprestimo", "capital de giro", "financiamento", "consignado"))


def _palavras(texto: str) -> list[str]:
    """Palavras sem acento e em minúsculas ('Giuliana Souza' -> ['giuliana', 'souza'])."""
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower())


def sugerir_aluno(texto: str, alunos) -> int | None:
    """Aluno que o texto do lançamento cita: nome completo, ou só o primeiro nome se um único aluno tiver esse primeiro nome.
    Na dúvida (dois candidatos) não sugere nada: quem confirma é o usuário."""
    palavras = set(_palavras(texto))
    completos, primeiros = [], []
    for a in alunos:
        nome = _palavras(a["nome"])
        if nome and set(nome) <= palavras:
            completos.append(a["id"])
        elif nome and len(nome[0]) >= 3 and nome[0] in palavras:
            primeiros.append(a["id"])
    if len(completos) == 1:
        return completos[0]
    return primeiros[0] if not completos and len(primeiros) == 1 else None


# ---------- Salário fixo PJ -> PF ----------
RETIRADA = "Retirada"
# Empréstimo da PJ (não emite nota): entra no caixa e paga contas, mas não é receita (não paga DAS, não é lucro, não é mensalidade)
EMPRESTIMO = "Empréstimo"
DEVOLUCAO = "Empréstimo (devolução)"


def _salario_parametros(con: sqlite3.Connection) -> tuple[float, int]:
    """(valor, dia de 1 a 31) do salário fixo; valor 0 = desligado."""
    p = db.parametros(con, "salario")
    return round(p.get("valor") or 0, 2), min(max(int(p.get("dia") or 5), 1), 31)


def _retiradas_mes(con: sqlite3.Connection, mes: str) -> list:
    """Retiradas PJ do mês (o salário), pagas ou em aberto: a do botão (origem SAL) e as lançadas à mão com data no mês.
    A do botão de outro mês (salário de setembro pago em outubro) não conta para outubro."""
    return con.execute("""SELECT valor, pago_em FROM lancamentos WHERE escopo='PJ' AND tipo='saida' AND excluido_em IS NULL
                          AND (origem=? OR (categoria=? AND substr(data,1,7)=? AND COALESCE(origem,'') NOT LIKE 'SAL:%'))""",
                       (f"SAL:{mes}:PJ", RETIRADA, mes)).fetchall()


def _salario_falta(con: sqlite3.Connection, mes: str, valor: float) -> float:
    """Quanto do salário do mês ainda não saiu da PJ nem foi lançado."""
    return round(max(valor - sum(r["valor"] for r in _retiradas_mes(con, mes)), 0), 2) if valor > 0 else 0.0


def salario_mes(con: sqlite3.Connection, mes: str, hoje: str) -> dict:
    """Salário do mês: valor e dia (parâmetros), se já foi pago (pelo botão ou Retirada à mão), se já pode pagar
    e quanto a PF já gastou do salário."""
    valor, dia = _salario_parametros(con)
    linhas = _retiradas_mes(con, mes)
    retirado = round(sum(r["valor"] for r in linhas), 2)
    falta = round(max(valor - retirado, 0), 2) if valor > 0 else 0.0
    pago_em = max(r["pago_em"] for r in linhas) if linhas and not falta and all(r["pago_em"] for r in linhas) else None
    gasto = con.execute("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE escopo='PF' AND tipo='saida' AND excluido_em IS NULL
                           AND pago_em IS NOT NULL AND substr(pago_em,1,7)=?""", (mes,)).fetchone()[0]
    data = vencimento(dia, mes)
    return {"mes": mes, "valor": valor, "dia": dia, "data": data, "ligado": valor > 0,
            "pago_em": pago_em, "retirado": retirado, "falta": falta, "pode_pagar": valor > 0 and not linhas and hoje >= data,
            "gasto_pf": round(gasto, 2), "pct_gasto": round(100 * gasto / valor) if valor > 0 else None,
            "sugestao": sugestao_salario(con, mes)}


def sugestao_salario(con: sqlite3.Connection, mes: str) -> float:
    """80% do lucro PJ médio dos 3 meses fechados antes de 'mes' (os 20% restantes vão para o colchão), em múltiplos de 50."""
    lucros = [resumo_mes(con, somar_meses(mes, -k))["lucro"] for k in (1, 2, 3)]
    media = sum(lucros) / 3
    return max(0, math.floor(0.8 * media / 50) * 50)


def pagar_salario(con: sqlite3.Connection, mes: str, pago_em: str) -> None:
    """Saída PJ (Retirada) + entrada PF (Salário) do mês, numa transação. ValueError se desligado ou já pago
    (pelo botão ou com Retirada lançada à mão no mês)."""
    valor = round(db.parametros(con, "salario").get("valor") or 0, 2)
    if valor <= 0:
        raise ValueError("Defina o valor do salário em Configurações.")
    if _retiradas_mes(con, mes):
        raise ValueError("O salário deste mês já foi pago (tem Retirada lançada no mês).")
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
    """Soma prevista das recorrências ativas do escopo na competência, sem a Retirada e sem o DAS
    (o DAS já sai do pote Imposto e, sem receita, não existe: não é conta a cobrir nem custo do colchão)."""
    return sum(r["valor"] for r in con.execute(
        f"""SELECT valor, descricao, categoria FROM recorrencias WHERE excluido_em IS NULL AND escopo=? AND categoria != ?
            AND inicio <= ? AND (fim IS NULL OR fim >= ?){' AND fixo=1' if so_fixos else ''}""", (escopo, RETIRADA, mes, mes))
        if not eh_das(r["descricao"], r["categoria"]))


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
        if e["categoria"] == EMPRESTIMO:   # empréstimo: sem imposto e tudo para as contas da PJ (é para isso que ele serve)
            div = {"imposto": 0.0, "contas": round(resto, 2), "salario": 0.0, "colchao": 0.0}
        else:
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
def _mensalidades_a_receber(con: sqlite3.Connection, mes: str) -> tuple[float, list[dict]]:
    """Quanto dos alunos ativos ainda falta lançar no mês (soma do 'falta' de cada aluno), menos as entradas PJ do mês sem aluno:
    se uma delas é o pagamento de quem aparece em aberto, contaria duas vezes. Na dúvida a previsão fica do lado seguro.
    Devolve (valor, entradas sem aluno)."""
    sem_aluno = entradas_sem_aluno(con, mes)
    falta = sum(m["falta"] for m in mensalidades(con, mes)) - sum(e["valor"] for e in sem_aluno)
    return round(max(falta, 0), 2), sem_aluno


def previsao(con: sqlite3.Connection, hoje: str, semanas: int = 13) -> dict:
    """Saldo previsto semana a semana, PF e PJ, a partir dos saldos digitados.
    Entra: tudo em aberto (lançamentos e recorrências), salário ainda não pago (sai da PJ, entra na PF),
    mensalidades que faltam receber (estimado, no dia previsao.dia_recebimento) e o DAS estimado
    (DAS% da receita do mês anterior, no dia previsao.dia_das, se o mês ainda não tem DAS lançado; ver eh_das).
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
    sal_valor, sal_dia = _salario_parametros(con)
    itens = [dict(i, estimado=False) for i in em_aberto_ate(con, fim, hoje)]

    def add(escopo, tipo, data, descricao, valor, estimado=True):
        if valor > 0 and data <= fim:
            itens.append({"escopo": escopo, "tipo": tipo, "data": max(data, hoje), "descricao": descricao,
                          "categoria": "", "valor": round(valor, 2), "estimado": estimado})

    receita = {}   # receita PJ esperada por mês (recebida + a receber), base do DAS do mês seguinte
    sem_aluno = []   # entradas PJ sem aluno descontadas do estimado: a tela pede para ligar ao aluno
    for mes in meses:
        recebido = _receita_pj(con, mes)
        falta, sem = _mensalidades_a_receber(con, mes)
        sem_aluno += [dict(e, mes=mes) for e in sem]
        abertas = sum(i["valor"] for i in itens if i["escopo"] == "PJ" and i["tipo"] == "entrada" and i["data"][:7] == mes
                      and i["categoria"] != EMPRESTIMO)
        receita[mes] = recebido + falta + abertas
        add("PJ", "entrada", vencimento(int(par.get("dia_recebimento") or 10), mes), "Mensalidades a receber", falta)
        # salário: só o que falta tirar da PJ (Retirada à mão também vale); a entrada na PF não volta se ela já está lançada
        falta_sal = _salario_falta(con, mes, sal_valor)
        if falta_sal:
            data = vencimento(sal_dia, mes)
            add("PJ", "saida", data, "Salário para a PF", falta_sal, estimado=False)
            if not con.execute("SELECT 1 FROM lancamentos WHERE origem=? AND excluido_em IS NULL", (f"SAL:{mes}:PF",)).fetchone():
                add("PF", "entrada", data, "Salário da PJ", falta_sal, estimado=False)
        # DAS: com DAS de verdade no mês (pago ou em aberto), nada a estimar; recorrência de DAS só conta o que ela prevê
        real, previsto = _das_do_mes(con, mes, itens)
        if not real:
            anterior = somar_meses(mes, -1)
            base = receita.get(anterior)
            if base is None:   # mês anterior a hoje: só o que entrou de fato
                base = _receita_pj(con, anterior)
            add("PJ", "saida", vencimento(int(par.get("dia_das") or 20), mes),
                f"DAS estimado ({anterior[5:]}/{anterior[:4]}){' além do previsto' if previsto else ''}", das_pct * base - previsto)

    livre = saldo_livre(con, hoje)
    saldo = {f: livre[f]["tem"] for f in ("PF", "PJ")}
    linhas, aperto = [], {}
    # pior dia: o saldo é seguido dia a dia, não só no fim da semana (um buraco entre dois recebimentos aparece)
    menor_dia = {f: {"saldo": round(saldo[f], 2), "data": hoje} for f in ("PF", "PJ")}
    for f in ("PF", "PJ"):
        if saldo[f] < 0:
            aperto[f] = {"inicio": hoje, "saldo": round(saldo[f], 2)}
    for k in range(semanas):
        ini = (h + dt.timedelta(days=7 * k)).isoformat()
        fim_sem = (h + dt.timedelta(days=7 * k + 6)).isoformat()
        da_semana = sorted((i for i in itens if (i["data"] <= fim_sem and (k == 0 or i["data"] >= ini))), key=lambda i: i["data"])
        linha = {"inicio": ini, "fim": fim_sem, "itens": da_semana}
        for f in ("PF", "PJ"):
            ent = sum(i["valor"] for i in da_semana if i["escopo"] == f and i["tipo"] == "entrada")
            sai = sum(i["valor"] for i in da_semana if i["escopo"] == f and i["tipo"] == "saida")
            pior = None   # (saldo, dia) do pior fim de dia da semana; atrasado conta em "hoje"
            por_dia = {}
            for i in da_semana:
                if i["escopo"] == f:
                    por_dia[max(i["data"], hoje)] = por_dia.get(max(i["data"], hoje), 0) + (i["valor"] if i["tipo"] == "entrada" else -i["valor"])
            for dia in sorted(por_dia):
                saldo[f] += por_dia[dia]
                if pior is None or saldo[f] < pior[0]:
                    pior = (round(saldo[f], 2), dia)
                if saldo[f] < 0 and f not in aperto:
                    aperto[f] = {"inicio": dia, "saldo": round(saldo[f], 2)}
                if saldo[f] < menor_dia[f]["saldo"]:
                    menor_dia[f] = {"saldo": round(saldo[f], 2), "data": dia}
            linha[f] = {"entradas": round(ent, 2), "saidas": round(sai, 2), "saldo": round(saldo[f], 2),
                        "pior": {"saldo": pior[0], "data": pior[1]} if pior and pior[0] < 0 else None}
        linha["negativo"] = any(linha[f]["pior"] for f in ("PF", "PJ"))
        linhas.append(linha)
    menor = {f: menor_dia[f]["saldo"] for f in ("PF", "PJ")}
    return {"semanas": linhas, "aperto": aperto, "menor": menor, "menor_dia": menor_dia, "inicio": {f: livre[f]["tem"] for f in ("PF", "PJ")},
            "sem_saldo": {f: livre[f]["sem_saldo"] for f in ("PF", "PJ")}, "fim": fim,
            "dias_velho": {f: livre[f]["dias_velho"] for f in ("PF", "PJ")},
            "desatualizado": {f: livre[f]["desatualizado"] for f in ("PF", "PJ")}, "sem_frente": livre["sem_frente"],
            "sem_aluno": sem_aluno, "sem_aluno_total": round(sum(e["valor"] for e in sem_aluno), 2)}
