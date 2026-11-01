"""Sugestões: o que fazer agora, a partir dos marcadores da Saúde financeira (app/marcadores.py). Regras fixas, sem IA.

No mesmo molde de alunos.estado(): REGRAS é uma tupla de funções (ctx, marc) -> sugestão | None, e calcular() só as junta.
O que é por pessoa ou para hoje continua nos alertas; aqui é estratégia (olha os 3 últimos meses fechados).
Marcador cinza (sem dados) e mensalidades vencidas não geram sugestão: o botão do próprio marcador já leva à solução.
REGRA DE MARKETING: recompensa e campanha agregam valor ao trabalho (presente, bônus, treino em dupla) e nunca dão desconto.
"""
import datetime as dt
import math

from . import marcadores
from .marcadores import _lista, _m, _pct

GRAV = {"vermelho": 1, "amarelo": 2, "azul": 3}
ADIAR_DIAS = 30
LIMITE = 3
GRUPO_ADIADA = "sugestao_adiada"


def _hoje() -> str:
    return dt.date.today().isoformat()


def _arredondar_50(valor) -> int:
    """Múltiplo de 50 mais próximo, no mínimo 50 (guardar R$ 37 por mês não é um plano)."""
    return max(50, int(round(valor / 50.0)) * 50)


def sugestao(chave, titulo, porque, marcador, impacto, tipo, cor, acoes, passos=None) -> dict:
    """O formato único. impacto em R$ ('mes' = por mês, 'uma_vez' = de uma vez); passos = até 3 caminhos curtos."""
    impacto = round(float(impacto or 0), 2)
    return {"chave": chave, "titulo": titulo, "porque": porque, "marcador": marcador, "impacto": impacto, "impacto_tipo": tipo,
            "impacto_txt": (f"{_m(impacto)} por mês" if tipo == "mes" else f"{_m(impacto)} de uma vez") if impacto else "",
            "cor": cor, "acoes": list(acoes), "passos": list(passos or [])[:3]}


def _ruim(m) -> bool:
    return m["cor"] in ("amarelo", "vermelho")


def _top(d: dict, n: int) -> list:
    return sorted(((k, v) for k, v in d.items() if v > 0), key=lambda kv: -kv[1])[:n]


def _por_mes(ctx, escopo, campo, meses) -> dict:
    """Soma por nome (categoria ou conta fixa), dividida pelo número de meses: quanto custa por mês."""
    total = {}
    for x in meses:
        for k, v in ctx[escopo][x][campo].items():
            total[k] = total.get(k, 0.0) + v
    n = max(len(meses), 1)
    return {k: v / n for k, v in total.items()}


def _meses_validos(ctx) -> list:
    return [x for x in marcadores._com_dados_pj(ctx, ctx["janela"]) if x in ctx["validos"]]


def _acao_reajuste(ctx) -> dict:
    if ctx["abaixo"]:
        return {"rotulo": f"Reajustar ({len(ctx['abaixo'])})", "href": _lista([a["id"] for a in ctx["abaixo"]], "reajuste")}
    return {"rotulo": "Ver preços", "href": "/simulador"}


# =====================================================================
# Finanças
# =====================================================================
def regra_equilibrio(ctx, marc):
    """Receita abaixo do ponto de equilíbrio (contábil ou econômico): quanto falta e 3 caminhos, cada um com o seu impacto."""
    ruins = [m for m in (marc["pe_contabil"], marc["pe_economico"]) if m["dados"].get("razao", 9) < 1 and m["cor"] != "cinza"]
    if not ruins:
        return None
    pior = max(ruins, key=lambda m: m["dados"]["falta"])
    d = pior["dados"]
    recorrente = ctx["metricas"]["faturamento_recorrente"]
    ticket = ctx["ticket_medio"]
    mg = d["margem"]
    custos = mg["fixos_mes"] + mg["variaveis"] / mg["n"]
    passos = [f"Reajustar as mensalidades em 10% rende {_m(0.10 * recorrente)} por mês."]
    if ticket > 0:
        n = math.ceil(d["falta"] / ticket)
        passos.append(f"Trazer {n} aluno{'s' if n > 1 else ''} novo{'s' if n > 1 else ''} (ticket de {_m(ticket)}) rende {_m(n * ticket)} por mês.")
    passos.append(f"Cortar 10% dos custos ({_m(custos)} por mês) economiza {_m(0.10 * custos)} por mês.")
    quando = "para empatar" if pior["chave"] == "pe_contabil" else "para a empresa valer a pena"
    acoes = [_acao_reajuste(ctx)]
    if ctx["veteranos"]:
        acoes.append({"rotulo": f"Pedir indicação ({len(ctx['veteranos'])})", "href": _lista(ctx["veteranos"], "indicacao")})
    acoes.append(marcadores.A_RECORRENTES)
    return sugestao("equilibrio", f"Faltam {_m(d['falta'])} por mês {quando}.",
                    f"{pior['nome']}: a receita média é {_m(d['receita_mes'])} e o mínimo é {_m(d['pe'])}.",
                    pior["chave"], d["falta"], "mes", pior["cor"], acoes, passos)


def regra_margem_contribuicao(ctx, marc):
    """Margem de contribuição baixa: as maiores categorias de custo variável."""
    m = marc["margem_contribuicao"]
    if not _ruim(m):
        return None
    meses = _meses_validos(ctx)
    var = _top(_por_mes(ctx, "pj", "var_cat", meses), 3)
    if not var:
        return None
    total = sum(_por_mes(ctx, "pj", "var_cat", meses).values())
    lista = ", ".join(f"{k} ({_m(v)})" for k, v in var)
    return sugestao("margem_contribuicao", "Os custos variáveis estão comendo a margem.",
                    f"Margem de contribuição em {m['texto']}; as maiores: {lista}.", "margem_contribuicao", 0.10 * total, "mes", m["cor"],
                    [marcadores.A_LIVRO_PJ, _acao_reajuste(ctx)])


def _regra_caixa(ctx, marc, chave, escopo):
    m = marc[chave]
    if m["cor"] != "vermelho":
        return None
    d = m["dados"]
    falta = -d["menor"] if d["menor"] < 0 else 0
    quando = f"{d['data'][8:10]}/{d['data'][5:7]}"
    acoes = [marcadores.A_90_DIAS, {"rotulo": "Contas", "href": "/financeiro#contas"}]
    if escopo == "PJ" and ctx["ids_cobrar"]:
        acoes.append({"rotulo": f"Cobrar vencidos ({len(ctx['ids_cobrar'])})", "href": _lista(ctx["ids_cobrar"], "cobrar")})
    return sugestao(chave, f"O caixa da {'empresa' if escopo == 'PJ' else 'vida pessoal'} fica negativo em {quando}.",
                    f"Caixa 90 dias: faltam {_m(falta)} no pior dia.", chave, falta, "uma_vez", "vermelho", acoes)


def regra_caixa_pj(ctx, marc):
    return _regra_caixa(ctx, marc, "caixa_pj", "PJ")


def regra_caixa_pf(ctx, marc):
    return _regra_caixa(ctx, marc, "caixa_pf", "PF")


def regra_salario_alto(ctx, marc):
    """O salário é maior que o lucro: sugere o valor de financeiro.sugestao_salario."""
    meses = marcadores._com_dados_pj(ctx, ctx["janela"])
    if ctx["salario"] <= 0 or not meses:
        return None
    lucro = sum(ctx["pj"][x]["lucro"] for x in meses) / len(meses)
    if lucro >= ctx["salario"]:
        return None
    sug = ctx["sugestao_salario"]
    return sugestao("salario_alto", f"Seu salário de {_m(ctx['salario'])} é maior que o lucro da empresa.",
                    f"Lucro médio de {_m(lucro)} por mês; o CRM sugere um salário de {_m(sug)}.", "margem_liquida",
                    ctx["salario"] - sug, "mes", "vermelho" if lucro < 0 else "amarelo",
                    [{"rotulo": "Ajustar o salário", "href": "/configuracoes#cfg-salario"}, {"rotulo": "Ver o lucro", "href": "/financeiro/painel"}])


def regra_subir_salario(ctx, marc):
    """Lucro, reserva e caixa no verde e o salário abaixo do que o lucro aguenta: dá para subir (azul, é uma boa notícia)."""
    if not all(marc[k]["cor"] == "verde" for k in ("margem_lucro", "reserva_pj", "caixa_pj")):
        return None
    sug = ctx["sugestao_salario"]
    if sug <= ctx["salario"]:
        return None
    return sugestao("subir_salario", f"Você pode subir o salário para {_m(sug)}.",
                    f"Lucro, reserva e caixa estão no verde; hoje o salário é {_m(ctx['salario'])}.", "margem_lucro", sug - ctx["salario"],
                    "mes", "azul", [{"rotulo": "Ajustar o salário", "href": "/configuracoes#cfg-salario"}])


def regra_reserva(ctx, marc):
    """Reserva da empresa abaixo da meta: quanto guardar por mês (falta ÷ 12, em múltiplos de 50)."""
    m = marc["reserva_pj"]
    if not _ruim(m):
        return None
    d = m["dados"]
    falta = max(d["meta_meses"] * d["mensal"] - d["guardado"], 0)
    por_mes = _arredondar_50(falta / 12)
    acoes = [{"rotulo": "Ver reserva", "href": "/financeiro/painel#reserva"}, marcadores.A_SALDOS]
    return sugestao("reserva", f"Guarde {_m(por_mes)} por mês na reserva da empresa.",
                    f"Reserva: {m['texto']} guardados; a meta é {marcadores._num(d['meta_meses'], 0)}.", "reserva_pj", por_mes, "mes", m["cor"], acoes)


def regra_cortar_custos(ctx, marc):
    """Margem de lucro baixa: as 3 maiores contas fixas e as 2 maiores categorias variáveis, com o impacto de cortar 10%."""
    m = marc["margem_lucro"]
    if not _ruim(m):
        return None
    meses = _meses_validos(ctx)
    fixos, var = _top(_por_mes(ctx, "pj", "fixo_itens", meses), 3), _top(_por_mes(ctx, "pj", "var_cat", meses), 2)
    if not (fixos or var):
        return None
    total = sum(v for _, v in fixos + var)
    passos = [f"{k}: cortar 10% economiza {_m(0.10 * v)} por mês (hoje {_m(v)})." for k, v in (fixos + var)[:3]]
    return sugestao("cortar_custos", "Corte 10% das maiores contas da empresa.",
                    f"Margem de lucro em {m['texto']}; as maiores contas somam {_m(total)} por mês.", "margem_lucro", 0.10 * total, "mes",
                    m["cor"], [marcadores.A_RECORRENTES, marcadores.A_LIVRO_PJ], passos)


def regra_gastos_pessoais(ctx, marc):
    """Sobra do mês baixa: as 2 maiores categorias de gasto da PF."""
    m = marc["sobra"]
    if not _ruim(m):
        return None
    meses = marcadores._com_dados_pf(ctx, ctx["janela"])
    cats = _top(_por_mes(ctx, "pf", "cats", meses), 2)
    if not cats:
        return None
    lista = " e ".join(f"{k} ({_m(v)})" for k, v in cats)
    return sugestao("gastos_pessoais", "Segure os dois maiores gastos pessoais.",
                    f"Sobra do mês em {m['texto']}; os maiores gastos: {lista}.", "sobra", 0.10 * sum(v for _, v in cats), "mes", m["cor"],
                    [marcadores.A_LIVRO_PF])


def regra_moradia(ctx, marc):
    """Moradia acima do limite saudável (30% da renda): rever o aluguel e as contas da casa."""
    m = marc["moradia"]
    if not _ruim(m):
        return None
    d = m["dados"]
    excesso = max(d["mensal"] - ctx["faixas"]["moradia"]["verde"] * d["renda"], 0)
    return sugestao("moradia", "Reveja o aluguel e as contas da casa.",
                    f"Moradia leva {m['texto']} da renda; o limite saudável é {_pct(ctx['faixas']['moradia']['verde'])}.", "moradia", excesso, "mes",
                    m["cor"], [marcadores.A_RECORRENTES])


def regra_dividas(ctx, marc):
    """Parcelas pesadas: quitar primeiro a dívida mais cara (maior juros do impacto_juros; sem juros, a maior)."""
    m = marc["dividas"]
    if not _ruim(m) or not ctx["dividas"]:
        return None
    pior = max(ctx["dividas"], key=lambda d: (d["juros"], d["valor"]))
    custo = pior["juros"] * pior["valor"]
    return sugestao("dividas", f"Quite primeiro {pior['descricao'] or pior['categoria']}, a dívida mais cara.",
                    f"Parcelas levam {m['texto']} da renda; o teto saudável é {_pct(ctx['faixas']['dividas']['verde'])}.", "dividas",
                    custo or pior["valor"], "mes" if custo else "uma_vez", m["cor"], [{"rotulo": "Ver contas", "href": "/financeiro#contas"}])


def regra_reserva_pf(ctx, marc):
    """Reserva de emergência da família abaixo de 6 meses: quanto guardar por mês até chegar lá."""
    m = marc["reserva_pf"]
    if not _ruim(m):
        return None
    d = m["dados"]
    falta = max(d["meta_meses"] * d["custo"] - d["guardado"], 0)
    por_mes = _arredondar_50(falta / 12)
    return sugestao("reserva_pf", f"Guarde {_m(por_mes)} por mês até chegar a {marcadores._num(d['meta_meses'], 0)} meses de reserva.",
                    f"Reserva de emergência cobre {m['texto']} de vida.", "reserva_pf", por_mes, "mes", m["cor"],
                    [{"rotulo": "Ver reserva", "href": "/financeiro/painel#reserva"}, marcadores.A_SALDOS])


def regra_reajuste(ctx, marc):
    """Alunos abaixo da margem mínima do motor de preços: reajustar para o preço mínimo."""
    abaixo = ctx["abaixo"]
    if not abaixo:
        return None
    mensal = sum(a["minimo"] - a["valor"] for a in abaixo if a["mensalidade"])
    avulso = sum(a["minimo"] - a["valor"] for a in abaixo if not a["mensalidade"])
    n = len(abaixo)
    return sugestao("reajuste", f"{n} aluno{'s' if n > 1 else ''} pagam abaixo do preço mínimo.",
                    f"Reajustar para o mínimo rende {_m(mensal or avulso)} {'por mês' if mensal else 'de uma vez'}.", "faturamento",
                    mensal or avulso, "mes" if mensal else "uma_vez", "amarelo", [_acao_reajuste(ctx)])


# =====================================================================
# Marketing (sem desconto)
# =====================================================================
def _agenda_ruim(marc) -> bool:
    return _ruim(marc["agenda"])


def regra_indicacao(ctx, marc):
    """Agenda não está no verde e há alunos em dia há 3 meses ou mais: pedir indicação, com um presente de agradecimento."""
    vet = ctx["veteranos"]
    if not _agenda_ruim(marc) or not vet:
        return None
    k = ctx["novos_por_canal"].get("Indicação", 0)
    historico = ("ninguém veio por indicação nos últimos 3 meses" if not k else
                 f"{k} aluno{'s' if k > 1 else ''} novo{'s' if k > 1 else ''} vieram por indicação nos últimos 3 meses")
    a = marc["agenda"]["dados"]
    return sugestao("indicacao", "Peça indicação a quem já treina com você.",
                    f"Agenda em {marcadores._num(a['horas'], 0)} h de {marcadores._num(a['meta'], 0)}; {historico}.", "agenda", ctx["ticket_medio"], "mes",
                    marc["agenda"]["cor"], [{"rotulo": f"Mandar convite ({len(vet)})", "href": _lista(vet, "indicacao")}],
                    ["Quem indicar ganha um presente seu quando o indicado fechar."])


def regra_reativar_ex_alunos(ctx, marc):
    """Ex-alunos dos últimos 12 meses: chamar de volta quando a agenda ou a saída de alunos não está no verde."""
    ex = ctx["ex_alunos"]
    if not ex or not (_agenda_ruim(marc) or _ruim(marc["saidas"])):
        return None
    valores = [e["valor"] for e in ex if e["valor"]]
    ticket = sum(valores) / len(valores) if valores else ctx["ticket_medio"]
    n = len(ex)
    return sugestao("reativar_ex_alunos", "Chame de volta quem saiu nos últimos 12 meses.",
                    f"{n} ex-aluno{'s' if n > 1 else ''} para chamar; cada um que volta rende {_m(ticket)} por mês.", "saidas", ticket, "mes",
                    "amarelo", [{"rotulo": f"Mandar mensagem ({n})", "href": _lista([e["id"] for e in ex], "reativar")}])


def regra_reativar_leads(ctx, marc):
    """Leads perdidos nos últimos 90 dias: retomar a conversa quando a agenda não está no verde."""
    leads = ctx["leads_perdidos"]
    if not leads or not _agenda_ruim(marc):
        return None
    n = len(leads)
    return sugestao("reativar_leads", "Retome a conversa com os leads perdidos dos últimos 90 dias.",
                    f"{n} lead{'s' if n > 1 else ''} perdido{'s' if n > 1 else ''}; cada um que fecha rende {_m(ctx['ticket_medio'])} por mês.",
                    "faturamento", ctx["ticket_medio"], "mes", "amarelo", [{"rotulo": "Ver leads", "href": "/leads"}])


def regra_horarios_de_vale(ctx, marc):
    """Horários de vale livres na grade: oferecer à lista de espera e aos novos alunos."""
    n = ctx["vale_livre"]
    if not n or not _agenda_ruim(marc):
        return None
    a = marc["agenda"]["dados"]
    acoes = [{"rotulo": "Ver horários de vale", "href": "/grade?vale=1"},
             {"rotulo": "Lista de espera", "href": "/rotina"} if ctx["espera_vale"] else {"rotulo": "Ver leads", "href": "/leads"}]
    return sugestao("horarios_de_vale", f"Ofereça os {n} horários de vale que estão livres.",
                    f"Agenda em {marcadores._num(a['horas'], 0)} h de {marcadores._num(a['meta'], 0)}; sobram horários no vale.", "agenda",
                    ctx["ticket_medio"], "mes", marc["agenda"]["cor"], acoes)


def regra_espera_no_pico(ctx, marc):
    """Gente esperando por horário de pico: o pico está disputado, dá para subir o preço dele."""
    n = ctx["metricas"]["espera_pico"]
    if not n:
        return None
    base = ctx["receita_pico"] or ctx["ticket_medio"]
    return sugestao("espera_no_pico", "Suba o preço do horário de pico.",
                    f"{n} pessoa{'s' if n > 1 else ''} na lista de espera do pico: o horário é disputado.", "margem_lucro", 0.10 * base, "mes",
                    "azul", [{"rotulo": "Ver a grade", "href": "/grade"}, {"rotulo": "Lista de espera", "href": "/rotina"}])


def regra_treino_em_dupla(ctx, marc):
    """Receita de grupos abaixo da meta: convidar alunos a treinar em dupla rende mais por hora."""
    meta = float(ctx["metas"].get("pct_grupos_dez26") or 0)
    pct = ctx["metricas"]["pct_receita_grupos"]
    solos = ctx["solos"]
    if not solos or not meta or pct >= meta:
        return None
    n = min(3, len(solos))
    ganho = n * (ctx["grupo_mult2"] - 1) * ctx["valor_solo"]
    return sugestao("treino_em_dupla", "Convide alunos para treinar em dupla.",
                    f"Só {_pct(pct)} da receita vem de grupos; a meta é {_pct(meta)}. {n} duplas rendem {_m(ganho)} a mais por mês.",
                    "faturamento", ganho, "mes", "azul", [{"rotulo": f"Mandar convite ({len(solos)})", "href": _lista(solos, "dupla")}])


def regra_verba_por_canal(ctx, marc):
    """Só com gasto de marketing lançado: o canal que gastou e não trouxe aluno, ou que custa mais que o limite por aluno."""
    pior = None
    for canal, g in ctx["gastos_canal"].items():
        if not g["gasto"] or g["gasto"] <= 0:
            continue
        novos = max(int(g["clientes"] or 0), ctx["novos_por_canal"].get(canal, 0))
        cac = g["gasto"] / novos if novos else None
        if (novos == 0 or (ctx["cac_max"] and cac > ctx["cac_max"])) and (pior is None or g["gasto"] > pior[1]):
            pior = (canal, g["gasto"], novos, cac)
    if not pior:
        return None
    canal, gasto, novos, cac = pior
    quanto = (f"{_m(gasto)} em 3 meses e nenhum aluno novo" if not novos else
              f"{_m(gasto)} em 3 meses, {_m(cac)} por aluno (o limite é {_m(ctx['cac_max'])})")
    return sugestao("verba_por_canal", f"Reveja a verba do canal {canal}.", f"{canal}: {quanto}.", "faturamento", gasto / 3, "mes",
                    "vermelho" if not novos else "amarelo", [{"rotulo": "Ver campanhas", "href": "/campanhas"}])


REGRAS = (regra_equilibrio, regra_margem_contribuicao, regra_caixa_pj, regra_caixa_pf, regra_salario_alto, regra_subir_salario,
          regra_reserva, regra_cortar_custos, regra_gastos_pessoais, regra_moradia, regra_dividas, regra_reserva_pf, regra_reajuste,
          regra_indicacao, regra_reativar_ex_alunos, regra_reativar_leads, regra_horarios_de_vale, regra_espera_no_pico,
          regra_treino_em_dupla, regra_verba_por_canal)


# =====================================================================
# O algoritmo
# =====================================================================
def calcular(ctx, marc) -> list:
    """Todas as sugestões que valem agora, da mais grave para a menos (gravidade, depois impacto). As que o usuário marcou "Já fiz"
    ficam escondidas até a data guardada. marc = marcadores.calcular(ctx)."""
    por_chave = marc["todos"]
    hoje = ctx["hoje"]
    out = []
    for regra in REGRAS:
        s = regra(ctx, por_chave)
        if s and ctx["adiadas"].get(s["chave"], "") <= hoje:
            out.append(s)
    return sorted(out, key=lambda s: (GRAV[s["cor"]], -s["impacto"]))


def escolher(lista, limite=LIMITE) -> tuple[list, list]:
    """(as primeiras `limite`, de marcadores diferentes; o resto). Duas sugestões do mesmo marcador não disputam o topo."""
    top, vistos = [], set()
    for s in lista:
        if len(top) < limite and s["marcador"] not in vistos:
            top.append(s)
            vistos.add(s["marcador"])
    return top, [s for s in lista if s not in top]


def painel(con, hoje=None, metricas=None, limite=LIMITE, estados=None) -> dict:
    """A fachada das telas e do Assistente: {"marcadores": {PJ, PF, nota, todos}, "sugestoes": [as principais], "mais": [o resto]}."""
    ctx = marcadores.contexto(con, hoje, metricas, estados)
    marc = marcadores.calcular(ctx)
    top, resto = escolher(calcular(ctx, marc), limite)
    return {"hoje": ctx["hoje"], "janela": ctx["janela"], "marcadores": marc, "sugestoes": top, "mais": resto}


def adiar(con, chave, hoje=None) -> str:
    """"Já fiz": esconde a sugestão por 30 dias. Devolve a data em que ela pode voltar."""
    ate = (dt.date.fromisoformat(hoje or _hoje()) + dt.timedelta(days=ADIAR_DIAS)).isoformat()
    with con:
        con.execute("""INSERT INTO parametros (grupo, chave, valor_texto, ordem) VALUES (?, ?, ?, 0)
                       ON CONFLICT(grupo, chave) DO UPDATE SET valor_texto=excluded.valor_texto""", (GRUPO_ADIADA, chave, ate))
    return ate
