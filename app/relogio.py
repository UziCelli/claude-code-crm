"""Relógio do app: a data e a hora de agora sempre no fuso do Brasil, em qualquer servidor.

Por que não `dt.date.today()`: ela usa o relógio do sistema operacional, e o fuso do sistema nem sempre é o do Brasil.
No Windows, a variável TZ="America/Sao_Paulo" é lida pelo C do Windows como "Ame" com deslocamento 0 (UTC), e depois
das 21h o "hoje" virava amanhã. Aqui o fuso vem do zoneinfo (pacote `tzdata` no Windows), sem depender do sistema.

Timestamps gravados pelo SQL (`datetime('now','localtime')`) continuam onde estão quando são comparados entre si
(ex.: `clientes.renovacao_em` com `lancamentos.criado_em` em financeiro.renovacoes, e o envio repetido em main):
os dois lados precisam vir do mesmo relógio."""
import datetime as dt

try:
    from zoneinfo import ZoneInfo
    FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:   # sem a base de fusos (Windows sem o pacote tzdata): fica o relógio do sistema
    FUSO = None


def _utc() -> dt.datetime:
    """Agora em UTC. É o único ponto que os testes trocam para simular outro horário."""
    return dt.datetime.now(dt.timezone.utc)


def agora() -> dt.datetime:
    """Data e hora de agora no Brasil, sem fuso anexado (os textos gravados seguem iguais)."""
    if FUSO is None:
        return _utc().astimezone().replace(tzinfo=None)
    return _utc().astimezone(FUSO).replace(tzinfo=None)


def hoje() -> dt.date:
    """A data de hoje no Brasil."""
    return agora().date()


def agora_txt() -> str:
    """Data e hora de agora no Brasil ("AAAA-MM-DD HH:MM:SS"). No Turso o SQL roda em UTC: o carimbo vai calculado aqui."""
    return agora().isoformat(sep=" ", timespec="seconds")
