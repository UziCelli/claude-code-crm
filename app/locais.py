"""Novo local (academia, condomínio...): grava os custos e gera os preços e a grade a partir de um local de referência.

Preços: copia os planos com aula (Pacote de Aulas e Mensalidade) do local de referência e troca o custo do local:
custo novo = custo da referência - (custo por aula da referência x sessões) + (custo por aula do novo local x sessões).
  - modo "margem": o preço sobe ou desce junto com o custo, para a margem ficar a mesma;
  - modo "preco": o preço fica igual; só a margem muda;
  - modo "custo": o preço sai do custo de verdade do local (seu pró-labore pela regra do tempo, deslocamento, taxas),
    na margem mínima do plano. Bom para local sem taxa: copiar a margem da CIA deixava o preço baixo demais.
Grade: copia os horários e multiplicadores da referência, todos livres (sem grade na referência: Seg-Sáb, 05h-23h).
"""
import sqlite3
import unicodedata

from . import precos

MODOS = ("margem", "preco", "custo")
CAMPOS = ("taxa_aula", "taxa_pessoa_extra", "max_pessoas", "deslocamento", "tempo_deslocamento", "taxa_mensal", "aulas_mes")
TIPOS_COM_AULA = ("Pacote de Aulas", "Mensalidade")
TIPOS_TAXA_CIA = TIPOS_COM_AULA + ("Aula avulsa",)   # planos da CIA com a taxa por aula embutida no custo


def custo_aula_local(con, local: str) -> float:
    """R$ por aula (1 pessoa) que o local cobra: CIA = taxa_cia[1]; local criado aqui = seus custos; outro = 0."""
    if local == "CIA":
        return precos.taxas_cia(con)[0].get(1, 0.0)
    c = precos.custos_locais(con).get(local)
    return precos.custo_por_aula(c) if c else 0.0


def ajustar_custos_cia(con, antiga: float, nova: float) -> None:
    """A taxa da CIA (1 pessoa) mudou em Configurações: o custo dos preços da CIA (que já traz a taxa embutida) acompanha.
    Um UPDATE só, dentro da transação de quem chama. Sem isso a margem da CIA não mudava e o "+ Novo local" descontava a taxa nova
    de um custo com a taxa velha."""
    dif = float(nova or 0) - float(antiga or 0)
    if abs(dif) < 1e-9:
        return
    con.execute("""UPDATE precos_base SET custo_operacional = COALESCE(custo_operacional,0) + ? * sessoes_mes,
                   custo_total = COALESCE(custo_total,0) + ? * sessoes_mes
                   WHERE local='CIA' AND sessoes_mes > 0 AND tipo_servico IN (?,?,?)""", (dif, dif, *TIPOS_TAXA_CIA))


def referencias(con) -> list[str]:
    """Locais que servem de base para copiar: a CIA e os criados aqui (o sistema sabe quanto custam por aula).
    Locais da planilha ficam de fora: a taxa deles está misturada no custo e seria cobrada duas vezes."""
    feitos = [r[0] for r in con.execute("SELECT local FROM locais_custos ORDER BY local")]
    return ["CIA"] + [x for x in feitos if x != "CIA"]


def _chave_nome(nome: str | None) -> str:
    """Nome do local sem acento, maiúsculas nem espaços nas pontas: como a agenda e as contas automáticas comparam."""
    return unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().strip().lower()


def criar_local(con, nome: str, referencia: str = "CIA", modo: str = "margem", **custos) -> dict:
    """Cria o local e devolve {"precos": n, "horarios": n}. ValueError com a frase para a tela."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Dê um nome ao local")
    if modo not in MODOS:
        raise ValueError("Escolha manter a margem, manter o preço ou montar pelo custo")
    ja = next((r[0] for r in con.execute("SELECT DISTINCT local FROM precos_base") if _chave_nome(r[0]) == _chave_nome(nome)), None)
    if ja:   # "cia" = "CIA" e "Acadêmia" = "Academia": não cria um segundo local com o mesmo nome (a agenda não separa)
        raise ValueError(f"'{ja}' já tem preços. Para mudar, use Configurações > Preços base")
    outro = next((r[0] for r in con.execute("SELECT local FROM locais_custos")
                  if r[0] != nome and _chave_nome(r[0]) == _chave_nome(nome)), None)
    if outro:  # mesmo local escrito de outro jeito (sem preços ainda): seriam duas contas para as mesmas aulas
        raise ValueError(f"'{outro}' já existe. Use esse nome")
    if referencia not in referencias(con):
        raise ValueError("Escolha a CIA ou um local criado aqui para copiar os preços")
    c = _custos(custos)
    ref_aula = custo_aula_local(con, referencia)
    novo_aula = precos.custo_por_aula(c)
    linhas = con.execute(f"SELECT * FROM precos_base WHERE local=? AND tipo_servico IN ({','.join('?' * len(TIPOS_COM_AULA))})",
                         (referencia, *TIPOS_COM_AULA)).fetchall()
    try:
        return _gravar(con, nome, referencia, modo, c, novo_aula - ref_aula, linhas)
    except sqlite3.IntegrityError:   # outro aparelho criou o mesmo local ao mesmo tempo
        raise ValueError(f"'{nome}' já existe. Recarregue a tela") from None


def _custos(custos: dict) -> dict:
    c = {k: max(0.0, float(custos.get(k) or 0)) for k in CAMPOS}
    c["max_pessoas"] = int(c["max_pessoas"])
    if c["taxa_mensal"] and not c["aulas_mes"]:
        raise ValueError("Com taxa mensal, diga quantas aulas por mês você dá nesse local (para dividir a taxa)")
    return c


def _preco_novo(preco: float, custo_ref: float, custo: float, modo: str) -> tuple[float, bool]:
    """(preço, manteve?) — modo margem: mesma razão custo/preço = mesma margem; custo zero não dá razão, então o preço fica."""
    if modo != "margem" or custo == custo_ref:
        return preco, False
    if custo_ref > 0 and custo > 0:
        return preco * custo / custo_ref, False
    return preco, True


def _preco_pelo_custo(con, b, nome: str, custo: float) -> float:
    """Preço do plano no local pelo custo: o preço sugerido do motor (R$ inteiro na margem mínima), com 1 pessoa,
    sem multiplicador de horário, na forma de pagamento da linha. Lê os custos do local já gravados (deslocamento)."""
    p = precos.carregar_parametros(con)
    base = {**dict(b), "local": nome, "custo_operacional": custo}
    forma = b["forma_pagamento"] if b["forma_pagamento"] in p["taxas"] else "PIX"
    return precos.calcular(base, p, forma_pagamento=forma, local=nome)["preco_sugerido"]


def _criado_aqui(con, nome: str):
    row = con.execute("SELECT * FROM locais_custos WHERE local=?", ((nome or "").strip(),)).fetchone()
    if not row or nome.strip() == "CIA":
        raise ValueError("Só dá para mudar locais criados pelo '+ Novo local'")
    return row


def editar_local(con, nome: str, modo: str = "margem", **custos) -> dict:
    """Troca os custos de um local criado aqui e refaz os preços dele (Pacote e Mensalidade) pela diferença do custo por aula.
    O nome não muda: ele está gravado nos alunos, na agenda, na grade e nas contas. A grade fica como está."""
    if modo not in MODOS:
        raise ValueError("Escolha manter a margem, manter o preço ou montar pelo custo")
    antes = dict(_criado_aqui(con, nome))
    nome = antes["local"]
    c = _custos(custos)
    dif_aula = precos.custo_por_aula(c) - precos.custo_por_aula(antes)
    linhas = con.execute(f"SELECT * FROM precos_base WHERE local=? AND tipo_servico IN ({','.join('?' * len(TIPOS_COM_AULA))})",
                         (nome, *TIPOS_COM_AULA)).fetchall()
    mantidos = 0
    with con:
        con.execute(f"UPDATE locais_custos SET {', '.join(k + '=?' for k in CAMPOS)}, modo=? WHERE local=?",
                    (*(c[k] for k in CAMPOS), modo, nome))
        for b in linhas:
            s = float(b["sessoes_mes"] or 0)
            custo_ref = float(b["custo_operacional"] or 0)
            custo = max(0.0, custo_ref + dif_aula * s)
            if modo == "custo":
                preco, manteve = _preco_pelo_custo(con, b, nome, custo), False
            else:
                preco, manteve = _preco_novo(float(b["preco_base"]), custo_ref, custo, modo)
            mantidos += manteve
            con.execute("UPDATE precos_base SET preco_base=?, custo_operacional=?, custo_total=? WHERE id=?",
                        (round(preco, 2), round(custo, 2), round(float(b["custo_total"] or 0) - custo_ref + custo, 2), b["id"]))
    return {"precos": len(linhas), "mantidos": mantidos}


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


def _gravar(con, nome, referencia, modo, c, dif_aula, linhas) -> dict:
    with con:
        con.execute("""INSERT INTO locais_custos (local, taxa_aula, taxa_pessoa_extra, max_pessoas, deslocamento, tempo_deslocamento,
                       taxa_mensal, aulas_mes, referencia, modo) VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(local) DO UPDATE SET taxa_aula=excluded.taxa_aula, taxa_pessoa_extra=excluded.taxa_pessoa_extra,
                       max_pessoas=excluded.max_pessoas, deslocamento=excluded.deslocamento, tempo_deslocamento=excluded.tempo_deslocamento,
                       taxa_mensal=excluded.taxa_mensal, aulas_mes=excluded.aulas_mes, referencia=excluded.referencia, modo=excluded.modo""",
                    (nome, *(c[k] for k in CAMPOS), referencia, modo))
        con.execute("INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem) "
                    "VALUES ('lista_locais', ?, ?, (SELECT COALESCE(MAX(ordem),0)+1 FROM parametros WHERE grupo='lista_locais'))", (nome, nome))
        mantidos = 0
        for b in linhas:
            s = float(b["sessoes_mes"] or 0)
            custo_ref = float(b["custo_operacional"] or 0)
            custo = max(0.0, custo_ref + dif_aula * s)
            if modo == "custo":
                preco, manteve = _preco_pelo_custo(con, b, nome, custo), False
            else:
                preco, manteve = _preco_novo(float(b["preco_base"]), custo_ref, custo, modo)
            mantidos += manteve
            total = float(b["custo_total"] or 0) - custo_ref + custo
            con.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, sessoes_mes, preco_base,
                           custo_operacional, mao_obra, custo_total, origem) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (b["tipo_servico"], nome, b["forma_pagamento"], b["qtd_aulas"], b["freq_semanal"], s, round(preco, 2),
                         round(custo, 2), b["mao_obra"], round(total, 2), f"local:{referencia}"))
        slots = con.execute("SELECT tipo_calculo, dia, hora, multiplicador FROM grade_slots WHERE local=?", (referencia,)).fetchall()
        if not slots:
            slots = [(t, d, h, 1.0) for t in ("Pacotes", "Mensalidades") for d in range(1, 7) for h in range(5, 24)]
        antes = con.execute("SELECT COUNT(*) FROM grade_slots WHERE local=?", (nome,)).fetchone()[0]
        con.executemany("INSERT OR IGNORE INTO grade_slots (tipo_calculo, dia, local, hora, status, multiplicador) VALUES (?,?,?,?,'livre',?)",
                        [(s[0], s[1], nome, s[2], s[3] or 1) for s in slots])
        depois = con.execute("SELECT COUNT(*) FROM grade_slots WHERE local=?", (nome,)).fetchone()[0]
    return {"precos": len(linhas), "horarios": depois - antes, "mantidos": mantidos}
