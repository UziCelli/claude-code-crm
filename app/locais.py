"""Locais (academia, condomínio...): os custos de cada local, editar, excluir e a prévia do preço. Um pop-up só para todos, CIA incluída.

O preço não fica guardado: o motor de preços (precos.custo_servico) lê estes custos na hora, junto com o seu
salário/hora, o tempo de deslocamento e o rateio dos custos fixos. Mudou um custo, todos os preços do local mudam.
Qualquer local que não é a CIA se edita igual: os criados pelo "+ Novo local" e os que vieram da lista (SmartFit, Condomínio...).
Um local da lista sem custos ganha a linha em locais_custos no primeiro "Editar local".
Grade: um local novo copia os horários da referência, todos livres (sem grade na referência: Seg-Sáb, 05h-23h). O multiplicador de cada hora
e a situação de cada horário (ocupado, indisponível) valem para todos os locais: ficam em Grade > Multiplicadores e na Grade.
"""
import sqlite3
import unicodedata

from . import db, precos

CAMPOS = ("taxa_aula", "taxa_pessoa_extra", "max_pessoas", "deslocamento", "tempo_deslocamento", "taxa_mensal", "aulas_mes")
PESSOAS_CIA = (1, 2, 3)   # o pop-up da CIA sempre mostra estes (e os a mais que já existirem em taxa_cia)


def custo_aula_local(con, local: str) -> float:
    """R$ por aula (1 pessoa) que o local custa: CIA = taxa_cia[1] + a ida + a taxa mensal ÷ aulas; local com custos = seus custos; outro = 0."""
    p = {"taxa_cia": precos.taxas_cia(con)[0], "cia_desloc": db.parametros(con, "cia_deslocamento"),
         "cia_mensal": db.parametros(con, "cia_mensal"), "locais": precos.custos_locais(con)}
    return precos.custo_aula_local(p, local)


def referencias(con) -> list[str]:
    """Locais de onde copiar a grade: a CIA e os que têm custos."""
    feitos = [r[0] for r in con.execute("SELECT local FROM locais_custos ORDER BY local")]
    return ["CIA"] + [x for x in feitos if x != "CIA"]


def _chave_nome(nome: str | None) -> str:
    """Nome do local sem acento, maiúsculas nem espaços nas pontas: como a agenda e as contas automáticas comparam."""
    return unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().strip().lower()


def _sem_espaco(nome: str | None) -> str:
    """Para achar o mesmo local escrito de outro jeito: 'Smart Fit' e 'SmartFit' são o mesmo."""
    return "".join(_chave_nome(nome).split())


def eh_cia(nome: str | None) -> bool:
    return _chave_nome(nome) == "cia"


def nomes(con) -> list[str]:
    """Todos os locais que existem: a lista de Configurações, os da Grade e os que têm custos."""
    todos = db.lista(con, "lista_locais")
    todos += [r[0] for r in con.execute("SELECT DISTINCT local FROM grade_slots")]
    todos += [r[0] for r in con.execute("SELECT local FROM locais_custos")]
    return list(dict.fromkeys(x for x in todos if x and x.strip()))


def criar_local(con, nome: str, referencia: str = "CIA", **custos) -> dict:
    """Cria o local e devolve {"horarios": n}. ValueError com a frase para a tela."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Dê um nome ao local")
    if eh_cia(nome):
        raise ValueError("A CIA já existe: escolha a CIA na Grade e clique em Editar local")
    outro = next((x for x in nomes(con) if _sem_espaco(x) == _sem_espaco(nome)), None)
    # o mesmo nome de um local da lista que ainda não tem custos (SmartFit) ganha os custos aqui, como no Editar local
    sem_custos = outro is not None and outro.strip() == nome and \
        not con.execute("SELECT 1 FROM locais_custos WHERE local=?", (outro,)).fetchone()
    if outro and not sem_custos:  # mesmo local escrito de outro jeito: seriam duas contas para as mesmas aulas
        raise ValueError(f"'{outro}' já existe. Use esse nome ou edite o local na Grade")
    nome = outro or nome
    if referencia not in referencias(con):
        raise ValueError("Escolha a CIA ou um local com custos para copiar a grade")
    c = _custos(custos)
    try:
        with con:
            _inserir(con, nome, c, referencia)
            return {"horarios": _copiar_grade(con, nome, referencia)}
    except sqlite3.IntegrityError:   # outro aparelho criou o mesmo local ao mesmo tempo
        raise ValueError(f"'{nome}' já existe. Recarregue a tela") from None


def _custos(custos: dict) -> dict:
    c = {k: max(0.0, float(custos.get(k) or 0)) for k in CAMPOS}
    c["max_pessoas"] = int(c["max_pessoas"])
    if c["taxa_mensal"] and not c["aulas_mes"]:
        raise ValueError("Com taxa mensal, diga quantas aulas por mês você dá nesse local (para dividir a taxa)")
    return c


def _editavel(con, nome: str) -> str:
    """O nome do local como está gravado, se dá para editar ou excluir. A CIA fica fora: edita por editar_cia e não exclui."""
    nome = (nome or "").strip()
    if eh_cia(nome):
        raise ValueError("A CIA não dá para excluir: só editar")
    achado = next((x for x in nomes(con) if x.strip() == nome), None)
    if not achado:
        raise ValueError(f"O local '{nome}' não existe mais. Recarregue a tela")
    return achado


def editar_local(con, nome: str, grupo: dict | None = None, **custos) -> dict:
    """Troca os custos de qualquer local e devolve {"horarios": n criados}. Os preços acompanham sozinhos
    (o motor lê os custos na hora). Local da lista sem custos (SmartFit) ganha a linha agora; sem grade, copia a da CIA.
    A CIA usa os mesmos campos e grava nos parâmetros dela (editar_cia; grupo = preço da aula com 2, 3 pessoas).
    O nome não muda: ele está gravado nos alunos, na agenda, na grade e nas contas. A grade que já existe fica como está."""
    if eh_cia(nome):
        editar_cia(con, grupo, **custos)
        return {"horarios": 0}
    nome = _editavel(con, nome)
    c = _custos(custos)
    with con:
        con.execute("INSERT OR IGNORE INTO locais_custos (local) VALUES (?)", (nome,))
        con.execute(f"UPDATE locais_custos SET {', '.join(k + '=?' for k in CAMPOS)} WHERE local=?", (*(c[k] for k in CAMPOS), nome))
        _na_lista(con, nome)
        tem_grade = con.execute("SELECT COUNT(*) FROM grade_slots WHERE local=?", (nome,)).fetchone()[0]
        return {"horarios": 0 if tem_grade else _copiar_grade(con, nome, "CIA")}


def excluir_local(con, nome: str) -> None:
    """Apaga qualquer local que não é a CIA (custos, preços, grade e o nome da lista) se ninguém mais usa.
    Aulas e contas antigas ficam: guardam o nome como texto. Um local da lista inicial não volta quando o app abre de novo."""
    nome = _editavel(con, nome)
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
        con.execute("DELETE FROM parametros WHERE grupo='lista_locais' AND (chave=? OR valor_texto=?)", (nome, nome))
        db.marcar_removido(con, "lista_locais", nome)


def _inserir(con, nome, c, referencia) -> None:
    con.execute(f"""INSERT INTO locais_custos (local, {', '.join(CAMPOS)}, referencia) VALUES (?,{','.join('?' * len(CAMPOS))},?)""",
                (nome, *(c[k] for k in CAMPOS), referencia))
    _na_lista(con, nome)


def _na_lista(con, nome) -> None:
    """Põe o local na lista de Configurações (Agenda, Propostas e fichas escolhem dela), se ainda não está."""
    if nome in db.lista(con, "lista_locais"):
        return
    con.execute("INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem) "
                "VALUES ('lista_locais', ?, ?, (SELECT COALESCE(MAX(ordem),0)+1 FROM parametros WHERE grupo='lista_locais'))", (nome, nome))


def _copiar_grade(con, nome, referencia) -> int:
    """Copia os horários da referência para o local, todos livres; devolve quantos entraram. Chamar dentro de `with con`."""
    slots = con.execute("SELECT tipo_calculo, dia, hora, multiplicador FROM grade_slots WHERE local=?", (referencia,)).fetchall()
    if not slots:
        slots = [(t, d, h, 1.0) for t in ("Pacotes", "Mensalidades") for d in range(1, 7) for h in range(5, 24)]
    antes = con.execute("SELECT COUNT(*) FROM grade_slots WHERE local=?", (nome,)).fetchone()[0]
    con.executemany("INSERT OR IGNORE INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador) VALUES (?,?,?,?,'livre',?)",
                    [(s[0], s[1], nome, s[2], s[3] or 1) for s in slots])
    return con.execute("SELECT COUNT(*) FROM grade_slots WHERE local=?", (nome,)).fetchone()[0] - antes


# ---------- CIA ----------
def cia_atual(con) -> dict:
    """Os custos da CIA nos mesmos campos de um local (CAMPOS, sem a pessoa a mais) + grupo {pessoas: R$ da aula com elas}:
    a CIA cobra a aula pelo nº de pessoas (taxa_cia), em vez de uma taxa por pessoa a mais."""
    taxas, maximo = precos.taxas_cia(con)
    ida, mensal = db.parametros(con, "cia_deslocamento"), db.parametros(con, "cia_mensal")
    return {"taxa_aula": float(taxas.get(1) or 0),
            "grupo": {n: float(taxas.get(n) or 0) for n in sorted(set(taxas) | set(PESSOAS_CIA)) if n > 1},
            "max_pessoas": maximo, "deslocamento": float(ida.get("reais_por_aula") or 0),
            "tempo_deslocamento": float(ida.get("minutos_por_aula") or 0),
            "taxa_mensal": float(mensal.get("taxa_mensal") or 0), "aulas_mes": float(mensal.get("aulas_mes") or 0)}


def _cia(con, custos: dict, grupo: dict | None) -> dict:
    """Os campos do pop-up (os mesmos de um local) no formato do motor: {taxa_cia, cia_max, cia_desloc, cia_mensal}.
    grupo: {pessoas: R$ da aula com elas}; quem não veio fica como está."""
    c = _custos(custos)   # os mesmos números e a mesma regra da taxa mensal de um local
    if c["taxa_aula"] <= 0:
        raise ValueError("Diga quanto a CIA cobra pela aula de 1 pessoa")
    if c["max_pessoas"] < 1:
        raise ValueError("Máximo de pessoas na CIA: pelo menos 1")
    taxas = dict(precos.taxas_cia(con)[0])
    for n, v in (grupo or {}).items():
        if float(v or 0) <= 0:
            raise ValueError(f"Diga quanto a CIA cobra pela aula com {int(n)} pessoas")
        taxas[int(n)] = float(v)
    taxas[1] = c["taxa_aula"]
    return {"taxa_cia": dict(sorted(taxas.items())), "cia_max": c["max_pessoas"],
            "cia_desloc": {"reais_por_aula": c["deslocamento"], "minutos_por_aula": c["tempo_deslocamento"]},
            "cia_mensal": {"taxa_mensal": c["taxa_mensal"], "aulas_mes": c["aulas_mes"]}}


def editar_cia(con, grupo: dict | None = None, **custos) -> None:
    """Grava o Editar local da CIA nos parâmetros de sempre (taxa_cia, cia_deslocamento, cia_mensal: os mesmos de Configurações).
    Preços e a conta da CIA em aberto acompanham."""
    c = _cia(con, custos, grupo)
    linhas = [("taxa_cia", str(n), v) for n, v in c["taxa_cia"].items()] + [("taxa_cia", "maximo_pessoas", c["cia_max"])]
    linhas += [("cia_deslocamento", k, v) for k, v in c["cia_desloc"].items()]
    linhas += [("cia_mensal", k, v) for k, v in c["cia_mensal"].items()]
    with con:
        for grupo_, chave, valor in linhas:
            con.execute("""INSERT OR IGNORE INTO parametros (grupo, chave, valor, ordem)
                           VALUES (?, ?, 0, (SELECT COALESCE(MAX(ordem),0)+1 FROM parametros WHERE grupo=?))""", (grupo_, chave, grupo_))
            con.execute("UPDATE parametros SET valor=? WHERE grupo=? AND chave=?", (valor, grupo_, chave))


# ---------- prévia do preço (pop-up do local e da CIA) ----------
def contas_fixas_do_local(con, nome: str) -> list[dict]:
    """Contas fixas da PJ (Contas a pagar > recorrências) que citam o local: com custos no local, elas saem do rateio
    dos custos fixos (financeiro.custos_fixos_rateio) e o preço só as cobra pela Taxa mensal."""
    from . import contas_auto, financeiro
    from .main import mes_atual
    if not (nome or "").strip() or eh_cia(nome):
        return []
    return [i for i in financeiro.custos_fixos_rateio(con, mes_atual(), [])["itens"] if contas_auto.eh_do_local(i["descricao"], nome)]


def _plano(tipo: str, ref: int, local: str) -> dict:
    """O mesmo plano de referência da Grade (main.plano_referencia): 8 aulas ou 2x/semana."""
    if tipo == "Mensalidades":
        return precos.base_motor("Mensalidade", freq=ref or 2, local=local)
    return precos.base_motor("Pacote de Aulas", qtd=ref or 8, local=local)


def _conta(base: dict, p: dict, local: str, maximo: int) -> dict:
    """As partes de 1 aula (precos.decompor), o preço mínimo por aula e o preço por pessoa em grupo (até 3)."""
    d = precos.decompor(dict(base), p, local)
    sessoes = d["sessoes"]
    d["minimo"] = round(precos.calcular(dict(base), p, local=local)["preco_minimo"] / sessoes, 2)
    d["grupo"] = []
    for n in range(2, min(maximo or 3, 3) + 1):
        try:
            d["grupo"].append({"pessoas": n, "preco": round(precos.calcular(dict(base), p, pessoas=n, local=local)["preco_pessoa"] / sessoes, 2)})
        except ValueError:
            pass
    return d


def previa(con, nome: str = "", custos: dict | None = None, grupo: dict | None = None, cia: bool = False,
           tipo: str = "Pacotes", ref: int = 0) -> dict:
    """Quanto 1 aula (1 pessoa, horário x1,00) custa e quanto sai com os custos digitados, sem gravar nada.
    custos: os campos do pop-up (CAMPOS, iguais para todo local); cia=True: o pop-up é o da CIA, com grupo {pessoas: R$ da aula}.
    {local, plano, agora: partes do preço, hoje: preço e custo com o que está salvo (None num local novo), contas_fixas}.
    ValueError com a frase para a tela."""
    if cia:
        local = "CIA"
        troca = _cia(con, custos or {}, grupo)
        maximo = troca["cia_max"]
    else:
        local = (nome or "").strip() or "Novo local"
        if eh_cia(local):
            raise ValueError("A CIA já existe: escolha a CIA na Grade e clique em Editar local")
        c = _custos(custos or {})
        troca, maximo = {"locais": {local: {"local": local, **c}}}, c["max_pessoas"]
    base = _plano(tipo, ref, local)
    agora = _conta(base, precos.carregar_parametros(con, troca), local, maximo)
    existe = local == "CIA" or any(x.strip() == local for x in nomes(con))
    hoje = None
    if existe:
        h = precos.decompor(dict(base), precos.carregar_parametros(con), local)
        hoje = {"preco": h["preco"], "custo": h["custo"]}
    plano = f"pacote de {base['qtd_aulas']} aulas" if tipo != "Mensalidades" else f"mensalidade {base['freq_semanal']}x/semana"
    return {"local": local, "plano": plano, "agora": agora, "hoje": hoje, "contas_fixas": contas_fixas_do_local(con, local)}
