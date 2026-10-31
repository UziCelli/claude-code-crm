"""Financeiro PF + PJ — lógica pura sobre lancamentos e recorrencias. Datas ISO (AAAA-MM-DD), competência AAAA-MM."""
import calendar
import datetime as dt
import math
import re
import sqlite3
import unicodedata
from urllib.parse import urlencode

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
                      "conta": r["conta"], "status": status(r, hoje)})
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
                      "prioridade": r["prioridade"], "status": status({"pago_em": None, "data": data}, hoje)})
    return itens


# ---------- Saldo livre ----------
FRENTES = ("PF", "PJ", "Reserva", "Fora")   # Reserva = dinheiro guardado (fica fora do livre); Fora = cartão, não guarda dinheiro
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
    for r in con.execute("""SELECT l.*, rc.prioridade AS prioridade FROM lancamentos l LEFT JOIN recorrencias rc ON rc.id = l.recorrencia_id
                            WHERE (l.pago_em IS NULL OR l.pago_em > ?) AND l.excluido_em IS NULL
                            AND COALESCE(l.pago_em, l.data) <= ?""", (hoje, ate)):
        data = r["pago_em"] or r["data"]
        itens.append({"origem": "lancamento", "id": r["id"], "escopo": r["escopo"], "tipo": r["tipo"], "data": data,
                      "descricao": r["descricao"] or r["categoria"], "categoria": r["categoria"], "valor": r["valor"],
                      "prioridade": r["prioridade"], "status": status({"pago_em": None, "data": data}, hoje)})
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


def moeda_br(v: float) -> str:
    """'R$ 1.234,50' (negativo: '−R$ 50,00'), igual ao filtro moeda das telas."""
    v = round(float(v), 2) + 0.0
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"−R$ {s}" if v < 0 else f"R$ {s}"


def pct_das(con: sqlite3.Connection) -> float:
    """DAS% das Configurações, como fração (0,06 = 6%)."""
    return db.parametros(con, "imposto").get("DAS", 0.06)


def texto_pct(fracao: float) -> str:
    """0,06 -> '6'; 0,045 -> '4,5'."""
    return f"{fracao * 100:g}".replace(".", ",")


def imposto_mes(con: sqlite3.Connection, mes: str, hoje: str | None = None, abertos: list[dict] | None = None) -> float:
    """Imposto (DAS) a separar da receita PJ recebida em `mes`: DAS% × entradas pagas, sem empréstimo. Esse DAS vence no mês
    seguinte. Menos o que a recorrência de DAS já prevê; 0 se o DAS desse vencimento já está lançado ou pago.
    É a única conta do imposto: o saldo_livre soma estes valores e a tela mostra o do mês de hoje.
    `abertos`: saídas em aberto (o saldo_livre já tem); sem elas, usa as dos próximos 30 dias a partir de `hoje`."""
    if abertos is None:
        hoje = hoje or dt.date.today().isoformat()
        ate = (dt.date.fromisoformat(hoje) + dt.timedelta(days=30)).isoformat()
        abertos = [i for i in em_aberto_ate(con, ate, hoje) if i["tipo"] == "saida"]
    return round(_das_a_guardar(con, somar_meses(mes, 1), abertos, _receita_pj(con, mes), pct_das(con)), 2)


def aviso_imposto(con: sqlite3.Connection, valor: float) -> str:
    """'Separe R$ 60,00 para o imposto (DAS 6%).' ao receber uma entrada PJ; vazio se o DAS está em 0%."""
    pct = pct_das(con)
    return f"Separe {moeda_br(round(pct * valor, 2))} para o imposto (DAS {texto_pct(pct)}%)." if pct > 0 and valor > 0 else ""


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
    Imposto a guardar = imposto_mes deste mês (DAS do mês que vem) + o do mês passado (DAS deste mês), enquanto não for
    lançado. DAS já em aberto está no comprometido e não conta duas vezes.
    Salário: o que falta tirar da PJ em cada salário que vence até hoje+dias (deste mês em diante)."""
    ate = (dt.date.fromisoformat(hoje) + dt.timedelta(days=dias)).isoformat()
    saldos = saldos_atuais(con)
    abertos = [i for i in em_aberto_ate(con, ate, hoje) if i["tipo"] == "saida"]
    mes = hoje[:7]
    dias_das = {mes: imposto_mes(con, somar_meses(mes, -1), abertos=abertos),
                somar_meses(mes, 1): imposto_mes(con, mes, abertos=abertos)}
    das = sum(dias_das.values())
    sal_valor, sal_dia = _salario_parametros(con)
    salario, m, salarios = 0.0, mes, {}
    while m <= ate[:7]:
        if vencimento(sal_dia, m) <= ate:
            salarios[m] = _salario_falta(con, m, sal_valor)
            salario += salarios[m]
        m = somar_meses(m, 1)
    out = {}
    for frente in ("PF", "PJ"):
        contas = {c: v for c, v in saldos.items() if v["escopo"] == frente}
        datas = [v["data"] for v in contas.values() if v["data"]]
        tem = _tem(con, contas, frente, hoje)
        comprometido = sum(i["valor"] for i in abertos if i["escopo"] == frente)
        imposto, sal = (das, salario) if frente == "PJ" else (0, 0)
        extras = _itens_virtuais(con, hoje, dias_das, salarios) if frente == "PJ" else []
        dias_velho = (dt.date.fromisoformat(hoje) - dt.date.fromisoformat(min(datas))).days if datas else None
        out[frente] = {
            "tem": round(tem, 2), "comprometido": round(comprometido, 2), "imposto": round(imposto, 2), "salario": round(sal, 2),
            "livre": round(tem - comprometido - imposto - sal, 2), "ate": ate,
            "itens": [i for i in abertos if i["escopo"] == frente], "extras": extras,   # extras: DAS a guardar e salário (fila de pagamento)
            "sem_saldo": not datas,   # nenhuma conta da frente com saldo digitado: o número não vale
            "dias_velho": dias_velho, "desatualizado": dias_velho is not None and dias_velho > DIAS_SALDO_VELHO,
        }
    out["reserva"] = round(sum(v["saldo"] for v in saldos.values() if v["escopo"] == "Reserva" and v["saldo"] is not None), 2)
    out["sem_frente"] = [c for c, v in saldos.items() if v["escopo"] is None]
    return out


def _itens_virtuais(con: sqlite3.Connection, hoje: str, das: dict, salarios: dict) -> list[dict]:
    """O que o saldo livre separa sem ser uma conta lançada: o DAS a guardar (por mês) e o salário ainda não tirado da PJ.
    Entram na fila de pagamento como os outros itens."""
    dia_das = int(db.parametros(con, "previsao").get("dia_das") or 20)
    sal_dia = _salario_parametros(con)[1]
    out = []
    for comp, valor in das.items():
        if valor > 0:
            data = vencimento(dia_das, comp)
            out.append({"origem": "virtual", "id": None, "escopo": "PJ", "tipo": "saida", "data": data, "valor": round(valor, 2),
                        "descricao": f"Guardar o DAS de {comp[5:]}/{comp[:4]}", "categoria": "Impostos/Taxas", "prioridade": None,
                        "status": status({"pago_em": None, "data": data}, hoje)})
    for comp, valor in salarios.items():
        if valor > 0:
            data = vencimento(sal_dia, comp)
            out.append({"origem": "virtual", "id": None, "escopo": "PJ", "tipo": "saida", "data": data, "valor": round(valor, 2),
                        "descricao": f"Salário {comp[5:]}/{comp[:4]} para a PF", "categoria": RETIRADA, "prioridade": None,
                        "status": status({"pago_em": None, "data": data}, hoje)})
    return out


# ---------- Fila de pagamento ----------
IMPACTO_PADRAO = (20, 0.02)   # categoria sem padrão: do lado seguro (nem some da fila, nem manda em tudo)


def nota_impacto(item: dict, curto: dict, juros: dict, hoje: str) -> dict:
    """Nota de quanto pagar esta conta já pesa, somando:
    curto prazo (0 a 40, parâmetro impacto_curto: o que acontece se atrasar agora) + urgência (atrasada +10, vence em até 3 dias +7,
    em até 7 dias +4) + longo prazo (3 × juros e multa por mês em pontos percentuais, no máximo 50; parâmetro impacto_juros)
    + escolha manual (prioridade da conta recorrente: sempre primeiro +100, pode esperar −100).
    Devolve a nota, o custo em R$ de atrasar 1 mês e o motivo em poucas palavras."""
    chave = f"{item['escopo']} {item['categoria']}"
    c = curto.get(chave, IMPACTO_PADRAO[0])
    j = juros.get(chave, IMPACTO_PADRAO[1])
    dias = _dias_com_sinal(item["data"], hoje)
    urgencia = 10 if dias < 0 else 7 if dias <= 3 else 4 if dias <= 7 else 0
    longo = min(50, round(300 * j))
    manual = 100 * (item.get("prioridade") or 0)
    motivo = []
    if manual:
        motivo.append("você pediu: primeiro" if manual > 0 else "você disse: pode esperar")
    if c >= 40:
        motivo.append("essencial")
    if j >= 0.08:
        motivo.append(f"multa alta (~{round(100 * j)}%/mês)")
    elif j >= 0.02:
        motivo.append("tem multa")
    motivo.append("atrasada há %d dia%s" % (-dias, "s" if dias < -1 else "") if dias < 0 else "vence hoje" if dias == 0
                  else "vence amanhã" if dias == 1 else f"vence em {dias} dias" if dias <= 7 else "")
    if not manual and c < 20 and j < 0.02:
        motivo.append("pode esperar")
    return {"nota": c + urgencia + longo + manual, "custo_atraso": round(item["valor"] * j, 2),
            "motivo": " · ".join(m for m in motivo if m)[:140]}


def _dias_com_sinal(data: str, hoje: str) -> int:
    """Dias de hoje até a data (negativo = já passou). Data inválida conta como longe, sem urgência."""
    try:
        return (dt.date.fromisoformat(data) - dt.date.fromisoformat(hoje)).days
    except (TypeError, ValueError):
        return 10_000


def fila_pagamentos(con: sqlite3.Connection, livre: dict, hoje: str) -> dict:
    """Em que ordem pagar, por frente (PF e PJ), a partir do resultado de saldo_livre.
    Ordena o que está comprometido (contas em aberto, DAS a guardar e salário a tirar) pela nota de impacto e vai gastando o 'tem':
    cada item vem com 'coberto' (o dinheiro dá) e, no primeiro que não cabe, a fila corta: dali para baixo falta dinheiro,
    mesmo que sobre troco para um item pequeno (o dinheiro vai para o que pesa mais).
    Devolve {frente: {itens, cobertos, tudo_coberto, sobra}}; sem saldo digitado ninguém é dado como coberto."""
    curto, juros = db.parametros(con, "impacto_curto"), db.parametros(con, "impacto_juros")
    semana = (dt.date.fromisoformat(hoje) + dt.timedelta(days=7)).isoformat()
    out = {}
    for f in ("PF", "PJ"):
        l = livre[f]
        itens = [dict(i) for i in l["itens"] + l.get("extras", [])]
        for i in itens:
            i.update(nota_impacto(i, curto, juros, hoje))
        itens.sort(key=lambda i: (-i["nota"], i["data"], -i["valor"]))
        resto, cortou = l["tem"], l["sem_saldo"]
        for i in itens:
            i["coberto"] = not cortou and resto + 0.005 >= i["valor"]
            if i["coberto"]:
                resto -= i["valor"]
            else:
                cortou = True
            i["esta_semana"] = i["coberto"] and i["data"] <= semana
        out[f] = {"itens": itens, "cobertos": sum(i["coberto"] for i in itens), "sem_saldo": l["sem_saldo"],
                  "tudo_coberto": bool(itens) and all(i["coberto"] for i in itens), "sobra": round(max(resto, 0), 2)}
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


JANELA_REPETIDO = 3   # dias entre dois lançamentos iguais para ainda parecerem o mesmo


def _dias_entre(a: str, b: str) -> int:
    """Dias entre duas datas ISO; data inválida nunca é "perto" (a tela não pode quebrar por causa de uma linha ruim)."""
    try:
        return abs((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days)
    except (TypeError, ValueError):
        return 10_000


def _mesma_descricao(a: dict, b: dict) -> bool:
    """Descrições iguais sem acento nem maiúscula (vazia não conta: não diz nada)."""
    pa, pb = _palavras(a["descricao"]), _palavras(b["descricao"])
    return bool(pa) and pa == pb


def _diferentes(a, b) -> bool:
    """Os dois campos estão preenchidos e não batem (campo vazio não prova nada)."""
    return a not in (None, "") and b not in (None, "") and a != b


def _pode_ser_o_mesmo(x: dict, y: dict) -> bool:
    """Dois lançamentos de mesmo escopo, tipo e valor que nada separa: parcela, aluno, conta, quem pagou e conta recorrente
    diferentes provam que são dois lançamentos de verdade."""
    if any(_diferentes(x[k], y[k]) for k in ("parcela_num", "cliente_id", "conta", "recorrencia_id")):
        return False
    if x["recorrencia_id"] and x["recorrencia_id"] == y["recorrencia_id"] and x["competencia"] != y["competencia"]:
        return False
    if (x["sem_recorrencia"] and y["recorrencia_id"]) or (y["sem_recorrencia"] and x["recorrencia_id"]):
        return False   # "não é a mesma conta" já foi respondido para este par
    return not _diferentes(_palavras(x["contraparte"]) or None, _palavras(y["contraparte"]) or None)


def duplicados(con: sqlite3.Connection) -> list[dict]:
    """Grupos de lançamentos que parecem o mesmo lançamento feito duas vezes (digitado e importado, ou lançado em dobro).
    Parecido = mesmo escopo, tipo e valor, com datas (pago_em, ou a data) até JANELA_REPETIDO dias uma da outra, sem nada que os
    distinga (ver _pode_ser_o_mesmo). Pares já marcados "não é repetido" e saídas que já aparecem em saidas_parecidas ficam fora.
    Só sugere: quem exclui é o usuário. Três cópias viram um grupo só.
    Cada grupo: {ids, certeza ('quase certo' = mesma data e mesma descrição; senão 'talvez'), manter (id), itens (o 'manter' primeiro)}."""
    ok = {(r["a"], r["b"]) for r in con.execute("SELECT a, b FROM duplicados_ok")}
    ja_avisadas = {s["id"] for s in saidas_parecidas(con)}
    linhas = [dict(r) for r in con.execute(
        """SELECT l.*, COALESCE(l.pago_em, l.data) AS quando, c.nome AS aluno FROM lancamentos l
           LEFT JOIN clientes c ON c.id = l.cliente_id WHERE l.excluido_em IS NULL AND l.categoria != ?
           ORDER BY l.escopo, l.tipo, ROUND(l.valor * 100), quando, l.id""", (RETIRADA,))]
    pai = {l["id"]: l["id"] for l in linhas}

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    for k, x in enumerate(linhas):
        for j in range(k + 1, len(linhas)):
            y = linhas[j]
            if (x["escopo"], x["tipo"], round(x["valor"] * 100)) != (y["escopo"], y["tipo"], round(y["valor"] * 100)):
                break   # ordenado por escopo, tipo e valor: o resto é de outro grupo
            if _dias_entre(x["quando"], y["quando"]) > JANELA_REPETIDO:
                break
            if (x["id"], y["id"]) in ok or x["id"] in ja_avisadas or y["id"] in ja_avisadas or not _pode_ser_o_mesmo(x, y):
                continue
            pai[raiz(y["id"])] = raiz(x["id"])
    grupos: dict[int, list[dict]] = {}
    for l in linhas:
        grupos.setdefault(raiz(l["id"]), []).append(l)

    def peso(l):   # o que se mantém: ligado a conta recorrente, aluno ou baixa; depois o mais completo; empate: o mais antigo
        campos = sum(l[k] not in (None, "") for k in ("descricao", "contraparte", "conta", "forma", "cliente_id", "observacao"))
        return (sum(l[k] is not None for k in ("recorrencia_id", "cliente_id", "pago_em")), campos, -l["id"])

    out = []
    for g in grupos.values():
        if len(g) < 2:
            continue
        manter = max(g, key=peso)
        resto = sorted((l for l in g if l is not manter), key=lambda l: (l["quando"], l["id"]))
        quase = all(l["quando"] == manter["quando"] and _mesma_descricao(l, manter) for l in resto)
        out.append({"ids": [l["id"] for l in [manter, *resto]], "manter": manter["id"], "certeza": "quase certo" if quase else "talvez",
                    "valor": manter["valor"], "escopo": manter["escopo"], "tipo": manter["tipo"],
                    "itens": [dict(l, manter=l is manter) for l in [manter, *resto]]})
    out.sort(key=lambda g: g["itens"][0]["quando"], reverse=True)   # mais recentes primeiro...
    out.sort(key=lambda g: g["certeza"] != "quase certo")             # ...e os quase certos antes dos "talvez"
    return out


# ---------- Conferir com o banco e linha do tempo ----------
def _dd_mm(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


def _fotos_conferidas(con: sqlite3.Connection) -> dict:
    """{conta: (data da foto, saldo)} que você marcou como 'Está certo'. Vale só para aquela foto."""
    return {r["chave"]: (r["valor_texto"], r["valor"]) for r in con.execute(
        "SELECT chave, valor, valor_texto FROM parametros WHERE grupo='conferencia_ok'")}


def marcar_conferido(con: sqlite3.Connection, conta: str) -> None:
    """'Está certo': a conta some do Banco × CRM até você digitar um saldo novo. ValueError se a conta não tem saldo digitado."""
    foto = con.execute("SELECT saldo, data FROM saldos WHERE conta=? AND excluido_em IS NULL ORDER BY data DESC, id DESC LIMIT 1",
                       (conta,)).fetchone()
    if foto is None:
        raise ValueError("Essa conta não tem saldo digitado.")
    with con:
        con.execute("""INSERT INTO parametros (grupo, chave, valor, valor_texto, ordem) VALUES ('conferencia_ok', ?, ?, ?,
                       (SELECT COALESCE(MAX(ordem), 0) + 1 FROM parametros WHERE grupo='conferencia_ok'))
                       ON CONFLICT (grupo, chave) DO UPDATE SET valor=excluded.valor, valor_texto=excluded.valor_texto""",
                    (conta, foto["saldo"], foto["data"]))


def conferencia_contas(con: sqlite3.Connection, repetidos: list[dict] | None = None) -> list[dict]:
    """Banco × CRM, uma linha por conta com pelo menos 2 fotos de saldo (cartão fica de fora).
    esperado = saldo da foto anterior + entradas − saídas pagas nessa conta depois dela, até a foto mais nova;
    diferença = saldo que você digitou − esperado. Zero = o CRM tem tudo que mexeu na conta.
    Conta marcada 'Está certo' fica de fora até haver uma foto mais nova (ver marcar_conferido).
    Cada linha traz o texto pronto: 'resumo' e uma 'causa' provável (saldo zero digitado; lançamento repetido; lançamentos pagos
    sem conta; senão falta entrada ou saída), mais os links 'lancar_url' (Novo lançamento já preenchido) e 'ver_url' (livro-caixa da conta).
    `repetidos`: o resultado de duplicados(), se quem chama já o tem (a conta é cara)."""
    frentes = frentes_contas(con)
    fotos: dict[str, list] = {}
    for r in con.execute("SELECT conta, saldo, data FROM saldos WHERE excluido_em IS NULL ORDER BY data, id"):
        fotos.setdefault(r["conta"], []).append(r)
    conferidas = _fotos_conferidas(con)
    out = []
    for conta, lista in fotos.items():
        frente = frentes.get(conta)
        if len(lista) < 2 or frente == "Fora":
            continue
        antes, depois = lista[-2], lista[-1]
        if antes["data"] == depois["data"] or conferidas.get(conta) == (depois["data"], depois["saldo"]):
            continue
        mov = {tipo: total for tipo, total in con.execute(
            """SELECT tipo, COALESCE(SUM(valor), 0) FROM lancamentos WHERE excluido_em IS NULL AND conta=? AND pago_em > ? AND pago_em <= ?
               GROUP BY tipo""", (conta, antes["data"], depois["data"]))}
        entradas, saidas = round(mov.get("entrada", 0), 2), round(mov.get("saida", 0), 2)
        esperado = round(antes["saldo"] + entradas - saidas, 2)
        dif = round(depois["saldo"] - esperado, 2)
        sem_conta = con.execute(
            """SELECT COUNT(*) FROM lancamentos WHERE excluido_em IS NULL AND conta IS NULL AND escopo=? AND pago_em > ? AND pago_em <= ?""",
            (frente, antes["data"], depois["data"])).fetchone()[0] if frente in ("PF", "PJ") else 0
        suspeito = None
        if abs(dif) >= 0.01:
            if repetidos is None:
                repetidos = duplicados(con)
            for g in repetidos:   # saída em dobro deixa o banco com MAIS que o esperado; entrada em dobro, com menos
                extras = len(g["itens"]) - 1
                if (g["tipo"] == "saida") == (dif > 0) and abs(abs(dif) - extras * g["valor"]) < 0.01 and any(
                        i["conta"] == conta and i["pago_em"] and antes["data"] < i["pago_em"] <= depois["data"] for i in g["itens"]):
                    suspeito = {"valor": g["valor"], "descricao": g["itens"][0]["descricao"] or g["itens"][0]["categoria"], "ids": g["ids"]}
                    break
        bate, zero = abs(dif) < 0.01, depois["saldo"] == 0
        if bate:
            causa = ""
        elif zero:   # 0 digitado quase sempre é campo não preenchido
            causa = f"Você digitou {moeda_br(0)} — foi isso mesmo?"
        elif suspeito:
            causa = f'Pode ser o lançamento repetido "{suspeito["descricao"]}" de {moeda_br(suspeito["valor"])} (veja em "Pode estar repetido").'
        elif sem_conta:
            causa = (f"{sem_conta} lançamentos pagos sem conta podem explicar." if sem_conta > 1
                     else "1 lançamento pago sem conta pode explicar.")
        elif dif > 0:
            causa = f"Falta lançar uma entrada de {moeda_br(dif)}."
        else:
            causa = f"Falta lançar uma saída de {moeda_br(-dif)}, ou tem entrada a mais."
        # Novo lançamento já preenchido, na data da foto: assim ele entra na conta que está sendo conferida
        lancar = urlencode({"novo": 1, "conta": conta, "tipo": "entrada" if dif > 0 else "saida", "escopo": "PJ" if frente == "PJ" else "PF",
                            "valor": f"{abs(dif):.2f}".replace(".", ","), "data": depois["data"],
                            "descricao": f"Diferença do saldo de {_dd_mm(depois['data'])} ({conta})"})
        out.append({"conta": conta, "frente": frente, "de": antes["data"], "ate": depois["data"], "saldo_antes": antes["saldo"],
                    "saldo_depois": depois["saldo"], "entradas": entradas, "saidas": saidas, "esperado": esperado, "diferenca": dif,
                    "bate": bate, "zero": zero, "sem_conta": sem_conta, "repetido": suspeito, "causa": causa,
                    "resumo": f"{conta}: você digitou {moeda_br(depois['saldo'])} em {_dd_mm(depois['data'])}. "
                              f"Pelos lançamentos, devia ter {moeda_br(esperado)}. Diferença: {moeda_br(dif)}.",
                    "lancar_url": f"/financeiro?{lancar}",
                    "ver_url": f"/financeiro?{urlencode({'conta': conta, 'mes': depois['data'][:7]})}"})
    out.sort(key=lambda c: (c["bate"], c["conta"]))   # o que não bate primeiro
    return out


DIAS_SEMANA = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def linha_do_tempo(con: sqlite3.Connection, hoje: str, dias: int = 30, conta: str | None = None) -> dict:
    """O que aconteceu nos últimos `dias`, do mais novo ao mais antigo e agrupado por dia: lançamentos pagos e as fotos de saldo
    (marcos). Cada movimento vem com etiquetas: empréstimo, repetido?, sem conta. `conta` filtra por conta."""
    h = dt.date.fromisoformat(hoje)
    de = (h - dt.timedelta(days=dias)).isoformat()
    ids_repetidos = {i for g in duplicados(con) for i in g["ids"]}
    filtro, args = (" AND conta=?", (conta,)) if conta else ("", ())
    por_dia: dict[str, list[dict]] = {}
    for r in con.execute(f"""SELECT * FROM lancamentos WHERE excluido_em IS NULL AND pago_em >= ? AND pago_em <= ?{filtro}
                             ORDER BY pago_em DESC, id DESC""", (de, hoje, *args)):
        por_dia.setdefault(r["pago_em"], []).append({
            "tipo": r["tipo"], "valor": r["valor"], "escopo": r["escopo"], "id": r["id"], "conta": r["conta"],
            "descricao": r["descricao"] or r["categoria"], "categoria": r["categoria"],
            "etiquetas": [t for t, ok in (
                ("empréstimo", r["categoria"].startswith(EMPRESTIMO)),
                ("parece empréstimo", r["escopo"] == "PJ" and r["tipo"] == "entrada" and not r["categoria"].startswith(EMPRESTIMO)
                 and parece_emprestimo(f"{r['descricao'] or ''} {r['contraparte'] or ''}")),
                ("repetido?", r["id"] in ids_repetidos), ("sem conta", not r["conta"])) if ok]})
    for r in con.execute(f"""SELECT * FROM saldos WHERE excluido_em IS NULL AND data >= ? AND data <= ?{filtro}
                             ORDER BY data DESC, id DESC""", (de, hoje, *args)):
        por_dia.setdefault(r["data"], []).insert(0, {"tipo": "saldo", "valor": r["saldo"], "conta": r["conta"], "escopo": None, "id": None,
                                                     "descricao": f"Saldo digitado: {r['conta']}", "categoria": "", "etiquetas": []})
    def rotulo(iso):
        d = dt.date.fromisoformat(iso)
        return "Hoje" if d == h else "Ontem" if d == h - dt.timedelta(days=1) else f"{DIAS_SEMANA[d.weekday()]} {d:%d/%m}"
    contas = [r[0] for r in con.execute(
        """SELECT conta FROM lancamentos WHERE excluido_em IS NULL AND conta IS NOT NULL AND pago_em >= ?
           UNION SELECT conta FROM saldos WHERE excluido_em IS NULL AND data >= ? ORDER BY 1""", (de, de))]
    return {"de": de, "ate": hoje, "dias": dias, "conta": conta, "contas": contas,
            "dias_lista": [{"dia": d, "rotulo": rotulo(d), "itens": por_dia[d]} for d in sorted(por_dia, reverse=True)]}


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
    Aluno que só começa depois do mês fica de fora. Qualquer pagamento quita o mês: recebido > 0 é 'recebido' com falta 0
    (os abertos dele ficam listados com quitado=True e não contam como a receber); senão 'em aberto'.
    Mês pulado (evento 'pausa' da ficha, sem cobrança): previsto 0 e situação 'pulou o mês'."""
    abertos = {}
    for r in con.execute("""SELECT id, cliente_id, data, valor, descricao, categoria, conta FROM lancamentos WHERE escopo='PJ' AND tipo='entrada'
                            AND excluido_em IS NULL AND pago_em IS NULL AND cliente_id IS NOT NULL AND substr(data,1,7)=? ORDER BY data, id""", (mes,)):
        abertos.setdefault(r["cliente_id"], []).append(dict(r))
    pulados = {r[0] for r in con.execute("""SELECT DISTINCT cliente_id FROM cliente_eventos WHERE tipo='pausa' AND excluido_em IS NULL
                                            AND substr(data,1,7)=?""", (mes,))}
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
        pulou = c["id"] in pulados
        if previsto <= 0 and recebido <= 0:
            continue
        if pulou:   # combinou de pular o mês: não deve nada nele (se pagou mesmo assim, aparece como recebido)
            previsto = 0.0
        if pulou and recebido <= 0:
            sit = "pulou o mês"
        else:
            sit = "recebido" if recebido > 0 else "em aberto"
        quitado = recebido > 0
        meus = abertos.get(c["id"], [])
        aberto = 0.0 if quitado else round(sum(a["valor"] for a in meus), 2)
        itens.append({"id": c["id"], "nome": c["nome"], "previsto": previsto, "recebido": recebido, "situacao": sit,
                      "abertos": meus, "aberto": aberto, "quitado": quitado,
                      "falta": 0.0 if quitado else round(max(previsto - recebido - aberto, 0), 2)})
    return itens


# ---------- Renovação dos alunos ----------
ANTECEDENCIA = 7   # dias: pagamento ou renovação lançados até 7 dias antes do vencimento já valem para ele
CHEIO = 0.9        # pagamento de 90% do valor mensal ou mais é mês inteiro (taxa do cartão, desconto combinado)
CONFIRMA = 15      # Renovação marcada até 15 dias depois de renovar, antes do vencimento seguinte, só confirma a renovação


def proxima_renovacao(data: str, n: int = 1) -> str:
    """A data mais n meses, sempre no mesmo dia (dia 31 vira o último dia nos meses curtos)."""
    return vencimento(int(data[8:10]), somar_meses(data[:7], n))


def _dias_antes(data: str, dias: int) -> str:
    return (dt.date.fromisoformat(data) - dt.timedelta(days=dias)).isoformat()


def renovacoes(con: sqlite3.Connection, cliente_id: int | None = None) -> dict[int, dict]:
    """Renovação efetiva de cada aluno: {cliente_id: {gravada, efetiva, ciclos, falta, pendente, motivo, motivo_data}}. Não grava nada.
    Parte da data de renovação do cadastro e anda um mês a cada:
      - pagamento do aluno (entrada PJ paga ligada a ele; o evento antigo 'pagamento' da ficha também vale, uma vez por mês);
      - Renovação marcada no histórico, se o próximo vencimento está a até 7 dias (ou já passou);
      - mês pulado ('pausa').
    Pagamento parcial também renova e dá baixa total no mês (nada fica devendo): pagamento menor que um mês, perto do vencimento,
    anda um mês com falta 0; o seguinte conta como qualquer outro pagamento.
    Renovação marcada sem pagamento fica pendente (falta = valor): o pagamento seguinte é dela, mesmo parcial, e quita (não anda outro mês).
    Valor de 2 mensalidades de uma vez anda 2 meses. Pagamento pequeno longe do vencimento (aula extra, taxa) não renova.
    Só conta o que é de até 7 dias antes da data gravada em diante e, se a data foi trocada à mão (renovacao_em),
    só o que foi lançado depois da troca."""
    filtro, args = ("AND id=?", (cliente_id,)) if cliente_id else ("", ())
    alunos = con.execute(f"""SELECT id, valor, data_renovacao, renovacao_em FROM clientes WHERE excluido_em IS NULL
                             AND data_renovacao IS NOT NULL {filtro}""", args).fetchall()
    filtro = "AND cliente_id=?" if cliente_id else "AND cliente_id IS NOT NULL"
    pagos, eventos = {}, {}
    for r in con.execute(f"""SELECT cliente_id, data, valor, criado_em FROM lancamentos WHERE escopo='PJ' AND tipo='entrada'
                             AND pago_em IS NOT NULL AND excluido_em IS NULL {filtro}""", args):
        pagos.setdefault(r["cliente_id"], []).append(r)
    for r in con.execute(f"""SELECT cliente_id, tipo, data, valor, criado_em FROM cliente_eventos WHERE excluido_em IS NULL
                             AND tipo IN ('pagamento','renovacao','pausa') {filtro}""", args):
        eventos.setdefault(r["cliente_id"], []).append(r)
    return {c["id"]: _renovacao(c, pagos.get(c["id"], []), eventos.get(c["id"], [])) for c in alunos}


def _renovacao(c, pagos: list, eventos: list) -> dict:
    gravada = str(c["data_renovacao"] or "").strip()[:10]
    out = {"gravada": c["data_renovacao"], "efetiva": c["data_renovacao"], "ciclos": 0, "falta": 0.0, "pendente": False,
           "motivo": None, "motivo_data": None}
    try:
        dt.date.fromisoformat(gravada)
    except ValueError:
        return out   # data torta no cadastro: fica como está
    valor = float(c["valor"] or 0)
    desde, trocada = _dias_antes(gravada, ANTECEDENCIA), c["renovacao_em"]
    meses_pagos = {str(p["data"])[:7] for p in pagos}
    itens = [("pagamento", p["data"], p["valor"], p["criado_em"]) for p in pagos]
    itens += [(e["tipo"], e["data"], e["valor"], e["criado_em"]) for e in eventos
              if not (e["tipo"] == "pagamento" and str(e["data"])[:7] in meses_pagos)]   # já lançado no financeiro: conta uma vez
    k, pendente, ultimo = 0, False, None
    for tipo, data, v, criado in sorted(itens, key=lambda i: (str(i[1]), str(i[3] or ""))):
        data = str(data or "").strip()[:10]
        if not ISO_DATA.fullmatch(data) or data < desde or (trocada and str(criado or "") <= trocada):
            continue   # é de antes da data gravada (ou da troca à mão): já está nela
        try:
            dt.date.fromisoformat(data)
        except ValueError:
            continue
        vence = proxima_renovacao(gravada, k)   # próximo mês ainda sem renovação
        perto = data >= _dias_antes(vence, ANTECEDENCIA)
        anda = 0
        if tipo == "pagamento":
            v = float(v or 0)
            meses = int(v / valor + (1 - CHEIO) + 1e-9) if valor > 0 else 0   # mensalidades inteiras neste pagamento
            if pendente:   # paga a Renovação marcada (mesmo parcial: baixa total); mensalidade a mais adianta
                pendente, anda = False, max(meses - 1, 0)
            elif meses:
                anda = meses
            elif perto:   # parcial (ou cadastro sem valor mensal): renova o mês e quita
                anda = 1
        elif tipo == "renovacao":
            confirma = ultimo is not None and data < vence and (
                dt.date.fromisoformat(data) - dt.date.fromisoformat(ultimo)).days <= CONFIRMA
            if perto and not confirma:   # renovou e ainda não pagou: o próximo pagamento é desta renovação
                anda, pendente = 1, valor > 0
        elif perto:   # mês pulado: não deve nada
            anda, pendente = 1, False
        if anda:
            k, ultimo = k + anda, data
            out.update(motivo=tipo, motivo_data=data)
    out.update(efetiva=proxima_renovacao(gravada, k) if k else gravada, ciclos=k, pendente=pendente,
               falta=valor if pendente else 0.0)
    return out


def cobranca(valor, vencida: str, hoje: str, par: dict) -> dict | None:
    """Cobrança de quem está com a renovação vencida: cada mês vencido até hoje com multa (uma vez) e juros ao mês
    proporcional aos dias de atraso dele. par = parâmetros 'cobranca' (multa, juros_ao_mes). None sem valor mensal ou sem atraso."""
    valor = float(valor or 0)
    try:
        dt.date.fromisoformat(str(vencida))
    except ValueError:
        return None
    if valor <= 0 or vencida >= hoje:
        return None
    multa_pct, juros_mes = float(par.get("multa") or 0), float(par.get("juros_ao_mes") or 0)
    h = dt.date.fromisoformat(hoje)
    meses, multa, juros, data = 0, 0.0, 0.0, vencida
    while data < hoje and meses < 24:
        dias = (h - dt.date.fromisoformat(data)).days
        multa += valor * multa_pct
        juros += valor * juros_mes * dias / 30
        meses += 1
        data = proxima_renovacao(vencida, meses)
    principal = valor * meses
    return {"meses": meses, "dias": (h - dt.date.fromisoformat(vencida)).days, "valor": round(principal, 2),
            "multa": round(multa, 2), "juros": round(juros, 2), "total": round(principal + multa + juros, 2)}


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
    """80% do lucro PJ médio dos 3 meses fechados antes de 'mes' (os 20% restantes ficam na empresa), em múltiplos de 50."""
    lucros = [resumo_mes(con, somar_meses(mes, -k))["lucro"] for k in (1, 2, 3)]
    media = sum(lucros) / 3
    return max(0, math.floor(0.8 * media / 50) * 50)


def conta_pf_salario(con: sqlite3.Connection) -> str | None:
    """Conta PF onde o salário cai: a conta PF com a foto de saldo mais recente (None se nenhuma conta PF tem saldo digitado).
    Sem conta, a entrada do salário nunca bate no Banco × CRM."""
    frentes = frentes_contas(con)
    for r in con.execute("SELECT conta FROM saldos WHERE excluido_em IS NULL ORDER BY data DESC, id DESC"):
        if frentes.get(r["conta"]) == "PF":
            return r["conta"]
    return None


def pagar_salario(con: sqlite3.Connection, mes: str, pago_em: str) -> None:
    """Saída PJ (Retirada) + entrada PF (Salário, na conta PF de conta_pf_salario) do mês, numa transação.
    ValueError se desligado ou já pago (pelo botão ou com Retirada lançada à mão no mês)."""
    valor = round(db.parametros(con, "salario").get("valor") or 0, 2)
    if valor <= 0:
        raise ValueError("Defina o valor do salário em Configurações.")
    if _retiradas_mes(con, mes):
        raise ValueError("O salário deste mês já foi pago (tem Retirada lançada no mês).")
    nome = f"Salário {mes[5:]}/{mes[:4]}"
    conta_pf = conta_pf_salario(con)
    antigo = con.execute("SELECT id FROM lancamentos WHERE origem=?", (f"SAL:{mes}:PJ",)).fetchone()
    try:
        with con:
            if antigo:   # pagamento que foi para a lixeira: volta com o valor de hoje
                cur = con.execute("""UPDATE lancamentos SET excluido_em=NULL, valor=?, data=?, pago_em=?
                                     WHERE origem IN (?, ?) AND excluido_em IS NOT NULL""", (valor, pago_em, pago_em, f"SAL:{mes}:PJ", f"SAL:{mes}:PF"))
                if cur.rowcount == 0:   # as duas linhas estão ativas: já pago
                    raise sqlite3.IntegrityError
                con.execute("UPDATE lancamentos SET conta=? WHERE origem=? AND conta IS NULL", (conta_pf, f"SAL:{mes}:PF"))
                return
            con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, conta, origem)
                           VALUES ('PJ','saida',?,?,?,?,?, 'Contabilizei Bank', ?)""", (pago_em, pago_em, valor, RETIRADA, nome, f"SAL:{mes}:PJ"))
            con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, conta, origem)
                           VALUES ('PF','entrada',?,?,?, 'Salário', ?, ?, ?)""", (pago_em, pago_em, valor, nome, conta_pf, f"SAL:{mes}:PF"))
    except sqlite3.IntegrityError:
        raise ValueError("O salário deste mês já foi pago.") from None


# ---------- Reserva ----------
def _fixos_mes(con: sqlite3.Connection, mes: str, escopo: str, so_fixos: bool) -> float:
    """Soma prevista das recorrências ativas do escopo na competência, sem a Retirada e sem o DAS
    (o DAS depende da receita e é guardado à parte, em imposto_mes: não é custo fixo da reserva)."""
    return sum(r["valor"] for r in con.execute(
        f"""SELECT valor, descricao, categoria FROM recorrencias WHERE excluido_em IS NULL AND escopo=? AND categoria != ?
            AND inicio <= ? AND (fim IS NULL OR fim >= ?){' AND fixo=1' if so_fixos else ''}""", (escopo, RETIRADA, mes, mes))
        if not eh_das(r["descricao"], r["categoria"]))


def colchao(con: sqlite3.Connection, mes: str) -> dict:
    """Custo fixo de 1 mês para a reserva: recorrências fixas da PJ + o salário da PF
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
    quitados, m = set(), somar_meses(hoje[:7], -3)   # entradas em aberto de quem já pagou o mês: não são mais a receber
    while m <= fim[:7]:
        quitados |= {a["id"] for i in mensalidades(con, m) if i["quitado"] for a in i["abertos"]}
        m = somar_meses(m, 1)
    itens = [dict(i, estimado=False) for i in em_aberto_ate(con, fim, hoje) if not (i["origem"] == "lancamento" and i["id"] in quitados)]

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
