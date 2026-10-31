"""Estado do aluno: UM algoritmo olha cada aluno ativo, descobre a situação dele e já traz os botões da solução.

Alertas do Painel, lista de Clientes, ficha, Mensalidades e Assistente leem daqui: nenhuma tela tem regra própria.
Ciclo = o mês entre duas renovações. O analisado é o que fecha na renovação efetiva (ou o último que fechou):
  - pago: pelo que abriu o ciclo em financeiro.renovacoes (pagamento, renovação marcada, mês pulado); antes disso, pagamento na janela do ciclo;
  - sem aula: nenhuma aula 'feita' nele, descontados os dias de bloqueio da agenda e de mês pulado;
  - tratado: já tem crédito daquele mês ou o mês foi pulado: não pergunta de novo.
"""
import datetime as dt
import re

from . import db, financeiro

ORDEM = ("cobrar", "pago_sem_aula", "sem_pagar_sem_aula", "vence_logo", "sem_aula_recente", "cadastro_incompleto", "em_dia")
ROTULO = {"cobrar": "Vencida", "pago_sem_aula": "Pagou sem aula", "sem_pagar_sem_aula": "Sem aula nem pagamento",
          "vence_logo": "Vence logo", "sem_aula_recente": "Sem aula", "cadastro_incompleto": "Cadastro incompleto", "em_dia": "Em dia"}
COR = {"cobrar": "vermelho", "pago_sem_aula": "amarelo", "sem_pagar_sem_aula": "amarelo", "vence_logo": "amarelo",
       "sem_aula_recente": "vermelho", "cadastro_incompleto": "azul", "em_dia": "verde"}
GRAV = {"vermelho": 1, "amarelo": 2, "azul": 3, "verde": 4}
SEM_AULA = ("pago_sem_aula", "sem_pagar_sem_aula", "sem_aula_recente")   # estados em que o aluno que tem aula não está indo
LIMITE_DIAS, LIMITE_HIBRIDA = 14, 35   # dias sem aula (descontados bloqueio e mês pulado) até alertar
DIAS_UTEIS_MIN = 14                    # um ciclo com menos dias úteis que isso (viagem, mês pulado) não vale para julgar "sem aula"
JANELA_DADOS = 120                     # dias de aulas lidos do banco (o ciclo analisado termina até 7 dias à frente)
RE_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _main():
    from . import main   # import tardio: main importa este módulo
    return main


def _como_data(hoje) -> dt.date:
    if hoje is None:
        return dt.date.today()
    return hoje if isinstance(hoje, dt.date) else dt.date.fromisoformat(str(hoje)[:10])


def _mm_aaaa(iso: str) -> str:
    return f"{iso[5:7]}/{iso[:4]}"


def sugerir_credito(valor, feitas, esperadas) -> float:
    """Crédito sugerido pelas aulas não usadas: valor × (1 − feitas ÷ esperadas), entre 0 e o valor, 2 casas. Sem aula feita: o valor inteiro."""
    valor = float(valor or 0)
    if valor <= 0:
        return 0.0
    if not feitas:
        return round(valor, 2)
    if not esperadas or esperadas <= 0:
        return 0.0
    return round(min(max(valor * (1 - feitas / esperadas), 0.0), valor), 2)


# ---------- botões ----------
def acao_pagamento(c, efetiva, valor, credito=0) -> dict:
    """Botão "Registrar pagamento": abre o diálogo único (dlg-pgto) com o valor (mensalidade − crédito) e o mês da renovação já preenchidos."""
    a_pagar = max(float(valor or 0) - float(credito or 0), 0)
    dados = {"titulo": f"Registrar pagamento de {c['nome']}", "cliente_id": c["id"],
             "valor": f"{a_pagar:.2f}".replace(".", ",") if a_pagar else "", "descricao": f"Mensalidade {efetiva[5:7]}/{efetiva[:4]}"}
    if credito:
        dados["nota"] = f"Crédito de {financeiro.moeda_br(credito)} descontado"
    return {"rotulo": "Registrar pagamento", "dialogo": "dlg-pgto", "classe": "verde", "dados": dados}


def acao_agenda(cid) -> dict:
    """Botão "Abrir agenda" já com o aluno no Controle do aluno."""
    return {"rotulo": "Abrir agenda", "href": f"/agenda?aluno={cid}"}


def acao_pulou(c, efetiva) -> dict:
    """Botão "Pulou o mês": confirma num diálogo e a renovação anda um mês, sem cobrança."""
    nova = financeiro.proxima_renovacao(efetiva)
    return {"rotulo": "Pulou o mês", "dialogo": "dlg-pulou", "classe": "claro",
            "dados": {"titulo": f"{c['nome']} pulou o mês? A renovação de {_data_br(efetiva)} vai para {_data_br(nova)}, sem cobrança.",
                      "acao": f"/alunos/{c['id']}/pulou"}}


def acao_credito(c, valor, mes) -> dict:
    """Botão "Crédito na próxima (R$ X)": diálogo com o valor sugerido, editável; vira desconto no próximo pagamento."""
    return {"rotulo": f"Crédito na próxima ({financeiro.moeda_br(valor)})", "dialogo": "dlg-credito", "classe": "claro",
            "dados": {"titulo": f"Crédito para {c['nome']}: não usou {_mm_aaaa(mes + '-01')}", "acao": f"/alunos/{c['id']}/credito",
                      "valor": f"{valor:.2f}".replace(".", ","), "mes": mes}}


def _data_br(iso) -> str:
    return _main().data_br(iso)


# ---------- o algoritmo ----------
def estado(con, hoje=None, ids=None) -> dict[int, dict]:
    """{cliente_id: estado} dos alunos ativos (ou só dos `ids`), em poucas consultas agrupadas. Cada estado:
      tem_aulas, consultoria, renovacao {efetiva, dias, vencida, pendente} | None, pagamento {mes, situacao, previsto, recebido, ultimo_pago},
      uso {ciclo {inicio, fim, mes, feitas, esperadas, uteis} | None, mes_atual, ultima, dias_sem}, credito (a descontar no próximo
      pagamento), credito_total, credito_sugerido, pausado_no_mes,
      situacao (um código de ORDEM), rotulo, texto (frase sem o nome), cor, grav, acoes (botões, no formato dos alertas),
      mais nome, tel, modelo/botao/extra/data_modelo do WhatsApp e ordem (para ordenar)."""
    m = _main()
    hoje = _como_data(hoje)
    h, lim7 = hoje.isoformat(), (hoje + dt.timedelta(days=7)).isoformat()
    if ids is not None:
        ids = sorted({int(i) for i in ids})
        if not ids:
            return {}
    so, args_so = ("", ()) if ids is None or len(ids) > 500 else (f" AND cliente_id IN ({','.join('?' * len(ids))})", tuple(ids))
    alunos = [c for c in con.execute("""SELECT id, nome, telefone, tipo_servico, plano, valor, data_inicio, data_renovacao FROM clientes
                                        WHERE excluido_em IS NULL AND status='ativo' ORDER BY nome""") if ids is None or c["id"] in ids]
    if not alunos:
        return {}
    ren = financeiro.renovacoes(con, ids[0] if ids and len(ids) == 1 else None)
    com_horario = m.alunos_com_horario(con)
    bloqueio = [(i, f) for i, f in ((m.data_iso(a), m.data_iso(b)) for a, b in m.fases_bloqueio(con)) if i and f]
    pausas = m.pausas_por_aluno(con)
    par_cob = db.parametros(con, "cobranca")
    desde = (hoje - dt.timedelta(days=JANELA_DADOS)).isoformat()

    ultima, aulas = {}, {}
    for r in con.execute(f"SELECT cliente_id, MAX(data) FROM cliente_eventos WHERE tipo='aula' AND excluido_em IS NULL{so} GROUP BY cliente_id", args_so):
        ultima[r[0]] = m.data_iso(r[1])
    for r in con.execute(f"SELECT cliente_id, data FROM cliente_eventos WHERE tipo='aula' AND excluido_em IS NULL AND data >= ?{so}", (desde, *args_so)):
        aulas.setdefault(r["cliente_id"], []).append(str(r["data"])[:10])
    pagos, ultimo_pago = {}, {}
    for r in con.execute(f"""SELECT cliente_id, data FROM lancamentos WHERE escopo='PJ' AND tipo='entrada' AND pago_em IS NOT NULL AND excluido_em IS NULL
                             AND cliente_id IS NOT NULL{so}""", args_so):
        d = str(r["data"])[:10]
        pagos.setdefault(r["cliente_id"], []).append(d)
        ultimo_pago[r["cliente_id"]] = max(ultimo_pago.get(r["cliente_id"], ""), d)
    for r in con.execute(f"SELECT cliente_id, data FROM cliente_eventos WHERE tipo='pagamento' AND excluido_em IS NULL{so}", args_so):
        pagos.setdefault(r["cliente_id"], []).append(str(r["data"])[:10])   # o evento antigo 'pagamento' da ficha também vale
    pulos, meses_credito = {}, {}
    for r in con.execute(f"SELECT cliente_id, tipo, data FROM cliente_eventos WHERE tipo IN ('pausa','credito') AND excluido_em IS NULL{so}", args_so):
        if r["tipo"] == "pausa":
            pulos.setdefault(r["cliente_id"], []).append(str(r["data"])[:10])
        else:
            meses_credito.setdefault(r["cliente_id"], set()).add(str(r["data"])[:7])
    livres = financeiro.creditos(con, ids[0] if ids and len(ids) == 1 else None)
    mens = {i["id"]: i for i in financeiro.mensalidades(con, h[:7])}

    out = {}
    for c in alunos:
        cid = c["id"]
        tipo = (c["tipo_servico"] or "").strip()
        tem = m.tem_aulas(c, com_horario)
        valor = float(c["valor"] or 0)
        r = ren.get(cid)
        efetiva = m.data_iso(r["efetiva"]) if r else None
        dias = (dt.date.fromisoformat(efetiva) - hoje).days if efetiva else None
        vencida = bool(efetiva) and efetiva < h
        parados = bloqueio + pausas.get(cid, [])
        ult = ultima.get(cid)
        hibrida = tipo == "Consultoria Híbrida"

        # ---- ciclo analisado: o que fecha na renovação efetiva (ou o último que fechou até 7 dias à frente)
        ciclo, julgar, pagou, sugerido, tratado = None, False, None, None, False
        if efetiva and tem and not vencida:
            i = 0
            while financeiro.proxima_renovacao(efetiva, -i) > lim7 and i < 24:
                i += 1
            fim = financeiro.proxima_renovacao(efetiva, -i)
            ini = financeiro.proxima_renovacao(efetiva, -i - 1)
            janela = min(ini, (dt.date.fromisoformat(fim) - dt.timedelta(days=LIMITE_HIBRIDA)).isoformat()) if hibrida else ini
            di, df = dt.date.fromisoformat(janela), dt.date.fromisoformat(fim)
            total = (df - di).days
            uteis = total - m.dias_parados(di - dt.timedelta(days=1), df - dt.timedelta(days=1), parados)
            feitas = sum(1 for d in aulas.get(cid, []) if janela <= d < fim)
            esperadas = m.aulas_mes(c) * uteis / total if total and m.aulas_mes(c) else 0
            ciclo = {"inicio": ini, "fim": fim, "mes": ini[:7], "feitas": feitas, "esperadas": round(esperadas, 1), "uteis": uteis}
            sugerido = sugerir_credito(valor, feitas, esperadas)
            inicio_aluno = m.data_iso(c["data_inicio"])
            tratado = ini[:7] in meses_credito.get(cid, ()) or any(ini <= d <= (dt.date.fromisoformat(fim) + dt.timedelta(days=7)).isoformat()
                                                                    for d in pulos.get(cid, []))
            pagou = _pago_no_ciclo(r, i, ini, fim, pagos.get(cid, []))
            julgar = (feitas == 0 and uteis >= DIAS_UTEIS_MIN and not tratado and pagou is not None
                      and (inicio_aluno is None or inicio_aluno <= janela))
            if tratado:   # crédito dado ou mês pulado: a ausência desse ciclo já foi resolvida, o relógio do "sem aula" recomeça depois dele
                parados = parados + [(janela, (df - dt.timedelta(days=1)).isoformat())]

        # ---- sem aula recente (a regra de sempre: bloqueio e mês pulado não contam)
        limite = LIMITE_HIBRIDA if hibrida else LIMITE_DIAS
        dias_sem, recente = None, False
        if tem:
            if ult is None:
                ini_aluno = m.data_iso(c["data_inicio"])
                recente = not (ini_aluno and ini_aluno > (hoje - dt.timedelta(days=limite)).isoformat())   # começou agora: ainda não
            else:
                u = dt.date.fromisoformat(ult)
                dias_sem = (hoje - u).days - m.dias_parados(u, hoje, parados)
                recente = dias_sem > limite
        faltas = [t for t, falta in (("telefone", not c["telefone"]), ("renovação", not c["data_renovacao"])) if falta]

        # ---- crédito
        total_livre = round(sum(x["valor"] for x in livres.get(cid, [])), 2)
        credito = financeiro.credito_aplicavel(livres.get(cid, []), valor)[0]

        # ---- a situação: a primeira que vale, na ordem de ORDEM
        if vencida:
            sit = "cobrar"
        elif julgar and pagou:
            sit = "pago_sem_aula"
        elif julgar:
            sit = "sem_pagar_sem_aula"
        elif efetiva and dias <= 7:
            sit = "vence_logo"
        elif recente:
            sit = "sem_aula_recente"
        elif faltas:
            sit = "cadastro_incompleto"
        else:
            sit = "em_dia"

        e = {"id": cid, "nome": c["nome"], "tel": c["telefone"], "valor": valor, "tem_aulas": tem,
             "consultoria": tipo.startswith("Consultoria"),
             "renovacao": {"efetiva": efetiva, "dias": dias, "vencida": vencida, "pendente": bool(r and r["pendente"])} if efetiva else None,
             "pagamento": _pagamento(mens.get(cid), h[:7], ultimo_pago.get(cid)),
             "uso": {"ciclo": ciclo, "mes_atual": sum(1 for d in aulas.get(cid, []) if d[:7] == h[:7]), "ultima": ult, "dias_sem": dias_sem},
             "credito": credito, "credito_total": total_livre, "credito_sugerido": sugerido,
             "pausado_no_mes": any(i <= h and f >= h[:7] + "-01" for i, f in pausas.get(cid, [])),
             "situacao": sit, "rotulo": ROTULO[sit], "cor": COR[sit], "grav": GRAV[COR[sit]], "modelo": None, "botao": None, "extra": None,
             "data_modelo": None, "cobranca": None, "ordem": c["nome"]}
        _texto_e_acoes(e, c, sit, efetiva, ciclo, ult, faltas, par_cob, h, tem and cid not in com_horario)
        out[cid] = e
    return out


def estado_aluno(con, cid, hoje=None) -> dict | None:
    """O estado de um aluno ativo (None se não é ativo ou não existe)."""
    return estado(con, hoje, ids=[cid]).get(cid)


def _pagamento(item, mes, ultimo) -> dict:
    return {"mes": mes, "situacao": item["situacao"] if item else None, "previsto": item["previsto"] if item else 0.0,
            "recebido": item["recebido"] if item else 0.0, "ultimo_pago": ultimo[:7] if ultimo else None}


def _pago_no_ciclo(r, i, ini, fim, datas) -> bool | None:
    """O ciclo [ini, fim) foi pago? True/False; None se foi um mês pulado (não deve nada). i = quantos meses antes da renovação efetiva ele fechou.
    Dentro do que a renovação conhece, vale o que abriu o ciclo; antes disso, um pagamento na janela do ciclo (de 7 dias antes até 7 antes do fim)."""
    j = (r["ciclos"] - 1 - i) if r else -1
    if r and 0 <= j < len(r["tipos"]):
        tipo = r["tipos"][j]
        if tipo == "pausa":
            return None
        return not (tipo == "renovacao" and r["pendente"] and j == r["ciclos"] - 1)
    antes = lambda iso, n: (dt.date.fromisoformat(iso) - dt.timedelta(days=n)).isoformat()   # noqa: E731
    return any(antes(ini, financeiro.ANTECEDENCIA) <= d < antes(fim, financeiro.ANTECEDENCIA) for d in datas)


def _texto_e_acoes(e, c, sit, efetiva, ciclo, ult, faltas, par_cob, h, converter) -> None:
    """Preenche texto e acoes do estado, conforme a situação. converter = tem aula só pelo plano: pode ser consultoria."""
    m = _main()
    cid, valor, credito = c["id"], e["valor"], e["credito"]
    cobre_tudo = credito > 0 and credito >= valor - 0.005   # o crédito paga o mês inteiro: não há o que registrar, só pular
    pagar = acao_pagamento(c, efetiva, valor, credito) if efetiva and not cobre_tudo else None
    pulou = acao_pulou(c, efetiva) if efetiva else None
    wa = {"wa": True}
    nao_tem_aula = {"rotulo": "Não tem aula (consultoria)", "href": f"/clientes?ids={cid}&motivo=sem-aula"}
    extras = [nao_tem_aula] if converter and ult is None else []
    mes_ciclo = _mm_aaaa(ciclo["inicio"]) if ciclo else ""
    if sit == "cobrar":
        cob = financeiro.cobranca(valor, efetiva, h, par_cob)
        e["texto"] = f"renovação venceu em {_data_br(efetiva)}"
        e["modelo"], e["data_modelo"], e["extra"] = ("cobranca" if cob else "renovacao"), _data_br(efetiva), (m.texto_cobranca(cob) if cob else None)
        e["botao"] = f"Cobrar {m.moeda(cob['total'])}" if cob else None
        e["cobranca"] = cob
        e["acoes"] = [pagar, wa, {"rotulo": "Pular mês", "href": f"/clientes/{cid}#renovacao"}] if pagar else [pulou, wa]
    elif sit == "pago_sem_aula":
        e["texto"] = f"pagou e não teve aula em {mes_ciclo}"
        e["acoes"] = [pulou, acao_credito(c, e["credito_sugerido"], ciclo["mes"])] + extras
    elif sit == "sem_pagar_sem_aula":
        e["texto"] = f"sem aula e sem pagamento em {mes_ciclo}: pulou o mês?"
        e["acoes"] = [x for x in (pulou, pagar) if x] + extras
    elif sit == "vence_logo":
        e["texto"] = f"renovação em {_data_br(efetiva)}"
        e["modelo"], e["data_modelo"] = "renovacao", _data_br(efetiva)
        e["acoes"] = [x for x in (pagar or pulou, wa) if x]
    elif sit == "sem_aula_recente":
        e["texto"] = f"sem aula desde {_data_br(ult)}" if ult else "nenhuma aula registrada"
        if ult:
            e["modelo"], e["data_modelo"] = "falta", _data_br(ult)
        e["acoes"] = [acao_agenda(cid)] + ([wa] if ult else []) + extras
    elif sit == "cadastro_incompleto":
        e["texto"] = "cadastro incompleto: falta " + " e ".join(faltas)
        e["acoes"] = [{"rotulo": "Completar cadastro", "href": f"/clientes/{cid}#cadastro"}]
    else:
        e["texto"] = "em dia"
        e["acoes"] = []
    if e["credito"] and sit in ("cobrar", "pago_sem_aula", "sem_pagar_sem_aula", "vence_logo"):
        e["texto"] += f" (crédito de {financeiro.moeda_br(e['credito'])} no próximo pagamento)"
    e["ordem"] = efetiva if sit in ("cobrar", "vence_logo") else c["nome"]


def frase(e) -> str:
    """Frase do alerta: 'Nome — situação'."""
    return f"{e['nome']} — {e['texto']}"


# ---------- soluções: pulou o mês e crédito (rotas, Assistente) ----------
def pular_mes(con, cid, hoje=None) -> tuple[str | None, str | None]:
    """"Pulou o mês": a renovação efetiva anda um mês, sem cobrança (evento 'pausa'). Se um crédito já cobre a mensalidade inteira, ele é usado.
    Devolve (mensagem, erro)."""
    m = _main()
    hoje = _como_data(hoje).isoformat()
    r = financeiro.renovacoes(con, cid).get(cid)
    efetiva = m.data_iso(r["efetiva"]) if r else None
    if not efetiva:
        return None, "Esse aluno não tem data de renovação: complete o cadastro."
    msg, erro = m.registrar_evento(con, cid, "pausa", hoje, "", "", financeiro.proxima_renovacao(efetiva))
    if not erro:
        with con:
            usado = financeiro.usar_credito(con, None, cid, hoje)
        if usado:
            msg += f" O crédito de {financeiro.moeda_br(usado)} cobriu esse mês."
    return msg, erro


def dar_credito(con, cid, valor=None, mes=None, hoje=None) -> tuple[str | None, str | None]:
    """Crédito do mês que o aluno pagou e não usou: vira desconto no próximo pagamento. valor vazio = o sugerido pelas aulas não usadas;
    não passa da mensalidade. mes = AAAA-MM do mês não usado (vazio = o ciclo analisado, senão o mês passado). Devolve (mensagem, erro)."""
    hoje = _como_data(hoje)
    c = con.execute("SELECT nome, valor FROM clientes WHERE id=? AND excluido_em IS NULL", (cid,)).fetchone()
    if not c:
        return None, "Aluno não encontrado."
    e = estado_aluno(con, cid, hoje)
    mes = mes or ((e["uso"]["ciclo"]["mes"] if e and e["uso"]["ciclo"] else None) or financeiro.somar_meses(hoje.isoformat()[:7], -1))
    if not RE_MES.match(mes):
        return None, "Mês inválido."
    if valor in (None, ""):
        valor = e["credito_sugerido"] if e else None
    if not valor or valor <= 0:
        return None, "Informe o valor do crédito (maior que zero)."
    valor, teto = round(float(valor), 2), float(c["valor"] or 0)
    if teto > 0:
        valor = min(valor, teto)
    if con.execute("SELECT 1 FROM cliente_eventos WHERE cliente_id=? AND tipo='credito' AND excluido_em IS NULL AND substr(data,1,7)=?",
                   (cid, mes)).fetchone():
        return None, f"{c['nome']} já tem crédito de {_mm_aaaa(mes + '-01')}: veja o histórico."
    with con:
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, valor, descricao) VALUES (?, 'credito', ?, ?, ?)",
                    (cid, mes + "-01", valor, f"Crédito: não usou {_mm_aaaa(mes + '-01')}"))
    return f"Crédito de {financeiro.moeda_br(valor)} para {c['nome']}: será descontado no próximo pagamento.", None
