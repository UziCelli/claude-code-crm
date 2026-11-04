"""Motor de preços — função pura, sem banco. Todos os parâmetros vêm de fora (tela Configurações)."""
import math


def taxas_cia(con) -> tuple[dict, int]:
    """({pessoas: preço da aula na CIA}, máximo de pessoas por horário), dos parâmetros `taxa_cia`."""
    from . import db
    cia = db.parametros(con, "taxa_cia")
    return {int(k): v for k, v in cia.items() if k.isdigit()}, int(cia.get("maximo_pessoas", 3))


def carregar_parametros(con) -> dict:
    """Monta o dicionário de parâmetros a partir da tabela `parametros`."""
    from . import db, financeiro
    g = lambda grupo: db.parametros(con, grupo)  # noqa: E731
    taxa_cia, cia_max = taxas_cia(con)
    p = {
        "das": financeiro.pct_das(con),   # alíquota efetiva de hoje pela tabela do Simples
        "taxas": g("taxa_pagamento"),
        "margens": g("margem_minima"),
        "taxa_cia": taxa_cia,
        "cia_max": cia_max,
        "grupo_mult": {int(k): v for k, v in g("grupo_multiplicador").items()},
        "grupo_mo": {int(k): v for k, v in g("grupo_mao_obra_extra").items()},
        "locais": custos_locais(con),
        "mo": g("mao_obra"),
    }
    auto = valor_hora_automatico(con, p)
    p["salario_hora"] = auto
    if auto["usado"]:
        p["mo"] = {**p["mo"], "valor_hora": auto["valor_hora"]}
    return p


def valor_hora_automatico(con, p: dict) -> dict:
    """Salário por hora = seus custos pessoais do mês ÷ suas horas de trabalho no mês.
      Custos pessoais: média das saídas pagas da PF nos 3 meses fechados (financeiro.custo_pessoal_medio).
      Horas: as da agenda dos alunos ativos + planejamento + consultoria, pela regra do tempo (main.horas_trabalho_mes).
    usado=False (automático desligado, sem gasto na PF ou sem aluno): vale o valor_hora digitado em Configurações."""
    from . import financeiro
    from .main import horas_trabalho_mes, mes_atual
    mo = p.get("mo") or {}
    fixo = float(mo.get("valor_hora") or 0)
    ligado = bool(float(mo.get("valor_hora_auto") or 0)) and fixo > 0   # valor_hora 0 desliga a regra toda
    custo, meses = financeiro.custo_pessoal_medio(con, mes_atual()) if ligado else (0.0, 0)
    horas = horas_trabalho_mes(con, p) if ligado else 0.0
    usado = custo > 0 and horas > 0
    return {"ligado": ligado, "usado": usado, "custo_pessoal": round(custo, 2), "meses": meses, "horas": round(horas, 1),
            "valor_hora": round(custo / horas, 2) if usado else fixo, "fixo": fixo}


# Serviços e o tempo de trabalho que a regra conta (minutos de Configurações > Mão de obra)
_COM_AULA = ("Pacote de Aulas", "Aula avulsa", "Mensalidade")
_CONSULTORIAS = ("Consultoria Online", "Consultoria Híbrida")
_AVALIACOES = ("Avaliação Física", "Avaliação")


def minutos_trabalho(base: dict, p: dict, local: str | None = None) -> float | None:
    """Minutos do seu trabalho (1 pessoa) num plano, pela regra do tempo. None = sem regra: vale a mão de obra da planilha.
      Pacote / avulsa: aulas x (aula + deslocamento do local) + planejamento do pacote
      Mensalidade:     aulas do mês x (aula + deslocamento) + planejamento do mês
      Consultoria:     tempo da consultoria no mês (+ as aulas presenciais da Híbrida)
      Avaliação:       tempo da avaliação + deslocamento
    Valor da hora 0 desliga a regra (tudo volta para a planilha)."""
    r = p.get("mo") or {}
    if not float(r.get("valor_hora") or 0):
        return None
    tipo = base.get("tipo_servico")
    sessoes = float(base.get("sessoes_mes") or 0)
    desloc = float((p.get("locais", {}).get(local or base.get("local")) or {}).get("tempo_deslocamento") or 0)
    aula = float(r.get("min_aula", 60) or 0) + desloc
    if tipo in _COM_AULA:
        plan = r.get("min_planejamento_mes" if tipo == "Mensalidade" else "min_planejamento_pacote")
        return sessoes * aula + float(plan or 0)
    if tipo in _CONSULTORIAS:
        fixo = float(r.get("min_consultoria_mes") or 0)
        return fixo + sessoes * aula if fixo else None
    if tipo in _AVALIACOES:
        fixo = float(r.get("min_avaliacao") or 0)
        return fixo + desloc if fixo else None
    return None


def custo_servico(base: dict, p: dict, local: str | None = None) -> tuple[float, float, float]:
    """(custo sem a mão de obra, mão de obra = pró-labore, horas de trabalho) de 1 pessoa.
    O "Custo Operacional" da planilha já traz a mão de obra dentro: ela sai e entra a da regra do tempo."""
    custo_op = float(base.get("custo_operacional") or 0)
    mo_planilha = float(base.get("mao_obra") or 0)
    minutos = minutos_trabalho(base, p, local)
    if minutos is None:
        sessoes = float(base.get("sessoes_mes") or 0)
        desloc = float((p.get("locais", {}).get(local or base.get("local")) or {}).get("tempo_deslocamento") or 0)
        return custo_op - mo_planilha, mo_planilha, (sessoes or 1.0) * (1 + desloc / 60)
    horas = minutos / 60
    return max(0.0, custo_op - mo_planilha), horas * float(p["mo"]["valor_hora"]), horas


def custos_locais(con) -> dict:
    """{local: custos} dos locais criados pelo "+ Novo local" (tabela locais_custos)."""
    return {r["local"]: dict(r) for r in con.execute("SELECT * FROM locais_custos")}


def custo_por_aula(c: dict) -> float:
    """R$ por aula (1 pessoa) de um local: taxa + deslocamento + a taxa mensal dividida pelas aulas do mês."""
    fixo = (c.get("taxa_mensal") or 0) / c["aulas_mes"] if c.get("aulas_mes") else 0.0
    return (c.get("taxa_aula") or 0) + (c.get("deslocamento") or 0) + fixo


def por_grupo(tabela: dict, pessoas: int, padrao: float) -> float:
    """Valor da tabela por nº de pessoas (multiplicador, mão de obra extra, taxa da CIA).
    Grupo maior que a tabela usa o maior configurado: 5 pessoas não podem custar o preço de 1."""
    if pessoas in tabela:
        return tabela[pessoas]
    menores = [k for k in tabela if k <= pessoas]
    return tabela[max(menores)] if menores else padrao


_CAMPOS_PACOTE = ("preco_base", "custo_operacional", "mao_obra")


def base_pacote(rows: list, n: int, avulsa: dict | None = None) -> dict:
    """Base sintética de um Pacote de N aulas (1 a 20, ímpar também) a partir dos pacotes cadastrados.
    Entre dois pacotes: interpola em linha reta (7 aulas = meio caminho entre 6 e 8).
    Abaixo do menor: a "Aula avulsa" vale como pacote de 1 (se existir); senão, proporcional por aula.
    Acima do maior: proporcional por aula do maior."""
    n = int(n)
    if n < 1:
        raise ValueError("O pacote precisa ter pelo menos 1 aula")
    pontos = {int(r["qtd_aulas"]): dict(r) for r in rows if r.get("qtd_aulas")}
    if avulsa and 1 not in pontos:
        # a linha "Aula avulsa" pode guardar N sessões: normaliza para 1 aula
        div = float(avulsa.get("sessoes_mes") or 1) or 1.0
        um = dict(avulsa)
        um.update({k: float(avulsa.get(k) or 0) / div for k in _CAMPOS_PACOTE})
        pontos[1] = um
    if not pontos:
        raise ValueError("Não há pacote cadastrado para calcular o personalizado")
    qtds = sorted(pontos)
    if n in pontos:
        modelo, valores = pontos[n], {k: float(pontos[n].get(k) or 0) for k in _CAMPOS_PACOTE}
    elif n < qtds[0] or n > qtds[-1]:
        ref = qtds[0] if n < qtds[0] else qtds[-1]
        modelo = pontos[ref]
        valores = {k: float(modelo.get(k) or 0) / ref * n for k in _CAMPOS_PACOTE}
    else:
        a = max(q for q in qtds if q < n)
        b = min(q for q in qtds if q > n)
        t = (n - a) / (b - a)
        modelo = pontos[b]
        valores = {k: float(pontos[a].get(k) or 0) * (1 - t) + float(pontos[b].get(k) or 0) * t
                   for k in _CAMPOS_PACOTE}
    base = dict(modelo)
    base.update(valores, tipo_servico="Pacote de Aulas", qtd_aulas=n, sessoes_mes=n)
    return base


def _componentes(base: dict, p: dict, pessoas: int, mult_horario: float, local: str | None) -> tuple[float, float, float, float]:
    """(preço cheio, custo, mão de obra, horas de trabalho) de um horário: o que muda de um horário/local para outro.
    A mão de obra (pró-labore) está dentro do custo; grupo soma o esforço extra (grupo_mao_obra_extra) sobre ela."""
    local = local or base.get("local")
    outro = p.get("locais", {}).get(local)
    if local == "CIA" and pessoas > p["cia_max"]:
        raise ValueError(f"Na CIA o máximo é {p['cia_max']} pessoas")
    if outro and outro.get("max_pessoas") and pessoas > outro["max_pessoas"]:
        raise ValueError(f"Em {local} o máximo é {outro['max_pessoas']} pessoas")
    sessoes = float(base.get("sessoes_mes") or 0)
    preco_cheio = float(base["preco_base"]) * mult_horario * por_grupo(p["grupo_mult"], pessoas, 1.0)
    resto, mo, horas = custo_servico(base, p, local)
    mo *= 1 + por_grupo(p["grupo_mo"], pessoas, 0.0)
    custo = resto + mo
    if local == "CIA" and pessoas > 1:
        um = p["taxa_cia"].get(1, 0.0)
        custo += (por_grupo(p["taxa_cia"], pessoas, um) - um) * sessoes
    if outro:
        custo += (outro.get("taxa_pessoa_extra") or 0) * (pessoas - 1) * sessoes
    return preco_cheio, custo, mo, horas


def calcular(base: dict, p: dict, pessoas: int = 1, mult_horario: float = 1.0,
             desconto: float = 0.0, forma_pagamento: str = "PIX", local: str | None = None,
             preco_final: float | None = None) -> dict:
    """
    base: linha de precos_base (tipo_servico, preco_base, custo_operacional, mao_obra, sessoes_mes).
    p: saída de carregar_parametros().
    Devolve preço total, por pessoa, lucro, margem, lucro/hora, preço mínimo e desconto máximo.
    """
    return calcular_misto([(base, mult_horario, local)], p, pessoas, desconto, forma_pagamento, preco_final)


def calcular_misto(horarios: list, p: dict, pessoas: int = 1, desconto: float = 0.0,
                   forma_pagamento: str = "PIX", preco_final: float | None = None,
                   extra: tuple | None = None) -> dict:
    """
    Proposta com vários horários (ex.: Seg 7h na CIA, Qua 19h na SmartFit), todos do mesmo plano.
    horarios: lista de (base, multiplicador do horário, local). Preço cheio e custo = média dos horários
    (preços iguais ficam iguais; diferentes viram a média). Cada aula da semana pesa igual.
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
    comps = [_componentes(b, p, pessoas, m, loc) for b, m, loc in horarios]
    preco_cheio, custo, mao_obra, horas = (sum(c[i] for c in comps) / len(comps) for i in range(4))
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
    taxa = p["das"] + p["taxas"][forma_pagamento]
    margem_min = p["margens"].get(base["tipo_servico"], 0.15)

    preco = preco_final if preco_final is not None and preco_final > 0 else preco_cheio * (1 - desconto)

    lucro = preco * (1 - taxa) - custo
    margem = lucro / preco if preco else 0.0
    if 1 - taxa - margem_min <= 1e-9:   # sem isso: divisão por zero (ou preço mínimo negativo) e a tela caía
        raise ValueError("Imposto + taxa + margem mínima passam de 100%: ajuste em Configurações")
    preco_minimo = custo / (1 - taxa - margem_min)
    desconto_maximo = max(0.0, 1 - preco_minimo / preco_cheio) if preco_cheio else 0.0

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
        "abaixo_margem": margem < margem_min - 1e-9,
        "sessoes": sessoes,
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
