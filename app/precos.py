"""Motor de preços. Custo e preço saem só dos parâmetros (Configurações, locais, Financeiro): nada da planilha.
O cálculo (calcular/calcular_misto) é função pura; carregar_parametros lê o banco uma vez."""
import math


def taxas_cia(con) -> tuple[dict, int]:
    """({pessoas: preço da aula na CIA}, máximo de pessoas por horário), dos parâmetros `taxa_cia`."""
    from . import db
    cia = db.parametros(con, "taxa_cia")
    return {int(k): v for k, v in cia.items() if k.isdigit()}, int(cia.get("maximo_pessoas", 3))


def carregar_parametros(con, troca: dict | None = None) -> dict:
    """Monta o dicionário de parâmetros a partir da tabela `parametros`.
    troca: custos simulados, sem gravar (a prévia do pop-up do local e da CIA): {"locais": {nome: custos}, "taxa_cia": {pessoas: R$},
    "cia_max": n, "cia_desloc": {reais_por_aula, minutos_por_aula}}. Entram antes das horas, do salário/hora e do rateio:
    a prévia passa pelo motor inteiro, igual ao preço depois de salvar."""
    from . import db, financeiro
    g = lambda grupo: db.parametros(con, grupo)  # noqa: E731
    taxa_cia, cia_max = taxas_cia(con)
    p = {
        "das": financeiro.pct_das(con),   # alíquota efetiva de hoje pela tabela do Simples
        "taxas": g("taxa_pagamento"),
        "margens": g("margem_minima"),
        "margens_alvo": g("margem_alvo"),   # a do preço de tabela (antes do desconto)
        "taxa_cia": taxa_cia,
        "cia_max": cia_max,
        "grupo_mo": {int(k): v for k, v in g("grupo_mao_obra_extra").items()},
        "locais": custos_locais(con),
        "cia_desloc": g("cia_deslocamento"),   # ida até a CIA: reais_por_aula e minutos_por_aula
        "mo": g("mao_obra"),
    }
    if troca:
        p["locais"] = {**p["locais"], **(troca.get("locais") or {})}
        for k in ("taxa_cia", "cia_max", "cia_desloc"):
            if troca.get(k) is not None:
                p[k] = troca[k]
    from .main import horas_trabalho_detalhe
    trabalho = horas_trabalho_detalhe(con, p)   # uma vez só: salário e custos fixos dividem pela mesma base
    auto = valor_hora_automatico(con, p, trabalho)
    p["salario_hora"] = auto
    if auto["usado"]:
        p["mo"] = {**p["mo"], "valor_hora": auto["valor_hora"]}
    p["rateio"] = rateio_fixos(con, p, trabalho["total"])
    p["rateio_hora"] = p["rateio"]["por_hora"]
    return p


def horas_base(con, horas: float) -> tuple[float, float]:
    """(base que divide o salário e os custos fixos, horas da agenda cheia). Custeio por absorção na capacidade normal:
    divide pelas suas horas de trabalho do mês; a agenda cheia (metas > horas_vendaveis) é só o piso, para os poucos alunos
    de uma agenda vazia não pagarem o custo inteiro (a parte ociosa sai do lucro, em main.cobre_custos)."""
    from . import db
    cheia = float(db.parametros(con, "metas").get("horas_vendaveis") or 0)
    return max(float(horas or 0), cheia), cheia


def rateio_fixos(con, p: dict, horas: float = 0.0) -> dict:
    """Custos fixos do negócio (MFIT, softwares, assinaturas: as contas fixas da PJ, financeiro.custos_fixos_rateio)
    divididos pelas mesmas horas do salário (horas_base): cada hora de trabalho paga a sua parte, e a soma das partes
    dos alunos dá o total das contas. horas = suas horas de trabalho no mês (main.horas_trabalho_mes)."""
    from . import financeiro
    from .main import mes_atual
    fixos = financeiro.custos_fixos_rateio(con, mes_atual(), list(p.get("locais") or {}))
    base, cheia = horas_base(con, horas)
    return {**fixos, "horas": round(base, 1), "horas_trabalho": round(float(horas or 0), 1), "horas_cheia": round(cheia, 1),
            "piso": cheia > (horas or 0), "por_hora": round(fixos["total"] / base, 4) if base > 0 else 0.0}


# ---------- Planos montados pelo motor (sem a tabela de preços base da planilha) ----------
SEMANAS_MES = 4.33
PLANOS = (("Pacote de Aulas", 4, 0), ("Pacote de Aulas", 8, 0), ("Pacote de Aulas", 12, 0), ("Pacote de Aulas", 16, 0),
          ("Mensalidade", 0, 1), ("Mensalidade", 0, 2), ("Mensalidade", 0, 3), ("Mensalidade", 0, 4), ("Mensalidade", 0, 5),
          ("Aula avulsa", 0, 0), ("Consultoria Online", 0, 0), ("Consultoria Híbrida", 0, 0), ("Avaliação Física", 0, 0))


def base_motor(tipo: str, qtd: int = 0, freq: int = 0, local: str | None = None) -> dict:
    """O plano que o motor precifica: só tipo, aulas e local. Custo e preço saem de custo_servico (tempo, local, rateio).
    Aulas no mês: Pacote = nº de aulas; Mensalidade = vezes por semana x 4,33; avulsa e Híbrida = 1; Online e Avaliação = 0."""
    qtd, freq = int(qtd or 0), int(freq or 0)
    if tipo == "Pacote de Aulas":
        sessoes = float(qtd)
    elif tipo == "Mensalidade":
        sessoes = freq * SEMANAS_MES
    elif tipo in ("Aula avulsa", "Consultoria Híbrida"):
        sessoes = 1.0
    else:
        sessoes = 0.0
    return {"tipo_servico": tipo, "local": local, "qtd_aulas": qtd if tipo == "Pacote de Aulas" else 0,
            "freq_semanal": freq if tipo == "Mensalidade" else 0, "sessoes_mes": sessoes}


def deslocamento(p: dict, local: str | None) -> tuple[float, float]:
    """(R$ por aula, minutos por aula) da ida até o local. CIA: Configurações > Deslocamento até a CIA; local criado aqui: os custos dele."""
    if local == "CIA":
        c = p.get("cia_desloc") or {}
        return float(c.get("reais_por_aula") or 0), float(c.get("minutos_por_aula") or 0)
    c = (p.get("locais") or {}).get(local) or {}
    return float(c.get("deslocamento") or 0), float(c.get("tempo_deslocamento") or 0)


def custo_aula_local(p: dict, local: str | None) -> float:
    """R$ por aula (1 pessoa) que o local custa: CIA = taxa da CIA de 1 pessoa + a ida; local criado aqui = custo_por_aula; outro = 0."""
    if local == "CIA":
        return float(p.get("taxa_cia", {}).get(1, 0.0)) + deslocamento(p, "CIA")[0]
    c = (p.get("locais") or {}).get(local)
    return custo_por_aula(c) if c else 0.0


def valor_hora_automatico(con, p: dict, trabalho: dict | None = None) -> dict:
    """Salário por hora = seus custos pessoais do mês ÷ suas horas de trabalho no mês (horas_base, a mesma dos custos fixos).
      Custos pessoais: média das saídas pagas da PF nos 3 meses fechados (financeiro.custo_pessoal_medio).
      Horas de trabalho: aulas + deslocamento + planejamento + consultoria dos alunos ativos (main.horas_trabalho_detalhe).
      Piso na agenda cheia (metas > horas_vendaveis): com a agenda vazia, dividir só pelas horas de hoje jogava o custo
      de vida inteiro nos poucos alunos atuais (com 1 aluno, ele "custava" o salário todo). Se cobre ou não os custos está
      em main.cobre_custos, que usa o custo pessoal inteiro.
    usado=False (automático desligado, sem gasto na PF ou sem aluno): vale o valor_hora digitado em Configurações."""
    from . import financeiro
    from .main import horas_trabalho_detalhe, mes_atual
    mo = p.get("mo") or {}
    fixo = float(mo.get("valor_hora") or 0)
    ligado = bool(float(mo.get("valor_hora_auto") or 0)) and fixo > 0   # valor_hora 0 desliga a regra toda
    custo, meses = financeiro.custo_pessoal_medio(con, mes_atual()) if ligado else (0.0, 0)
    trabalho = trabalho if trabalho is not None else horas_trabalho_detalhe(con, p)
    horas = trabalho["total"] if ligado else 0.0
    base, cheia = horas_base(con, horas)
    usado = custo > 0 and horas > 0
    return {"ligado": ligado, "usado": usado, "custo_pessoal": round(custo, 2), "meses": meses, "horas": round(horas, 1),
            "horas_cheia": round(cheia, 1), "horas_base": round(base, 1), "piso": cheia > horas,
            "partes": {k: round(v, 1) for k, v in trabalho.items() if k != "total"},
            "valor_hora": round(custo / base, 2) if usado else fixo, "fixo": fixo}


# Serviços e o tempo de trabalho que a regra conta (minutos de Configurações > Mão de obra)
_COM_AULA = ("Pacote de Aulas", "Aula avulsa", "Mensalidade")
_CONSULTORIAS = ("Consultoria Online", "Consultoria Híbrida")
_AVALIACOES = ("Avaliação Física", "Avaliação")


PARTES_TRABALHO = ("aulas", "deslocamento", "planejamento", "consultoria", "avaliacao")


def partes_minutos(base: dict, p: dict, local: str | None = None) -> dict:
    """Minutos do seu trabalho (1 pessoa) num plano, por parte, pela regra do tempo (Configurações > Mão de obra):
      Pacote / avulsa: aulas x (aula + deslocamento do local) + planejamento do pacote
      Mensalidade:     aulas do mês x (aula + deslocamento) + planejamento do mês
      Consultoria:     tempo da consultoria no mês (+ as aulas presenciais da Híbrida)
      Avaliação:       tempo da avaliação + deslocamento"""
    r = p.get("mo") or {}
    tipo = base.get("tipo_servico")
    sessoes = float(base.get("sessoes_mes") or 0)
    desloc = deslocamento(p, local or base.get("local"))[1]
    out = dict.fromkeys(PARTES_TRABALHO, 0.0)
    if tipo in _AVALIACOES:
        out.update(avaliacao=float(r.get("min_avaliacao") or 0), deslocamento=desloc)
        return out
    out.update(aulas=sessoes * float(r.get("min_aula", 60) or 0), deslocamento=sessoes * desloc)
    if tipo in _COM_AULA:
        out["planejamento"] = float(r.get("min_planejamento_mes" if tipo == "Mensalidade" else "min_planejamento_pacote") or 0)
    elif tipo in _CONSULTORIAS:
        out["consultoria"] = float(r.get("min_consultoria_mes") or 0)
    return out


def minutos_trabalho(base: dict, p: dict, local: str | None = None) -> float:
    """Minutos do seu trabalho (1 pessoa) num plano: a soma das partes (partes_minutos)."""
    return sum(partes_minutos(base, p, local).values())


def custo_servico(base: dict, p: dict, local: str | None = None) -> tuple[float, float, float]:
    """(custo do negócio, mão de obra = pró-labore, horas de trabalho) de 1 pessoa, tudo pelo motor (nada da planilha):
      horas        = minutos_trabalho / 60
      mão de obra  = horas x valor da hora
      custo do negócio = o que o local cobra por aula x aulas + rateio dos custos fixos (R$ por hora x horas)"""
    local = local or base.get("local")
    sessoes = float(base.get("sessoes_mes") or 0)
    horas = minutos_trabalho(base, p, local) / 60
    mo = horas * float((p.get("mo") or {}).get("valor_hora") or 0)
    return custo_aula_local(p, local) * sessoes + float(p.get("rateio_hora") or 0) * horas, mo, horas


def decompor(base: dict, p: dict, local: str | None = None) -> dict:
    """De onde vem o preço de 1 aula (1 pessoa, sem multiplicador do horário) num local: as partes do custo por aula, que somam o custo,
    e o preço de tabela por aula. Para a Grade comparar os locais ("Por que esse preço?")."""
    local = local or base.get("local")
    sessoes = float(base.get("sessoes_mes") or 0) or 1.0
    reais, minutos_ida = deslocamento(p, local)
    if local == "CIA":
        taxa, mensal = float(p.get("taxa_cia", {}).get(1, 0.0)), 0.0
    else:
        c = (p.get("locais") or {}).get(local) or {}
        taxa = float(c.get("taxa_aula") or 0)
        mensal = (c.get("taxa_mensal") or 0) / c["aulas_mes"] if c.get("aulas_mes") else 0.0
    resto, mo, horas = custo_servico(base, p, local)
    rateio = float(p.get("rateio_hora") or 0) * horas
    custo = resto + mo
    r = calcular(base, p, local=local)
    partes = {"taxa": taxa, "mensal": mensal, "ida_reais": reais, "salario": mo / sessoes, "rateio": rateio / sessoes}
    return {**{k: round(v, 2) for k, v in partes.items()}, "custo": round(custo / sessoes, 2),
            "minutos": round(horas * 60 / sessoes, 1), "minutos_ida": minutos_ida,
            "valor_hora": round(float((p.get("mo") or {}).get("valor_hora") or 0), 2),
            "preco": round(r["preco_cheio"] / sessoes, 2), "sessoes": sessoes}


HORAS_GRADE = range(5, 24)


def mult_horario(con) -> dict:
    """Multiplicador do preço de cada horário (Grade > Multiplicadores): {hora: x}. O mesmo em todos os dias, locais e tipos.
    Abaixo de 1 = vale (horário para encher)."""
    from . import db
    m = {}
    for k, v in db.parametros(con, "mult_horario").items():
        try:
            m[int(k)] = float(v)
        except (TypeError, ValueError):
            pass
    return {h: (m.get(h) or 1.0) for h in HORAS_GRADE}


def custos_locais(con) -> dict:
    """{local: custos} dos locais criados pelo "+ Novo local" (tabela locais_custos)."""
    return {r["local"]: dict(r) for r in con.execute("SELECT * FROM locais_custos")}


def custo_por_aula(c: dict) -> float:
    """R$ por aula (1 pessoa) de um local: taxa + deslocamento + a taxa mensal dividida pelas aulas do mês."""
    fixo = (c.get("taxa_mensal") or 0) / c["aulas_mes"] if c.get("aulas_mes") else 0.0
    return (c.get("taxa_aula") or 0) + (c.get("deslocamento") or 0) + fixo


def por_grupo(tabela: dict, pessoas: int, padrao: float) -> float:
    """Valor da tabela por nº de pessoas (mão de obra extra, taxa da CIA).
    Grupo maior que a tabela usa o maior configurado: 5 pessoas não podem custar o preço de 1."""
    if pessoas in tabela:
        return tabela[pessoas]
    menores = [k for k in tabela if k <= pessoas]
    return tabela[max(menores)] if menores else padrao


def _componentes(base: dict, p: dict, pessoas: int, local: str | None) -> tuple[float, float, float]:
    """(custo, mão de obra, horas de trabalho) de um horário para o grupo todo: o que muda de um local para outro.
    A mão de obra (pró-labore) está dentro do custo; o grupo soma o esforço extra (grupo_mao_obra_extra) sobre ela
    e o que o local cobra a mais por pessoa."""
    local = local or base.get("local")
    outro = (p.get("locais") or {}).get(local)
    if local == "CIA" and pessoas > p["cia_max"]:
        raise ValueError(f"Na CIA o máximo é {p['cia_max']} pessoas")
    if outro and outro.get("max_pessoas") and pessoas > outro["max_pessoas"]:
        raise ValueError(f"Em {local} o máximo é {outro['max_pessoas']} pessoas")
    sessoes = float(base.get("sessoes_mes") or 0)
    resto, mo, horas = custo_servico(base, p, local)
    # Com o salário automático, a hora já é o seu custo de vida: o grupo não aumenta esse custo (contaria 2 vezes).
    if not (p.get("salario_hora") or {}).get("usado"):
        mo *= 1 + por_grupo(p["grupo_mo"], pessoas, 0.0)
    custo = resto + mo
    if local == "CIA" and pessoas > 1:
        um = p["taxa_cia"].get(1, 0.0)
        custo += (por_grupo(p["taxa_cia"], pessoas, um) - um) * sessoes
    if outro:
        custo += (outro.get("taxa_pessoa_extra") or 0) * (pessoas - 1) * sessoes
    return custo, mo, horas


def margem_alvo(p: dict, tipo: str) -> float:
    """Margem do preço de tabela do plano: a de Configurações > Margem alvo; sem ela, a mínima + 10 pontos."""
    minima = p["margens"].get(tipo, 0.15)
    return max(float((p.get("margens_alvo") or {}).get(tipo, minima + 0.10)), minima)


def calcular(base: dict, p: dict, pessoas: int = 1, mult_horario: float = 1.0,
             desconto: float = 0.0, forma_pagamento: str = "PIX", local: str | None = None,
             preco_final: float | None = None) -> dict:
    """
    base: plano do motor (base_motor: tipo_servico, qtd_aulas, freq_semanal, sessoes_mes, local).
    p: saída de carregar_parametros().
    Devolve preço total, por pessoa, lucro, margem, lucro/hora, preço mínimo e desconto máximo.
    """
    return calcular_misto([(base, mult_horario, local)], p, pessoas, desconto, forma_pagamento, preco_final)


def calcular_misto(horarios: list, p: dict, pessoas: int = 1, desconto: float = 0.0,
                   forma_pagamento: str = "PIX", preco_final: float | None = None,
                   extra: tuple | None = None) -> dict:
    """
    Proposta com vários horários (ex.: Seg 7h na CIA, Qua 19h na SmartFit), todos do mesmo plano.
    horarios: lista de (base, multiplicador do horário, local). Custo = média dos horários; cada aula da semana pesa igual.
    Preço de tabela (cheio) = custo ÷ (1 - impostos - taxa - margem alvo) x multiplicador do horário.
    Preço mínimo = custo ÷ (1 - impostos - taxa - margem mínima).
    preco_final: o preço que você quer cobrar (total); vira o desconto (negativo = acréscimo).
    extra: (preço, custo[, mão de obra, horas]) somados ao pacote, ex.: a consultoria do acompanhamento completo.
    Lucro = o que sobra depois do pró-labore (a mão de obra é custo); lucro/hora divide pelas horas de trabalho.
    """
    if not horarios:
        raise ValueError("Escolha pelo menos um horário")
    pessoas = max(1, int(pessoas))
    if forma_pagamento not in p["taxas"]:
        raise ValueError(f"Forma de pagamento desconhecida: {forma_pagamento}")
    base = horarios[0][0]
    taxa = p["das"] + p["taxas"][forma_pagamento]
    margem_min = p["margens"].get(base["tipo_servico"], 0.15)
    alvo = margem_alvo(p, base["tipo_servico"])
    if 1 - taxa - alvo <= 1e-9:   # sem isso: divisão por zero (ou preço negativo) e a tela caía
        raise ValueError("Imposto + taxa + margem passam de 100%: ajuste em Configurações")
    comps = [_componentes(b, p, pessoas, loc) for b, _, loc in horarios]
    custo, mao_obra, horas = (sum(c[i] for c in comps) / len(comps) for i in range(3))
    mult = sum(float(m or 1) for _, m, _ in horarios) / len(horarios)
    preco_cheio = custo * mult / (1 - taxa - alvo)
    if extra:
        extra = tuple(extra) + (0.0,) * (4 - len(extra))
        preco_cheio += float(extra[0] or 0)
        custo += float(extra[1] or 0)
        mao_obra += float(extra[2] or 0)
        horas += float(extra[3] or 0)

    if preco_final is not None and preco_final > 0 and preco_cheio:
        desconto = 1 - preco_final / preco_cheio
    if desconto >= 1 or desconto <= -9:
        raise ValueError("Desconto deve ficar abaixo de 100% (e o acréscimo, no máximo 900%)")

    sessoes = float(base.get("sessoes_mes") or 0)
    preco = preco_final if preco_final is not None and preco_final > 0 else preco_cheio * (1 - desconto)

    lucro = preco * (1 - taxa) - custo
    margem = lucro / preco if preco else 0.0
    preco_minimo = custo / (1 - taxa - margem_min)
    desconto_maximo = max(0.0, 1 - preco_minimo / preco_cheio) if preco_cheio else 0.0
    # Os 3 pisos da negociação (lucro aqui é DEPOIS do seu salário):
    #   piso do negócio: paga só impostos, taxas e custos do local; abaixo dele você paga para trabalhar
    #   piso do salário: paga também o seu salário/hora inteiro (lucro 0)
    #   preço mínimo:    salário + a margem mínima, que é o que sobra para reinvestir na empresa
    custo_negocio = custo - mao_obra
    piso_negocio = custo_negocio / (1 - taxa)
    piso_salario = custo / (1 - taxa)
    ganho_hora = (preco * (1 - taxa) - custo_negocio) / horas if horas else 0.0
    veredito = ("fechar" if preco >= preco_minimo - 0.005 else "so_salario" if preco >= piso_salario - 0.005
                else "parcial" if preco >= piso_negocio - 0.005 else "recusar")

    return {
        "desconto": round(desconto, 4),
        # preço redondo (R$ inteiro, para cima) que fica na margem mínima: o "ajustar" da tela Propostas
        "preco_sugerido": float(math.ceil(round(preco_minimo, 2))),
        "preco_total": round(preco, 2),
        "preco_pessoa": round(preco / pessoas, 2),
        "preco_cheio": round(preco_cheio, 2),
        "custo_total": round(custo, 2),
        "mao_obra": round(mao_obra, 2),   # pró-labore: já está dentro do custo_total
        "horas": round(horas, 2),
        "impostos_taxas": round(preco * taxa, 2),
        "lucro": round(lucro, 2),
        "margem": round(margem, 4),
        "lucro_hora": round(lucro / horas, 2) if horas else 0.0,
        "preco_minimo": round(preco_minimo, 2),
        "desconto_maximo": round(desconto_maximo, 4),
        "margem_minima": margem_min,
        "margem_alvo": alvo,
        "abaixo_margem": margem < margem_min - 1e-9,
        "sessoes": sessoes,
        "custo_negocio": round(custo_negocio, 2),
        "piso_negocio": round(piso_negocio, 2),
        "piso_salario": round(piso_salario, 2),
        "ganho_hora": round(ganho_hora, 2),   # o que você leva por hora (salário + lucro) com esse preço
        "valor_hora": round(float((p.get("mo") or {}).get("valor_hora") or 0), 2),   # o seu salário/hora em uso
        "veredito": veredito,
    }


def cor_margem(margem: float | None, minima: float = 0.15) -> str:
    """Classe de cor usada na grade e nas listas: verde (>= margem mínima do plano) / amarelo (até 5 pontos abaixo) /
    vermelho / prejuizo (< 0)."""
    if margem is None:
        return "neutro"
    if margem < 0:
        return "prejuizo"
    if margem < minima - 0.05 - 1e-9:
        return "vermelho"
    if margem < minima - 1e-9:
        return "amarelo"
    return "verde"
