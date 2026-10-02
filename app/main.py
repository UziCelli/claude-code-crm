"""VFITCOACH CRM — servidor web (FastAPI). Todas as rotas ficam aqui."""
import csv
import datetime as dt
import io
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, exportar, importar, precos

ROOT = Path(__file__).resolve().parent
DIAS = {1: "Segunda", 2: "Terça", 3: "Quarta", 4: "Quinta", 5: "Sexta", 6: "Sábado", 7: "Domingo"}
DIAS_CURTO = {1: "Seg", 2: "Ter", 3: "Qua", 4: "Qui", 5: "Sex", 6: "Sáb", 7: "Dom"}
ETAPAS = [("lead", "Lead"), ("conversa", "Conversa"), ("avaliacao", "Avaliação marcada"), ("cliente", "Cliente"), ("perdido", "Perdido")]
ROTINA = [("segunda_grade", "Segunda: atualizar a grade"), ("quarta_leads", "Quarta: lançar os leads por canal"),
          ("sexta_propostas", "Sexta: revisar as propostas"), ("fim_mes", "Último dia do mês: fechar o histórico e comparar com as metas")]
HORAS_PICO = [7, 9, 18, 19]
SEMANAS_MES = 4.33


@asynccontextmanager
async def lifespan(app):
    db.iniciar_banco()
    try:
        db.backup_diario()
    except Exception as e:  # o CRM abre mesmo se o backup falhar
        print(f"AVISO: backup diário falhou ({e}). Faça um backup manual em Dados.")
    yield


app = FastAPI(title="VFITCOACH CRM", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


# ---------- filtros de exibição (pt-BR) ----------
def moeda(v):
    if v is None:
        return "—"
    s = f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def data_br(v):
    if not v:
        return "—"
    try:
        return dt.date.fromisoformat(str(v)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(v)


def pct(v, casas=0):
    return "—" if v is None else f"{float(v) * 100:.{casas}f}%".replace(".", ",")


def num(v, casas=1):
    return "—" if v is None else f"{float(v):.{casas}f}".replace(".", ",")


templates.env.filters.update(moeda=moeda, data=data_br, pct=pct, num=num, dia=lambda d: DIAS.get(d, ""),
                             dia_curto=lambda d: DIAS_CURTO.get(d, ""), cor=precos.cor_margem)
templates.env.globals.update(ETAPAS=ETAPAS, DIAS=DIAS, hoje=lambda: dt.date.today().isoformat())


def get_db():
    con = db.conectar()
    try:
        yield con
    finally:
        con.close()


def render(request, nome, con, **ctx):
    ctx.update(request=request, msg=request.query_params.get("msg"), erro=request.query_params.get("erro"),
               listas={k: db.lista(con, k) for k in db.LISTAS_INICIAIS}, alertas=alertas(con))
    return templates.TemplateResponse(request, nome, ctx)


def voltar(url, msg=None, erro=None):
    if msg:
        url += ("&" if "?" in url else "?") + "msg=" + quote(msg)
    if erro:
        url += ("&" if "?" in url else "?") + "erro=" + quote(erro)
    return RedirectResponse(url, status_code=303)


def mes_atual():
    return dt.date.today().strftime("%Y-%m")


def aulas_mes(c) -> float:
    """Sessões por mês estimadas a partir do plano do cliente."""
    plano = (c["plano"] or "")
    m = re.search(r"Pacote (\d+)", plano)
    if m:
        return int(m.group(1))
    m = re.search(r"Mensalidade (\d+)x", plano)
    if m:
        return int(m.group(1)) * SEMANAS_MES
    if c["tipo_servico"] == "Consultoria Híbrida":
        return 1
    return 0


def base_do_cliente(con, c):
    """Linha de precos_base mais parecida com o plano do cliente (para estimar custo e lucro)."""
    qtd = int(aulas_mes(c)) if c["tipo_servico"] == "Pacote de Aulas" else 0
    m = re.search(r"Mensalidade (\d+)x", c["plano"] or "")
    freq = int(m.group(1)) if m else 0
    forma = c["forma_pagamento"] if c["forma_pagamento"] in db.LISTAS_INICIAIS["lista_formas_pagamento"] else "PIX"
    return con.execute(
        """SELECT * FROM precos_base WHERE tipo_servico=? AND local=? AND qtd_aulas=? AND freq_semanal=?
           ORDER BY (forma_pagamento=?) DESC, forma_pagamento LIMIT 1""",
        (c["tipo_servico"], c["local"], qtd, freq, forma)).fetchone()


def dias_parado(con, lead, hoje: str) -> int | None:
    """Dias que um lead ficou parado na etapa. None se ainda não atingiu o limite."""
    limites = db.parametros(con, "lead_parado_dias")
    datas = [d for d in [lead["data_mudanca_etapa"], lead["atualizado_em"][:10]] if d]
    if not datas:
        return None
    ult_toque = max(dt.date.fromisoformat(d) for d in datas).isoformat()
    dias = (dt.date.fromisoformat(hoje) - dt.date.fromisoformat(ult_toque)).days
    limite = limites.get(lead["etapa"])
    return dias if (limite and dias >= limite) else None


# ---------- alertas (topo de todas as telas) ----------
def alertas(con):
    hoje = dt.date.today()
    lim7, lim14 = (hoje + dt.timedelta(days=7)).isoformat(), (hoje - dt.timedelta(days=14)).isoformat()
    renov = con.execute("""SELECT id, nome, data_renovacao FROM clientes WHERE excluido_em IS NULL AND status='ativo'
                           AND data_renovacao IS NOT NULL AND data_renovacao <= ? ORDER BY data_renovacao""", (lim7,)).fetchall()
    sem_aula = con.execute("""SELECT c.id, c.nome, MAX(e.data) AS ultima FROM clientes c
                              LEFT JOIN cliente_eventos e ON e.cliente_id=c.id AND e.tipo='aula' AND e.excluido_em IS NULL
                              WHERE c.excluido_em IS NULL AND c.status='ativo' AND c.tipo_servico != 'Consultoria Online'
                              AND COALESCE(c.data_inicio, substr(c.criado_em,1,10)) < ?
                              GROUP BY c.id HAVING ultima IS NULL OR ultima < ? ORDER BY ultima""", (lim14, lim14)).fetchall()
    acoes = con.execute("""SELECT id, nome, proxima_acao, data_proxima_acao FROM leads WHERE excluido_em IS NULL
                           AND etapa NOT IN ('cliente','perdido') AND data_proxima_acao <= ? ORDER BY data_proxima_acao""",
                        (hoje.isoformat(),)).fetchall()
    return {"renovacao": renov, "sem_aula": sem_aula, "acoes": acoes}


# =====================================================================
# 6. PAINEL (tela inicial)
# =====================================================================
def calcular_metricas(con, mes=None):
    mes = mes or mes_atual()
    p = precos.carregar_parametros(con)
    metas = db.parametros(con, "metas")
    clientes = con.execute("SELECT * FROM clientes WHERE excluido_em IS NULL AND status='ativo'").fetchall()
    horas = lucro_total = 0.0
    receita = receita_grupos = 0.0
    for c in clientes:
        h = aulas_mes(c)
        horas += h
        receita += c["valor"] or 0
        if (c["pessoas"] or 1) > 1:
            receita_grupos += c["valor"] or 0
        base = base_do_cliente(con, c)
        if base and c["valor"]:
            forma = c["forma_pagamento"] if c["forma_pagamento"] in p["taxas"] else "PIX"
            taxa = p["das"] + p["taxas"][forma]
            lucro_total += c["valor"] * (1 - taxa) - base["custo_total"]
    perdidos = con.execute("""SELECT COUNT(*) FROM cliente_eventos WHERE tipo='status' AND descricao LIKE '%inativo%'
                              AND substr(data,1,7)=?""", (mes,)).fetchone()[0]
    abaixo10 = con.execute("""SELECT COUNT(*) FROM propostas WHERE excluido_em IS NULL AND status='aceita'
                              AND margem < 0.10 AND substr(data,1,7)=?""", (mes,)).fetchone()[0]
    espera_pico = con.execute("SELECT COUNT(*) FROM lista_espera WHERE excluido_em IS NULL AND hora IN (7,9,18,19)").fetchone()[0]
    lucro_hora = lucro_total / horas if horas else 0
    nivel = 1
    if lucro_hora >= metas["lucro_hora_dez26"] and horas >= metas["horas_dez26"]:
        nivel = 2
    if nivel == 2 and horas >= metas["horas_mar27"] and espera_pico > 0:
        nivel = 3
    if nivel == 3 and metas.get("preco_base_reajuste", 0) > 0:
        nivel = 4
    return dict(mes=mes, clientes_ativos=len(clientes), horas_ocupadas=round(horas, 1), lucro_hora=round(lucro_hora, 2),
                pct_receita_grupos=(receita_grupos / receita) if receita else 0, faturamento_recorrente=round(receita, 2),
                clientes_perdidos=perdidos, vendas_abaixo_10=abaixo10, nivel=nivel, espera_pico=espera_pico)


def metricas_por_canal(con, mes):
    metas = db.parametros(con, "metas")
    out = []
    ltv_meses = metas.get("ltv_meses", 6)
    for canal in db.lista(con, "lista_canais"):
        ids = [r[0] for r in con.execute("SELECT id FROM leads WHERE excluido_em IS NULL AND canal_origem=?", (canal,))]

        def chegou(etapa):
            if not ids:
                return 0
            q = ",".join("?" * len(ids))
            return con.execute(f"SELECT COUNT(DISTINCT lead_id) FROM lead_etapas_log WHERE etapa=? AND lead_id IN ({q})",
                               (etapa, *ids)).fetchone()[0]
        n_conv, n_aval, n_cli = chegou("conversa"), chegou("avaliacao"), chegou("cliente")
        gasto = con.execute("""SELECT COALESCE(SUM(mensalidade+anuncios+comissoes+outros),0), COALESCE(SUM(leads),0),
                               COALESCE(SUM(clientes),0) FROM gastos_marketing WHERE excluido_em IS NULL AND canal=? AND mes=?""",
                            (canal, mes)).fetchone()
        clientes_canal = con.execute("""SELECT COUNT(*), COALESCE(AVG(valor),0) FROM clientes WHERE excluido_em IS NULL
                                        AND canal_origem=? AND substr(COALESCE(data_inicio, criado_em),1,7)=?""", (canal, mes)).fetchone()
        n_leads = len(ids) or gasto[1]
        n_clientes = n_cli or gasto[2] or clientes_canal[0]
        if not (ids or gasto[0] or n_clientes):
            continue
        cpl = gasto[0] / n_leads if n_leads else None
        cac = gasto[0] / n_clientes if n_clientes else None
        ltv = clientes_canal[1] * ltv_meses if clientes_canal[1] else None
        out.append(dict(canal=canal, leads=n_leads, conversa=n_conv, avaliacao=n_aval, clientes=n_clientes, gasto=gasto[0],
                        tx_conversa=(n_conv / len(ids)) if ids else None, tx_avaliacao=(n_aval / n_conv) if n_conv else None,
                        tx_fechamento=(n_cli / n_aval) if n_aval else None, cpl=cpl, cac=cac,
                        ltv_cac=(ltv / cac) if (ltv and cac) else None))
    return out


@app.get("/", response_class=HTMLResponse)
def painel(request: Request, con=Depends(get_db)):
    m = calcular_metricas(con)
    metas = db.parametros(con, "metas")
    historico = [dict(r) for r in con.execute("SELECT * FROM metricas_mensais ORDER BY mes")]
    historico = [h for h in historico if h["mes"] != m["mes"]] + [m]
    return render(request, "painel.html", con, m=m, metas=metas, canais=metricas_por_canal(con, m["mes"]),
                  historico=historico[-12:], fases=fase_atual(con))


@app.post("/painel/fechar-mes")
def fechar_mes(con=Depends(get_db)):
    m = calcular_metricas(con)
    with con:
        con.execute("""INSERT INTO metricas_mensais (mes, clientes_ativos, horas_ocupadas, lucro_hora, pct_receita_grupos,
                       faturamento_recorrente, clientes_perdidos, vendas_abaixo_10, nivel) VALUES
                       (:mes,:clientes_ativos,:horas_ocupadas,:lucro_hora,:pct_receita_grupos,:faturamento_recorrente,
                       :clientes_perdidos,:vendas_abaixo_10,:nivel) ON CONFLICT(mes) DO UPDATE SET
                       clientes_ativos=excluded.clientes_ativos, horas_ocupadas=excluded.horas_ocupadas,
                       lucro_hora=excluded.lucro_hora, pct_receita_grupos=excluded.pct_receita_grupos,
                       faturamento_recorrente=excluded.faturamento_recorrente, clientes_perdidos=excluded.clientes_perdidos,
                       vendas_abaixo_10=excluded.vendas_abaixo_10, nivel=excluded.nivel, fechado_em=datetime('now','localtime')""", m)
        con.execute("INSERT OR IGNORE INTO rotina_itens (semana, item) VALUES (?, 'fim_mes')", (semana_atual(),))
        con.execute("UPDATE rotina_itens SET feito=1, data_feito=date('now','localtime') WHERE semana=? AND item='fim_mes'", (semana_atual(),))
    return voltar("/", msg=f"Mês {m['mes'][5:]}/{m['mes'][:4]} fechado e guardado no histórico.")


# =====================================================================
# 1. CLIENTES
# =====================================================================
CAMPOS_CLIENTE = ["nome", "telefone", "local", "tipo_servico", "plano", "pessoas", "dias_horarios", "valor",
                  "forma_pagamento", "status", "canal_origem", "data_inicio", "data_renovacao", "observacoes"]


def _num_br(v) -> float:
    s = str(v or "0").strip().replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s or 0)


@app.get("/clientes", response_class=HTMLResponse)
def clientes(request: Request, status: str = "ativo", busca: str = "", con=Depends(get_db)):
    sql = "SELECT * FROM clientes WHERE excluido_em IS NULL"
    args = []
    if status != "todos":
        sql += " AND status=?"
        args.append(status)
    if busca:
        sql += " AND nome LIKE ?"
        args.append(f"%{busca}%")
    rows = con.execute(sql + " ORDER BY status='ativo' DESC, nome", args).fetchall()
    hoje = dt.date.today()
    itens = []
    for c in rows:
        alerta = None
        if c["data_renovacao"] and c["status"] == "ativo":
            dias = (dt.date.fromisoformat(c["data_renovacao"]) - hoje).days
            alerta = "vermelho" if dias < 0 else ("amarelo" if dias <= 7 else None)
        itens.append({**dict(c), "alerta": alerta})
    totais = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM clientes WHERE excluido_em IS NULL GROUP BY status")}
    return render(request, "clientes.html", con, clientes=itens, status=status, busca=busca, totais=totais)


def _form_cliente(form) -> dict:
    d = {k: (form.get(k) or None) for k in CAMPOS_CLIENTE}
    d["pessoas"] = int(d["pessoas"] or 1)
    d["valor"] = _num_br(d["valor"])
    d["status"] = d["status"] or "ativo"
    return d


@app.get("/clientes/novo", response_class=HTMLResponse)
def cliente_novo(request: Request, con=Depends(get_db)):
    return render(request, "cliente.html", con, c=None, eventos=[], estimativa=None, propostas=[])


@app.post("/clientes")
async def cliente_criar(request: Request, con=Depends(get_db)):
    d = _form_cliente(await request.form())
    if not d["nome"]:
        return voltar("/clientes/novo", erro="Informe o nome.")
    with con:
        cur = con.execute(f"INSERT INTO clientes ({','.join(CAMPOS_CLIENTE)}) VALUES ({','.join(':' + k for k in CAMPOS_CLIENTE)})", d)
    return voltar(f"/clientes/{cur.lastrowid}", msg="Cliente cadastrado.")


@app.get("/clientes/{cid}", response_class=HTMLResponse)
def cliente_ficha(request: Request, cid: int, con=Depends(get_db)):
    c = con.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone()
    if not c:
        return voltar("/clientes", erro="Cliente não encontrado.")
    eventos = con.execute("SELECT * FROM cliente_eventos WHERE cliente_id=? AND excluido_em IS NULL ORDER BY data DESC, id DESC", (cid,)).fetchall()
    estimativa = None
    base = base_do_cliente(con, c)
    if base and c["valor"]:
        p = precos.carregar_parametros(con)
        forma = c["forma_pagamento"] if c["forma_pagamento"] in p["taxas"] else "PIX"
        try:
            estimativa = precos.calcular({**dict(base), "preco_base": c["valor"]}, p, pessoas=c["pessoas"] or 1, forma_pagamento=forma)
        except ValueError:
            estimativa = None
    propostas = con.execute("SELECT * FROM propostas WHERE cliente_id=? AND excluido_em IS NULL ORDER BY id DESC", (cid,)).fetchall()
    return render(request, "cliente.html", con, c=c, eventos=eventos, estimativa=estimativa, propostas=propostas)


@app.post("/clientes/{cid}")
async def cliente_salvar(request: Request, cid: int, con=Depends(get_db)):
    d = _form_cliente(await request.form())
    d["id"] = cid
    antigo = con.execute("SELECT status FROM clientes WHERE id=?", (cid,)).fetchone()
    with con:
        con.execute(f"UPDATE clientes SET {','.join(k + '=:' + k for k in CAMPOS_CLIENTE)}, atualizado_em=datetime('now','localtime') WHERE id=:id", d)
        if antigo and antigo["status"] != d["status"]:
            con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'status', date('now','localtime'), ?)",
                        (cid, f"Status alterado para {d['status']}"))
    return voltar(f"/clientes/{cid}", msg="Salvo.")


@app.post("/clientes/{cid}/status")
def cliente_status(cid: int, status: str = Form(...), con=Depends(get_db)):
    with con:
        con.execute("UPDATE clientes SET status=?, atualizado_em=datetime('now','localtime') WHERE id=?", (status, cid))
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao) VALUES (?, 'status', date('now','localtime'), ?)",
                    (cid, f"Status alterado para {status}"))
    return voltar(f"/clientes/{cid}", msg=f"Status: {status}.")


@app.post("/clientes/{cid}/evento")
def cliente_evento(cid: int, tipo: str = Form(...), data: str = Form(...), valor: str = Form(""), descricao: str = Form(""),
                   nova_renovacao: str = Form(""), con=Depends(get_db)):
    v = _num_br(valor) if valor else None
    with con:
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, valor, descricao) VALUES (?,?,?,?,?)", (cid, tipo, data, v, descricao or None))
        if tipo == "renovacao" and nova_renovacao:
            con.execute("UPDATE clientes SET data_renovacao=?, status='ativo' WHERE id=?", (nova_renovacao, cid))
    return voltar(f"/clientes/{cid}", msg="Registrado.")


@app.post("/clientes/{cid}/excluir")
def cliente_excluir(cid: int, con=Depends(get_db)):
    with con:
        con.execute("UPDATE clientes SET excluido_em=datetime('now','localtime') WHERE id=?", (cid,))
    return voltar("/clientes", msg="Cliente enviado para a lixeira (restaurável em Dados).")


# =====================================================================
# 2. LEADS (kanban)
# =====================================================================
@app.get("/leads", response_class=HTMLResponse)
def leads(request: Request, con=Depends(get_db)):
    rows = con.execute("SELECT * FROM leads WHERE excluido_em IS NULL ORDER BY data_proxima_acao IS NULL, data_proxima_acao, id DESC").fetchall()
    colunas = {e: [] for e, _ in ETAPAS}
    hoje = dt.date.today().isoformat()
    for l in rows:
        atrasado = bool(l["data_proxima_acao"] and l["data_proxima_acao"] < hoje and l["etapa"] not in ("cliente", "perdido"))
        parado = dias_parado(con, l, hoje)
        colunas[l["etapa"]].append({**dict(l), "atrasado": atrasado, "dias": parado, "parado": bool(parado)})
    return render(request, "leads.html", con, colunas=colunas, destaque=request.query_params.get("destaque"))


@app.post("/leads")
def lead_criar(nome: str = Form(...), telefone: str = Form(""), canal_origem: str = Form(...), interesse: str = Form(""),
               proxima_acao: str = Form(""), data_proxima_acao: str = Form(""), observacoes: str = Form(""), con=Depends(get_db)):
    with con:
        cur = con.execute("""INSERT INTO leads (nome, telefone, canal_origem, interesse, proxima_acao, data_proxima_acao, observacoes)
                             VALUES (?,?,?,?,?,?,?)""", (nome, telefone or None, canal_origem, interesse or None, proxima_acao or None,
                                                         data_proxima_acao or None, observacoes or None))
        con.execute("INSERT INTO lead_etapas_log (lead_id, etapa) VALUES (?, 'lead')", (cur.lastrowid,))
    return voltar("/leads", msg="Lead adicionado.")


@app.post("/leads/{lid}")
def lead_salvar(lid: int, nome: str = Form(...), telefone: str = Form(""), canal_origem: str = Form(...), interesse: str = Form(""),
                proxima_acao: str = Form(""), data_proxima_acao: str = Form(""), observacoes: str = Form(""), con=Depends(get_db)):
    with con:
        con.execute("""UPDATE leads SET nome=?, telefone=?, canal_origem=?, interesse=?, proxima_acao=?, data_proxima_acao=?,
                       observacoes=?, atualizado_em=datetime('now','localtime') WHERE id=?""",
                    (nome, telefone or None, canal_origem, interesse or None, proxima_acao or None, data_proxima_acao or None,
                     observacoes or None, lid))
    return voltar("/leads", msg="Lead salvo.")


@app.post("/leads/{lid}/etapa")
def lead_etapa(lid: int, etapa: str = Form(...), motivo_perda: str = Form(""), con=Depends(get_db)):
    l = con.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
    if not l or etapa not in dict(ETAPAS):
        return voltar("/leads", erro="Etapa inválida.")
    with con:
        con.execute("UPDATE leads SET etapa=?, motivo_perda=?, data_mudanca_etapa=date('now','localtime') WHERE id=?",
                    (etapa, (motivo_perda or None) if etapa == "perdido" else None, lid))
        con.execute("INSERT INTO lead_etapas_log (lead_id, etapa) VALUES (?, ?)", (lid, etapa))
        if etapa == "cliente" and not l["cliente_id"]:
            partes = (l["interesse"] or "").split("/")
            cur = con.execute("""INSERT INTO clientes (nome, telefone, canal_origem, observacoes, lead_id, tipo_servico, local, data_inicio)
                                 VALUES (?,?,?,?,?,?,?,date('now','localtime'))""",
                              (l["nome"], l["telefone"], l["canal_origem"], l["observacoes"], lid,
                               partes[0].strip() or None, partes[1].strip() if len(partes) > 1 else None))
            con.execute("UPDATE leads SET cliente_id=? WHERE id=?", (cur.lastrowid, lid))
            return voltar(f"/leads?destaque={lid}", msg=f"Novo aluno: {l['nome']}")
    return voltar(f"/leads?destaque={lid}", msg="Etapa atualizada.")


@app.post("/leads/{lid}/excluir")
def lead_excluir(lid: int, con=Depends(get_db)):
    with con:
        con.execute("UPDATE leads SET excluido_em=datetime('now','localtime') WHERE id=?", (lid,))
    return voltar("/leads", msg="Lead enviado para a lixeira.")


# =====================================================================
# 3. GRADE DE HORÁRIOS
# =====================================================================
def plano_referencia(con, tipo_calculo, local):
    if tipo_calculo == "Mensalidades":
        return con.execute("SELECT * FROM precos_base WHERE tipo_servico='Mensalidade' AND local=? AND forma_pagamento='PIX' ORDER BY abs(freq_semanal-2) LIMIT 1", (local,)).fetchone()
    return con.execute("SELECT * FROM precos_base WHERE tipo_servico='Pacote de Aulas' AND local=? AND forma_pagamento='PIX' ORDER BY abs(qtd_aulas-8) LIMIT 1", (local,)).fetchone()


@app.get("/grade", response_class=HTMLResponse)
def grade(request: Request, tipo: str = "Pacotes", local: str = "CIA", vale: int = 0, con=Depends(get_db)):
    slots = con.execute("SELECT * FROM grade_slots WHERE tipo_calculo=? AND local=? AND dia BETWEEN 1 AND 6", (tipo, local)).fetchall()
    p = precos.carregar_parametros(con)
    base = plano_referencia(con, tipo, local)
    celulas = {}
    for s in slots:
        cel = dict(s)
        cel["preco_aula"] = cel["margem"] = None
        cel["apagado"] = False
        if s["status"] == "livre" and base:
            r = precos.calcular(dict(base), p, mult_horario=s["multiplicador"] or 1)
            cel["preco_aula"] = r["preco_total"] / (base["sessoes_mes"] or 1)
            cel["margem"] = r["margem"]
        if vale and not (s["status"] == "livre" and (s["multiplicador"] or 1) < 1):
            cel["apagado"] = True
        celulas[(s["dia"], s["hora"])] = cel
    locais = [r[0] for r in con.execute("SELECT DISTINCT local FROM grade_slots ORDER BY local")] or db.lista(con, "lista_locais")
    clientes_ = con.execute("SELECT id, nome FROM clientes WHERE excluido_em IS NULL AND status='ativo' ORDER BY nome").fetchall()
    resumo = {"livres": sum(1 for c in celulas.values() if c["status"] == "livre"),
              "ocupados": sum(1 for c in celulas.values() if c["status"] == "ocupado"),
              "vale": sum(1 for c in celulas.values() if c["status"] == "livre" and (c["multiplicador"] or 1) < 1)}
    return render(request, "grade.html", con, celulas=celulas, tipo=tipo, local=local, vale=vale, locais=locais,
                  horas=range(5, 24), clientes=clientes_, base=base, resumo=resumo)


@app.post("/grade/slot")
def grade_slot(tipo: str = Form(...), local: str = Form(...), dia: int = Form(...), hora: int = Form(...), status: str = Form(...),
               cliente_id: str = Form(""), multiplicador: str = Form("1"), so_este: int = Form(0), con=Depends(get_db)):
    cid = int(cliente_id) if cliente_id else None
    nome = con.execute("SELECT nome FROM clientes WHERE id=?", (cid,)).fetchone()["nome"] if cid else None
    mult = _num_br(multiplicador) or 1.0
    tipos = [tipo] if so_este else ["Pacotes", "Mensalidades"]
    with con:
        for t in tipos:
            con.execute("""INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, cliente_id, cliente_nome, multiplicador)
                           VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(tipo_calculo, dia, local, hora) DO UPDATE SET
                           status=excluded.status, cliente_id=excluded.cliente_id, cliente_nome=excluded.cliente_nome,
                           multiplicador=excluded.multiplicador""",
                        (t, dia, local, hora, status, cid if status == "ocupado" else None, nome if status == "ocupado" else None, mult))
    return voltar(f"/grade?tipo={tipo}&local={local}", msg=f"{DIAS_CURTO[dia]} {hora:02d}h atualizado.")


# =====================================================================
# 4. SIMULADOR / PROPOSTAS / EXPLORADOR
# =====================================================================
def opcoes_plano(con):
    rows = con.execute("SELECT DISTINCT tipo_servico, qtd_aulas, freq_semanal FROM precos_base ORDER BY tipo_servico, qtd_aulas, freq_semanal").fetchall()
    out = []
    for r in rows:
        if r["tipo_servico"] == "Pacote de Aulas":
            rotulo = f"Pacote de {r['qtd_aulas']} aulas"
        elif r["tipo_servico"] == "Mensalidade":
            rotulo = f"Mensalidade {r['freq_semanal']}x por semana"
        else:
            rotulo = r["tipo_servico"]
        out.append({"valor": f"{r['tipo_servico']}|{r['qtd_aulas']}|{r['freq_semanal']}", "rotulo": rotulo})
    return out


def simular(con, plano, local, forma, pessoas, dia, hora, desconto):
    tipo, qtd, freq = plano.split("|")
    base = con.execute("""SELECT * FROM precos_base WHERE tipo_servico=? AND qtd_aulas=? AND freq_semanal=? AND local=?
                          ORDER BY (forma_pagamento=?) DESC LIMIT 1""", (tipo, int(qtd), int(freq), local, forma)).fetchone()
    if not base:
        raise ValueError(f"Não há preço base para {tipo} em {local}. Importe a planilha ou cadastre em Configurações.")
    mult = 1.0
    if dia and hora:
        tc = "Mensalidades" if tipo == "Mensalidade" else "Pacotes"
        s = con.execute("SELECT multiplicador FROM grade_slots WHERE tipo_calculo=? AND local=? AND dia=? AND hora=?", (tc, local, dia, hora)).fetchone()
        mult = (s["multiplicador"] or 1.0) if s else 1.0
    p = precos.carregar_parametros(con)
    r = precos.calcular(dict(base), p, pessoas=pessoas, mult_horario=mult, desconto=desconto / 100, forma_pagamento=forma, local=local)
    r.update(base=dict(base), mult=mult, tipo=tipo, qtd=int(qtd), freq=int(freq))
    return r


@app.get("/simulador", response_class=HTMLResponse)
def simulador(request: Request, plano: str = "", local: str = "CIA", forma: str = "PIX", pessoas: int = 1, dia: int = 0,
              hora: int = 0, desconto: float = 0, lead_id: int = 0, cliente_id: int = 0, con=Depends(get_db)):
    resultado = erro = None
    if plano:
        try:
            resultado = simular(con, plano, local, forma, pessoas, dia, hora, desconto)
        except ValueError as e:
            erro = str(e)
    leads_ = con.execute("SELECT id, nome FROM leads WHERE excluido_em IS NULL AND etapa NOT IN ('cliente','perdido') ORDER BY nome").fetchall()
    clientes_ = con.execute("SELECT id, nome FROM clientes WHERE excluido_em IS NULL ORDER BY nome").fetchall()
    propostas = con.execute("""SELECT p.*, l.nome AS lead_nome, c.nome AS cliente_nome FROM propostas p
                               LEFT JOIN leads l ON l.id=p.lead_id LEFT JOIN clientes c ON c.id=p.cliente_id
                               WHERE p.excluido_em IS NULL ORDER BY p.id DESC LIMIT 30""").fetchall()
    return render(request, "simulador.html", con, planos=opcoes_plano(con), f=dict(plano=plano, local=local, forma=forma, pessoas=pessoas,
                  dia=dia, hora=hora, desconto=desconto, lead_id=lead_id, cliente_id=cliente_id), r=resultado, erro_sim=erro,
                  leads=leads_, clientes=clientes_, propostas=propostas, horas=range(5, 24))


@app.post("/propostas")
def proposta_salvar(plano: str = Form(...), local: str = Form(...), forma: str = Form(...), pessoas: int = Form(1), dia: int = Form(0),
                    hora: int = Form(0), desconto: float = Form(0), lead_id: str = Form(""), cliente_id: str = Form(""),
                    observacoes: str = Form(""), confirmar: int = Form(0), con=Depends(get_db)):
    url = f"/simulador?plano={quote(plano)}&local={local}&forma={quote(forma)}&pessoas={pessoas}&dia={dia}&hora={hora}&desconto={desconto}"
    try:
        r = simular(con, plano, local, forma, pessoas, dia, hora, desconto)
    except ValueError as e:
        return voltar(url, erro=str(e))
    if r["abaixo_margem"] and not confirmar:
        return voltar(url, erro="Proposta abaixo da margem mínima. Marque 'Salvar mesmo assim' para confirmar.")
    if not lead_id and not cliente_id:
        return voltar(url, erro="Vincule a proposta a um lead ou cliente.")
    with con:
        cur = con.execute("""INSERT INTO propostas (lead_id, cliente_id, tipo_servico, qtd_aulas, freq_semanal, local, forma_pagamento, pessoas,
                             dia, hora, desconto, preco_total, preco_pessoa, custo_total, lucro, margem, lucro_hora, preco_minimo,
                             desconto_maximo, abaixo_margem, observacoes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (int(lead_id) if lead_id else None, int(cliente_id) if cliente_id else None, r["tipo"], r["qtd"], r["freq"],
                           local, forma, pessoas, dia or None, hora or None, desconto / 100, r["preco_total"], r["preco_pessoa"],
                           r["custo_total"], r["lucro"], r["margem"], r["lucro_hora"], r["preco_minimo"], r["desconto_maximo"],
                           int(r["abaixo_margem"]), observacoes or None))
    return voltar("/simulador", msg=f"Proposta #{cur.lastrowid} salva.")


@app.post("/propostas/{pid}/status")
def proposta_status(pid: int, status: str = Form(...), con=Depends(get_db)):
    with con:
        con.execute("UPDATE propostas SET status=? WHERE id=?", (status, pid))
    return voltar("/simulador", msg=f"Proposta #{pid}: {status}.")


@app.post("/propostas/{pid}/excluir")
def proposta_excluir(pid: int, con=Depends(get_db)):
    with con:
        con.execute("UPDATE propostas SET excluido_em=datetime('now','localtime') WHERE id=?", (pid,))
    return voltar("/simulador", msg="Proposta enviada para a lixeira.")


@app.get("/explorador", response_class=HTMLResponse)
def explorador(request: Request, local: str = "CIA", tipo_servico: str = "", forma: str = "PIX", pessoas: int = 1, dia: int = 0,
               ordem: str = "lucro_hora", so_vale: int = 0, con=Depends(get_db)):
    p = precos.carregar_parametros(con)
    sql = "SELECT * FROM precos_base WHERE local=? AND forma_pagamento=?"
    args = [local, forma]
    if tipo_servico:
        sql += " AND tipo_servico=?"
        args.append(tipo_servico)
    bases = con.execute(sql, args).fetchall()
    slots = con.execute("SELECT * FROM grade_slots WHERE local=? AND status='livre' AND dia BETWEEN 1 AND 6" + (" AND dia=?" if dia else ""),
                        (local, dia) if dia else (local,)).fetchall()
    linhas = []
    for b in bases:
        tc = "Mensalidades" if b["tipo_servico"] == "Mensalidade" else "Pacotes"
        presencial = b["tipo_servico"] in ("Pacote de Aulas", "Mensalidade", "Aula avulsa")
        candidatos = [s for s in slots if s["tipo_calculo"] == tc] if presencial else [None]
        for s in candidatos:
            mult = (s["multiplicador"] or 1) if s else 1
            if so_vale and mult >= 1:
                continue
            try:
                r = precos.calcular(dict(b), p, pessoas=pessoas, mult_horario=mult, forma_pagamento=forma, local=local)
            except ValueError:
                continue
            linhas.append({**r, "tipo_servico": b["tipo_servico"], "qtd_aulas": b["qtd_aulas"], "freq_semanal": b["freq_semanal"],
                           "dia": s["dia"] if s else None, "hora": s["hora"] if s else None, "mult": mult})
    linhas.sort(key=lambda x: x.get(ordem) or 0, reverse=ordem != "preco_total")
    tipos = [r[0] for r in con.execute("SELECT DISTINCT tipo_servico FROM precos_base ORDER BY 1")]
    return render(request, "explorador.html", con, linhas=linhas[:400], total=len(linhas), tipos=tipos,
                  f=dict(local=local, tipo_servico=tipo_servico, forma=forma, pessoas=pessoas, dia=dia, ordem=ordem, so_vale=so_vale))


# =====================================================================
# 5. CAMPANHAS
# =====================================================================
def fase_atual(con):
    hoje = dt.date.today().isoformat()
    return con.execute("SELECT * FROM campanha_fases WHERE inicio<=? AND fim>=? ORDER BY ordem", (hoje, hoje)).fetchall()


@app.get("/campanhas", response_class=HTMLResponse)
def campanhas(request: Request, mes: str = "", con=Depends(get_db)):
    mes = mes or mes_atual()
    fases = [dict(f) for f in con.execute("SELECT * FROM campanha_fases ORDER BY ordem")]
    hoje = dt.date.today().isoformat()
    for f in fases:
        f["itens"] = con.execute("SELECT * FROM campanha_itens WHERE fase_id=? AND excluido_em IS NULL ORDER BY ordem, id", (f["id"],)).fetchall()
        f["situacao"] = "atual" if f["inicio"] <= hoje <= f["fim"] else ("passada" if f["fim"] < hoje else "futura")
        f["feitos"] = sum(1 for i in f["itens"] if i["feito"])
    checkpoints = []
    for c in con.execute("SELECT * FROM campanha_checkpoints ORDER BY prazo"):
        n = con.execute("SELECT COUNT(*) FROM clientes WHERE excluido_em IS NULL AND canal_origem=? AND COALESCE(data_inicio, substr(criado_em,1,10)) <= ?",
                        (c["canal"], c["prazo"])).fetchone()[0]
        auto = "sim" if n > 0 else ("nao" if hoje > c["prazo"] else "pendente")
        checkpoints.append({**dict(c), "clientes": n, "auto": auto})
    gastos = con.execute("SELECT * FROM gastos_marketing WHERE excluido_em IS NULL AND mes=? ORDER BY canal", (mes,)).fetchall()
    meses = [r[0] for r in con.execute("SELECT DISTINCT mes FROM gastos_marketing WHERE excluido_em IS NULL ORDER BY mes DESC")]
    if mes not in meses:
        meses.insert(0, mes)
    return render(request, "campanhas.html", con, fases=fases, checkpoints=checkpoints, gastos=gastos, mes=mes, meses=meses)


@app.post("/campanhas/item")
def campanha_item(fase_id: int = Form(...), texto: str = Form(...), con=Depends(get_db)):
    with con:
        con.execute("INSERT INTO campanha_itens (fase_id, texto, ordem) VALUES (?,?, (SELECT COALESCE(MAX(ordem),0)+1 FROM campanha_itens WHERE fase_id=?))",
                    (fase_id, texto, fase_id))
    return voltar("/campanhas")


@app.post("/campanhas/item/{iid}/toggle")
def campanha_item_toggle(iid: int, con=Depends(get_db)):
    with con:
        con.execute("UPDATE campanha_itens SET feito = 1-feito, data_feito = CASE WHEN feito=0 THEN date('now','localtime') ELSE NULL END WHERE id=?", (iid,))
    return voltar("/campanhas")


@app.post("/campanhas/item/{iid}/excluir")
def campanha_item_excluir(iid: int, con=Depends(get_db)):
    with con:
        con.execute("UPDATE campanha_itens SET excluido_em=datetime('now','localtime') WHERE id=?", (iid,))
    return voltar("/campanhas")


@app.post("/campanhas/gasto")
def campanha_gasto(mes: str = Form(...), canal: str = Form(...), mensalidade: float = Form(0), anuncios: float = Form(0),
                   comissoes: float = Form(0), outros: float = Form(0), leads: int = Form(0), agendamentos: int = Form(0),
                   clientes: int = Form(0), observacao: str = Form(""), con=Depends(get_db)):
    with con:
        con.execute("""INSERT INTO gastos_marketing (mes, canal, mensalidade, anuncios, comissoes, outros, leads, agendamentos, clientes, observacao)
                       VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(mes, canal) DO UPDATE SET mensalidade=excluded.mensalidade,
                       anuncios=excluded.anuncios, comissoes=excluded.comissoes, outros=excluded.outros, leads=excluded.leads,
                       agendamentos=excluded.agendamentos, clientes=excluded.clientes, observacao=excluded.observacao, excluido_em=NULL""",
                    (mes, canal, mensalidade, anuncios, comissoes, outros, leads, agendamentos, clientes, observacao or None))
    return voltar(f"/campanhas?mes={mes}", msg="Gasto salvo.")


@app.post("/campanhas/gasto/{gid}/excluir")
def campanha_gasto_excluir(gid: int, con=Depends(get_db)):
    with con:
        con.execute("UPDATE gastos_marketing SET excluido_em=datetime('now','localtime') WHERE id=?", (gid,))
    return voltar("/campanhas")


@app.post("/campanhas/checkpoint/{cid}")
def campanha_checkpoint(cid: int, resposta: str = Form(...), con=Depends(get_db)):
    with con:
        con.execute("UPDATE campanha_checkpoints SET resposta=? WHERE id=?", (resposta, cid))
    return voltar("/campanhas")


# =====================================================================
# 7. ROTINA SEMANAL + LISTA DE ESPERA
# =====================================================================
def semana_atual():
    y, w, _ = dt.date.today().isocalendar()
    return f"{y}-W{w:02d}"


@app.get("/rotina", response_class=HTMLResponse)
def rotina(request: Request, con=Depends(get_db)):
    sem = semana_atual()
    hoje = dt.date.today()
    with con:
        con.executemany("INSERT OR IGNORE INTO rotina_itens (semana, item) VALUES (?, ?)", [(sem, k) for k, _ in ROTINA])
    feitos = {r["item"]: r for r in con.execute("SELECT * FROM rotina_itens WHERE semana=?", (sem,))}
    itens = [{"chave": k, "texto": t, "feito": feitos[k]["feito"], "data": feitos[k]["data_feito"]} for k, t in ROTINA]
    ultimo_dia = (hoje.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    espera = con.execute("SELECT * FROM lista_espera WHERE excluido_em IS NULL ORDER BY hora, dia, data").fetchall()
    historico = con.execute("SELECT semana, SUM(feito) AS feitos, COUNT(*) AS total FROM rotina_itens GROUP BY semana ORDER BY semana DESC LIMIT 8").fetchall()
    return render(request, "rotina.html", con, itens=itens, semana=sem, espera=espera, horas_pico=HORAS_PICO,
                  ultimo_dia=ultimo_dia.isoformat(), historico=historico)


@app.post("/rotina/{item}/toggle")
def rotina_toggle(item: str, con=Depends(get_db)):
    with con:
        con.execute("UPDATE rotina_itens SET feito=1-feito, data_feito=CASE WHEN feito=0 THEN date('now','localtime') ELSE NULL END WHERE semana=? AND item=?",
                    (semana_atual(), item))
    return voltar("/rotina")


@app.post("/espera")
def espera_add(nome: str = Form(...), telefone: str = Form(""), dia: int = Form(0), hora: int = Form(...), local: str = Form(""),
               observacao: str = Form(""), con=Depends(get_db)):
    with con:
        con.execute("INSERT INTO lista_espera (nome, telefone, dia, hora, local, observacao) VALUES (?,?,?,?,?,?)",
                    (nome, telefone or None, dia or None, hora, local or None, observacao or None))
    return voltar("/rotina", msg="Adicionado à lista de espera.")


@app.post("/espera/{eid}/excluir")
def espera_excluir(eid: int, con=Depends(get_db)):
    with con:
        con.execute("UPDATE lista_espera SET excluido_em=datetime('now','localtime') WHERE id=?", (eid,))
    return voltar("/rotina")


# =====================================================================
# CONFIGURAÇÕES + IMPORTAR
# =====================================================================
GRUPOS_CONFIG = [("imposto", "Imposto (DAS)", "pct"), ("taxa_pagamento", "Taxas por forma de pagamento", "pct"),
                 ("margem_minima", "Margem mínima por serviço", "pct"), ("taxa_cia", "Taxa da CIA por pessoa (R$) e máximo de pessoas", "num"),
                 ("grupo_multiplicador", "Multiplicador de preço por nº de pessoas", "num"),
                 ("grupo_mao_obra_extra", "Mão de obra extra por nº de pessoas", "pct"), ("metas", "Metas do painel", "num"),
                 ("mao_obra_aula", "Mão de obra por aula (tipo|qtd)", "num"), ("lead_parado_dias", "Limite de dias parado por etapa", "num")]


@app.get("/configuracoes", response_class=HTMLResponse)
def configuracoes(request: Request, con=Depends(get_db)):
    grupos = []
    for g, titulo, fmt in GRUPOS_CONFIG:
        rows = con.execute("SELECT * FROM parametros WHERE grupo=? ORDER BY ordem, chave", (g,)).fetchall()
        if rows:
            grupos.append({"grupo": g, "titulo": titulo, "fmt": fmt, "itens": rows})
    listas_ = [(k, k.replace("lista_", "").replace("_", " ").capitalize(), con.execute("SELECT * FROM parametros WHERE grupo=? ORDER BY ordem", (k,)).fetchall())
               for k in db.LISTAS_INICIAIS]
    precos_ = con.execute("SELECT * FROM precos_base ORDER BY tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal").fetchall()
    ultima = con.execute("SELECT * FROM importacoes ORDER BY id DESC LIMIT 1").fetchone()
    return render(request, "configuracoes.html", con, grupos=grupos, listas_cfg=listas_, precos=precos_, ultima=ultima,
                  planilha=str(db.PLANILHA), planilha_existe=db.PLANILHA.exists())


@app.post("/configuracoes")
async def configuracoes_salvar(request: Request, con=Depends(get_db)):
    form = await request.form()
    with con:
        for k, v in form.items():
            if k.startswith("p_") and v != "":
                pid = int(k[2:])
                fmt = form.get(f"f_{pid}", "num")
                val = _num_br(v)
                con.execute("UPDATE parametros SET valor=? WHERE id=?", (val / 100 if fmt == "pct" else val, pid))
    return voltar("/configuracoes", msg="Parâmetros salvos.")


@app.post("/configuracoes/lista")
def configuracoes_lista(grupo: str = Form(...), nome: str = Form(...), con=Depends(get_db)):
    with con:
        con.execute("INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem) VALUES (?,?,?, (SELECT COALESCE(MAX(ordem),0)+1 FROM parametros WHERE grupo=?))",
                    (grupo, nome.strip(), nome.strip(), grupo))
    return voltar("/configuracoes", msg=f"'{nome}' adicionado.")


@app.post("/configuracoes/lista/{pid}/remover")
def configuracoes_lista_remover(pid: int, con=Depends(get_db)):
    with con:
        con.execute("DELETE FROM parametros WHERE id=? AND grupo LIKE 'lista_%'", (pid,))
    return voltar("/configuracoes", msg="Item removido da lista.")


@app.post("/configuracoes/preco")
def configuracoes_preco(tipo_servico: str = Form(...), local: str = Form(...), forma_pagamento: str = Form(...), qtd_aulas: int = Form(0),
                        freq_semanal: int = Form(0), sessoes_mes: float = Form(0), preco_base: float = Form(...),
                        custo_operacional: float = Form(0), mao_obra: float = Form(0), con=Depends(get_db)):
    with con:
        con.execute("""INSERT INTO precos_base (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, sessoes_mes, preco_base,
                       custo_operacional, mao_obra, custo_total, origem) VALUES (?,?,?,?,?,?,?,?,?,?,'manual')
                       ON CONFLICT(tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal) DO UPDATE SET sessoes_mes=excluded.sessoes_mes,
                       preco_base=excluded.preco_base, custo_operacional=excluded.custo_operacional, mao_obra=excluded.mao_obra,
                       custo_total=excluded.custo_total, origem='manual'""",
                    (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal, sessoes_mes, preco_base, custo_operacional, mao_obra,
                     custo_operacional))
    return voltar("/configuracoes", msg="Preço base salvo.")


@app.post("/importar")
def importar_planilha(con=Depends(get_db)):
    if not db.PLANILHA.exists():
        return voltar("/configuracoes", erro=f"Planilha não encontrada em {db.PLANILHA}")
    try:
        db.fazer_backup("antes-importar")
        resumo = importar.importar_tudo(con, db.PLANILHA)
    except Exception as e:  # noqa: BLE001 — mostrar o erro ao usuário em vez de derrubar o servidor
        return voltar("/configuracoes", erro=f"Falha na importação: {e}")
    txt = "; ".join(f"{k}: {v['inseridos']} novos, {v['atualizados']} atualizados" for k, v in resumo.items())
    return voltar("/configuracoes", msg="Importação concluída. " + txt)


# =====================================================================
# 8. DADOS: exportar, backup, restaurar, lixeira
# =====================================================================
LIXEIRA = [("clientes", "Cliente", "nome"), ("leads", "Lead", "nome"), ("propostas", "Proposta", "tipo_servico"),
           ("cliente_eventos", "Evento de cliente", "descricao"), ("lista_espera", "Lista de espera", "nome"),
           ("gastos_marketing", "Gasto de marketing", "canal"), ("campanha_itens", "Item de campanha", "texto")]


@app.get("/dados", response_class=HTMLResponse)
def dados(request: Request, con=Depends(get_db)):
    lim = (dt.datetime.now() - dt.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    lixo = []
    for tabela, rotulo, campo in LIXEIRA:
        for r in con.execute(f"SELECT id, {campo} AS nome, excluido_em FROM {tabela} WHERE excluido_em >= ? ORDER BY excluido_em DESC", (lim,)):
            lixo.append({"tabela": tabela, "rotulo": rotulo, "id": r["id"], "nome": r["nome"], "quando": r["excluido_em"]})
    lixo.sort(key=lambda x: x["quando"], reverse=True)
    backups, erro_backup = [], None
    try:
        backups = db.listar_backups()
    except OSError as e:  # sem redirect para /dados (viraria laço): mostra o erro na própria tela
        erro_backup = f"Não foi possível ler a pasta de backups: {e}"
    return render(request, "dados.html", con, backups=backups, lixo=lixo, pasta_backup=str(db.BACKUP_DIR),
                  banco=str(db.DB_PATH), erro_backup=erro_backup)


@app.post("/backup")
def backup_agora():
    try:
        f = db.fazer_backup()
    except Exception as e:
        return voltar("/dados", erro=f"O backup falhou: {e}")
    return voltar("/dados", msg=f"Backup criado: {f.name}")


@app.post("/restaurar")
def restaurar(nome: str = Form(...), confirmar: str = Form("")):
    if confirmar.strip().upper() != "RESTAURAR":
        return voltar("/dados", erro="Digite RESTAURAR para confirmar.")
    try:
        seg = db.restaurar_backup(nome)
    except FileNotFoundError:
        return voltar("/dados", erro="Backup não encontrado.")
    except ValueError as e:
        return voltar("/dados", erro=str(e))
    return voltar("/dados", msg=f"Banco restaurado de {nome}. O banco anterior foi guardado como {seg.name}.")


@app.post("/lixeira/restaurar")
def lixeira_restaurar(tabela: str = Form(...), rid: int = Form(...), con=Depends(get_db)):
    if tabela not in {t for t, _, _ in LIXEIRA}:
        return voltar("/dados", erro="Tabela inválida.")
    with con:
        con.execute(f"UPDATE {tabela} SET excluido_em=NULL WHERE id=?", (rid,))
    return voltar("/dados", msg="Registro restaurado.")


@app.get("/exportar/{nome}.{fmt}")
def exportar_arquivo(nome: str, fmt: str, con=Depends(get_db)):
    if nome == "metricas":
        historico = [dict(r) for r in con.execute("SELECT * FROM metricas_mensais ORDER BY mes")]
        atual = calcular_metricas(con)
        if not any(h["mes"] == atual["mes"] for h in historico):
            historico.append({k: atual.get(k) for k in ["mes", "clientes_ativos", "horas_ocupadas", "lucro_hora", "pct_receita_grupos",
                                                          "faturamento_recorrente", "clientes_perdidos", "vendas_abaixo_10", "nivel"]})
        cab, linhas = exportar.de_dicts(historico)
    else:
        try:
            cab, linhas = exportar.tabela(con, nome)
        except ValueError:
            return voltar("/dados", erro="Exportação desconhecida.")
    arquivo = f"vfitcoach-{nome}-{dt.date.today():%Y-%m-%d}.{fmt}"
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\n")
        w.writerow(cab)
        w.writerows(linhas)
        data = ("﻿" + buf.getvalue()).encode("utf-8")
        tipo = "text/csv"
    else:
        data = exportar.xlsx(cab, linhas, nome)
        tipo = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return StreamingResponse(io.BytesIO(data), media_type=tipo, headers={"Content-Disposition": f'attachment; filename="{arquivo}"'})
