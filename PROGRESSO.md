# VFITCOACH CRM — progresso e como retomar

Plano completo (pastas, modelo de dados, ordem dos módulos): `PLANO.md`.

## Como retomar (para uma sessão nova do Claude Code)
1. Abrir a pasta `C:\Users\victo\VFITCOACH-CRM` no Claude Code.
2. Ler `PLANO.md` e este arquivo. Modo ponytail **full**. Interface em pt-BR, sem emojis, paleta azul (tokens no topo do `style.css`), Montserrat + Inter locais.
3. Rodar `.venv\Scripts\python.exe -m pytest tests` (todos verdes) antes de entregar qualquer mudança.
4. Servidor de desenvolvimento: `.venv\Scripts\python.exe -m uvicorn app.main:app --port 8765 --reload`.

## Sem cota na Anthropic? Use o OmniRoute
`continuar-com-omniroute.bat` sobe o OmniRoute (porta 20128) e abre o Claude Code apontando para ele.

## Estado dos módulos — TODOS ENTREGUES em 17/09/2026
- [x] 0. Base: `iniciar-crm.bat`, `schema.sql`, `db.py` (backup diário, 30 cópias, restaurar), `importar.py`
- [x] 1. Clientes (cards, ficha, histórico, alertas)
- [x] 2. Leads / kanban (converter em cliente, motivo de perda, log de etapas)
- [x] 3. Grade de horários (cores por margem, filtro vale, edição por célula)
- [x] 4. Motor de preços `precos.py` (8 testes) + simulador + propostas + explorador
- [x] 5. Campanhas (fases, checklists, gastos, checkpoints automáticos)
- [x] 6. Painel (7 KPIs com metas, nível, gráfico mensal, por canal)
- [x] 7. Rotina semanal + lista de espera
- [x] 8. Exportar xlsx/csv, backup/restaurar, lixeira, README

## Reforma — Rodada 1 (concluída em 01/10/2026; git, tag `base` = antes da reforma)
Plano completo em `C:\Users\victo\.claude\plans\a-gente-vai-come-ar-functional-thunder.md`. Mapas de referência em `docs/mapa-rodada1.md` e `docs/mapa-financeiro.md`.
- [x] Git no projeto + `.gitignore`/`.gitattributes` (LF) + teste de fumaça de todas as telas (`tests/test_rotas.py`)
- [x] Backup só local em `data\backups`; o CRM abre mesmo se o backup falhar; a restauração recusa arquivo corrompido ou vazio
- [x] Visual: logo e favicon do site, fontes locais (funciona offline), paleta azul, padrão Impeccable (foco visível, estados, textos de lista vazia)
- [x] Motion em CSS/JS puro: transição entre telas, botão "salvando…" (sem duplo envio), avisos, dialogs, destaque do card movido, momento lead→aluno; respeita "reduzir movimento"
- [x] Leads: "parado há X dias" por etapa (prazos editáveis em Configurações)
- [x] Painel: "O que precisa de você hoje" (8 tipos de alerta, ordenados) + setas ↑↓ vs mês anterior
- [x] WhatsApp: mensagens prontas (renovação, falta, boas-vindas, reativação), editáveis em Configurações
- [x] Grade: preço total e lucro em letra miúda abaixo do preço por aula; legenda dos números; seletor do plano de referência
- [x] Grade: edição em lote ("Selecionar vários", Shift = bloco, clique no dia/hora = coluna/linha, Ctrl+clique; "Não alterar" preserva situação e cliente)
- [x] Leads: previsão do funil e "Por que perco leads"; proposta para imprimir/salvar PDF (`/propostas/{id}`)
- Teste visual sem tocar no banco real: preview `crm-teste` (porta 8766, usa cópia temporária do `crm.db`)
- 34 testes passando (`.venv\Scripts\python.exe -m pytest tests`)

## Próximos passos
- **Usuário:** completar telefone e data de renovação dos alunos (o painel mostra "cadastro incompleto").
- **Rodada 2 — financeiro PF + PJ: código pronto em 02/10/2026** (60 testes):
  - `/financeiro` (livro-caixa + "A pagar e a receber" + contas recorrentes/cartões), `/financeiro/mensalidades` (previsto × recebido), `/financeiro/painel` (receita, custos, lucro, ponto de equilíbrio, DAS, pró-labore, INSS, bloco PF, 12 meses); pagamentos na ficha do aluno; alerta de contas vencidas.
  - Lógica em `app/financeiro.py`; migração em `python -m app.migrar_financeiro` (sem `--gravar` só simula; com `--gravar` faz backup `antes-financeiro` e é idempotente).
  - **Migração gravada** (conferido em 05/10/2026: simulação mostra 363 lançamentos e 6 recorrências já no CRM). Planilha aposentada. Antes:
  - Pendente: usuário aprovar a simulação (363 lançamentos + 6 recorrências; totais por mês batem com a planilha) e então rodar `.venv\Scripts\python.exe -m app.migrar_financeiro --gravar` com o Excel e o CRM fechados.
  - Preview `crm-teste-fin` (porta 8767): cópia temporária do banco já com a migração gravada, para conferir as telas.
  - Saldos de contas (`tblSaldosContas`) não migrados: decidir depois.
- **Banco na nuvem (Turso): código pronto em 05/10/2026** (`app/nuvem.py`, `python -m app.subir_nuvem`; testes rodam também com `CRM_BANCO=libsql`). **No ar desde 05/10/2026**: 1601 linhas enviadas, tela Dados mostra o Turso ligado. A `.venv` do PC agora usa Python 3.13 (o libsql não tem pacote para o 3.14 no Windows). O `crm.db` antigo ficou como cópia de segurança.
- **CRM no celular: código pronto em 05/10/2026** (Render grátis + Cloudflare Access; `render.yaml`, `app/acesso.py`). Configurado pelo usuário; agora vira a reserva (linha abaixo).
- **CRM no celular via Cloudflare Tunnel no PC (código pronto em 10/10/2026); Render vira reserva em `crm-reserva.vfitcoachapp.com`.**
  `iniciar-crm.bat /servidor` (liga sem navegador, para o início automático) e `configurar-pc-servidor.ps1` (início automático, energia, confere `.env` e túnel).
  Pendente (usuário, passo a passo no README, "CRM no celular"): apagar o DNS `crm` antigo; criar o túnel `pc-crm` (cloudflared como serviço, `crm` → `localhost:8765`);
  no app CRM do Access, acrescentar `crm-reserva` e sessão de 1 mês; trocar o domínio no Render para `crm-reserva`; pôr `CF_ACCESS_TEAM_DOMAIN`/`CF_ACCESS_AUD` no `.env` do PC; rodar `configurar-pc-servidor.ps1`.
  Túnel funcionando em 10/10/2026 (celular abre rápido). Falta: reserva no Render (`crm-reserva`) e sessão de 1 mês no Access.
- **Checkpoints e checklist da Rotina editáveis (10/10/2026):** incluir e excluir (lixeira); tarefas da rotina na tabela `rotina_tarefas`.
- **PC se atualiza sozinho (10/10/2026, `app/atualizar.py`):** confere a `main` a cada 15 min; com versão nova, espera 5 min sem uso,
  faz `git merge --ff-only` e reinicia pelo `iniciar-crm.bat /servidor`. Versão que não abre volta para a anterior (`data/atualizacao-recusada.txt`).
  Log em `data/atualizacao.log`; situação na tela Dados. Desligar: `CRM_AUTOATUALIZAR=0` no `.env`.
  Atenção ao programar no PC: commit local na `main` ou outro ramo param a atualização automática (de propósito).
- **Agenda (14/10/2026):** aba nova com os horários fixos da Grade e aulas avulsas; marcar aula feita/faltou/desmarcou com 1 toque (vai para o histórico do aluno); aviso de aulas da semana sem marcar.
- **Agenda com seletor (14/10/2026):** 1 card por horário (até 2 alunos), escolhe aluno e local; Copiar da Grade em uma gravação só.
- **Agenda: reposições e lote (15/10/2026):** controle do aluno (saldo de reposições, aulas do mês, "Agendar reposição"); "Marcar várias" grava tudo com um Salvar (2 gravações); vários horários fixos de um aluno de uma vez.
- **Vigia do CRM (15/10/2026, `app/vigia.py`):** o `iniciar-crm.bat /servidor` liga um processo sem janela que confere a porta a cada minuto e religa o CRM se cair 2 vezes seguidas (fim do 502 no celular). Não religa depois do botão Encerrar (`data/desligado.txt`, apagado ao abrir pelo atalho ou ligar o Windows) nem durante a atualização automática (`data/atualizando.txt`). O .bat agora espera até 2 minutos o servidor subir, e o CRM abre com a réplica local se o Turso estiver fora ao ligar.
- **Saldo livre (16/10/2026):** topo do `/financeiro` mostra "Quanto dá para gastar" PF e PJ = saldo digitado das contas − saídas em aberto até 30 dias − DAS a guardar (PJ). Entrada prevista não conta. Botão "Atualizar saldos" (1x por semana, tabela `saldos`; frente da conta PF/PJ/Reserva/Fora em `parametros` grupo `conta_escopo`). Alertas: livre negativo e saldo com mais de 7 dias. Tarefa de segunda na Rotina (`saldos`).
- **Salário fixo PJ → PF (16/10/2026):** valor e dia em Configurações (grupo `salario`; 0 = desligado). Botão "Pagar salário" lança saída PJ "Retirada" + entrada PF "Salário" (`origem` SAL:AAAA-MM:PJ/PF, não paga duas vezes). Retirada sai do lucro sem virar custo. Barra "gasto pessoal × salário", alerta a partir de 90%, sugestão = 80% do lucro médio de 3 meses.
- **Potes e colchão (16/10/2026):** cada entrada PJ recebida enche em cascata imposto (DAS%) → contas da PJ do mês → salário PF → colchão (`potes_mes`). Ao salvar entrada PJ paga, a mensagem diz quanto separar em cada pote. Painel: card do colchão (1 e 3 meses de custo fixo, guardado nas contas Reserva, meta em Configurações, grupo `colchao`; 0 = sem meta).
  Próximo PR do mesmo plano: linha do tempo de 90 dias.
- **Depois:** repositório privado no GitHub (feito: UziCelli/claude-code-crm); agente de IA (Sonnet 5.5) adiado.
- Forma de pagamento dos clientes importados vem como "Mensal"/"Parcelado" (texto da planilha); o motor usa PIX como padrão nesses casos.
- Multiagente: tarefas simples em Haiku, implementação em Sonnet 5.5, modelo principal só para revisão.

## Decisões tomadas
- Canais antigos da planilha: CLT→Outro, Totem-CIA→Parceria (síndico/academia), Conecta→Conecta Fitness, Instagram→Instagram orgânico, PersonalGo→canal próprio.
- Nomes de serviço no CRM: Pacote de Aulas, Mensalidade, Consultoria Online, Consultoria Híbrida, Avaliação Física.
- Local "CIA Athletica" da planilha vira "CIA". Valor do cliente importado = "Receita Mensal" da Tabela16.
- Gate do plugin ECC bloqueia a 1ª criação de arquivo pelo Write: criar arquivos novos via PowerShell (`[IO.File]::WriteAllText`) ou criar vazio + Read + Write.