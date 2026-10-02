"""Conexão SQLite, criação do esquema, parâmetros iniciais e backup."""
import datetime as dt
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "crm.db"
SCHEMA = ROOT / "app" / "schema.sql"
BACKUP_DIR = ROOT / "data" / "backups"   # local e fora do git (data/ é ignorado)
PLANILHA = Path(r"C:\Users\victo\OneDrive\Documentos\Contabilidade.xlsx")
MANTER_BACKUPS = 30

# (grupo, chave, valor, valor_texto, ordem) — semeado só se ainda não existir (INSERT OR IGNORE)
PARAMETROS_INICIAIS = [
    ("imposto", "DAS", 0.06, None, 1),
    ("taxa_pagamento", "PIX", 0.0, None, 1),
    ("taxa_pagamento", "Cartão 1x", 0.0581, None, 2),
    ("taxa_pagamento", "Cartão 3x", 0.0765, None, 3),
    ("taxa_pagamento", "Cartão 6x", 0.104, None, 4),
    ("taxa_pagamento", "Cartão 12x", 0.159, None, 5),
    ("margem_minima", "Pacote de Aulas", 0.15, None, 1),
    ("margem_minima", "Mensalidade", 0.15, None, 2),
    ("margem_minima", "Consultoria Online", 0.20, None, 3),
    ("margem_minima", "Consultoria Híbrida", 0.22, None, 4),
    ("margem_minima", "Avaliação Física", 0.20, None, 5),
    ("taxa_cia", "1", 70.76, None, 1),
    ("taxa_cia", "2", 99.69, None, 2),
    ("taxa_cia", "3", 151.47, None, 3),
    ("taxa_cia", "maximo_pessoas", 3, None, 4),
    ("grupo_multiplicador", "1", 1.0, None, 1),
    ("grupo_multiplicador", "2", 1.6, None, 2),
    ("grupo_multiplicador", "3", 2.1, None, 3),
    ("grupo_multiplicador", "4", 2.5, None, 4),
    ("grupo_mao_obra_extra", "1", 0.0, None, 1),
    ("grupo_mao_obra_extra", "2", 0.20, None, 2),
    ("grupo_mao_obra_extra", "3", 0.35, None, 3),
    ("grupo_mao_obra_extra", "4", 0.55, None, 4),
    ("metas", "clientes_dez26", 14, None, 1),
    ("metas", "clientes_mar27", 18, None, 2),
    ("metas", "horas_vendaveis", 97, None, 3),
    ("metas", "horas_dez26", 82, None, 4),
    ("metas", "horas_mar27", 90, None, 5),
    ("metas", "lucro_hora_dez26", 30, None, 6),
    ("metas", "lucro_hora_mar27", 45, None, 7),
    ("metas", "pct_grupos_dez26", 0.15, None, 8),
    ("metas", "pct_grupos_mar27", 0.30, None, 9),
    ("metas", "recorrente_dez26", 9500, None, 10),
    ("metas", "recorrente_mar27", 12000, None, 11),
    ("metas", "perdidos_max", 1, None, 12),
    ("metas", "conv_conversa", 0.60, None, 13),
    ("metas", "conv_avaliacao", 0.40, None, 14),
    ("metas", "conv_fechamento", 0.50, None, 15),
    ("metas", "cac_max", 300, None, 16),
    ("metas", "ltv_cac_min", 3, None, 17),
    ("metas", "preco_base_reajuste", 0, None, 18),
    ("lead_parado_dias", "lead", 2, None, 1),
    ("lead_parado_dias", "conversa", 4, None, 2),
    ("lead_parado_dias", "avaliacao", 2, None, 3),
]
LISTAS_INICIAIS = {
    "lista_canais": ["Indicação", "Parceria (síndico/academia)", "WhatsApp", "Google", "Instagram orgânico",
                     "Instagram Ads", "Stadami", "Conecta Fitness", "TreinarMe", "PersonalGo", "Outro"],
    "lista_locais": ["CIA", "SmartFit", "Condomínio", "Online"],
    "lista_tipos_servico": ["Pacote de Aulas", "Mensalidade", "Consultoria Online", "Consultoria Híbrida",
                            "Avaliação Física"],
    "lista_formas_pagamento": ["PIX", "Cartão 1x", "Cartão 3x", "Cartão 6x", "Cartão 12x"],
}
FASES_INICIAIS = [
    ("Fase 0 — Ajustar a planilha", "2026-09-17", "2026-09-20", "fase"),
    ("Fase 1 — Grupos nos horários de vale", "2026-09-21", "2026-10-11", "fase"),
    ("Fase 2 — Pré-venda (início 03/11)", "2026-10-12", "2026-10-24", "fase"),
    ("Bloqueio — Casamento e lua de mel (sem aulas nem vendas)", "2026-10-25", "2026-11-02", "bloqueio"),
    ("Fase 3 — Retomar e medir", "2026-11-03", "2026-12-31", "fase"),
    ("Fase 4 — Escalar", "2027-01-01", "2027-03-31", "fase"),
]
CHECKPOINTS_INICIAIS = [
    ("Conecta Fitness trouxe cliente até 24/10?", "Conecta Fitness", "2026-10-24"),
    ("Stadami trouxe cliente até 31/10?", "Stadami", "2026-10-31"),
]


def conectar(caminho: Path = None) -> sqlite3.Connection:
    con = sqlite3.connect(caminho or DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def iniciar_banco(caminho: Path = None) -> None:
    """Cria tabelas e dados iniciais. Seguro de rodar várias vezes."""
    caminho = caminho or DB_PATH
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = conectar(caminho)
    with con:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        con.executemany(
            "INSERT OR IGNORE INTO parametros (grupo, chave, valor, valor_texto, ordem) VALUES (?,?,?,?,?)",
            PARAMETROS_INICIAIS,
        )
        for grupo, itens in LISTAS_INICIAIS.items():
            con.executemany(
                "INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem) VALUES (?,?,?,?)",
                [(grupo, nome, nome, i) for i, nome in enumerate(itens, 1)],
            )
        if con.execute("SELECT COUNT(*) FROM campanha_fases").fetchone()[0] == 0:
            con.executemany(
                "INSERT INTO campanha_fases (nome, inicio, fim, tipo, ordem) VALUES (?,?,?,?,?)",
                [(n, i, f, t, k) for k, (n, i, f, t) in enumerate(FASES_INICIAIS, 1)],
            )
        if con.execute("SELECT COUNT(*) FROM campanha_checkpoints").fetchone()[0] == 0:
            con.executemany(
                "INSERT INTO campanha_checkpoints (pergunta, canal, prazo) VALUES (?,?,?)", CHECKPOINTS_INICIAIS
            )
    con.close()


# ---------- parâmetros ----------
def parametros(con: sqlite3.Connection, grupo: str) -> dict:
    """{chave: valor} (ou valor_texto quando valor é NULL), na ordem cadastrada."""
    rows = con.execute(
        "SELECT chave, valor, valor_texto FROM parametros WHERE grupo=? ORDER BY ordem, chave", (grupo,)
    ).fetchall()
    return {r["chave"]: (r["valor"] if r["valor"] is not None else r["valor_texto"]) for r in rows}


def lista(con: sqlite3.Connection, nome: str) -> list[str]:
    return list(parametros(con, nome).values())


# ---------- backup ----------
def pasta_backup() -> Path:
    """Pasta local de backups (criada se não existir)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def fazer_backup(prefixo: str = "crm") -> Path:
    """Cópia consistente do banco (API de backup do SQLite). Mantém os últimos MANTER_BACKUPS."""
    pasta = pasta_backup()
    destino = pasta / f"{prefixo}-{dt.datetime.now():%Y-%m-%d_%H%M%S}.db"
    origem = sqlite3.connect(DB_PATH)
    copia = sqlite3.connect(destino)
    with copia:
        origem.backup(copia)
    copia.close()
    origem.close()
    for antigo in sorted(pasta.glob(f"{prefixo}-*.db"))[:-MANTER_BACKUPS]:
        antigo.unlink()
    return destino


def backup_diario() -> Path | None:
    """Um backup por dia, feito ao abrir o CRM."""
    hoje = dt.date.today().isoformat()
    if any(pasta_backup().glob(f"crm-{hoje}_*.db")):
        return None
    return fazer_backup()


def listar_backups() -> list[dict]:
    itens = []
    for f in sorted(pasta_backup().glob("*.db"), reverse=True):
        st = f.stat()
        itens.append({"nome": f.name, "quando": dt.datetime.fromtimestamp(st.st_mtime), "kb": round(st.st_size / 1024)})
    return itens


def restaurar_backup(nome: str) -> Path:
    """Substitui o banco atual por um backup. Antes, guarda o banco atual como 'antes-restaurar-*'."""
    origem = pasta_backup() / Path(nome).name
    if not origem.exists() or origem.suffix != ".db":
        raise FileNotFoundError(nome)
    teste = sqlite3.connect(origem.as_uri() + "?mode=ro", uri=True)
    try:
        ok = teste.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except sqlite3.DatabaseError:
        ok = False
    finally:
        teste.close()   # fecha antes do copy2 (Windows trava arquivo aberto)
    if not ok:
        raise ValueError(f"O arquivo {origem.name} está corrompido ou não é um banco do CRM. Nada foi alterado.")
    seguranca = fazer_backup("antes-restaurar")
    shutil.copy2(origem, DB_PATH)
    return seguranca
