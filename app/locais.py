"""Novo local (academia, condomínio...): grava os custos do local e copia a grade de um local de referência.

O preço não fica guardado: o motor de preços (precos.custo_servico) lê estes custos na hora, junto com o seu
salário/hora, o tempo de deslocamento e o rateio dos custos fixos. Mudou um custo, todos os preços do local mudam.
Grade: copia os horários da referência, todos livres (sem grade na referência: Seg-Sáb, 05h-23h). O multiplicador de cada hora
e a situação de cada horário (ocupado, indisponível) valem para todos os locais: ficam em Grade > Multiplicadores e na Grade.
"""
import sqlite3
import unicodedata

from . import precos

CAMPOS = ("taxa_aula", "taxa_pessoa_extra", "max_pessoas", "deslocamento", "tempo_deslocamento", "taxa_mensal", "aulas_mes")


def custo_aula_local(con, local: str) -> float:
    """R$ por aula (1 pessoa) que o local custa: CIA = taxa_cia[1] + a ida; local criado aqui = seus custos; outro = 0."""
    from . import db
    p = {"taxa_cia": precos.taxas_cia(con)[0], "cia_desloc": db.parametros(con, "cia_deslocamento"), "locais": precos.custos_locais(con)}
    return precos.custo_aula_local(p, local)


def referencias(con) -> list[str]:
    """Locais de onde copiar a grade: a CIA e os criados aqui."""
    feitos = [r[0] for r in con.execute("SELECT local FROM locais_custos ORDER BY local")]
    return ["CIA"] + [x for x in feitos if x != "CIA"]


def _chave_nome(nome: str | None) -> str:
    """Nome do local sem acento, maiúsculas nem espaços nas pontas: como a agenda e as contas automáticas comparam."""
    return unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().strip().lower()


def criar_local(con, nome: str, referencia: str = "CIA", **custos) -> dict:
    """Cria o local e devolve {"horarios": n}. ValueError com a frase para a tela."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Dê um nome ao local")
    if _chave_nome(nome) == _chave_nome("CIA"):
        raise ValueError("A CIA já existe: a taxa dela fica em Configurações > Taxa da CIA")
    outro = next((r[0] for r in con.execute("SELECT local FROM locais_custos")
                  if _chave_nome(r[0]) == _chave_nome(nome)), None)
    if outro:  # mesmo local escrito de outro jeito: seriam duas contas para as mesmas aulas
        raise ValueError(f"'{outro}' já existe. Use esse nome ou edite o local na Grade")
    if referencia not in referencias(con):
        raise ValueError("Escolha a CIA ou um local criado aqui para copiar a grade")
    c = _custos(custos)
    try:
        return _gravar(con, nome, referencia, c)
    except sqlite3.IntegrityError:   # outro aparelho criou o mesmo local ao mesmo tempo
        raise ValueError(f"'{nome}' já existe. Recarregue a tela") from None


def _custos(custos: dict) -> dict:
    c = {k: max(0.0, float(custos.get(k) or 0)) for k in CAMPOS}
    c["max_pessoas"] = int(c["max_pessoas"])
    if c["taxa_mensal"] and not c["aulas_mes"]:
        raise ValueError("Com taxa mensal, diga quantas aulas por mês você dá nesse local (para dividir a taxa)")
    return c


def _criado_aqui(con, nome: str):
    row = con.execute("SELECT * FROM locais_custos WHERE local=?", ((nome or "").strip(),)).fetchone()
    if not row or nome.strip() == "CIA":
        raise ValueError("Só dá para mudar locais criados pelo '+ Novo local'")
    return row


def editar_local(con, nome: str, **custos) -> None:
    """Troca os custos de um local criado aqui. Os preços acompanham sozinhos (o motor lê os custos na hora).
    O nome não muda: ele está gravado nos alunos, na agenda, na grade e nas contas. A grade fica como está."""
    nome = _criado_aqui(con, nome)["local"]
    c = _custos(custos)
    with con:
        con.execute(f"UPDATE locais_custos SET {', '.join(k + '=?' for k in CAMPOS)} WHERE local=?", (*(c[k] for k in CAMPOS), nome))


def excluir_local(con, nome: str) -> None:
    """Apaga um local criado aqui (custos, preços, grade e o nome da lista) se ninguém mais usa.
    Aulas e contas antigas ficam: guardam o nome como texto."""
    nome = _criado_aqui(con, nome)["local"]
    alunos = con.execute("SELECT COUNT(*) FROM clientes WHERE local=? AND excluido_em IS NULL AND status != 'inativo'", (nome,)).fetchone()[0]
    fixos = con.execute("""SELECT COUNT(*) FROM agenda_fixos f JOIN clientes c ON c.id=f.cliente_id
                           WHERE f.local=? AND f.excluido_em IS NULL AND c.excluido_em IS NULL AND c.status != 'inativo'""", (nome,)).fetchone()[0]
    grade = con.execute("SELECT COUNT(*) FROM grade_slots WHERE local=? AND status='ocupado'", (nome,)).fetchone()[0]
    if alunos or fixos or grade:
        raise ValueError(f"'{nome}' ainda está em uso ({alunos} aluno(s), {fixos} horário(s) fixo(s), {grade} na Grade). "
                         "Mude esses alunos de local antes de excluir")
    with con:
        con.execute("DELETE FROM grade_slots WHERE local=?", (nome,))
        con.execute("DELETE FROM precos_base WHERE local=?", (nome,))
        con.execute("DELETE FROM locais_custos WHERE local=?", (nome,))
        con.execute("DELETE FROM parametros WHERE grupo='lista_locais' AND chave=?", (nome,))


def _gravar(con, nome, referencia, c) -> dict:
    with con:
        con.execute(f"""INSERT INTO locais_custos (local, {', '.join(CAMPOS)}, referencia) VALUES (?,{','.join('?' * len(CAMPOS))},?)""",
                    (nome, *(c[k] for k in CAMPOS), referencia))
        con.execute("INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem) "
                    "VALUES ('lista_locais', ?, ?, (SELECT COALESCE(MAX(ordem),0)+1 FROM parametros WHERE grupo='lista_locais'))", (nome, nome))
        slots = con.execute("SELECT tipo_calculo, dia, hora, multiplicador FROM grade_slots WHERE local=?", (referencia,)).fetchall()
        if not slots:
            slots = [(t, d, h, 1.0) for t in ("Pacotes", "Mensalidades") for d in range(1, 7) for h in range(5, 24)]
        antes = con.execute("SELECT COUNT(*) FROM grade_slots WHERE local=?", (nome,)).fetchone()[0]
        con.executemany("INSERT OR IGNORE INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador) VALUES (?,?,?,?,'livre',?)",
                        [(s[0], s[1], nome, s[2], s[3] or 1) for s in slots])
        depois = con.execute("SELECT COUNT(*) FROM grade_slots WHERE local=?", (nome,)).fetchone()[0]
    return {"horarios": depois - antes}
