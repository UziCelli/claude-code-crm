"""Contas automáticas em Contas a pagar: o DAS, a conta da CIA e a de cada local criado pelo "+ Novo local", do mês anterior.

Todas são retroativas. Em novembro o app lança o DAS de outubro (sobre o que entrou em outubro), a CIA de outubro
(as aulas Feitas em outubro) e a de cada local (as aulas Feitas lá, pelos custos do local). O lançamento é uma saída PJ
em aberto, na data do vencimento, com `auto` = 'das:2026-10', 'cia:2026-10' ou 'local:<nome>:2026-10'.
Idempotente e barato: roda em INSERT OR IGNORE (PC e Render escrevem no mesmo Turso)."""
import datetime as dt
import re
import sqlite3
import traceback
import unicodedata

from . import db, financeiro, precos
from .vigencia import fixo_vale
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
    """O local é a CIA: 'CIA' no começo sem outra letra colada ('CIA', 'Cia 111', 'CIA2', 'CIA_Centro'), sem diferenciar maiúsculas.
    'Ciagym' ou 'Ciática Studio' não são a CIA (a taxa deles não pode virar conta da CIA)."""
    sem_acento = unicodedata.normalize("NFKD", local or "").encode("ascii", "ignore").decode().strip().lower()
    return bool(re.match(r"cia(?![a-z])", sem_acento))


def _sem_acento(texto: str | None) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().strip().lower()


def _mes_br(mes: str) -> str:
    return f"{mes[5:7]}/{mes[:4]}"


# ---------- aulas Feitas por local ----------
def _conta_do_local(local: str | None) -> str | None:
    """A qual conta vai a aula dada nesse local da agenda: 'cia' (eh_local_cia) ou o nome sem acento/maiúsculas."""
    if not (local or "").strip():
        return None
    return "cia" if eh_local_cia(local) else _sem_acento(local)


def aulas_por_local(con: sqlite3.Connection, mes: str) -> dict:
    """{conta: {(data, hora): {aluno}}} das aulas com marcação Feita (cliente_eventos tipo 'aula') no mês; conta = _conta_do_local.
    O local vem como na Agenda (controle do aluno): a avulsa daquele dia e hora, senão o horário fixo que valia naquele dia
    (fixo_vale: mudar o horário ou o local não muda os meses que passaram).
    Aula lançada pela ficha (sem hora) vale UMA vez: no primeiro horário do aluno naquele dia (avulsa ou fixo, em qualquer local).
    Sem horário nesse dia, não conta. Faltou, desmarcou e cancelada não são Feita, então não entram.
    3 leituras para o mês inteiro, todos os locais juntos (cada leitura no Turso é uma ida à rede)."""
    ini, fim = f"{mes}-01", f"{somar_meses(mes, 1)}-01"
    avulsas = {(r["cliente_id"], r["data"], r["hora"]): r["local"] for r in con.execute(
        "SELECT cliente_id, data, hora, local FROM agenda_avulsas WHERE excluido_em IS NULL AND data >= ? AND data < ? ORDER BY id", (ini, fim))}
    avulsas_do_dia = {}
    for (cid, data, hora) in avulsas:
        avulsas_do_dia.setdefault((cid, data), set()).add(hora)
    fixos = {}   # (aluno, dia da semana) -> linhas que podem ter valido no mês; a ativa primeiro
    for r in con.execute("""SELECT cliente_id, dia, hora, local, vigente_de, criado_em, excluido_em FROM agenda_fixos
                            WHERE (excluido_em IS NULL OR substr(excluido_em,1,10) >= ?) AND (vigente_de IS NULL OR vigente_de < ?)
                            ORDER BY excluido_em IS NOT NULL, id""", (ini, fim)):
        fixos.setdefault((r["cliente_id"], r["dia"]), []).append(r)

    def validos(cid, data):
        return [r for r in fixos.get((cid, _dia_da_semana(data)), ()) if fixo_vale(r, data)]

    contas = {}
    for e in con.execute("""SELECT DISTINCT e.cliente_id, e.data, e.hora FROM cliente_eventos e JOIN clientes c ON c.id = e.cliente_id
                            WHERE e.tipo='aula' AND e.excluido_em IS NULL AND c.excluido_em IS NULL AND e.data >= ? AND e.data < ?""",
                         (ini, fim)):
        cid, data, hora = e["cliente_id"], e["data"], e["hora"]
        fx = validos(cid, data)
        if hora is None:   # lançada pela ficha: o primeiro horário dele naquele dia, em qualquer local
            horas = avulsas_do_dia.get((cid, data), set()) | {r["hora"] for r in fx}
            if not horas:
                continue
            hora = min(horas)
        local = avulsas.get((cid, data, hora)) or next((r["local"] for r in fx if r["hora"] == hora), None)
        conta = _conta_do_local(local)
        if conta:
            contas.setdefault(conta, {}).setdefault((data, hora), set()).add(cid)
    return contas


class _Rodada:
    """O que uma rodada (gerar, prévia) lê uma vez só: aulas por mês, custos dos locais, parâmetros."""
    def __init__(self, con: sqlite3.Connection):
        self.con, self._aulas, self._custos, self._params, self._locais = con, {}, None, None, None
        self._lancadas: dict | None = None

    def aulas(self, mes: str) -> dict:
        if mes not in self._aulas:
            self._aulas[mes] = aulas_por_local(self.con, mes)
        return self._aulas[mes]

    def custos(self) -> dict:
        if self._custos is None:
            self._custos = precos.custos_locais(self.con)
        return self._custos

    def params(self) -> dict:
        if self._params is None:
            self._params = db.parametros(self.con, "contas_auto")
        return self._params

    def locais(self) -> list[str]:
        """Locais criados aqui que geram conta automática: os de locais_custos, menos a CIA (ela tem a conta dela)
        e menos um segundo com o mesmo nome sem acento (as aulas da agenda são as mesmas: cobraria duas vezes)."""
        if self._locais is None:
            vistos, self._locais = set(), []
            for n in self.custos():
                k = _sem_acento(n)
                if k and not eh_local_cia(n) and k not in vistos:
                    vistos.add(k)
                    self._locais.append(n)
        return self._locais

    def prever(self, chaves: list[str]) -> None:
        """Lê de uma vez as contas automáticas já lançadas dessas chaves (uma ida ao banco, não uma por local)."""
        self._lancadas = {r["auto"]: r for r in self.con.execute(
            f"""SELECT auto, id, valor, data, descricao, observacao, pago_em, excluido_em, recorrencia_id
                FROM lancamentos WHERE auto IN ({','.join('?' * len(chaves))})""", chaves)}

    def lancada(self, chave: str):
        """A conta automática `chave` já lançada (ou None). Sem prever(), lê só ela."""
        if self._lancadas is not None:
            return self._lancadas.pop(chave, None)
        return self.con.execute("""SELECT auto, id, valor, data, descricao, observacao, pago_em, excluido_em, recorrencia_id
                                   FROM lancamentos WHERE auto=?""", (chave,)).fetchone()


# ---------- CIA ----------
def _grupos_cia(con: sqlite3.Connection, mes: str) -> dict:
    """{(data, hora): {aluno}} das aulas Feitas na CIA no mês (ver aulas_por_local)."""
    return aulas_por_local(con, mes).get("cia", {})


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


def cia_mes(con: sqlite3.Connection, mes: str, rodada: "_Rodada | None" = None) -> dict:
    """Conta da CIA pelas aulas Feitas no mês: {mes, aulas: {pessoas: quantas aulas}, valor, vencimento, texto}.
    Duas pessoas Feitas no mesmo (data, hora) são UMA aula de 2 pessoas (taxa_cia['2']); acima do máximo vale a taxa do máximo.
    O vencimento é o dia `contas_auto.dia_cia` (padrão 5) do mês seguinte, antecipado para a sexta se cair no fim de semana."""
    r = rodada or _Rodada(con)
    taxa, maximo = precos.taxas_cia(con)
    aulas = {p: 0 for p in range(1, maximo + 1)}
    for pessoas in r.aulas(mes).get("cia", {}).values():
        aulas[min(len(pessoas), maximo)] += 1
    valor = round(sum(n * taxa.get(p, taxa.get(maximo, 0)) for p, n in aulas.items()), 2)
    dia = int(r.params().get("dia_cia") or DIA_CIA)
    return {"mes": mes, "aulas": aulas, "valor": valor, "vencimento": vencimento_util(dia, somar_meses(mes, 1)),
            "texto": _texto_cia(aulas, taxa)}


# ---------- locais criados pelo "+ Novo local" ----------
def eh_do_local(texto: str | None, nome: str) -> bool:
    """O texto (descrição, contraparte) fala do local? O nome inteiro, sem acento nem maiúsculas ('SmartFit' casa com 'Aluguel smartfit')."""
    alvo = _sem_acento(nome)
    return bool(alvo) and bool(re.search(rf"(?<![a-z0-9]){re.escape(alvo)}(?![a-z0-9])", _sem_acento(texto)))


def locais_com_conta(con: sqlite3.Connection) -> list[str]:
    """Locais criados aqui que geram conta automática (ver _Rodada.locais)."""
    return _Rodada(con).locais()


def local_mes(con: sqlite3.Connection, nome: str, mes: str, rodada: "_Rodada | None" = None) -> dict:
    """Conta do local pelas aulas Feitas lá no mês: {mes, aulas, pessoas_extra, valor, vencimento, texto}.
    Cada (data, hora) com aula Feita é uma aula: taxa por aula + taxa por pessoa a mais × (pessoas − 1), como no preço.
    A taxa mensal entra uma vez, só se houve aula no mês. O deslocamento (gasolina, Uber) NÃO entra: é gasto seu, não
    cobrança do local, e já aparece no financeiro quando você paga. Vence no dia `contas_auto.dia_locais`
    (padrão: o mesmo da CIA) do mês seguinte, antecipado para a sexta se cair no fim de semana."""
    r = rodada or _Rodada(con)
    c = r.custos().get(nome) or {}
    taxa, extra, mensal = float(c.get("taxa_aula") or 0), float(c.get("taxa_pessoa_extra") or 0), float(c.get("taxa_mensal") or 0)
    grupos = r.aulas(mes).get(_sem_acento(nome), {}).values()
    n, extras = len(grupos), sum(len(p) - 1 for p in grupos)
    valor = round(n * taxa + extras * extra + (mensal if n else 0), 2)
    p = r.params()
    dia = int(p.get("dia_locais") or p.get("dia_cia") or DIA_CIA)
    partes = []
    if n:
        partes.append(f"{n} aula{'s' if n != 1 else ''} × {moeda_br(taxa)}")
        if extras and extra:
            partes.append(f"{extras} pessoa{'s' if extras != 1 else ''} a mais × {moeda_br(extra)}")
        if mensal:
            partes.append(f"taxa mensal {moeda_br(mensal)}")
    return {"mes": mes, "aulas": n, "pessoas_extra": extras, "valor": valor, "vencimento": vencimento_util(dia, somar_meses(mes, 1)),
            "texto": " + ".join(partes) or f"Nenhuma aula Feita em {nome}"}


# ---------- as contas ----------
def _local_do_tipo(tipo: str) -> str | None:
    return tipo[len("local:"):] if tipo.startswith("local:") else None


def _dono(texto: str | None, locais: list[str]) -> str | None:
    """De qual conta automática (CIA ou local) o texto fala, pela mais específica: o local de nome mais longo que casa
    ('Aluguel Smart Fit' é do 'Smart Fit', não do 'Fit'); um local vence a CIA ('Studio 111' não é a CIA 111); senão, eh_cia."""
    achados = [n for n in locais if eh_do_local(texto, n)]
    if achados:
        return f"local:{max(achados, key=lambda n: len(_sem_acento(n)))}"
    return "cia" if eh_cia(texto) else None


def _e_a_conta(rodada: "_Rodada", tipo: str, texto: str, categoria=None) -> bool:
    """O texto (descrição + contraparte) é a mesma conta do tipo? DAS: eh_das; CIA e locais: _dono."""
    if tipo == "das":
        return financeiro.eh_das(texto, categoria)
    return _dono(texto, rodada.locais()) == tipo


def _conta(con: sqlite3.Connection, tipo: str, comp: str, rodada: "_Rodada") -> dict:
    """O que o app lançaria para a competência: {valor, data, descricao, categoria, observacao}."""
    nome = _local_do_tipo(tipo)
    if nome:
        c = local_mes(con, nome, comp, rodada)
        return {"valor": c["valor"], "data": c["vencimento"], "descricao": f"{nome}: aulas de {_mes_br(comp)}",
                "categoria": CATEGORIA_CIA, "observacao": c["texto"]}
    if tipo == "das":
        d = financeiro.das_competencia(con, comp)
        return {"valor": d["valor"], "data": d["vencimento"], "descricao": f"DAS {_mes_br(comp)} (Simples)",
                "categoria": CATEGORIA_DAS, "observacao": financeiro.explicacao_das(d)}
    c = cia_mes(con, comp, rodada)
    return {"valor": c["valor"], "data": c["vencimento"], "descricao": f"CIA 111: aulas de {_mes_br(comp)}",
            "categoria": CATEGORIA_CIA, "observacao": c["texto"]}


def _ja_lancada_a_mao(con: sqlite3.Connection, tipo: str, mes_venc: str, rodada: "_Rodada") -> bool:
    """Já existe, no mês do vencimento, uma saída PJ dessa conta lançada à mão (paga ou em aberto, não excluída)?
    Para um local, gasto de Transporte que cita o nome ('Gasolina SmartFit') não é a conta do local."""
    for r in con.execute("""SELECT descricao, categoria, contraparte FROM lancamentos WHERE escopo='PJ' AND tipo='saida'
                            AND excluido_em IS NULL AND auto IS NULL AND substr(data,1,7)=?""", (mes_venc,)):
        if tipo == "das" and financeiro.eh_das(r["descricao"], r["categoria"]):
            return True
        if tipo.startswith("local:") and _sem_acento(r["categoria"]) == "transporte":
            continue
        if tipo != "das" and _e_a_conta(rodada, tipo, f"{r['descricao'] or ''} {r['contraparte'] or ''}"):
            return True
    return False


def _recorrencia(con: sqlite3.Connection, tipo: str, mes_venc: str, rodada: "_Rodada | None" = None):
    """Recorrência PJ ativa nesse mês (fixa ou variável) que é a mesma conta (DAS: eh_das; CIA: eh_cia; local: o nome, na descrição).
    Excluída ou já encerrada não conta: sem recorrência, o app lança a conta sem vínculo e não há item virtual a duplicar."""
    rodada = rodada or _Rodada(con)
    for r in con.execute("""SELECT * FROM recorrencias WHERE excluido_em IS NULL AND escopo='PJ' AND inicio <= ?
                            AND (fim IS NULL OR fim >= ?) ORDER BY id""", (mes_venc, mes_venc)):
        if _e_a_conta(rodada, tipo, r["descricao"], r["categoria"]):
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


def _ligar(con: sqlite3.Connection, tipo: str, lid: int, chave: str, data: str, rodada: "_Rodada") -> bool:
    """Liga a automática já existente (sem recorrencia_id) à recorrência que é a mesma conta, se a vaga do mês da data
    estiver livre ou só com linha na lixeira. Sem recorrência que case, ou com o mês já baixado à mão, não mexe. True se ligou."""
    rec = _recorrencia(con, tipo, data[:7], rodada)
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


def _garantir(con: sqlite3.Connection, tipo: str, comp: str, rodada: "_Rodada") -> bool:
    """Cria (ou recalcula, se ainda em aberto; em aberto e zerada, apaga) a conta automática da competência e a mantém ligada à recorrência da mesma conta,
    para ela ser a conta do mês e a recorrência não mostrar um item a mais. True se mexeu no banco."""
    conta = _conta(con, tipo, comp, rodada)
    chave = f"{tipo}:{comp}"
    atual = rodada.lancada(chave)
    if atual:   # excluído não volta; pago não é recalculado; sem valor não há o que recalcular
        if atual["excluido_em"]:
            return False
        mexeu, data = False, atual["data"]
        if not atual["pago_em"] and conta["valor"] <= 0:   # em aberto e o mês não tem mais o que cobrar (aula desmarcada, local mudou)
            with con:   # a conta é só do app (auto = chave: ninguém editou): sai de vez; se o valor voltar, é criada de novo
                cur = con.execute("DELETE FROM lancamentos WHERE id=? AND auto=? AND pago_em IS NULL AND excluido_em IS NULL",
                                  (atual["id"], chave))
            return cur.rowcount > 0
        if not atual["pago_em"] and conta["valor"] > 0 and \
                (round(atual["valor"], 2), atual["data"], atual["descricao"], atual["observacao"]) != \
                (conta["valor"], conta["data"], conta["descricao"], conta["observacao"]):
            with con:   # `auto = ?` no WHERE: editou à mão (a rota zera `auto`) entre a leitura e aqui? Então não mexe
                cur = con.execute("""UPDATE lancamentos SET valor=?, data=?, descricao=?, observacao=? WHERE id=? AND auto=?
                                     AND pago_em IS NULL AND excluido_em IS NULL""",
                                  (conta["valor"], conta["data"], conta["descricao"], conta["observacao"], atual["id"], chave))
            mexeu, data = cur.rowcount > 0, conta["data"]
        if atual["recorrencia_id"] is None and _ligar(con, tipo, atual["id"], chave, data, rodada):   # criada antes, sem vínculo
            mexeu = True
        return mexeu
    if conta["valor"] <= 0 or _ja_lancada_a_mao(con, tipo, conta["data"][:7], rodada):
        return False
    rec = _recorrencia(con, tipo, conta["data"][:7], rodada)
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
    """Lança em Contas a pagar o DAS, a CIA e a conta de cada local do mês anterior a `hoje` ('AAAA-MM-DD' ou date) que ainda
    não existem, e recalcula os que ainda estão em aberto. Não cria DAS que já existe de verdade nem CIA/local lançado à mão;
    liga o lançamento à recorrência da conta, se houver. Devolve as chaves que criou ou atualizou ('das:2026-10', 'local:X:2026-10')."""
    comp = somar_meses(str(hoje)[:7], -1)
    rodada = _Rodada(con)
    tipos = ["das", "cia"] + [f"local:{n}" for n in rodada.locais()]
    rodada.prever([f"{tipo}:{comp}" for tipo in tipos])
    return [f"{tipo}:{comp}" for tipo in tipos if _garantir(con, tipo, comp, rodada)]


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
    """Linhas para o Financeiro: o que a CIA, cada local com aula e o DAS do mês corrente estão somando até agora."""
    mes = str(hoje)[:7]
    rodada = _Rodada(con)
    cia, das = cia_mes(con, mes, rodada), financeiro.das_competencia(con, mes)
    n = sum(cia["aulas"].values())
    venc = das["vencimento"]
    linhas = [f"CIA este mês até agora: {n} aula{'s' if n != 1 else ''} = {moeda_br(cia['valor'])}"]
    for nome in rodada.locais():
        c = local_mes(con, nome, mes, rodada)
        if c["aulas"]:
            linhas.append(f"{nome} este mês até agora: {c['aulas']} aula{'s' if c['aulas'] != 1 else ''} = {moeda_br(c['valor'])}")
    return linhas + [f"DAS de {_mes_br(mes)} (vence {venc[8:10]}/{venc[5:7]}): {moeda_br(das['valor'])} até agora"]
