"""Faturas de cartão em PDF (Inter e Itaú): lê as compras, sugere a categoria, confere o total e o limite e devolve uma prévia; só grava
o que você confirmar na tela de revisão (nada entra sozinho).

Sem contar duas vezes: as compras ficam em cartao_compras, fora de lancamentos. O dinheiro sai da conta quando a fatura é paga, e
esse pagamento já é um lançamento (categoria 'Fatura', vindo do extrato). Se as compras também fossem saídas, o mesmo gasto
contaria duas vezes no saldo livre e nas saídas da PF. A tela Cartões abre o 'Fatura' por categoria.

Cada parcela conta no mês da fatura em que aparece (o mês do vencimento). Cada compra guarda uma chave fixa
'<conta>:<vencimento>:<cartão>:<data>:<centavos>:<descrição>:<n>' (n = repetição idêntica, como dois IOF iguais no mesmo dia):
importar a mesma fatura de novo não cria nada."""
import datetime as dt
import hashlib
import io
import json
import logging
import re
import sqlite3

from . import db, financeiro

CONTA_INTER = "Cartão Inter"
CONTA_ITAU = "Cartão Itaú"
CATEGORIA_PAGAMENTO = "Fatura"        # categoria PF do pagamento da fatura no extrato
GRUPO_REGRA = "cartao_regra"          # parametros: palavras da compra -> categoria (o que você corrigiu)
LISTA = "lista_categorias_cartao"
MAX_BYTES = 5 * 1024 * 1024
MAX_PAGINAS = 40
MAX_COMPRAS = 1000
TOLERANCIA_LIMITE = 1.00              # R$: diferença entre o "usado" do banco e a conta do CRM que ainda é arredondamento
DIAS_PAGAMENTO = 5                    # pagamento da fatura no extrato: até 5 dias da data que a fatura mostra
MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}

# categoria sugerida: a primeira cuja palavra aparece na compra (descrição + ramo do Itaú, sem acento e minúsculas).
# Palavra de até 4 letras precisa ser a palavra inteira ('bar', 'iof'); maior basta estar dentro ('canva' em 'canva1234x').
PALAVRAS = [
    ("Juros e tarifas do cartão", ("iof", "juros", "multa", "encargo", "encargos", "rotativo", "anuidade", "tarifa", "mora")),
    ("Parcelamento de fatura", ("parcela de ref", "parc fatura", "parcelamento de fatura", "parcelamento fatura")),
    ("Pix no crédito", ("pix cred", "pix credito", "pix no credito")),
    ("Ferramentas de trabalho", ("anthropic", "claude", "chatgpt", "openai", "canva", "workspace", "notion", "adobe", "github")),
    ("Assinaturas", ("netflix", "spotify", "disney", "primevideo", "prime video", "hbomax", "globoplay", "deezer", "youtube",
                     "apple com", "icloud")),
    ("Delivery", ("ifd", "ifood", "rappi", "ze delivery", "aiqfome")),
    ("Compras", ("mercadolivre", "mercado livre", "amazon", "shopee", "magalu", "aliexpress", "shein", "vivara", "eletro",
                 "americanas", "kabum")),
    ("Vestuário", ("netshoes", "brooksfield", "renner", "riachuelo", "zara", "centauro", "hering", "vestuario", "roupa")),
    ("Mercado", ("market", "supermerc", "mercado", "conven", "carrefour", "assai", "atacad", "hortifruti", "oxxo")),
    ("Alimentação", ("bar", "rest", "restaurante", "lanchonete", "padaria", "doces", "pizz", "burger", "cafe", "acai", "sorvet")),
    ("Transporte", ("uber", "posto", "combustivel", "estaciona", "shell", "ipiranga", "metro", "pedagio", "sem parar")),
    ("Saúde", ("drogaria", "farmacia", "drogasil", "raia", "hospital", "clinica", "laborat", "odonto")),
    ("Educação", ("udemy", "curso", "alura", "escola", "faculdade", "hotmart")),
    ("Lazer", ("cinema", "ingresso", "sympla", "steam", "playstation", "show")),
]

logging.getLogger("pypdf").setLevel(logging.ERROR)   # fonte do Itaú sem fontTools só avisa; o texto sai certo


class ArquivoInvalido(ValueError):
    """Mensagem em português para a tela (o arquivo não é uma fatura que o CRM sabe ler)."""


# ---------- leitura ----------
def _valor(v: str) -> float:
    """'1.234,56', '-6,77', 'R$ 28,46' -> float."""
    return float(v.replace("R$", "").replace(" ", "").replace(".", "").replace(",", "."))


def _data_br(v: str) -> str:
    d, m, a = v.split("/")
    return dt.date(int(a), int(m), int(d)).isoformat()


def _achar(padrao: str, texto: str, conv=_valor):
    m = re.search(padrao, texto, re.I)
    if not m:
        return None
    try:
        return conv(m.group(1))
    except ValueError:
        return None


def _texto_pdf(conteudo: bytes) -> str:
    """Texto de todas as páginas. ArquivoInvalido se não abrir, tiver senha ou não tiver texto (foto)."""
    if len(conteudo) > MAX_BYTES:
        raise ArquivoInvalido("o arquivo passa de 5 MB")
    if not conteudo.lstrip()[:5] == b"%PDF-":
        raise ArquivoInvalido("não é um PDF")
    try:
        from pypdf import PdfReader
        pdf = PdfReader(io.BytesIO(conteudo))
        if pdf.is_encrypted:
            raise ArquivoInvalido("o PDF tem senha: baixe a fatura de novo sem senha")
        if len(pdf.pages) > MAX_PAGINAS:
            raise ArquivoInvalido(f"o PDF tem mais de {MAX_PAGINAS} páginas")
        texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except ArquivoInvalido:
        raise
    except Exception:   # PDF quebrado: qualquer erro do leitor vira a mesma mensagem
        raise ArquivoInvalido("não consegui abrir o PDF") from None
    if not texto.strip():
        raise ArquivoInvalido("o PDF não tem texto (parece uma foto): baixe a fatura pelo app do banco")
    return texto


def _parcela(desc: str, padrao: str) -> tuple[str, int | None, int | None]:
    m = re.search(padrao, desc, re.I)
    if not m:
        return desc, None, None
    num, total = int(m.group(1)), int(m.group(2))
    if not 0 < num <= total:
        return desc, None, None
    return (desc[:m.start()] + desc[m.end():]).strip(), num, total


def ler_inter(texto: str) -> dict:
    """Fatura do Inter: 'DD de mmm. AAAA  descrição  [beneficiário]  [+ ]R$ valor', agrupada por 'CARTÃO 5555****1234'.
    Compra em dólar ocupa várias linhas (a cotação fica na nota). '+ R$' é crédito: pagamento ou estorno."""
    data_ini = re.compile(r"^(\d{1,2}) de ([a-zç]{3})\.? (\d{4})\s*(.*)$", re.I)
    valor_fim = re.compile(r"(\+\s*)?R\$\s*(-?[\d.]+,\d{2})$")
    compras, pagamentos, cartao, pend = [], [], None, None

    def fechar(p, linha_valor):
        m = valor_fim.search(linha_valor)
        desc = re.sub(r"\s*-?\s*$", "", f"{p['texto']} {linha_valor[:m.start()]}").strip()   # sem o "-" de beneficiário vazio
        desc, num, total = _parcela(desc, r"\(Parcela (\d+) de (\d+)\)")
        valor = _valor(m.group(2)) * (-1 if m.group(1) else 1)
        desc = " ".join(desc.split())
        if valor < 0 and "pagamento" in financeiro._palavras(desc):
            pagamentos.append({"data": p["data"], "valor": round(-valor, 2), "descricao": desc})
            return
        compras.append({"cartao": cartao, "data": p["data"], "descricao": desc, "valor": round(valor, 2), "parcela_num": num,
                        "parcela_total": total, "ramo": None, "nota": " · ".join(p["extra"])[:200] or None})

    for bruta in texto.splitlines():
        linha = " ".join(bruta.split())
        if not linha:
            continue
        if m := re.match(r"^CART[AÃ]O\s+\d{4}\*+(\d{4})$", linha, re.I):
            cartao, pend = m.group(1), None
            continue
        if re.match(r"^\d{4}\*+\d{4} \d{2}/\d{2}/\d{4}", linha) or linha.lower().startswith("total cart"):
            if linha.lower().startswith("total cart"):
                pend = None
            elif pend and pend["extra"] and not re.search(r"\d", pend["extra"][-1]):
                pend["extra"].pop()   # rodapé da página no meio de uma compra: o nome do titular logo antes não é da compra
            continue
        m = data_ini.match(linha)
        if m and m.group(2).lower() in MESES:
            try:
                data = dt.date(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1))).isoformat()
            except ValueError:
                continue
            pend = {"data": data, "texto": "", "extra": []}
            resto = m.group(4)
            if valor_fim.search(resto):
                fechar(pend, resto)
                pend = None
            else:
                pend["texto"] = resto
            continue
        if pend is not None:
            if valor_fim.search(linha):
                fechar(pend, linha)
                pend = None
            elif len(pend["extra"]) < 6:
                pend["extra"].append(linha)
            else:
                pend = None
    venc = _achar(r"Data de Vencimento\s*(\d{2}/\d{2}/\d{4})", texto, _data_br)
    despesas = _achar(r"Despesas do m[eê]s\s*R\$\s*(-?[\d.]+,\d{2})", texto)
    return {"banco": "Inter", "conta": CONTA_INTER, "vencimento": venc, "fechamento": None,
            "total": _achar(r"Total da sua fatura\s*R\$\s*(-?[\d.]+,\d{2})", texto) or _achar(r"Fatura atual\s*R\$\s*(-?[\d.]+,\d{2})", texto),
            "esperado": despesas, "financiado": 0.0,
            "limite_total": _achar(r"Limite de cr[eé]dito total:?\s*R\$\s*(-?[\d.]+,\d{2})", texto),
            "limite_usado": _achar(r"Utilizado:\s*R\$\s*(-?[\d.]+,\d{2})", texto),
            "limite_disponivel": _achar(r"Dispon[ií]vel:\s*R\$\s*(-?[\d.]+,\d{2})", texto),
            "compras": compras, "pagamentos": pagamentos}


def _ano(dia_mes: str, ref: str) -> str:
    """'03/09' sem ano -> a data mais recente até `ref` (a fatura só traz o que aconteceu até o fechamento)."""
    d, m = (int(x) for x in dia_mes.split("/"))
    ano = int(ref[:4]) if (m, d) <= (int(ref[5:7]), int(ref[8:10])) else int(ref[:4]) - 1
    return dt.date(ano, m, d).isoformat()


def ler_itau(texto: str) -> dict:
    """Fatura do Itaú: 'DD/MM  estabelecimento [NN/TT]  valor', sem ano (vem do fechamento). A linha de baixo da compra traz o ramo
    ('ELETRONICS  CURITIBA'). Seções: Pagamentos efetuados, Lançamentos: … (compras, produtos e serviços), Encargos cobrados."""
    venc = _achar(r"Vencimento:\s*(\d{2}/\d{2}/\d{4})", texto, _data_br)
    fech = (_achar(r"Emiss[aã]o:\s*(\d{2}/\d{2}/\d{4})", texto, _data_br) or _achar(r"Postagem:\s*(\d{2}/\d{2}/\d{4})", texto, _data_br)
            or venc)
    final = _achar(r"Cart[aã]o\s+\d{4}[.\s]*X{4}[.\s]*X{4}[.\s]*(\d{4})", texto, str)
    item = re.compile(r"^(\d{2}/\d{2})\s+(.+?)\s+(-?[\d.]+,\d{2})$")
    fim = ("total", "lancamentos no cartao", "lancamentos produtos", "compras parceladas", "proxima fatura", "demais faturas",
           "limites de credito", "limite ", "novo teto", "fique atento", "simulacao")
    compras, pagamentos, modo, ultimo, cartao = [], [], None, None, final
    for bruta in texto.splitlines():
        linha = " ".join(bruta.split())
        if not linha or not fech:
            continue
        low = financeiro._sem_acento_low(linha)
        if low.startswith("pagamentos efetuados"):
            modo, ultimo = "pag", None
            continue
        if low.startswith("lancamentos:"):
            modo, ultimo = "compra", None
            continue
        if low.startswith("encargos cobrados nesta fatura"):
            modo, ultimo = "encargo", None
            continue
        if low.startswith(fim):
            modo, ultimo = None, None
            continue
        if modo in ("pag", "compra") and (m := item.match(linha)):
            try:
                data = _ano(m.group(1), fech)
            except ValueError:
                continue
            valor = _valor(m.group(3))
            if modo == "pag":
                pagamentos.append({"data": data, "valor": round(abs(valor), 2), "descricao": m.group(2)})
                continue
            desc, num, total = _parcela(m.group(2), r"\s(\d{2})/(\d{2})$")
            ultimo = {"cartao": cartao, "data": data, "descricao": desc, "valor": round(valor, 2), "parcela_num": num,
                      "parcela_total": total, "ramo": None, "nota": None}
            compras.append(ultimo)
            continue
        if modo == "compra":
            if ultimo is None:   # nome do titular/adicional antes das compras
                if f := re.search(r"final\s*(\d{4})", linha, re.I):
                    cartao = f.group(1)
                continue
            if ultimo["ramo"] is None and ultimo["nota"] is None and len(linha) >= 3:
                if re.match(r"^principal\b", low):
                    ultimo["nota"] = linha[:200]
                else:
                    ultimo["ramo"] = re.split(r"\s{2,}", bruta.strip())[0][:60] if "  " in bruta.strip() else linha.split(" ")[0][:60]
            continue
        if modo == "encargo" and (m := re.match(r"^([^\d(]+?)\s+[\d(].*?(-?[\d.]+,\d{2})$", linha)):
            if not low.startswith("total"):
                compras.append({"cartao": cartao, "data": fech, "descricao": m.group(1).strip(), "valor": round(_valor(m.group(2)), 2),
                                "parcela_num": None, "parcela_total": None, "ramo": None, "nota": None})
    total = _achar(r"Total desta fatura\s*(?:R\$\s*)?(-?[\d.]+,\d{2})", texto)
    financiado = _achar(r"Saldo financiado\s*(?:R\$\s*)?(-?[\d.]+,\d{2})", texto) or 0.0
    return {"banco": "Itaú", "conta": CONTA_ITAU, "vencimento": venc, "fechamento": fech, "total": total,
            "esperado": round(total - financiado, 2) if total is not None else None, "financiado": financiado,
            "limite_total": _achar(r"Limite total de cr[eé]dito:?\s*(?:R\$\s*)?([\d.]+,\d{2})", texto),
            "limite_usado": _achar(r"Limite total utilizado:?\s*(?:R\$\s*)?(-?[\d.]+,\d{2})", texto),
            "limite_disponivel": _achar(r"Limite dispon[ií]vel:?\s*(?:R\$\s*)?(-?[\d.]+,\d{2})", texto),
            "compras": compras, "pagamentos": pagamentos}


def _chaves(f: dict) -> None:
    """Chave fixa de cada compra (a mesma compra idêntica no mesmo dia, como dois IOF iguais, ganha 1, 2…)."""
    vistos: dict[tuple, int] = {}
    for c in f["compras"]:
        base = (c["cartao"] or "", c["data"], round(c["valor"] * 100), " ".join(financeiro._palavras(c["descricao"])),
                f"{c['parcela_num'] or ''}/{c['parcela_total'] or ''}")
        vistos[base] = vistos.get(base, 0) + 1
        texto = hashlib.sha1(f"{base[3]}|{base[4]}".encode()).hexdigest()[:10]
        c["chave"] = f"{f['conta']}:{f['vencimento']}:{base[0]}:{base[1]}:{base[2]}:{texto}:{vistos[base]}"


def ler_texto(texto: str) -> dict:
    """Descobre o banco pelo texto e lê. ArquivoInvalido com o motivo."""
    low = financeiro._sem_acento_low(texto)
    if "itau" in low and ("lancamentos:" in low or "total desta fatura" in low):
        f = ler_itau(texto)
    elif "despesas da fatura" in low or "bancointer" in low:
        f = ler_inter(texto)
    else:
        raise ArquivoInvalido("não reconheci: use a fatura em PDF do cartão Inter ou do Itaú")
    if not f["vencimento"]:
        raise ArquivoInvalido("não achei a data de vencimento da fatura")
    if f["total"] is None:
        raise ArquivoInvalido("não achei o total da fatura")
    if not f["compras"]:
        raise ArquivoInvalido("não achei nenhuma compra na fatura")
    if len(f["compras"]) > MAX_COMPRAS:
        raise ArquivoInvalido(f"a fatura tem mais de {MAX_COMPRAS} compras")
    _chaves(f)
    return f


def ler_arquivo(nome: str, conteudo: bytes) -> dict:
    f = ler_texto(_texto_pdf(conteudo))
    f["arquivo"] = (nome or "")[:120]
    return f


# ---------- categoria ----------
def _texto_regra(descricao: str) -> str:
    """As palavras que identificam a compra para a regra: a descrição sem números e sem 'parcela', no máximo 4 palavras."""
    return " ".join([w for w in financeiro._palavras(descricao) if not any(ch.isdigit() for ch in w)][:4])


def regras(con: sqlite3.Connection) -> list[tuple[list[str], str]]:
    """[(palavras, categoria)], as mais específicas primeiro."""
    out = [(texto.split(), cat) for texto, cat in db.parametros(con, GRUPO_REGRA).items() if texto and cat]
    return sorted(out, key=lambda r: -len(r[0]))


def categoria(descricao: str, ramo: str | None, regras_salvas, validas: list[str]) -> tuple[str, bool]:
    """(categoria, veio de regra sua). Regra que você ensinou > palavra-chave > 'Outros'. Sempre uma da lista."""
    palavras = financeiro._palavras(f"{descricao} {ramo or ''}")
    p = set(palavras)
    for chaves, cat in regras_salvas:
        if set(chaves) <= p and cat in validas:
            return cat, True
    texto = " ".join(palavras)
    for cat, chaves in PALAVRAS:
        if cat in validas and any((k in p) if len(k) <= 4 else (k in texto) for k in chaves):
            return cat, False
    return ("Outros" if "Outros" in validas else validas[-1]), False


# ---------- conferências ----------
def parcelas_futuras(compras: list[dict]) -> float:
    """O que as compras parceladas desta fatura ainda vão cobrar nas próximas (valor da parcela × parcelas que faltam)."""
    return round(sum(c["valor"] * (c["parcela_total"] - c["parcela_num"]) for c in compras
                     if c.get("parcela_total") and c.get("parcela_num") and c["valor"] > 0), 2)


def conferir_limite(f: dict) -> dict:
    """Usado pela conta do CRM = total da fatura + parcelas futuras. Compara com o 'usado' que o banco mostra no fechamento."""
    crm = round((f["total"] or 0) + parcelas_futuras(f["compras"]), 2)
    banco = f.get("limite_usado")
    dif = round(crm - banco, 2) if banco is not None else None
    return {"usado_crm": crm, "usado_banco": banco, "diferenca": dif,
            "bate": dif is not None and abs(dif) <= TOLERANCIA_LIMITE,
            "estourado": f.get("limite_disponivel") is not None and f["limite_disponivel"] < 0}


def pagamento_no_extrato(con: sqlite3.Connection, data: str, valor: float):
    """O lançamento de saída de uma conta (não cartão) com o mesmo valor, até DIAS_PAGAMENTO dias da data: o pagamento da fatura
    que veio do extrato ou foi lançado à mão. O mais perto da data."""
    return con.execute(
        """SELECT id, conta, escopo, categoria, COALESCE(pago_em, data) AS quando FROM lancamentos
           WHERE excluido_em IS NULL AND tipo='saida' AND ROUND(valor * 100)=? AND (conta IS NULL OR conta NOT LIKE 'Cartão%')
           AND COALESCE(pago_em, data) BETWEEN date(?, ?) AND date(?, ?)
           ORDER BY ABS(julianday(COALESCE(pago_em, data)) - julianday(?)), id LIMIT 1""",
        (round(valor * 100), data, f"-{DIAS_PAGAMENTO} days", data, f"+{DIAS_PAGAMENTO} days", data)).fetchone()


def paga_fatura(con: sqlite3.Connection, data: str, valor: float) -> str | None:
    """Saída do extrato com o valor de uma fatura importada, perto do vencimento (10 dias antes a 5 depois): o cartão que ela paga.
    O extrato usa para sugerir a categoria 'Fatura'."""
    r = con.execute("""SELECT conta FROM cartao_faturas WHERE excluido_em IS NULL AND ROUND(total * 100)=?
                       AND ? BETWEEN date(vencimento, '-10 days') AND date(vencimento, '+5 days') LIMIT 1""",
                    (round(valor * 100), data)).fetchone()
    return r["conta"] if r else None


# ---------- prévia ----------
def previa(con: sqlite3.Connection, arquivos: list[tuple[str, bytes]]) -> dict:
    """Lê todos os PDFs. {'faturas': [...], 'erros': [...]}. Cada fatura ganha: soma e se bate com o total, conferência do limite,
    pagamentos achados no extrato e, em cada compra, a categoria sugerida e se já está no CRM."""
    validas = db.lista(con, LISTA)
    if not validas:
        return {"faturas": [], "erros": ["A lista de categorias do cartão está vazia (Configurações)."]}
    regras_salvas = regras(con)
    contas = db.lista(con, "lista_contas")
    faturas, erros, vistas = [], [], set()
    for nome, conteudo in arquivos:
        try:
            f = ler_arquivo(nome, conteudo)
        except ArquivoInvalido as e:
            erros.append(f"{nome}: {e}.")
            continue
        if f["conta"] not in contas:
            erros.append(f"{nome}: a conta {f['conta']} não está na lista de contas (Configurações).")
            continue
        if (f["conta"], f["vencimento"]) in vistas:
            erros.append(f"{nome}: a mesma fatura veio duas vezes nesta importação.")
            continue
        vistas.add((f["conta"], f["vencimento"]))
        ja = {r[0] for r in con.execute("SELECT chave FROM cartao_compras WHERE chave LIKE ?", (f"{f['conta']}:{f['vencimento']}:%",))}
        for c in f["compras"]:
            c["categoria"], c["por_regra"] = categoria(c["descricao"], c["ramo"], regras_salvas, validas)
            c["categoria_sugerida"] = c["categoria"]
            c["existe"] = c["chave"] in ja
        soma = round(sum(c["valor"] for c in f["compras"]), 2)
        f["soma"] = soma
        f["confere"] = f["esperado"] is not None and abs(soma - f["esperado"]) < 0.05
        f["limite"] = conferir_limite(f)
        for p in f["pagamentos"]:
            r = pagamento_no_extrato(con, p["data"], p["valor"])
            p["lancamento"] = dict(r) if r else None
        antes = con.execute("SELECT importado_em FROM cartao_faturas WHERE conta=? AND vencimento=? AND excluido_em IS NULL",
                            (f["conta"], f["vencimento"])).fetchone()
        f["importada_em"] = antes[0] if antes else None
        f["novas"] = sum(1 for c in f["compras"] if not c["existe"])
        faturas.append(f)
    return {"faturas": faturas, "erros": erros}


# ---------- gravação ----------
def salvar(con: sqlite3.Connection, faturas: list[dict], marcar: set[int]) -> dict:
    """Grava numa transação: a fatura (ou atualiza o limite e o total, se já existe), as compras novas (a chave barra a repetida) e
    as regras de categoria que você corrigiu. `marcar`: lançamentos do extrato que pagam a fatura e passam para a categoria 'Fatura'."""
    cont = {"faturas": 0, "atualizadas": 0, "compras": 0, "existentes": 0, "regras": 0, "pagamentos": 0}
    aprendidas: set[str] = set()
    with con:
        for f in faturas:
            r = con.execute("SELECT id FROM cartao_faturas WHERE conta=? AND vencimento=? AND excluido_em IS NULL",
                            (f["conta"], f["vencimento"])).fetchone()
            campos = (f["fechamento"], f["total"], f["limite_total"], f["limite_usado"], f["limite_disponivel"], f["arquivo"])
            if r:
                fid = r[0]
                con.execute("""UPDATE cartao_faturas SET fechamento=?, total=?, limite_total=?, limite_usado=?, limite_disponivel=?,
                               arquivo=?, importado_em=datetime('now','localtime') WHERE id=?""", (*campos, fid))
                cont["atualizadas"] += 1
            else:
                fid = con.execute("""INSERT INTO cartao_faturas (conta, vencimento, fechamento, total, limite_total, limite_usado,
                                     limite_disponivel, arquivo) VALUES (?,?,?,?,?,?,?,?)""", (f["conta"], f["vencimento"], *campos)).lastrowid
                cont["faturas"] += 1
            for c in f["compras"]:
                n = con.execute("""INSERT OR IGNORE INTO cartao_compras (fatura_id, chave, cartao, data, descricao, valor, parcela_num,
                                   parcela_total, categoria, ramo, nota) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                                (fid, c["chave"], c["cartao"], c["data"], c["descricao"], c["valor"], c["parcela_num"],
                                 c["parcela_total"], c["categoria"], c["ramo"], c["nota"])).rowcount
                if not n:
                    cont["existentes"] += 1
                    continue
                cont["compras"] += 1
                if c["categoria"] != c["categoria_sugerida"] and (texto := _texto_regra(c["descricao"])):
                    con.execute("""INSERT INTO parametros (grupo, chave, valor_texto, ordem) VALUES (?, ?, ?, 0)
                                   ON CONFLICT (grupo, chave) DO UPDATE SET valor_texto=excluded.valor_texto""",
                                (GRUPO_REGRA, texto, c["categoria"]))
                    aprendidas.add(texto)
            con.execute("INSERT INTO importacoes (arquivo, resumo) VALUES (?, ?)",
                        (f"fatura:{f['conta']}", json.dumps({"vencimento": f["vencimento"], "compras": len(f["compras"])}, ensure_ascii=False)))
        for lid in sorted(marcar):
            cont["pagamentos"] += con.execute(
                """UPDATE lancamentos SET categoria=? WHERE id=? AND tipo='saida' AND escopo='PF' AND categoria<>? AND excluido_em IS NULL""",
                (CATEGORIA_PAGAMENTO, lid, CATEGORIA_PAGAMENTO)).rowcount
        cont["regras"] = len(aprendidas)
    return cont


# ---------- tela Cartões ----------
def cartoes(con: sqlite3.Connection) -> list[dict]:
    """A última fatura de cada cartão: limite total, usado e disponível do banco, e a conferência com a conta do CRM."""
    out = []
    for r in con.execute("""SELECT f.* FROM cartao_faturas f WHERE f.excluido_em IS NULL AND f.vencimento = (
                              SELECT MAX(vencimento) FROM cartao_faturas g WHERE g.conta = f.conta AND g.excluido_em IS NULL)
                            ORDER BY f.conta"""):
        compras = [dict(c) for c in con.execute("SELECT valor, parcela_num, parcela_total FROM cartao_compras WHERE fatura_id=?", (r["id"],))]
        out.append({**dict(r), **conferir_limite({**dict(r), "compras": compras})})
    return out


def avisos(con: sqlite3.Connection) -> list[str]:
    """Textos para o painel: cartão com limite estourado ou com o usado do banco diferente da conta do CRM."""
    out = []
    for c in cartoes(con):
        if c["estourado"]:
            out.append(f"{c['conta']}: limite estourado em {financeiro.moeda_br(-c['limite_disponivel'])} na última fatura")
        elif c["usado_banco"] is not None and not c["bate"]:
            out.append(f"{c['conta']}: o limite usado do banco não bate com o CRM (diferença de {financeiro.moeda_br(abs(c['diferenca']))})")
    return out


def meses(con: sqlite3.Connection, n: int = 6) -> list[str]:
    """Os últimos n meses (AAAA-MM do vencimento) com fatura importada, do mais antigo ao mais novo."""
    rs = con.execute("""SELECT DISTINCT substr(vencimento, 1, 7) FROM cartao_faturas WHERE excluido_em IS NULL
                        ORDER BY 1 DESC LIMIT ?""", (n,)).fetchall()
    return sorted(r[0] for r in rs)


def por_categoria(con: sqlite3.Connection, lista_meses: list[str]) -> dict:
    """{'linhas': [{categoria, valores: {mes: total}, total}], 'totais': {mes: total}}: gastos do cartão por categoria e mês da fatura,
    das categorias que mais gastaram para as que menos."""
    if not lista_meses:
        return {"linhas": [], "totais": {}}
    marcas = ",".join("?" * len(lista_meses))
    linhas: dict[str, dict] = {}
    totais = {m: 0.0 for m in lista_meses}
    for r in con.execute(f"""SELECT c.categoria, substr(f.vencimento, 1, 7) AS mes, SUM(c.valor) AS total FROM cartao_compras c
                             JOIN cartao_faturas f ON f.id = c.fatura_id WHERE f.excluido_em IS NULL
                             AND substr(f.vencimento, 1, 7) IN ({marcas}) GROUP BY c.categoria, mes""", lista_meses):
        l = linhas.setdefault(r["categoria"], {"categoria": r["categoria"], "valores": {}, "total": 0.0})
        l["valores"][r["mes"]] = round(r["total"], 2)
        l["total"] = round(l["total"] + r["total"], 2)
        totais[r["mes"]] = round(totais[r["mes"]] + r["total"], 2)
    return {"linhas": sorted(linhas.values(), key=lambda l: -l["total"]), "totais": totais}


def compras_do_mes(con: sqlite3.Connection, mes: str) -> list[dict]:
    """Compras das faturas que vencem no mês, por categoria e data."""
    return [dict(r) for r in con.execute(
        """SELECT c.*, f.conta FROM cartao_compras c JOIN cartao_faturas f ON f.id = c.fatura_id
           WHERE f.excluido_em IS NULL AND substr(f.vencimento, 1, 7)=? ORDER BY c.categoria, c.data, c.id""", (mes,))]
