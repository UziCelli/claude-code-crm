"""Novo local (academia, condomínio...): grava os custos e gera os preços e a grade a partir de um local de referência.

Preços: copia os planos com aula (Pacote de Aulas e Mensalidade) do local de referência e troca o custo do local:
custo novo = custo da referência - (custo por aula da referência x sessões) + (custo por aula do novo local x sessões).
  - modo "margem": o preço sobe ou desce junto com o custo, para a margem ficar a mesma;
  - modo "preco": o preço fica igual; só a margem muda.
Grade: copia os horários e multiplicadores da referência, todos livres (sem grade na referência: Seg-Sáb, 05h-23h).
"""
from . import precos

MODOS = ("margem", "preco")
CAMPOS = ("taxa_aula", "taxa_pessoa_extra", "max_pessoas", "deslocamento", "tempo_deslocamento", "taxa_mensal", "aulas_mes")
TIPOS_COM_AULA = ("Pacote de Aulas", "Mensalidade")


def custo_aula_local(con, local: str) -> float:
    """R$ por aula (1 pessoa) que o local cobra: CIA = taxa_cia[1]; local criado aqui = seus custos; outro = 0."""
    if local == "CIA":
        return precos.taxas_cia(con)[0].get(1, 0.0)
    c = precos.custos_locais(con).get(local)
    return precos.custo_por_aula(c) if c else 0.0


def criar_local(con, nome: str, referencia: str = "CIA", modo: str = "margem", **custos) -> dict:
    """Cria o local e devolve {"precos": n, "horarios": n}. ValueError com a frase para a tela."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Dê um nome ao local")
    if modo not in MODOS:
        raise ValueError("Escolha manter a margem ou manter o preço")
    if con.execute("SELECT 1 FROM precos_base WHERE local=? LIMIT 1", (nome,)).fetchone():
        raise ValueError(f"'{nome}' já tem preços. Para mudar, use Configurações > Preços base")
    c = {k: max(0.0, float(custos.get(k) or 0)) for k in CAMPOS}
    c["max_pessoas"] = int(c["max_pessoas"])
    if c["taxa_mensal"] and not c["aulas_mes"]:
        raise ValueError("Com taxa mensal, diga quantas aulas por mês você dá nesse local (para dividir a taxa)")
    ref_aula = custo_aula_local(con, referencia)
    novo_aula = precos.custo_por_aula(c)
    linhas = con.execute(f"SELECT * FROM precos_base WHERE local=? AND tipo_servico IN ({','.join('?' * len(TIPOS_COM_AULA))})",
                         (referencia, *TIPOS_COM_AULA)).fetchall()
    with con:
        con.execute("""INSERT INTO locais_custos (local, taxa_aula, taxa_pessoa_extra, max_pessoas, deslocamento, tempo_deslocamento,
                       taxa_mensal, aulas_mes, referencia, modo) VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(local) DO UPDATE SET taxa_aula=excluded.taxa_aula, taxa_pessoa_extra=excluded.taxa_pessoa_extra,
                       max_pessoas=excluded.max_pessoas, deslocamento=excluded.deslocamento, tempo_deslocamento=excluded.tempo_deslocamento,
                       taxa_mensal=excluded.taxa_mensal, aulas_mes=excluded.aulas_mes, referencia=excluded.referencia, modo=excluded.modo""",
                    (nome, *(c[k] for k in CAMPOS), referencia, modo))
        con.execute("INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem) "
                    "VALUES ('lista_locais', ?, ?, (SELECT COALESCE(MAX(ordem),0)+1 FROM parametros WHERE grupo='lista_locais'))", (nome, nome))
        for b in linhas:
            s = float(b["sessoes_mes"] or 0)
            custo_ref = float(b["custo_operacional"] or 0)
            custo = max(0.0, custo_ref + (novo_aula - ref_aula) * s)
            preco = float(b["preco_base"])
            if modo == "margem" and custo_ref > 0:   # margem = 1 - taxas - custo/preço: mesma razão custo/preço = mesma margem
                preco = preco * custo / custo_ref
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
    return {"precos": len(linhas), "horarios": depois - antes}
