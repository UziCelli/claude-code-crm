"""Ofertas de upsell: proposta com valor de oferta, por quantos meses vale e até quando (Campanhas), e o que cada aluno respondeu.

Tudo transparente: a mensagem diz o que inclui, o valor normal, o da oferta, por quanto tempo e para quanto volta.
Uma resposta por oferta e aluno (oferta_respostas): enviada -> aceitou | recusou. Aceitou pode atualizar a mensalidade e, se o valor
tem prazo, guarda o dia em que ele acaba: perto desse dia o CRM avisa (alerta azul) e o botão volta a mensalidade ao valor normal.
Telas (Campanhas, ficha, lista de Clientes), alertas e sugestões leem daqui: nenhuma tem regra própria.
"""
import datetime as dt

from . import alunos, db, financeiro

SITUACOES_ELEGIVEIS = ("em_dia", "vence_logo")   # só quem está em dia recebe a proposta; quem deve ou sumiu tem outra solução
MAX_MESES = 36
TAXA_ESTIMADA = 0.3                              # quantos aceitam, na conta do impacto da sugestão
PADRAO_UPSELL = next(t for g, k, _, t, _ in db.PARAMETROS_INICIAIS if g == "msg_whatsapp" and k == "upsell")


def _main():
    from . import main   # import tardio: main importa este módulo
    return main


def _iso(hoje=None) -> str:
    if hoje is None:
        return dt.date.today().isoformat()
    return hoje.isoformat() if isinstance(hoje, dt.date) else str(hoje)[:10]


def _limpo(texto) -> str:
    return " ".join(str(texto or "").split())


# ---------- cadastro ----------
def validar(titulo, inclui, valor_normal, valor_oferta, meses, valida_ate) -> tuple[dict | None, str | None]:
    """Confere o formulário da oferta. Devolve (dados, erro): um dos dois é None. Meses vazio = o valor da oferta vale sempre."""
    m = _main()
    titulo, inclui = _limpo(titulo), _limpo(inclui)
    if not titulo:
        return None, "Escreva o título da oferta."
    if not inclui:
        return None, "Diga o que a oferta inclui."
    try:
        normal, oferta = m._num_br(valor_normal), m._num_br(valor_oferta)
    except ValueError:
        return None, "Valor inválido: use só números, como 350,00."
    if normal <= 0:
        return None, "Informe o valor normal (maior que zero)."
    if oferta <= 0 or oferta >= normal:
        return None, "O valor da oferta precisa ser maior que zero e menor que o valor normal."
    meses_txt = str(meses or "").strip()
    n = None
    if meses_txt:
        if not meses_txt.isdigit() or not 1 <= int(meses_txt) <= MAX_MESES:
            return None, f"Meses: use um número de 1 a {MAX_MESES}, ou deixe vazio para valer sempre."
        n = int(meses_txt)
    ate = None
    if str(valida_ate or "").strip():
        ate = m.data_iso(valida_ate)
        if not ate:
            return None, "Validade inválida: escolha a data no calendário."
    return {"titulo": titulo, "inclui": inclui, "valor_normal": round(normal, 2), "valor_oferta": round(oferta, 2),
            "meses_desconto": n, "valida_ate": ate}, None


def salvar(con, oid, dados: dict) -> int:
    """Cria (oid vazio) ou atualiza a oferta. Devolve o id."""
    with con:
        if oid:
            con.execute("""UPDATE ofertas SET titulo=:titulo, inclui=:inclui, valor_normal=:valor_normal, valor_oferta=:valor_oferta,
                           meses_desconto=:meses_desconto, valida_ate=:valida_ate WHERE id=:id AND excluido_em IS NULL""", {**dados, "id": oid})
            return oid
        return con.execute("""INSERT INTO ofertas (titulo, inclui, valor_normal, valor_oferta, meses_desconto, valida_ate, ativa)
                              VALUES (:titulo, :inclui, :valor_normal, :valor_oferta, :meses_desconto, :valida_ate, 1)""", dados).lastrowid


def alternar_ativa(con, oid) -> bool | None:
    """Liga/desliga a oferta. Devolve o novo estado (None se não existe)."""
    r = con.execute("SELECT ativa FROM ofertas WHERE id=? AND excluido_em IS NULL", (oid,)).fetchone()
    if not r:
        return None
    novo = 0 if r["ativa"] else 1
    with con:
        con.execute("UPDATE ofertas SET ativa=? WHERE id=?", (novo, oid))
    return bool(novo)


def excluir(con, oid) -> bool:
    """Manda a oferta para a lixeira (restaurável em Dados)."""
    with con:
        cur = con.execute("UPDATE ofertas SET excluido_em=datetime('now','localtime') WHERE id=? AND excluido_em IS NULL", (oid,))
    return cur.rowcount > 0


def obter(con, oid) -> dict | None:
    r = con.execute("SELECT * FROM ofertas WHERE id=? AND excluido_em IS NULL", (oid,)).fetchone()
    return dict(r) if r else None


def todas(con) -> list[dict]:
    """Todas as ofertas que não foram excluídas, as ativas primeiro."""
    return [dict(r) for r in con.execute("SELECT * FROM ofertas WHERE excluido_em IS NULL ORDER BY ativa DESC, id DESC")]


def ativas(con, hoje=None) -> list[dict]:
    """Ofertas que podem ser enviadas hoje: ativas, não excluídas e dentro da validade."""
    return [dict(r) for r in con.execute(
        "SELECT * FROM ofertas WHERE excluido_em IS NULL AND ativa=1 AND (valida_ate IS NULL OR valida_ate >= ?) ORDER BY id", (_iso(hoje),))]


# ---------- a mensagem ----------
def duracao_txt(o) -> str:
    n = o.get("meses_desconto")
    if not n:
        return ""
    return " no primeiro mês" if n == 1 else f" nos primeiros {n} meses"


def texto(o, nome="", modelo=None) -> str:
    """A mensagem do WhatsApp (modelo 'upsell'). Sem prazo não sobra 'nos primeiros...' nem 'depois volta'; sem validade some a frase da validade."""
    m = _main()
    n = o.get("meses_desconto")
    ate = o.get("valida_ate")
    extra = {"titulo": _limpo(o.get("titulo")).rstrip(".;,: "), "inclui": _limpo(o.get("inclui")).rstrip(".;,: "),
             "valor_normal": m.moeda(o["valor_normal"]), "valor_oferta": m.moeda(o["valor_oferta"]),
             "duracao": duracao_txt(o), "depois": f" (depois volta para {m.moeda(o['valor_normal'])})" if n else "",
             "ate": f" Válida até {m.data_br(ate)}." if ate else ""}
    return m.preencher(modelo or PADRAO_UPSELL, nome, "", extra)


def previa(form, modelo=None) -> str:
    """Texto de exemplo (aluno 'Maria') para a tela de Campanhas, com o que já foi digitado; o que falta aparece entre parênteses."""
    m = _main()

    def num(k):
        try:
            return max(m._num_br(form.get(k)), 0.0)
        except ValueError:
            return 0.0
    meses = str(form.get("meses_desconto") or "").strip()
    o = {"titulo": _limpo(form.get("titulo")) or "(título da oferta)", "inclui": _limpo(form.get("inclui")) or "(o que inclui)",
         "valor_normal": num("valor_normal"), "valor_oferta": num("valor_oferta"),
         "meses_desconto": int(meses) if meses.isdigit() and int(meses) > 0 else None, "valida_ate": m.data_iso(form.get("valida_ate"))}
    return texto(o, "Maria", modelo)


# ---------- respostas ----------
def situacao_aluno(con, cid, hoje=None) -> list[dict]:
    """Por oferta ativa: {oferta, status (nao_enviada|enviada|aceitou|recusou), data, ate_desconto, encerrado_em}."""
    resp = {r["oferta_id"]: r for r in con.execute(
        "SELECT * FROM oferta_respostas WHERE cliente_id=? AND excluido_em IS NULL", (cid,))}
    out = []
    for o in ativas(con, hoje):
        r = resp.get(o["id"])
        out.append({"oferta": o, "status": r["status"] if r else "nao_enviada", "data": r["data"] if r else None,
                    "ate_desconto": r["ate_desconto"] if r else None, "encerrado_em": r["encerrado_em"] if r else None})
    return out


def _gravar(con, oid, cid, status, data, **extra) -> None:
    campos = {"ate_desconto": None, "valor_antes": None, "encerrado_em": None, **extra}
    con.execute("""INSERT INTO oferta_respostas (oferta_id, cliente_id, status, data, ate_desconto, valor_antes, encerrado_em)
                   VALUES (?,?,?,?,?,?,?) ON CONFLICT(oferta_id, cliente_id) DO UPDATE SET status=excluded.status, data=excluded.data,
                   ate_desconto=excluded.ate_desconto, valor_antes=excluded.valor_antes, encerrado_em=excluded.encerrado_em, excluido_em=NULL""",
                (oid, cid, status, data, campos["ate_desconto"], campos["valor_antes"], campos["encerrado_em"]))


def _par(con, cid, oid):
    c = con.execute("SELECT * FROM clientes WHERE id=? AND excluido_em IS NULL", (cid,)).fetchone()
    return c, obter(con, oid)


def _resposta(con, cid, oid):
    return con.execute("SELECT * FROM oferta_respostas WHERE oferta_id=? AND cliente_id=? AND excluido_em IS NULL", (oid, cid)).fetchone()


def registrar_envio(con, cid, oid, modelo=None, hoje=None) -> tuple[str | None, str | None]:
    """Marca como enviada e devolve (link do WhatsApp, erro). Quem já aceitou não recebe de novo."""
    m = _main()
    c, o = _par(con, cid, oid)
    if not c or not o:
        return None, "Aluno ou oferta não encontrado."
    if not o["ativa"]:
        return None, "Essa oferta está pausada: ative em Campanhas para enviar."
    if not "".join(ch for ch in str(c["telefone"] or "") if ch.isdigit()):
        return None, f"{c['nome']} está sem telefone: complete o cadastro para enviar."
    r = _resposta(con, cid, oid)
    if r and r["status"] == "aceitou":
        return None, f"{c['nome']} já aceitou essa oferta."
    h = _iso(hoje)
    with con:
        _gravar(con, oid, cid, "enviada", h)
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'mensagem', ?, ?)",
                    (cid, h, f"Oferta enviada: {o['titulo']}"))
    return m.wa(c["telefone"], texto(o, c["nome"], modelo)), None


def prazo_do_desconto(o, hoje=None) -> str | None:
    """Dia em que o valor da oferta acaba se for aceita hoje (None = sempre)."""
    return financeiro.proxima_renovacao(_iso(hoje), o["meses_desconto"]) if o.get("meses_desconto") else None


def aceitou(con, cid, oid, atualizar=True, hoje=None) -> tuple[str | None, str | None]:
    """Aceitou a oferta. Com `atualizar`, a mensalidade do aluno passa para o valor da oferta (e a receita a mais entra no resultado)."""
    m = _main()
    c, o = _par(con, cid, oid)
    if not c or not o:
        return None, "Aluno ou oferta não encontrado."
    h = _iso(hoje)
    ate = prazo_do_desconto(o, h)
    antes = round(float(c["valor"] or 0), 2) if atualizar else None
    quando = f" até {m.data_br(ate)[:5]}" if ate else ""
    with con:
        _gravar(con, oid, cid, "aceitou", h, ate_desconto=ate, valor_antes=antes)
        if atualizar:
            con.execute("UPDATE clientes SET valor=?, atualizado_em=datetime('now','localtime') WHERE id=?", (o["valor_oferta"], cid))
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'anotacao', ?, ?)",
                    (cid, h, f"Aceitou a oferta: {o['titulo']} ({m.moeda(o['valor_oferta'])}/mês{quando})"
                             + ("" if atualizar else "; mensalidade não alterada")))
    return (f"{c['nome']} aceitou: mensalidade em {m.moeda(o['valor_oferta'])}." if atualizar
            else f"{c['nome']} aceitou. A mensalidade continua {m.moeda(c['valor'])}."), None


def recusou(con, cid, oid, hoje=None) -> tuple[str | None, str | None]:
    c, o = _par(con, cid, oid)
    if not c or not o:
        return None, "Aluno ou oferta não encontrado."
    r = _resposta(con, cid, oid)
    if r and r["status"] == "aceitou":
        return None, f"{c['nome']} já aceitou essa oferta."
    with con:
        _gravar(con, oid, cid, "recusou", _iso(hoje))
    return f"{c['nome']} recusou: anotado.", None


def encerrar_desconto(con, cid, oid, hoje=None) -> tuple[str | None, str | None]:
    """O valor da oferta acabou: a mensalidade volta ao valor normal e o alerta some."""
    m = _main()
    c, o = _par(con, cid, oid)
    r = _resposta(con, cid, oid)
    if not c or not o or not r or r["status"] != "aceitou":
        return None, "Essa oferta não está aceita por esse aluno."
    h = _iso(hoje)
    with con:
        con.execute("UPDATE oferta_respostas SET encerrado_em=? WHERE id=?", (h, r["id"]))
        con.execute("UPDATE clientes SET valor=?, atualizado_em=datetime('now','localtime') WHERE id=?", (o["valor_normal"], cid))
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'anotacao', ?, ?)",
                    (cid, h, f"Fim do valor da oferta {o['titulo']}: mensalidade voltou para {m.moeda(o['valor_normal'])}"))
    return f"Mensalidade de {c['nome']} voltou para {m.moeda(o['valor_normal'])}.", None


# ---------- quem recebe, resultado e avisos ----------
def pendentes(con, estados=None, hoje=None) -> list[dict]:
    """Por oferta ativa: {oferta, elegiveis}. Elegível = aluno ativo, em dia (ou vencendo), com telefone e sem resposta a essa oferta.
    estados = alunos.estado já calculado (as sugestões passam o seu)."""
    lista = ativas(con, hoje)
    if not lista:
        return []
    if estados is None:
        estados = alunos.estado(con, _iso(hoje))
    respondeu = {}
    for r in con.execute("SELECT oferta_id, cliente_id FROM oferta_respostas WHERE excluido_em IS NULL"):
        respondeu.setdefault(r["oferta_id"], set()).add(r["cliente_id"])
    bons = sorted((e for e in estados.values() if e["situacao"] in SITUACOES_ELEGIVEIS and str(e["tel"] or "").strip()),
                  key=lambda e: e["nome"].lower())
    return [{"oferta": o, "elegiveis": [e for e in bons if e["id"] not in respondeu.get(o["id"], ())]} for o in lista]


def elegiveis(con, oferta_id, estados=None, hoje=None) -> list[dict]:
    for p in pendentes(con, estados, hoje):
        if p["oferta"]["id"] == oferta_id:
            return p["elegiveis"]
    return []


def resultado(con, oferta_id) -> dict:
    """{enviadas, aceitas, recusadas, taxa, mais_mes}. enviadas = todos que receberam a proposta (enviada, aceitou ou recusou).
    mais_mes = receita a mais por mês: (valor da oferta − mensalidade de antes) de quem aceitou e teve a mensalidade atualizada;
    quando o valor da oferta já acabou, vale o valor normal."""
    r = con.execute("""SELECT COUNT(*) enviadas, COALESCE(SUM(r.status='aceitou'), 0) aceitas, COALESCE(SUM(r.status='recusou'), 0) recusadas,
                       COALESCE(SUM(CASE WHEN r.status='aceitou' AND r.valor_antes IS NOT NULL
                                    THEN (CASE WHEN r.encerrado_em IS NULL THEN o.valor_oferta ELSE o.valor_normal END) - r.valor_antes END), 0) mais
                       FROM oferta_respostas r JOIN ofertas o ON o.id=r.oferta_id WHERE r.oferta_id=? AND r.excluido_em IS NULL""",
                    (oferta_id,)).fetchone()
    env, ac = int(r["enviadas"]), int(r["aceitas"])
    return {"enviadas": env, "aceitas": ac, "recusadas": int(r["recusadas"]), "taxa": (ac / env) if env else 0.0,
            "mais_mes": round(max(float(r["mais"]), 0.0), 2)}


def resumo(res) -> str:
    """'Enviada a 5 · 2 aceitaram (40%) · +R$ 180,00/mês' (para a linha de resultado de cada oferta)."""
    m = _main()
    if not res["enviadas"]:
        return "Ainda não enviada."
    ac = res["aceitas"]
    partes = [f"Enviada a {res['enviadas']}", f"{ac} {'aceitou' if ac == 1 else 'aceitaram'} ({round(res['taxa'] * 100)}%)"]
    if res["mais_mes"]:
        partes.append(f"+{m.moeda(res['mais_mes'])}/mês")
    return " · ".join(partes)


def descontos_acabando(con, hoje=None, dias=7) -> list[dict]:
    """Quem aceitou uma oferta com prazo que acaba em até `dias` dias (ou já acabou) e ainda paga o valor da oferta: é hora de voltar ao normal."""
    h = _iso(hoje)
    lim = (dt.date.fromisoformat(h) + dt.timedelta(days=dias)).isoformat()
    out = []
    for r in con.execute("""SELECT r.cliente_id, r.oferta_id, r.ate_desconto, c.nome, c.telefone, c.valor, o.titulo, o.valor_normal, o.valor_oferta
                            FROM oferta_respostas r JOIN ofertas o ON o.id=r.oferta_id AND o.excluido_em IS NULL
                            JOIN clientes c ON c.id=r.cliente_id AND c.excluido_em IS NULL AND c.status='ativo'
                            WHERE r.excluido_em IS NULL AND r.status='aceitou' AND r.encerrado_em IS NULL
                            AND r.ate_desconto IS NOT NULL AND r.ate_desconto <= ? ORDER BY r.ate_desconto, c.nome""", (lim,)):
        if abs(float(r["valor"] or 0) - float(r["valor_oferta"])) < 0.005:   # já voltou (ou nunca foi atualizado)? não há o que avisar
            out.append(dict(r))
    return out
