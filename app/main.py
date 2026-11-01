"""VFITCOACH CRM — servidor web (FastAPI). Todas as rotas ficam aqui."""
import csv
import datetime as dt
import io
import json
import math
import re
import secrets
import signal
import sqlite3
import threading
import unicodedata
from contextlib import asynccontextmanager, closing
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import acesso, assistente, atualizar, db, exportar, financeiro, importar, precos, vigia
from . import indicacoes   # quem indicou quem e o presente da indicação (brinde, nunca desconto)
from . import alunos as alu   # estado de cada aluno (um algoritmo só); 'alunos' é nome de variável em várias rotas

ROOT = Path(__file__).resolve().parent
DIAS = {1: "Segunda", 2: "Terça", 3: "Quarta", 4: "Quinta", 5: "Sexta", 6: "Sábado", 7: "Domingo"}
DIAS_CURTO = {1: "Seg", 2: "Ter", 3: "Qua", 4: "Qui", 5: "Sex", 6: "Sáb", 7: "Dom"}
ETAPAS = [("lead", "Lead"), ("conversa", "Conversa"), ("avaliacao", "Avaliação marcada"), ("cliente", "Cliente"), ("perdido", "Perdido")]
HORAS_PICO = [7, 9, 18, 19]
SEMANAS_MES = 4.33


@asynccontextmanager
async def lifespan(app):
    if db.nuvem.ativo():
        db.nuvem.sincronizar(db.DB_PATH)   # sem internet segue com a réplica local; o alerta avisa
    try:
        db.iniciar_banco()
    except sqlite3.Error as e:
        if not db.nuvem.ativo():
            raise
        # sem internet as gravações do Turso falham: abre com a réplica local (o banco já existe) em vez de cair e dar 502
        print(f"AVISO: não deu para atualizar o banco na nuvem ({e}); abrindo com a cópia local.", flush=True)
        db.nuvem.status["erro"] = f"banco na nuvem fora do ar ao ligar: {e}"
    try:
        con = db.conectar()
        try:
            assistente.carregar_chave(con)   # chave do Assistente salva em Configurações
        finally:
            con.close()
    except Exception as e:  # o CRM abre mesmo sem ler a chave
        print(f"AVISO: não deu para ler a chave do Assistente ({e}).", flush=True)
    if db.nuvem.ativo():
        db.nuvem.iniciar_sync_periodico(db.DB_PATH)
    try:
        db.backup_diario()
    except Exception as e:  # o CRM abre mesmo se o backup falhar
        print(f"AVISO: backup diário falhou ({e}). Faça um backup manual em Dados.")
    atualizar.iniciar()   # só no PC com Windows: baixa versão nova do GitHub e reinicia quando ninguém está usando
    yield


app = FastAPI(title="VFITCOACH CRM", lifespan=lifespan)


@app.middleware("http")
async def portaria(request: Request, call_next):
    """Na internet (Render ou túnel até o PC), só passa quem entrou pelo Cloudflare Access. No próprio PC (localhost) não faz nada."""
    atualizar.registrar_uso()   # alguém usando: a atualização automática não reinicia agora
    motivo = await run_in_threadpool(acesso.motivo_bloqueio, request.method, request.url.path, request.headers, request.cookies)
    if motivo:
        return HTMLResponse("<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                            "<title>VFITCOACH CRM</title><body style='font-family:system-ui;padding:24px;background:#E8F0FA;color:#0F2A52'>"
                            f"<h1>Acesso restrito</h1><p>{acesso.MENSAGENS[motivo]}</p>", status_code=403)
    return await call_next(request)


@app.api_route("/saude", methods=["GET", "HEAD"], response_class=PlainTextResponse)
@app.api_route("/health", methods=["GET", "HEAD"], response_class=PlainTextResponse)
@app.api_route("/healthz", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def saude():
    return "ok"   # checagem do Render; não abre o banco nem mostra dados
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


# ---------- filtros de exibição (pt-BR) ----------
def moeda(v):
    if v is None:
        return "—"
    v = round(float(v), 2) + 0.0   # "-0,00" vira "0,00"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"−R$ {s}" if v < 0 else f"R$ {s}"   # negativo num formato só


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
def wa(tel, texto=""):
    """Link do WhatsApp; sem telefone o WhatsApp pede para escolher o contato."""
    n = "".join(ch for ch in str(tel or "") if ch.isdigit())
    if len(n) in (10, 11):
        n = "55" + n
    return f"https://wa.me/{n}?text={quote(texto or '', safe='')}"


def preencher(texto, nome="", data="", extra=None):
    """Troca {nome} e {data} na mensagem; na cobrança também {valor}, {dias}, {multa}, {juros} e {total} (extra)."""
    texto = (texto or "").replace("{nome}", nome or "").replace("{data}", data or "")
    for k, v in (extra or {}).items():
        texto = texto.replace("{" + k + "}", str(v))
    return texto


def texto_cobranca(cob) -> dict:
    """Valores da cobrança (financeiro.cobranca) já escritos para a mensagem do WhatsApp."""
    return {"valor": moeda(cob["valor"]), "dias": cob["dias"], "multa": moeda(cob["multa"]), "juros": moeda(cob["juros"]),
            "total": moeda(cob["total"])}


templates.env.filters["preencher"] = preencher
templates.env.filters["markdown"] = assistente.markdown_simples   # respostas do assistente (escapa todo o resto)
def versao(arquivo):
    """Etiqueta ?v= nos arquivos de /static: muda a cada atualização, então o navegador (celular) não usa o visual antigo do cache."""
    try:
        return int((ROOT / "static" / arquivo).stat().st_mtime)
    except OSError:
        return 0


templates.env.globals.update(ETAPAS=ETAPAS, DIAS=DIAS, hoje=lambda: dt.date.today().isoformat(), wa=wa, acesso=acesso, versao=versao)


def get_db():
    if db.nuvem.ativo():
        db.nuvem.sincronizar_se_velho(db.DB_PATH)   # traz o que foi lançado no outro aparelho (PC ou celular)
    con = db.conectar()
    try:
        yield con
    finally:
        con.close()


def render(request, nome, con, **ctx):
    ctx.update(request=request, msg=request.query_params.get("msg"), erro=request.query_params.get("erro"),
               listas={k: db.lista(con, k) for k in db.LISTAS_INICIAIS}, alertas=alertas(con),
               modelos=db.parametros(con, "msg_whatsapp"))
    return templates.TemplateResponse(request, nome, ctx)


def voltar(url, msg=None, erro=None):
    url, _, ancora = url.partition("#")   # a âncora (#hoje) fica no fim, depois do msg/erro
    if msg:
        url += ("&" if "?" in url else "?") + "msg=" + quote(msg)
    if erro:
        url += ("&" if "?" in url else "?") + "erro=" + quote(erro)
    return RedirectResponse(url + ("#" + ancora if ancora else ""), status_code=303)


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


def alunos_com_horario(con) -> set:
    """Ids de quem tem algum horário fixo ativo na Agenda."""
    return {r[0] for r in con.execute("SELECT DISTINCT cliente_id FROM agenda_fixos WHERE excluido_em IS NULL")}


def tem_aulas(c, com_horario) -> bool:
    """Regra única de "o aluno tem aula" (alertas e Controle do aluno). c = linha de clientes (id, tipo_servico, plano); com_horario = alunos_com_horario.
    Pacote e Mensalidade sempre; Consultoria e Avaliação só com horário fixo; sem tipo de serviço, vale o plano."""
    tipo = (c["tipo_servico"] or "").strip()
    return tipo in ("Pacote de Aulas", "Mensalidade") or c["id"] in com_horario or (not tipo and aulas_mes(c) > 0)


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


def estimativa_cliente(con, c, p):
    """Preço, custo e lucro do aluno pelo motor de preços (o mesmo da ficha, do simulador e da grade). None sem preço base ou sem valor.
    O valor da ficha é o que o aluno paga de verdade: o multiplicador de grupo do motor não se aplica por cima dele."""
    base = base_do_cliente(con, c)
    if not (base and c["valor"]):
        return None
    pessoas = c["pessoas"] or 1
    forma = c["forma_pagamento"] if c["forma_pagamento"] in p["taxas"] else "PIX"
    try:
        return precos.calcular({**dict(base), "preco_base": c["valor"] / (p["grupo_mult"].get(pessoas) or 1.0)}, p,
                               pessoas=pessoas, forma_pagamento=forma)
    except ValueError:
        return None


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
GRAV = {"vermelho": 1, "amarelo": 2, "azul": 3}
MAX_IDS = 200   # alunos de uma lista filtrada de /clientes?ids=


def acao_whatsapp(tel) -> list:
    """WhatsApp de um lead (não há modelo de mensagem para lead: abre a conversa sem texto). Sem telefone, nada."""
    return [{"rotulo": "WhatsApp", "href": wa(tel), "externo": True}] if tel else []


def contas_vencendo(con, h: str) -> list:
    """Saídas vencidas ou que vencem em até 3 dias (alerta e filtro ?vencidas=1 do Contas a pagar), vencidas primeiro.
    Na virada do mês (30/10 olhando 01/11) olha também as pendências do mês seguinte."""
    lim3 = (dt.date.fromisoformat(h) + dt.timedelta(days=3)).isoformat()
    vistos, venc = set(), []
    for mes_pend in dict.fromkeys((h[:7], lim3[:7])):
        for p in financeiro.pendencias(con, mes_pend, h):
            chave = (p["origem"], p["id"], p.get("competencia"))
            if p["tipo"] == "saida" and p["data"] <= lim3 and chave not in vistos:
                vistos.add(chave)
                venc.append(p)
    return sorted(venc, key=lambda p: (p["status"] != "atrasado", p["data"]))


def alertas(con):
    """Lista única de {grav, cor, texto, url, tel, modelo, acoes}, mais grave primeiro.
    acoes = botões do alerta, em ordem: {"wa": True} (WhatsApp/cobrança do modelo), {"rotulo", "href"} ou {"rotulo", "dialogo", "dados"}."""
    hoje = dt.date.today()
    h = hoje.isoformat()
    lim7 = (hoje + dt.timedelta(days=7)).isoformat()
    out = []

    def add(cor, texto, url, tel=None, modelo=None, nome=None, data=None, extra=None, botao=None, acoes=None):
        acoes = list(acoes or [])
        if modelo and not any(x.get("wa") for x in acoes):
            acoes.insert(0, {"wa": True})   # o WhatsApp do modelo vem primeiro, a menos que o alerta o ponha em outra posição
        out.append(dict(grav=GRAV[cor], cor=cor, texto=texto, url=url, tel=tel, modelo=modelo, nome=nome, data=data,
                        extra=extra, botao=botao, acoes=acoes))

    def s(n):
        return "s" if n > 1 else ""

    # alunos: UM algoritmo (alu.estado) diz a situação de cada um e traz os botões; aqui só vira alerta
    estados = alu.estado(con, hoje)
    incompletos = []
    for e in sorted(estados.values(), key=lambda e: (alu.ORDEM.index(e["situacao"]), e["ordem"])):
        if e["situacao"] == "em_dia":
            continue
        if e["situacao"] == "cadastro_incompleto":
            incompletos.append(e["id"])   # um alerta só para todos, no fim da lista
            continue
        add(e["cor"], alu.frase(e), f"/clientes/{e['id']}", e["tel"], e["modelo"], e["nome"], e["data_modelo"], extra=e["extra"],
            botao=e["botao"], acoes=e["acoes"])
    n = aulas_sem_marcar(con, hoje)
    if n:
        add("azul", f"{n} aula{s(n)} da agenda sem marcar nesta semana", "/agenda")
    for l in con.execute("""SELECT * FROM leads WHERE excluido_em IS NULL AND etapa NOT IN ('cliente','perdido')
                            ORDER BY data_proxima_acao IS NULL, data_proxima_acao"""):
        if l["data_proxima_acao"] and l["data_proxima_acao"] <= h:
            add("vermelho" if l["data_proxima_acao"] < h else "azul",
                f"{l['nome']} — {l['proxima_acao'] or 'próxima ação'} ({data_br(l['data_proxima_acao'])})", "/leads", l["telefone"],
                acoes=acao_whatsapp(l["telefone"]))
        elif d := dias_parado(con, l, h):
            add("amarelo", f"{l['nome']} — lead parado há {d} dias", "/leads", l["telefone"], acoes=acao_whatsapp(l["telefone"]))
    ultimo_dia = (hoje + dt.timedelta(days=1)).day == 1
    feitos = {r[0] for r in con.execute("SELECT item FROM rotina_itens WHERE semana=? AND feito=1", (semana_atual(),))}
    for t in tarefas_rotina(con):
        if (t["dia"] == hoje.isoweekday() or (t["chave"] == "fim_mes" and ultimo_dia)) and t["chave"] not in feitos:
            add("azul", "Rotina de hoje: " + rotina_texto(t), "/rotina")
    for c in con.execute("""SELECT pergunta, prazo FROM campanha_checkpoints WHERE excluido_em IS NULL AND resposta='pendente'
                            AND prazo <= ? ORDER BY prazo""", (lim7,)):
        add("vermelho" if c["prazo"] < h else "amarelo", f"Checkpoint de campanha ({data_br(c['prazo'])}): {c['pergunta']}", "/campanhas")
    venc = contas_vencendo(con, h)
    if venc:
        add("vermelho" if any(p["status"] == "atrasado" for p in venc) else "amarelo",
            f"{len(venc)} conta{s(len(venc))} vencida{s(len(venc))} ou vencendo em 3 dias ({moeda(sum(p['valor'] for p in venc))})",
            "/financeiro?vencidas=1#vencidas")
    rep = financeiro.duplicados(con)
    if rep:
        add("amarelo", f"{len(rep)} {'grupos' if len(rep) > 1 else 'grupo'} de lançamentos do financeiro {'parecem' if len(rep) > 1 else 'parece'} "
                       "repetido: confira e exclua", "/financeiro/conferir")
    sal = financeiro.salario_mes(con, h[:7], h)
    if sal["ligado"] and sal["pct_gasto"] >= 90:
        add("vermelho" if sal["pct_gasto"] >= 100 else "amarelo",
            f"Gasto pessoal do mês em {sal['pct_gasto']}% do salário ({moeda(sal['gasto_pf'])} de {moeda(sal['valor'])})", "/financeiro")
    if sal["pode_pagar"]:
        add("azul", f"Pagar o salário do mês ({moeda(sal['valor'])}) da PJ para a PF", "/financeiro")
    saldos = financeiro.saldos_resumo(con, h)
    if saldos["desatualizado"]:
        add("amarelo", f"Saldos das contas sem atualizar há {saldos['dias_velho']} dias: atualize para saber quanto tem", "/financeiro?abrir=saldos")
    n = con.execute("SELECT COUNT(*) FROM propostas WHERE excluido_em IS NULL AND status='enviada'").fetchone()[0]
    if n:
        add("azul", f"{n} proposta{s(n)} enviada{s(n)} esperando resposta", "/simulador")
    for p in indicacoes.pendentes(con):   # presente da indicação: o indicado já fez o 1º pagamento
        add("azul", f"Dar o presente a {p['indicador']} (indicou {p['indicado']})", f"/clientes/{p['indicador_id']}",
            acoes=[{"rotulo": "Registrar presente", "dialogo": "dlg-presente", "classe": "verde",
                    "dados": {"acao": f"/clientes/{p['indicador_id']}/indicacao/{p['indicado_id']}/presente",
                              "titulo": f"Presente para {p['indicador']}, que indicou {p['indicado']}"}}])
    if n := len(incompletos):
        add("azul", f"{n} aluno{s(n)} ativo{s(n)} com cadastro incompleto (telefone ou renovação)",
            "/clientes?ids=" + ",".join(map(str, incompletos[:MAX_IDS])) + "&motivo=incompleto")
    if db.nuvem.ativo() and db.nuvem.status["erro"]:
        add("vermelho", "Sem conexão com o banco na nuvem (Turso): confira a internet antes de lançar algo", "/dados")
    return sorted(out, key=lambda a: a["grav"])  # estável: mantém a ordem das fontes dentro da gravidade


# =====================================================================
# 6. PAINEL (tela inicial)
# =====================================================================
def calcular_metricas(con, mes=None):
    mes = mes or mes_atual()
    p = precos.carregar_parametros(con)
    metas = db.parametros(con, "metas")
    clientes = con.execute("SELECT * FROM clientes WHERE excluido_em IS NULL AND status='ativo'").fetchall()
    horas = horas_com_preco = lucro_total = 0.0
    receita = receita_grupos = 0.0
    for c in clientes:
        h = aulas_mes(c)
        horas += h
        receita += c["valor"] or 0
        if (c["pessoas"] or 1) > 1:
            receita_grupos += c["valor"] or 0
        est = estimativa_cliente(con, c, p)
        if est:   # lucro/h só sobre as horas de quem tem preço base: sem ele o aluno não tem lucro calculado
            horas_com_preco += h
            lucro_total += est["lucro"]
    perdidos = con.execute("""SELECT COUNT(*) FROM cliente_eventos WHERE tipo='status' AND descricao LIKE '%inativo%'
                              AND substr(data,1,7)=?""", (mes,)).fetchone()[0]
    abaixo10 = con.execute("""SELECT COUNT(*) FROM propostas WHERE excluido_em IS NULL AND status='aceita'
                              AND margem < 0.10 AND substr(data,1,7)=?""", (mes,)).fetchone()[0]
    espera_pico = con.execute("SELECT COUNT(*) FROM lista_espera WHERE excluido_em IS NULL AND hora IN (7,9,18,19)").fetchone()[0]
    lucro_hora = lucro_total / horas_com_preco if horas_com_preco else 0
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

        def chegou(etapa):   # leads que chegaram na etapa NESTE mês (o gasto também é do mês: dividir pela história inteira engana o CAC)
            if not ids:
                return 0
            q = ",".join("?" * len(ids))
            return con.execute(f"SELECT COUNT(DISTINCT lead_id) FROM lead_etapas_log WHERE etapa=? AND substr(data,1,7)=? AND lead_id IN ({q})",
                               (etapa, mes, *ids)).fetchone()[0]
        n_novos, n_conv, n_aval, n_cli = chegou("lead"), chegou("conversa"), chegou("avaliacao"), chegou("cliente")
        gasto = con.execute("""SELECT COALESCE(SUM(mensalidade+anuncios+comissoes+outros),0), COALESCE(SUM(leads),0),
                               COALESCE(SUM(clientes),0) FROM gastos_marketing WHERE excluido_em IS NULL AND canal=? AND mes=?""",
                            (canal, mes)).fetchone()
        clientes_canal = con.execute("""SELECT COUNT(*), COALESCE(AVG(valor),0) FROM clientes WHERE excluido_em IS NULL
                                        AND canal_origem=? AND substr(COALESCE(data_inicio, criado_em),1,7)=?""", (canal, mes)).fetchone()
        n_leads = n_novos or gasto[1]
        n_clientes = n_cli or gasto[2] or clientes_canal[0]
        if not (n_novos or n_conv or n_aval or gasto[0] or n_clientes):
            continue
        cpl = gasto[0] / n_leads if n_leads else None
        cac = gasto[0] / n_clientes if n_clientes else None
        ltv = clientes_canal[1] * ltv_meses if clientes_canal[1] else None
        out.append(dict(canal=canal, leads=n_leads, conversa=n_conv, avaliacao=n_aval, clientes=n_clientes, gasto=gasto[0],
                        tx_conversa=(n_conv / n_novos) if n_novos else None, tx_avaliacao=(n_aval / n_conv) if n_conv else None,
                        tx_fechamento=(n_cli / n_aval) if n_aval else None, cpl=cpl, cac=cac,
                        ltv_cac=(ltv / cac) if (ltv and cac) else None))
    return out


def gravar_mes(con, m):
    with con:
        con.execute("""INSERT INTO metricas_mensais (mes, clientes_ativos, horas_ocupadas, lucro_hora, pct_receita_grupos,
                       faturamento_recorrente, clientes_perdidos, vendas_abaixo_10, nivel) VALUES
                       (:mes,:clientes_ativos,:horas_ocupadas,:lucro_hora,:pct_receita_grupos,:faturamento_recorrente,
                       :clientes_perdidos,:vendas_abaixo_10,:nivel) ON CONFLICT(mes) DO UPDATE SET
                       clientes_ativos=excluded.clientes_ativos, horas_ocupadas=excluded.horas_ocupadas,
                       lucro_hora=excluded.lucro_hora, pct_receita_grupos=excluded.pct_receita_grupos,
                       faturamento_recorrente=excluded.faturamento_recorrente, clientes_perdidos=excluded.clientes_perdidos,
                       vendas_abaixo_10=excluded.vendas_abaixo_10, nivel=excluded.nivel, fechado_em=datetime('now','localtime')""", m)


@app.get("/", response_class=HTMLResponse)
def painel(request: Request, con=Depends(get_db)):
    m = calcular_metricas(con)
    metas = db.parametros(con, "metas")
    ant_mes = (dt.date.fromisoformat(m["mes"] + "-01") - dt.timedelta(days=1)).strftime("%Y-%m")
    if not con.execute("SELECT 1 FROM metricas_mensais WHERE mes=?", (ant_mes,)).fetchone():
        # ponytail: foto do primeiro acesso no mês; use Fechar o mês para histórico exato
        gravar_mes(con, calcular_metricas(con, ant_mes))
    ant = con.execute("SELECT * FROM metricas_mensais WHERE mes=?", (ant_mes,)).fetchone()
    historico = [dict(r) for r in con.execute("SELECT * FROM metricas_mensais ORDER BY mes")]
    historico = [h for h in historico if h["mes"] != m["mes"]] + [m]
    return render(request, "painel.html", con, m=m, ant=ant, metas=metas, canais=metricas_por_canal(con, m["mes"]),
                  historico=historico[-12:], fases=fase_atual(con))


@app.post("/painel/fechar-mes")
def fechar_mes(con=Depends(get_db)):
    m = calcular_metricas(con)
    gravar_mes(con, m)
    with con:
        # só marca na rotina se a tarefa "fim_mes" não foi excluída
        con.execute("""INSERT OR IGNORE INTO rotina_itens (semana, item) SELECT ?, 'fim_mes'
                       WHERE EXISTS (SELECT 1 FROM rotina_tarefas WHERE chave='fim_mes' AND excluido_em IS NULL)""", (semana_atual(),))
        con.execute("UPDATE rotina_itens SET feito=1, data_feito=date('now','localtime') WHERE semana=? AND item='fim_mes'", (semana_atual(),))
    return voltar("/", msg=f"Mês {m['mes'][5:]}/{m['mes'][:4]} fechado e guardado no histórico.")


# =====================================================================
# 1. CLIENTES
# =====================================================================
CAMPOS_CLIENTE = ["nome", "telefone", "local", "tipo_servico", "plano", "pessoas", "dias_horarios", "valor",
                  "forma_pagamento", "status", "canal_origem", "data_inicio", "data_renovacao", "observacoes", "indicado_por"]


def _num_br(v) -> float:
    s = str(v or "0").strip().replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):   # "1.500" = mil e quinhentos
        s = s.replace(".", "")
    return float(s or 0)


MOTIVOS_LISTA = {"sem-aula": "Alunos sem nenhuma aula registrada", "incompleto": "Cadastro incompleto"}   # /clientes?ids=..&motivo=..
TIPOS_SEM_AULA = ("Consultoria Online", "Consultoria Híbrida")


@app.get("/clientes", response_class=HTMLResponse)
def clientes(request: Request, status: str = "ativo", busca: str = "", ids: str = "", motivo: str = "", con=Depends(get_db)):
    # lista filtrada (link de um alerta): só estes alunos, sem os filtros de status e nome; quem já foi resolvido sai da lista
    filtro = list(dict.fromkeys(i for i in map(id_valido, ids.split(",")) if i))[:MAX_IDS]
    sql = "SELECT * FROM clientes WHERE excluido_em IS NULL"
    args = []
    if filtro:
        sql += f" AND id IN ({','.join('?' * len(filtro))})"
        args += filtro
        if motivo == "incompleto":
            sql += " AND status='ativo' AND (telefone IS NULL OR telefone='' OR data_renovacao IS NULL)"
    else:
        if status != "todos":
            sql += " AND status=?"
            args.append(status)
        if busca:
            sql += " AND nome LIKE ?"
            args.append(f"%{busca}%")
    rows = con.execute(sql + " ORDER BY status='ativo' DESC, nome", args).fetchall()
    hoje = dt.date.today()
    estados = alu.estado(con, hoje, ids=[c["id"] for c in rows if c["status"] == "ativo"])   # a situação de cada aluno vem do algoritmo central
    if filtro and motivo == "sem-aula":   # quem não está indo: sem aula registrada ou o mês pago/pulado sem aula (quem virou consultoria sai: mesma regra tem_aulas)
        rows = [c for c in rows if c["id"] in estados and estados[c["id"]]["situacao"] in alu.SEM_AULA]
    ren = financeiro.renovacoes(con)
    itens = []
    for c in rows:
        alerta = None
        renova = ren[c["id"]]["efetiva"] if c["id"] in ren else c["data_renovacao"]   # andou com os pagamentos
        if data_iso(renova) and c["status"] == "ativo":
            dias = (dt.date.fromisoformat(data_iso(renova)) - hoje).days
            alerta = "vermelho" if dias < 0 else ("amarelo" if dias <= 7 else None)
        faltas = [t for t, falta in (("falta telefone", not c["telefone"]), ("falta data de renovação", not c["data_renovacao"])) if falta]
        itens.append({**dict(c), "data_renovacao": renova, "alerta": alerta, "faltas": faltas, "estado": estados.get(c["id"])})
    totais = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM clientes WHERE excluido_em IS NULL GROUP BY status")}
    return render(request, "clientes.html", con, clientes=itens, status=status, busca=busca, totais=totais, filtrado=bool(filtro),
                  motivo=motivo if motivo in MOTIVOS_LISTA else "", titulo_lista=MOTIVOS_LISTA.get(motivo, "Alunos selecionados"),
                  voltar_lista=f"/clientes?ids={','.join(map(str, filtro))}&motivo={motivo if motivo in MOTIVOS_LISTA else ''}")


def _form_cliente(form) -> dict:
    d = {k: (form.get(k) or None) for k in CAMPOS_CLIENTE}
    d["pessoas"] = int(d["pessoas"] or 1)
    d["valor"] = _num_br(d["valor"])
    d["status"] = d["status"] or "ativo"
    return d


def _indicado_por(con, d: dict, proprio_id=None) -> str | None:
    """Confere o 'Indicado por' de d (troca o texto pelo id) e marca o canal como Indicação. Devolve o erro, se houver."""
    d["indicado_por"], erro = indicacoes.validar(con, d.get("indicado_por"), proprio_id)
    if d["indicado_por"]:
        d["canal_origem"] = indicacoes.CANAL
    return erro


@app.get("/clientes/novo", response_class=HTMLResponse)
def cliente_novo(request: Request, con=Depends(get_db)):
    return render(request, "cliente.html", con, c=None, eventos=[], estimativa=None, propostas=[],
                  indicadores=indicacoes.alunos_para_escolher(con))


@app.post("/clientes")
async def cliente_criar(request: Request, con=Depends(get_db)):
    d = _form_cliente(await request.form())
    if not d["nome"]:
        return voltar("/clientes/novo", erro="Informe o nome.")
    if erro := _indicado_por(con, d):
        return voltar("/clientes/novo", erro=erro)
    with con:
        cur = con.execute(f"INSERT INTO clientes ({','.join(CAMPOS_CLIENTE)}) VALUES ({','.join(':' + k for k in CAMPOS_CLIENTE)})", d)
    return voltar(f"/clientes/{cur.lastrowid}", msg="Cliente cadastrado.")


@app.get("/clientes/{cid}", response_class=HTMLResponse)
def cliente_ficha(request: Request, cid: int, con=Depends(get_db)):
    c = con.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone()
    if not c:
        return voltar("/clientes", erro="Cliente não encontrado.")
    eventos = con.execute("SELECT * FROM cliente_eventos WHERE cliente_id=? AND excluido_em IS NULL ORDER BY data DESC, id DESC", (cid,)).fetchall()
    estimativa = estimativa_cliente(con, c, precos.carregar_parametros(con))
    propostas = con.execute("SELECT * FROM propostas WHERE cliente_id=? AND excluido_em IS NULL ORDER BY id DESC", (cid,)).fetchall()
    pagamentos = con.execute("SELECT * FROM lancamentos WHERE cliente_id=? AND excluido_em IS NULL ORDER BY data DESC, id DESC LIMIT 8", (cid,)).fetchall()
    renovacao = financeiro.renovacoes(con, cid).get(cid)
    hoje = dt.date.today().isoformat()
    cob = (financeiro.cobranca(c["valor"], renovacao["efetiva"], hoje, db.parametros(con, "cobranca"))
           if renovacao and c["status"] == "ativo" else None)   # quem saiu não recebe cobrança de renovação
    pago_ate = None   # mês da última mensalidade paga: o ciclo que fecha na renovação efetiva (só se há pagamento de verdade)
    if renovacao and renovacao["ciclos"] and con.execute(
            """SELECT 1 FROM lancamentos WHERE cliente_id=? AND escopo='PJ' AND tipo='entrada' AND pago_em IS NOT NULL AND excluido_em IS NULL
               UNION ALL SELECT 1 FROM cliente_eventos WHERE cliente_id=? AND tipo='pagamento' AND excluido_em IS NULL LIMIT 1""", (cid, cid)).fetchone():
        m = financeiro.proxima_renovacao(renovacao["efetiva"], -1)
        pago_ate = f"{m[5:7]}/{m[:4]}"
    return render(request, "cliente.html", con, c=c, eventos=eventos, estimativa=estimativa, propostas=propostas, pagamentos=pagamentos,
                  renovacao=renovacao, cobranca=cob, texto_cob=texto_cobranca(cob) if cob else None, pago_ate=pago_ate,
                  estado=alu.estado_aluno(con, cid), indicadores=indicacoes.alunos_para_escolher(con, cid),
                  indicou=indicacoes.do_aluno(con, cid), indicado_por=indicacoes.quem_indicou(con, cid))


@app.post("/clientes/{cid}")
async def cliente_salvar(request: Request, cid: int, con=Depends(get_db)):
    d = _form_cliente(await request.form())
    d["id"] = cid
    if erro := _indicado_por(con, d, cid):
        return voltar(f"/clientes/{cid}", erro=erro)
    antigo = con.execute("SELECT status, data_renovacao FROM clientes WHERE id=?", (cid,)).fetchone()
    ren = financeiro.renovacoes(con, cid).get(cid)
    if antigo and ren and d["data_renovacao"] == ren["efetiva"]:
        d["data_renovacao"] = antigo["data_renovacao"]   # a ficha mostra a data que já andou com os pagamentos: salvar não mexe nela
    trocou = bool(antigo) and (d["data_renovacao"] or None) != (antigo["data_renovacao"] or None)
    with con:
        con.execute(f"UPDATE clientes SET {','.join(k + '=:' + k for k in CAMPOS_CLIENTE)}, atualizado_em=datetime('now','localtime') WHERE id=:id", d)
        if trocou:   # data trocada à mão: os pagamentos lançados até agora já estão nela
            con.execute("UPDATE clientes SET renovacao_em=datetime('now','localtime') WHERE id=?", (cid,))
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
    """Ficha: só anotação e mês pulado. Aula, falta e desmarcou são marcadas na Agenda."""
    if tipo not in ("anotacao", "pausa"):
        return voltar(f"/clientes/{cid}", erro="Aqui só anotação. Aula, falta e desmarcou: marque na Agenda.")
    msg, erro = registrar_evento(con, cid, tipo, data, valor, descricao, nova_renovacao)
    return voltar(f"/clientes/{cid}", msg=msg, erro=erro)


def registrar_evento(con, cid: int, tipo: str, data: str, valor="", descricao="", nova_renovacao="") -> tuple:
    """Registra no histórico do aluno (ficha ou assistente). Devolve (mensagem, erro): um dos dois é None."""
    v = _num_br(valor) if valor else None
    nova = data_iso(nova_renovacao)
    antes = financeiro.renovacoes(con, cid).get(cid)
    if tipo == "pausa":
        # pulou o mês: a renovação que estava para vencer não é cobrada; a próxima é a volta (vazio = um mês depois)
        pulada = data_iso(antes["efetiva"]) if antes else None
        pulada = pulada or data_iso(data) or dt.date.today().isoformat()
        volta = nova or financeiro.proxima_renovacao(pulada)
        if volta <= pulada:
            return None, f"A volta precisa ser depois de {data_br(pulada)} (a renovação que foi pulada)."
        texto = f"Renovação de {data_br(pulada)} sem cobrança; volta em {data_br(volta)}" + (f". {descricao}" if descricao else "")
        with con:
            con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, ate, descricao) VALUES (?,?,?,?,?)",
                        (cid, "pausa", pulada, volta, texto))
            con.execute("UPDATE clientes SET data_renovacao=?, renovacao_em=datetime('now','localtime'), status='ativo' WHERE id=?",
                        (volta, cid))
        return f"Mês pulado, sem cobrança. Próxima renovação: {data_br(volta)}.", None
    with con:
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, valor, descricao) VALUES (?,?,?,?,?)", (cid, tipo, data, v, descricao or None))
        if tipo == "renovacao" and nova:
            con.execute("UPDATE clientes SET data_renovacao=?, renovacao_em=datetime('now','localtime'), status='ativo' WHERE id=?",
                        (nova, cid))
        elif tipo == "renovacao" and not antes and data_iso(data):   # aluno sem data de renovação: renovou hoje, a próxima é daqui a um mês
            con.execute("UPDATE clientes SET data_renovacao=?, renovacao_em=datetime('now','localtime'), status='ativo' WHERE id=?",
                        (financeiro.proxima_renovacao(data_iso(data)), cid))
        elif tipo == "renovacao":
            con.execute("UPDATE clientes SET status='ativo' WHERE id=?", (cid,))
    if tipo != "renovacao":
        return "Registrado.", None
    depois = financeiro.renovacoes(con, cid).get(cid)
    proxima = data_br(depois["efetiva"]) if depois else "—"
    if nova or not antes or depois["efetiva"] != antes["efetiva"]:
        return f"Renovação registrada. Próxima: {proxima}.", None
    return (f"Registrado. A renovação continua em {proxima}: sem data, ela só anda quando faltam até {financeiro.ANTECEDENCIA} dias. "
            "Para outra data, preencha a nova data de renovação."), None


@app.post("/alunos/{cid}/credito")
def aluno_credito(cid: int, valor: str = Form(""), mes: str = Form(""), destino: str = Form("", alias="voltar"), con=Depends(get_db)):
    """Crédito do mês pago e não usado (valor vazio = o sugerido): vira desconto no próximo pagamento."""
    url = _caminho_seguro(destino) or f"/clientes/{cid}"
    try:
        v = _num_br(valor) if valor.strip() else None
    except ValueError:
        return voltar(url, erro="Valor inválido.")
    msg, erro = alu.dar_credito(con, cid, v, mes.strip() or None)
    return voltar(url, msg=msg, erro=erro)


@app.post("/alunos/{cid}/pulou")
def aluno_pulou(cid: int, destino: str = Form("", alias="voltar"), con=Depends(get_db)):
    """"Pulou o mês": a renovação anda um mês, sem cobrança."""
    msg, erro = alu.pular_mes(con, cid)
    return voltar(_caminho_seguro(destino) or f"/clientes/{cid}", msg=msg, erro=erro)


@app.post("/clientes/{cid}/consultoria")
def cliente_consultoria(cid: int, tipo_servico: str = Form(""), destino: str = Form("", alias="voltar"), con=Depends(get_db)):
    """"Não tem aula" (lista de alunos sem aula): o aluno é de consultoria, então não precisa de aula marcada. Volta para a lista."""
    url = _caminho_seguro(destino)
    url = url if url.startswith("/clientes") else "/clientes"
    if tipo_servico not in TIPOS_SEM_AULA:
        return voltar(url, erro="Escolha Consultoria Online ou Consultoria Híbrida.")
    c = con.execute("SELECT nome FROM clientes WHERE id=? AND excluido_em IS NULL", (cid,)).fetchone()
    if not c:
        return voltar(url, erro="Aluno não encontrado.")
    with con:
        con.execute("UPDATE clientes SET tipo_servico=?, atualizado_em=datetime('now','localtime') WHERE id=?", (tipo_servico, cid))
    return voltar(url, msg=f"{c['nome']}: {tipo_servico}.")


@app.post("/clientes/{cid}/excluir")
def cliente_excluir(cid: int, con=Depends(get_db)):
    with con:
        con.execute("UPDATE clientes SET excluido_em=datetime('now','localtime') WHERE id=?", (cid,))
    return voltar("/clientes", msg="Cliente enviado para a lixeira (restaurável em Dados).")


# ---------- indicações: o presente de quem indicou ----------
@app.post("/clientes/{cid}/indicacao/{iid}/presente")
def indicacao_presente(cid: int, iid: int, o_que: str = Form(""), custo: str = Form(""), data: str = Form(""),
                       destino: str = Form("", alias="voltar"), con=Depends(get_db)):
    """Registra o presente (brinde, nunca desconto) que o aluno `cid` ganhou por ter indicado `iid`. Um presente só por indicado."""
    url = _caminho_seguro(destino) or f"/clientes/{cid}"
    try:
        v = _num_br(custo) if custo.strip() else None
    except ValueError:
        return voltar(url, erro="Custo inválido: use só números, como 35,90.")
    msg, erro = indicacoes.registrar_presente(con, cid, iid, o_que, data_iso(data) or dt.date.today().isoformat(), v or None)
    return voltar(url, msg=msg, erro=erro)


# =====================================================================
# 2. LEADS (kanban)
# =====================================================================
def previsao_funil(con):
    chance = db.parametros(con, "funil_chance")
    # valor 0 é lead recém-convertido, ainda sem preço: não entra na média do ticket
    ticket = con.execute("SELECT AVG(valor) FROM clientes WHERE status='ativo' AND excluido_em IS NULL AND valor > 0").fetchone()[0] or 0
    etapas = con.execute("SELECT etapa, COUNT(*) n FROM leads WHERE excluido_em IS NULL GROUP BY etapa").fetchall()
    n = sum(r["n"] for r in etapas if r["etapa"] in chance)
    return {"receita": sum(chance[r["etapa"]] * r["n"] for r in etapas if r["etapa"] in chance) * ticket, "leads": n, "ticket": ticket}


def motivos_perda(con):
    return con.execute("""SELECT COALESCE(NULLIF(LOWER(TRIM(motivo_perda)), ''), 'sem motivo') m, COUNT(*) n FROM leads
                          WHERE etapa='perdido' AND excluido_em IS NULL GROUP BY m ORDER BY n DESC, m""").fetchall()


@app.get("/leads", response_class=HTMLResponse)
def leads(request: Request, con=Depends(get_db)):
    rows = con.execute("SELECT * FROM leads WHERE excluido_em IS NULL ORDER BY data_proxima_acao IS NULL, data_proxima_acao, id DESC").fetchall()
    colunas = {e: [] for e, _ in ETAPAS}
    hoje = dt.date.today().isoformat()
    for l in rows:
        atrasado = bool(l["data_proxima_acao"] and l["data_proxima_acao"] < hoje and l["etapa"] not in ("cliente", "perdido"))
        parado = dias_parado(con, l, hoje)
        colunas[l["etapa"]].append({**dict(l), "atrasado": atrasado, "dias": parado, "parado": bool(parado)})
    return render(request, "leads.html", con, colunas=colunas, destaque=request.query_params.get("destaque"),
                  previsao=previsao_funil(con), motivos=motivos_perda(con), indicadores=indicacoes.alunos_para_escolher(con))


@app.post("/leads")
def lead_criar(nome: str = Form(...), telefone: str = Form(""), canal_origem: str = Form(...), interesse: str = Form(""),
               proxima_acao: str = Form(""), data_proxima_acao: str = Form(""), observacoes: str = Form(""),
               indicado_por: str = Form(""), con=Depends(get_db)):
    indicador, erro = indicacoes.validar(con, indicado_por)
    if erro:
        return voltar("/leads", erro=erro)
    with con:
        cur = con.execute("""INSERT INTO leads (nome, telefone, canal_origem, interesse, proxima_acao, data_proxima_acao, observacoes, indicado_por)
                             VALUES (?,?,?,?,?,?,?,?)""", (nome, telefone or None, indicacoes.CANAL if indicador else canal_origem,
                                                           interesse or None, proxima_acao or None, data_proxima_acao or None,
                                                           observacoes or None, indicador))
        con.execute("INSERT INTO lead_etapas_log (lead_id, etapa) VALUES (?, 'lead')", (cur.lastrowid,))
    return voltar("/leads", msg="Lead adicionado.")


@app.post("/leads/{lid}")
def lead_salvar(lid: int, nome: str = Form(...), telefone: str = Form(""), canal_origem: str = Form(...), interesse: str = Form(""),
                proxima_acao: str = Form(""), data_proxima_acao: str = Form(""), observacoes: str = Form(""),
                indicado_por: str = Form(""), con=Depends(get_db)):
    antigo = con.execute("SELECT cliente_id FROM leads WHERE id=?", (lid,)).fetchone()
    indicador, erro = indicacoes.validar(con, indicado_por, antigo["cliente_id"] if antigo else None)   # o lead já virou aluno: esse aluno não se indica
    if erro:
        return voltar("/leads", erro=erro)
    with con:
        con.execute("""UPDATE leads SET nome=?, telefone=?, canal_origem=?, interesse=?, proxima_acao=?, data_proxima_acao=?,
                       observacoes=?, indicado_por=?, atualizado_em=datetime('now','localtime') WHERE id=?""",
                    (nome, telefone or None, indicacoes.CANAL if indicador else canal_origem, interesse or None, proxima_acao or None,
                     data_proxima_acao or None, observacoes or None, indicador, lid))
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
            cur = con.execute("""INSERT INTO clientes (nome, telefone, canal_origem, observacoes, lead_id, tipo_servico, local, indicado_por, data_inicio)
                                 VALUES (?,?,?,?,?,?,?,?,date('now','localtime'))""",
                              (l["nome"], l["telefone"], l["canal_origem"], l["observacoes"], lid,
                               partes[0].strip() or None, partes[1].strip() if len(partes) > 1 else None, l["indicado_por"]))
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
def plano_referencia(con, tipo_calculo, local, ref=0):
    # ref = vezes por semana (Mensalidades) ou nº de aulas (Pacotes); 0 = padrão 2x/sem ou 8 aulas
    if tipo_calculo == "Mensalidades":
        return con.execute("SELECT * FROM precos_base WHERE tipo_servico='Mensalidade' AND local=? AND forma_pagamento='PIX' ORDER BY abs(freq_semanal-?) LIMIT 1", (local, ref or 2)).fetchone()
    return con.execute("SELECT * FROM precos_base WHERE tipo_servico='Pacote de Aulas' AND local=? AND forma_pagamento='PIX' ORDER BY abs(qtd_aulas-?) LIMIT 1", (local, ref or 8)).fetchone()


@app.get("/grade", response_class=HTMLResponse)
def grade(request: Request, tipo: str = "Pacotes", local: str = "CIA", vale: int = 0, ref: int = 0, con=Depends(get_db)):
    slots = con.execute("SELECT * FROM grade_slots WHERE tipo_calculo=? AND local=? AND dia BETWEEN 1 AND 6", (tipo, local)).fetchall()
    p = precos.carregar_parametros(con)
    base = plano_referencia(con, tipo, local, ref)
    col, servico = ("freq_semanal", "Mensalidade") if tipo == "Mensalidades" else ("qtd_aulas", "Pacote de Aulas")
    refs = [r[0] for r in con.execute(f"SELECT DISTINCT {col} FROM precos_base WHERE tipo_servico=? AND local=? AND forma_pagamento='PIX' AND {col} IS NOT NULL ORDER BY 1", (servico, local))]
    celulas = {}
    for s in slots:
        cel = dict(s)
        cel["preco_aula"] = cel["margem"] = cel["preco_total"] = cel["lucro"] = None
        cel["apagado"] = False
        if s["status"] == "livre" and base:
            r = precos.calcular(dict(base), p, mult_horario=s["multiplicador"] or 1)
            cel["preco_aula"] = r["preco_total"] / (base["sessoes_mes"] or 1)
            cel["margem"], cel["preco_total"], cel["lucro"] = r["margem"], r["preco_total"], r["lucro"]
        if vale and not (s["status"] == "livre" and (s["multiplicador"] or 1) < 1):
            cel["apagado"] = True
        celulas[(s["dia"], s["hora"])] = cel
    locais = [r[0] for r in con.execute("SELECT DISTINCT local FROM grade_slots ORDER BY local")] or db.lista(con, "lista_locais")
    clientes_ = con.execute("SELECT id, nome FROM clientes WHERE excluido_em IS NULL AND status='ativo' ORDER BY nome").fetchall()
    resumo = {"livres": sum(1 for c in celulas.values() if c["status"] == "livre"),
              "ocupados": sum(1 for c in celulas.values() if c["status"] == "ocupado"),
              "vale": sum(1 for c in celulas.values() if c["status"] == "livre" and (c["multiplicador"] or 1) < 1)}
    return render(request, "grade.html", con, celulas=celulas, tipo=tipo, local=local, vale=vale, locais=locais,
                  horas=range(5, 24), clientes=clientes_, base=base, resumo=resumo, refs=refs, ref_atual=base[col] if base else None)


def salvar_slots(con, slots, bloco=100):
    """Grava várias células da grade com UM upsert de várias linhas (blocos de 100: 8 parâmetros por linha, e o SQLite limita os parâmetros).
    slots = [(tipo, dia, local, hora, status, cliente_id, cliente_nome, multiplicador)]. No Turso cada gravação é uma viagem pela rede.
    Quem chama abre a transação."""
    for i in range(0, len(slots), bloco):
        parte = slots[i:i + bloco]
        con.execute("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, cliente_id, cliente_nome, multiplicador) VALUES "
                    + ",".join(["(?,?,?,?,?,?,?,?)"] * len(parte)) + """ ON CONFLICT(tipo_calculo, dia, local, hora) DO UPDATE SET
                   status=excluded.status, cliente_id=excluded.cliente_id, cliente_nome=excluded.cliente_nome,
                   multiplicador=excluded.multiplicador""", [v for l in parte for v in l])


def salvar_slot(con, tipo, dia, local, hora, status, cliente_id, cliente_nome, multiplicador):
    """Grava uma célula da grade (cria ou atualiza). Usada pela Grade e pela Agenda; quem chama abre a transação."""
    salvar_slots(con, [(tipo, dia, local, hora, status, cliente_id, cliente_nome, multiplicador)])


@app.post("/grade/slot")
def grade_slot(tipo: str = Form(...), local: str = Form(...), dia: int = Form(0), hora: int = Form(0), status: str = Form(""),
               cliente_id: str = Form(""), multiplicador: str = Form(""), so_este: int = Form(0), ref: int = Form(0),
               celulas: list[str] = Form([]), con=Depends(get_db)):
    lote = bool(celulas)
    pares = []
    for c in (celulas or [f"{dia}-{hora}"])[:300]:
        try:
            d, h = (int(x) for x in c.split("-"))
        except ValueError:
            continue
        if 1 <= d <= 6 and 5 <= h <= 23 and (d, h) not in pares:
            pares.append((d, h))
    url = f"/grade?tipo={tipo}&local={local}&ref={ref}"
    if not pares or status not in ("", "livre", "ocupado", "indisponivel"):
        return voltar(url, erro="Nenhum horário selecionado." if not pares else "Situação inválida.")
    cid = int(cliente_id) if cliente_id else None
    nome = con.execute("SELECT nome FROM clientes WHERE id=?", (cid,)).fetchone()["nome"] if cid else None
    mult_novo = _num_br(multiplicador) or 1.0 if multiplicador.strip() else None
    tipos = [tipo] if so_este else ["Pacotes", "Mensalidades"]
    with con:
        for t in tipos:
            for d, h in pares:
                ex = con.execute("SELECT * FROM grade_slots WHERE tipo_calculo=? AND dia=? AND local=? AND hora=?",
                                 (t, d, local, h)).fetchone()
                st = status or (ex["status"] if ex else None) or "livre"
                if status:
                    c_id, c_nome = (cid, nome) if st == "ocupado" else (None, None)
                else:
                    c_id, c_nome = (ex["cliente_id"], ex["cliente_nome"]) if ex else (None, None)
                mult = mult_novo if mult_novo is not None else ((ex["multiplicador"] if ex else None) or 1.0)
                salvar_slot(con, t, d, local, h, st, c_id, c_nome, mult)
    msg = f"{len(pares)} horários atualizados." if lote else f"{DIAS_CURTO[pares[0][0]]} {pares[0][1]:02d}h atualizado."
    return voltar(url, msg=msg)


# =====================================================================
# 3b. AGENDA (horários fixos próprios + aulas avulsas; marcar a aula com 1 toque; a Agenda avisa a Grade, nunca o contrário)
# =====================================================================
ESTADO_TIPO = {"feita": "aula", "faltou": "falta", "desmarcou": "desmarcou", "cancelada": "cancelada"}   # estado na tela -> tipo em cliente_eventos
TIPO_ESTADO = {t: e for e, t in ESTADO_TIPO.items()}
TIPOS_MARCA = ",".join(f"'{t}'" for t in ESTADO_TIPO.values())   # para o IN (...) do SQL: tudo o que a Agenda marca
ESTADO_MSG = {"feita": "aula feita", "faltou": "faltou", "desmarcou": "desmarcou (repõe)", "cancelada": "cancelada (não repõe)"}
ISO_DATA = re.compile(r"\d{4}-\d{2}-\d{2}")


def inicio_semana(texto="") -> dt.date:
    """Segunda-feira da semana de qualquer data ISO (vazia ou inválida: semana atual)."""
    try:
        d = dt.date.fromisoformat(str(texto or "").strip()[:10])
    except ValueError:
        d = dt.date.today()
    return d - dt.timedelta(days=d.weekday())


def fases_bloqueio(con) -> list:
    """(início, fim) das fases de bloqueio das Campanhas (ex.: casamento 25/10 a 02/11)."""
    return [(f["inicio"], f["fim"]) for f in con.execute(
        "SELECT inicio, fim FROM campanha_fases WHERE tipo='bloqueio' AND inicio IS NOT NULL AND fim IS NOT NULL")]


def em_bloqueio(fases, iso) -> bool:
    return any(i <= iso <= f for i, f in fases)


def data_iso(v) -> str | None:
    """'AAAA-MM-DD' válida (dos 10 primeiros caracteres) ou None."""
    s = str(v or "").strip()[:10]
    try:
        return dt.date.fromisoformat(s).isoformat() if ISO_DATA.fullmatch(s) else None
    except ValueError:
        return None


templates.env.globals.update(data_iso=data_iso, proxima_renovacao=financeiro.proxima_renovacao)


def pausas_por_aluno(con) -> dict:
    """{cliente_id: [(início, fim)]} dos meses pulados (ficha → Pulou o mês): da renovação pulada até a véspera da volta."""
    out = {}
    for e in con.execute("SELECT cliente_id, data, ate FROM cliente_eventos WHERE tipo='pausa' AND excluido_em IS NULL"):
        ini = data_iso(e["data"])
        if not ini:
            continue
        volta = data_iso(e["ate"])
        if not volta or volta <= ini:
            volta = financeiro.proxima_renovacao(ini)
        out.setdefault(e["cliente_id"], []).append((ini, (dt.date.fromisoformat(volta) - dt.timedelta(days=1)).isoformat()))
    return out


def dias_parados(ultima: dt.date, hoje: dt.date, intervalos) -> int:
    """Quantos dias depois de `ultima` até `hoje` (inclusive) caem em algum intervalo [início, fim] ISO: bloqueio da agenda
    (viagem) ou mês pulado. Intervalos que se cruzam contam uma vez."""
    total, contado = 0, ultima
    for i, f in sorted(intervalos):
        ini = max(dt.date.fromisoformat(i), contado + dt.timedelta(days=1))
        fim = min(dt.date.fromisoformat(f), hoje)
        if fim >= ini:
            total += (fim - ini).days + 1
            contado = fim
    return total


def aulas_da_semana(con, segunda, hoje=None) -> list:
    """Aulas de segunda a sábado: horários fixos da Agenda (aluno ativo, a partir da data de início) + avulsas, com o estado marcado.
    situacao: feita | faltou | desmarcou | cancelada | pausa (mês pulado, sem marcar) | pendente (dia passou sem marcar) | futura (hoje ou depois, sem marcar)."""
    h = (hoje or dt.date.today()).isoformat()
    datas = {n: (segunda + dt.timedelta(days=n - 1)).isoformat() for n in range(1, 7)}
    aulas, vistos = [], set()
    for r in con.execute("""SELECT f.dia, f.hora, f.local, c.id AS cliente_id, c.nome, c.telefone, c.data_inicio
                            FROM agenda_fixos f JOIN clientes c ON c.id=f.cliente_id
                            WHERE f.excluido_em IS NULL AND f.dia BETWEEN 1 AND 6 AND f.hora BETWEEN 5 AND 23
                            AND c.status='ativo' AND c.excluido_em IS NULL ORDER BY f.id"""):
        if (r["dia"], r["hora"], r["cliente_id"]) in vistos:   # linha repetida (voltou da lixeira): conta uma vez só
            continue
        vistos.add((r["dia"], r["hora"], r["cliente_id"]))
        ini = str(r["data_inicio"] or "").strip()[:10]
        if ISO_DATA.fullmatch(ini) and datas[r["dia"]] < ini:
            continue
        aulas.append(dict(data=datas[r["dia"]], dia=r["dia"], hora=r["hora"], local=r["local"], cliente_id=r["cliente_id"],
                          nome=r["nome"], telefone=r["telefone"], avulsa=False, avulsa_id=None, reposicao=False, repoe=""))
    dia_de = {d: n for n, d in datas.items()}
    for r in con.execute("""SELECT a.id, a.data, a.hora, a.local, a.reposicao, c.id AS cliente_id, c.nome, c.telefone,
                            (SELECT o.data FROM cliente_eventos o WHERE o.id=a.repoe_evento_id AND o.excluido_em IS NULL) AS repoe
                            FROM agenda_avulsas a JOIN clientes c ON c.id=a.cliente_id
                            WHERE a.excluido_em IS NULL AND a.data BETWEEN ? AND ? AND c.status='ativo' AND c.excluido_em IS NULL""",
                         (datas[1], datas[6])):
        if r["data"] in dia_de:   # domingo (ou data torta) não entra
            aulas.append(dict(data=r["data"], dia=dia_de[r["data"]], hora=r["hora"], local=r["local"], cliente_id=r["cliente_id"],
                              nome=r["nome"], telefone=r["telefone"], avulsa=True, avulsa_id=r["id"], reposicao=bool(r["reposicao"]),
                              repoe=data_br(r["repoe"])[:5] if r["reposicao"] and r["repoe"] else ""))   # dd/mm da aula desmarcada que ela repõe
    marcas = {}   # (aluno, data) -> [(hora, estado)] do mais antigo ao mais novo
    for e in con.execute(f"""SELECT cliente_id, data, hora, tipo FROM cliente_eventos WHERE excluido_em IS NULL
                             AND tipo IN ({TIPOS_MARCA}) AND data BETWEEN ? AND ? ORDER BY id""", (datas[1], datas[6])):
        marcas.setdefault((e["cliente_id"], e["data"]), []).append((e["hora"], TIPO_ESTADO[e["tipo"]]))
    fases, pausas = fases_bloqueio(con), pausas_por_aluno(con)
    for a in aulas:
        # vale a marca mais nova do aluno no dia com a mesma hora, ou sem hora (aula lançada pela ficha)
        a["estado"] = next((est for hr, est in reversed(marcas.get((a["cliente_id"], a["data"]), [])) if hr is None or hr == a["hora"]), None)
        a["pausa"] = any(i <= a["data"] <= f for i, f in pausas.get(a["cliente_id"], []))   # "Pulou o mês" cobre o dia
        a["situacao"] = a["estado"] or ("pausa" if a["pausa"] else "pendente" if a["data"] < h else "futura")
        a["bloqueio"] = em_bloqueio(fases, a["data"])
    return sorted(aulas, key=lambda a: (a["data"], a["hora"], a["nome"].lower()))


def aulas_sem_marcar(con, hoje) -> int:
    """Aulas desta semana (de segunda até ontem) sem marcação (Feita, Faltou, Desmarcou ou Cancelada), fora dos dias de bloqueio e do mês pulado."""
    if isinstance(hoje, str):
        hoje = dt.date.fromisoformat(hoje)
    h = hoje.isoformat()
    return sum(1 for a in aulas_da_semana(con, inicio_semana(h), hoje) if a["data"] < h and not a["estado"] and not a["bloqueio"] and not a["pausa"])


def _norm(texto) -> str:
    """Minúsculas, sem acento e com espaços simples: "  JOSÉ  Álvares " vira "jose alvares"."""
    s = unicodedata.normalize("NFKD", str(texto or "").lower())
    return " ".join("".join(ch for ch in s if not unicodedata.combining(ch)).split())


def sugerir_cliente(nome, clientes):
    """Id do aluno ativo que bate com um nome escrito à mão na Grade: nome completo igual (sem acento/maiúscula), ou o único aluno
    cujo nome começa com o que foi digitado ("Ana" -> "Ana Silva"). None se não achar ou se houver mais de um."""
    n = _norm(nome)
    if not n:
        return None
    cands = []
    for c in clientes:
        try:
            if c["status"] != "ativo":
                continue
        except (KeyError, IndexError):   # lista já só com alunos ativos
            pass
        cands.append((c["id"], _norm(c["nome"])))
    for bate in (lambda x: x == n, lambda x: x.startswith(n + " ")):
        achou = [i for i, x in cands if bate(x)]
        if len(achou) == 1:
            return achou[0]
    return None


def ocupar_fixo(con, cid, nome, dia, local, hora):
    """Põe o aluno no horário fixo da Grade (Pacotes e Mensalidades, mantendo o multiplicador de cada um).
    Devolve o texto do erro (horário de outro aluno ou indisponível) ou None se gravou. Quem chama abre a transação."""
    rows = con.execute("SELECT * FROM grade_slots WHERE dia=? AND local=? AND hora=?", (dia, local, hora)).fetchall()
    dono = next((r for r in rows if r["status"] == "ocupado" and r["cliente_id"] and r["cliente_id"] != cid), None)
    if dono:   # nome escrito à mão (sem cliente_id) pode ser trocado: é o "ligar ao aluno"
        outro = con.execute("SELECT nome FROM clientes WHERE id=?", (dono["cliente_id"],)).fetchone()
        return f"Esse horário já é de {outro['nome'] if outro else dono['cliente_nome']} na Grade. Tire ele de lá antes."
    if any(r["status"] == "indisponivel" for r in rows):
        return f"{DIAS_CURTO[dia]} {hora:02d}h em {local} está indisponível na Grade. Libere o horário lá antes."
    mult = {r["tipo_calculo"]: r["multiplicador"] or 1.0 for r in rows}
    for t in ("Pacotes", "Mensalidades"):
        salvar_slot(con, t, dia, local, hora, "ocupado", cid, nome, mult.get(t, 1.0))
    return None


def nomes_curtos(nomes) -> list:
    """Primeiro nome de cada um; se dois começam igual ("Ana Silva" e "Ana Lima"), usa o nome inteiro."""
    cur = [(str(n or "").split() or [""])[0] for n in nomes]
    return [n if [x.lower() for x in cur].count(c.lower()) > 1 else c for n, c in zip(nomes, cur)]


def fixos_do_horario(con, dia, hora) -> list:
    """Linhas ativas do horário fixo (dia, hora) dos alunos ativos, da mais antiga à mais nova (id, cliente_id, local, nome)."""
    return con.execute("""SELECT f.id, f.cliente_id, f.local, c.nome FROM agenda_fixos f JOIN clientes c ON c.id=f.cliente_id
                          WHERE f.dia=? AND f.hora=? AND f.excluido_em IS NULL AND c.status='ativo' AND c.excluido_em IS NULL
                          ORDER BY f.id""", (dia, hora)).fetchall()


def inserir_fixos(con, linhas, bloco=200):
    """Grava (cliente_id, dia, hora, local) na agenda_fixos com UM INSERT de várias linhas (blocos de 200: o SQLite limita os parâmetros).
    No Turso cada gravação é uma viagem pela rede, então nunca em laço. Quem chama abre a transação."""
    for i in range(0, len(linhas), bloco):
        parte = linhas[i:i + bloco]
        con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES " + ",".join(["(?,?,?,?)"] * len(parte)),
                    [v for l in parte for v in l])


def grade_liberar(con, cid, dia, local, hora) -> bool:
    """Solta a célula da Grade (Pacotes e Mensalidades) se ainda é deste aluno. Lê antes: sem célula dele, não grava nada."""
    if not con.execute("SELECT 1 FROM grade_slots WHERE cliente_id=? AND dia=? AND local=? AND hora=? LIMIT 1", (cid, dia, local, hora)).fetchone():
        return False
    con.execute("""UPDATE grade_slots SET status='livre', cliente_id=NULL, cliente_nome=NULL
                   WHERE cliente_id=? AND dia=? AND local=? AND hora=?""", (cid, dia, local, hora))
    return True


def grade_ocupar(con, cid, nome, dia, local, hora):
    """Avisa a Grade que o aluno tem este horário. Melhor esforço: célula de outro aluno ou indisponível fica como está, e erro dela nunca
    vira erro da Agenda. Se os dois tipos já são dele, não grava nada."""
    try:
        ja = con.execute("""SELECT COUNT(DISTINCT tipo_calculo) FROM grade_slots WHERE dia=? AND local=? AND hora=? AND status='ocupado'
                            AND cliente_id=? AND tipo_calculo IN ('Pacotes','Mensalidades')""", (dia, local, hora, cid)).fetchone()[0]
        if ja < 2:
            ocupar_fixo(con, cid, nome, dia, local, hora)
    except sqlite3.Error:
        pass


def grade_ocupar_lote(con, cid, nome, pares):
    """Como grade_ocupar, para vários horários do mesmo aluno de uma vez: pares = [(dia, local, hora)]. 1 SELECT nas células e 1 upsert de
    várias linhas (salvar_slots); célula de outro aluno, indisponível ou que já é dele fica como está. Melhor esforço: erro da Grade nunca vira erro da Agenda."""
    try:
        if not pares:
            return
        ondes = " OR ".join(["(dia=? AND local=? AND hora=?)"] * len(pares))
        rows = con.execute(f"SELECT * FROM grade_slots WHERE tipo_calculo IN ('Pacotes','Mensalidades') AND ({ondes})", [v for p in pares for v in p]).fetchall()
        por = {}
        for r in rows:
            por.setdefault((r["dia"], r["local"], r["hora"]), []).append(r)
        slots = []
        for par in pares:
            cel = por.get(par, [])
            if any(r["status"] == "ocupado" and r["cliente_id"] and r["cliente_id"] != cid for r in cel) or any(r["status"] == "indisponivel" for r in cel):
                continue
            if len({r["tipo_calculo"] for r in cel if r["status"] == "ocupado" and r["cliente_id"] == cid}) >= 2:
                continue
            mult = {r["tipo_calculo"]: r["multiplicador"] or 1.0 for r in cel}
            slots += [(t, par[0], par[1], par[2], "ocupado", cid, nome, mult.get(t, 1.0)) for t in ("Pacotes", "Mensalidades")]
        if slots:
            salvar_slots(con, slots)
    except sqlite3.Error:
        pass


def definir_horario(con, dia, hora, alunos, local) -> dict:
    """Deixa o horário fixo (dia, hora) com estes alunos (0 a 2 ids) e grava só a diferença: sai = exclusão (lixeira), troca de local =
    UPDATE, entra = INSERT; quem não mudou não gera gravação. `local` é um texto (vale para todos) ou {cliente_id: local}.
    Depois avisa a Grade, só nesse sentido: solta a célula de quem saiu ou mudou de local e ocupa a de quem entrou ou mudou
    (sem mexer em célula de outro aluno ou indisponível; sem erro). Quem chama abre a transação.
    Devolve {"entrou": [ids], "saiu": [ids], "mudou": [ids]}."""
    alunos = list(dict.fromkeys(alunos))[:2]
    locais = local if isinstance(local, dict) else {c: local for c in alunos}
    atual, apagar = {}, []
    for r in fixos_do_horario(con, dia, hora):
        if r["cliente_id"] in atual:
            apagar.append(r["id"])   # linha repetida (voltou da lixeira): sobra
        else:
            atual[r["cliente_id"]] = r
    saiu = [c for c in atual if c not in alunos]
    mudou = [c for c in alunos if c in atual and atual[c]["local"] != locais[c]]
    entrou = [c for c in alunos if c not in atual]
    apagar += [atual[c]["id"] for c in saiu]
    if apagar:
        con.execute(f"UPDATE agenda_fixos SET excluido_em=datetime('now','localtime') WHERE id IN ({','.join('?' * len(apagar))})", apagar)
    for c in mudou:
        con.execute("UPDATE agenda_fixos SET local=? WHERE id=?", (locais[c], atual[c]["id"]))
    if entrou:
        inserir_fixos(con, [(c, dia, hora, locais[c]) for c in entrou])
    soltos = set()   # células da Grade que ficaram livres agora
    for c in saiu + mudou:
        try:
            if grade_liberar(con, c, dia, atual[c]["local"], hora):
                soltos.add(atual[c]["local"])
        except sqlite3.Error:
            pass
    ocupar = entrou + mudou + [c for c in alunos if c in atual and c not in mudou and locais[c] in soltos]   # + quem ficou com a célula que acabou de soltar
    if ocupar:
        nomes = {r["id"]: r["nome"] for r in con.execute(f"SELECT id, nome FROM clientes WHERE id IN ({','.join('?' * len(ocupar))})", ocupar)}
        for c in ocupar:
            if c in nomes:
                grade_ocupar(con, c, nomes[c], dia, locais[c], hora)
    return {"entrou": entrou, "saiu": saiu, "mudou": mudou}


MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def mes_valido(texto) -> str:
    """"AAAA-MM" se for um mês de 2000 a 2100; senão vazio."""
    t = str(texto or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", t) and 2000 <= int(t[:4]) <= 2100 and 1 <= int(t[5:]) <= 12:
        return t
    return ""


def id_valido(texto) -> int:
    """Id numérico de um campo de texto (vazio ou torto: 0)."""
    t = str(texto or "").strip()
    return int(t) if t.isascii() and t.isdigit() and len(t) < 10 else 0


def url_agenda(semana, todas=0, aluno="", mes="") -> str:
    """Endereço da Agenda; mantém o aluno do painel de controle (e o mês dele) quando vierem."""
    url = f"/agenda?semana={inicio_semana(semana).isoformat()}" + ("&todas=1" if todas else "")
    if id_valido(aluno):
        url += f"&aluno={id_valido(aluno)}" + (f"&mes={mes_valido(mes)}" if mes_valido(mes) else "")
    return url


def descricao_marca(d, hora, local, avulsa=False, reposicao=False) -> str:
    return " ".join(p for p in (f"Agenda — {DIAS_CURTO[d.isoweekday()]} {hora:02d}h", (local or "").strip(),
                                "(reposição)" if reposicao else "(avulsa)" if avulsa else "") if p)


def gravar_marcas(con, itens, bloco_exclusao=300, bloco_insercao=150):
    """Grava marcações da Agenda: itens = [(cliente_id, data, hora, estado, descricao)]; estado "" só desfaz. A marcação nova substitui as
    anteriores da mesma aula (e a lançada pela ficha, sem hora). Repetido (mesmo aluno, data e hora): vale o último.
    1 UPDATE de exclusão para todos + 1 INSERT de várias linhas para os que têm estado (em blocos: o SQLite limita os parâmetros).
    No Turso cada gravação é uma viagem pela rede, então nunca em laço. Quem chama abre a transação."""
    ultimo = {}
    for cid, data, hora, estado, desc in itens:
        ultimo[(cid, data, hora)] = (estado, desc)
    chaves = list(ultimo)
    for i in range(0, len(chaves), bloco_exclusao):
        parte = chaves[i:i + bloco_exclusao]
        con.execute(f"UPDATE cliente_eventos SET excluido_em=datetime('now','localtime') WHERE excluido_em IS NULL AND tipo IN ({TIPOS_MARCA}) AND ("
                    + " OR ".join(["(cliente_id=? AND data=? AND (hora=? OR hora IS NULL))"] * len(parte)) + ")", [v for k in parte for v in k])
    novas = [(c, ESTADO_TIPO[e], d, desc, h) for (c, d, h), (e, desc) in ultimo.items() if e]
    for i in range(0, len(novas), bloco_insercao):
        parte = novas[i:i + bloco_insercao]
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao, hora) VALUES " + ",".join(["(?,?,?,?,?)"] * len(parte)),
                    [v for l in parte for v in l])


def saldos_reposicao(con, ids=None, hoje=None) -> dict:
    """Reposições de cada aluno, só leitura (2 SELECTs agrupados, nenhuma tabela de saldo): {cid: {devidas, usadas, saldo, agendadas}}.
    devidas = marcações 'desmarcou' ativas (a 'cancelada' não repõe e nunca entra); usadas = avulsas de reposição (não excluídas) com Feita ou Faltou
    no mesmo aluno, data e hora (faltar na reposição perde a reposição); saldo = devidas - usadas, nunca abaixo de 0;
    agendadas = avulsas de reposição de hoje em diante sem marcação.
    Com ids, devolve todos eles (zerados se for o caso); sem ids, só quem tem alguma coisa."""
    h = (hoje or dt.date.today()).isoformat()
    ids = list(dict.fromkeys(ids)) if ids is not None else None
    filtro = lambda col: f" AND {col} IN ({','.join('?' * len(ids))})" if ids is not None else ""
    out = {c: {"devidas": 0, "usadas": 0, "saldo": 0, "agendadas": 0} for c in (ids or [])}
    if ids is not None and not ids:
        return out
    for r in con.execute("SELECT cliente_id, COUNT(*) AS n FROM cliente_eventos WHERE excluido_em IS NULL AND tipo='desmarcou'"
                         + filtro("cliente_id") + " GROUP BY cliente_id", ids or []):
        out.setdefault(r["cliente_id"], {"devidas": 0, "usadas": 0, "saldo": 0, "agendadas": 0})["devidas"] = r["n"]
    marca = """(SELECT COUNT(*) FROM cliente_eventos e WHERE e.cliente_id=a.cliente_id AND e.data=a.data AND e.hora=a.hora AND e.excluido_em IS NULL
               AND e.tipo IN ({}))"""
    for r in con.execute(f"""SELECT cliente_id, SUM(CASE WHEN com_af > 0 THEN 1 ELSE 0 END) AS usadas,
                            SUM(CASE WHEN com_qualquer = 0 AND data >= ? THEN 1 ELSE 0 END) AS agendadas
                            FROM (SELECT a.cliente_id, a.data, {marca.format("'aula','falta'")} AS com_af, {marca.format(TIPOS_MARCA)} AS com_qualquer
                                  FROM agenda_avulsas a WHERE a.reposicao=1 AND a.excluido_em IS NULL{filtro("a.cliente_id")})
                            GROUP BY cliente_id""", [h] + (ids or [])):
        d = out.setdefault(r["cliente_id"], {"devidas": 0, "usadas": 0, "saldo": 0, "agendadas": 0})
        d["usadas"], d["agendadas"] = r["usadas"] or 0, r["agendadas"] or 0
    for d in out.values():
        d["saldo"] = max(d["devidas"] - d["usadas"], 0)
    return out


def controle_aluno(con, cid, mes, hoje) -> dict | None:
    """Painel do aluno na Agenda: saldo de reposições (sempre o total) e as aulas do mês (feitas, faltas, desmarcadas, canceladas e reposições
    agendadas). Cada linha de evento traz o id (eid) para os botões do desmarcou; a reposição ligada a uma desmarcação traz a data dela (repoe).
    None se o aluno não existe. mes = "AAAA-MM" válido."""
    c = con.execute("SELECT id, nome, status FROM clientes WHERE id=? AND excluido_em IS NULL", (cid,)).fetchone()
    if not c:
        return None
    ano, m = int(mes[:4]), int(mes[5:])
    primeiro = dt.date(ano, m, 1)
    prox = dt.date(ano + (m == 12), m % 12 + 1, 1)
    ant = primeiro - dt.timedelta(days=1)
    h = hoje.isoformat()
    locais = {(r["dia"], r["hora"]): r["local"] for r in con.execute(
        "SELECT dia, hora, local FROM agenda_fixos WHERE cliente_id=? AND excluido_em IS NULL ORDER BY id DESC", (cid,))}
    de_quem = "(SELECT o.data FROM cliente_eventos o WHERE o.id=a.repoe_evento_id AND o.excluido_em IS NULL)"   # a desmarcação que a reposição repõe
    linhas = []
    for e in con.execute(f"""SELECT e.id, e.data, e.hora, e.tipo, a.local, a.id IS NOT NULL AS repos, {de_quem} AS repoe FROM cliente_eventos e
                            LEFT JOIN agenda_avulsas a ON a.cliente_id=e.cliente_id AND a.data=e.data AND a.hora=e.hora AND a.reposicao=1 AND a.excluido_em IS NULL
                            WHERE e.cliente_id=? AND e.excluido_em IS NULL AND e.tipo IN ({TIPOS_MARCA}) AND e.data >= ? AND e.data < ?
                            ORDER BY e.data, e.hora, e.id""", (cid, primeiro.isoformat(), prox.isoformat())):
        dia = dt.date.fromisoformat(e["data"]).isoweekday()
        linhas.append({"eid": e["id"], "data": e["data"], "hora": e["hora"], "estado": TIPO_ESTADO[e["tipo"]], "reposicao": bool(e["repos"]),
                       "repoe": e["repoe"], "local": e["local"] or locais.get((dia, e["hora"]), "")})
    for a in con.execute(f"""SELECT a.data, a.hora, a.local, {de_quem} AS repoe FROM agenda_avulsas a
                            WHERE a.cliente_id=? AND a.reposicao=1 AND a.excluido_em IS NULL
                            AND a.data >= ? AND a.data < ? AND a.data >= ? AND NOT EXISTS (SELECT 1 FROM cliente_eventos e WHERE e.cliente_id=a.cliente_id
                            AND e.data=a.data AND e.hora=a.hora AND e.excluido_em IS NULL AND e.tipo IN ({TIPOS_MARCA}))""",
                         (cid, primeiro.isoformat(), prox.isoformat(), h)):
        linhas.append({"eid": None, "data": a["data"], "hora": a["hora"], "estado": "agendada", "reposicao": True, "repoe": a["repoe"], "local": a["local"]})
    linhas.sort(key=lambda l: (l["data"], l["hora"] if l["hora"] is not None else -1))
    for l in linhas:
        d = dt.date.fromisoformat(l["data"])
        l["data_br"], l["dia"] = f"{d:%d/%m}", DIAS_CURTO[d.isoweekday()]
        l["repoe_br"] = data_br(l["repoe"])[:5] if l["repoe"] else ""   # dd/mm
    contar = lambda est: sum(1 for l in linhas if l["estado"] == est)
    return {"id": c["id"], "nome": c["nome"], "status": c["status"], "mes": mes, "mes_txt": f"{MESES[m - 1]} de {ano}",
            "mes_ant": ant.strftime("%Y-%m"), "mes_prox": prox.strftime("%Y-%m"), "eh_atual": mes == hoje.strftime("%Y-%m"),
            "feitas": contar("feita"), "faltou": contar("faltou"), "desmarcou": contar("desmarcou"), "canceladas": contar("cancelada"),
            "repostas": sum(1 for l in linhas if l["estado"] == "feita" and l["reposicao"]), "linhas": linhas,
            **saldos_reposicao(con, [cid], hoje)[cid]}


@app.get("/agenda", response_class=HTMLResponse)
def agenda(request: Request, semana: str = "", todas: int = 0, aluno: str = "", mes: str = "", con=Depends(get_db)):
    hoje = dt.date.today()
    segunda = inicio_semana(semana)
    atual = segunda == inicio_semana(hoje.isoformat())
    fases = fases_bloqueio(con)
    dias = [{"n": n, "data": segunda + dt.timedelta(days=n - 1)} for n in range(1, 7)]
    for d in dias:
        d["iso"] = d["data"].isoformat()
        d["hoje"] = d["data"] == hoje
        d["bloqueio"] = em_bloqueio(fases, d["iso"])
    aulas = aulas_da_semana(con, segunda, hoje)
    saldos = saldos_reposicao(con, {a["cliente_id"] for a in aulas}, hoje) if aulas else {}
    celulas = {}
    for a in aulas:
        celulas.setdefault((a["dia"], a["hora"]), []).append(a)
        a["deve"] = saldos[a["cliente_id"]]["saldo"]
        a["marca"] = {k: a[k] for k in ("cliente_id", "data", "hora", "local", "avulsa", "reposicao", "estado")}   # o que o "Marcar várias" manda ao salvar
        a["base"] = a["marca"]["base"] = "bloq" if a["bloqueio"] else "pausa" if a["pausa"] else ("pendente" if a["data"] < hoje.isoformat() else "futura")   # cor da aula sem marcação
    for lista in celulas.values():
        for a, curto in zip(lista, nomes_curtos([a["nome"] for a in lista])):
            a["curto"] = curto
    fixos = {}   # (dia, hora) -> quem tem o horário fixo (mesmo antes da data de início): preenche o seletor
    for r in con.execute("""SELECT f.dia, f.hora, f.local, c.id AS cliente_id, c.nome FROM agenda_fixos f JOIN clientes c ON c.id=f.cliente_id
                            WHERE f.excluido_em IS NULL AND f.dia BETWEEN 1 AND 6 AND f.hora BETWEEN 5 AND 23
                            AND c.status='ativo' AND c.excluido_em IS NULL ORDER BY f.id"""):
        lista = fixos.setdefault((r["dia"], r["hora"]), [])
        if all(x["cliente_id"] != r["cliente_id"] for x in lista):
            lista.append({"cliente_id": r["cliente_id"], "nome": r["nome"], "local": r["local"]})
    clientes_ = con.execute("SELECT id, nome, local, tipo_servico, plano FROM clientes WHERE excluido_em IS NULL AND status='ativo' ORDER BY nome").fetchall()
    com_horario = alunos_com_horario(con)
    com_aulas = [c for c in clientes_ if tem_aulas(c, com_horario)]   # só eles no Controle do aluno; Incluir aula e horário fixo listam todos
    vazia = con.execute("SELECT 1 FROM agenda_fixos WHERE excluido_em IS NULL LIMIT 1").fetchone() is None
    horas = range(5, 24) if todas or not celulas else sorted({h for _, h in celulas})
    infos = {}   # (dia, hora) -> dados do card para a janelinha (JSON no data-info)
    for d in dias:
        for h in horas:
            lista, fx = celulas.get((d["n"], h), []), fixos.get((d["n"], h), [])
            infos[(d["n"], h)] = {
                "dia": d["n"], "hora": h, "data": d["iso"], "titulo": f"{DIAS_CURTO[d['n']]} {d['data']:%d/%m} · {h:02d}h",
                "local": (fx or lista or [{"local": ""}])[0]["local"],
                "alunos": [{k: a[k] for k in ("cliente_id", "nome", "estado", "situacao", "avulsa", "avulsa_id", "reposicao", "repoe", "local", "bloqueio", "pausa", "deve", "base")} for a in lista],
                "fixos": fx}
    locais = db.lista(con, "lista_locais")
    locais += [r[0] for r in con.execute("""SELECT local FROM grade_slots UNION SELECT local FROM agenda_fixos WHERE excluido_em IS NULL ORDER BY 1""")
               if r[0] not in locais]
    mes_ok = mes_valido(mes) or hoje.strftime("%Y-%m")
    controle = controle_aluno(con, id_valido(aluno), mes_ok, hoje) if id_valido(aluno) else None   # aluno ou mês inválidos: página normal
    extra_aluno = f"&aluno={controle['id']}&mes={controle['mes']}" if controle else ""
    extra = ("&todas=1" if todas else "") + extra_aluno   # vai nos links da tela, para o painel do aluno não sumir ao trocar de semana
    return render(request, "agenda.html", con, dias=dias, horas=horas, celulas=celulas, infos=infos, todas=1 if todas else 0, atual=atual, hoje_d=hoje,
                  segunda=segunda.isoformat(), anterior=(segunda - dt.timedelta(days=7)).isoformat(), proxima=(segunda + dt.timedelta(days=7)).isoformat(),
                  semana_txt=f"{segunda:%d/%m} a {segunda + dt.timedelta(days=5):%d/%m}", tem_aulas=bool(celulas), vazia=vazia,
                  hoje_aulas=[a for a in aulas if a["data"] == hoje.isoformat()] if atual else [],
                  multi_local=len({x["local"] for l in celulas.values() for x in l}) > 1, controle=controle, extra=extra, extra_aluno=extra_aluno,
                  hoje_segunda=inicio_semana(hoje.isoformat()).isoformat(),
                  locais=locais, clientes=clientes_, com_aulas=com_aulas, data_padrao=(hoje if atual else segunda).isoformat())


@app.post("/agenda/marcar")
def agenda_marcar(cliente_id: int = Form(0), data: str = Form(""), hora: int = Form(0), local: str = Form(""), estado: str = Form(""),
                  avulsa: int = Form(0), reposicao: int = Form(0), semana: str = Form(""), todas: int = Form(0), aluno: str = Form(""), mes: str = Form(""),
                  ancora: str = Form(""), con=Depends(get_db)):
    url = url_agenda(semana or data, todas, aluno, mes) + ("#hoje" if ancora == "hoje" else "")   # o card Hoje volta para o próprio card
    try:
        d = dt.date.fromisoformat(data.strip())
    except ValueError:
        return voltar(url, erro="Data inválida.")
    if estado and estado not in ESTADO_TIPO:
        return voltar(url, erro="Situação inválida.")
    if not 5 <= hora <= 23:
        return voltar(url, erro="Hora inválida.")
    c = con.execute("SELECT nome FROM clientes WHERE id=? AND excluido_em IS NULL", (cliente_id,)).fetchone()
    if not c:
        return voltar(url, erro="Aluno não encontrado.")
    with con:
        gravar_marcas(con, [(cliente_id, d.isoformat(), hora, estado, descricao_marca(d, hora, local, avulsa, reposicao))])
    primeiro = (c["nome"].split() or [c["nome"]])[0]
    return voltar(url, msg=f"{primeiro}: {ESTADO_MSG[estado]}." if estado else f"{primeiro}: marcação desfeita.")


@app.post("/agenda/marcar-lote")
def agenda_marcar_lote(itens: str = Form(""), semana: str = Form(""), todas: int = Form(0), aluno: str = Form(""), mes: str = Form(""), con=Depends(get_db)):
    """"Marcar várias": o navegador pinta as aulas sem falar com o servidor e manda tudo de uma vez, em JSON:
    [{cliente_id, data, hora, local, avulsa, reposicao, estado}] (até 300; estado "" desfaz a marcação). Valida tudo antes de gravar:
    1 SELECT dos alunos e 2 gravações no total (gravar_marcas)."""
    try:
        lista = json.loads(itens)
    except ValueError:
        lista = None
    if not isinstance(lista, list) or not lista:
        return voltar(url_agenda(semana, todas, aluno, mes), erro="Nenhuma aula para salvar.")
    url = url_agenda(semana or (lista[0].get("data") if isinstance(lista[0], dict) else ""), todas, aluno, mes)
    if len(lista) > 300:
        return voltar(url, erro="Muitas aulas de uma vez (máximo 300).")
    marcas = {}   # (aluno, data, hora) -> item; repetido: vale o último
    for it in lista:
        if not isinstance(it, dict):
            return voltar(url, erro="Dados inválidos.")
        try:
            d = dt.date.fromisoformat(str(it.get("data", "")).strip())
        except ValueError:
            return voltar(url, erro="Data inválida.")
        estado = it.get("estado") or ""
        if estado not in ("", *ESTADO_TIPO):
            return voltar(url, erro="Situação inválida.")
        try:
            cid, hora = int(it.get("cliente_id")), int(it.get("hora"))
        except (TypeError, ValueError):
            return voltar(url, erro="Dados inválidos.")
        if not 5 <= hora <= 23:
            return voltar(url, erro="Hora inválida.")
        marcas[(cid, d.isoformat(), hora)] = (d, estado, descricao_marca(d, hora, str(it.get("local") or ""), it.get("avulsa"), it.get("reposicao")))
    ids = list({k[0] for k in marcas})
    achados = {r["id"] for r in con.execute(f"SELECT id FROM clientes WHERE excluido_em IS NULL AND id IN ({','.join('?' * len(ids))})", ids)}
    if len(achados) != len(ids):
        return voltar(url, erro="Aluno não encontrado.")
    with con:
        gravar_marcas(con, [(c, data, h, est, desc) for (c, data, h), (_, est, desc) in marcas.items()])
    n = {e: sum(1 for _, est, _ in marcas.values() if est == e) for e in ESTADO_TIPO}
    feitas = sum(n.values())
    partes = [txt for txt in (f"{n['feita']} {'feita' if n['feita'] == 1 else 'feitas'}" if n["feita"] else "",
                              f"{n['faltou']} {'faltou' if n['faltou'] == 1 else 'faltaram'}" if n["faltou"] else "",
                              f"{n['desmarcou']} {'desmarcou' if n['desmarcou'] == 1 else 'desmarcaram'}" if n["desmarcou"] else "",
                              f"{n['cancelada']} {'cancelada' if n['cancelada'] == 1 else 'canceladas'}" if n["cancelada"] else "",
                              f"{_plural(len(marcas) - feitas, 'desfeita', 'desfeitas')}" if len(marcas) > feitas else "") if txt]
    if not feitas:
        return voltar(url, msg=f"{_plural(len(marcas), 'marcação desfeita', 'marcações desfeitas')}.")
    return voltar(url, msg=f"{_plural(feitas, 'aula marcada', 'aulas marcadas')}: {', '.join(partes)}.")


@app.post("/agenda/incluir")
def agenda_incluir(cliente_id: int = Form(0), local: str = Form(""), dia: int = Form(0), hora: int = Form(0), repetir: int = Form(1),
                   data: str = Form(""), reposicao: int = Form(0), dias: list[int] = Form([]), horas: list[int] = Form([]),
                   semana: str = Form(""), todas: int = Form(0), aluno: str = Form(""), mes: str = Form(""), repoe_evento_id: str = Form(""),
                   con=Depends(get_db)):
    """Horário fixo (repetir=1) ou aula avulsa (repetir=0, com reposicao=1 se for reposição). O fixo aceita vários horários de uma vez:
    dias[] e horas[] em pares (até 12); sem eles vale o dia/hora de sempre. repoe_evento_id (só na reposição): a desmarcação que ela repõe."""
    url = url_agenda(semana, todas, aluno, mes)
    local = local.strip()
    c = con.execute("SELECT nome FROM clientes WHERE id=? AND excluido_em IS NULL AND status='ativo'", (cliente_id,)).fetchone()
    if not c:
        return voltar(url, erro="Escolha um aluno ativo.")
    if not local:
        return voltar(url, erro="Escolha o local.")
    if repetir and dias:
        if len(dias) != len(horas):
            return voltar(url, erro="Escolha o dia e a hora de cada horário.")
        pares = list(dict.fromkeys(zip(dias, horas)))
        if len(pares) > 12:
            return voltar(url, erro="No máximo 12 horários de uma vez.")
    else:
        pares = [(dia, hora)]
    if not all(5 <= h <= 23 for _, h in pares):
        return voltar(url, erro="Escolha a hora (05h a 23h).")
    if repetir:   # horário fixo: soma o aluno aos que já estão (cabem 2) e avisa a Grade
        if not all(1 <= d <= 6 for d, _ in pares):
            return voltar(url, erro="Escolha o dia (segunda a sábado).")
        ja, cheios, mudam, novos = [], [], [], []   # lê tudo antes: sem nada a gravar, nem abre transação
        for d, h in pares:
            locais = {}
            for r in fixos_do_horario(con, d, h):
                locais.setdefault(r["cliente_id"], r["local"])
            if cliente_id in locais and locais[cliente_id] == local:
                ja.append((d, h))
            elif cliente_id in locais:
                mudam.append((d, h, locais))
            elif len(locais) >= 2:
                cheios.append((d, h))
            else:
                novos.append((d, h))
        if mudam or novos:
            with con:
                for d, h, locais in mudam:   # já está em outro local (raro): troca o local, com a Grade
                    locais[cliente_id] = local
                    definir_horario(con, d, h, list(locais), locais)
                if novos:   # todos os horários novos: 1 INSERT na Agenda + 1 upsert na Grade
                    inserir_fixos(con, [(cliente_id, d, h, local) for d, h in novos])
                    grade_ocupar_lote(con, cliente_id, c["nome"], [(d, local, h) for d, h in novos])
        q = lambda lst: ", ".join(f"{DIAS_CURTO[x[0]]} {x[1]:02d}h" for x in lst)
        if len(pares) == 1:
            quando = q(pares)
            if cheios:
                return voltar(url, erro=f"{quando} já tem 2 alunos.")
            if ja:
                return voltar(url, msg=f"{c['nome']} já está no horário fixo de {quando} ({local}).")
            acao = f"agora fica em {local} no horário fixo de {quando}" if mudam else f"entrou no horário fixo de {quando} ({local})"
            return voltar(url, msg=f"{c['nome']} {acao}. A Grade também foi atualizada.")
        primeiro = (c["nome"].split() or [c["nome"]])[0]
        frases = [f"{primeiro} entrou em {q(novos)} ({local})." if novos else "",
                  f"{primeiro} agora fica em {local} em {q(mudam)}." if mudam else "",
                  f"{q(ja)} já {'estava' if len(ja) == 1 else 'estavam'}." if ja else "",
                  f"{q(cheios)} já {'tem' if len(cheios) == 1 else 'têm'} 2 alunos." if cheios else ""]
        texto = " ".join(f for f in frases if f)
        return voltar(url, erro=texto) if cheios and not (novos or mudam or ja) else voltar(url, msg=texto)
    try:
        d = dt.date.fromisoformat(data.strip())
    except ValueError:
        return voltar(url, erro="Escolha a data da aula avulsa.")
    if d.isoweekday() == 7:
        return voltar(url, erro="Domingo não aparece na agenda.")
    origem = None   # a desmarcação que esta reposição repõe (só informativo: o saldo não depende dela)
    if reposicao and id_valido(repoe_evento_id):
        origem = con.execute("SELECT id, data FROM cliente_eventos WHERE id=? AND cliente_id=? AND tipo='desmarcou' AND excluido_em IS NULL",
                             (id_valido(repoe_evento_id), cliente_id)).fetchone()
        if not origem:
            return voltar(url, erro="Essa aula desmarcada não existe mais.")
    with con:
        con.execute("INSERT INTO agenda_avulsas (cliente_id, data, hora, local, reposicao, repoe_evento_id) VALUES (?,?,?,?,?,?)",
                    (cliente_id, d.isoformat(), hora, local, 1 if reposicao else 0, origem["id"] if origem else None))
    return voltar(url_agenda(d.isoformat(), todas, aluno, mes),
                  msg=f"{'Reposição' if reposicao else 'Aula avulsa'} de {c['nome']} em {d:%d/%m} às {hora:02d}h"
                      + (f" (repõe a de {data_br(origem['data'])[:5]})." if origem else "."))


@app.post("/agenda/horario")
def agenda_horario(dia: int = Form(0), hora: int = Form(0), aluno1: str = Form(""), aluno2: str = Form(""), local: str = Form(""),
                   semana: str = Form(""), todas: int = Form(0), aluno: str = Form(""), mes: str = Form(""), con=Depends(get_db)):
    """Seletor do card: quem tem aula neste dia e hora (até 2 alunos) e em que local. Sem aluno = "sem aula"."""
    url = url_agenda(semana, todas, aluno, mes)
    local = local.strip()
    if not 1 <= dia <= 6:
        return voltar(url, erro="Escolha o dia (segunda a sábado).")
    if not 5 <= hora <= 23:
        return voltar(url, erro="Escolha a hora (05h a 23h).")
    ids = []
    for txt in (aluno1.strip(), aluno2.strip()):
        if not txt:
            continue
        if not (txt.isascii() and txt.isdigit()):
            return voltar(url, erro="Escolha um aluno ativo.")
        if int(txt) not in ids:   # o mesmo aluno nos dois campos vale uma vez
            ids.append(int(txt))
    nomes = {}
    if ids:
        nomes = {r["id"]: r["nome"] for r in con.execute(
            f"SELECT id, nome FROM clientes WHERE excluido_em IS NULL AND status='ativo' AND id IN ({','.join('?' * len(ids))})", ids)}
        if len(nomes) != len(ids):
            return voltar(url, erro="Escolha um aluno ativo.")
        if not local:
            return voltar(url, erro="Escolha o local.")
    with con:
        definir_horario(con, dia, hora, ids, local)
    quando = f"{DIAS_CURTO[dia]} {hora:02d}h"
    if not ids:
        return voltar(url, msg=f"{quando} ficou sem aula.")
    return voltar(url, msg=f"{quando}: {' + '.join(nomes_curtos([nomes[i] for i in ids]))} ({local}).")


def _plural(n, um, varios) -> str:
    return f"{n} {um if n == 1 else varios}"


@app.post("/agenda/copiar-grade")
def agenda_copiar_grade(semana: str = Form(""), todas: int = Form(0), aluno: str = Form(""), mes: str = Form(""), con=Depends(get_db)):
    """Passa os alunos da Grade para a Agenda, uma vez só e com a Agenda vazia: 1 linha por aluno em cada (dia, hora), até 2.
    Tudo vai num INSERT só (no Turso cada gravação é uma viagem pela rede)."""
    url = url_agenda(semana, todas, aluno, mes)
    if con.execute("SELECT 1 FROM agenda_fixos WHERE excluido_em IS NULL LIMIT 1").fetchone():
        return voltar(url, erro="A Agenda já tem horários fixos. Copiar da Grade só vale com a Agenda vazia.")
    ativos = con.execute("SELECT id, nome, local FROM clientes WHERE excluido_em IS NULL AND status='ativo' ORDER BY nome").fetchall()
    cadastro = {a["id"]: (a["local"] or "").strip() for a in ativos}
    horarios = {}    # (dia, hora) -> {cliente_id: [locais onde a Grade tem o aluno]}
    sem_aluno = {}   # nome escrito à mão que não bate com um só aluno ativo (sem repetir)
    achados = {}     # nome escrito à mão -> aluno (ou None): a Grade repete o mesmo nome em vários locais e tipos
    for g in con.execute("""SELECT dia, hora, local, cliente_id, TRIM(COALESCE(cliente_nome, '')) AS nome FROM grade_slots
                            WHERE status='ocupado' AND dia BETWEEN 1 AND 6 AND hora BETWEEN 5 AND 23
                            ORDER BY dia, hora, local, tipo_calculo, id"""):
        if g["cliente_id"]:
            cid = g["cliente_id"] if g["cliente_id"] in cadastro else None   # aluno inativo ou excluído não entra
        else:
            chave = _norm(g["nome"])
            if chave not in achados:
                achados[chave] = sugerir_cliente(g["nome"], ativos)
            cid = achados[chave]
            if cid is None and chave:
                sem_aluno.setdefault(chave, g["nome"])
        if cid is not None:
            horarios.setdefault((g["dia"], g["hora"]), {}).setdefault(cid, []).append(g["local"])
    linhas, de_fora = [], 0
    for (dia, hora), alunos in horarios.items():
        for cid in list(alunos)[:2]:   # a Agenda comporta 2 alunos por horário
            locs = alunos[cid]
            linhas.append((cid, dia, hora, cadastro[cid] if cadastro[cid] in locs else locs[0]))   # prefere o local do cadastro
        de_fora += max(len(alunos) - 2, 0)
    nomes = list(sem_aluno.values())
    if not linhas:
        dica = f" Nomes sem aluno no CRM: {', '.join(nomes[:5])}{'…' if len(nomes) > 5 else '.'}" if nomes else ""
        return voltar(url, erro="Não achei alunos ativos na Grade para copiar." + dica)
    with con:
        inserir_fixos(con, linhas)
    n = len({(l[1], l[2]) for l in linhas})   # um card por horário
    msg = (f"{_plural(n, 'horário copiado', 'horários copiados')} da Grade" + (f" ({_plural(len(linhas), 'aluno', 'alunos')})" if len(linhas) != n else "") + ".")
    if nomes:
        msg += f" {_plural(len(nomes), 'nome não reconhecido', 'nomes não reconhecidos')}: {', '.join(nomes[:5])}{'…' if len(nomes) > 5 else '.'}"
    if de_fora:
        msg += f" {_plural(de_fora, 'aluno ficou', 'alunos ficaram')} de fora (cabem 2 por horário)."
    return voltar(url, msg=msg)


def evento_ativo(con, eid):
    """Marcação ativa da Agenda (id, cliente_id, tipo, data) ou None."""
    return con.execute("SELECT id, cliente_id, tipo, data FROM cliente_eventos WHERE id=? AND excluido_em IS NULL", (eid,)).fetchone()


@app.post("/agenda/evento/{eid}/nao-repoe")
def agenda_evento_nao_repoe(eid: int, semana: str = Form(""), todas: int = Form(0), aluno: str = Form(""), mes: str = Form(""), con=Depends(get_db)):
    """Controle do aluno → "Não repõe": a desmarcação vira Cancelada (não repõe) e sai das reposições a fazer."""
    e = evento_ativo(con, eid)
    url = url_agenda(semana, todas, aluno or (e["cliente_id"] if e else ""), mes or (e["data"][:7] if e else ""))
    if not e or e["tipo"] != "desmarcou":
        return voltar(url, erro="Essa aula desmarcada não existe mais.")
    with con:
        con.execute("UPDATE cliente_eventos SET tipo='cancelada' WHERE id=? AND tipo='desmarcou' AND excluido_em IS NULL", (eid,))
    return voltar(url, msg=f"Aula de {data_br(e['data'])[:5]} agora é Cancelada (não repõe).")


@app.post("/agenda/evento/{eid}/excluir")
def agenda_evento_excluir(eid: int, semana: str = Form(""), todas: int = Form(0), aluno: str = Form(""), mes: str = Form(""), destino: str = Form(""),
                          con=Depends(get_db)):
    """Desfazer: manda a marcação (ou qualquer registro do histórico) para a lixeira. destino=ficha volta para a ficha do aluno."""
    e = evento_ativo(con, eid)
    url = url_agenda(semana, todas, aluno or (e["cliente_id"] if e else ""), mes or (e["data"][:7] if e else ""))
    if e and destino == "ficha":
        url = f"/clientes/{e['cliente_id']}"
    if not e:
        return voltar(url, erro="Esse registro não existe mais.")
    with con:
        con.execute("UPDATE cliente_eventos SET excluido_em=datetime('now','localtime') WHERE id=? AND excluido_em IS NULL", (eid,))
    return voltar(url, msg="Registro enviado para a lixeira (dá para restaurar em Dados).")


@app.post("/agenda/avulsa/{aid}/excluir")
def agenda_avulsa_excluir(aid: int, semana: str = Form(""), todas: int = Form(0), aluno: str = Form(""), mes: str = Form(""), con=Depends(get_db)):
    with con:
        con.execute("UPDATE agenda_avulsas SET excluido_em=datetime('now','localtime') WHERE id=?", (aid,))
    return voltar(url_agenda(semana, todas, aluno, mes), msg="Aula avulsa enviada para a lixeira (dá para restaurar em Dados).")


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


@app.get("/propostas/{pid}", response_class=HTMLResponse)
def proposta_ver(request: Request, pid: int, con=Depends(get_db)):
    p = con.execute("""SELECT p.*, COALESCE(c.nome, l.nome) AS para FROM propostas p
                       LEFT JOIN leads l ON l.id=p.lead_id LEFT JOIN clientes c ON c.id=p.cliente_id
                       WHERE p.id=? AND p.excluido_em IS NULL""", (pid,)).fetchone()
    if not p:
        return voltar("/simulador", erro="Proposta não encontrada.")
    return render(request, "proposta.html", con, prop=p)


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
    for c in con.execute("SELECT * FROM campanha_checkpoints WHERE excluido_em IS NULL ORDER BY prazo, id"):
        n, auto = None, "pendente"   # sem canal: só a resposta na mão
        if c["canal"]:
            # só cliente que chegou depois do início da fase do prazo: cliente antigo do canal não prova que a campanha funcionou
            fase = con.execute("""SELECT inicio FROM campanha_fases WHERE tipo='fase' AND inicio IS NOT NULL AND inicio<=?
                                  ORDER BY (fim>=?) DESC, inicio DESC LIMIT 1""", (c["prazo"], c["prazo"])).fetchone()
            n = con.execute("""SELECT COUNT(*) FROM clientes WHERE excluido_em IS NULL AND canal_origem=?
                               AND COALESCE(data_inicio, substr(criado_em,1,10)) BETWEEN ? AND ?""",
                            (c["canal"], fase["inicio"] if fase else "0000-00-00", c["prazo"])).fetchone()[0]
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


@app.post("/campanhas/checkpoint")
def campanha_checkpoint_add(pergunta: str = Form(...), prazo: str = Form(...), canal: str = Form(""), con=Depends(get_db)):
    try:
        prazo = dt.date.fromisoformat(prazo).isoformat()
    except ValueError:
        return voltar("/campanhas", erro="Prazo inválido. Escolha a data no calendário.")
    if not pergunta.strip():
        return voltar("/campanhas", erro="Escreva a pergunta do checkpoint.")
    with con:
        con.execute("INSERT INTO campanha_checkpoints (pergunta, canal, prazo) VALUES (?,?,?)", (pergunta.strip(), canal.strip(), prazo))
    return voltar("/campanhas", msg="Checkpoint incluído.")


@app.post("/campanhas/checkpoint/{cid}/excluir")
def campanha_checkpoint_excluir(cid: int, con=Depends(get_db)):
    with con:
        con.execute("UPDATE campanha_checkpoints SET excluido_em=datetime('now','localtime') WHERE id=?", (cid,))
    return voltar("/campanhas", msg="Checkpoint enviado para a lixeira (dá para restaurar em Dados).")


# =====================================================================
# 7. ROTINA SEMANAL + LISTA DE ESPERA
# =====================================================================
def semana_atual():
    y, w, _ = dt.date.today().isocalendar()
    return f"{y}-W{w:02d}"


def tarefas_rotina(con):
    return con.execute("SELECT * FROM rotina_tarefas WHERE excluido_em IS NULL ORDER BY ordem, id").fetchall()


def rotina_texto(t):
    return f"{DIAS[t['dia']]}: {t['texto']}" if t["dia"] else t["texto"]


@app.get("/rotina", response_class=HTMLResponse)
def rotina(request: Request, con=Depends(get_db)):
    sem = semana_atual()
    hoje = dt.date.today()
    tarefas = tarefas_rotina(con)
    if tarefas:
        with con:
            con.executemany("INSERT OR IGNORE INTO rotina_itens (semana, item) VALUES (?, ?)", [(sem, t["chave"]) for t in tarefas])
    feitos = {r["item"]: r for r in con.execute("SELECT * FROM rotina_itens WHERE semana=?", (sem,))}
    itens = [{"id": t["id"], "chave": t["chave"], "texto": rotina_texto(t), "feito": feitos[t["chave"]]["feito"],
              "data": feitos[t["chave"]]["data_feito"]} for t in tarefas]
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


@app.post("/rotina/tarefa")
def rotina_tarefa_add(texto: str = Form(...), dia: int = Form(0), con=Depends(get_db)):
    if not texto.strip():
        return voltar("/rotina", erro="Escreva a tarefa.")
    with con:
        con.execute("INSERT INTO rotina_tarefas (chave, texto, dia, ordem) VALUES (?,?,?, (SELECT COALESCE(MAX(ordem),0)+1 FROM rotina_tarefas))",
                    ("t" + secrets.token_hex(4), texto.strip(), dia if 1 <= dia <= 7 else None))
    return voltar("/rotina", msg="Tarefa incluída no checklist.")


@app.post("/rotina/tarefa/{tid}/excluir")
def rotina_tarefa_excluir(tid: int, con=Depends(get_db)):
    with con:
        t = con.execute("SELECT chave FROM rotina_tarefas WHERE id=?", (tid,)).fetchone()
        con.execute("UPDATE rotina_tarefas SET excluido_em=datetime('now','localtime') WHERE id=?", (tid,))
        if t:   # sai da semana atual; as semanas anteriores ficam como foram
            con.execute("DELETE FROM rotina_itens WHERE semana=? AND item=?", (semana_atual(), t["chave"]))
    return voltar("/rotina", msg="Tarefa enviada para a lixeira (dá para restaurar em Dados).")


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
# FINANCEIRO (livro-caixa, contas a pagar, recorrências)
# =====================================================================
RE_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _caminho_seguro(p) -> str:
    """Destino de volta aceito: caminho do próprio CRM ("/clientes/3"). Esquema, "//host" e barra invertida viram "" (vale o padrão da rota)."""
    p = (p or "").strip()
    return p if p.startswith("/") and not p.startswith("//") and "\\" not in p and p.isprintable() else ""


def _fin_voltar(volta, msg=None, erro=None):
    volta = volta.replace("\n", "").replace("\r", "")
    # volta que é um caminho completo (ex.: mensalidades, ficha do aluno) vale como está; senão é a query do livro-caixa
    return voltar(volta if volta.startswith("/financeiro/") or _caminho_seguro(volta) else "/financeiro?" + volta, msg, erro)


@app.get("/financeiro", response_class=HTMLResponse)
def financeiro_tela(request: Request, mes: str = "", escopo: str = "todos", conta: str = "", vencidas: int = 0, con=Depends(get_db)):
    h = dt.date.today().isoformat()
    mes = mes if RE_MES.match(mes) else mes_atual()
    escopo = escopo if escopo in ("PJ", "PF") else "todos"
    lista = ("PJ", "PF") if escopo == "todos" else (escopo,)
    qs = ",".join("?" * len(lista))
    lancs = [dict(r, status=financeiro.status(r, h)) for r in con.execute(
        f"SELECT * FROM lancamentos WHERE excluido_em IS NULL AND substr(data,1,7)=? AND escopo IN ({qs}) ORDER BY data, id", (mes, *lista))]
    # PJ e PF juntos: o salário (Retirada da PJ + Salário na PF) é só transferência e não entra nas somas
    transf = [l for l in lancs if escopo == "todos" and ((l["escopo"] == "PJ" and l["tipo"] == "saida" and l["categoria"] == financeiro.RETIRADA)
                                                         or (l["escopo"] == "PF" and l["tipo"] == "entrada" and l["categoria"] == "Salário"))]
    # empréstimo da PJ (e a devolução) também não é receita nem custo: fica fora das somas, com o valor avisado
    empr = [l for l in lancs if l["escopo"] == "PJ" and l["categoria"] in (financeiro.EMPRESTIMO, financeiro.DEVOLUCAO)]
    transf_ids = {l["id"] for l in transf}
    fora_ids = transf_ids | {l["id"] for l in empr}
    entradas = round(sum(l["valor"] for l in lancs if l["tipo"] == "entrada" and l["id"] not in fora_ids), 2)
    saidas = round(sum(l["valor"] for l in lancs if l["tipo"] == "saida" and l["id"] not in fora_ids), 2)
    emprestado = round(sum(l["valor"] for l in empr if l["tipo"] == "entrada"), 2)
    devolvido = round(sum(l["valor"] for l in empr if l["tipo"] == "saida"), 2)
    # A receber: as entradas em aberto do mês (as saídas em aberto ficam só na lista Contas a pagar)
    pend = [p for p in financeiro.pendencias(con, mes, h) if p["escopo"] in lista and p["tipo"] == "entrada"]
    for p in pend:
        p["dias"] = (dt.date.fromisoformat(h) - dt.date.fromisoformat(p["data"])).days if p["status"] == "atrasado" else 0
    # ?vencidas=1 (link do alerta): a mesma lista, só com as contas que o alerta conta (de qualquer mês)
    so = {financeiro.chave_conta(p) for p in contas_vencendo(con, h)} if vencidas else None
    contas = financeiro.contas_a_pagar(con, h, so=so)
    parecidas = [s for s in financeiro.saidas_parecidas(con) if s["escopo"] in lista]
    # recorrência em aberto cuja conta parece já ter sido lançada à mão naquele mês: etiqueta "talvez já pago"
    talvez = {(c["id"], s["data"][:7]) for s in parecidas for c in s["candidatos"] if not c["ja_baixada"]}
    for p in contas["itens"]:
        p["talvez_pago"] = p["origem"] == "recorrencia" and (p["id"], p["competencia"]) in talvez
    repetidos = financeiro.duplicados(con)
    bancos = financeiro.conferencia_contas(con, repetidos)
    conta = conta if conta in db.lista(con, "lista_contas") else ""
    tabela = [l for l in lancs if l["conta"] == conta] if conta else lancs   # filtro só do livro-caixa: as somas do mês ficam como estão
    recs = con.execute(f"SELECT * FROM recorrencias WHERE excluido_em IS NULL AND escopo IN ({qs}) ORDER BY escopo, dia_vencimento, descricao", lista).fetchall()
    clientes_ = con.execute("SELECT id, nome FROM clientes WHERE excluido_em IS NULL ORDER BY nome").fetchall()
    return render(request, "financeiro.html", con, mes=mes, escopo=escopo, conta=conta, lancs=tabela, entradas=entradas, saidas=saidas,
                  saldo=round(entradas - saidas, 2), transferencia=round(sum(l["valor"] for l in transf if l["tipo"] == "saida"), 2),
                  emprestado=emprestado, devolvido=devolvido, pend=pend, contas=contas, so_vencidas=bool(vencidas), recs=recs, clientes_=clientes_,
                  volta=f"mes={mes}&escopo={escopo}" + ("&vencidas=1" if vencidas else ""),   # pagou uma, continua vendo as outras
                  resumo=financeiro.saldos_resumo(con, h), saldos=financeiro.saldos_atuais(con), frentes=financeiro.FRENTES,
                  salario=financeiro.salario_mes(con, h[:7], h), imposto=financeiro.imposto_mes(con, h[:7], h),
                  das_txt=financeiro.texto_pct(financeiro.pct_das(con)), parecidas=parecidas,
                  n_conferir=len(repetidos) + len(parecidas) + len(financeiro.recorrencias_retirada(con)) + sum(not b["bate"] for b in bancos),
                  recs_todas=con.execute("SELECT * FROM recorrencias WHERE excluido_em IS NULL ORDER BY escopo, descricao").fetchall())


@app.get("/financeiro/previsao", response_class=HTMLResponse)
def financeiro_previsao(request: Request, con=Depends(get_db)):
    return render(request, "financeiro_previsao.html", con, prev=financeiro.previsao(con, dt.date.today().isoformat()))


def _ja_aconteceu(data: str) -> bool:
    """Data ISO válida e não no futuro: pagamento e saldo só valem para o que já aconteceu."""
    try:
        return dt.date.fromisoformat(data) <= dt.date.today()
    except (TypeError, ValueError):
        return False


@app.post("/financeiro/salario")
def financeiro_salario(mes: str = Form(...), pago_em: str = Form(...), volta: str = Form(""), con=Depends(get_db)):
    if not _ja_aconteceu(pago_em):
        return _fin_voltar(volta, erro="Confira a data do pagamento: não pode ser no futuro.")
    if not RE_MES.match(mes):
        return _fin_voltar(volta, erro="Mês inválido.")
    try:
        financeiro.pagar_salario(con, mes, pago_em)
    except ValueError as e:
        return _fin_voltar(volta, erro=str(e))
    return _fin_voltar(volta, msg="Salário pago: saída na PJ e entrada na PF lançadas. Faça a transferência no banco.")


@app.post("/financeiro/saldos")
async def financeiro_saldos(request: Request, con=Depends(get_db)):
    """Foto semanal dos saldos: uma linha por conta (conta_i, saldo_i, frente_i). Saldo vazio = não mexe naquela conta."""
    f = await request.form()
    volta = f.get("volta", "")
    data = f.get("data") or dt.date.today().isoformat()
    valores, frentes = {}, {}
    contas = set(db.lista(con, "lista_contas"))
    if not _ja_aconteceu(data):   # foto no futuro venceria todas as outras e esconderia o que for pago até lá
        return _fin_voltar(volta, erro="Confira a data dos saldos: não pode ser no futuro.")
    try:
        for k, conta in f.items():
            if not k.startswith("conta_") or conta not in contas:
                continue
            i = k[6:]
            frentes[conta] = f.get(f"frente_{i}", "")
            if (f.get(f"saldo_{i}") or "").strip():
                v = _num_br(f[f"saldo_{i}"].replace("−", "-"))   # saldo pode ser negativo (cheque especial)
                if not math.isfinite(v):
                    raise ValueError
                valores[conta] = v
    except ValueError:
        return _fin_voltar(volta, erro="Confira a data e os valores dos saldos.")
    n = financeiro.salvar_saldos(con, data, valores, frentes)
    return _fin_voltar(volta, msg=f"Saldos salvos ({n} conta{'s' if n != 1 else ''})." if n else "Frentes das contas salvas.")


def _fin_valor(f):
    """Valor positivo com 2 casas, ou ValueError em português."""
    if f.get("escopo") not in ("PF", "PJ"):
        raise ValueError("Escolha PF ou PJ.")
    try:
        valor = round(_num_br(f.get("valor")), 2)
    except ValueError:
        raise ValueError("Valor inválido.") from None
    if not math.isfinite(valor) or valor <= 0:
        raise ValueError("O valor precisa ser maior que zero.")
    return valor


@app.post("/financeiro/lancamento")
async def financeiro_lancamento(request: Request, con=Depends(get_db)):
    f = dict((await request.form()).items())
    volta = _caminho_seguro(f.get("voltar")) or f.get("volta", "")   # "voltar" (ex.: ficha do aluno) manda; inseguro cai no "volta"
    try:
        valor = _fin_valor(f)
        if f.get("tipo") not in ("entrada", "saida") or not f.get("categoria"):
            raise ValueError("Escolha o tipo e a categoria.")
        pago_em = f.get("pago_em") or None
        try:
            dt.date.fromisoformat(f.get("data", ""))
            if pago_em:
                dt.date.fromisoformat(pago_em)
            cliente_id, parcela_num, parcela_total, lid = (int(f[k]) if f.get(k) else None for k in ("cliente_id", "parcela_num", "parcela_total", "id"))
        except ValueError:
            raise ValueError("Confira as datas e os números.") from None
        if pago_em and not _ja_aconteceu(pago_em):
            raise ValueError("\"Pago em\" não pode ser no futuro: deixe vazio e dê baixa no dia em que pagar.")
        if parcela_num is not None and parcela_num < 1 or parcela_total is not None and parcela_total < 1:
            raise ValueError("Parcela e total começam em 1.")
        if parcela_num and not parcela_total:
            raise ValueError("Informe também \"De quantas\" parcelas.")
        if parcela_num and parcela_num > parcela_total:
            raise ValueError(f"Parcela {parcela_num} de {parcela_total} não existe: o número não pode passar do total.")
        try:
            rec_id = int(f["recorrencia_id"]) if f.get("recorrencia_id") else None
        except ValueError:
            raise ValueError("Conta recorrente inválida.") from None
        rec = None
        if rec_id:
            if f["tipo"] != "saida":
                raise ValueError("Só saída pode ser uma conta recorrente.")
            rec = con.execute("SELECT * FROM recorrencias WHERE id=? AND excluido_em IS NULL", (rec_id,)).fetchone()
            if rec is None:
                raise ValueError("Conta recorrente não encontrada.")
            if rec["escopo"] != f["escopo"]:
                raise ValueError(f"{rec['descricao']} é da {rec['escopo']} e este lançamento é da {f['escopo']}.")
    except ValueError as e:
        return _fin_voltar(volta, erro=str(e))
    campos = [f["escopo"], f["tipo"], f["data"], pago_em, valor, f["categoria"], f.get("descricao") or None, f.get("contraparte") or None,
              cliente_id, f.get("conta") or None, f.get("forma") or None, parcela_num, parcela_total]
    # competência: o mês da data; ao editar uma baixa já ligada à mesma conta, fica a competência dela (mexer na data não troca de mês)
    competencia = f["data"][:7] if rec_id else None
    if rec_id and lid:
        atual = con.execute("SELECT recorrencia_id, competencia FROM lancamentos WHERE id=?", (lid,)).fetchone()
        if atual and atual["recorrencia_id"] == rec_id and atual["competencia"]:
            competencia = atual["competencia"]
    aberta, parcial, aviso = None, None, ""
    if not lid and cliente_id and pago_em and f["escopo"] == "PJ" and f["tipo"] == "entrada":
        # o aluno já tem essa entrada lançada em aberto no mês: dar baixa nela em vez de criar outra (senão conta duas vezes)
        aberta = con.execute("""SELECT id FROM lancamentos WHERE cliente_id=? AND escopo='PJ' AND tipo='entrada' AND pago_em IS NULL
                                AND excluido_em IS NULL AND ROUND(valor, 2)=? AND substr(data,1,7)=? ORDER BY data, id LIMIT 1""",
                             (cliente_id, valor, f["data"][:7])).fetchone()
        if not aberta:   # pagamento de outro valor: dá baixa total na 1ª entrada em aberto do mês, com o valor realmente recebido
            parcial = con.execute("""SELECT id, valor FROM lancamentos WHERE cliente_id=? AND escopo='PJ' AND tipo='entrada' AND pago_em IS NULL
                                     AND excluido_em IS NULL AND substr(data,1,7)=? ORDER BY data, id LIMIT 1""",
                                  (cliente_id, f["data"][:7])).fetchone()
    try:
        with con:
            if rec_id:
                financeiro.liberar_vaga(con, rec_id, competencia, lid)   # ValueError amigável se o mês já foi baixado
            if aberta:
                lid, aviso = aberta["id"], "Esse valor já estava lançado em aberto para o aluno: dei baixa nele, sem criar outro. "
                con.execute("UPDATE lancamentos SET pago_em=?, conta=COALESCE(?, conta), forma=COALESCE(?, forma) WHERE id=?",
                            (pago_em, f.get("conta") or None, f.get("forma") or None, lid))
            elif parcial:
                lid = parcial["id"]
                aviso = f"Baixa total: a mensalidade em aberto de {financeiro.moeda_br(parcial['valor'])} foi quitada com {financeiro.moeda_br(valor)}. "
                con.execute("UPDATE lancamentos SET pago_em=?, valor=?, conta=COALESCE(?, conta), forma=COALESCE(?, forma) WHERE id=?",
                            (pago_em, valor, f.get("conta") or None, f.get("forma") or None, lid))
            elif lid:
                con.execute("""UPDATE lancamentos SET escopo=?, tipo=?, data=?, pago_em=?, valor=?, categoria=?, descricao=?, contraparte=?,
                               cliente_id=?, conta=?, forma=?, parcela_num=?, parcela_total=? WHERE id=?""", (*campos, lid))
                if rec_id:
                    con.execute("UPDATE lancamentos SET recorrencia_id=?, competencia=?, sem_recorrencia=NULL WHERE id=?", (rec_id, competencia, lid))
                elif not con.execute("""SELECT 1 FROM lancamentos l JOIN recorrencias r ON r.id = l.recorrencia_id
                                        WHERE l.id=? AND r.excluido_em IS NOT NULL""", (lid,)).fetchone():
                    # campo vazio = "não é conta recorrente"; só mantém a ligação se a conta recorrente está na lixeira (não aparece na lista)
                    con.execute("UPDATE lancamentos SET recorrencia_id=NULL, competencia=NULL WHERE id=?", (lid,))
            else:
                lid = con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, contraparte, cliente_id,
                                     conta, forma, parcela_num, parcela_total, recorrencia_id, competencia)
                                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (*campos, rec_id, competencia)).lastrowid
    except ValueError as e:
        return _fin_voltar(volta, erro=str(e))
    except sqlite3.IntegrityError:
        return _fin_voltar(volta, erro="Não foi possível salvar: confira o aluno e os campos.")
    if f["escopo"] == "PJ" and f["tipo"] == "entrada" and pago_em and cliente_id:
        with con:
            if desconto := financeiro.usar_credito(con, lid):   # o crédito do aluno foi descontado neste pagamento
                aviso += f"Crédito de {financeiro.moeda_br(desconto)} descontado. "
    if f["escopo"] == "PJ" and f["tipo"] == "entrada" and f["categoria"] == financeiro.EMPRESTIMO:
        return _fin_voltar(volta, msg=(aviso or "Lançamento salvo. ") + "É empréstimo: não paga DAS e não conta como receita.")
    if f["escopo"] == "PJ" and f["tipo"] == "entrada" and pago_em:
        # dinheiro que entrou na PJ: diz na hora quanto separar para o imposto
        if separe := financeiro.aviso_imposto(con, valor):
            return _fin_voltar(volta, msg=(aviso or "Lançamento salvo. ") + separe)
    return _fin_voltar(volta, msg=aviso.strip() or "Lançamento salvo.")


@app.post("/financeiro/lancamento/{lid}/baixa")
def financeiro_baixa(lid: int, volta: str = Form(""), voltar_a: str = Form("", alias="voltar"), pago_em: str = Form(""), conta: str = Form(""),
                     con=Depends(get_db)):
    """Dar baixa: 'pago_em' (vazio = hoje; não pode ser futura) e 'conta' (vazio mantém a do lançamento)."""
    volta = _caminho_seguro(voltar_a) or volta
    pago_em = pago_em.strip() or dt.date.today().isoformat()
    if not _ja_aconteceu(pago_em):
        return _fin_voltar(volta, erro="Confira a data do pagamento: não pode ser no futuro.")
    with con:
        con.execute("UPDATE lancamentos SET pago_em=?, conta=COALESCE(NULLIF(?, ''), conta) WHERE id=? AND pago_em IS NULL", (pago_em, conta.strip(), lid))
        desconto = financeiro.usar_credito(con, lid)   # pagamento de aluno: desconta o crédito dele
    return _fin_voltar(volta, msg="Baixa registrada." + (f" Crédito de {financeiro.moeda_br(desconto)} descontado." if desconto else ""))


@app.post("/financeiro/lancamento/{lid}/aluno")
def financeiro_ligar_aluno(lid: int, cliente_id: int = Form(0), volta: str = Form(""), con=Depends(get_db)):
    """Liga uma entrada PJ sem aluno à ficha: mensalidades e previsão passam a contar o pagamento dele uma vez só."""
    c = con.execute("SELECT nome FROM clientes WHERE id=? AND excluido_em IS NULL", (cliente_id,)).fetchone()
    if c is None:
        return _fin_voltar(volta, erro="Escolha o aluno.")
    with con:
        con.execute("UPDATE lancamentos SET cliente_id=? WHERE id=? AND cliente_id IS NULL AND excluido_em IS NULL", (cliente_id, lid))
    return _fin_voltar(volta, msg=f"Entrada ligada a {c['nome']}.")


@app.post("/financeiro/lancamento/{lid}/emprestimo")
def financeiro_emprestimo(lid: int, volta: str = Form(""), con=Depends(get_db)):
    """'É empréstimo': a entrada PJ deixa de ser receita (DAS, lucro, mensalidades) e passa a pagar as contas da PJ."""
    with con:
        n = con.execute("""UPDATE lancamentos SET categoria=?, cliente_id=NULL WHERE id=? AND escopo='PJ' AND tipo='entrada'
                           AND excluido_em IS NULL""", (financeiro.EMPRESTIMO, lid)).rowcount
    if not n:
        return _fin_voltar(volta, erro="Só uma entrada da PJ pode ser empréstimo.")
    return _fin_voltar(volta, msg="Marcado como empréstimo: não paga DAS e não conta como receita nem como mensalidade.")


@app.get("/financeiro/conferir", response_class=HTMLResponse)
def financeiro_conferir(request: Request, con=Depends(get_db)):
    """Tudo que o app acha que precisa de um olhar: lançamentos repetidos, contas lançadas à mão que parecem recorrentes e saldos que não batem."""
    repetidos = financeiro.duplicados(con)
    return render(request, "financeiro_conferir.html", con, repetidos=repetidos, parecidas=financeiro.saidas_parecidas(con),
                  recs_retirada=financeiro.recorrencias_retirada(con), bancos=financeiro.conferencia_contas(con, repetidos), volta="/financeiro/conferir")


@app.post("/financeiro/conferir/ok")
def financeiro_conferir_ok(conta: str = Form(""), volta: str = Form("/financeiro/conferir"), con=Depends(get_db)):
    """'Está certo': esconde a diferença desta conta até você digitar um saldo novo."""
    try:
        financeiro.marcar_conferido(con, conta)
    except ValueError as e:
        return _fin_voltar(volta, erro=str(e))
    return _fin_voltar(volta, msg=f"Combinado: {conta} fica sem aviso até você digitar um saldo novo.")


@app.get("/financeiro/linha-do-tempo", response_class=HTMLResponse)
def financeiro_linha_do_tempo(request: Request, dias: int = 30, conta: str = "", con=Depends(get_db)):
    """O que aconteceu nas contas nos últimos 7, 30 ou 90 dias, dia a dia."""
    dias = dias if dias in (7, 30, 90) else 30
    conta = conta if conta in db.lista(con, "lista_contas") else None
    return render(request, "financeiro_linha.html", con, linha=financeiro.linha_do_tempo(con, dt.date.today().isoformat(), dias, conta))


@app.post("/financeiro/duplicados/manter")
def financeiro_duplicados_manter(manter: int = Form(...), ids: list[int] = Form(...), volta: str = Form(""), con=Depends(get_db)):
    """'Manter só este': os outros do grupo vão para a lixeira (restaurável em Dados)."""
    outros = [i for i in dict.fromkeys(ids) if i != manter]
    if manter not in ids or not outros:
        return _fin_voltar(volta, erro="Escolha qual lançamento manter.")
    with con:
        n = sum(con.execute("UPDATE lancamentos SET excluido_em=datetime('now','localtime') WHERE id=? AND excluido_em IS NULL", (i,)).rowcount
                for i in outros)
    return _fin_voltar(volta, msg=f"{n} lançamento{'s' if n != 1 else ''} repetido{'s' if n != 1 else ''} enviado{'s' if n != 1 else ''} para a lixeira (restaurável em Dados).")


@app.post("/financeiro/duplicados/nao-repetido")
def financeiro_duplicados_nao_repetido(ids: list[int] = Form(...), volta: str = Form(""), con=Depends(get_db)):
    """'Não é repetido': guarda os pares do grupo e a tela Conferir não avisa deles de novo."""
    ids = sorted(set(ids))
    with con:
        con.executemany("INSERT OR IGNORE INTO duplicados_ok (a, b) VALUES (?, ?)", [(a, b) for k, a in enumerate(ids) for b in ids[k + 1:]])
    return _fin_voltar(volta, msg="Combinado: esses lançamentos não são repetidos.")


@app.post("/financeiro/lancamento/{lid}/recorrencia")
def financeiro_ligar_recorrencia(lid: int, recorrencia_id: int = Form(0), volta: str = Form(""), con=Depends(get_db)):
    """Liga uma saída lançada à mão à conta recorrente: ela sai de A pagar e do Saldo livre, e 'Pagar' não lança de novo."""
    try:
        nome = financeiro.ligar_recorrencia(con, lid, recorrencia_id)
    except ValueError as e:
        return _fin_voltar(volta, erro=str(e))
    return _fin_voltar(volta, msg=f"Lançamento ligado a {nome}.")


@app.post("/financeiro/lancamento/{lid}/nao-recorrente")
def financeiro_nao_recorrente(lid: int, volta: str = Form(""), con=Depends(get_db)):
    """'Não é a mesma conta': o lançamento sai da lista de contas parecidas com recorrentes."""
    with con:
        con.execute("UPDATE lancamentos SET sem_recorrencia=1 WHERE id=? AND recorrencia_id IS NULL AND excluido_em IS NULL", (lid,))
    return _fin_voltar(volta, msg="Combinado: este lançamento não é uma conta recorrente.")


@app.post("/financeiro/lancamento/{lid}/excluir")
def financeiro_lancamento_excluir(lid: int, volta: str = Form(""), con=Depends(get_db)):
    with con:
        con.execute("UPDATE lancamentos SET excluido_em=datetime('now','localtime') WHERE id=?", (lid,))
    return _fin_voltar(volta, msg="Lançamento enviado para a lixeira (restaurável em Dados).")


@app.post("/financeiro/recorrencia")
async def financeiro_recorrencia(request: Request, con=Depends(get_db)):
    f = dict((await request.form()).items())
    volta = f.get("volta", "")
    fim = f.get("fim") or None
    try:
        valor = _fin_valor(f)
        if not f.get("descricao", "").strip() or not f.get("categoria"):
            raise ValueError("Informe a descrição e a categoria.")
        if f["categoria"] == financeiro.RETIRADA:
            raise ValueError("Salário não é conta recorrente: configure o valor em Configurações e use \"Pagar salário\".")
        if not (RE_MES.match(f.get("inicio", "")) and (fim is None or RE_MES.match(fim))):
            raise ValueError("Confira o início e o fim (mês/ano).")
        if not 1 <= int(f.get("dia_vencimento") or 0) <= 31:
            raise ValueError("O dia de vencimento vai de 1 a 31.")
        rid = int(f["id"]) if f.get("id") else None
        if f.get("prioridade", "") not in ("", "1", "-1"):
            raise ValueError("Prioridade inválida.")
    except ValueError as e:
        return _fin_voltar(volta, erro=str(e))
    campos = [f["escopo"], f["descricao"].strip(), f["categoria"], valor, int(f["dia_vencimento"]), 1 if f.get("fixo") == "1" else 0,
              f.get("conta") or None, f["inicio"], fim, int(f["prioridade"]) if f.get("prioridade") else None]
    try:
        with con:
            if rid:
                con.execute("""UPDATE recorrencias SET escopo=?, descricao=?, categoria=?, valor=?, dia_vencimento=?, fixo=?, conta=?, inicio=?,
                               fim=?, prioridade=? WHERE id=?""", (*campos, rid))
            else:
                con.execute("""INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, conta, inicio, fim, prioridade)
                               VALUES (?,?,?,?,?,?,?,?,?,?)""", campos)
    except sqlite3.IntegrityError:
        return _fin_voltar(volta, erro="Não foi possível salvar: confira os campos.")
    return _fin_voltar(volta, msg="Conta recorrente salva.")


@app.post("/financeiro/recorrencia/{rid}/excluir")
def financeiro_recorrencia_excluir(rid: int, volta: str = Form(""), con=Depends(get_db)):
    with con:
        con.execute("UPDATE recorrencias SET excluido_em=datetime('now','localtime') WHERE id=?", (rid,))
    return _fin_voltar(volta, msg="Conta recorrente enviada para a lixeira (restaurável em Dados).")


@app.post("/financeiro/recorrencia/pular")
def financeiro_recorrencia_pular(rid: int = Form(...), competencia: str = Form(...), volta: str = Form(""), con=Depends(get_db)):
    """Excluir uma conta a pagar, "Só este mês": a competência sai da lista, dos totais e do alerta; os outros meses continuam."""
    try:
        nome = financeiro.pular_mes(con, rid, competencia)
    except ValueError as e:
        return _fin_voltar(volta, erro=str(e))
    return _fin_voltar(volta, msg=f"{nome} de {competencia[5:7]}/{competencia[:4]} saiu da lista. Nos outros meses ela continua.")


@app.post("/financeiro/recorrencia/encerrar")
def financeiro_recorrencia_encerrar(rid: int = Form(...), competencia: str = Form(...), volta: str = Form(""), con=Depends(get_db)):
    """Excluir uma conta a pagar, "Encerrar a conta": nenhum mês dessa competência em diante volta."""
    try:
        nome, lixeira = financeiro.encerrar_recorrencia(con, rid, competencia)
    except ValueError as e:
        return _fin_voltar(volta, erro=str(e))
    return _fin_voltar(volta, msg=f"{nome} encerrada" + (" e enviada para a lixeira (restaurável em Dados)." if lixeira
                                                          else ": os meses já pagos ficam no livro-caixa."))


@app.post("/financeiro/recorrencia/baixa")
def financeiro_recorrencia_baixa(rid: int = Form(...), competencia: str = Form(...), valor: str = Form(...), pago_em: str = Form(...),
                                 volta: str = Form(""), con=Depends(get_db)):
    try:
        if not _ja_aconteceu(pago_em):
            raise ValueError("Confira a data do pagamento: não pode ser no futuro.")
        if not RE_MES.match(competencia):
            raise ValueError("Competência inválida.")
        financeiro.baixar_recorrencia(con, rid, competencia, _num_br(valor), pago_em)
    except ValueError as e:
        return _fin_voltar(volta, erro=str(e))
    return _fin_voltar(volta, msg="Conta paga.")


def _fin_mes(mes):
    return mes if RE_MES.match(mes) else mes_atual()


@app.get("/financeiro/mensalidades", response_class=HTMLResponse)
def financeiro_mensalidades(request: Request, mes: str = "", con=Depends(get_db)):
    mes = _fin_mes(mes)
    itens = financeiro.mensalidades(con, mes)
    alunos_estado = alu.estado(con)   # a situação de cada aluno (hoje) vem do algoritmo central
    previsto, recebido = (round(sum(i[k] for i in itens), 2) for k in ("previsto", "recebido"))
    # falta: só quem ainda não pagou nada no mês (qualquer pagamento quita o mês)
    falta = round(sum(i["previsto"] for i in itens if not i["quitado"]), 2)
    alunos = con.execute("SELECT id, nome FROM clientes WHERE excluido_em IS NULL ORDER BY status != 'ativo', nome").fetchall()
    sem_aluno = [dict(e, sugestao=financeiro.sugerir_aluno(f"{e['descricao'] or ''} {e['contraparte'] or ''}", alunos),
                      parece_emprestimo=financeiro.parece_emprestimo(f"{e['descricao'] or ''} {e['contraparte'] or ''}"))
                 for e in financeiro.entradas_sem_aluno(con, mes)]
    return render(request, "financeiro_mensalidades.html", con, mes=mes, itens=itens, previsto=previsto, recebido=recebido, falta=falta,
                  sem_aluno=sem_aluno, alunos=alunos, volta=f"/financeiro/mensalidades?mes={mes}",
                  estados=alunos_estado)


@app.get("/financeiro/painel", response_class=HTMLResponse)
def financeiro_painel(request: Request, mes: str = "", con=Depends(get_db)):
    mes = _fin_mes(mes)
    n = int(mes[:4]) * 12 + int(mes[5:]) - 1
    meses = [f"{(n - i) // 12}-{(n - i) % 12 + 1:02d}" for i in range(11, -1, -1)]
    serie = [financeiro.resumo_mes(con, x) for x in meses]
    maximo = max([s["receita"] for s in serie] + [s["custos_fixos"] + s["custos_variaveis"] for s in serie] + [abs(s["lucro"]) for s in serie] + [1])
    das_pct = f"{db.parametros(con, 'imposto').get('DAS', 0.06) * 100:g}".replace(".", ",")
    return render(request, "financeiro_painel.html", con, mes=mes, r=serie[-1], serie=serie, maximo=maximo, das_pct=das_pct,
                  salario=financeiro.salario_mes(con, mes, dt.date.today().isoformat()), colchao=financeiro.colchao(con, mes))


# =====================================================================
# ASSISTENTE (chat com o Claude: lê e edita financeiro, contas e tarefas)
# =====================================================================
def _custo_br(v) -> str:
    if not v:
        return ""
    return "< US$ 0,01" if v < 0.01 else f"≈ US$ {v:.2f}".replace(".", ",")


@app.get("/assistente", response_class=HTMLResponse)
def assistente_tela(request: Request, c: int = 0, con=Depends(get_db)):
    conversa = assistente.conversa(con, c) if c else None
    if c and conversa is None:
        return voltar("/assistente", erro="Conversa não encontrada.")
    return render(request, "assistente.html", con, conversa=conversa, conversas=assistente.conversas(con), info=assistente.info(),
                  turnos=assistente.para_tela(con, conversa["id"]) if conversa else [],
                  custo=_custo_br(assistente.custo_conversa(con, conversa["id"])) if conversa else "")


@app.get("/assistente/conversa/{cid}", response_class=HTMLResponse)
def assistente_mensagens(request: Request, cid: int, con=Depends(get_db)):
    """Só as mensagens (a tela troca o que chegou aos pedaços pela versão formatada)."""
    if assistente.conversa(con, cid) is None:
        return HTMLResponse("", status_code=404)
    return templates.TemplateResponse(request, "_assistente_mensagens.html", {"turnos": assistente.para_tela(con, cid)},
                                      headers={"X-Custo": quote(_custo_br(assistente.custo_conversa(con, cid)))})


@app.post("/assistente/enviar")
def assistente_enviar(texto: str = Form(""), conversa: str = Form("")):
    """Resposta aos pedaços (text/event-stream): cada linha 'data:' é um evento JSON. O banco só fica aberto nos momentos
    de ler e gravar, nunca enquanto o modelo pensa (no modo Turso a conexão é uma só)."""
    def eventos():
        if db.nuvem.ativo():
            db.nuvem.sincronizar_se_velho(db.DB_PATH)   # traz o que foi lançado no outro aparelho
        cid = None
        with closing(assistente.responder(texto, int(conversa) if conversa.isdigit() else None)) as fluxo:
            for ev in fluxo:
                atualizar.registrar_uso()   # resposta longa também é uso: a atualização automática não reinicia no meio
                if ev["tipo"] == "vivo":   # modelo pensando em silêncio: comentário só para a conexão não cair
                    yield ": vivo\n\n"
                    continue
                cid = ev["id"] if ev["tipo"] == "conversa" else cid
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'tipo': 'fim', 'id': cid})}\n\n"
    return StreamingResponse(eventos(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/assistente/{cid}/excluir")
def assistente_excluir(cid: int, con=Depends(get_db)):
    assistente.excluir_conversa(con, cid)
    return voltar("/assistente", msg="Conversa enviada para a lixeira (dá para restaurar em Dados).")


# =====================================================================
# CONFIGURAÇÕES + IMPORTAR
# =====================================================================
GRUPOS_CONFIG = [("imposto", "Imposto (DAS)", "pct"), ("taxa_pagamento", "Taxas por forma de pagamento", "pct"),
                 ("margem_minima", "Margem mínima por serviço", "pct"), ("taxa_cia", "Taxa da CIA por pessoa (R$) e máximo de pessoas", "num"),
                 ("grupo_multiplicador", "Multiplicador de preço por nº de pessoas", "num"),
                 ("grupo_mao_obra_extra", "Mão de obra extra por nº de pessoas", "pct"), ("metas", "Metas do painel", "num"),
                 ("mao_obra_aula", "Mão de obra por aula (tipo|qtd)", "num"), ("lead_parado_dias", "Limite de dias parado por etapa", "num"),
                 ("funil_chance", "Chance de fechar por etapa do funil", "pct"),
                 ("fiscal", "Fiscal: salário mínimo (R$), pró-labore e INSS (frações, ex.: 0,28 = 28%)", "num"),
                 ("salario", "Salário fixo da PJ para a PF: valor (R$ por mês; 0 = desligado) e dia do pagamento", "num"),
                 ("colchao", "Reserva: meta em meses de custo fixo (0 = sem meta)", "num"),
                 ("impacto_curto", "Fila de pagamento: o quanto atrasar atrapalha agora (0 a 40; quanto maior, mais cedo na fila)", "num"),
                 ("impacto_juros", "Fila de pagamento: juros e multa por mês de atraso (quanto maior, mais cedo na fila)", "pct"),
                 ("cobranca", "Cobrança de aluno atrasado: multa (uma vez) e juros ao mês, proporcional aos dias. "
                              "Só cobre se estiver no contrato; pelo Código do Consumidor a multa vai até 2%", "pct")]


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
    msgs = con.execute("SELECT id, chave, valor_texto FROM parametros WHERE grupo='msg_whatsapp' ORDER BY ordem").fetchall()
    return render(request, "configuracoes.html", con, grupos=grupos, msgs=msgs, listas_cfg=listas_, precos=precos_, ultima=ultima,
                  planilha=str(db.PLANILHA), planilha_existe=db.PLANILHA.exists(), assistente=assistente.info())


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
            elif k.startswith("t_"):
                con.execute("UPDATE parametros SET valor_texto=? WHERE id=? AND grupo='msg_whatsapp'", (v, int(k[2:])))
    return voltar("/configuracoes", msg="Parâmetros salvos.")


@app.post("/configuracoes/assistente")
def configuracoes_assistente(chave: str = Form(""), con=Depends(get_db)):
    chave = chave.strip()
    if not chave.startswith("sk-ant-") or len(chave) < 20:
        return voltar("/configuracoes", erro="Chave inválida: ela começa com sk-ant- e é bem mais longa. Copie de novo em console.anthropic.com.")
    assistente.salvar_chave(con, chave)
    return voltar("/configuracoes", msg="Chave salva: o Assistente está ligado.")


@app.post("/configuracoes/assistente/remover")
def configuracoes_assistente_remover(con=Depends(get_db)):
    assistente.remover_chave(con)
    return voltar("/configuracoes", msg="Chave do Assistente removida.")


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
           ("cliente_eventos", "Evento de cliente", "(SELECT nome FROM clientes WHERE clientes.id=cliente_eventos.cliente_id) || ' — ' || "
            "CASE tipo WHEN 'aula' THEN 'aula feita' WHEN 'falta' THEN 'faltou' WHEN 'cancelada' THEN 'cancelada (não repõe)' WHEN 'credito' THEN 'crédito' WHEN 'brinde' THEN 'presente' ELSE tipo END || ' ' || data || "
            "COALESCE(' — ' || descricao, '')"), ("lista_espera", "Lista de espera", "nome"),
           ("gastos_marketing", "Gasto de marketing", "canal"), ("campanha_itens", "Item de campanha", "texto"),
           ("campanha_checkpoints", "Checkpoint", "pergunta"), ("rotina_tarefas", "Tarefa da rotina", "texto"),
           ("lancamentos", "Lançamento", "COALESCE(descricao, categoria)"), ("recorrencias", "Conta recorrente", "descricao"),
           ("assistente_conversas", "Conversa do assistente", "titulo"),
           ("agenda_avulsas", "Aula avulsa", "(SELECT nome FROM clientes WHERE clientes.id=agenda_avulsas.cliente_id) || ' ' || data"),
           ("agenda_fixos", "Horário fixo", "(SELECT nome FROM clientes WHERE clientes.id=agenda_fixos.cliente_id) || ' — ' || "
            "CASE dia WHEN 1 THEN 'Seg' WHEN 2 THEN 'Ter' WHEN 3 THEN 'Qua' WHEN 4 THEN 'Qui' WHEN 5 THEN 'Sex' WHEN 6 THEN 'Sáb' ELSE dia END || ' ' || "
            "substr('0' || hora, -2) || 'h (' || local || ')'")]


@app.post("/encerrar", response_class=HTMLResponse)
def encerrar(request: Request):
    # no Render, desligar só faria o CRM sumir para todos; pelo túnel, o celular derrubaria o PC sem ninguém lá para religar
    if not acesso.pode_encerrar(request):
        return HTMLResponse("Indisponível pela internet: o CRM só pode ser encerrado no próprio PC.", status_code=404)
    try:
        vigia.DESLIGADO.parent.mkdir(exist_ok=True)
        vigia.DESLIGADO.write_text("desligado pelo botao Encerrar\n", encoding="utf-8")   # avisa o vigia para não religar
    except OSError as e:
        print(f"AVISO: não consegui marcar o desligamento ({e}); o vigia pode religar o CRM.", flush=True)
    # o servidor roda sem janela (iniciar-crm.bat); SIGINT faz o uvicorn desligar com calma, depois de responder
    threading.Timer(0.5, signal.raise_signal, (signal.SIGINT,)).start()
    return HTMLResponse("<!doctype html><meta charset='utf-8'><title>CRM encerrado</title>"
                        "<body style='font-family:system-ui;padding:40px;background:#E8F0FA;color:#0F2A52'>"
                        "<h1>CRM encerrado.</h1><p>Pode fechar esta aba. Para abrir de novo, use o atalho da Área de Trabalho.</p>")


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
                  banco=str(db.DB_PATH), erro_backup=erro_backup, nuvem=db.nuvem, atualizacao=atualizar.status)


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
    fixo = None
    if tabela == "agenda_fixos":   # cabem 2 alunos por horário, sem repetir
        fixo = con.execute("""SELECT f.dia, f.hora, f.local, f.cliente_id, c.nome FROM agenda_fixos f JOIN clientes c ON c.id=f.cliente_id
                              WHERE f.id=?""", (rid,)).fetchone()
        if fixo:
            quem = {r["cliente_id"] for r in fixos_do_horario(con, fixo["dia"], fixo["hora"])}
            if fixo["cliente_id"] not in quem and len(quem) >= 2:
                return voltar("/dados", erro=f"{DIAS_CURTO[fixo['dia']]} {fixo['hora']:02d}h já tem 2 alunos. Tire um deles antes de restaurar.")
            if fixo["cliente_id"] in quem:
                return voltar("/dados", erro=f"{fixo['nome']} já está no horário {DIAS_CURTO[fixo['dia']]} {fixo['hora']:02d}h.")
    if tabela == "cliente_eventos":   # uma aula só tem uma marcação: restaurar não pode duplicar a que está valendo
        ev = con.execute(f"SELECT cliente_id, data, hora FROM cliente_eventos WHERE id=? AND tipo IN ({TIPOS_MARCA})", (rid,)).fetchone()
        if ev and any(ev["hora"] is None or r["hora"] is None or r["hora"] == ev["hora"] for r in con.execute(
                f"SELECT hora FROM cliente_eventos WHERE cliente_id=? AND data=? AND id != ? AND excluido_em IS NULL AND tipo IN ({TIPOS_MARCA})",
                (ev["cliente_id"], ev["data"], rid))):
            return voltar("/dados", erro="Essa aula já tem outra marcação. Desfaça a que está valendo na Agenda antes de restaurar.")
    if tabela == "cliente_eventos":   # 1 presente por indicado: restaurar não pode duplicar o que está valendo
        if con.execute("""SELECT 1 FROM cliente_eventos b JOIN cliente_eventos o ON o.indicado_id = b.indicado_id AND o.tipo='brinde'
                          AND o.excluido_em IS NULL AND o.id != b.id WHERE b.id=? AND b.tipo='brinde'""", (rid,)).fetchone():
            return voltar("/dados", erro="Esse indicado já tem o presente registrado. Exclua o que está valendo antes de restaurar.")
    with con:
        con.execute(f"UPDATE {tabela} SET excluido_em=NULL WHERE id=?", (rid,))
        if fixo:   # a Agenda avisa a Grade, como ao salvar
            grade_ocupar(con, fixo["cliente_id"], fixo["nome"], fixo["dia"], fixo["local"], fixo["hora"])
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
