"""Gera, com o CRM em Python, o que o Worker usa para conferir que faz igual (rodar da raiz: python worker/paridade/gerar.py).

- worker/migrations/0001_inicial.sql: esquema de um banco novo do Python (tabelas e índices, mesma ordem).
- worker/test/dados/semente.sql: dados que o Python grava num banco novo (parâmetros, listas, campanha, rotina).
- worker/test/paridade/*.json: casos entrada -> saída das regras de cálculo, para os testes TS exigirem o mesmo resultado.

Só para desenvolvimento: sai junto com o Python na última fase; os JSON ficam.
"""
import json
import random
import sqlite3
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
WORKER = RAIZ / "worker"

from app import db  # noqa: E402


def banco_novo() -> Path:
    pasta = Path(tempfile.mkdtemp())
    db.DB_PATH, db.BACKUP_DIR = pasta / "crm.db", pasta / "backups"
    db.iniciar_banco()
    return db.DB_PATH


def literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def esquema_e_semente(caminho: Path) -> None:
    con = sqlite3.connect(caminho)
    objs = con.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY rowid").fetchall()
    ddl = [s + ";" for t, _, s in objs if t == "table"] + [s + ";" for t, _, s in objs if t != "table"]
    cab = "-- Gerado por worker/paridade/gerar.py a partir de um banco novo do CRM em Python (app/schema.sql + app/db.py). Não editar.\n"
    (WORKER / "migrations" / "0001_inicial.sql").write_text(cab + "\n".join(ddl) + "\n", encoding="utf-8")
    linhas = []
    for (tabela,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY rowid"):
        cur = con.execute(f'SELECT * FROM "{tabela}" ORDER BY rowid')
        cols = ", ".join(d[0] for d in cur.description)
        for r in cur:
            linhas.append(f'INSERT INTO "{tabela}" ({cols}) VALUES ({", ".join(literal(v) for v in r)});')
    (WORKER / "test" / "dados" / "semente.sql").write_text(cab + "\n".join(linhas) + "\n", encoding="utf-8")
    con.close()


def salvar(nome: str, casos) -> None:
    (WORKER / "test" / "paridade" / f"{nome}.json").write_text(json.dumps(casos, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")


def casos_arred():
    rnd = random.Random(7)
    fixos = [2.675, 1.005, 0.125, 0.375, 0.625, -2.5, 2.5, 0.5, 1.5, -0.125, 1234.565, 0.285, 1.115, 10.005, 99.995,
             -0.001, 0.0, 1e-9, 123456789.125, 0.045, 3.14159, 2.0000000001]
    casos = [[x, n, round(x, n)] for x in fixos for n in (0, 1, 2)]
    for _ in range(3000):   # somas e porcentagens como as do financeiro
        x = sum(rnd.randint(1, 500000) / 100 for _ in range(rnd.randint(1, 6))) * rnd.choice((1, 0.06, 0.155, 1 / 3, 0.1133, -1))
        casos.append([x, 2, round(x, 2)])
    return casos


HOJE = "2026-11-19"


def semear_financeiro(caminho: Path, fator: int = 3) -> None:
    """Dados sintéticos do financeiro (fator x o volume real), sempre iguais: alunos, recorrências, lançamentos,
    pagamentos de vários meses e lançamentos repetidos de propósito."""
    import datetime as dt
    rnd = random.Random(1)
    hoje = dt.date.fromisoformat(HOJE)
    con = sqlite3.connect(caminho)
    with con:
        cids = []
        for i in range(15 * fator):
            cid = con.execute("INSERT INTO clientes (nome, telefone, local, tipo_servico, plano, valor, forma_pagamento, status, data_inicio, data_renovacao)"
                              " VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (f"Aluno {i} Ção", f"1199999{i:04d}", "CIA", "Mensalidade", "2x", 600 + i * 7.5, "PIX", "ativo" if i % 9 else "inativo",
                               (hoje - dt.timedelta(days=200 + i)).isoformat(), (hoje + dt.timedelta(days=i % 40 - 10)).isoformat())).lastrowid
            cids.append(cid)
        for i in range(10 * fator):
            con.execute("INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, conta, inicio) VALUES (?,?,?,?,?,?,?,?)",
                        (("PF", "PJ")[i % 2], f"Conta {i}", "Outros", 50 + i, 1 + i % 28, i % 3 != 0, "Contabilizei Bank",
                         (hoje - dt.timedelta(days=400)).strftime("%Y-%m")))
        lids = []
        for i in range(400 * fator):
            d = hoje - dt.timedelta(days=rnd.randint(-60, 540))
            tipo = rnd.choice(("entrada", "saida", "saida"))
            cli = rnd.choice(cids) if tipo == "entrada" and rnd.random() < 0.8 else None
            valor = round(rnd.uniform(10, 2000), 2) if not cli else rnd.choice((600.0, 1200.0, 1800.0, 300.0, 615.0))
            lids.append(con.execute(
                "INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, contraparte, cliente_id, conta, forma, meses)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("PJ" if cli else rnd.choice(("PF", "PJ")), tipo, d.isoformat(), d.isoformat() if d <= hoje else None, valor,
                 "Mensalidade (Aulas Presenciais)" if tipo == "entrada" else rnd.choice(("Alimentação", "Outros", "Retirada")),
                 rnd.choice((f"Desc {i % 70}", "", None, "Mercado São João")), rnd.choice((f"Pessoa {i % 50}", None, "")), cli,
                 rnd.choice(("Contabilizei Bank", None)), "PIX", rnd.choice((None, None, None, 3, 6)) if cli else None)).lastrowid)
        for i in range(30 * fator):   # repetidos: cópia de um lançamento, mesma data ou 1-2 dias depois
            orig = con.execute("SELECT escopo, tipo, data, pago_em, valor, categoria, descricao, contraparte, cliente_id, conta, forma FROM lancamentos WHERE id=?",
                               (rnd.choice(lids),)).fetchone()
            desloc = rnd.choice((0, 0, 1, 2, 5))
            d = (dt.date.fromisoformat(orig[2]) + dt.timedelta(days=desloc)).isoformat()
            con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, contraparte, cliente_id, conta, forma)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (orig[0], orig[1], d, d if orig[3] else None, *orig[4:]))
        con.execute("INSERT INTO duplicados_ok (a, b) SELECT MIN(id), MAX(id) FROM lancamentos WHERE id IN (1, 2)")
    con.close()


def dump(caminho: Path, tabelas: list[str], arquivo: str) -> None:
    con = sqlite3.connect(caminho)
    linhas = []
    for tabela in tabelas:
        cur = con.execute(f'SELECT * FROM "{tabela}" ORDER BY rowid')
        cols = ", ".join(d[0] for d in cur.description)
        valores = [f'({", ".join(literal(v) for v in r)})' for r in cur]
        for i in range(0, len(valores), 100):   # uma linha por lote de 100 (limite do D1: 100 KB por comando)
            linhas.append(f'INSERT INTO "{tabela}" ({cols}) VALUES ' + ",".join(valores[i:i + 100]) + ";")
    (WORKER / "test" / "dados" / arquivo).write_text("\n".join(linhas) + "\n", encoding="utf-8")
    con.close()


def casos_financeiro_prototipo():
    """Cenário do teste de CPU: o Worker carrega o mesmo banco e tem de achar os mesmos números."""
    import datetime as dt
    from app import financeiro, relogio
    relogio._utc = lambda: dt.datetime(2026, 11, 19, 15, 0, tzinfo=dt.timezone.utc)
    caminho = banco_novo()
    semear_financeiro(caminho)
    dump(caminho, ["clientes", "recorrencias", "lancamentos", "duplicados_ok"], "cenario-financeiro.sql")
    con = db.conectar(caminho)
    meses = [financeiro.somar_meses(HOJE[:7], k) for k in range(-3, 3)]
    ja = sorted({x["id"] for x in financeiro.saidas_parecidas(con)})
    saida = {
        "cobertura": {m: {str(k): v for k, v in financeiro._cobertura_adiantada(con, m).items()} for m in meses},
        "ja_avisadas": ja,
        "duplicados": financeiro.duplicados(con),
        "somar_meses": [[m, n, financeiro.somar_meses(m, n)] for m in ("2026-01", "2026-12", "0001-01", "2024-02") for n in (-25, -13, -1, 0, 1, 11, 12, 25)],
        "vencimento": [[d, m, financeiro.vencimento(d, m)] for d in (1, 28, 29, 30, 31) for m in ("2024-02", "2026-02", "2026-04", "2026-12")],
        "meses_do_pagamento": [[v, val, e, financeiro.meses_do_pagamento(v, val, e)] for v in (0, 539.99, 540, 600, 1199, 1800.5, None)
                               for val in (0, 600, None) for e in (None, 0, 3)],
        "palavras": [[t, financeiro._palavras(t)] for t in ("Giuliana Souza", "  São João, nº 12 ", "", None, "ÇÃO-ção_x")],
    }
    salvar("financeiro-prototipo", saida)
    con.close()


def casos_formato():
    from app import main
    rnd = random.Random(11)
    valores = [None, 0, -0.0, 0.004, -0.004, 0.005, 1234.5, -1234.565, 1e6, 999.995, 12.0, -7.25] + \
        [rnd.uniform(-50000, 50000) for _ in range(300)]
    datas = [None, "", "2026-11-19", "2026-11-19 10:20:30", "2026-02-30", "texto", "2026-1-5"]
    tels = [None, "", "(11) 99999-0000", "1133334444", "5511999990000", 11999990000]
    textos = ["Oi {nome}, vence {data}: {valor} via {pix}. {vantagem} {dias}", "a+b/c?d=é ç&x", "", None]
    return {
        "moeda": [[v, main.moeda(v)] for v in valores],
        "data_br": [[d, main.data_br(d)] for d in datas],
        "pct": [[v, c, main.pct(v, c)] for v in [None, 0.155, 0.1, 1 / 3, 0.0125, 2.5] for c in (0, 1, 2)],
        "num": [[v, c, main.num(v, c)] for v in [None, 1.25, 2.675, 10, 1 / 3] for c in (0, 1, 2)],
        "wa": [[t, x, main.wa(t, x)] for t in tels for x in textos[:3]],
        "preencher": [[x, "Ana", "05/12", {"dias": 3, "valor": "R$ 10,00"}, main.preencher(x, "Ana", "05/12", {"dias": 3, "valor": "R$ 10,00"})]
                      for x in textos[:3]] + [["{valor}{pix}", "", "", {}, main.preencher("{valor}{pix}")]],
    }


def html_base(caminho_banco: Path) -> None:
    """O layout (base.html) de uma tela simples, num banco novo, sem alertas: o Worker tem de gerar o mesmo HTML."""
    from starlette.requests import Request
    from app import main, relogio
    relogio._utc = lambda: __import__("datetime").datetime(2026, 11, 19, 15, 0, tzinfo=__import__("datetime").timezone.utc)
    con = db.conectar(caminho_banco)
    escopo = {"type": "http", "method": "GET", "path": "/clientes", "query_string": b"msg=Salvo&erro=Falhou",
              "headers": [(b"host", b"crm.vfitcoachapp.com")], "scheme": "https", "server": ("crm.vfitcoachapp.com", 443)}
    req = Request(escopo)
    ctx = dict(request=req, msg="Salvo", erro="Falhou", listas={k: db.lista(con, k) for k in db.LISTAS_INICIAIS}, alertas=[],
               modelos=db.parametros(con, "msg_whatsapp"), dados_msg=main.dados_mensagem(con), locais_ref=main.loc.referencias(con))
    tpl = main.templates.env.from_string('{% extends "base.html" %}{% block conteudo %}<p>conteúdo da tela</p>{% endblock %}')
    (WORKER / "test" / "paridade" / "base.html").write_text(tpl.render(ctx), encoding="utf-8")
    con.close()


if __name__ == "__main__":
    caminho = banco_novo()
    esquema_e_semente(caminho)
    salvar("arred", casos_arred())
    salvar("formato", casos_formato())
    html_base(caminho)
    casos_financeiro_prototipo()
    print("paridade gerada em worker/")
