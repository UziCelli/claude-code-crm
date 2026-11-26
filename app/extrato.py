"""Extrato das contas: Inter (PF) em OFX e Contabilizei Bank (PJ) em CSV. Lê o arquivo, interpreta cada movimento, casa com o que
já está no CRM e devolve uma prévia; só grava o que você confirmar na tela de revisão (nada entra sozinho).

Anti-duplicação: cada movimento importado guarda em lancamentos.origem uma chave fixa '<OFX|CSV>:<conta>:<data>:<centavos>:<descrição>:<n>'
(n = repetição idêntica no mesmo dia). No Inter o FITID é a data + 077 + a sequência do dia (202611240771), então pode mudar se o
extrato for exportado no meio do dia; por isso a chave vem do conteúdo, nos dois bancos. Importar o mesmo período de novo encontra a
chave e não cria nada."""
import datetime as dt
import hashlib
import json
import re
import sqlite3

from . import db, faturas, financeiro

CONTA_OFX = "Inter"                 # o único banco que exportamos em OFX
CONTA_CSV = "Contabilizei Bank"     # o único que exportamos em CSV
BANCOS_OFX = {"77", "077", "0077"}  # código do Banco Inter (BANKID)
DIAS_EXISTE = 3                      # pago à mão até 3 dias do movimento: é o mesmo
DIAS_PAGAR = 10                      # conta em aberto até 10 dias do movimento: o movimento pode ser o pagamento dela
DIAS_SEM_IMPORTAR = 7                # aviso no painel
GRUPO_REGRA = "extrato_regra"        # parametros: chave 'escopo|tipo|palavras' -> categoria (o que você corrigiu)
GRUPO_IGNORADO = "extrato_ignorado"  # parametros: origem que você mandou ignorar (não aparece de novo como novo)
GRUPO_LIGADO = "extrato_ligado"      # parametros: chave do extrato -> id do lançamento que já tinha outra origem (planilha 'PJ:17', 'SAL:…')
MAX_BYTES = 5 * 1024 * 1024
MAX_LINHAS = 2000

# forma: a primeira regra cujas palavras aparecem na descrição (sem acento, minúsculas)
FORMAS = [(("pix",), "PIX"), (("boleto",), "Boleto"), (("titulo",), "Boleto"), (("debito", "automatico"), "Débito Auto"),
          (("deb", "aut"), "Débito Auto"), (("ted",), "Transferência"), (("doc",), "Transferência"),
          (("transferencia",), "Transferência"), (("compra", "debito"), "Cartão Débito")]
# palavras de operação que não fazem parte do nome de quem pagou/recebeu
OPERACAO = {"pix", "recebido", "recebida", "enviado", "enviada", "ted", "doc", "transferencia", "transf", "pagamento", "pagto", "pgto",
            "boleto", "titulo", "debito", "credito", "compra", "de", "para", "em", "cp", "cpf", "cnpj", "conta", "recebimento", "envio",
            "devolucao", "estorno", "deb", "cred", "aut", "automatico", "no", "na", "do", "da"}


class ArquivoInvalido(ValueError):
    """Mensagem em português para a tela (o arquivo não é do formato esperado)."""


# ---------- leitura ----------
def _texto(conteudo: bytes) -> str:
    for cod in ("utf-8-sig", "cp1252"):
        try:
            return conteudo.decode(cod)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("latin-1")


def _valor_br(v: str) -> float:
    """'1.234,56', '-12,00', 'R$ -12,00', '(12,00)', '-50.00' -> float. ValueError se não for número."""
    s = (v or "").strip().replace("R$", "").replace("\xa0", "").replace(" ", "").replace("−", "-")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:   # 1.234.567 sem centavos
        s = s.replace(".", "")
    n = float(s)
    if n != n or n in (float("inf"), float("-inf")):
        raise ValueError(v)
    return -abs(n) if neg else n


def _data(v: str) -> str:
    """'20261124...', '24/11/2026', '24/11/26' ou '2026-11-24' -> '2026-11-24'. ValueError se não for data."""
    v = (v or "").strip()
    if m := re.match(r"(\d{4})(\d{2})(\d{2})", v):
        return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    if m := re.match(r"(\d{4})-(\d{2})-(\d{2})", v):
        return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    if m := re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", v):
        ano = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return dt.date(ano, int(m[2]), int(m[1])).isoformat()
    raise ValueError(v)


def _tag(bloco: str, nome: str) -> str | None:
    """Valor de <NOME> no OFX, no formato antigo (SGML, sem fechar) ou XML."""
    m = re.search(rf"<{nome}>\s*([^<\r\n]*)", bloco, re.I)
    return m.group(1).strip() if m else None


def _nome_ofx(nome: str | None) -> str | None:
    """NAME do Inter sem o enchimento da cidade e sem códigos: 'Super Market          Sao Paulo    Bra' -> 'Super Market';
    'São Paulo - Bilhete único - 01M7MT37' -> 'São Paulo - Bilhete único'."""
    nome = re.split(r"\s{2,}", (nome or "").strip())[0]
    partes = [p.strip() for p in nome.split(" - ") if p.strip() and not re.search(r"\d", p)]
    return " - ".join(partes)[:80] or None


def _chaves(movs: list[dict]) -> None:
    """Chave estável de cada movimento: data + centavos + descrição, numerando as repetições idênticas do mesmo dia."""
    vistos: dict[tuple, int] = {}
    for m in movs:
        base = (m["data"], round(m["valor"] * 100), " ".join(financeiro._palavras(m["descricao"])))
        vistos[base] = vistos.get(base, 0) + 1
        m["chave"] = f"{base[0]}:{base[1]}:{hashlib.sha1(base[2].encode()).hexdigest()[:10]}:{vistos[base]}"


def ler_ofx(conteudo: bytes) -> dict:
    """{'conta', 'formato', 'saldo', 'saldo_data', 'movimentos': [{'data', 'valor' (com sinal), 'descricao', 'contraparte', 'chave'}]}."""
    t = _texto(conteudo)
    if "<OFX>" not in t.upper():
        raise ArquivoInvalido("não é um arquivo OFX")
    banco = (_tag(t, "BANKID") or "").lstrip("0")
    org = (_tag(t, "ORG") or "").lower()
    if banco not in {b.lstrip("0") for b in BANCOS_OFX} and "inter" not in org:
        raise ArquivoInvalido("o OFX não é do Inter (só a conta do Inter vem em OFX)")
    movs = []
    for bloco in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", t, re.S | re.I):
        try:
            valor = _valor_br(_tag(bloco, "TRNAMT") or "")
            data = _data(_tag(bloco, "DTPOSTED") or "")
        except ValueError:
            raise ArquivoInvalido("um movimento do OFX tem data ou valor que não entendi") from None
        memo = " ".join((_tag(bloco, "MEMO") or "").split())
        nome = _nome_ofx(_tag(bloco, "NAME"))
        movs.append({"data": data, "valor": valor, "descricao": memo or nome or (_tag(bloco, "TRNTYPE") or ""), "contraparte": nome})
        if len(movs) > MAX_LINHAS:
            raise ArquivoInvalido(f"o arquivo tem mais de {MAX_LINHAS} movimentos: exporte um período menor")
    _chaves(movs)
    saldo = saldo_data = None
    if m := re.search(r"<LEDGERBAL>(.*?)(</LEDGERBAL>|<AVAILBAL>|</STMTRS>)", t, re.S | re.I):
        try:
            saldo, saldo_data = round(_valor_br(_tag(m.group(1), "BALAMT") or ""), 2), _data(_tag(m.group(1), "DTASOF") or "")
        except ValueError:
            saldo = saldo_data = None
    return {"conta": CONTA_OFX, "formato": "OFX", "saldo": saldo, "saldo_data": saldo_data, "movimentos": movs}


def _coluna(cab: list[str], *nomes) -> int | None:
    """A primeira coluna que contém o primeiro nome; senão o segundo, e assim por diante."""
    for n in nomes:
        for i, c in enumerate(cab):
            if n in c:
                return i
    return None


def ler_csv(conteudo: bytes) -> dict:
    """CSV do Contabilizei: acha o cabeçalho (data, descrição/histórico, valor ou crédito+débito, saldo se houver) pelas palavras."""
    import csv
    linhas_txt = _texto(conteudo).splitlines()
    if not linhas_txt:
        raise ArquivoInvalido("o CSV está vazio")
    amostra = "\n".join(linhas_txt[:20])
    sep = ";" if amostra.count(";") >= amostra.count(",") else ","
    linhas = list(csv.reader(linhas_txt, delimiter=sep))
    ini = None
    for i, l in enumerate(linhas[:30]):
        cab = [" ".join(financeiro._palavras(c)) for c in l]
        if _coluna(cab, "data") is not None and (_coluna(cab, "valor") is not None or _coluna(cab, "credito", "entrada") is not None):
            ini = i
            break
    if ini is None:
        raise ArquivoInvalido("não achei as colunas de data e valor no CSV")
    cab = [" ".join(financeiro._palavras(c)) for c in linhas[ini]]
    c_data = _coluna(cab, "data")
    c_desc = _coluna(cab, "descricao", "historico", "detalhe")
    c_oper = _coluna(cab, "lancamento", "tipo")   # Contabilizei: "PIX", "Devolução PIX"
    c_valor = _coluna(cab, "valor")
    c_cred, c_deb = _coluna(cab, "entrada", "credito"), _coluna(cab, "saida", "debito")
    c_saldo = _coluna(cab, "saldo")
    if c_valor is not None and c_valor == c_saldo:
        c_valor = None
    movs, saldos = [], {}
    for l in linhas[ini + 1:]:
        if not any(x.strip() for x in l):
            continue

        def cel(i):
            v = l[i].strip() if i is not None and i < len(l) else ""
            return "" if v in ("-", "—") else v   # "-" = campo vazio

        try:
            data = _data(cel(c_data))
        except ValueError:
            continue   # linha de total ou de rodapé
        try:
            if c_valor is not None:
                valor = _valor_br(cel(c_valor))
            else:
                valor = (abs(_valor_br(cel(c_cred))) if cel(c_cred) else 0) - (abs(_valor_br(cel(c_deb))) if cel(c_deb) else 0)
        except ValueError:
            raise ArquivoInvalido(f"o valor da linha de {data[8:]}/{data[5:7]} não é um número") from None
        if cel(c_saldo):
            try:   # "Saldo do dia": o mesmo em todas as linhas do dia, e as linhas não vêm em ordem
                saldos[data] = round(_valor_br(cel(c_saldo)), 2)
            except ValueError:
                pass
        if round(valor, 2) == 0:
            continue
        nome = " ".join(cel(c_desc).split())
        oper = " ".join(cel(c_oper).split())
        movs.append({"data": data, "valor": valor, "descricao": f"{oper}: {nome}" if oper and nome else (oper or nome),
                     "contraparte": contraparte(nome) if c_oper is not None else None})
        if len(movs) > MAX_LINHAS:
            raise ArquivoInvalido(f"o arquivo tem mais de {MAX_LINHAS} movimentos: exporte um período menor")
    _chaves(movs)
    saldo_data = max(saldos) if saldos else None
    return {"conta": CONTA_CSV, "formato": "CSV", "saldo": saldos.get(saldo_data), "saldo_data": saldo_data, "movimentos": movs}


def ler_arquivo(nome: str, conteudo: bytes) -> dict:
    """Descobre o banco pelo conteúdo (OFX = Inter; CSV = Contabilizei). ArquivoInvalido com o motivo."""
    if len(conteudo) > MAX_BYTES:
        raise ArquivoInvalido("o arquivo passa de 5 MB")
    inicio = _texto(conteudo[:4000]).upper()
    if "OFXHEADER" in inicio or "<OFX>" in inicio:
        r = ler_ofx(conteudo)
    elif (nome or "").lower().endswith((".csv", ".txt")) or ";" in inicio:
        r = ler_csv(conteudo)
    else:
        raise ArquivoInvalido("não reconheci: use o OFX do Inter ou o CSV do Contabilizei")
    if not r["movimentos"]:
        raise ArquivoInvalido("o arquivo não tem movimentos")
    r["arquivo"] = nome
    return r


# ---------- interpretação ----------
def parece_emprestimo(texto: str) -> bool:
    """Entrada que pode ser empréstimo: as palavras de financeiro.parece_emprestimo ou "crédito" ("X Soluções de Crédito",
    "Crédito liberado"). Só pede confirmação na revisão; o cadastro do empréstimo é a Etapa 3."""
    return financeiro.parece_emprestimo(texto) or "credito" in financeiro._palavras(texto)

def _forma(palavras: list[str]) -> str | None:
    p = set(palavras)
    for chaves, forma in FORMAS:
        if set(chaves) <= p:
            return forma
    return None


def contraparte(descricao: str) -> str | None:
    """O nome que sobra da descrição depois de tirar a operação, números e documentos ('PIX RECEBIDO - 123 JOAO SILVA' -> 'Joao Silva')."""
    palavras = [w for w in re.findall(r"[A-Za-zÀ-ÿ]+", descricao or "") if len(w) > 1]
    nome = [w for w in palavras if financeiro._sem_acento_low(w) not in OPERACAO]
    return " ".join(w.capitalize() for w in nome[:6]) or None


def _texto_regra(contra: str | None, descricao: str) -> str:
    """As palavras que identificam o movimento para a regra de categoria: o nome da contraparte; sem ele, a descrição sem números."""
    return " ".join(financeiro._palavras(contra) or [w for w in financeiro._palavras(descricao) if not w.isdigit()][:6])


def regras(con: sqlite3.Connection) -> list[tuple[str, str, list[str], str]]:
    """[(escopo, tipo, palavras, categoria)], as mais específicas (mais palavras) primeiro."""
    out = []
    for chave, cat in db.parametros(con, GRUPO_REGRA).items():
        escopo, tipo, texto = (chave.split("|", 2) + ["", ""])[:3]
        if texto and cat:
            out.append((escopo, tipo, texto.split(), cat))
    return sorted(out, key=lambda r: -len(r[2]))


def categoria(escopo: str, tipo: str, palavras: list[str], cliente_id, regras_salvas, listas: dict) -> tuple[str, bool]:
    """(categoria, veio de regra sua). Regra que você ensinou > palavra-chave > aluno > 'Outros'. Sempre uma da lista do escopo."""
    validas = listas["PJ" if escopo == "PJ" else "PF"]
    p = set(palavras)
    for e, t, chaves, cat in regras_salvas:
        if e == escopo and t == tipo and set(chaves) <= p and cat in validas:
            return cat, True
    texto = " ".join(palavras)
    sugestoes = []
    if tipo == "entrada" and parece_emprestimo(texto):
        sugestoes.append(financeiro.EMPRESTIMO)
    if p & {"tarifa", "iof", "das"} or "simples nacional" in texto or "juros" in p:
        sugestoes.append("Impostos/Taxas" if escopo == "PJ" else "Outros")
    if p & {"fatura", "cartao"} and tipo == "saida":
        sugestoes.append("Fatura")
    if p & {"uber", "transporte", "bilhete", "metro", "onibus", "combustivel", "estacionamento"} and tipo == "saida":
        sugestoes.append("Transporte")
    if p & {"food", "ifood", "restaurante", "mercado", "market", "supermercado", "padaria", "lanchonete"} and tipo == "saida":
        sugestoes.append("Alimentação")
    if cliente_id and escopo == "PJ" and tipo == "entrada":
        sugestoes.append("Mensalidade (Aulas Presenciais)")
    for s in sugestoes:
        if s in validas:
            return s, False
    return ("Outros" if "Outros" in validas else validas[-1]), False


def interpretar(con: sqlite3.Connection, arq: dict) -> list[dict]:
    """Cada movimento do arquivo vira uma linha pronta para casar: tipo, valor (> 0), forma, contraparte, aluno e categoria."""
    conta = arq["conta"]
    frente = financeiro.frentes_contas(con).get(conta)
    escopo = "PJ" if frente == "PJ" else "PF"
    alunos = con.execute("SELECT id, nome FROM clientes WHERE excluido_em IS NULL").fetchall()
    regras_salvas = regras(con)
    listas = {"PJ": db.lista(con, "lista_categorias_pj"), "PF": db.lista(con, "lista_categorias_pf")}
    prefixo = f"{arq['formato']}:{conta}:"
    out = []
    for m in arq["movimentos"]:
        tipo = "entrada" if m["valor"] > 0 else "saida"
        contra = contraparte(m.get("contraparte") or "") or contraparte(m["descricao"])
        palavras = financeiro._palavras(f"{m['descricao']} {contra or ''}")
        cliente_id = financeiro.sugerir_aluno(m["descricao"], alunos) if escopo == "PJ" and tipo == "entrada" else None
        cat, por_regra = categoria(escopo, tipo, palavras, cliente_id, regras_salvas, listas)
        if (tipo == "saida" and escopo == "PF" and not por_regra and faturas.CATEGORIA_PAGAMENTO in listas["PF"]
                and faturas.paga_fatura(con, m["data"], abs(m["valor"]))):
            cat = faturas.CATEGORIA_PAGAMENTO   # o valor de uma fatura importada, perto do vencimento: é o pagamento do cartão
        out.append({"origem": prefixo + m["chave"], "conta": conta, "escopo": escopo, "tipo": tipo, "data": m["data"],
                    "valor": round(abs(m["valor"]), 2), "descricao": m["descricao"][:200], "contraparte": contra,
                    "forma": _forma(palavras), "cliente_id": cliente_id, "categoria": cat, "categoria_sugerida": cat,
                    "emprestimo": tipo == "entrada" and not por_regra and parece_emprestimo(" ".join(palavras))})
    return out


# ---------- casamento com o que já existe ----------
def _ligados(con: sqlite3.Connection) -> dict[str, int]:
    """{chave do extrato: id do lançamento} de todo lançamento já conciliado com um movimento do banco: o que guarda a chave na
    origem e o que já tinha outra origem (guardado em parametros, grupo GRUPO_LIGADO). Um lançamento conciliado não casa de novo."""
    out = {r["origem"]: r["id"] for r in con.execute(
        "SELECT id, origem FROM lancamentos WHERE origem LIKE 'OFX:%' OR origem LIKE 'CSV:%'")}
    for chave, lid in db.parametros(con, GRUPO_LIGADO).items():
        try:
            out[chave] = int(lid)
        except (TypeError, ValueError):
            continue
    return out


def _ligar(con: sqlite3.Connection, lid: int, origem: str) -> None:
    """Registra que o lançamento é o movimento `origem` do extrato. Sem origem, ela vira a chave; com outra (planilha, salário), a ligação
    fica em parametros sem apagar a origem antiga."""
    con.execute("UPDATE lancamentos SET origem=? WHERE id=? AND origem IS NULL", (origem, lid))
    if con.execute("SELECT origem FROM lancamentos WHERE id=?", (lid,)).fetchone()[0] != origem:
        con.execute("""INSERT INTO parametros (grupo, chave, valor, ordem) VALUES (?, ?, ?, 0)
                       ON CONFLICT (grupo, chave) DO UPDATE SET valor=excluded.valor""", (GRUPO_LIGADO, origem, lid))


def _dias(a: str, b: str) -> int:
    return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)


def casar(con: sqlite3.Connection, linhas: list[dict], hoje: str, reservas: dict | None = None) -> list[dict]:
    """Para cada linha decide a ação sugerida e se é certeza:
    - 'existe' (já importado pela chave, ou lançado à mão: pago, mesmo valor, até DIAS_EXISTE dias);
    - 'pagar' (lançamento em aberto ou conta recorrente do mês com o mesmo valor: o movimento é o pagamento dela);
    - 'ignorar' (você já mandou ignorar esta linha); senão 'novo'.
    Cada linha ganha 'acao', 'ref', 'certo', 'motivo' e 'opcoes' [(valor, rótulo)]. Um lançamento só casa com um movimento, também
    entre os arquivos da mesma revisão (`reservas`, compartilhado por previa). Lançamento de outro aluno nunca é candidato; o de um aluno,
    quando o extrato não diz quem pagou, pede decisão."""
    reservas = reservas if reservas is not None else {}
    usados: set[int] = reservas.setdefault("usados", set())
    ignorados = set(db.parametros(con, GRUPO_IGNORADO))
    ligados = _ligados(con)
    origens = {l["origem"]: ligados[l["origem"]] for l in linhas if l["origem"] in ligados}
    usados |= set(ligados.values())   # lançamento já conciliado com outro movimento não casa de novo
    recs_vistas: set[str] = reservas.setdefault("recorrencias", set())
    for l in linhas:
        l["opcoes"], l["ref"], l["certo"], l["motivo"] = [], "", True, ""
        if l["origem"] in origens:
            l["acao"], l["ref"], l["motivo"] = "existe", str(origens[l["origem"]]), "já importado antes"
            l["opcoes"] = [("existe", "Já está no CRM")]
            continue
        if l["origem"] in ignorados:
            l["acao"], l["motivo"] = "ignorar", "você mandou ignorar antes"
            l["opcoes"] = [("ignorar", "Ignorar"), ("novo", "Lançar como novo")]
            continue
        cents = round(l["valor"] * 100)
        cand = con.execute(
            """SELECT id, data, pago_em, descricao, categoria, conta, cliente_id, origem FROM lancamentos
               WHERE excluido_em IS NULL AND escopo=? AND tipo=? AND ROUND(valor * 100)=? AND (conta=? OR conta IS NULL)
               AND COALESCE(pago_em, data) BETWEEN date(?, ?) AND date(?, ?) ORDER BY id""",
            (l["escopo"], l["tipo"], cents, l["conta"], l["data"], f"-{DIAS_PAGAR} days", l["data"], f"+{DIAS_PAGAR} days")).fetchall()
        existe = [c for c in cand if c["pago_em"] and c["id"] not in usados and _dias(c["pago_em"], l["data"]) <= DIAS_EXISTE
                  ]
        abertos = [c for c in cand if not c["pago_em"] and c["id"] not in usados]
        if l["cliente_id"]:   # pagamento de um aluno não casa com lançamento de outro aluno
            existe = [c for c in existe if c["cliente_id"] in (None, l["cliente_id"])]
            abertos = [c for c in abertos if c["cliente_id"] in (None, l["cliente_id"])]
        if l["cliente_id"]:   # mensalidade do aluno sugerido primeiro
            abertos.sort(key=lambda c: (c["cliente_id"] != l["cliente_id"], _dias(c["data"], l["data"])))
        else:
            abertos.sort(key=lambda c: _dias(c["data"], l["data"]))
        recs = []
        if l["tipo"] == "saida":
            conta_rec = {r["id"]: r["conta"] for r in con.execute("SELECT id, conta FROM recorrencias WHERE excluido_em IS NULL")}
            mes = l["data"][:7]   # paga adiantado no fim do mês: a competência seguinte também (o filtro de dias limita)
            for comp in (mes, financeiro.somar_meses(mes, -1), financeiro.somar_meses(mes, 1)):
                for r in financeiro._recorrencias_abertas(con, comp, hoje):
                    chave = f"r:{r['id']}:{comp}"
                    if r["escopo"] == l["escopo"] and chave not in recs_vistas and _dias(r["data"], l["data"]) <= DIAS_PAGAR:
                        igual = round(r["valor"] * 100) == cents
                        parecido = set(financeiro._palavras(r["descricao"])) & set(financeiro._palavras(l["descricao"]))
                        # conta recorrente de outra conta: só como opção, nunca como certeza
                        mesma_conta = conta_rec.get(r["id"]) in (None, "", l["conta"])
                        if igual or (parecido and abs(r["valor"] - l["valor"]) <= 0.15 * r["valor"]):
                            recs.append((chave, r, igual and mesma_conta))
        for c in existe:
            l["opcoes"].append((f"e:{c['id']}", f"Já lançado: {c['descricao'] or c['categoria']} (pago {c['pago_em'][8:]}/{c['pago_em'][5:7]})"))
        for c in abertos:
            l["opcoes"].append((f"l:{c['id']}", f"Dar baixa: {c['descricao'] or c['categoria']} (vence {c['data'][8:]}/{c['data'][5:7]})"))
        for chave, r, _ in recs:
            l["opcoes"].append((chave, f"Dar baixa: {r['descricao']} de {financeiro._mes_br(r['competencia'])}"))
        l["opcoes"] += [("novo", "Lançar como novo"), ("ignorar", "Ignorar")]
        if existe:
            c = existe[0]
            l["acao"], l["ref"] = "existe", f"e:{c['id']}"
            l["certo"] = len(existe) == 1 and c["pago_em"] == l["data"] and (not c["cliente_id"] or c["cliente_id"] == l["cliente_id"])
            l["motivo"] = "parece o lançamento que você já fez"
            usados.add(c["id"])
        elif abertos:
            c = abertos[0]
            l["acao"], l["ref"] = "pagar", f"l:{c['id']}"
            mesmo_aluno = bool(l["cliente_id"]) and c["cliente_id"] == l["cliente_id"]
            l["certo"] = len(abertos) == 1 and (mesmo_aluno or (not c["cliente_id"] and _dias(c["data"], l["data"]) <= DIAS_EXISTE))
            l["motivo"] = "paga uma conta em aberto"
            usados.add(c["id"])
        elif recs:
            chave, r, igual = recs[0]
            l["acao"], l["ref"], l["certo"] = "pagar", chave, igual and len(recs) == 1
            l["motivo"] = "paga a conta recorrente do mês"
            recs_vistas.add(chave)
        else:
            l["acao"] = "novo"
            l["certo"] = not l["emprestimo"]   # empréstimo: confirme (Etapa 3 cuida do cadastro)
            l["motivo"] = "parece empréstimo: confirme" if l["emprestimo"] else ""
    return linhas


def previa(con: sqlite3.Connection, arquivos: list[tuple[str, bytes]], hoje: str) -> dict:
    """Lê e casa todos os arquivos. {'contas': [{conta, escopo, arquivo, de, ate, saldo, saldo_data, saldo_digitado, linhas}], 'erros': [..]}."""
    contas, erros, vistas, reservas = [], [], set(), {}
    for nome, conteudo in arquivos:
        try:
            arq = ler_arquivo(nome, conteudo)
        except ArquivoInvalido as e:
            erros.append(f"{nome}: {e}.")
            continue
        if arq["conta"] not in db.lista(con, "lista_contas"):
            erros.append(f"{nome}: a conta {arq['conta']} não está na lista de contas (Configurações).")
            continue
        linhas = [l for l in interpretar(con, arq) if l["origem"] not in vistas]   # o mesmo movimento em dois arquivos: uma vez só
        if not linhas:
            erros.append(f"{nome}: todos os movimentos já estão em outro arquivo desta importação.")
            continue
        vistas.update(l["origem"] for l in linhas)
        linhas = casar(con, linhas, hoje, reservas)
        datas = [l["data"] for l in linhas]
        digitado = None
        if arq["saldo_data"]:
            r = con.execute("SELECT saldo FROM saldos WHERE conta=? AND data=? AND excluido_em IS NULL ORDER BY id DESC LIMIT 1",
                            (arq["conta"], arq["saldo_data"])).fetchone()
            digitado = r["saldo"] if r else None
        contas.append({"conta": arq["conta"], "escopo": linhas[0]["escopo"], "arquivo": nome, "formato": arq["formato"],
                       "de": min(datas), "ate": max(datas), "saldo": arq["saldo"], "saldo_data": arq["saldo_data"],
                       "saldo_digitado": digitado, "linhas": linhas})
    return {"contas": contas, "erros": erros}


# ---------- gravação ----------
_COLS_NOVO = "escopo, tipo, data, pago_em, valor, categoria, descricao, contraparte, cliente_id, conta, forma, origem"


def _baixar_recorrencia(con, rid: int, comp: str, l: dict) -> int:
    """Lançamento pago da conta recorrente na competência (sem abrir transação: quem chama já está em `with con`)."""
    r = con.execute("SELECT * FROM recorrencias WHERE id=? AND excluido_em IS NULL", (rid,)).fetchone()
    if r is None:
        raise ValueError("conta recorrente não encontrada")
    financeiro.liberar_vaga(con, rid, comp, None)   # ValueError se o mês já tem baixa; a da lixeira só é solta (continua restaurável)
    return con.execute("""INSERT INTO lancamentos (escopo, tipo, data, pago_em, valor, categoria, descricao, contraparte, conta, forma,
                          recorrencia_id, competencia, origem) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (r["escopo"], "saida", financeiro.vencimento(r["dia_vencimento"], comp), l["data"], l["valor"], r["categoria"],
                        r["descricao"], l["contraparte"], l["conta"], l["forma"], rid, comp, l["origem"])).lastrowid


def _ligar_varios(con: sqlite3.Connection, pares: list[tuple[int, str]], origem_atual: dict) -> None:
    """Registra de uma vez que cada lançamento é o movimento `origem` do extrato (o que _ligar fazia um a um). Sem origem, ela vira a
    chave (um UPDATE com CASE); com outra (planilha, salário), a ligação fica em parametros sem apagar a origem antiga.
    origem_atual: {id: origem} lida antes da transação."""
    sem = [(lid, o) for lid, o in pares if origem_atual.get(lid) is None]
    for i in range(0, len(sem), db.MAX_PARAMS // 3):
        parte = sem[i:i + db.MAX_PARAMS // 3]
        con.execute(f"UPDATE lancamentos SET origem=CASE id {' '.join(['WHEN ? THEN ?'] * len(parte))} END "
                    f"WHERE id IN ({db.marcas(len(parte))}) AND origem IS NULL",
                    [v for par in parte for v in par] + [lid for lid, _ in parte])
    db.inserir_varios(con, "INSERT INTO parametros (grupo, chave, valor, ordem)",
                      [(GRUPO_LIGADO, o, lid, 0) for lid, o in pares if origem_atual.get(lid) not in (None, o)],
                      "ON CONFLICT (grupo, chave) DO UPDATE SET valor=excluded.valor")


def salvar(con: sqlite3.Connection, linhas: list[dict], saldos: list[dict]) -> dict:
    """Grava numa transação só o que veio confirmado. linhas: as da prévia, já validadas, com 'acao' = novo | ignorar | existe |
    e:<id> | l:<id> | r:<rid>:<AAAA-MM>. saldos: [{conta, saldo, data}] para acrescentar como foto (nunca apaga foto digitada).
    Linha cuja chave já está no CRM (envio repetido) é pulada. Devolve a contagem por resultado.
    Em lote (AGENTS.md): o que já existe é lido antes; lançamentos novos sem crédito de aluno, ignorados, ligações, regras, saldos e
    importações vão em poucas instruções de várias linhas. Só a baixa de conta em aberto/recorrente e a entrada de aluno (crédito)
    continuam uma a uma, porque dependem do resultado da anterior."""
    cont = {"novos": 0, "pagos": 0, "existentes": 0, "ignorados": 0, "pulados": 0, "regras": 0, "saldos": 0}
    por_conta: dict[str, int] = {}
    alvos: set[int] = set()
    # leituras primeiro, antes de abrir a transação de escrita
    ligados = _ligados(con)
    ja_conciliados = set(ligados.values())
    ja_ignorados = set(db.parametros(con, GRUPO_IGNORADO))
    refs = sorted({int(l["acao"][2:]) for l in linhas if l["acao"][:2] in ("e:", "l:")})
    origem_atual = {}
    for ids in db.em_blocos(refs):
        origem_atual |= {r[0]: r[1] for r in con.execute(f"SELECT id, origem FROM lancamentos WHERE id IN ({db.marcas(len(ids))})", ids)}
    fotos = {(s["conta"], s["data"]) for s in saldos
             if con.execute("SELECT 1 FROM saldos WHERE conta=? AND data=? AND excluido_em IS NULL", (s["conta"], s["data"])).fetchone()}
    ignorar, desfazer_ignorado, novos, ligar, regras_novas = [], [], [], [], {}
    conta_existe: dict[str, list[int]] = {}
    with con:
        for l in linhas:
            acao = l["acao"]
            if l["origem"] in ligados:
                cont["existentes" if acao == "existe" else "pulados"] += 1   # já importado; senão, o mesmo envio chegando de novo
                continue
            ligados[l["origem"]] = 0   # a mesma linha duas vezes no envio: a segunda é pulada
            por_conta[l["conta"]] = por_conta.get(l["conta"], 0) + 1
            if acao == "ignorar":
                ignorar.append((GRUPO_IGNORADO, l["origem"], l["descricao"], 0))
                cont["ignorados"] += 1
                continue
            if l["origem"] in ja_ignorados:
                desfazer_ignorado.append(l["origem"])
            lid = None
            alvo = int(acao[2:]) if acao[:2] in ("e:", "l:") else None
            if alvo in alvos or alvo in ja_conciliados:
                acao = "novo"   # o mesmo lançamento para dois movimentos (agora ou numa importação anterior): o segundo é um movimento a mais
            elif alvo:
                alvos.add(alvo)
            if acao.startswith("e:") or acao == "existe":
                if alvo:   # marca o lançamento feito à mão com a chave: a próxima importação o reconhece direto
                    conta_existe.setdefault(l["conta"], []).append(alvo)
                    ligar.append((alvo, l["origem"]))
                    if l["cliente_id"] and l["escopo"] == "PJ" and l["tipo"] == "entrada":   # o aluno confirmado na revisão
                        if con.execute("UPDATE lancamentos SET cliente_id=? WHERE id=? AND cliente_id IS NULL AND escopo='PJ' AND tipo='entrada'",
                                       (l["cliente_id"], alvo)).rowcount:
                            financeiro.usar_credito(con, alvo)   # agora é pagamento do aluno: desconta o crédito dele, como numa entrada nova
                cont["existentes"] += 1
                continue
            if acao.startswith("l:"):
                alvo = int(acao[2:])
                n = con.execute("""UPDATE lancamentos SET pago_em=?, conta=?, forma=COALESCE(forma, ?), contraparte=COALESCE(contraparte, ?)
                                   WHERE id=? AND pago_em IS NULL AND excluido_em IS NULL""",
                                (l["data"], l["conta"], l["forma"], l["contraparte"], alvo)).rowcount
                if n:
                    lid = alvo
                    ligar.append((alvo, l["origem"]))
                    cont["pagos"] += 1
                else:
                    acao = "novo"   # já foi paga por outro caminho: o movimento entra como novo
            elif acao.startswith("r:"):
                _, rid, comp = acao.split(":")
                try:
                    lid = _baixar_recorrencia(con, int(rid), comp, l)
                    cont["pagos"] += 1
                except ValueError:
                    acao = "novo"
            pj_entrada = l["escopo"] == "PJ" and l["tipo"] == "entrada"
            credito = pj_entrada and l["cliente_id"]
            if acao == "novo":
                valores = (l["escopo"], l["tipo"], l["data"], l["data"], l["valor"], l["categoria"], l["descricao"] or None,
                           l["contraparte"], l["cliente_id"], l["conta"], l["forma"], l["origem"])
                if credito:   # entrada de aluno: precisa do id agora para descontar o crédito
                    lid = con.execute(f"INSERT INTO lancamentos ({_COLS_NOVO}) VALUES ({db.marcas(len(valores))})", valores).lastrowid
                else:
                    novos.append(valores)   # sem crédito para descontar: vai no lote do fim
                cont["novos"] += 1
            if lid and pj_entrada:   # o lançamento em aberto pode já ser de um aluno, mesmo sem o extrato dizer quem pagou
                if l["cliente_id"] and acao != "novo":
                    con.execute("UPDATE lancamentos SET cliente_id=COALESCE(cliente_id, ?) WHERE id=?", (l["cliente_id"], lid))
                financeiro.usar_credito(con, lid)
            if acao == "novo" and (l["categoria"] != l.get("categoria_sugerida") or l.get("emprestimo")) \
                    and (texto := _texto_regra(l["contraparte"], l["descricao"])):
                # você corrigiu a categoria (ou confirmou a de uma entrada que parecia empréstimo): vale para as próximas com o mesmo nome
                regras_novas[f"{l['escopo']}|{l['tipo']}|{texto}"] = l["categoria"]
        # o resto vai junto, em poucas instruções
        db.inserir_varios(con, f"INSERT INTO lancamentos ({_COLS_NOVO})", novos)
        db.inserir_varios(con, "INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem)", ignorar)
        for origens in db.em_blocos(desfazer_ignorado):
            con.execute(f"DELETE FROM parametros WHERE grupo=? AND chave IN ({db.marcas(len(origens))})", (GRUPO_IGNORADO, *origens))
        for conta, ids in conta_existe.items():
            for parte in db.em_blocos(ids):
                con.execute(f"UPDATE lancamentos SET conta=? WHERE id IN ({db.marcas(len(parte))}) AND conta IS NULL AND excluido_em IS NULL",
                            (conta, *parte))
        _ligar_varios(con, ligar, origem_atual)
        db.inserir_varios(con, "INSERT INTO parametros (grupo, chave, valor_texto, ordem)",
                          [(GRUPO_REGRA, chave, cat, 0) for chave, cat in regras_novas.items()],
                          "ON CONFLICT (grupo, chave) DO UPDATE SET valor_texto=excluded.valor_texto")
        cont["regras"] = len(regras_novas)
        # já tem foto nesse dia (digitada ou do banco): não acrescenta. Duas fotos no mesmo dia esconderiam a conta do Conferir;
        # se o valor é outro, a revisão mostra o conflito e a foto digitada fica
        novas_fotos = {}
        for s in saldos:
            if (s["conta"], s["data"]) not in fotos and (s["conta"], s["data"]) not in novas_fotos:
                novas_fotos[(s["conta"], s["data"])] = (s["conta"], round(s["saldo"], 2), s["data"])
        cont["saldos"] = db.inserir_varios(con, "INSERT INTO saldos (conta, saldo, data)", list(novas_fotos.values()))
        db.inserir_varios(con, "INSERT INTO importacoes (arquivo, resumo)",
                          [(f"extrato:{conta}", json.dumps({"linhas": por_conta.get(conta, 0), **cont}, ensure_ascii=False))
                           for conta in {*por_conta, *(s["conta"] for s in saldos)}])
    return cont


def ultimas_importacoes(con: sqlite3.Connection) -> dict:
    """{conta: 'AAAA-MM-DD HH:MM:SS'} da última importação de extrato de cada conta."""
    return {r["arquivo"][8:]: r["quando"] for r in con.execute(
        "SELECT arquivo, MAX(data) AS quando FROM importacoes WHERE arquivo LIKE 'extrato:%' GROUP BY arquivo")}


def contas_atrasadas(con: sqlite3.Connection, hoje: str) -> list[tuple[str, int]]:
    """[(conta, dias)] das contas do extrato (Inter e Contabilizei) sem importar há mais de DIAS_SEM_IMPORTAR dias.
    Só avisa depois da primeira importação de extrato (antes disso o recurso não está em uso)."""
    ult = ultimas_importacoes(con)
    if not ult:
        return []
    out = []
    for conta in (CONTA_OFX, CONTA_CSV):
        if conta not in db.lista(con, "lista_contas"):
            continue
        quando = ult.get(conta)
        dias = _dias(quando[:10], hoje) if quando else None
        if dias is None or dias > DIAS_SEM_IMPORTAR:
            out.append((conta, dias))
    return out
