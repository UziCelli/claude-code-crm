"""Indicações: quem indicou quem e o presente que o indicador ganha.

O presente SOMA valor, não desconta: brinde (avaliação física, camiseta, garrafa...), nunca desconto nem crédito. Por isso nada aqui toca em
crédito, mensalidade ou no estado do aluno.
Quando o presente é devido: no 1º pagamento de verdade do indicado (entrada paga de aluno; empréstimo não conta).
O presente é um cliente_eventos tipo 'brinde' do indicador, com indicado_id = o indicado: no máximo 1 por indicado.
"""
from . import financeiro

SUGESTOES = ["Avaliação física", "Camiseta", "Garrafa", "Treino extra para casa"]
CANAL = "Indicação"   # canal de origem de quem veio por indicação (lista_canais)

# 1º pagamento de verdade do indicado (data em que caiu) e o presente já dado (o mais antigo ativo), numa consulta só
_BASE = f"""
SELECT r.id AS indicador_id, r.nome AS indicador, i.id AS indicado_id, i.nome AS indicado,
       (SELECT MIN(l.pago_em) FROM lancamentos l WHERE l.cliente_id = i.id AND l.escopo='PJ' AND l.tipo='entrada'
           AND l.pago_em IS NOT NULL AND l.excluido_em IS NULL AND l.categoria != '{financeiro.EMPRESTIMO}') AS pago_em,
       (SELECT MIN(e.id) FROM cliente_eventos e WHERE e.tipo='brinde' AND e.indicado_id = i.id AND e.excluido_em IS NULL) AS brinde_id,
       (SELECT e.data FROM cliente_eventos e WHERE e.tipo='brinde' AND e.indicado_id = i.id AND e.excluido_em IS NULL ORDER BY e.id LIMIT 1) AS brinde_data,
       (SELECT e.descricao FROM cliente_eventos e WHERE e.tipo='brinde' AND e.indicado_id = i.id AND e.excluido_em IS NULL ORDER BY e.id LIMIT 1) AS brinde_desc
FROM clientes i JOIN clientes r ON r.id = i.indicado_por
WHERE i.excluido_em IS NULL AND r.excluido_em IS NULL AND i.id != r.id
"""


def pendentes(con) -> list[dict]:
    """Presentes a dar: o indicado já pagou o 1º pagamento e o indicador ainda não ganhou nada por ele. Mais antigo primeiro."""
    linhas = [dict(r) for r in con.execute(_BASE)]
    out = [r for r in linhas if r["pago_em"] and not r["brinde_id"]]
    return sorted(out, key=lambda r: (r["pago_em"], r["indicado_id"]))


def do_aluno(con, cid: int) -> list[dict]:
    """Quem este aluno indicou, com a situação de cada um: 'aguardando' (sem 1º pagamento), 'pendente' (pagou, falta o presente)
    ou 'entregue' (data e o que foi dado)."""
    out = []
    for r in con.execute(_BASE + " AND r.id = ? ORDER BY i.id", (cid,)):
        r = dict(r)
        r["status"] = "aguardando"
        if r["brinde_id"]:
            prefixo = f"Presente pela indicação de {r['indicado']}: "
            desc = r["brinde_desc"] or ""
            r.update(status="entregue", data=r["brinde_data"], o_que=desc[len(prefixo):] if desc.startswith(prefixo) else desc)
        elif r["pago_em"]:
            r["status"] = "pendente"
        out.append(r)
    return out


def quem_indicou(con, cid: int) -> dict | None:
    """{id, nome} de quem indicou este aluno (None se ninguém ou se foi para a lixeira)."""
    r = con.execute("""SELECT r.id, r.nome FROM clientes i JOIN clientes r ON r.id = i.indicado_por
                       WHERE i.id=? AND r.excluido_em IS NULL""", (cid,)).fetchone()
    return dict(r) if r else None


def validar(con, texto, proprio_id: int | None = None) -> tuple[int | None, str | None]:
    """Confere o campo 'Indicado por' (id de aluno, vazio = ninguém). Devolve (id ou None, erro ou None). Ninguém indica a si mesmo."""
    texto = str(texto or "").strip()
    if not texto:
        return None, None
    if not texto.isdigit():
        return None, "Escolha quem indicou na lista."
    iid = int(texto)
    if proprio_id is not None and iid == proprio_id:
        return None, "Ninguém pode indicar a si mesmo."
    if not con.execute("SELECT 1 FROM clientes WHERE id=? AND excluido_em IS NULL", (iid,)).fetchone():
        return None, "Quem indicou não está no cadastro de alunos."
    return iid, None


def alunos_para_escolher(con, excluir: int | None = None) -> list[dict]:
    """Alunos (ativos e inativos) para o campo 'Indicado por', em ordem alfabética."""
    return [dict(r) for r in con.execute(
        "SELECT id, nome, status FROM clientes WHERE excluido_em IS NULL AND id != ? ORDER BY nome COLLATE NOCASE", (excluir or 0,))]


def registrar_presente(con, cid: int, iid: int, o_que: str, data: str, custo: float | None) -> tuple[str | None, str | None]:
    """Grava o presente do indicador `cid` pelo indicado `iid`. Devolve (mensagem, erro): um dos dois é None."""
    o_que = " ".join((o_que or "").split())
    if not o_que:
        return None, "Diga o que você deu."
    achou = [r for r in con.execute(_BASE + " AND r.id = ? AND i.id = ?", (cid, iid))]
    if not achou:
        return None, "Essa indicação não existe."
    r = achou[0]
    if r["brinde_id"]:
        return None, f"O presente pela indicação de {r['indicado']} já foi registrado."
    if not r["pago_em"]:
        return None, f"{r['indicado']} ainda não fez o 1º pagamento: registre o pagamento primeiro."
    with con:
        con.execute("""INSERT INTO cliente_eventos (cliente_id, tipo, data, valor, descricao, indicado_id) VALUES (?, 'brinde', ?, ?, ?, ?)""",
                    (cid, data, custo, f"Presente pela indicação de {r['indicado']}: {o_que}", iid))
    return f"Presente registrado: {o_que} para {r['indicador']}.", None
