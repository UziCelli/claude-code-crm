# VFITCOACH CRM — Plano de pastas e modelo de dados

## Contexto
CRM local (Windows, sem programação) para o negócio de personal trainer VFITCOACH. Substitui a operação manual na planilha `Contabilidade.xlsx` (que continua existindo, só leitura) por um app web local com clientes, funil, grade, motor de preços, campanhas, painel e rotina. Prioridades: nunca perder dados, visual simples para TDAH, parâmetros editáveis.

Decisão já tomada com o usuário: canais antigos da planilha são mapeados assim na importação — `CLT -> Outro`, `Totem-CIA -> Parceria (síndico/academia)`, `Conecta -> Conecta Fitness`, `Instagram -> Instagram orgânico`, e **PersonalGo vira canal próprio** (app terceiro, como Conecta Fitness). Lista final de canais: Indicação, Parceria (síndico/academia), WhatsApp, Google, Instagram orgânico, Instagram Ads, Stadami, Conecta Fitness, TreinarMe, PersonalGo, Outro.

## Stack (mínima)
Python 3.14 (já instalado) + FastAPI + Uvicorn + Jinja2 + sqlite3 (stdlib) + openpyxl (só leitura da planilha) + pytest. Sem ORM, sem framework JS: HTML + CSS + JS simples. Fontes Montserrat/Inter via Google Fonts com fallback local (Segoe UI) se estiver sem internet.

## Plano de pastas
```
C:\Users\victo\VFITCOACH-CRM\
  iniciar-crm.bat        cria .venv na 1ª vez, instala deps, sobe servidor, abre http://localhost:8765
  README.md              como iniciar, onde ficam os dados, backup/restauração, atualizar
  requirements.txt
  app\
    main.py              FastAPI: rotas de todas as telas e APIs
    db.py                conexão SQLite, criação/migração do schema, backup diário (últimos 30), restauração
    schema.sql           tabelas (abaixo)
    precos.py            motor de preços — função pura, sem banco (testável)
    importar.py          lê a planilha (openpyxl, read_only) e faz upsert sem duplicar
    exportar.py          .xlsx e .csv
    templates\           uma página HTML por módulo (base.html + 9 telas)
    static\              style.css (cores da marca), app.js
  tests\
    test_precos.py       motor de preços
    test_importar.py     dedup da importação (planilha de teste pequena)
  data\
    crm.db               banco (fora do OneDrive)
  .venv\                 criado pelo .bat (não versionar)
```
Backups: `C:\Users\victo\OneDrive\Documentos\VFITCOACH-CRM-backups\crm-AAAA-MM-DD_HHMM.db` — feito via `sqlite3.Connection.backup()` (cópia consistente) ao iniciar o servidor (1x por dia) e pelo botão "Fazer backup agora"; mantém os 30 mais recentes.
Atalho: `VFITCOACH CRM.lnk` na Área de Trabalho apontando para `iniciar-crm.bat` (criado pelo .bat na 1ª execução via PowerShell).

## Modelo de dados (SQLite)
Convenções: `id INTEGER PRIMARY KEY`, datas ISO no banco (exibidas dd/mm/aaaa), valores em REAL (R$), `criado_em`, `atualizado_em`, e **`excluido_em` (NULL = ativo)** em toda tabela de registros do usuário — exclusão é lógica; a Lixeira lista e restaura por 30 dias.

### parametros — tudo que é editável em "Configurações"
`grupo, chave, valor REAL, valor_texto, ordem` — chave única (grupo, chave). Grupos e valores iniciais:
- `imposto`: DAS = 0,06
- `taxa_pagamento`: PIX 0 · Cartão 1x 0,0581 · Cartão 3x 0,0765 · Cartão 6x 0,104 · Cartão 12x 0,159
- `margem_minima` (por tipo de serviço): Pacote 0,15 · Mensalidade 0,15 · Consultoria Online 0,20 · Consultoria Híbrida 0,22 · Avaliação Física 0,20
- `taxa_cia` (por nº de pessoas): 1 = 70,76 · 2 = 99,69 · 3 = 151,47 · máximo 3
- `grupo_multiplicador`: 1 = 1 · 2 = 1,6 · 3 = 2,1 · 4 = 2,5
- `grupo_mao_obra_extra`: 1 = 0 · 2 = 0,20 · 3 = 0,35 · 4 = 0,55
- `metas`: clientes_dez26 14 · clientes_mar27 18 · horas_dez26 82 · horas_mar27 90 · horas_vendaveis 97 · lucro_hora_dez26 30 · lucro_hora_mar27 45 · pct_grupos_dez26 0,15 · pct_grupos_mar27 0,30 · recorrente_dez26 9500 · recorrente_mar27 12000 · perdidos_max 1 · conv_conversa 0,60 · conv_avaliacao 0,40 · conv_fechamento 0,50 · cac_max 300 · ltv_cac_min 3
- `listas`: canais de origem, locais, tipos de serviço, formas de pagamento (texto, editáveis)

### clientes
`id, nome, telefone, local (CIA|SmartFit|Condomínio|Online), tipo_servico, plano (ex.: "Pacote 8 aulas", "Mensalidade 3x/sem"), pessoas INTEGER (1–4), dias_horarios TEXT (ex.: "Seg 07:00; Qua 07:00"), valor REAL, forma_pagamento, status (ativo|inativo|pausado), canal_origem, data_inicio, data_renovacao, observacoes, planilha_id INTEGER (ID da Tabela16, chave de dedup), lead_id (se veio do funil), excluido_em`
- Alertas derivados: `data_renovacao` nos próximos 7 dias; sem evento `aula` há 14 dias.

### cliente_eventos — histórico
`id, cliente_id, tipo (pagamento|renovacao|anotacao|aula), data, valor REAL, descricao, excluido_em`

### leads — funil kanban
`id, nome, telefone, canal_origem (obrigatório), etapa (lead|conversa|avaliacao|cliente|perdido), motivo_perda, proxima_acao, data_proxima_acao, interesse (tipo/local), observacoes, cliente_id (preenchido ao converter), data_entrada, data_mudanca_etapa, excluido_em`
- `lead_etapas_log(id, lead_id, etapa, data)` — para conversão por etapa no painel.

### precos_base — importado do Comparador (tblComparadorPrecos + Tabela12)
`id, tipo_servico, local, forma_pagamento, qtd_aulas INTEGER (pacote) , freq_semanal INTEGER (mensalidade), sessoes_mes REAL, preco_base REAL, custo_operacional REAL, mao_obra REAL, custo_total REAL, origem (comparador|tabela12|manual)` — chave única (tipo_servico, local, forma_pagamento, qtd_aulas, freq_semanal).
- Tabela24 (mão de obra por qtd de aulas) e tblPrecificacaoGrupos entram em `parametros`.

### grade_slots — grade semanal (importada da Matriz, editável)
`id, tipo_calculo (Pacotes|Mensalidades), dia (1=Seg … 7=Dom), local, hora INTEGER (5–23), status (livre|ocupado|indisponivel), cliente_id, cliente_nome, bloqueio, multiplicador REAL` — chave única (tipo_calculo, dia, local, hora). Grade mostra Seg–Sáb; domingo fica guardado mas oculto. "Vale" = multiplicador < 1.

### propostas — simulador
`id, data, lead_id, cliente_id, tipo_servico, qtd_aulas, freq_semanal, local, forma_pagamento, pessoas, dia, hora, desconto REAL, preco_total, preco_pessoa, custo_total, lucro, margem, lucro_hora, preco_minimo, desconto_maximo, abaixo_margem INTEGER, status (rascunho|enviada|aceita|recusada), observacoes, excluido_em`

### campanhas
- `campanha_fases(id, nome, inicio, fim, tipo (fase|bloqueio), descricao, ordem)` — 6 registros iniciais (Fase 0–4 + bloqueio 25/10–02/11).
- `campanha_itens(id, fase_id, texto, feito INTEGER, data_feito, ordem)` — checklists.
- `campanha_checkpoints(id, pergunta, canal, prazo, resposta (pendente|sim|nao))` — "Conecta Fitness trouxe cliente até 24/10?", "Stadami até 31/10?"; resposta automática = existe cliente com esse canal e data_inicio ≤ prazo.
- `gastos_marketing(id, mes (AAAA-MM), canal, mensalidade, anuncios, comissoes, outros, leads, agendamentos, clientes, observacao, excluido_em)` — importado de tblMarketingMarketplaces; chave (mes, canal).

### painel
- `metricas_mensais(id, mes, clientes_ativos, horas_ocupadas, lucro_hora, pct_receita_grupos, faturamento_recorrente, clientes_perdidos, vendas_abaixo_10, nivel, fechado_em)` — snapshot gravado no "fechar o mês"; o mês atual é calculado ao vivo.
- Nível atual calculado das métricas: 1 Organizar → 2 Agrupar (lucro/h ≥ 30 e ≥ 82 h) → 3 Escalar (≥ 90 h e lista de espera no pico) → 4 Valorizar (flag manual em parametros: `preco_base_reajuste`).

### rotina
- `rotina_itens(id, semana (AAAA-Wss), item (segunda_grade|quarta_leads|sexta_propostas|fim_mes), feito, data_feito)` — cria a semana automaticamente ao abrir.
- `lista_espera(id, nome, telefone, dia, hora (7|9|18|19), local, observacao, data, excluido_em)`.

### importacoes
`id, data, arquivo, resumo (json: inseridos/atualizados por aba)` — auditoria do botão "Importar da planilha".

## Regras da importação (sem duplicar)
- Clientes: chave `planilha_id`; atualiza campos vindos da planilha, **nunca sobrescreve** campos que só existem no CRM (telefone, horários, datas, observações).
- Preços: chave composta; substitui valores.
- Matriz: chave (tipo, dia, local, hora); atualiza multiplicador/status/bloqueio; célula marcada `ocupado` no CRM com `cliente_id` preenchido não é sobrescrita.
- Marketing: chave (mes, canal). Config_Servicos: alimenta `parametros` só se a chave ainda não existir (para não desfazer edições da tela Configurações).
- Planilha aberta com `openpyxl.load_workbook(read_only=True, data_only=True)` — nunca grava.

## Motor de preços (`precos.py`, função pura)
Entrada: tipo, qtd_aulas/freq, local, forma_pagamento, pessoas, dia, hora, desconto.
1. `preco = preco_base × multiplicador_horario × multiplicador_grupo × (1 − desconto)`
2. `custo = custo_operacional + mao_obra × extra_grupo + (taxa_cia[pessoas] − taxa_cia[1]) × sessoes` (só na CIA; erro se pessoas > 3)
3. `liquido = preco × (1 − DAS − taxa_cartao)`; `lucro = liquido − custo`; `margem = lucro / preco`; `lucro_hora = lucro / sessoes`
4. `preco_minimo` = menor preço com margem = margem_minima; `desconto_maximo = 1 − preco_minimo / preco_sem_desconto`
Saída: preco_total, preco_pessoa, lucro, margem, lucro_hora, preco_minimo, desconto_maximo, abaixo_margem.

## Ordem de construção (cada módulo entregue funcionando, com teste)
0. Base: pastas, `.bat`, atalho, `db.py` + `schema.sql`, backup, Configurações, importação, layout base.
1. Clientes → 2. Leads/kanban → 3. Grade → 4. Motor de preços + simulador + explorador → 5. Campanhas → 6. Painel → 7. Rotina + lista de espera → 8. Exportar/backup/lixeira + README.

## Verificação
- `pytest tests/` verde antes de cada entrega (motor de preços: casos PIX/cartão, grupo 1–4, CIA máx. 3, desconto máximo, margem mínima).
- Rodar `iniciar-crm.bat`, abrir `http://localhost:8765` no navegador da sessão e mostrar cada tela ao usuário.
- Importar a planilha 2x seguidas e conferir que as contagens não mudam (sem duplicatas).
- Conferir que `Contabilidade.xlsx` mantém a data de modificação após a importação.
- Conferir arquivo de backup criado na pasta do OneDrive e restauração com confirmação.
