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


CARIMBO = "2026-11-19 12:00:00"


def fixar_carimbos(caminho: Path) -> None:
    """criado_em/atualizado_em gravados pelo SQL na hora da geração viram uma data fixa: gerar de novo dá os mesmos arquivos."""
    con = sqlite3.connect(caminho)
    with con:
        for (tabela,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            cols = {r[1] for r in con.execute(f'PRAGMA table_info("{tabela}")')}
            for col in ("criado_em", "atualizado_em"):
                if col in cols:
                    # o que o SQL carimbou agora (hoje de verdade); datas escritas no cenário são anteriores
                    con.execute(f"UPDATE \"{tabela}\" SET {col}=? WHERE {col} >= date('now', '-2 days')", (CARIMBO,))
    con.close()


def literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def esquema_e_semente(caminho: Path) -> None:
    fixar_carimbos(caminho)
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
    fixar_carimbos(caminho)


def dump(caminho: Path, tabelas: list[str], arquivo: str) -> None:
    con = sqlite3.connect(caminho)
    linhas = []
    for tabela in tabelas:   # o cenário substitui a tabela inteira (a semente pode já ter linhas nela)
        linhas.append(f'DELETE FROM "{tabela}";')
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


def jsonavel(x):
    """Estruturas do Python em JSON: chave numérica vira texto, tupla vira lista, sqlite3.Row vira dict."""
    if isinstance(x, sqlite3.Row) or type(x).__name__ == "Linha":
        x = dict(x)
    if isinstance(x, dict):
        return {str(k): jsonavel(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [jsonavel(v) for v in (sorted(x) if isinstance(x, set) else x)]
    return x


def semear_motor(caminho: Path) -> None:
    """Cenário do motor de preços: locais com custos, alunos de todos os tipos, horários na Agenda (com dupla e repetido),
    contas fixas que entram ou não no rateio, gastos da PF e receita da PJ de 14 meses (RBT12)."""
    con = sqlite3.connect(caminho)
    with con:
        con.execute("UPDATE parametros SET valor=5 WHERE grupo='cia_deslocamento' AND chave='reais_por_aula'")
        con.execute("UPDATE parametros SET valor=20 WHERE grupo='cia_deslocamento' AND chave='minutos_por_aula'")
        con.execute("UPDATE parametros SET valor=300 WHERE grupo='cia_mensal' AND chave='taxa_mensal'")
        con.execute("UPDATE parametros SET valor=40 WHERE grupo='cia_mensal' AND chave='aulas_mes'")
        con.executemany("INSERT INTO locais_custos (local, taxa_aula, taxa_pessoa_extra, max_pessoas, deslocamento, tempo_deslocamento, taxa_mensal, aulas_mes)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        [("Smart Fit", 20, 10, 2, 8, 25, 0, 0), ("Box Centro", 0, 0, 0, 0, 15, 400, 30)])
        alunos = [  # nome, tipo, plano, local, status, valor, pessoas, forma
            ("Ana", "Mensalidade", "Mensalidade 2x", "CIA", "ativo", 640, 1, "PIX"),
            ("Bruno", "Mensalidade", "Mensalidade 3x", "Smart Fit", "ativo", 900, 2, "Cartão 1x"),
            ("Carla", "Pacote de Aulas", "Pacote 8", "CIA", "ativo", 700, 1, "PIX"),
            ("Davi", "Pacote de Aulas", "Pacote de 12 aulas", "Box Centro", "ativo", 1100, 1, "PIX"),
            ("Eva", "Consultoria Online", "", None, "ativo", 250, 1, "PIX"),
            ("Fábio", "Consultoria Híbrida", "", "CIA", "ativo", 400, 1, "PIX"),
            ("Gil", "Avaliação Física", "", "Smart Fit", "ativo", 150, 1, "PIX"),
            ("Hana", "", "Pacote 4", "CIA", "ativo", 300, 1, "PIX"),
            ("Ivo", "Mensalidade", "Mensal", "CIA", "ativo", 500, 1, "PIX"),
            ("Juli", "Mensalidade", "Mensalidade 1x", "CIA", "inativo", 350, 1, "PIX"),
            ("Kai", "Mensalidade", "Mensalidade 2x", "CIA", "ativo", 620, 1, "PIX"),
        ]
        ids = {}
        for nome, tipo, plano, local, status, valor, pessoas, forma in alunos:
            ids[nome] = con.execute("INSERT INTO clientes (nome, tipo_servico, plano, local, status, valor, pessoas, forma_pagamento, data_inicio, data_renovacao)"
                                    " VALUES (?,?,?,?,?,?,?,?, '2026-03-01', '2026-12-05')",
                                    (nome, tipo, plano, local, status, valor, pessoas, forma)).lastrowid
        con.execute("UPDATE clientes SET excluido_em='2026-10-01' WHERE nome='Kai'")
        fixos = [("Ana", 1, 7, "CIA"), ("Ana", 4, 7, "CIA"), ("Ana", 1, 7, "CIA"), ("Bruno", 2, 18, "Smart Fit"), ("Bruno", 4, 18, "Smart Fit"),
                 ("Bruno", 6, 9, "Smart Fit"), ("Carla", 1, 7, "CIA"), ("Carla", 3, 8, "CIA"), ("Fábio", 5, 10, "CIA"), ("Juli", 2, 6, "CIA"),
                 ("Kai", 3, 6, "CIA"), ("Davi", 7, 10, "Box Centro"), ("Davi", 2, 4, "Box Centro")]
        for nome, dia, hora, local in fixos:
            con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?,?,?,?)", (ids[nome], dia, hora, local))
        con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, excluido_em) VALUES (?, 5, 12, 'CIA', '2026-11-01')", (ids["Carla"],))
        recs = [("PJ", "MFIT", "Software/Assinaturas", 99.9, 1, None), ("PJ", "Dropbox", "Software/Assinaturas", 50, 1, None),
                ("PJ", "Aluguel Box Centro", "Aluguel", 400, 1, None), ("PJ", "Créditos de aulas", "Outros", 800, 1, None),
                ("PJ", "DAS", "Impostos/Taxas", 300, 1, None), ("PJ", "Pró-labore", "Retirada", 3000, 1, None),
                ("PJ", "Internet", "Internet/Telefone", 120, 1, "2026-10"), ("PJ", "Variável", "Outros", 70, 0, None),
                ("PF", "Aluguel casa", "Moradia", 2000, 1, None), ("PJ", "Impostos", "Impostos/Taxas", 45, 1, None),
                ("PJ", "Contador", "Impostos/Taxas", 180, 1, None)]
        for escopo, desc, cat, valor, fixo, fim in recs:
            con.execute("INSERT INTO recorrencias (escopo, descricao, categoria, valor, dia_vencimento, fixo, inicio, fim) VALUES (?,?,?,?,10,?,'2025-01',?)",
                        (escopo, desc, cat, valor, fixo, fim))
        rnd = random.Random(5)
        for mes in ["2025-09", "2025-10", "2025-11", "2025-12"] + [f"2026-{m:02d}" for m in range(1, 12)]:
            for k in range(rnd.randint(2, 6)):
                v = round(rnd.uniform(300, 2500), 2)
                cat = "Empréstimo" if k == 5 else "Mensalidade (Aulas Presenciais)"
                con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria) VALUES ('PJ','entrada',?,?,?,?)",
                            (f"{mes}-1{k}", f"{mes}-1{k}", v, cat))
        for mes in ["2026-07", "2026-08", "2026-10", "2026-11"]:
            for k in range(3):
                con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria) VALUES ('PF','saida',?,?,?,'Alimentação')",
                            (f"{mes}-0{k + 1}", f"{mes}-0{k + 1}", round(rnd.uniform(200, 1500), 2)))
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria) VALUES ('PF','saida','2026-09-05', 999, 'Alimentação')")
    con.close()
    fixar_carimbos(caminho)


def casos_motor():
    import datetime as dt
    from app import contas_auto, financeiro, main, precos
    caminho = banco_novo()
    semear_motor(caminho)
    dump(caminho, ["parametros", "clientes", "locais_custos", "agenda_fixos", "recorrencias", "lancamentos"], "cenario-motor.sql")
    con = db.conectar(caminho)
    p = precos.carregar_parametros(con)
    locais = ["CIA", "Smart Fit", "Box Centro", None]
    calculos = []
    for tipo, qtd, freq in precos.PLANOS:
        for local in locais:
            base = precos.base_motor(tipo, qtd, freq, local)
            for pessoas in (1, 2, 3):
                for forma in ("PIX", "Cartão 1x", "Boleto"):
                    for final in (None, 300.0):
                        try:
                            r = precos.calcular(base, p, pessoas=pessoas, forma_pagamento=forma, preco_final=final, local=local, mult_horario=1.1)
                        except ValueError as e:
                            r = {"erro": str(e)}
                        calculos.append([tipo, qtd, freq, local, pessoas, forma, final, r])
    base_m = precos.base_motor("Mensalidade", 0, 2, "CIA")
    misto = [precos.calcular_misto([(base_m, 1.0, "CIA"), (precos.base_motor("Mensalidade", 0, 2, "Smart Fit"), 1.2, "Smart Fit")], p, 2, 0.05, "PIX"),
             precos.calcular_misto([(base_m, None, "Box Centro")], p, 1, 0, "Cartão 1x", None, (120.0, 40.0)),
             precos.calcular_misto([(base_m, 1.0, "CIA")], p, 1, 0, "PIX", None, (100.0, 30.0, 10.0, 2.5))]
    decomp = [[tipo, qtd, freq, local, precos.decompor(precos.base_motor(tipo, qtd, freq, local), p, local)]
              for tipo, qtd, freq in precos.PLANOS for local in locais[:3]]
    clientes = [dict(r) for r in con.execute("SELECT id, nome, tipo_servico, plano, local FROM clientes ORDER BY id")]
    textos = ["DAS", "das outubro", "Simples Nacional", "Pagamento DAS", "Imposto", "ÁDAS", "Darf", "dasx", "", None]
    saida = {
        "params": jsonavel(p),
        "trabalho": jsonavel(main.horas_trabalho_detalhe(con, p)),
        "fixos": jsonavel(main.fixos_atuais(con)),
        "das": {m: financeiro.das_competencia(con, m) for m in ["2025-08", "2025-09", "2025-10", "2026-03", "2026-11", "2026-12"]},
        "custo_pessoal": jsonavel(financeiro.custo_pessoal_medio(con, "2026-11")),
        "custos_fixos": financeiro.custos_fixos_rateio(con, "2026-11", list(p["locais"])),
        "calculos": jsonavel(calculos),
        "misto": misto,
        "decompor": jsonavel(decomp),
        "mult_horario": jsonavel(precos.mult_horario(con)),
        "base_cliente": jsonavel([[c, main.base_do_cliente(con, c), main.aulas_mes(c)] for c in clientes]),
        "texto_pct": [[x, financeiro.texto_pct(x)] for x in (0.06, 0.045, 0.0753125, 0.112, 0, 1.5, 0.12345678, 0.000001)],
        "cor_margem": [[m, mi, precos.cor_margem(m, mi)] for m in (None, -0.01, 0, 0.09, 0.1, 0.12, 0.15, 0.3) for mi in (0.15, 0.2)],
        "eh_das": [[d, c, financeiro.eh_das(d, c)] for d in textos for c in ("Impostos/Taxas", "DAS", "Outros", None)],
        "eh_cia": [[t, contas_auto.eh_cia(t), contas_auto.eh_local_cia(t)] for t in ("CIA", "Cia 111", "Crédito de aula", "créditos das aulas",
                                                                                   "Ciagym", "Ciática Studio", "CIA2", "111", "Academia", None)],
        "util": [[d, financeiro.util_anterior(d)] for d in ("2026-11-21", "2026-11-22", "2026-11-23", "2026-11-20")] +
                [[f"{dia}|{mes}", financeiro.vencimento_util(dia, mes)] for dia in (20, 31) for mes in ("2026-02", "2026-11", "2027-01")],
    }
    salvar("motor", jsonavel(saida))
    con.close()
    html_configuracoes(caminho)


def cliente_python_como_nuvem():
    """TestClient do CRM em Python com a cara da nuvem (como o Worker): sem Encerrar, com Sair, sem portaria no teste,
    e sem os alertas do topo (ainda não portados: entram com as regras de alunos e do financeiro)."""
    from fastapi.testclient import TestClient
    from app import acesso, main
    acesso.motivo_bloqueio = lambda *a, **k: None
    acesso.local = lambda *a, **k: False
    acesso.pode_encerrar = lambda *a, **k: False
    main.alertas = lambda con: []
    return TestClient(main.app, base_url="https://crm.vfitcoachapp.com")


def html_configuracoes(caminho: Path) -> None:
    """A tela Configurações no cenário do motor, com uma importação antiga e a chave do Assistente salva."""
    from app import assistente
    con = sqlite3.connect(caminho)
    with con:
        con.execute("INSERT INTO importacoes (data, arquivo, resumo) VALUES ('2026-10-02 09:15:00', 'Contabilidade.xlsx', 'ok')")
        con.execute("INSERT INTO segredos (chave, valor, atualizado_em) VALUES ('anthropic_api_key', 'sk-ant-teste-0000000000wxyz', '2026-11-01 10:00:00')")
        con.execute("UPDATE parametros SET valor_texto='chave@pix.com' WHERE grupo='msg_dados' AND chave='pix'")
    con.close()
    fixar_carimbos(caminho)
    dump(caminho, ["importacoes", "segredos", "parametros"], "cenario-config.sql")
    db.DB_PATH = caminho
    c2 = db.conectar(caminho)
    assistente.carregar_chave(c2)
    c2.close()
    http = cliente_python_como_nuvem()
    (WORKER / "test" / "paridade" / "configuracoes.html").write_text(http.get("/configuracoes").text, encoding="utf-8")


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


def congelar_relogio() -> None:
    import datetime as dt
    from app import relogio
    relogio._utc = lambda: dt.datetime(2026, 11, 19, 15, 0, tzinfo=dt.timezone.utc)


if __name__ == "__main__":
    congelar_relogio()
    caminho = banco_novo()
    esquema_e_semente(caminho)
    salvar("arred", casos_arred())
    salvar("formato", casos_formato())
    html_base(caminho)
    casos_financeiro_prototipo()
    casos_motor()
    print("paridade gerada em worker/")
