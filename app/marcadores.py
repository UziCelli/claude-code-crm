"""Saúde financeira: marcadores da empresa (PJ) e da vida pessoal (PF), cada um com cor, uma frase e o botão que leva à solução.

Duas etapas, como em alunos.estado():
  contexto(con, hoje, metricas, estados)  faz todo o SQL (número de consultas fixo: não cresce com alunos nem lançamentos);
  calcular(ctx)                           é uma função pura: {"PJ": [grupos], "PF": [grupos], "nota": {...}}.
Janela = os 3 últimos meses FECHADOS (o mês corrente, pela metade, engana), somando antes de dividir (Σ ÷ Σ, nunca média de razões).
Margens e pontos de equilíbrio só valem desde que fixo e variável existem (migrar_financeiro.INICIO): antes disso ficam cinza.
Empréstimo não é receita e Retirada (salário) não é custo: já vem assim de financeiro.resumo_mes. O DAS conta como custo variável
(é uma % do faturamento): usa-se DAS% × receita e tira-se o DAS já pago dos custos, para não contar duas vezes.
"""
import datetime as dt
import math
import re

from . import alunos, db, financeiro

try:
    from .migrar_financeiro import INICIO   # mês em que fixo/variável passam a existir
except ImportError:   # sem o openpyxl da migração: o valor é fixo
    INICIO = "2026-10"

MAX_IDS = 200   # alunos de uma lista filtrada de /clientes?ids=
COR_GRAV = {"vermelho": 1, "amarelo": 2, "verde": 4, "cinza": 5}
PONTOS = {"verde": 100, "amarelo": 50, "vermelho": 0}
MORADIA = re.compile(r"\b(aluguel|condom\w*|moradia|luz|energia|[áa]gua|internet|g[áa]s|iptu)\b", re.I)
DIVIDA = re.compile(r"d[ií]vida|financiamento|empr[ée]stimo|cons[óo]rcio|parcela", re.I)

# Faixas de cada marcador. maior: quanto maior melhor (verde se valor >= verde, amarelo se >= amarelo); menor: o contrário.
# Podem ser trocadas em Configurações-parâmetros, grupo saude_faixas, com as chaves "<marcador>_verde" e "<marcador>_amarelo".
FAIXAS = {
    "faturamento": {"verde": 0.0, "amarelo": -0.10, "sentido": "maior"},            # variação sobre os 3 meses anteriores
    "margem_contribuicao": {"verde": 0.70, "amarelo": 0.50, "sentido": "maior"},
    "margem_lucro": {"verde": 0.40, "amarelo": 0.20, "sentido": "maior"},
    "margem_liquida": {"verde": 0.15, "amarelo": 0.05, "sentido": "maior"},
    "pe_contabil": {"verde": 1.20, "amarelo": 1.00, "sentido": "maior"},            # receita ÷ ponto de equilíbrio
    "pe_economico": {"verde": 1.00, "amarelo": 0.90, "sentido": "maior"},
    "caixa": {"verde": 0.5, "amarelo": 0.0, "sentido": "maior"},                    # menor saldo em 90 dias ÷ custo de 1 mês
    "reserva": {"verde": 3.0, "amarelo": 1.0, "sentido": "maior"},                  # meses de custo fixo guardados
    "vencidas": {"verde": 0.05, "amarelo": 0.15, "sentido": "menor"},               # vencido ÷ receita recorrente
    "saidas": {"verde": 1.0, "amarelo": 2.0, "sentido": "menor"},                   # alunos que saem por mês, em múltiplos da meta
    "agenda": {"verde": 1.0, "amarelo": 0.70, "sentido": "maior"},                  # horas ocupadas, em fração da meta
    "renda_pessoa": {"verde": 3.0, "amarelo": 2.0, "sentido": "maior"},             # salários mínimos por pessoa
    "sobra": {"verde": 0.20, "amarelo": 0.10, "sentido": "maior"},
    "contas_fixas": {"verde": 0.50, "amarelo": 0.60, "sentido": "menor"},
    "moradia": {"verde": 0.30, "amarelo": 0.35, "sentido": "menor"},
    "dividas": {"verde": 0.15, "amarelo": 0.30, "sentido": "menor"},
    "reserva_pf": {"verde": 6.0, "amarelo": 3.0, "sentido": "maior"},               # meses de custo de vida guardados
}
GRUPOS_PJ = (("Resultado", ("faturamento", "margem_contribuicao", "margem_lucro", "margem_liquida")),
             ("Ponto de equilíbrio", ("pe_contabil", "pe_economico")),
             ("Fôlego", ("caixa_pj", "reserva_pj", "vencidas")),
             ("Clientes", ("saidas", "agenda")))
GRUPOS_PF = (("Renda e gastos", ("renda_pessoa", "custo_vida", "sobra")),
             ("Compromissos", ("contas_fixas", "moradia", "dividas")),
             ("Fôlego", ("reserva_pf", "caixa_pf")))


def _main():
    from . import main   # import tardio: main importa este módulo
    return main


# ---------- pequenas contas ----------
def _hoje(hoje) -> str:
    if hoje is None:
        return dt.date.today().isoformat()
    return hoje.isoformat() if isinstance(hoje, dt.date) else str(hoje)[:10]


def cor_da_faixa(valor, faixa) -> str:
    """verde / amarelo / vermelho de um valor numa faixa {verde, amarelo, sentido}. O limite exato conta como a cor melhor."""
    v = round(float(valor), 6)
    if faixa["sentido"] == "menor":
        return "verde" if v <= faixa["verde"] + 1e-9 else ("amarelo" if v <= faixa["amarelo"] + 1e-9 else "vermelho")
    return "verde" if v >= faixa["verde"] - 1e-9 else ("amarelo" if v >= faixa["amarelo"] - 1e-9 else "vermelho")


def _faixas(con) -> dict:
    """FAIXAS com o que o usuário trocou no grupo de parâmetros saude_faixas."""
    out = {k: dict(v) for k, v in FAIXAS.items()}
    for chave, valor in db.parametros(con, "saude_faixas").items():
        nome, _, lado = chave.rpartition("_")
        if nome in out and lado in ("verde", "amarelo") and isinstance(valor, (int, float)):
            out[nome][lado] = float(valor)
    return out


def _pct(v) -> str:
    return f"{v * 100:.0f}%".replace("-", "−")


def _num(v, casas=1) -> str:
    t = f"{v:.{casas}f}".replace(".", ",")
    return t[:-2] if t.endswith(",0") else t   # 3,0 vira 3


def _m(v) -> str:
    """R$ em reais inteiros (R$ 1.234; negativo −R$ 50): números redondos leem mais rápido que centavos."""
    n = int(round(float(v)))
    t = f"R$ {abs(n):,}".replace(",", ".")
    return f"−{t}" if n < 0 else t


def _tendencia(atual, anterior, minimo) -> str | None:
    """'↑' / '↓' se mudou mais que `minimo` (na unidade do valor); None sem como comparar."""
    if atual is None or anterior is None:
        return None
    d = atual - anterior
    return "↑" if d > minimo else ("↓" if d < -minimo else None)


def _bom(seta, maior_melhor=True):
    if seta is None:
        return None
    return (seta == "↑") == maior_melhor


def marcador(chave, nome, grupo, valor, texto, cor, frase, acao, tendencia=None, bom=None, dados=None, na_nota=True) -> dict:
    """O formato único de um marcador. frase = 1 frase curta (até 90 letras) que já diz o que é bom; acao = {rotulo, href}."""
    return {"chave": chave, "nome": nome, "grupo": grupo, "valor": valor, "texto": texto, "cor": cor, "frase": frase,
            "tendencia": tendencia, "tendencia_boa": bom, "acao": acao, "dados": dados or {}, "na_nota": na_nota}


def _cinza(chave, nome, grupo, frase, acao) -> dict:
    return marcador(chave, nome, grupo, None, "sem dados", "cinza", frase, acao)


def _lista(ids, motivo) -> str:
    return f"/clientes?ids={','.join(map(str, list(ids)[:MAX_IDS]))}&motivo={motivo}"


A_RECORRENTES = {"rotulo": "Contas fixas", "href": "/financeiro#recorrentes"}
A_SALDOS = {"rotulo": "Atualizar saldos", "href": "/financeiro?abrir=saldos"}
A_90_DIAS = {"rotulo": "Ver 90 dias", "href": "/financeiro/previsao"}
A_LIVRO_PJ = {"rotulo": "Ver lançamentos", "href": "/financeiro?escopo=PJ#livro-caixa"}
A_LIVRO_PF = {"rotulo": "Ver lançamentos", "href": "/financeiro?escopo=PF#livro-caixa"}


# =====================================================================
# 1. contexto: todo o SQL
# =====================================================================
def _vazio_pj() -> dict:
    return {"receita": 0.0, "fixos": 0.0, "variaveis": 0.0, "das_pago": 0.0, "das": 0.0, "das_fixo": 0.0, "retirada": 0.0, "lucro": 0.0,
            "pro_labore": 0.0, "inss": 0.0, "saidas": 0.0, "var_cat": {}, "fixo_itens": {}}


def _vazio_pf() -> dict:
    return {"entradas": 0.0, "saidas": 0.0, "fixos": 0.0, "moradia": 0.0, "cats": {}}


def _meses_pj(con, meses) -> dict:
    """Números da PJ por mês: resumo_mes (receita, fixos, variáveis, DAS, pró-labore) mais o DAS já pago tirado dos custos e as
    categorias de custo. Uma consulta agrupada para os 6 meses, além de resumo_mes."""
    out = {}
    for mes in meses:
        r = financeiro.resumo_mes(con, mes)
        out[mes] = dict(_vazio_pj(), receita=r["receita"], fixos=r["custos_fixos"], variaveis=r["custos_variaveis"], das=r["das"],
                        retirada=r["retirada"], lucro=r["lucro"], pro_labore=r["pro_labore"], inss=r["inss"], pf=r["pf"],
                        emprestimos=r["emprestimos"])
    for mes, descricao, categoria, fixo, total in con.execute(
        """SELECT substr(l.data,1,7), l.descricao, l.categoria, r.fixo, SUM(l.valor) FROM lancamentos l
           LEFT JOIN recorrencias r ON r.id = l.recorrencia_id
           WHERE l.escopo='PJ' AND l.tipo='saida' AND l.excluido_em IS NULL AND l.pago_em IS NOT NULL
                 AND substr(l.data,1,7) BETWEEN ? AND ? AND l.categoria NOT IN (?, ?)
           GROUP BY substr(l.data,1,7), l.descricao, l.categoria, r.fixo""",
        (meses[0], meses[-1], financeiro.RETIRADA, financeiro.DEVOLUCAO)):
        d = out.get(mes)
        if d is None:
            continue
        d["saidas"] += total
        if financeiro.eh_das(descricao, categoria):
            d["das_pago"] += total
            if fixo == 1:
                d["das_fixo"] += total
        elif fixo == 1:
            nome = descricao or categoria
            d["fixo_itens"][nome] = d["fixo_itens"].get(nome, 0.0) + total
        else:
            d["var_cat"][categoria] = d["var_cat"].get(categoria, 0.0) + total
    return out


def _meses_pf(con, meses) -> dict:
    """Entradas, saídas, contas fixas, moradia e categorias da PF por mês (só o que foi pago), numa consulta."""
    out = {m: _vazio_pf() for m in meses}
    for mes, tipo, categoria, descricao, fixo, total in con.execute(
        """SELECT substr(l.data,1,7), l.tipo, l.categoria, l.descricao, r.fixo, SUM(l.valor) FROM lancamentos l
           LEFT JOIN recorrencias r ON r.id = l.recorrencia_id
           WHERE l.escopo='PF' AND l.excluido_em IS NULL AND l.pago_em IS NOT NULL AND substr(l.data,1,7) BETWEEN ? AND ?
                 AND NOT (l.tipo='entrada' AND l.categoria=?)   -- empréstimo recebido não é renda
           GROUP BY substr(l.data,1,7), l.tipo, l.categoria, l.descricao, r.fixo""", (meses[0], meses[-1], financeiro.EMPRESTIMO)):
        d = out.get(mes)
        if d is None:
            continue
        if tipo == "entrada":
            d["entradas"] += total
            continue
        d["saidas"] += total
        d["cats"][categoria] = d["cats"].get(categoria, 0.0) + total
        if fixo == 1:
            d["fixos"] += total
        if MORADIA.search(categoria or "") or MORADIA.search(descricao or ""):
            d["moradia"] += total
    return out


def _data_do_aluno(c) -> str | None:
    m = _main()
    return m.data_iso(c["data_inicio"]) or (str(c["criado_em"])[:10] if c["criado_em"] else None)


def contexto(con, hoje=None, metricas=None, estados=None) -> dict:
    """Tudo o que os marcadores e as sugestões precisam, lido do banco com um número fixo de consultas.
    metricas = main.calcular_metricas já calculado (o Painel passa o seu); estados = alunos.estado já calculado."""
    m = _main()
    h = _hoje(hoje)
    mes = h[:7]
    janela = [financeiro.somar_meses(mes, -k) for k in (3, 2, 1)]
    anteriores = [financeiro.somar_meses(mes, -k) for k in (6, 5, 4)]
    todos = anteriores + janela
    metricas = metricas or m.calcular_metricas(con)
    estados = estados if estados is not None else alunos.estado(con, h)
    pj, pf = _meses_pj(con, todos), _meses_pf(con, todos)
    parametros = lambda g: db.parametros(con, g)   # noqa: E731
    fiscal, salario, familia, saude = parametros("fiscal"), parametros("salario"), parametros("familia"), parametros("saude")
    metas = parametros("metas")
    previsao = financeiro.previsao(con, h, 13)
    ate30 = (dt.date.fromisoformat(h) + dt.timedelta(days=30)).isoformat()
    parcelas_total = {r["id"]: r["parcela_total"] for r in con.execute(
        "SELECT id, parcela_total FROM lancamentos WHERE escopo='PF' AND tipo='saida' AND pago_em IS NULL AND excluido_em IS NULL "
        "AND parcela_total > 1")}
    juros = parametros("impacto_juros")
    dividas = []
    for i in financeiro.em_aberto_ate(con, ate30, h):
        if i["escopo"] == "PF" and i["tipo"] == "saida" and (DIVIDA.search(i["categoria"] or "") or
                                                              (i["origem"] == "lancamento" and parcelas_total.get(i["id"]))):
            dividas.append({"descricao": i["descricao"], "categoria": i["categoria"], "valor": i["valor"], "data": i["data"],
                            "juros": float(juros.get(f"PF {i['categoria']}", 0) or 0)})

    # alunos: ativos e ex-alunos, tudo de uma vez
    todos_alunos = con.execute("""SELECT id, nome, telefone, tipo_servico, plano, pessoas, valor, status, canal_origem, local, forma_pagamento,
                                  data_inicio, criado_em, atualizado_em FROM clientes WHERE excluido_em IS NULL""").fetchall()
    saiu_em = {r[0]: m.data_iso(r[1]) for r in con.execute(
        "SELECT cliente_id, MAX(data) FROM cliente_eventos WHERE tipo='status' AND descricao LIKE '%inativo%' AND excluido_em IS NULL "
        "GROUP BY cliente_id")}
    ativos = [c for c in todos_alunos if c["status"] == "ativo"]
    limite_inativo = (dt.date.fromisoformat(h) - dt.timedelta(days=365)).isoformat()
    ex_alunos = []
    for c in todos_alunos:
        if c["status"] == "inativo":
            quando = saiu_em.get(c["id"]) or str(c["atualizado_em"] or "")[:10]
            if quando and quando >= limite_inativo:
                ex_alunos.append({"id": c["id"], "nome": c["nome"], "valor": c["valor"] or 0, "saiu_em": quando})
    ate90 = (dt.date.fromisoformat(h) - dt.timedelta(days=90)).isoformat()
    novos_por_canal = {}
    for c in todos_alunos:
        inicio = _data_do_aluno(c)
        if inicio and inicio >= ate90:
            novos_por_canal[c["canal_origem"] or ""] = novos_por_canal.get(c["canal_origem"] or "", 0) + 1
    veteranos = [c["id"] for c in ativos if (estados.get(c["id"]) or {}).get("situacao") == "em_dia"
                 and (_data_do_aluno(c) or "9999") <= ate90]
    solos = [c["id"] for c in ativos if (c["pessoas"] or 1) == 1 and (estados.get(c["id"]) or {}).get("situacao") == "em_dia"
             and (estados.get(c["id"]) or {}).get("tem_aulas")]
    # reajuste: quem paga menos que o preço mínimo do motor de preços (uma consulta de preços para todos)
    from . import precos
    p, bases = precos.carregar_parametros(con), m.carregar_bases(con)
    abaixo = []
    for c in ativos:
        est = m.estimativa_cliente(con, c, p, bases)
        if est and est["abaixo_margem"] and est["preco_minimo"] > (c["valor"] or 0):
            abaixo.append({"id": c["id"], "nome": c["nome"], "valor": c["valor"] or 0, "minimo": est["preco_minimo"],
                           "mensalidade": c["tipo_servico"] == "Mensalidade"})
    perdidos_leads = [dict(r) for r in con.execute(
        """SELECT id, nome, telefone FROM leads WHERE excluido_em IS NULL AND etapa='perdido' AND data_mudanca_etapa >= ?""", (ate90,))]
    vale_livre = con.execute("""SELECT COUNT(*) FROM (SELECT DISTINCT dia, local, hora FROM grade_slots
                                WHERE status='livre' AND COALESCE(multiplicador, 1) < 1 AND dia BETWEEN 1 AND 6)""").fetchone()[0]
    espera_vale = con.execute("SELECT COUNT(*) FROM lista_espera WHERE excluido_em IS NULL AND hora NOT IN (7,9,18,19)").fetchone()[0]
    gastos = {r[0]: {"gasto": r[1], "clientes": r[2]} for r in con.execute(
        """SELECT canal, SUM(mensalidade+anuncios+comissoes+outros), SUM(clientes) FROM gastos_marketing
           WHERE excluido_em IS NULL AND mes BETWEEN ? AND ? GROUP BY canal""", (janela[0], janela[-1]))}
    receita_pico = con.execute("""SELECT COALESCE(SUM(valor), 0) FROM clientes WHERE excluido_em IS NULL AND status='ativo' AND id IN
                                  (SELECT cliente_id FROM agenda_fixos WHERE excluido_em IS NULL AND hora IN (7,9,18,19))""").fetchone()[0]
    adiadas = {k: v for k, v in parametros("sugestao_adiada").items() if isinstance(v, str)}
    valores = [c["valor"] or 0 for c in ativos if (c["valor"] or 0) > 0]
    return {
        "hoje": h, "mes": mes, "janela": janela, "anteriores": anteriores,
        "validos": [x for x in janela if x >= INICIO], "validos_ant": [x for x in anteriores if x >= INICIO],
        "pj": pj, "pf": pf, "faixas": _faixas(con), "metricas": metricas, "estados": estados, "metas": metas,
        "salario_minimo": float(fiscal.get("salario_minimo") or 0), "pessoas": max(int(familia.get("pessoas") or 2), 1),
        "salario": float(salario.get("valor") or 0), "reserva_desejada": float(saude.get("reserva_mensal_desejada") or 0),
        "sugestao_salario": financeiro.sugestao_salario(con, mes), "colchao": financeiro.colchao(con, mes), "previsao": previsao,
        "fixos_pj": financeiro.fixos_previstos(con, mes, "PJ"), "dividas": dividas,
        "ids_cobrar": [i for i, e in estados.items() if e["situacao"] == "cobrar"],
        "cobrar_total": round(sum((e["cobranca"] or {}).get("valor") or e["valor"] for e in estados.values() if e["situacao"] == "cobrar"), 2),
        "ex_alunos": ex_alunos, "veteranos": veteranos, "solos": solos, "abaixo": abaixo, "leads_perdidos": perdidos_leads,
        "novos_por_canal": novos_por_canal, "vale_livre": vale_livre, "espera_vale": espera_vale, "gastos_canal": gastos,
        "cac_max": float(metas.get("cac_max") or 0), "ticket_medio": round(sum(valores) / len(valores), 2) if valores else 0.0,
        "adiadas": adiadas, "receita_pico": round(receita_pico, 2),
        "valor_solo": round(sum(c["valor"] or 0 for c in ativos if c["id"] in solos) / len(solos), 2) if solos else 0.0,
        "grupo_mult2": float(parametros("grupo_multiplicador").get("2") or 1.6),
    }


# =====================================================================
# 2. calcular: função pura
# =====================================================================
def _soma(ctx, escopo, meses, campo) -> float:
    return sum(ctx[escopo][x][campo] for x in meses)


def _com_dados_pj(ctx, meses) -> list:
    """Meses da lista em que a PJ tem algum lançamento pago (um mês sem nada não é um mês de queda)."""
    return [x for x in meses if ctx["pj"][x]["receita"] > 0 or ctx["pj"][x]["saidas"] > 0]


def _com_dados_pf(ctx, meses) -> list:
    return [x for x in meses if ctx["pf"][x]["entradas"] > 0 or ctx["pf"][x]["saidas"] > 0]


def _margens(ctx, meses) -> dict | None:
    """Σ de receita, contribuição, lucro operacional e líquido dos meses (o DAS é DAS% × receita; o DAS pago sai dos custos). None sem receita."""
    receita = _soma(ctx, "pj", meses, "receita")
    if not meses or receita <= 0:
        return None
    das = _soma(ctx, "pj", meses, "das")
    variaveis = _soma(ctx, "pj", meses, "variaveis") - sum(_das_variavel(ctx["pj"][x]) for x in meses)
    fixos = _soma(ctx, "pj", meses, "fixos") - sum(_das_fixo(ctx["pj"][x]) for x in meses)
    contribuicao = receita - variaveis - das
    operacional = contribuicao - fixos
    liquido = operacional - _soma(ctx, "pj", meses, "pro_labore") - _soma(ctx, "pj", meses, "inss")
    n = len(meses)
    return {"n": n, "receita": receita, "variaveis": variaveis, "fixos": fixos, "das": das, "contribuicao": contribuicao,
            "operacional": operacional, "liquido": liquido, "receita_mes": receita / n, "fixos_mes": fixos / n,
            "mc": contribuicao / receita, "ml": operacional / receita, "mliq": liquido / receita}


def _das_fixo(d) -> float:
    """DAS pago que entrou em custos fixos (recorrência de DAS marcada como fixa): sai de lá, porque o DAS já vem de DAS% × receita."""
    return d["das_fixo"]


def _das_variavel(d) -> float:
    return d["das_pago"] - d["das_fixo"]


def _nome_mes(mes) -> str:
    return f"{mes[5:]}/{mes[:4]}"


def _faturamento(ctx):
    f, g = ctx["faixas"]["faturamento"], "Resultado"
    meses = _com_dados_pj(ctx, ctx["janela"])
    ant = _com_dados_pj(ctx, ctx["anteriores"])
    receita = _soma(ctx, "pj", meses, "receita") if meses else 0
    if not meses or receita <= 0:
        return _cinza("faturamento", "Faturamento", g, "Sem entradas pagas nos últimos 3 meses.",
                      {"rotulo": "Lançar entrada", "href": "/financeiro?escopo=PJ"})
    media = receita / len(meses)
    media_ant = _soma(ctx, "pj", ant, "receita") / len(ant) if ant else 0
    if media_ant <= 0:
        cor, var, frase = "verde", None, f"Média de {_m(media)} por mês. Bom é não cair."
        seta = None
    else:
        var = media / media_ant - 1
        cor = cor_da_faixa(var, f)
        seta = _tendencia(media, media_ant, media_ant * 0.02)
        frase = f"{'Subiu' if var >= 0 else 'Caiu'} {_pct(abs(var))} contra os 3 meses antes. Bom é não cair."
    acao = {"rotulo": "Ver mensalidades", "href": "/financeiro/mensalidades"}
    return marcador("faturamento", "Faturamento", g, round(media, 2), f"{_m(media)}/mês", cor, frase, acao, seta, _bom(seta),
                    {"media": round(media, 2), "anterior": round(media_ant, 2), "variacao": var})


def _gray_antes_de_inicio(chave, nome, g, ctx):
    return _cinza(chave, nome, g, "Aparece no fim do mês, quando já der para separar fixo de variável.", A_RECORRENTES)


def _margem(ctx, chave, nome, campo, frase_base):
    g = "Resultado"
    meses = [x for x in _com_dados_pj(ctx, ctx["janela"]) if x in ctx["validos"]]
    mg = _margens(ctx, meses)
    if not ctx["validos"]:
        return _gray_antes_de_inicio(chave, nome, g, ctx)
    if mg is None:
        return _cinza(chave, nome, g, "Sem receita nos meses fechados para calcular.", {"rotulo": "Lançar entrada", "href": "/financeiro?escopo=PJ"})
    faixa = ctx["faixas"][chave]
    valor = mg[campo]
    cor = cor_da_faixa(valor, faixa)
    ant = [x for x in _com_dados_pj(ctx, ctx["anteriores"]) if x in ctx["validos_ant"]]
    mg_ant = _margens(ctx, ant)
    seta = _tendencia(valor, mg_ant[campo], 0.01) if mg_ant else None
    frase = f"{frase_base}: {_pct(valor)}. Bom é {_pct(faixa['verde'])} ou mais."
    acao = {"rotulo": "Ver custos", "href": "/financeiro?escopo=PJ#livro-caixa"} if cor != "verde" else A_LIVRO_PJ
    return marcador(chave, nome, g, round(valor, 4), _pct(valor), cor, frase, acao, seta, _bom(seta), {"margem": mg})


def _equilibrio(ctx, chave, nome, economico):
    g = "Ponto de equilíbrio"
    meses = [x for x in _com_dados_pj(ctx, ctx["janela"]) if x in ctx["validos"]]
    if not ctx["validos"]:
        return _gray_antes_de_inicio(chave, nome, g, ctx)
    mg = _margens(ctx, meses)
    if mg is None:
        return _cinza(chave, nome, g, "Sem receita nos meses fechados para calcular.", {"rotulo": "Lançar entrada", "href": "/financeiro?escopo=PJ"})
    fixos = mg["fixos_mes"]
    salario = ctx["salario"] or (sum(ctx["pj"][x]["retirada"] for x in meses) / len(meses))
    extra = (salario + ctx["reserva_desejada"]) if economico else 0
    if fixos + extra <= 0:
        frase = "Defina o salário em Configurações para calcular." if economico else "Cadastre as contas fixas para calcular."
        acao = {"rotulo": "Definir salário", "href": "/configuracoes#cfg-salario"} if economico else A_RECORRENTES
        return _cinza(chave, nome, g, frase, acao)
    if mg["mc"] <= 0:
        return marcador(chave, nome, g, None, "sem margem", "vermelho", "Cada venda não cobre os custos variáveis. Bom é sobrar 50% ou mais.",
                        {"rotulo": "Ver custos", "href": "/financeiro?escopo=PJ#livro-caixa"}, dados={"margem": mg})
    pe = (fixos + extra) / mg["mc"]
    razao = mg["receita_mes"] / pe
    cor = cor_da_faixa(razao, ctx["faixas"][chave])
    diff = mg["receita_mes"] - pe
    if economico:
        frase = (f"Para valer a pena precisa de {_m(pe)}; você fez {_m(mg['receita_mes'])}." if len(_m(pe)) < 12
                 else f"Precisa de {_m(pe)} por mês para valer a pena.")
    else:
        frase = f"Receita {_m(abs(diff))} {'acima' if diff >= 0 else 'abaixo'} do mínimo de {_m(pe)}. Bom é 20% acima."
    acao = {"rotulo": "Ver o que fazer", "href": "/financeiro/painel#o-que-fazer"} if cor != "verde" else A_RECORRENTES
    return marcador(chave, nome, g, round(pe, 2), f"{_m(pe)}/mês", cor, frase, acao,
                    dados={"pe": round(pe, 2), "razao": razao, "falta": round(max(pe - mg["receita_mes"], 0), 2),
                           "receita_mes": round(mg["receita_mes"], 2), "mc": mg["mc"], "margem": mg})


def _caixa(ctx, escopo):
    chave = "caixa_pj" if escopo == "PJ" else "caixa_pf"
    nome = "Caixa 90 dias"
    g = "Fôlego"
    prev = ctx["previsao"]
    if prev["sem_saldo"][escopo]:
        return _cinza(chave, nome, g, "Digite os saldos das contas para prever o caixa.", A_SALDOS)
    menor = prev["menor_dia"][escopo]
    aperto = prev["aperto"].get(escopo)
    if escopo == "PJ":
        base = ctx["fixos_pj"]
    else:
        meses = _com_dados_pf(ctx, ctx["janela"])
        base = _soma(ctx, "pf", meses, "saidas") / len(meses) if meses else 0
    f = ctx["faixas"]["caixa"]
    if aperto or menor["saldo"] < 0:
        cor = "vermelho"
    elif base > 0:
        cor = cor_da_faixa(menor["saldo"] / base, f)
    else:
        cor = "verde"
    dd = f"{menor['data'][8:10]}/{menor['data'][5:7]}"
    if cor == "vermelho":
        frase = f"Fica negativo em {dd}, chegando a {_m(menor['saldo'])}. Bom é nunca ficar negativo."
    elif cor == "amarelo":
        frase = f"Menor saldo: {_m(menor['saldo'])} em {dd}. Bom é ter folga de meio mês de custos."
    else:
        frase = f"Menor saldo: {_m(menor['saldo'])} em {dd}, sem ficar negativo."
    acao = A_SALDOS if prev["desatualizado"][escopo] and cor != "verde" else A_90_DIAS
    return marcador(chave, nome, g, menor["saldo"], _m(menor["saldo"]), cor, frase, acao,
                    dados={"menor": menor["saldo"], "data": menor["data"], "aperto": aperto, "base": round(base, 2)})


def _reserva_pj(ctx):
    c, g = ctx["colchao"], "Fôlego"
    if c["cobre_meses"] is None:
        return _cinza("reserva_pj", "Reserva", g, "Cadastre as contas fixas para saber quanto guardar.", A_RECORRENTES)
    faixa = dict(ctx["faixas"]["reserva"])
    if c["meses_meta"]:
        faixa["verde"] = float(c["meses_meta"])
    cor = cor_da_faixa(c["cobre_meses"], faixa)
    frase = f"Guardado cobre {_num(c['cobre_meses'])} mês(es) de custos. Bom é {_num(faixa['verde'], 0)} meses ou mais."
    acao = {"rotulo": "Ver reserva", "href": "/financeiro/painel#reserva"}
    if cor != "verde":
        acao = {"rotulo": "Definir a meta", "href": "/configuracoes#cfg-colchao"} if not c["meses_meta"] else acao
    return marcador("reserva_pj", "Reserva", g, c["cobre_meses"], f"{_num(c['cobre_meses'])} meses", cor, frase, acao,
                    dados={"cobre": c["cobre_meses"], "meta_meses": faixa["verde"], "mensal": c["mensal"], "guardado": c["guardado"]})


def _vencidas(ctx):
    g, nome = "Fôlego", "Mensalidades vencidas"
    recorrente = ctx["metricas"]["faturamento_recorrente"]
    if not recorrente:
        return _cinza("vencidas", nome, g, "Cadastre as mensalidades dos alunos ativos.", {"rotulo": "Ver alunos", "href": "/clientes"})
    total = ctx["cobrar_total"]
    razao = total / recorrente
    cor = cor_da_faixa(razao, ctx["faixas"]["vencidas"])
    n = len(ctx["ids_cobrar"])
    if not n:
        frase, acao = "Nenhuma mensalidade vencida. Bom é até 5% da receita.", {"rotulo": "Ver mensalidades", "href": "/financeiro/mensalidades"}
    else:
        frase = f"{n} aluno{'s' if n > 1 else ''} atrasado{'s' if n > 1 else ''} ({_m(total)}). Bom é até 5% da receita."
        acao = {"rotulo": f"Cobrar ({n})", "href": _lista(ctx["ids_cobrar"], "cobrar")}
    return marcador("vencidas", nome, g, round(razao, 4), _pct(razao), cor, frase, acao, dados={"total": total, "n": n, "razao": razao})


def _saidas(ctx):
    g, nome = "Clientes", "Alunos que saem"
    meta = float(ctx["metas"].get("perdidos_max") or 1)
    ex = ctx["ex_alunos"]
    recentes = [e for e in ex if e["saiu_em"] >= f"{ctx['janela'][0]}-01" and e["saiu_em"] < f"{ctx['mes']}-01"]
    anteriores = [e for e in ex if f"{ctx['anteriores'][0]}-01" <= e["saiu_em"] < f"{ctx['janela'][0]}-01"]
    media = len(recentes) / 3
    f = ctx["faixas"]["saidas"]
    cor = cor_da_faixa(media / meta if meta else media, f)
    seta = _tendencia(media, len(anteriores) / 3, 0.01) if anteriores or recentes else None
    frase = f"Saem {_num(media)} aluno(s) por mês. Bom é até {_num(meta * f['verde'], 0)} por mês."
    if ex:
        acao = {"rotulo": f"Chamar de volta ({len(ex)})", "href": _lista([e['id'] for e in ex], "reativar")}
    else:
        acao = {"rotulo": "Ver inativos", "href": "/clientes?status=inativo"}
    return marcador("saidas", nome, g, round(media, 2), f"{_num(media)}/mês", cor, frase, acao, seta, _bom(seta, False),
                    {"media": media, "meta": meta, "ex_alunos": len(ex)})


def _agenda(ctx):
    g, nome = "Clientes", "Agenda ocupada"
    horas, meta = ctx["metricas"]["horas_ocupadas"], float(ctx["metas"].get("horas_dez26") or 0)
    if not meta:
        return _cinza("agenda", nome, g, "Defina a meta de horas em Configurações.", {"rotulo": "Definir meta", "href": "/configuracoes#cfg-metas"})
    f = ctx["faixas"]["agenda"]
    cor = cor_da_faixa(horas / meta, f)
    frase = f"{_num(horas, 0)} horas ocupadas por mês. Bom é {_num(meta * f['verde'], 0)} ou mais."
    vet = ctx["veteranos"]
    acao = {"rotulo": f"Pedir indicação ({len(vet)})", "href": _lista(vet, "indicacao")} if vet and cor != "verde" else {"rotulo": "Ver agenda", "href": "/grade"}
    return marcador("agenda", nome, g, horas, f"{_num(horas, 0)} h", cor, frase, acao, dados={"horas": horas, "meta": meta})


# ---------- PF ----------
def _pf_medias(ctx):
    meses = _com_dados_pf(ctx, ctx["janela"])
    if not meses:
        return None
    n = len(meses)
    ent, sai = _soma(ctx, "pf", meses, "entradas"), _soma(ctx, "pf", meses, "saidas")
    ant = _com_dados_pf(ctx, ctx["anteriores"])
    return {"meses": meses, "n": n, "entradas": ent, "saidas": sai, "renda": ent / n, "custo": sai / n,
            "ant": {"renda": _soma(ctx, "pf", ant, "entradas") / len(ant), "custo": _soma(ctx, "pf", ant, "saidas") / len(ant),
                    "entradas": _soma(ctx, "pf", ant, "entradas"), "saidas": _soma(ctx, "pf", ant, "saidas")} if ant else None}


def _sem_pf(chave, nome, g):
    return _cinza(chave, nome, g, "Lance as entradas e saídas da PF para calcular.", {"rotulo": "Lançar na PF", "href": "/financeiro?escopo=PF"})


def _renda_pessoa(ctx, pf):
    g, nome = "Renda e gastos", "Renda por pessoa"
    if not pf or pf["renda"] <= 0:
        return _sem_pf("renda_pessoa", nome, g)
    if ctx["salario_minimo"] <= 0:
        return _cinza("renda_pessoa", nome, g, "Defina o salário mínimo em Configurações.", {"rotulo": "Definir", "href": "/configuracoes#cfg-fiscal"})
    por_pessoa = pf["renda"] / ctx["pessoas"]
    sm = por_pessoa / ctx["salario_minimo"]
    f = ctx["faixas"]["renda_pessoa"]
    cor = cor_da_faixa(sm, f)
    seta = _tendencia(pf["renda"], pf["ant"]["renda"], pf["ant"]["renda"] * 0.02) if pf["ant"] else None
    frase = f"Cada pessoa vive com {_m(por_pessoa)} ({_num(sm)} SM). Bom é {_num(f['verde'], 0)} SM ou mais."
    return marcador("renda_pessoa", nome, g, round(sm, 2), f"{_num(sm)} SM", cor, frase,
                    {"rotulo": "Ver entradas", "href": "/financeiro?escopo=PF#livro-caixa"}, seta, _bom(seta),
                    {"por_pessoa": round(por_pessoa, 2), "renda": round(pf["renda"], 2)})


def _sobra(ctx, pf):
    g, nome = "Renda e gastos", "Sobra do mês"
    if not pf or pf["entradas"] <= 0:
        return _sem_pf("sobra", nome, g)
    sobra = (pf["entradas"] - pf["saidas"]) / pf["entradas"]
    f = ctx["faixas"]["sobra"]
    cor = cor_da_faixa(sobra, f)
    ant = pf["ant"]
    seta = _tendencia(sobra, (ant["entradas"] - ant["saidas"]) / ant["entradas"], 0.01) if ant and ant["entradas"] > 0 else None
    frase = f"Sobra {_pct(sobra)} do que entra. Bom é {_pct(f['verde'])} ou mais."
    return marcador("sobra", nome, g, round(sobra, 4), _pct(sobra), cor, frase, {"rotulo": "Ver gastos", "href": "/financeiro?escopo=PF#livro-caixa"},
                    seta, _bom(seta), {"sobra": sobra, "media_sobra": round(pf["renda"] - pf["custo"], 2)})


def _custo_vida(ctx, pf, sobra):
    g, nome = "Renda e gastos", "Custo de vida por pessoa"
    if not pf or pf["saidas"] <= 0:
        return _sem_pf("custo_vida", nome, g)
    por_pessoa = pf["custo"] / ctx["pessoas"]
    seta = _tendencia(pf["custo"], pf["ant"]["custo"], pf["ant"]["custo"] * 0.02) if pf["ant"] else None
    cor = sobra["cor"] if sobra["cor"] != "cinza" else "amarelo"
    return marcador("custo_vida", nome, g, round(por_pessoa, 2), f"{_m(por_pessoa)}/mês", cor,
                    f"Cada pessoa gasta {_m(por_pessoa)} por mês. Bom é não subir.", {"rotulo": "Ver gastos", "href": "/financeiro?escopo=PF#livro-caixa"},
                    seta, _bom(seta, False), {"custo": round(pf["custo"], 2)}, na_nota=False)


def _contas_fixas(ctx, pf):
    g, nome = "Compromissos", "Contas fixas"
    meses = [x for x in (pf["meses"] if pf else []) if x in ctx["validos"]]
    if not ctx["validos"]:
        return _cinza("contas_fixas", nome, g, "Aparece no fim do mês, quando já der para separar fixo de variável.", A_RECORRENTES)
    renda = _soma(ctx, "pf", meses, "entradas")
    if renda <= 0:
        return _sem_pf("contas_fixas", nome, g)
    razao = _soma(ctx, "pf", meses, "fixos") / renda
    f = ctx["faixas"]["contas_fixas"]
    cor = cor_da_faixa(razao, f)
    return marcador("contas_fixas", nome, g, round(razao, 4), _pct(razao), cor, f"Contas fixas levam {_pct(razao)} da renda. Bom é até {_pct(f['verde'])}.",
                    A_RECORRENTES, dados={"razao": razao})


def _moradia(ctx, pf):
    g, nome = "Compromissos", "Moradia"
    if not pf or pf["entradas"] <= 0:
        return _sem_pf("moradia", nome, g)
    casa = _soma(ctx, "pf", pf["meses"], "moradia")
    if casa <= 0:
        return _cinza("moradia", nome, g, "Sem aluguel, luz, água ou internet na PF: lance as contas da casa.", A_RECORRENTES)
    razao = casa / pf["entradas"]
    f = ctx["faixas"]["moradia"]
    cor = cor_da_faixa(razao, f)
    return marcador("moradia", nome, g, round(razao, 4), _pct(razao), cor, f"A casa leva {_pct(razao)} da renda. Bom é até {_pct(f['verde'])}.",
                    A_RECORRENTES, dados={"razao": razao, "mensal": round(casa / pf["n"], 2), "renda": round(pf["renda"], 2)})


def _dividas(ctx, pf):
    g, nome = "Compromissos", "Dívidas e parcelas"
    if not pf or pf["renda"] <= 0:
        return _sem_pf("dividas", nome, g)
    total = round(sum(d["valor"] for d in ctx["dividas"]), 2)
    razao = total / pf["renda"]
    f = ctx["faixas"]["dividas"]
    cor = cor_da_faixa(razao, f)
    frase = (f"Parcelas dos próximos 30 dias: {_pct(razao)} da renda. Bom é até {_pct(f['verde'])}." if total
             else f"Nenhuma parcela nos próximos 30 dias. Bom é até {_pct(f['verde'])} da renda.")
    return marcador("dividas", nome, g, round(razao, 4), _pct(razao), cor, frase, {"rotulo": "Ver contas", "href": "/financeiro#contas"},
                    dados={"total": total, "razao": razao})


def _reserva_pf(ctx, pf):
    g, nome = "Fôlego", "Reserva de emergência"
    if not pf or pf["custo"] <= 0:
        return _sem_pf("reserva_pf", nome, g)
    guardado = ctx["colchao"]["guardado"]
    meses = guardado / pf["custo"]
    f = ctx["faixas"]["reserva_pf"]
    cor = cor_da_faixa(meses, f)
    return marcador("reserva_pf", nome, g, round(meses, 1), f"{_num(meses)} meses", cor,
                    f"Guardado cobre {_num(meses)} mês(es) de vida. Bom é {_num(f['verde'], 0)} meses ou mais.",
                    A_SALDOS if guardado <= 0 else {"rotulo": "Ver reserva", "href": "/financeiro/painel#reserva"},
                    dados={"meses": meses, "guardado": guardado, "custo": round(pf["custo"], 2), "meta_meses": f["verde"]})


def calcular(ctx) -> dict:
    """{"PJ": [{grupo, marcadores}], "PF": [...], "nota": {"PJ": {...}, "PF": {...}}}. Função pura: só lê o contexto."""
    pf = _pf_medias(ctx)
    sobra = _sobra(ctx, pf)
    todos = {
        "faturamento": _faturamento(ctx),
        "margem_contribuicao": _margem(ctx, "margem_contribuicao", "Margem de contribuição", "mc", "Sobra depois dos custos variáveis e do DAS"),
        "margem_lucro": _margem(ctx, "margem_lucro", "Margem de lucro", "ml", "Sobra depois de todos os custos"),
        "margem_liquida": _margem(ctx, "margem_liquida", "Margem líquida", "mliq", "Sobra depois de pagar o seu trabalho"),
        "pe_contabil": _equilibrio(ctx, "pe_contabil", "Equilíbrio contábil", False),
        "pe_economico": _equilibrio(ctx, "pe_economico", "Equilíbrio econômico", True),
        "caixa_pj": _caixa(ctx, "PJ"), "reserva_pj": _reserva_pj(ctx), "vencidas": _vencidas(ctx),
        "saidas": _saidas(ctx), "agenda": _agenda(ctx),
        "renda_pessoa": _renda_pessoa(ctx, pf), "custo_vida": _custo_vida(ctx, pf, sobra), "sobra": sobra,
        "contas_fixas": _contas_fixas(ctx, pf), "moradia": _moradia(ctx, pf), "dividas": _dividas(ctx, pf),
        "reserva_pf": _reserva_pf(ctx, pf), "caixa_pf": _caixa(ctx, "PF"),
    }
    out = {"PJ": [{"grupo": g, "marcadores": [todos[c] for c in cs]} for g, cs in GRUPOS_PJ],
           "PF": [{"grupo": g, "marcadores": [todos[c] for c in cs]} for g, cs in GRUPOS_PF]}
    out["nota"] = {e: nota([x for g in out[e] for x in g["marcadores"]]) for e in ("PJ", "PF")}
    out["todos"] = todos
    return out


def nota(marcadores) -> dict:
    """Nota de 0 a 100 (verde 100, amarelo 50, vermelho 0; cinza e informativos não entram) e o texto 'N de M no verde'."""
    contam = [x for x in marcadores if x["cor"] in PONTOS and x["na_nota"]]
    verdes = sum(1 for x in contam if x["cor"] == "verde")
    pontos = round(sum(PONTOS[x["cor"]] for x in contam) / len(contam)) if contam else None
    return {"nota": pontos, "verdes": verdes, "total": len(contam), "cinzas": sum(1 for x in marcadores if x["cor"] == "cinza"),
            "texto": f"{verdes} de {len(contam)} no verde" if contam else "sem dados ainda",
            "cor": None if pontos is None else ("verde" if pontos >= 75 else ("amarelo" if pontos >= 40 else "vermelho"))}
