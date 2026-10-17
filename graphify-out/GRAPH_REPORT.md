# Graph Report - claude-code-crm  (2026-10-17)

## Corpus Check
- 66 files · ~79,327 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 3, .woff2 2, .example 1)

## Summary
- 1194 nodes · 3222 edges · 56 communities (44 shown, 12 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 255 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Testes da agenda
- Migração e importação do financeiro
- Rotas do CRM (main.py)
- Financeiro: saldo livre e previsão
- Painéis honestos e livro-caixa
- Acesso e deploy no Render
- Painel e métricas
- Testes do financeiro
- Alertas e mapa da Rodada 1
- Testes de acesso
- Mapa da planilha financeira
- Testes de rotas e conexão
- Banco SQLite e backup
- Agenda semanal
- Plano, progresso e README
- Recorrências e pendências
- Agenda: horários e fixos
- Banco inicial e testes de importação
- Vigia do CRM
- Atualizador do CRM
- Testes do atualizador
- Motor de preços e parâmetros
- base.html
- test_paineis.py
- financeiro_tela()
- nuvem.py
- Conexao
- pytest
- test_alertas.py
- Tabela clientes
- Reforma Rodada 1
- Grade semanal com cores por margem
- test_incluir_excluir.py
- app/__init__.py
- agenda_copiar_grade()
- CRM no celular (túnel no PC e reserva no
- estimativa_cliente()
- salario_mes()
- re
- sqlite3
- Cursor
- Linha
- Espia
- test_grade_lote.py
- configurar-pc-servidor.ps1
- ajudante()
- .claude/CLAUDE.md (claude-code-crm graph
- portaria()
- mensalidades()
- reiniciar()
- saldos_reposicao()
- test_inserir_fixos_em_blocos_de_200_linh
- versao()
- claude-code-crm/.claude/hooks/session-st

## God Nodes (most connected - your core abstractions)
1. `aluno()` - 107 edges
2. `conectar()` - 55 edges
3. `voltar()` - 46 edges
4. `erro()` - 40 edges
5. `consulta()` - 39 edges
6. `fixos_ativos()` - 33 edges
7. `iniciar_banco()` - 33 edges
8. `saldo_livre()` - 29 edges
9. `horario()` - 28 edges
10. `msg()` - 28 edges

## Surprising Connections (you probably didn't know these)
- `dias_parado()` --implements--> `Item 4: Lead esfriando (selo parado há X dias)`  [INFERRED]
  app/main.py → docs/mapa-rodada1.md
- `Listas em parametros (categorias PJ/PF, formas de lançamento)` --shares_data_with--> `parametros()`  [INFERRED]
  docs/mapa-financeiro.md → app/db.py
- `pendencias()` --implements--> `Regras calculadas sem coluna (status, pendências, baixa)`  [INFERRED]
  app/financeiro.py → docs/mapa-financeiro.md
- `baixar_recorrencia()` --implements--> `Regras calculadas sem coluna (status, pendências, baixa)`  [INFERRED]
  app/financeiro.py → docs/mapa-financeiro.md
- `Armadilha: linhas de total e linhas fantasma` --references--> `ler_tabela()`  [EXTRACTED]
  docs/mapa-financeiro.md → app/importar.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **CRM na nuvem: serviço Render, portaria Cloudflare Access e banco Turso** — claude_code_crm_render_servico_web_vfitcoach_crm, claude_code_crm_render_crm_nuvem, claude_code_crm_render_portaria_cloudflare_access, claude_code_crm_render_turso_banco_libsql_na_nuvem, claude_code_crm_render_variaveis_cf_access, claude_code_crm_render_variaveis_turso [EXTRACTED 1.00]
- **Migração da planilha financeira para as tabelas SQLite PF+PJ** — claude_code_crm_docs_mapa_financeiro_transacoes_empresariais_pj, claude_code_crm_docs_mapa_financeiro_transacoes_pessoais_pf, claude_code_crm_docs_mapa_financeiro_cartoes_faturas, claude_code_crm_docs_mapa_financeiro_custos_empresariais_e_pessoais, claude_code_crm_docs_mapa_financeiro_migracao_unica_planilha_para_campo, claude_code_crm_docs_mapa_financeiro_tabela_lancamentos, claude_code_crm_docs_mapa_financeiro_tabela_recorrencias, claude_code_crm_docs_mapa_financeiro_tabela_contas [EXTRACTED 1.00]
- **Fluxo lead, simulação, proposta impressa e cadastro de cliente** — claude_code_crm_app_templates_leads_kanban, claude_code_crm_app_templates_simulador_resultado, claude_code_crm_app_templates_simulador_salvar, claude_code_crm_app_templates_proposta_impressao, claude_code_crm_app_templates_cliente_cadastro [INFERRED 0.85]
- **Saldos digitados alimentam saldo livre, previsão 90 dias e colchão** — claude_code_crm_app_templates_financeiro_atualizar_saldos, claude_code_crm_app_templates_financeiro_saldo_livre, claude_code_crm_app_templates_financeiro_previsao_cartoes, claude_code_crm_app_templates_financeiro_previsao_semana, claude_code_crm_app_templates_financeiro_painel_colchao [INFERRED 0.95]
- **Exclusão lógica com Lixeira reaproveitada por várias telas** — claude_code_crm_app_templates_dados_lixeira, claude_code_crm_plano_exclusao_logica, claude_code_crm_app_templates_cliente_acoes, claude_code_crm_app_templates_leads_kanban, claude_code_crm_app_templates_simulador_recentes, claude_code_crm_app_templates_financeiro_livro_caixa, claude_code_crm_app_templates_campanhas_checkpoints, claude_code_crm_app_templates_rotina_checklist [INFERRED 0.95]

## Communities (56 total, 12 thin omitted)

### Community 0 - "Testes da agenda"
Cohesion: 0.06
Nodes (141): alertas(), aluno(), alunos_da_grade(), ativos(), aulas(), cards(), _con(), consulta() (+133 more)

### Community 1 - "Migração e importação do financeiro"
Cohesion: 0.06
Nodes (43): de_dicts(), tabela(), xlsx(), canal(), importar_clientes(), importar_config(), importar_marketing(), importar_matriz() (+35 more)

### Community 2 - "Rotas do CRM (main.py)"
Cohesion: 0.07
Nodes (55): backup_agora(), campanha_checkpoint(), campanha_checkpoint_add(), campanha_checkpoint_excluir(), campanha_gasto(), campanha_gasto_excluir(), campanha_item(), campanha_item_excluir() (+47 more)

### Community 3 - "Financeiro: saldo livre e previsão"
Cohesion: 0.09
Nodes (19): _das_a_guardar(), _das_do_mes(), em_aberto_ate(), entradas_sem_aluno(), liberar_vaga(), _mensalidades_a_receber(), _mes_br(), previsao() (+11 more)

### Community 4 - "Painéis honestos e livro-caixa"
Cohesion: 0.11
Nodes (35): Gastos por canal, Formulário de cadastro do cliente, Pagamentos do aluno (lançamentos financeiros), Parâmetros editáveis por grupo, A pagar e a receber, Atualizar saldos (conta e frente PF/PJ/Reserva/Fora), Livro-caixa e novo lançamento, Previsto, recebido e falta receber (+27 more)

### Community 5 - "Acesso e deploy no Render"
Cohesion: 0.07
Nodes (28): _chaves(), local(), motivo_bloqueio(), _nome_host(), pode_encerrar(), verificar(), saude(), render.yaml (Blueprint do Render) (+20 more)

### Community 6 - "Painel e métricas"
Cohesion: 0.13
Nodes (30): lista(), parametros(), calcular_metricas(), campanhas(), cliente_ficha(), cliente_novo(), clientes(), configuracoes() (+22 more)

### Community 7 - "Testes do financeiro"
Cohesion: 0.13
Nodes (31): resumo_mes(), salvar_saldos(), lancar(), ligar_salario(), recorrencia_imposto(), saida(), saldo(), test_gasto_pf_contra_salario_e_sugestao() (+23 more)

### Community 8 - "Alertas e mapa da Rodada 1"
Cohesion: 0.07
Nodes (29): alertas(), data_br(), lead_etapa(), preencher(), rotina_texto(), tarefas_rotina(), wa(), mapa-rodada1.md (Mapa do código, Rodada 1) (+21 more)

### Community 9 - "Testes de acesso"
Cohesion: 0.09
Nodes (21): banco(), ChavesFalsas, desligar(), na_internet(), no_pc(), test_encerrar_indisponivel_na_internet(), test_login_valido_entra_e_esconde_encerrar(), test_no_pc_encerrar_so_para_quem_esta_no_pc() (+13 more)

### Community 10 - "Mapa da planilha financeira"
Cohesion: 0.15
Nodes (31): mapa-financeiro.md (Mapa da planilha, Rodada 2), Armadilha: mesma obrigação PF em dois lugares, Armadilha: linhas de total e linhas fantasma, Armadilha: coluna Mês sem ano, Armadilha: Inter e Itaú são conta e cartão, Armadilha: pró-labore contado duas vezes na renda PF, Armadilhas da migração (20 itens), Aba Backend_Fin (listas e regras) (+23 more)

### Community 11 - "Testes de rotas e conexão"
Cohesion: 0.12
Nodes (19): conectar(), get_db(), cliente_http(), test_atualizar_saldos_e_ver_saldo_livre(), test_financeiro_card_avisa_recorrencia_de_retirada_ja_cadastrada(), test_financeiro_card_de_contas_parecidas_ligar_e_descartar(), test_financeiro_entradas_invalidas_nao_gravam_nem_quebram(), test_financeiro_lancamento_baixa_e_recorrencia() (+11 more)

### Community 12 - "Banco SQLite e backup"
Cohesion: 0.15
Nodes (13): backup_diario(), fazer_backup(), listar_backups(), pasta_backup(), restaurar_backup(), lifespan(), Falha de backup bloqueia o startup, Item 6: Backup e restauração (+5 more)

### Community 13 - "Agenda semanal"
Cohesion: 0.10
Nodes (14): agenda(), agenda_avulsa_excluir(), agenda_horario(), aulas_da_semana(), aulas_sem_marcar(), controle_aluno(), em_bloqueio(), fases_bloqueio() (+6 more)

### Community 14 - "Plano, progresso e README"
Cohesion: 0.13
Nodes (17): Fases de campanha e checklists, Backup e restauração com confirmação, Exportar xlsx e csv, Checklist semanal editável, Backup consistente diário (últimos 30), Ordem de construção dos módulos, Plano de pastas, Plano de verificação (+9 more)

### Community 15 - "Recorrências e pendências"
Cohesion: 0.17
Nodes (19): baixar_recorrencia(), ligar_recorrencia(), pendencias(), saidas_parecidas(), abertas_de_outubro(), paga_a_mao(), recorrencia(), test_baixa_excluida_volta_como_pendente_e_pode_ser_paga_de_novo() (+11 more)

### Community 16 - "Agenda: horários e fixos"
Cohesion: 0.11
Nodes (13): agenda_incluir(), definir_horario(), fixos_do_horario(), grade_liberar(), grade_ocupar(), grade_ocupar_lote(), grade_slot(), inserir_fixos() (+5 more)

### Community 17 - "Banco inicial e testes de importação"
Cohesion: 0.10
Nodes (14): _garantir_coluna(), iniciar_banco(), test_banco_antigo_ganha_coluna_hora_e_tabela_de_avulsas(), test_banco_antigo_sem_agenda_fixos_ganha_a_tabela(), test_dados_mostra_a_situacao(), banco_tmp(), con_temp(), con_temp() (+6 more)

### Community 18 - "Vigia do CRM"
Cohesion: 0.14
Nodes (14): rodada(), aberturas(), envelhecer(), nuvem_ligada(), pasta(), test_atualizando_agora_nao_religa(), test_encerrar_pelo_botao_nao_religa(), test_erro_na_rodada_nao_derruba_o_vigia() (+6 more)

### Community 19 - "Atualizador do CRM"
Cohesion: 0.14
Nodes (12): abrir_crm(), conferir(), git(), _git(), iniciar(), _laco(), log(), motivo_desligado() (+4 more)

### Community 20 - "Testes do atualizador"
Cohesion: 0.26
Nodes (16): rodada(), commit(), parado(), publicar(), repos(), sh(), test_arquivo_mudado_no_pc_explica(), test_em_dia_nao_faz_nada() (+8 more)

### Community 21 - "Motor de preços e parâmetros"
Cohesion: 0.15
Nodes (20): Rentabilidade estimada do cliente, Listas editáveis (canais, locais, tipos, formas), Preços base (formulário e tabela), Explorador de combinações de planos, Gráfico dos últimos 12 meses, Potes do mês, Formulário de novo ou editar lead, Evolução mensal do faturamento recorrente (+12 more)

### Community 23 - "test_paineis.py"
Cohesion: 0.15
Nodes (12): _DataFixa, lancar(), sem_das(), test_alerta_de_conta_olha_o_mes_seguinte_na_virada(), test_aperto_olha_o_pior_dia_e_nao_o_fim_da_semana(), test_atrasado_conta_em_hoje_e_semana_sem_aperto_nao_tem_pior(), test_cac_do_mes_nao_divide_pelos_clientes_de_toda_a_historia(), test_checkpoint_nao_conta_cliente_anterior_a_fase() (+4 more)

### Community 24 - "financeiro_tela()"
Cohesion: 0.12
Nodes (11): colchao(), _fixos_mes(), frentes_contas(), potes_mes(), recorrencias_retirada(), saldos_atuais(), status(), financeiro_tela() (+3 more)

### Community 25 - "nuvem.py"
Cohesion: 0.20
Nodes (10): ativo(), _bruta(), carregar_env(), conectar(), iniciar_sync_periodico(), laco(), preenchido(), sincronizar() (+2 more)

### Community 26 - "Conexao"
Cohesion: 0.14
Nodes (4): Conexao, _erro(), _posicional(), test_parametros_nomeados_viram_posicionais()

### Community 27 - "pytest"
Cohesion: 0.22
Nodes (10): calcular(), cor_margem(), test_bate_com_a_planilha_pix(), test_cartao_reduz_lucro(), test_cia_cobra_taxa_extra_por_pessoa_e_limita_a_3(), test_cor_margem(), test_desconto_e_preco_minimo(), test_grupo_dupla_multiplica_preco_e_mao_de_obra() (+2 more)

### Community 28 - "test_alertas.py"
Cohesion: 0.12
Nodes (7): cliente_http(), con_temp(), test_alerta_contas_vencidas(), test_alertas_ordem_e_agregacao(), test_dias_parado(), test_post_etapa_cliente_redireciona_com_destaque(), test_post_etapa_redireciona_com_destaque()

### Community 29 - "Tabela clientes"
Cohesion: 0.27
Nodes (14): Checkpoints de campanha, Histórico e registro de eventos do cliente, Lista de clientes em cards com filtros, Importar da planilha Contabilidade.xlsx, Alertas derivados de clientes, Modelo de dados SQLite, Tabelas de campanhas e gastos_marketing, Tabela cliente_eventos (+6 more)

### Community 30 - "Reforma Rodada 1"
Cohesion: 0.18
Nodes (15): Lista de alertas com atalho de WhatsApp, Alertas recolhíveis no topo das telas, Ações do cabeçalho da ficha (status, WhatsApp, proposta, excluir), Propostas do cliente, Mensagens prontas de WhatsApp, Lixeira dos últimos 30 dias, Formulário de motivo de perda, Funil kanban de leads (+7 more)

### Community 31 - "Grade semanal com cores por margem"
Cohesion: 0.26
Nodes (15): Controle do aluno (saldo e contadores do mês), Copiar da Grade (uma vez), Janelinha do horário (até 2 alunos e local), Estados da aula (feita, faltou, desmarcou, pendente, agendada), Tabela semanal da Agenda, Card Hoje com marcação em 1 toque, Incluir aula (fixa, avulsa ou reposição), Marcar várias aulas (pincel e Salvar único) (+7 more)

### Community 32 - "test_incluir_excluir.py"
Cohesion: 0.23
Nodes (11): alertas(), consulta(), http(), test_checkpoint_com_prazo_invalido_nao_entra(), test_excluir_e_restaurar_checkpoint(), test_excluir_e_restaurar_tarefa(), test_fechar_mes_sem_a_tarefa_fim_mes(), test_incluir_checkpoint_com_e_sem_canal() (+3 more)

### Community 33 - "app/__init__.py"
Cohesion: 0.16
Nodes (6): assumir_trava(), atualizando(), processo_vivo(), test_processo_vivo(), test_trava_de_processo_morto_e_lixo_sao_ignoradas(), test_trava_so_um_vigia()

### Community 34 - "agenda_copiar_grade()"
Cohesion: 0.18
Nodes (8): agenda_copiar_grade(), agenda_marcar(), agenda_marcar_lote(), descricao_marca(), gravar_marcas(), _norm(), _plural(), sugerir_cliente()

### Community 35 - "CRM no celular (túnel no PC e reserva no"
Cohesion: 0.24
Nodes (12): Controle de acesso: botão Encerrar e link Sair, Aviso do status da atualização automática, Aviso do status do Turso, PC se atualiza sozinho (app/atualizar.py), CRM no celular via Cloudflare Tunnel e Render reserva, Banco na nuvem Turso, Vigia do CRM (app/vigia.py), Como atualizar o CRM (autoatualização) (+4 more)

### Community 36 - "estimativa_cliente()"
Cohesion: 0.20
Nodes (9): aulas_mes(), base_do_cliente(), estimativa_cliente(), moeda(), aluno(), base_pacote(), test_ficha_nao_multiplica_o_valor_pago_pelo_grupo_e_bate_com_o_painel(), test_lucro_hora_so_conta_as_horas_de_quem_tem_preco_base() (+1 more)

### Community 37 - "salario_mes()"
Cohesion: 0.22
Nodes (5): pagar_salario(), _retiradas_mes(), salario_mes(), sugestao_salario(), test_salario_desligado_nao_paga()

### Community 38 - "re"
Cohesion: 0.25
Nodes (5): eh_das(), _palavras(), sugerir_aluno(), test_eh_das(), test_sugerir_aluno()

### Community 39 - "sqlite3"
Cohesion: 0.28
Nodes (3): copiar_dados(), _ordem_tabelas(), main()

### Community 43 - "test_grade_lote.py"
Cohesion: 0.36
Nodes (6): con_temp(), _post(), _slot(), test_celula_unica_antiga(), test_lote_mantem_status_e_cliente(), test_lote_sem_celula_valida()

### Community 44 - "configurar-pc-servidor.ps1"
Cohesion: 0.36
Nodes (4): Aviso(), Energia(), Linha(), Ok()

### Community 45 - "ajudante()"
Cohesion: 0.40
Nodes (4): ajudante(), test_ajudante_limpa_atualizando_mesmo_com_erro(), test_ajudante_marca_e_limpa_atualizando(), quebra()

### Community 46 - ".claude/CLAUDE.md (claude-code-crm graph"
Cohesion: 0.67
Nodes (4): .claude/CLAUDE.md (claude-code-crm graphify skill), graphify skill trigger, CLAUDE.md (claude-code-crm graphify rules), Graphify query first rules

### Community 48 - "mensalidades()"
Cohesion: 0.50
Nodes (3): mensalidades(), test_mensalidades_em_aberto_falta_e_inicio(), test_mensalidades_previsto_x_recebido()

## Ambiguous Edges - Review These
- `httpx` → `Testes (pytest, tmp_path, sem TestClient)`  [AMBIGUOUS]
  requirements.txt · relation: conceptually_related_to
- `Backup consistente diário (últimos 30)` → `Onde ficam os dados e backups`  [AMBIGUOUS]
  README.md · relation: conceptually_related_to
- `Banco na nuvem Turso` → `Stack mínima`  [AMBIGUOUS]
  PROGRESSO.md · relation: conceptually_related_to

## Knowledge Gaps
- **12 isolated node(s):** `Controle de acesso: botão Encerrar e link Sair`, `Cores fixas fora do :root (style.css e templates)`, `Item 1: Logo (SVG e favicon)`, `Migração financeira (app.migrar_financeiro)`, `autoDeploy da main do GitHub` (+7 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 268 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `claude-code-crm/README.md` connect `Plano, progresso e README` to `CRM no celular (túnel no PC e reserva no`, `Acesso e deploy no Render`, `Alertas e mapa da Rodada 1`, `base.html`, `Tabela clientes`?**
  _High betweenness centrality (0.225) - this node is a cross-community bridge._
- **What connects `Controle de acesso: botão Encerrar e link Sair`, `Cores fixas fora do :root (style.css e templates)`, `Item 1: Logo (SVG e favicon)` to the rest of the system?**
  _12 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Testes da agenda` be split into smaller, more focused modules?**
  _Cohesion score 0.05992700110347169 - nodes in this community are weakly interconnected._
- **Why does `render.yaml (Blueprint do Render)` connect `Acesso e deploy no Render` to `Plano, progresso e README`?**
  _High betweenness centrality (0.191) - this node is a cross-community bridge._
- **Should `Migração e importação do financeiro` be split into smaller, more focused modules?**
  _Cohesion score 0.06342342342342343 - nodes in this community are weakly interconnected._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `httpx` and `Testes (pytest, tmp_path, sem TestClient)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `Backup consistente diário (últimos 30)` and `Onde ficam os dados e backups`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._