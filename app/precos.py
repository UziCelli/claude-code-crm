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
    return {
        "das": financeiro.pct_das(con),   # alíquota efetiva de hoje pela tabela do Simples
        "taxas": g("taxa_pagamento"),
        "margens": g("margem_minima"),
        "taxa_cia": taxa_cia,
        "cia_max": cia_max,
        "grupo_mult": {int(k): v for k, v in g("grupo_multiplicador").items()},
        "grupo_mo": {int(k): v for k, v in g("grupo_mao_obra_extra").items()},
    }


def _componentes(base: dict, p: dict, pessoas: int, mult_horario: float, local: str | None) -> tuple[float, float]:
    """(preço cheio, custo) de um horário: o que muda de um horário/local para outro."""
    local = local or base.get("local")
    if local == "CIA" and pessoas > p["cia_max"]:
        raise ValueError(f"Na CIA o máximo é {p['cia_max']} pessoas")
    sessoes = float(base.get("sessoes_mes") or 0)
    preco_cheio = float(base["preco_base"]) * mult_horario * p["grupo_mult"].get(pessoas, 1.0)
    custo = float(base.get("custo_operacional") or 0)
    custo += float(base.get("mao_obra") or 0) * p["grupo_mo"].get(pessoas, 0.0)
    if local == "CIA" and pessoas > 1:
        custo += (p["taxa_cia"][pessoas] - p["taxa_cia"][1]) * sessoes
    return preco_cheio, custo


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
                   forma_pagamento: str = "PIX", preco_final: float | None = None) -> dict:
    """
    Proposta com vários horários (ex.: Seg 7h na CIA, Qua 19h na SmartFit), todos do mesmo plano.
    horarios: lista de (base, multiplicador do horário, local). Preço cheio e custo = média dos horários
    (preços iguais ficam iguais; diferentes viram a média). Cada aula da semana pesa igual.
    preco_final: o preço que você quer cobrar (total); vira o desconto (negativo = acréscimo).
    """
    if not horarios:
        raise ValueError("Escolha pelo menos um horário")
    pessoas = max(1, int(pessoas))
    if forma_pagamento not in p["taxas"]:
        raise ValueError(f"Forma de pagamento desconhecida: {forma_pagamento}")
    base = horarios[0][0]
    comps = [_componentes(b, p, pessoas, m, loc) for b, m, loc in horarios]
    preco_cheio = sum(c[0] for c in comps) / len(comps)
    custo = sum(c[1] for c in comps) / len(comps)

    if preco_final is not None and preco_final > 0 and preco_cheio:
        desconto = 1 - preco_final / preco_cheio
    if desconto >= 1 or desconto <= -9:
        raise ValueError("Desconto deve estar entre 0% e 99%")

    sessoes = float(base.get("sessoes_mes") or 0)
    horas = sessoes or 1.0
    taxa = p["das"] + p["taxas"][forma_pagamento]
    margem_min = p["margens"].get(base["tipo_servico"], 0.15)

    preco = preco_final if preco_final is not None and preco_final > 0 else preco_cheio * (1 - desconto)

    lucro = preco * (1 - taxa) - custo
    margem = lucro / preco if preco else 0.0
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
        "impostos_taxas": round(preco * taxa, 2),
        "lucro": round(lucro, 2),
        "margem": round(margem, 4),
        "lucro_hora": round(lucro / horas, 2),
        "preco_minimo": round(preco_minimo, 2),
        "desconto_maximo": round(desconto_maximo, 4),
        "margem_minima": margem_min,
        "abaixo_margem": margem < margem_min - 1e-9,
        "sessoes": sessoes,
    }


def cor_margem(margem: float | None) -> str:
    """Classe de cor usada na grade e nas listas: verde / amarelo / vermelho / prejuizo."""
    if margem is None:
        return "neutro"
    if margem < 0:
        return "prejuizo"
    if margem < 0.10:
        return "vermelho"
    if margem < 0.15:
        return "amarelo"
    return "verde"
