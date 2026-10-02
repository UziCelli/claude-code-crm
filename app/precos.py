"""Motor de preços — função pura, sem banco. Todos os parâmetros vêm de fora (tela Configurações)."""


def carregar_parametros(con) -> dict:
    """Monta o dicionário de parâmetros a partir da tabela `parametros`."""
    from . import db
    g = lambda grupo: db.parametros(con, grupo)  # noqa: E731
    cia = g("taxa_cia")
    return {
        "das": g("imposto").get("DAS", 0.06),
        "taxas": g("taxa_pagamento"),
        "margens": g("margem_minima"),
        "taxa_cia": {int(k): v for k, v in cia.items() if k.isdigit()},
        "cia_max": int(cia.get("maximo_pessoas", 3)),
        "grupo_mult": {int(k): v for k, v in g("grupo_multiplicador").items()},
        "grupo_mo": {int(k): v for k, v in g("grupo_mao_obra_extra").items()},
    }


def calcular(base: dict, p: dict, pessoas: int = 1, mult_horario: float = 1.0,
             desconto: float = 0.0, forma_pagamento: str = "PIX", local: str | None = None) -> dict:
    """
    base: linha de precos_base (tipo_servico, preco_base, custo_operacional, mao_obra, sessoes_mes).
    p: saída de carregar_parametros().
    Devolve preço total, por pessoa, lucro, margem, lucro/hora, preço mínimo e desconto máximo.
    """
    pessoas = max(1, int(pessoas))
    local = local or base.get("local")
    if local == "CIA" and pessoas > p["cia_max"]:
        raise ValueError(f"Na CIA o máximo é {p['cia_max']} pessoas")
    if not 0 <= desconto < 1:
        raise ValueError("Desconto deve estar entre 0% e 99%")
    if forma_pagamento not in p["taxas"]:
        raise ValueError(f"Forma de pagamento desconhecida: {forma_pagamento}")

    sessoes = float(base.get("sessoes_mes") or 0)
    horas = sessoes or 1.0
    taxa = p["das"] + p["taxas"][forma_pagamento]
    margem_min = p["margens"].get(base["tipo_servico"], 0.15)

    preco_cheio = float(base["preco_base"]) * mult_horario * p["grupo_mult"].get(pessoas, 1.0)
    preco = preco_cheio * (1 - desconto)

    custo = float(base.get("custo_operacional") or 0)
    custo += float(base.get("mao_obra") or 0) * p["grupo_mo"].get(pessoas, 0.0)
    if local == "CIA" and pessoas > 1:
        custo += (p["taxa_cia"][pessoas] - p["taxa_cia"][1]) * sessoes

    lucro = preco * (1 - taxa) - custo
    margem = lucro / preco if preco else 0.0
    preco_minimo = custo / (1 - taxa - margem_min)
    desconto_maximo = max(0.0, 1 - preco_minimo / preco_cheio) if preco_cheio else 0.0

    return {
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
