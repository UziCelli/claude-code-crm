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
    excluido_em TEXT,
    renovacao_em TEXT                -- quando a data de renovação foi trocada à mão (o que foi lançado antes já está nela)
);

CREATE TABLE IF NOT EXISTS cliente_eventos (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    tipo TEXT NOT NULL,              -- pagamento | renovacao | pausa | credito | anotacao | status | aula | falta | desmarcou | cancelada (não repõe)
    data TEXT NOT NULL,              -- pausa: a renovação que foi pulada; credito: dia 1 do mês pago e não usado
    valor REAL,
    descricao TEXT,
    criado_em TEXT DEFAULT (datetime('now','localtime')),
    excluido_em TEXT,
    hora INTEGER,                    -- aula marcada pela Agenda (5..23); NULL = lançada pela ficha
    ate TEXT,                        -- pausa: dia da volta
    usado_em TEXT,                   -- credito: dia em que foi descontado (NULL = ainda disponível)
    usado_lancamento_id INTEGER      -- credito: o pagamento (lancamentos.id) que o descontou
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
    canal TEXT NOT NULL,             -- '' = sem canal: resposta só na mão
    prazo TEXT NOT NULL,
    resposta TEXT DEFAULT 'pendente', -- pendente | sim | nao
    excluido_em TEXT
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

CREATE TABLE IF NOT EXISTS rotina_tarefas (   -- itens do checklist da semana (o usuário inclui e exclui)
    id INTEGER PRIMARY KEY,
    chave TEXT NOT NULL UNIQUE,      -- liga com rotina_itens.item; 'fim_mes' = último dia do mês (Fechar o mês no Painel)
    texto TEXT NOT NULL,
    dia INTEGER,                     -- 1=segunda ... 7=domingo: dia do aviso "Rotina de hoje"; NULL = sem dia
    ordem INTEGER DEFAULT 0,
    excluido_em TEXT
);

CREATE TABLE IF NOT EXISTS rotina_itens (
    id INTEGER PRIMARY KEY,
    semana TEXT NOT NULL,            -- AAAA-Wss
    item TEXT NOT NULL,              -- rotina_tarefas.chave
    feito INTEGER DEFAULT 0,
    data_feito TEXT,
    UNIQUE (semana, item)
);

CREATE TABLE IF NOT EXISTS agenda_avulsas (   -- aula só num dia (reposição, extra); o horário fixo vem da agenda_fixos
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    data TEXT NOT NULL,
    hora INTEGER NOT NULL,           -- 5..23
    local TEXT NOT NULL,
    reposicao INTEGER DEFAULT 0,     -- 1 = reposição de uma aula desmarcada (conta no saldo do aluno quando fica Feita ou Faltou)
    repoe_evento_id INTEGER,         -- reposição: o cliente_eventos 'desmarcou' que ela repõe (só informativo; o saldo não depende dele)
    criado_em TEXT DEFAULT (datetime('now','localtime')),
    excluido_em TEXT
);

CREATE TABLE IF NOT EXISTS agenda_fixos (   -- horário fixo da Agenda: até 2 alunos ativos por (dia, hora), controlado no app; a Agenda avisa a Grade, nunca o contrário
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    dia INTEGER NOT NULL,            -- 1..6 (segunda a sábado)
    hora INTEGER NOT NULL,           -- 5..23
    local TEXT NOT NULL,
    criado_em TEXT DEFAULT (datetime('now','localtime')),
    excluido_em TEXT
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

-- Financeiro PF + PJ. valor > 0 sempre; o sentido vem de tipo. Contas e cartões são texto (lista_contas).
CREATE TABLE IF NOT EXISTS recorrencias (
    id INTEGER PRIMARY KEY,
    escopo TEXT NOT NULL CHECK (escopo IN ('PF','PJ')),
    descricao TEXT NOT NULL,
    categoria TEXT NOT NULL,
    valor REAL NOT NULL CHECK (valor > 0),            -- previsto; a baixa grava o real
    dia_vencimento INTEGER NOT NULL CHECK (dia_vencimento BETWEEN 1 AND 31),
    fixo INTEGER NOT NULL DEFAULT 1,                  -- 1 fixo, 0 variável (ponto de equilíbrio)
    conta TEXT,
    inicio TEXT NOT NULL,                             -- AAAA-MM
    fim TEXT,                                         -- AAAA-MM; NULL = sem fim
    origem TEXT UNIQUE,                               -- ID da planilha: CEF-001, CPV-002...
    excluido_em TEXT,
    prioridade INTEGER                                -- fila de pagamento: 1 = sempre primeiro, -1 = pode esperar, NULL = automática
);

CREATE TABLE IF NOT EXISTS lancamentos (
    id INTEGER PRIMARY KEY,
    escopo TEXT NOT NULL CHECK (escopo IN ('PF','PJ')),
    tipo TEXT NOT NULL CHECK (tipo IN ('entrada','saida')),
    data TEXT NOT NULL,                               -- data do movimento / vencimento
    pago_em TEXT,                                     -- NULL = em aberto
    valor REAL NOT NULL CHECK (valor > 0),
    categoria TEXT NOT NULL,
    descricao TEXT,
    contraparte TEXT,
    cliente_id INTEGER REFERENCES clientes(id),
    conta TEXT,
    forma TEXT,
    parcela_num INTEGER,
    parcela_total INTEGER,
    recorrencia_id INTEGER REFERENCES recorrencias(id),
    competencia TEXT,                                 -- AAAA-MM, só junto com recorrencia_id
    sem_recorrencia INTEGER,                          -- 1 = "não é a conta recorrente": sai da lista de contas parecidas
    nfse INTEGER,                                     -- 1 emitida, 0 não, NULL não se aplica
    observacao TEXT,
    origem TEXT UNIQUE,                               -- 'PJ:17', 'PF:8', 'CC:11', 'EP:11'
    criado_em TEXT DEFAULT (datetime('now','localtime')),
    excluido_em TEXT,
    UNIQUE (recorrencia_id, competencia)
);
CREATE INDEX IF NOT EXISTS idx_lancamentos_data ON lancamentos (data);
CREATE INDEX IF NOT EXISTS idx_lancamentos_competencia ON lancamentos (competencia);

-- Foto do saldo de cada conta, digitada 1x por semana. O saldo atual é o mais recente da conta.
-- A frente da conta (PF, PJ, Reserva ou Fora) fica em parametros, grupo conta_escopo.
CREATE TABLE IF NOT EXISTS saldos (
    id INTEGER PRIMARY KEY,
    conta TEXT NOT NULL,
    saldo REAL NOT NULL,
    data TEXT NOT NULL,                               -- AAAA-MM-DD
    criado_em TEXT DEFAULT (datetime('now','localtime')),
    excluido_em TEXT
);
CREATE INDEX IF NOT EXISTS idx_saldos_conta ON saldos (conta, data);

-- pares de lançamentos que o usuário disse "não é repetido" (a < b): a tela Conferir não avisa de novo
CREATE TABLE IF NOT EXISTS duplicados_ok (
    a INTEGER NOT NULL,
    b INTEGER NOT NULL,
    PRIMARY KEY (a, b)
);

-- Assistente (chat com o Claude). A conversa só cresce: o que já foi mandado para a API nunca é editado.
CREATE TABLE IF NOT EXISTS assistente_conversas (
    id INTEGER PRIMARY KEY,
    titulo TEXT,
    criado_em TEXT DEFAULT (datetime('now','localtime')),
    atualizado_em TEXT DEFAULT (datetime('now','localtime')),
    excluido_em TEXT
);

CREATE TABLE IF NOT EXISTS assistente_mensagens (
    id INTEGER PRIMARY KEY,
    conversa_id INTEGER NOT NULL REFERENCES assistente_conversas(id),
    papel TEXT NOT NULL,              -- user | assistant | aviso (aviso só aparece na tela, não vai para a API)
    conteudo TEXT NOT NULL,           -- JSON: lista de blocos, como a API devolveu
    uso TEXT,                         -- JSON: modelo e tokens da resposta (estimativa de custo)
    criado_em TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_assistente_mensagens ON assistente_mensagens (conversa_id, id);

-- Segredos do CRM (hoje só a chave do Assistente, linha 'anthropic_api_key'). O assistente nunca pode ler esta tabela.
CREATE TABLE IF NOT EXISTS segredos (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL,
    atualizado_em TEXT DEFAULT (datetime('now','localtime'))
);
