"""Quando um horário fixo da Agenda (linha de agenda_fixos) vale. Usado pela Agenda e pelas contas automáticas (CIA e locais)."""


def fixo_vale(r, data: str) -> bool:
    """A linha do horário fixo vale na data? Vale de vigente_de (ou sempre) até o dia da exclusão, inclusive:
    excluir hoje vale a partir de amanhã (a aula de hoje continua na Agenda e na chamada).
    Linha criada e excluída no mesmo dia foi engano: nunca vale. Quando outra linha do aluno começa no mesmo dia
    (troca de hora ou de local), quem chama tira a antiga (ver trocada_no_dia)."""
    exc = str(r["excluido_em"] or "")[:10]
    if exc and exc <= str(r["criado_em"] or "")[:10]:
        return False
    return (not r["vigente_de"] or data >= r["vigente_de"]) and (not exc or data <= exc)


def trocada_no_dia(r, data: str, comecam: set) -> bool:
    """A linha foi excluída na data e o aluno ganhou outra linha que começa nesse dia (mudou de hora ou de local):
    vale a nova, para não ter duas aulas no mesmo dia. comecam = {(cliente_id, dia da semana)} com vigente_de == data."""
    return str(r["excluido_em"] or "")[:10] == data and (r["cliente_id"], r["dia"]) in comecam
