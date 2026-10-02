-- VFITCOACH CRM — esquema do banco (SQLite)
-- Datas em ISO (AAAA-MM-DD) no banco; exibidas como dd/mm/aaaa.
-- excluido_em: NULL = ativo; preenchido = na lixeira (restaurável por 30 dias).

CREATE TABLE IF NOT EXISTS parametros (
    id INTEGER PRIMARY KEY,
    grupo TEXT NOT NULL,
    chave TEXT NOT NULL,
    valor REAL,
    valor_texto TEXT,
    ordem INTEGER DEFAULT 0,
    UNIQUE (grupo, chave)
);

CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    telefone TEXT,
    local TEXT,
    tipo_servico TEXT,
    plano TEXT,
    pessoas INTEGER DEFAULT 1,
    dias_horarios TEXT,
    valor REAL DEFAULT 0,
    forma_pagamento TEXT,
    status TEXT NOT NULL DEFAULT 'ativo',
    canal_origem TEXT,
    data_inicio TEXT,
    data_renovacao TEXT,
    observacoes TEXT,
    planilha_id INTEGER UNIQUE,
    lead_id INTEGER,
    criado_em TEXT DEFAULT (datetime('now','localtime')),
    atualizado_em TEXT DEFAULT (datetime('now','localtime')),
    excluido_em TEXT
);

CREATE TABLE IF NOT EXISTS cliente_eventos (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    tipo TEXT NOT NULL,              -- pagamento | renovacao | anotacao | aula
    data TEXT NOT NULL,
    valor REAL,
    descricao TEXT,
    criado_em TEXT DEFAULT (datetime('now','localtime')),
    excluido_em TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    telefone TEXT,
    canal_origem TEXT NOT NULL,
    etapa TEXT NOT NULL DEFAULT 'lead',   -- lead | conversa | avaliacao | cliente | perdido
    motivo_perda TEXT,
    proxima_acao TEXT,
    data_proxima_acao TEXT,
    interesse TEXT,
    observacoes TEXT,
    cliente_id INTEGER,
    data_entrada TEXT DEFAULT (date('now','localtime')),
    data_mudanca_etapa TEXT DEFAULT (date('now','localtime')),
    criado_em TEXT DEFAULT (datetime('now','localtime')),
    atualizado_em TEXT DEFAULT (datetime('now','localtime')),
    excluido_em TEXT
);

CREATE TABLE IF NOT EXISTS lead_etapas_log (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES leads(id),
    etapa TEXT NOT NULL,
    data TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS precos_base (
    id INTEGER PRIMARY KEY,
    tipo_servico TEXT NOT NULL,
    local TEXT NOT NULL,
    forma_pagamento TEXT NOT NULL,
    qtd_aulas INTEGER DEFAULT 0,
    freq_semanal INTEGER DEFAULT 0,
    sessoes_mes REAL DEFAULT 0,
    preco_base REAL NOT NULL,
    custo_operacional REAL DEFAULT 0,
    mao_obra REAL DEFAULT 0,
    custo_total REAL DEFAULT 0,
    origem TEXT DEFAULT 'manual',
    UNIQUE (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal)
);

CREATE TABLE IF NOT EXISTS grade_slots (
    id INTEGER PRIMARY KEY,
    tipo_calculo TEXT NOT NULL,      -- Pacotes | Mensalidades
    dia INTEGER NOT NULL,            -- 1=Seg ... 7=Dom
    local TEXT NOT NULL,
    hora INTEGER NOT NULL,           -- 5..23
    status TEXT NOT NULL DEFAULT 'livre',   -- livre | ocupado | indisponivel
    cliente_id INTEGER,
    cliente_nome TEXT,
    bloqueio TEXT,
    multiplicador REAL DEFAULT 1,
    UNIQUE (tipo_calculo, dia, local, hora)
);

CREATE TABLE IF NOT EXISTS propostas (
    id INTEGER PRIMARY KEY,
    data TEXT DEFAULT (date('now','localtime')),
    lead_id INTEGER,
    cliente_id INTEGER,
    tipo_servico TEXT NOT NULL,
    qtd_aulas INTEGER DEFAULT 0,
    freq_semanal INTEGER DEFAULT 0,
    local TEXT,
    forma_pagamento TEXT,
    pessoas INTEGER DEFAULT 1,
    dia INTEGER,
    hora INTEGER,
    desconto REAL DEFAULT 0,
    preco_total REAL,
    preco_pessoa REAL,
    custo_total REAL,
    lucro REAL,
    margem REAL,
    lucro_hora REAL,
    preco_minimo REAL,
    desconto_maximo REAL,
    abaixo_margem INTEGER DEFAULT 0,
    status TEXT DEFAULT 'rascunho',  -- rascunho | enviada | aceita | recusada
    observacoes TEXT,
    criado_em TEXT DEFAULT (datetime('now','localtime')),
    excluido_em TEXT
);

CREATE TABLE IF NOT EXISTS campanha_fases (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    inicio TEXT,
    fim TEXT,
    tipo TEXT DEFAULT 'fase',        -- fase | bloqueio
    descricao TEXT,
    ordem INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS campanha_itens (
    id INTEGER PRIMARY KEY,
    fase_id INTEGER NOT NULL REFERENCES campanha_fases(id),
    texto TEXT NOT NULL,
    feito INTEGER DEFAULT 0,
    data_feito TEXT,
    ordem INTEGER DEFAULT 0,
    excluido_em TEXT
);

CREATE TABLE IF NOT EXISTS campanha_checkpoints (
    id INTEGER PRIMARY KEY,
    pergunta TEXT NOT NULL,
    canal TEXT NOT NULL,
    prazo TEXT NOT NULL,
    resposta TEXT DEFAULT 'pendente'  -- pendente | sim | nao
);

CREATE TABLE IF NOT EXISTS gastos_marketing (
    id INTEGER PRIMARY KEY,
    mes TEXT NOT NULL,               -- AAAA-MM
    canal TEXT NOT NULL,
    mensalidade REAL DEFAULT 0,
    anuncios REAL DEFAULT 0,
    comissoes REAL DEFAULT 0,
    outros REAL DEFAULT 0,
    leads INTEGER DEFAULT 0,
    agendamentos INTEGER DEFAULT 0,
    clientes INTEGER DEFAULT 0,
    observacao TEXT,
    excluido_em TEXT,
    UNIQUE (mes, canal)
);

CREATE TABLE IF NOT EXISTS metricas_mensais (
    id INTEGER PRIMARY KEY,
    mes TEXT NOT NULL UNIQUE,        -- AAAA-MM
    clientes_ativos INTEGER,
    horas_ocupadas REAL,
    lucro_hora REAL,
    pct_receita_grupos REAL,
    faturamento_recorrente REAL,
    clientes_perdidos INTEGER,
    vendas_abaixo_10 INTEGER,
    nivel INTEGER,
    fechado_em TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS rotina_itens (
    id INTEGER PRIMARY KEY,
    semana TEXT NOT NULL,            -- AAAA-Wss
    item TEXT NOT NULL,              -- segunda_grade | quarta_leads | sexta_propostas | fim_mes
    feito INTEGER DEFAULT 0,
    data_feito TEXT,
    UNIQUE (semana, item)
);

CREATE TABLE IF NOT EXISTS lista_espera (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    telefone TEXT,
    dia INTEGER,
    hora INTEGER,
    local TEXT,
    observacao TEXT,
    data TEXT DEFAULT (date('now','localtime')),
    excluido_em TEXT
);

CREATE TABLE IF NOT EXISTS importacoes (
    id INTEGER PRIMARY KEY,
    data TEXT DEFAULT (datetime('now','localtime')),
    arquivo TEXT,
    resumo TEXT
);
