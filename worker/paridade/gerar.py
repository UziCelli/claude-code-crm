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


def semear_alunos(caminho: Path, n: int = 70) -> None:
    """Alunos sintéticos em todas as situações: vencido (com e sem crédito), vence logo, pagou sem aula, sem aula nem pagamento,
    sem aula recente, cadastro incompleto, em dia; pagamentos de vários meses, Renovação marcada pendente, mês pulado, créditos
    (usados ou não), diferença de multa e juros, aulas com bloqueio no meio. Sempre os mesmos (semente fixa)."""
    import datetime as dt
    rnd = random.Random(42)
    hoje = dt.date.fromisoformat(HOJE)
    d = lambda k: (hoje + dt.timedelta(days=k)).isoformat()   # noqa: E731
    con = sqlite3.connect(caminho)
    with con:
        con.execute("UPDATE parametros SET valor_texto='chave@pix.com' WHERE grupo='msg_dados' AND chave='pix'")
        con.execute("UPDATE parametros SET valor_texto='Victor Celli' WHERE grupo='msg_dados' AND chave='pix_nome'")
        con.execute("UPDATE parametros SET valor_texto='São Paulo' WHERE grupo='msg_dados' AND chave='pix_cidade'")
        tipos = ["Mensalidade"] * 6 + ["Pacote de Aulas", "Pacote de Aulas", "Consultoria Online", "Consultoria Híbrida", "Avaliação Física", ""]
        for i in range(n):
            tipo = rnd.choice(tipos)
            plano = {"Mensalidade": rnd.choice(["Mensalidade 2x", "Mensalidade 3x", "Mensalidade 1x", "Mensal"]),
                     "Pacote de Aulas": rnd.choice(["Pacote 8", "Pacote de 4 aulas"]), "": rnd.choice(["Pacote 4", ""])}.get(tipo, "")
            valor = rnd.choice([0, 300, 450.5, 600, 600, 615.33, 999.99])
            tel = rnd.choice(["11999990000", "(11) 98888-7777", "", None])
            inicio = rnd.choice([d(-rnd.randint(30, 400)), d(-rnd.randint(30, 400)), None, d(rnd.randint(1, 20)), "2026-02-30"])
            renov = rnd.choice([d(rnd.randint(-70, 45)) for _ in range(6)] + [None, "2026-02-30"])
            status = "ativo" if rnd.random() < 0.9 else "inativo"
            cid = con.execute("INSERT INTO clientes (nome, telefone, tipo_servico, plano, valor, status, data_inicio, data_renovacao, local)"
                              " VALUES (?,?,?,?,?,?,?,?, 'CIA')", (f"Aluno {i:02d} {rnd.choice(['Ána', 'Bê', 'Cid'])}", tel, tipo, plano, valor,
                                                                     status, inicio, renov)).lastrowid
            if rnd.random() < 0.15 and renov:
                con.execute("UPDATE clientes SET renovacao_em=? WHERE id=?", (d(-rnd.randint(5, 40)) + " 10:00:00", cid))
            if rnd.random() < 0.5:
                con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (?,?,?, 'CIA')", (cid, rnd.randint(1, 6), rnd.randint(6, 20)))
            densidade = rnd.choice([0, 0, 1, 2, 4, 8])
            for k in range(densidade * 4):
                con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, hora) VALUES (?, 'aula', ?, 7)", (cid, d(-rnd.randint(0, 130))))
            if rnd.random() < 0.15:
                con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'aula', ?)", (cid, d(-rnd.randint(140, 300))))
            # pagamentos mensais com falhas; alguns de vários meses; alguns em aberto
            if valor and renov and rnd.random() < 0.85:
                base = dt.date.fromisoformat(renov) if renov != "2026-02-30" else hoje
                for m in range(rnd.randint(0, 6)):
                    if rnd.random() < 0.2:
                        continue
                    data = (base - dt.timedelta(days=30 * m + rnd.randint(-8, 5))).isoformat()
                    meses = rnd.choice([None, None, None, None, 3])
                    v = rnd.choice([valor, valor, valor * 2, round(valor * 0.5, 2), round(valor * 0.95, 2)])
                    pago = data if (data <= HOJE and rnd.random() < 0.9) else None
                    lid = con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id, meses, criado_em)"
                                      " VALUES ('PJ','entrada',?,?,?, 'Mensalidade (Aulas Presenciais)', ?, ?, ?)",
                                      (data, pago, v, cid, meses, data + " 09:00:00")).lastrowid
                    if pago and rnd.random() < 0.08:
                        con.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, origem) VALUES ('PJ','entrada',?,?, 'Multa e juros', ?)",
                                    (data, round(rnd.uniform(5, 30), 2), f"MULTA:{lid}"))
            if rnd.random() < 0.2:
                con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data) VALUES (?, 'pagamento', ?)", (cid, d(-rnd.randint(0, 60))))
            if rnd.random() < 0.15 and renov and renov != "2026-02-30":
                con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, criado_em) VALUES (?, 'renovacao', ?, ?)",
                            (cid, d(rnd.randint(-40, 3)), d(-1) + " 08:00:00"))
            if rnd.random() < 0.15 and renov and renov != "2026-02-30":
                ate = rnd.choice([None, d(rnd.randint(-5, 40))])
                con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, ate) VALUES (?, 'pausa', ?, ?)", (cid, d(rnd.randint(-45, 2)), ate))
            if rnd.random() < 0.2:
                mes = (hoje - dt.timedelta(days=30 * rnd.randint(1, 3))).isoformat()[:7]
                usado = rnd.random() < 0.3
                con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, valor, usado_em) VALUES (?, 'credito', ?, ?, ?)",
                            (cid, mes + "-01", rnd.choice([120.0, 299.5, valor or 50.0]), d(-3) if usado else None))
    con.close()
    fixar_carimbos(caminho)


def semear_ofertas_indicacoes(caminho: Path) -> None:
    """Ofertas (ativa, pausada, vencida, com e sem prazo), respostas (enviada, aceitou com e sem prazo, recusou) e indicações."""
    con = sqlite3.connect(caminho)
    with con:
        ofertas = [("Treino em dupla", "2 aulas por semana com um amigo.", 600, 480, 3, None, 1),
                   ("Avaliação mensal", "avaliação física; plano ajustado", 500, 450, None, "2026-12-31", 1),
                   ("Pausada", "x", 300, 200, 2, None, 0), ("Vencida", "y", 300, 250, 1, "2026-10-01", 1)]
        for t, inc, vn, vo, m, ate, at in ofertas:
            con.execute("INSERT INTO ofertas (titulo, inclui, valor_normal, valor_oferta, meses_desconto, valida_ate, ativa) VALUES (?,?,?,?,?,?,?)",
                        (t, inc, vn, vo, m, ate, at))
        ids = [r[0] for r in con.execute("SELECT id FROM clientes WHERE status='ativo' AND excluido_em IS NULL ORDER BY id")]
        respostas = [(1, ids[0], "enviada", "2026-11-10", None, None), (1, ids[1], "aceitou", "2026-09-20", "2026-11-20", 600),
                     (1, ids[2], "recusou", "2026-11-01", None, None), (2, ids[3], "aceitou", "2026-10-10", None, 500),
                     (1, ids[4], "aceitou", "2026-08-01", "2026-11-01", 615.33)]
        for oid, cid, st, d, ate, antes in respostas:
            con.execute("INSERT INTO oferta_respostas (oferta_id, cliente_id, status, data, ate_desconto, valor_antes) VALUES (?,?,?,?,?,?)",
                        (oid, cid, st, d, ate, antes))
        con.execute("UPDATE clientes SET valor=480 WHERE id=?", (ids[1],))
        con.execute("UPDATE clientes SET valor=480 WHERE id=?", (ids[4],))
        for indicado, indicador in [(ids[5], ids[6]), (ids[7], ids[6]), (ids[8], ids[9]), (ids[10], ids[10])]:
            con.execute("UPDATE clientes SET indicado_por=?, canal_origem='Indicação' WHERE id=?", (indicador, indicado))
        con.execute("INSERT INTO cliente_eventos (cliente_id, tipo, data, descricao, indicado_id) VALUES (?, 'brinde', '2026-11-02', ?, ?)",
                    (ids[6], "Presente pela indicação de X: Camiseta", ids[7]))
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id) VALUES ('PJ','entrada','2026-11-03','2026-11-03', 600, 'Mensalidade (Aulas Presenciais)', ?)", (ids[5],))
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, cliente_id) VALUES ('PJ','entrada','2026-11-03','2026-11-03', 600, 'Mensalidade (Aulas Presenciais)', ?)", (ids[7],))
    con.close()
    fixar_carimbos(caminho)


def semear_leads(caminho: Path) -> None:
    """Leads em todas as etapas: atrasados, parados, com indicação, perdidos com motivo e um que já virou aluno."""
    con = sqlite3.connect(caminho)
    with con:
        ids = [r[0] for r in con.execute("SELECT id FROM clientes ORDER BY id LIMIT 3")]
        leads = [("Lia", "11911112222", "Instagram orgânico", "Mensalidade / CIA", "mandar mensagem", "2026-11-10", "lead", None, None, "2026-11-01", None),
                 ("Mel", None, "Indicação", "Pacote de Aulas / SmartFit", None, None, "lead", None, ids[0], "2026-10-01", None),
                 ("Nil", "11933334444", "Google", None, "marcar avaliação", "2026-11-25", "conversa", None, None, "2026-11-18", None),
                 ("Oto", "11955556666", "WhatsApp", "Mensalidade / Condomínio", None, None, "avaliacao", None, None, "2026-09-01", None),
                 ("Pri", "11977778888", "Stadami", None, None, None, "perdido", "Preço", None, "2026-10-10", None),
                 ("Quim", None, "Outro", None, None, None, "perdido", "  preço ", None, "2026-10-12", None),
                 ("Rui", "11999990001", "Indicação", "Mensalidade / CIA", None, None, "cliente", None, None, "2026-10-20", ids[1])]
        for nome, tel, canal, interesse, prox, dprox, etapa, motivo, ind, mud, cid in leads:
            con.execute("""INSERT INTO leads (nome, telefone, canal_origem, interesse, proxima_acao, data_proxima_acao, etapa, motivo_perda,
                           indicado_por, data_entrada, data_mudanca_etapa, cliente_id, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, ?)""",
                        (nome, tel, canal, interesse, prox, dprox, etapa, motivo, ind, mud, mud, cid, mud + " 10:00:00"))
        con.execute("INSERT INTO propostas (cliente_id, tipo_servico, qtd_aulas, local, forma_pagamento, preco_total, preco_pessoa, lucro, margem, status)"
                    " VALUES (?, 'Mensalidade', 8, 'CIA', 'PIX', 640, 640, 120, 0.1875, 'enviada')", (ids[0],))
    con.close()
    fixar_carimbos(caminho)


def normalizar_tabela(rows):
    """Linhas para comparar com o Worker: carimbo de agora (relógio do servidor) vira '<agora>'."""
    import datetime as dt
    hoje_real = dt.date.today()
    out = []
    for r in rows:
        linha = {}
        for k, v in r.items():
            if isinstance(v, str) and len(v) == 19 and v[10] == " " and v[:10] >= (hoje_real - dt.timedelta(days=2)).isoformat():
                v = "<agora>"
            linha[k] = v
        out.append(linha)
    return out


def telas_e_roteiro(caminho: Path, nome: str, urls: list, passos: list, tabelas: list) -> None:
    """Grava o HTML do Python de cada tela e o resultado de um roteiro de POSTs (status, Location e as tabelas no fim)."""
    import shutil
    db.DB_PATH = caminho
    http = cliente_python_como_nuvem()
    telas = {u: http.get(u, follow_redirects=False).text for u in urls}
    respostas = []
    for metodo, url, dados in passos:
        r = http.request(metodo, url, data=dados, follow_redirects=False)
        respostas.append([metodo, url, dados, r.status_code, r.headers.get("location")])
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    estado_final = {t: normalizar_tabela([dict(x) for x in con.execute(f'SELECT * FROM "{t}" ORDER BY rowid')]) for t in tabelas}
    con.close()
    salvar(nome, {"telas": telas, "respostas": respostas, "tabelas": estado_final})


def casos_clientes():
    from app import alunos
    caminho = banco_novo()
    semear_alunos(caminho)
    semear_ofertas_indicacoes(caminho)
    semear_leads(caminho)
    dump(caminho, ["parametros", "clientes", "agenda_fixos", "cliente_eventos", "lancamentos", "ofertas", "oferta_respostas", "leads", "propostas"],
         "cenario-clientes.sql")
    con = db.conectar(caminho)
    est = alunos.estado(con, HOJE)
    por_sit = {}
    for cid, e in est.items():
        por_sit.setdefault(e["situacao"], []).append(cid)
    ativos = sorted(est)
    inativo = con.execute("SELECT id FROM clientes WHERE status!='ativo' ORDER BY id LIMIT 1").fetchone()[0]
    difs = sorted(__import__("app").financeiro.diferencas(con))
    indicador = con.execute("SELECT indicado_por FROM clientes WHERE indicado_por IS NOT NULL ORDER BY id LIMIT 1").fetchone()[0]
    sem_tel = con.execute("SELECT id FROM clientes WHERE status='ativo' AND (telefone IS NULL OR telefone='') ORDER BY id LIMIT 1").fetchone()[0]
    con.close()
    fichas = sorted({*[v[0] for v in por_sit.values()], *[v[-1] for v in por_sit.values()], inativo, *difs[:2], indicador, ativos[0], ativos[1], ativos[4], sem_tel})
    lista_ids = ",".join(map(str, ativos[:40] + [inativo]))
    urls = ["/clientes", "/clientes?status=todos", "/clientes?status=inativo&busca=Aluno 1", "/clientes?status=pausado", "/clientes?busca=zzz",
            *[f"/clientes?ids={lista_ids}&motivo={m}" for m in ("cobrar", "sem-aula", "incompleto", "indicacao", "reativar", "dupla", "reajuste", "outro")],
            f"/clientes?ids={lista_ids}&motivo=upsell&oferta=1", f"/clientes?ids={lista_ids}&motivo=upsell&oferta=3", "/clientes?ids=x,0",
            "/clientes/novo", *[f"/clientes/{c}" for c in fichas], "/clientes/99999", "/leads", "/leads?destaque=3"]
    cobrar = por_sit["cobrar"][0]
    sem_aula = (por_sit.get("pago_sem_aula") or por_sit["sem_pagar_sem_aula"])[0]
    passos = [
        ("POST", "/clientes", {"nome": "Novo Ana", "telefone": "11912345678", "valor": "650,50", "status": "ativo", "tipo_servico": "Mensalidade",
                               "plano": "Mensalidade 2x", "local": "CIA", "pessoas": "2", "indicado_por": str(ativos[2]), "data_inicio": "2026-11-10"}),
        ("POST", "/clientes", {"nome": "Novo Ana", "telefone": "11912345678", "valor": "650,50"}),
        ("POST", "/clientes", {"nome": ""}),
        ("POST", "/clientes", {"nome": "Beto", "indicado_por": "abc"}),
        ("POST", f"/clientes/{ativos[0]}/wa/renovacao", {}), ("POST", f"/clientes/{cobrar}/wa/cobranca", {}),
        ("POST", f"/clientes/{ativos[1]}/wa/indicacao", {}), ("POST", f"/clientes/{ativos[1]}/wa/falta", {}),
        ("POST", f"/clientes/{ativos[0]}/wa/xyz", {}), ("POST", f"/clientes/{sem_tel}/wa/renovacao", {}), ("POST", "/clientes/99999/wa/renovacao", {}),
        ("POST", f"/clientes/{ativos[0]}/depoimento", {"descricao": "  Adorei  "}), ("POST", f"/clientes/{ativos[0]}/depoimento", {}),
        ("POST", f"/alunos/{sem_aula}/credito", {"valor": "", "mes": ""}), ("POST", f"/alunos/{sem_aula}/credito", {"valor": "", "mes": ""}),
        ("POST", f"/alunos/{ativos[3]}/credito", {"valor": "x"}), ("POST", f"/alunos/{ativos[3]}/credito", {"valor": "99999", "mes": "2026-08", "voltar": "/clientes"}),
        ("POST", f"/alunos/{ativos[3]}/credito", {"valor": "10", "mes": "2026-13"}),
        ("POST", f"/clientes/{ativos[5]}/consultoria", {"tipo_servico": "Consultoria Online", "voltar": f"/clientes?ids={lista_ids}&motivo=sem-aula"}),
        ("POST", f"/clientes/{ativos[5]}/consultoria", {"tipo_servico": "Mensalidade"}),
        ("POST", f"/clientes/{indicador}/indicacao/{ativos[5] if False else 0}/presente", {"o_que": "x"}),
        ("POST", f"/clientes/{ativos[0]}/oferta/1/enviar", {}), ("POST", f"/clientes/{ativos[0]}/oferta/1/aceitou", {"atualizar": "1"}),
        ("POST", f"/clientes/{ativos[2]}/oferta/2/recusou", {}), ("POST", f"/clientes/{ativos[1]}/oferta/1/encerrar-desconto", {}),
        ("POST", f"/clientes/{ativos[6]}/oferta/2/aceitou", {}), ("POST", f"/clientes/{ativos[6]}/oferta/3/enviar", {"voltar": "/clientes"}),
        ("POST", "/leads", {"nome": "Sol", "telefone": "", "canal_origem": "Google", "indicado_por": str(ativos[0]), "interesse": "Mensalidade / CIA"}),
        ("POST", "/leads", {"nome": "Tom", "canal_origem": "Google", "indicado_por": "999999"}),
        ("POST", "/leads/1", {"nome": "Lia B", "canal_origem": "Instagram Ads", "observacoes": "volta dia 30"}),
        ("POST", "/leads/1/etapa", {"etapa": "conversa"}), ("POST", "/leads/4/etapa", {"etapa": "cliente"}),
        ("POST", "/leads/3/etapa", {"etapa": "perdido", "motivo_perda": "Horário"}), ("POST", "/leads/3/etapa", {"etapa": "xx"}),
        ("POST", "/leads/2/excluir", {}), ("POST", f"/clientes/{ativos[7]}/excluir", {}),
    ]
    telas_e_roteiro(caminho, "clientes", urls, passos, ["clientes", "cliente_eventos", "leads", "lead_etapas_log", "oferta_respostas"])


def semear_agenda(caminho: Path) -> None:
    """Agenda e Grade sobre os alunos sintéticos: dupla, horário com 3 (limite reduzido depois), lixeira e linha repetida,
    vigência, 2 locais colados (aviso de deslocamento), aluno parado cujo horário encheu, e as células antigas da Grade
    (cópia com aluno, nome digitado, indisponível, multiplicadores). Horas 5 e 21-23: os horários sorteados usam 6 a 20."""
    semear_alunos(caminho)
    con = sqlite3.connect(caminho)
    antigo, ontem = "2026-09-01 10:00:00", "2026-11-18 10:00:00"
    with con:
        A = [r[0] for r in con.execute("SELECT id FROM clientes WHERE status='ativo' ORDER BY id")]
        I = [r[0] for r in con.execute("SELECT id FROM clientes WHERE status!='ativo' ORDER BY id")]
        con.execute("UPDATE agenda_fixos SET criado_em=?", (antigo,))
        con.execute("INSERT INTO locais_custos (local, tempo_deslocamento, taxa_aula) VALUES ('SmartFit', 25, 30)")
        con.execute("UPDATE parametros SET valor=0.8 WHERE grupo='mult_horario' AND chave='05'")
        con.execute("UPDATE parametros SET valor=1.2 WHERE grupo='mult_horario' AND chave='22'")
        fixos = [(A[0], 1, 5, "CIA", None, antigo, None), (A[1], 1, 5, "CIA", None, antigo, None),
                 (A[2], 2, 21, "SmartFit", "2026-10-01", antigo, None), (A[3], 2, 22, "CIA", None, ontem, None),
                 (A[4], 3, 5, "CIA", None, antigo, None), (A[5], 3, 5, "CIA", None, antigo, None), (A[6], 3, 5, "CIA", None, antigo, None),
                 (A[7], 4, 21, "CIA", None, antigo, "2026-11-01 10:00:00"), (A[8], 4, 21, "CIA", None, antigo, None),
                 (A[8], 4, 21, "CIA", None, antigo, None),
                 (I[0], 5, 5, "CIA", None, antigo, None), (A[9], 5, 5, "CIA", None, ontem, None), (A[10], 5, 5, "CIA", None, antigo, None),
                 (I[0], 5, 23, "SmartFit", None, antigo, None), (I[1], 6, 22, "Condomínio", "2026-10-10", antigo, None)]
        con.executemany("INSERT INTO agenda_fixos (cliente_id, dia, hora, local, vigente_de, criado_em, excluido_em) VALUES (?,?,?,?,?,?,?)", fixos)
        grade = []
        for t in ("Pacotes", "Mensalidades"):
            grade += [(t, 1, "CIA", 5, "ocupado", A[0], "Cópia A0", 0.8), (t, 5, "CIA", 5, "ocupado", I[0], "Cópia I0", 0.8),
                      (t, 3, "CIA", 22, "ocupado", None, "Fulano Digitado", 1.2), (t, 6, "SmartFit", 5, "indisponivel", None, None, 0.8),
                      (t, 2, "CIA", 21, "ocupado", A[3], "Cópia A3", 1.0), (t, 4, "CIA", 22, "ocupado", A[11], "Só na Grade", 1.2),
                      (t, 2, "SmartFit", 22, "livre", None, None, 1.2)]
        grade.append(("Pacotes", 5, "SmartFit", 23, "ocupado", I[0], "Cópia I0", 1.0))
        mult = {int(k): v for k, v in con.execute("SELECT chave, valor FROM parametros WHERE grupo='mult_horario'")}
        cheia = [(t, d, "CIA", h, "livre", None, None, mult.get(h, 1.0)) for t in ("Pacotes", "Mensalidades") for d in range(1, 7) for h in range(5, 24)]
        con.executemany("INSERT INTO grade_slots (tipo_calculo, dia, local, hora, status, cliente_id, cliente_nome, multiplicador)"
                        " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(tipo_calculo, dia, local, hora) DO UPDATE SET status=excluded.status,"
                        " cliente_id=excluded.cliente_id, cliente_nome=excluded.cliente_nome, multiplicador=excluded.multiplicador", cheia + grade)
    con.close()
    fixar_carimbos(caminho)


def casos_agenda_ficha():
    """Etapa 3a: as gravações da ficha que mexem na Agenda (horários, status, evento, pular mês, salvar)."""
    caminho = banco_novo()
    semear_agenda(caminho)
    dump(caminho, ["parametros", "clientes", "agenda_fixos", "grade_slots", "locais_custos", "cliente_eventos", "lancamentos"],
         "cenario-agenda.sql")
    con = sqlite3.connect(caminho)
    A = [r[0] for r in con.execute("SELECT id FROM clientes WHERE status='ativo' ORDER BY id")]
    I = [r[0] for r in con.execute("SELECT id FROM clientes WHERE status!='ativo' ORDER BY id")]
    sem_ren = con.execute("SELECT id FROM clientes WHERE status='ativo' AND data_renovacao IS NULL ORDER BY id").fetchone()[0]
    com_ren = [r[0] for r in con.execute("SELECT id FROM clientes WHERE status='ativo' AND data_renovacao LIKE '2026-1%' ORDER BY id")]
    ficha = {k: v for k, v in zip(["nome", "telefone", "local", "tipo_servico", "plano", "pessoas", "valor", "forma_pagamento", "status",
                                   "canal_origem", "data_inicio", "data_renovacao", "observacoes", "indicado_por"],
                                  con.execute("SELECT nome, telefone, local, tipo_servico, plano, pessoas, valor, forma_pagamento, status, canal_origem,"
                                              " data_inicio, data_renovacao, observacoes, indicado_por FROM clientes WHERE id=?", (A[12],)).fetchone())}
    con.close()
    ficha = {k: ("" if v is None else str(v)) for k, v in ficha.items()}
    hor = lambda cid, ds, hs, ls: ("POST", f"/clientes/{cid}/horarios", {"dia": [str(x) for x in ds], "hora": [str(x) for x in hs], "local": ls})  # noqa: E731
    passos = [
        hor(A[11], [2, 3], [21, 5], ["SmartFit", "CIA"]),            # Qua 05h tem 3: cheio, nada grava
        hor(A[11], [2, 6], [21, 23], ["SmartFit", "SmartFit"]),     # entra (e sai do sorteado), aviso de deslocamento
        hor(A[11], [2, 6], [21, 23], ["SmartFit", " CIA "]),        # troca de local
        hor(A[11], [2, 6], [21, 23], ["SmartFit", "CIA"]),          # nada mudou
        hor(A[0], [], [], []),                                       # sai de tudo; a dupla fica com a célula da Grade
        hor(A[8], [4], [21], ["SmartFit"]),                          # linha repetida + troca de local
        hor(A[1], [1], [5], ["Lugar X"]), hor(A[1], [7], [5], ["CIA"]), hor(A[1], [1, 1], [5, 5], ["CIA", "CIA"]),
        hor(A[1], [1], [5, 6], ["CIA"]), hor(A[1], list(range(1, 7)) * 3, [5] * 18, ["CIA"] * 18),
        hor(I[2], [1], [5], ["CIA"]), hor(99999, [], [], []),
        ("POST", f"/clientes/{I[0]}/status", {"status": "ativo"}),  # Sex 05h encheu: sai; Sex 23h volta para a Grade
        ("POST", f"/clientes/{A[9]}/status", {"status": "inativo"}),
        ("POST", f"/clientes/{I[1]}/status", {"status": "ativo"}),
        ("POST", f"/clientes/{A[4]}/status", {}),
        ("POST", f"/clientes/{A[4]}/evento", {"tipo": "anotacao", "data": "2026-11-19", "descricao": "Treino leve", "valor": "12,5"}),
        ("POST", f"/clientes/{A[4]}/evento", {"tipo": "aula", "data": "2026-11-19"}),
        ("POST", f"/clientes/{com_ren[0]}/evento", {"tipo": "pausa", "data": "2026-11-19", "descricao": "Viagem"}),
        ("POST", f"/clientes/{com_ren[1]}/evento", {"tipo": "pausa", "data": "2026-11-19", "nova_renovacao": "2020-01-01"}),
        ("POST", f"/clientes/{I[3]}/evento", {"tipo": "pausa", "data": "2026-11-19", "nova_renovacao": "2026-12-30"}),
        ("POST", f"/alunos/{com_ren[2]}/pulou", {"voltar": "/clientes"}), ("POST", f"/alunos/{sem_ren}/pulou", {}),
        ("POST", f"/clientes/{A[12]}", {**ficha, "status": "pausado", "observacoes": "Mudou"}),
        ("POST", f"/clientes/{A[12]}", {**ficha, "status": "ativo", "data_renovacao": "2027-01-05"}),
        ("POST", f"/clientes/{A[12]}", {**ficha, "indicado_por": str(A[12])}),
    ]
    muitos = ",".join(map(str, range(1, 151)))   # mais de 100 ids: o D1 aceita até 100 parâmetros por consulta
    telas_e_roteiro(caminho, "agenda-ficha", [f"/clientes/{A[0]}", f"/clientes/{I[0]}", f"/clientes?ids={muitos}&motivo=cobrar",
                                              f"/clientes?ids={muitos}&motivo=sem-aula"], passos,
                    ["clientes", "agenda_fixos", "grade_slots", "cliente_eventos"])


def casos_grade():
    """Etapa 3b: a tela da Grade (tipos, locais, plano de referência, vale) e o roteiro dos cliques que gravam na Agenda."""
    caminho = banco_novo()
    semear_agenda(caminho)
    con = sqlite3.connect(caminho)
    A = [r[0] for r in con.execute("SELECT id FROM clientes WHERE status='ativo' ORDER BY id")]
    I = [r[0] for r in con.execute("SELECT id FROM clientes WHERE status!='ativo' ORDER BY id")]
    con.close()
    urls = ["/grade", "/grade?tipo=Mensalidades&local=CIA", "/grade?local=SmartFit", "/grade?local=SmartFit&tipo=Mensalidades&ref=3&vale=1",
            "/grade?local=Condom%C3%ADnio", "/grade?ref=12&vale=1", "/grade?ref=7", "/grade?local=Inexistente"]
    slot = lambda **d: ("POST", "/grade/slot", {"tipo": "Pacotes", "local": "CIA", "ref": "0", **d})  # noqa: E731
    passos = [
        ("POST", "/grade/multiplicadores?tipo=Pacotes&local=CIA&ref=0", {"m_05": "0,9", "m_07": "abc"}),
        ("POST", "/grade/multiplicadores?tipo=Mensalidades&local=SmartFit&ref=3", {"m_05": "0,85", "m_22": "1,5", "m_06": ""}),
        ("POST", "/grade/multiplicadores?tipo=Pacotes&local=CIA", {"m_08": "9"}),
        ("POST", "/grade/multiplicadores", {}),
        slot(dia="1", hora="21", status="ocupado", cliente_id=[str(A[13]), str(A[14])]),
        slot(dia="1", hora="5", status="ocupado", cliente_id=[str(A[0]), str(A[2])]),
        slot(celulas=["3-5", "2-21"], status="ocupado", cliente_id=[str(A[15])]),
        slot(celulas=["2-21", "6-21", "6-21", "x", "9-9"], status="ocupado", cliente_id=[str(A[15])], local="SmartFit"),
        slot(dia="1", hora="5", status="livre"),
        slot(dia="3", hora="5", status="indisponivel"),
        slot(dia="1", hora="23", status="indisponivel", local="SmartFit", tipo="Mensalidades", ref="3"),
        slot(dia="1", hora="23", status=""), slot(celulas=["x", "9-9"], status="livre"),
        slot(dia="4", hora="23", status="ocupado", cliente_id=[str(I[0])]), slot(dia="4", hora="23", status="ocupado"),
        slot(dia="3", hora="5", status="ocupado", cliente_id=[str(A[4]), str(A[5])]),
        slot(dia="3", hora="22", status="ocupado", cliente_id=[str(A[16])]),
        slot(dia="abc", hora="5", status="livre"),
        ("POST", "/grade/passar-para-agenda", {"tipo": "Mensalidades", "local": "SmartFit", "ref": "3"}),
        ("POST", "/grade/passar-para-agenda", {}),
        ("GET", "/grade?ref=abc", {}),
    ]
    telas_e_roteiro(caminho, "grade", urls, passos, ["agenda_fixos", "grade_slots", "parametros"])


def casos_alunos():
    from app import alunos, financeiro, main, pix
    caminho = banco_novo()
    semear_alunos(caminho)
    semear_ofertas_indicacoes(caminho)
    dump(caminho, ["parametros", "clientes", "agenda_fixos", "cliente_eventos", "lancamentos", "ofertas", "oferta_respostas"], "cenario-alunos.sql")
    db.DB_PATH = caminho
    con = db.conectar(caminho)
    est = alunos.estado(con, HOJE)
    situacoes = sorted({e["situacao"] for e in est.values()})
    unicos = {cid: alunos.estado(con, HOJE, ids=[cid]).get(cid) for cid in list(est)[::7]}
    par = db.parametros(con, "cobranca")
    meses = [financeiro.somar_meses(HOJE[:7], k) for k in (-2, -1, 0, 1)]
    saida = {
        "situacoes": situacoes,
        "estado": est, "estado_um": unicos,
        "renovacoes": financeiro.renovacoes(con),
        "mensalidades": {m: financeiro.mensalidades(con, m) for m in meses},
        "creditos": financeiro.creditos(con),
        "diferencas": financeiro.diferencas(con),
        "pago_adiantado_ate": financeiro.pago_adiantado_ate(con, HOJE),
        "cobranca": [[v, venc, cred, dia, financeiro.cobranca(v, venc, HOJE, par, cred, dia)]
                     for v in (0, 600, 450.5) for venc in ("2026-11-19", "2026-11-18", "2026-09-30", "2026-01-31", "2024-05-10", "xx")
                     for cred in (0, 100, 600) for dia in (None, 31, 10)],
        "dias_parados": [[u, h, iv, main.dias_parados(__import__("datetime").date.fromisoformat(u), __import__("datetime").date.fromisoformat(h), iv)]
                         for u, h, iv in [("2026-10-01", "2026-11-19", [("2026-10-25", "2026-11-02")]),
                                          ("2026-10-01", "2026-11-19", [("2026-10-25", "2026-11-02"), ("2026-10-30", "2026-11-10"), ("2026-09-01", "2026-10-03")]),
                                          ("2026-11-05", "2026-11-19", [("2026-10-25", "2026-11-02")]), ("2026-11-01", "2026-11-03", [("2026-11-02", "2026-12-30")])]],
        "br_code": [[c, nm, ci, v, pix.br_code(c, nm, ci, v)] for c, nm, ci, v in [
            ("chave@pix.com", "Victor Celli", "São Paulo", 615.33), ("+5511999990000", "José Ação da Silva Muito Comprido Nome", "Ribeirão Preto do Sul", None),
            ("", "A", "B", 10), ("12345678900", "  ana  ", " sp ", 0.005), ("chave", "Ç", "É", 1234567.891)]],
        "frase_valor": [[v, cs, alunos.frase_valor(v, cs)] for v, cs in [
            (600, None), (0, [{"id": 1, "mes": "2026-10", "valor": 100.0}]), (600, [{"id": 1, "mes": "2026-10", "valor": 100.0}, {"id": 2, "mes": "2026-09", "valor": 550.0}]),
            (300, [{"id": 3, "mes": "2026-08", "valor": 120.0}, {"id": 4, "mes": "2026-09", "valor": 120.0}])]],
    }
    salvar("alunos", jsonavel(saida))
    casos_cartao_ofertas(con)
    con.close()
    print("situações no cenário:", situacoes)


def casos_cartao_ofertas(con):
    import datetime as dt
    import textwrap
    from app import alunos, cartao, financeiro, indicacoes, main, ofertas
    hoje = dt.date.fromisoformat(HOJE)
    est = alunos.estado(con, HOJE)
    modelos, dados = db.parametros(con, "msg_whatsapp"), main.dados_mensagem(con)
    par = db.parametros(con, "cobranca")
    clientes = {r["id"]: r for r in con.execute("SELECT * FROM clientes")}
    cartoes = []
    for cid, e in est.items():
        if not e["cartao"]:
            continue
        ren = e["renovacao"]
        ca = main.cobranca_atual(con, clientes[cid], {"efetiva": ren["efetiva"], "vence": ren["vence"], "cob": e["cobranca"], "credito": e["credito"]},
                                 hoje, modelos, dados)
        cartoes.append([cid, ca["codigo"], cartao.svg(ca, main.moeda, main.data_br, par)])
    difs = financeiro.diferencas(con)
    dif_cartoes = [[cid, main.diferenca_cartao(clientes[cid], itens, dados, modelos)["codigo"],
                    cartao.svg(main.diferenca_cartao(clientes[cid], itens, dados, modelos), main.moeda, main.data_br)] for cid, itens in difs.items()]
    pendencias = {cid: main.pendencia_diferenca(clientes[cid], itens, dados) for cid, itens in difs.items()}
    textos = ["Oi, Ana! Sua mensalidade de R$ 600,00 venceu em 10/11/2026. Segue o Pix atualizado com multa e juros.",
              "palavra-com-hifen-muito-comprida-que-passa-do-limite-de-largura e mais", "a--b c—d e - f", "   espaço   no começo",
              "x" * 80, "Tab\taqui e\nquebra", ""]
    ids = sorted(clientes)
    saida = {
        "cartoes": cartoes, "dif_cartoes": dif_cartoes, "pendencias": pendencias,
        "wrap": [[t, w, textwrap.wrap(t, w)] for t in textos for w in (10, 36)] + [[t, 62, textwrap.wrap(t, 62, break_on_hyphens=False)] for t in textos],
        "indicacoes_pendentes": indicacoes.pendentes(con),
        "indicacoes_do_aluno": {cid: indicacoes.do_aluno(con, cid) for cid in ids[:12]},
        "quem_indicou": {cid: indicacoes.quem_indicou(con, cid) for cid in ids[:12]},
        "escolher": indicacoes.alunos_para_escolher(con, ids[0]),
        "ofertas_ativas": ofertas.ativas(con, HOJE),
        "situacao": {cid: ofertas.situacao_aluno(con, cid, HOJE) for cid in ids[:6]},
        "texto_oferta": [ofertas.texto(o, "Ana") for o in ofertas.todas(con)],
        "pendentes_oferta": [[p["oferta"]["id"], [e["id"] for e in p["elegiveis"]]] for p in ofertas.pendentes(con, None, HOJE)],
        "descontos_acabando": ofertas.descontos_acabando(con, HOJE),
        "validar": [list(ofertas.validar(*a)) for a in [("", "x", "1", "0,5", "", ""), ("T", "", 1, 1, "", ""), ("T", "I", "abc", "1", "", ""),
                    ("T", "I", "0", "1", "", ""), ("T", "I", "100", "100", "", ""), ("T", "I", "100", "80", "37", ""),
                    ("T", "I", "100", "80", "x", ""), ("T", "I", "100", "80", "3", "2026-02-30"), (" Treino  dupla ", " inclui ", "1.500", "1.200,50", " 12 ", "2026-12-01")]],
    }
    salvar("cartao-ofertas", jsonavel(saida))


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
    casos_alunos()
    casos_clientes()
    casos_agenda_ficha()
    casos_grade()
    print("paridade gerada em worker/")
