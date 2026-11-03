"""Quando um horário fixo da Agenda (linha de agenda_fixos) vale. Usado pela Agenda e pelas contas automáticas (CIA e locais)."""


def fixo_vale(r, data: str) -> bool:
    """A linha do horário fixo vale na data? Vale de vigente_de (ou sempre) até o dia antes da exclusão.
    Linha criada e excluída no mesmo dia foi engano: nunca vale."""
    exc = str(r["excluido_em"] or "")[:10]
    if exc and exc <= str(r["criado_em"] or "")[:10]:
        return False
    return (not r["vigente_de"] or data >= r["vigente_de"]) and (not exc or data < exc)
