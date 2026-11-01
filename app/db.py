"""Conexão SQLite, criação do esquema, parâmetros iniciais e backup."""
import datetime as dt
import shutil
import sqlite3
from pathlib import Path

from . import nuvem

ROOT = Path(__file__).resolve().parent.parent
DB_LOCAL = ROOT / "data" / "crm.db"
# com Turso, a réplica local é outro arquivo: o crm.db antigo fica intacto como fonte do envio (python -m app.subir_nuvem)
DB_PATH = ROOT / "data" / "crm-nuvem.db" if nuvem.ativo() and not nuvem.SO_ADAPTADOR else DB_LOCAL
SCHEMA = ROOT / "app" / "schema.sql"
BACKUP_DIR = ROOT / "data" / "backups"   # local e fora do git (data/ é ignorado)
PLANILHA = Path(r"C:\Users\victo\OneDrive\Documentos\Contabilidade.xlsx")
MANTER_BACKUPS = 30

# textos padrão antigos dos modelos de WhatsApp: o banco só troca para o novo se o texto salvo ainda é exatamente o antigo (senão o usuário editou)
RENOVACAO_ANTIGA = "Oi, {nome}! Sua renovação está marcada para {data}. Vamos combinar a continuação dos treinos? Victor | VFITCOACH"
RENOVACAO_NOVA = ("Oi, {nome}! Sua renovação é em {data}: {valor}. PIX: {pix}. Pode me mandar o comprovante? Victor | VFITCOACH")
INDICACAO_ANTIGA = ("Oi, {nome}! Tá curtindo os treinos? Se você conhece alguém que quer começar, me indica! "
                                        "Quando a pessoa fechar, você ganha um presente meu 🎁 Victor | VFITCOACH")
INDICACAO_NOVA = ("Oi, {nome}! Tá curtindo os treinos? Se você conhece alguém que quer começar, me indica! "
                  "Quando a pessoa fechar, você ganha {vantagem} 🎁 Victor | VFITCOACH")

# (grupo, chave, valor, valor_texto, ordem) — semeado só se ainda não existir (INSERT OR IGNORE)
PARAMETROS_INICIAIS = [
    ("msg_whatsapp", "renovacao", None, RENOVACAO_NOVA, 1),
    ("msg_whatsapp", "falta", None, "Oi, {nome}! Senti sua falta nos treinos (última aula em {data}). Está tudo bem? Vamos remarcar? Victor | VFITCOACH", 2),
    ("msg_whatsapp", "boas_vindas", None, "Oi, {nome}! Seja bem-vindo(a) à VFITCOACH! Fico feliz em começar essa jornada com você. Victor | VFITCOACH", 3),
    ("msg_whatsapp", "reativacao", None, "Oi, {nome}! Faz tempo que não nos falamos. Que tal retomarmos os treinos? Tenho novidades para você. Victor | VFITCOACH", 4),
    ("msg_whatsapp", "cobranca", None, "Oi, {nome}! Tudo bem? Passando para lembrar do pagamento em aberto desde {data} ({dias} dias de atraso): "
                                       "{valor} + multa de {multa} + juros de {juros} = {total}. Pode me mandar o comprovante quando pagar? "
                                       "Obrigado! Victor | VFITCOACH", 5),
    # campanhas que o CRM sugere (Saúde financeira): agregam valor ao trabalho, nunca dão desconto
    ("msg_whatsapp", "indicacao", None, INDICACAO_NOVA, 6),
    ("msg_whatsapp", "dupla", None, "Oi, {nome}! Que tal treinar com um amigo ou amiga? Em dupla o treino rende mais, é mais animado e "
                                    "vocês se cobram um ao outro. Quer trazer alguém? Victor | VFITCOACH", 7),
    ("msg_whatsapp", "depoimento", None, "Oi, {nome}! Seu treino comigo tem feito diferença? Você toparia me mandar um depoimento curto (texto ou vídeo)? "
                                         "{link_avaliacao} Obrigado! 🙏 Victor | VFITCOACH", 8),
    # dados que entram nas mensagens ({pix}, {link_avaliacao}, {vantagem}); a chave PIX começa vazia, o CRM avisa para cadastrar
    ("msg_dados", "pix", None, "", 1),
    ("msg_dados", "link_avaliacao", None, "", 2),
    ("msg_dados", "vantagem", None, "uma avaliação física grátis", 3),
    # oferta de upsell (Campanhas): {duracao}, {depois} e {ate} já vêm escritos ou vazios; nada fica pendurado
    ("msg_whatsapp", "upsell", None, "Oi, {nome}! Tenho uma proposta: {titulo}. Inclui: {inclui}. De {valor_normal} por {valor_oferta}/mês{duracao}{depois}.{ate} "
                                     "Quer aproveitar? Victor | VFITCOACH", 9),
    # cobrança de mensalidade atrasada (botão "Cobrar" no alerta): multa uma vez + juros ao mês proporcional aos dias
    ("cobranca", "multa", 0.02, None, 1),
    ("cobranca", "juros_ao_mes", 0.01, None, 2),
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
    ("funil_chance", "lead", 0.10, None, 1),
    ("funil_chance", "conversa", 0.30, None, 2),
    ("funil_chance", "avaliacao", 0.60, None, 3),
    ("fiscal", "salario_minimo", 1518, None, 1),   # R$; pró-labore nunca fica abaixo disto
    ("fiscal", "pro_labore_pct", 0.28, None, 2),   # fração da receita (0,28 = 28%)
    ("fiscal", "inss_pct", 0.11, None, 3),         # fração do pró-labore
    ("salario", "valor", 0, None, 1),              # R$ por mês que a PJ paga à PF; 0 = desligado
    ("salario", "dia", 5, None, 2),                # dia do mês do pagamento
    ("previsao", "dia_recebimento", 10, None, 1),  # dia em que a previsão põe as mensalidades que faltam receber
    ("previsao", "dia_das", 20, None, 2),          # vencimento do DAS (sobre a receita do mês anterior)
    ("colchao", "meses", 0, None, 1),              # meta da Reserva em meses de custo fixo; 0 = sem meta ainda
    ("familia", "pessoas", 2, None, 1),            # quantas pessoas vivem da renda da PF (renda e custo de vida por pessoa na Saúde financeira)
    ("saude", "reserva_mensal_desejada", 0, None, 1),   # R$ por mês que o negócio deveria render para a reserva (ponto de equilíbrio econômico)
    # frente de cada conta no Saldo livre: PF, PJ, Reserva (dinheiro guardado, fica fora do livre) ou Fora (cartões)
    ("conta_escopo", "Contabilizei Bank", None, "PJ", 1),
    ("conta_escopo", "Inter", None, "PF", 2),
    ("conta_escopo", "Itaú", None, "PF", 3),
    ("conta_escopo", "Caixa", None, "PF", 4),
    ("conta_escopo", "Mercado Pago", None, "PF", 5),
    ("conta_escopo", "Cartão Inter", None, "Fora", 6),
    ("conta_escopo", "Cartão Itaú", None, "Fora", 7),
]
# Fila de pagamento (nota de impacto). Chave = "frente categoria". curto = o quanto atrasar atrapalha agora (0 a 40);
# juros = multa + juros por mês de atraso. Categoria sem padrão: 20 e 2%. Editáveis em Configurações.
_IMPACTO = [
    ("PJ Aluguel", 40, 0.11), ("PJ Internet/Telefone", 40, 0.03), ("PJ Software/Assinaturas", 40, 0.02),
    ("PJ Material de Trabalho", 30, 0), ("PJ Transporte", 30, 0), ("PJ Retirada", 30, 0), ("PJ Manutenção", 20, 0.02),
    ("PJ Impostos/Taxas", 20, 0.11), ("PJ Empréstimo (devolução)", 20, 0.08), ("PJ Alimentação", 10, 0),
    ("PJ Marketing/Divulgação", 0, 0), ("PJ Outros", 0, 0),
    ("PF Moradia", 40, 0.11), ("PF Saúde", 40, 0.02), ("PF Alimentação", 40, 0), ("PF Fatura", 20, 0.15), ("PF Dívidas", 20, 0.08),
    ("PF Transporte", 20, 0), ("PF Educação", 10, 0.02), ("PF Pessoal", 0, 0), ("PF Lazer", 0, 0), ("PF Vestuário", 0, 0),
    ("PF Outros", 0, 0),
]
PARAMETROS_INICIAIS += [("impacto_curto", k, c, None, i) for i, (k, c, _) in enumerate(_IMPACTO, 1)]
PARAMETROS_INICIAIS += [("impacto_juros", k, j, None, i) for i, (k, _, j) in enumerate(_IMPACTO, 1)]
LISTAS_INICIAIS = {
    "lista_canais": ["Indicação", "Parceria (síndico/academia)", "WhatsApp", "Google", "Instagram orgânico",
                     "Instagram Ads", "Stadami", "Conecta Fitness", "TreinarMe", "PersonalGo", "Outro"],
    "lista_locais": ["CIA", "SmartFit", "Condomínio", "Online"],
    "lista_tipos_servico": ["Pacote de Aulas", "Mensalidade", "Consultoria Online", "Consultoria Híbrida",
                            "Avaliação Física"],
    "lista_formas_pagamento": ["PIX", "Cartão 1x", "Cartão 3x", "Cartão 6x", "Cartão 12x"],
    # financeiro (lista_formas_pagamento acima é de preço; não reaproveitar)
    "lista_categorias_pj": ["Pacotes de Aulas", "Mensalidade (Aulas Presenciais)", "Consultoria Online",
                            "Consultoria Híbrida", "Empréstimo", "Retirada", "Empréstimo (devolução)", "Aluguel",
                            "Internet/Telefone", "Material de Trabalho",
                            "Transporte", "Marketing/Divulgação", "Impostos/Taxas", "Alimentação",
                            "Software/Assinaturas", "Manutenção", "Outros"],
    "lista_categorias_pf": ["Alimentação", "Moradia", "Transporte", "Pessoal", "Lazer", "Educação", "Vestuário",
                            "Saúde", "Salário", "Dívidas", "Fatura", "Outros"],
    "lista_formas_lancamento": ["PIX", "Transferência", "Boleto", "Dinheiro", "Cartão Crédito", "Cartão Débito",
                                "Débito Auto"],
    "lista_contas": ["Contabilizei Bank", "Inter", "Itaú", "Caixa", "Mercado Pago", "Cartão Inter", "Cartão Itaú"],
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
ROTINA_INICIAL = [   # (chave, texto, dia: 1=segunda ... 7=domingo; None = sem dia)
    ("segunda_grade", "atualizar a grade", 1),
    ("quarta_leads", "lançar os leads por canal", 3),
    ("sexta_propostas", "revisar as propostas", 5),
    ("fim_mes", "Último dia do mês: fechar o histórico e comparar com as metas", None),
]


def conectar(caminho: Path = None) -> sqlite3.Connection:
    if nuvem.ativo():
        return nuvem.conectar(caminho or DB_PATH)
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
        for chave, antigo, novo in (("renovacao", RENOVACAO_ANTIGA, RENOVACAO_NOVA), ("indicacao", INDICACAO_ANTIGA, INDICACAO_NOVA)):
            con.execute("UPDATE parametros SET valor_texto=? WHERE grupo='msg_whatsapp' AND chave=? AND valor_texto=?", (novo, chave, antigo))
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
        _garantir_coluna(con, "campanha_checkpoints", "excluido_em", "TEXT")   # banco de antes de dar para excluir
        _garantir_coluna(con, "lancamentos", "sem_recorrencia", "INTEGER")     # banco de antes de ligar saída à recorrência
        _garantir_coluna(con, "recorrencias", "prioridade", "INTEGER")         # banco de antes da fila de pagamento
        _garantir_coluna(con, "cliente_eventos", "hora", "INTEGER")            # banco de antes da Agenda
        _garantir_coluna(con, "agenda_avulsas", "reposicao", "INTEGER DEFAULT 0")   # banco de antes do controle de reposições
        _garantir_coluna(con, "agenda_avulsas", "repoe_evento_id", "INTEGER")  # banco de antes de ligar a reposição à desmarcação
        _garantir_coluna(con, "clientes", "renovacao_em", "TEXT")              # banco de antes da renovação pelo pagamento
        _garantir_coluna(con, "cliente_eventos", "ate", "TEXT")                # banco de antes do "pulou o mês"
        _garantir_coluna(con, "cliente_eventos", "usado_em", "TEXT")           # banco de antes do crédito do aluno
        _garantir_coluna(con, "cliente_eventos", "usado_lancamento_id", "INTEGER")
        _garantir_coluna(con, "clientes", "indicado_por", "INTEGER")           # banco de antes das indicações
        _garantir_coluna(con, "leads", "indicado_por", "INTEGER")
        _garantir_coluna(con, "cliente_eventos", "indicado_id", "INTEGER")
        if con.execute("SELECT COUNT(*) FROM campanha_checkpoints").fetchone()[0] == 0:
            con.executemany(
                "INSERT INTO campanha_checkpoints (pergunta, canal, prazo) VALUES (?,?,?)", CHECKPOINTS_INICIAIS
            )
        # excluídos continuam na tabela (lixeira): a contagem só é 0 na primeira vez
        if con.execute("SELECT COUNT(*) FROM rotina_tarefas").fetchone()[0] == 0:
            con.executemany(   # OR IGNORE: PC e Render podem criar ao mesmo tempo no Turso
                "INSERT OR IGNORE INTO rotina_tarefas (chave, texto, dia, ordem) VALUES (?,?,?,?)",
                [(c, txt, d, k) for k, (c, txt, d) in enumerate(ROTINA_INICIAL, 1)],
            )
        # tarefa que veio com o Saldo livre: entra também em banco antigo (excluída fica na lixeira e não volta)
        con.execute("""INSERT OR IGNORE INTO rotina_tarefas (chave, texto, dia, ordem)
                       VALUES ('saldos', 'atualizar os saldos das contas e olhar o Saldo livre', 1,
                               (SELECT COALESCE(MAX(ordem), 0) + 1 FROM rotina_tarefas))""")
    con.close()


def _garantir_coluna(con, tabela: str, coluna: str, tipo: str) -> None:
    """Acrescenta a coluna se o banco for de uma versão anterior (CREATE TABLE IF NOT EXISTS não mexe em tabela existente)."""
    if coluna in {r[1] for r in con.execute(f"PRAGMA table_info({tabela})").fetchall()}:
        return
    try:
        con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():   # PC e Render acrescentando ao mesmo tempo no Turso
            raise


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


def fazer_backup(prefixo: str = "crm", arquivo: Path = None) -> Path:
    """Cópia consistente do banco (API de backup do SQLite). Mantém os últimos MANTER_BACKUPS."""
    pasta = pasta_backup()
    destino = pasta / f"{prefixo}-{dt.datetime.now():%Y-%m-%d_%H%M%S}.db"
    origem = sqlite3.connect(arquivo or DB_PATH)   # a réplica do Turso também é um arquivo SQLite comum
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
        has_clientes = teste.execute("SELECT 1 FROM sqlite_master WHERE name='clientes'").fetchone() is not None
        ok = ok and has_clientes
    except sqlite3.DatabaseError:
        ok = False
    finally:
        teste.close()   # fecha antes do copy2 (Windows trava arquivo aberto)
    if not ok:
        raise ValueError(f"O arquivo {origem.name} está corrompido ou não é um banco do CRM. Nada foi alterado.")
    seguranca = fazer_backup("antes-restaurar")
    if nuvem.ativo():   # trocar o arquivo da réplica quebraria a sincronização: regrava os dados pela conexão
        con = conectar()
        try:
            nuvem.copiar_dados(origem, con)
        finally:
            con.close()
    else:
        shutil.copy2(origem, DB_PATH)
    iniciar_banco()   # backup antigo pode não ter tabelas novas; idempotente
    return seguranca
