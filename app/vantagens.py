"""Vantagem da indicação: o leque de presentes que cabe no local de quem indicou.

Quem ganha a vantagem é quem indicou, e ela é entregue no local DELE: o local do amigo indicado (novo, outro já cadastrado ou o
mesmo) não muda nada. Num local que cobra por aula (a CIA: taxa_cia; ou locais_custos com taxa_aula/taxa_pessoa_extra), uma vantagem
que gasta uma aula ali (avaliação física, aula extra) sai do seu bolso: some do leque. Local vazio ou desconhecido conta como
"cobra por aula" (o lado seguro).
A lista fica em parametros, grupo 'vantagem_indicacao': chave = o texto que entra na mensagem, valor = 1 se gasta uma aula no local.
"""
from . import locais, precos

GRUPO = "vantagem_indicacao"
MAX_LEQUE = 3   # a mensagem mostra no máximo tantas opções
# (texto, gasta uma aula no local): semeadas uma vez; o que você tirar em Configurações não volta (db.marcar_removido)
INICIAIS = [("uma avaliação física grátis", 1), ("uma camiseta", 0), ("uma garrafa", 0), ("um treino extra para fazer em casa", 0)]


def cobra_por_aula(con, local: str | None) -> bool:
    """True se dar uma aula grátis nesse local custa dinheiro: a CIA com taxa, um local com taxa por aula ou por pessoa a mais.
    Local vazio ou que o CRM não conhece: True (não oferece o que gasta aula)."""
    nome = (local or "").strip()
    if not nome:
        return True
    if locais.eh_cia(nome):
        return float(precos.taxas_cia(con)[0].get(1, 0) or 0) > 0
    chave = locais._sem_espaco(nome)   # 'Smart Fit' e 'SmartFit' são o mesmo local
    for r in con.execute("SELECT local, taxa_aula, taxa_pessoa_extra FROM locais_custos"):
        if locais._sem_espaco(r["local"]) == chave:
            return float(r["taxa_aula"] or 0) > 0 or float(r["taxa_pessoa_extra"] or 0) > 0
    return nome not in locais.nomes(con)   # local da lista sem custos (Condomínio, Online): não cobra; nome estranho: lado seguro


def lista(con) -> list[dict]:
    """[{id, texto, gasta_aula}] na ordem cadastrada."""
    return [{"id": r["id"], "texto": r["chave"], "gasta_aula": bool(r["valor"])}
            for r in con.execute("SELECT id, chave, valor FROM parametros WHERE grupo=? ORDER BY ordem, id", (GRUPO,))]


def do_local(con, local: str | None, itens: list[dict] | None = None) -> list[str]:
    """As vantagens que cabem no local (até MAX_LEQUE): sem as que gastam aula quando o local cobra por aula."""
    itens = lista(con) if itens is None else itens
    cobra = cobra_por_aula(con, local)
    return [i["texto"] for i in itens if not (cobra and i["gasta_aula"])][:MAX_LEQUE]


def texto(opcoes: list[str]) -> str:
    """O que entra no {vantagem}: 'X'; 'à sua escolha: X ou Y'; 'à sua escolha: X, Y ou Z'; '' sem nenhuma."""
    if len(opcoes) <= 1:
        return opcoes[0] if opcoes else ""
    return "à sua escolha: " + ", ".join(opcoes[:-1]) + " ou " + opcoes[-1]


def do_aluno(con, local: str | None) -> str:
    """O {vantagem} pronto para a mensagem de quem treina nesse local."""
    return texto(do_local(con, local))


def rotulo(t: str) -> str:
    """'uma camiseta' -> 'Camiseta': como o presente fica anotado no histórico."""
    t = " ".join((t or "").split())
    for artigo in ("uma ", "um ", "a ", "o "):
        if t.lower().startswith(artigo):
            t = t[len(artigo):]
            break
    return t[:1].upper() + t[1:]


def sugestoes_presente(con, local: str | None) -> str:
    """As sugestões do 'O que você deu?' (Registrar presente) para quem indicou e treina nesse local, separadas por '|'."""
    return "|".join(rotulo(t) for t in do_local(con, local))
