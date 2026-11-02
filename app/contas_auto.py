"""Contas automáticas em Contas a pagar: o DAS e a conta da CIA do mês anterior, calculados pelo app.

Ambas são retroativas. Em novembro o app lança o DAS de outubro (sobre o que entrou em outubro) e a CIA de outubro
(as aulas Feitas em outubro). O lançamento é uma saída PJ em aberto, na data do vencimento, com `auto` = 'das:2026-10'
ou 'cia:2026-10'. Idempotente e barato: roda em INSERT OR IGNORE (PC e Render escrevem no mesmo Turso)."""
import datetime as dt
import re
import sqlite3
import traceback
import unicodedata

from . import db, financeiro, precos
from .financeiro import moeda_br, somar_meses, vencimento_util

DIA_CIA = 5   # padrão do parâmetro contas_auto.dia_cia
CATEGORIA_CIA = "Aluguel"   # o espaço onde ele dá aula: cai na mesma nota de impacto do aluguel
CATEGORIA_DAS = "Impostos/Taxas"
# 'CIA', '111' (o nome do espaço) ou 'crédito(s) de/da/das/do/dos aula(s)', já sem acento e em minúsculas
RE_CIA = re.compile(r"\bcia\b|\b111\b|\bcreditos?\s+(?:d[aeo]s?\s+)?aulas?\b")


def eh_cia(texto: str | None) -> bool:
    """O texto (descrição, contraparte) é a conta da CIA: 'CIA', '111' ou 'Crédito(s) de aula(s)', sem acento nem maiúsculas."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return bool(RE_CIA.search(sem_acento))


def eh_local_cia(local: str | None) -> bool:
    """O local é a CIA: o nome 'CIA' ou que começa com 'CIA' (sem diferenciar maiúsculas)."""
    return (local or "").strip().lower().startswith("cia")


def _mes_br(mes: str) -> str:
    return f"{mes[5:7]}/{mes[:4]}"


# ---------- CIA ----------
def _grupos_cia(con: sqlite3.Connection, mes: str) -> dict:
    """{(data, hora): {aluno}} das aulas com marcação Feita (cliente_eventos tipo 'aula') na CIA no mês.
    O local vem como na Agenda (controle do aluno): a avulsa daquele dia e hora, senão o horário fixo do dia da semana.
    Aula lançada pela ficha (sem hora) vale no primeiro horário do aluno na CIA naquele dia; sem horário na CIA, não conta.
    Faltou, desmarcou e cancelada não são Feita, então não entram."""
    ini, fim = f"{mes}-01", f"{somar_meses(mes, 1)}-01"
    avulsas = {(r["cliente_id"], r["data"], r["hora"]): r["local"] for r in con.execute(
        "SELECT cliente_id, data, hora, local FROM agenda_avulsas WHERE excluido_em IS NULL AND data >= ? AND data < ? ORDER BY id", (ini, fim))}
    fixos = {(r["cliente_id"], r["dia"], r["hora"]): r["local"] for r in con.execute(
        "SELECT cliente_id, dia, hora, local FROM agenda_fixos WHERE excluido_em IS NULL ORDER BY id")}

    def local(cid, data, hora):
        dia = _dia_da_semana(data)
        return avulsas.get((cid, data, hora)) or fixos.get((cid, dia, hora))

    grupos = {}
    for e in con.execute("""SELECT DISTINCT e.cliente_id, e.data, e.hora FROM cliente_eventos e JOIN clientes c ON c.id = e.cliente_id
                            WHERE e.tipo='aula' AND e.excluido_em IS NULL AND c.excluido_em IS NULL AND e.data >= ? AND e.data < ?""",
                         (ini, fim)):
        cid, data, hora = e["cliente_id"], e["data"], e["hora"]
        if hora is None:   # lançada pela ficha: acha o horário dele na CIA naquele dia
            horas = sorted({h for (c, d, h), loc in avulsas.items() if c == cid and d == data and eh_local_cia(loc)}
                           | {h for (c, dia, h), loc in fixos.items() if c == cid and dia == _dia_da_semana(data) and eh_local_cia(loc)})
            hora = horas[0] if horas else None
            if hora is None:
                continue
        if eh_local_cia(local(cid, data, hora)):
            grupos.setdefault((data, hora), set()).add(cid)
    return grupos


def _dia_da_semana(data: str) -> int:
    return dt.date.fromisoformat(data).isoweekday()


def _texto_cia(aulas: dict, taxa: dict) -> str:
    partes = []
    for pessoas, n in aulas.items():
        if not n:
            continue
        aula = f"{n} aula{'s' if n != 1 else ''} de" if not partes else f"{n} de"
        partes.append(f"{aula} {pessoas} pessoa{'s' if pessoas != 1 else ''} × {moeda_br(taxa.get(pessoas, 0))}")
    return " + ".join(partes) or "Nenhuma aula Feita na CIA"


def cia_mes(con: sqlite3.Connection, mes: str) -> dict:
    """Conta da CIA pelas aulas Feitas no mês: {mes, aulas: {pessoas: quantas aulas}, valor, vencimento, texto}.
    Duas pessoas Feitas no mesmo (data, hora) são UMA aula de 2 pessoas (taxa_cia['2']); acima do máximo vale a taxa do máximo.
    O vencimento é o dia `contas_auto.dia_cia` (padrão 5) do mês seguinte, antecipado para a sexta se cair no fim de semana."""
    taxa, maximo = precos.taxas_cia(con)
    aulas = {p: 0 for p in range(1, maximo + 1)}
    for pessoas in _grupos_cia(con, mes).values():
        aulas[min(len(pessoas), maximo)] += 1
    valor = round(sum(n * taxa.get(p, taxa.get(maximo, 0)) for p, n in aulas.items()), 2)
    dia = int(db.parametros(con, "contas_auto").get("dia_cia") or DIA_CIA)
    return {"mes": mes, "aulas": aulas, "valor": valor, "vencimento": vencimento_util(dia, somar_meses(mes, 1)),
            "texto": _texto_cia(aulas, taxa)}


# ---------- as duas contas ----------
def _conta(con: sqlite3.Connection, tipo: str, comp: str) -> dict:
    """O que o app lançaria para a competência: {valor, data, descricao, categoria, observacao}."""
    if tipo == "das":
        d = financeiro.das_competencia(con, comp)
        return {"valor": d["valor"], "data": d["vencimento"], "descricao": f"DAS {_mes_br(comp)} (Simples)",
                "categoria": CATEGORIA_DAS, "observacao": financeiro.explicacao_das(d)}
    c = cia_mes(con, comp)
    return {"valor": c["valor"], "data": c["vencimento"], "descricao": f"CIA 111: aulas de {_mes_br(comp)}",
            "categoria": CATEGORIA_CIA, "observacao": c["texto"]}


def _ja_lancada_a_mao(con: sqlite3.Connection, tipo: str, mes_venc: str) -> bool:
    """Já existe, no mês do vencimento, uma saída PJ dessa conta lançada à mão (paga ou em aberto, não excluída)?"""
    for r in con.execute("""SELECT descricao, categoria, contraparte FROM lancamentos WHERE escopo='PJ' AND tipo='saida'
                            AND excluido_em IS NULL AND auto IS NULL AND substr(data,1,7)=?""", (mes_venc,)):
        if tipo == "das" and financeiro.eh_das(r["descricao"], r["categoria"]):
            return True
        if tipo == "cia" and eh_cia(f"{r['descricao'] or ''} {r['contraparte'] or ''}"):
            return True
    return False


def _recorrencia(con: sqlite3.Connection, tipo: str, mes_venc: str):
    """Recorrência PJ ativa nesse mês (fixa ou variável) que é a mesma conta (DAS: eh_das; CIA: eh_cia na descrição).
    Excluída ou já encerrada não conta: sem recorrência, o app lança a conta sem vínculo e não há item virtual a duplicar."""
    for r in con.execute("""SELECT * FROM recorrencias WHERE excluido_em IS NULL AND escopo='PJ' AND inicio <= ?
                            AND (fim IS NULL OR fim >= ?) ORDER BY id""", (mes_venc, mes_venc)):
        if (financeiro.eh_das(r["descricao"], r["categoria"]) if tipo == "das" else eh_cia(r["descricao"])):
            return r
    return None


def _vaga_ligavel(con: sqlite3.Connection, rec, comp: str) -> bool:
    """Solta a vaga (recorrência, competência) se estiver livre ou só com linha na lixeira (como liberar_vaga) e devolve True.
    False se um lançamento ativo, pago ou em aberto, já ocupa o mês: a conta já existe. Quem chama já está em `with con`."""
    try:
        financeiro.liberar_vaga(con, rec["id"], comp, None)
    except ValueError:
        return False
    return True


def _ligar(con: sqlite3.Connection, tipo: str, lid: int, chave: str, data: str) -> bool:
    """Liga a automática já existente (sem recorrencia_id) à recorrência que é a mesma conta, se a vaga do mês da data
    estiver livre ou só com linha na lixeira. Sem recorrência que case, ou com o mês já baixado à mão, não mexe. True se ligou."""
    rec = _recorrencia(con, tipo, data[:7])
    if rec is None:
        return False
    try:
        with con:   # `auto = ?` no WHERE: editou à mão entre a leitura e aqui? Então não mexe
            if not _vaga_ligavel(con, rec, data[:7]):
                return False
            cur = con.execute("""UPDATE lancamentos SET recorrencia_id=?, competencia=?, conta=COALESCE(conta, ?)
                                 WHERE id=? AND auto=? AND recorrencia_id IS NULL AND excluido_em IS NULL""",
                              (rec["id"], data[:7], rec["conta"], lid, chave))
    except sqlite3.IntegrityError:   # outro PC ocupou a vaga no meio do caminho
        return False
    return cur.rowcount > 0


def _garantir(con: sqlite3.Connection, tipo: str, comp: str) -> bool:
    """Cria (ou recalcula, se ainda em aberto) a conta automática da competência e a mantém ligada à recorrência da mesma conta,
    para ela ser a conta do mês e a recorrência não mostrar um item a mais. True se mexeu no banco."""
    conta = _conta(con, tipo, comp)
    chave = f"{tipo}:{comp}"
    atual = con.execute("""SELECT id, valor, data, descricao, observacao, pago_em, excluido_em, recorrencia_id
                           FROM lancamentos WHERE auto=?""", (chave,)).fetchone()
    if atual:   # excluído não volta; pago não é recalculado; sem valor não há o que recalcular
        if atual["excluido_em"]:
            return False
        mexeu, data = False, atual["data"]
        if not atual["pago_em"] and conta["valor"] > 0 and \
                (round(atual["valor"], 2), atual["data"], atual["descricao"], atual["observacao"]) != \
                (conta["valor"], conta["data"], conta["descricao"], conta["observacao"]):
            with con:   # `auto = ?` no WHERE: editou à mão (a rota zera `auto`) entre a leitura e aqui? Então não mexe
                cur = con.execute("""UPDATE lancamentos SET valor=?, data=?, descricao=?, observacao=? WHERE id=? AND auto=?
                                     AND pago_em IS NULL AND excluido_em IS NULL""",
                                  (conta["valor"], conta["data"], conta["descricao"], conta["observacao"], atual["id"], chave))
            mexeu, data = cur.rowcount > 0, conta["data"]
        if atual["recorrencia_id"] is None and _ligar(con, tipo, atual["id"], chave, data):   # criada antes, sem vínculo
            mexeu = True
        return mexeu
    if conta["valor"] <= 0 or _ja_lancada_a_mao(con, tipo, conta["data"][:7]):
        return False
    rec = _recorrencia(con, tipo, conta["data"][:7])
    try:
        with con:
            if rec and not _vaga_ligavel(con, rec, conta["data"][:7]):
                return False   # o mês dessa recorrência já tem baixa ativa (a da lixeira é solta da vaga)
            cur = con.execute("""INSERT OR IGNORE INTO lancamentos (escopo, tipo, data, valor, categoria, descricao, observacao, conta,
                                 recorrencia_id, competencia, auto) VALUES ('PJ','saida',?,?,?,?,?,?,?,?,?)""",
                              (conta["data"], conta["valor"], conta["categoria"], conta["descricao"], conta["observacao"],
                               rec["conta"] if rec else None, rec["id"] if rec else None, conta["data"][:7] if rec else None, chave))
    except sqlite3.IntegrityError:   # outro PC ocupou a vaga no meio do caminho
        return False
    return cur.rowcount > 0


def gerar_contas_automaticas(con: sqlite3.Connection, hoje) -> list[str]:
    """Lança em Contas a pagar o DAS e a CIA do mês anterior a `hoje` ('AAAA-MM-DD' ou date) que ainda não existem, e recalcula
    os que ainda estão em aberto. Não cria DAS que já existe de verdade nem CIA lançada à mão; liga o lançamento à recorrência
    da conta, se houver. Devolve as chaves que criou ou atualizou ('das:2026-10')."""
    comp = somar_meses(str(hoje)[:7], -1)
    return [f"{tipo}:{comp}" for tipo in ("das", "cia") if _garantir(con, tipo, comp)]


# cache por dia: Painel e startup não refazem a conta a cada requisição; /financeiro força (recalcula o que está em aberto)
_feito: dict = {"chave": None}


def limpar_cache() -> None:
    _feito["chave"] = None


def garantir(con: sqlite3.Connection, hoje, forcar: bool = False) -> None:
    """gerar_contas_automaticas com cache em memória por dia (e por banco). Nunca derruba a tela: o erro vai para o log."""
    chave = (str(db.DB_PATH), str(hoje)[:10])
    if not forcar and _feito["chave"] == chave:
        return
    try:
        gerar_contas_automaticas(con, hoje)
        _feito["chave"] = chave
    except Exception:
        traceback.print_exc()


# ---------- prévia e "Como calculei" ----------
def previa(con: sqlite3.Connection, hoje) -> list[str]:
    """Duas linhas para o Financeiro: o que a CIA e o DAS do mês corrente estão somando até agora."""
    mes = str(hoje)[:7]
    cia, das = cia_mes(con, mes), financeiro.das_competencia(con, mes)
    n = sum(cia["aulas"].values())
    venc = das["vencimento"]
    return [f"CIA este mês até agora: {n} aula{'s' if n != 1 else ''} = {moeda_br(cia['valor'])}",
            f"DAS de {_mes_br(mes)} (vence {venc[8:10]}/{venc[5:7]}): {moeda_br(das['valor'])} até agora"]
