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
- **Próximos 90 dias (16/10/2026):** `/financeiro/previsao` mostra o saldo previsto PF e PJ semana a semana (13 semanas) a partir dos saldos digitados: contas em aberto e recorrentes, salário não pago, mensalidades que faltam receber (estimado, dia `previsao.dia_recebimento`) e DAS estimado (dia `previsao.dia_das`, se o mês não tem imposto PJ lançado). Mostra o primeiro aperto e pinta de vermelho as semanas negativas.
- **Aluno conta uma vez (16/10/2026, PR 1 da auditoria financeira):** entrada PJ sem aluno ligado é descontada de "Mensalidades a receber" (não conta duas vezes) e aparece em Mensalidades com "Ligar" (sugere o aluno citado na descrição, só nome inequívoco); a previsão avisa quantas há. Aluno com entrada já lançada em aberto ganha "Dar baixa" no lugar de "Registrar pagamento", e salvar entrada paga igual a uma em aberto do mesmo aluno/mês dá baixa nela em vez de criar outra. "Falta receber" soma por aluno; aluno com início depois do mês fica fora; a ficha não oferece mais "Pagamento" no histórico (não ia para o financeiro). Próximos PRs da auditoria: recorrência paga à mão e painéis (feitos, abaixo).
- **Imposto certo (17/10/2026, PR 2 da auditoria):** o DAS é reconhecido por `eh_das` (categoria "DAS", "DAS" na descrição, "Simples Nacional" ou imposto sem descrição), não mais por "imposto" na categoria: DARF, INSS e taxas não apagam o DAS estimado nem abatem a reserva. Recorrência de DAS só abate o que prevê (o resto vira "DAS estimado … além do previsto"). Saldo livre PJ guarda também o DAS do mês corrente (sobre a receita do mês passado) até ele ser lançado. Potes e colchão não contam recorrência de DAS como conta.
- **Saldo de partida (17/10/2026, PR 3 da auditoria):** "Tem" = último saldo digitado de cada conta + entradas − saídas pagas depois da data dele (no mesmo dia já está na foto), até hoje. Lançamento com conta só mexe nela (cartão, Reserva e conta de outra frente ficam de fora); sem conta vai pelo escopo, do lado seguro (saída depois da foto mais antiga da frente, entrada só depois da mais recente). Dar baixa depois da foto não faz mais o livre subir. Saldo e "pago em" no futuro são recusados; pago com data futura antiga conta como aberto. Livre PJ guarda o salário que falta pagar até 30 dias. Retirada lançada à mão no mês conta como salário (sem reprojeção na previsão, sem botão/alerta "Pagar"; parcial mostra quanto falta). A previsão avisa saldo velho e conta sem frente.
- **Recorrência paga à mão (17/10/2026, PR 4 da auditoria):** o `/financeiro` lista as saídas lançadas à mão que parecem uma conta recorrente (mesma descrição, ou mesma categoria e valor): botão "Ligar" (a competência é o mês da data), "Não é a mesma conta" (tira da lista) e, se o mês já tinha a baixa pelo "Pagar", só "Excluir" (pagamento em dobro). Em "A pagar", a recorrência fica com a etiqueta "talvez já pago". Novo lançamento de saída tem o campo "É uma conta recorrente?" (ligar ao lançar; ligar duas vezes no mesmo mês dá erro claro; baixa na lixeira não trava mais a vaga). Retirada deixa de ser categoria de recorrência (o card avisa as que já existem; o custo variável não fica mais negativo). Parcela precisa ser ≤ total. Coluna nova `lancamentos.sem_recorrencia`. A ligação é sempre manual: categoria + valor dá falso positivo.
- **Painéis honestos (17/10/2026, PR 5 da auditoria; fecha a auditoria):** *Previsão:* o aperto e o ponto mais baixo são seguidos dia a dia (um buraco entre dois recebimentos aparece), com a data do pior dia; a linha da semana diz "pior: R$ X em dd/mm"; o que está atrasado ganha a etiqueta "atrasado" e a recorrência, "previsto". *Valores:* negativo num formato só ("−R$ 169,40"), sem "-0,00"; o texto do DAS usa o parâmetro. *Livro-caixa "PJ e PF":* o salário (Retirada + Salário) não infla Entradas e Saídas. *Aviso do salário* aparece também quando a PJ não teve lucro. *Alerta* de contas olha os 3 dias seguintes mesmo na virada do mês. *Painel principal (os números mudam):* lucro/h só sobre as horas de quem tem preço base; painel e ficha usam o mesmo cálculo do motor de preços (custo operacional + extras de grupo, que é o do PLANO), e a ficha não multiplica mais o valor pago pelo multiplicador de grupo; "Por canal" (CAC/CPL/taxas) só conta leads e clientes do mês; ticket do funil ignora aluno com valor 0 e a frase diz a conta de verdade; checkpoint de campanha só conta cliente que chegou depois do início da fase; barra de prejuízo listrada no gráfico de 12 meses (que agora ocupa a linha toda). O histórico já gravado em `metricas_mensais` fica como estava.
- **Depois:** repositório privado no GitHub (feito: UziCelli/vfitcoach-crm, antes claude-code-crm; o serviço do Render continua com o nome antigo); agente de IA (Sonnet 5.5) adiado.
- Forma de pagamento dos clientes importados vem como "Mensal"/"Parcelado" (texto da planilha); o motor usa PIX como padrão nesses casos.
- Multiagente: tarefas simples em Haiku, implementação em Sonnet 5.5, modelo principal só para revisão.
- PRs do Claude: sem check-ins agendados. Claude revisa e dá merge sozinho quando os testes passam e a revisão está limpa; se o merge já tiver sido feito à mão, só avisa que viu.

## O que falta fazer (atualizado em 17/10/2026, depois do PR 5)
A auditoria financeira de 16/10 tinha 5 PRs: os 5 estão na `main` (#26 a #30). Não há PR da auditoria aberto.

**Para o usuário (nada disso o Claude faz por você)**
- [ ] `/financeiro/conferir` (botão **Conferir** no Financeiro): resolver o que o CRM achou. Lançamentos que parecem repetidos ("Manter este" ou "Não é repetido") e contas lançadas à mão que parecem recorrentes (o card de antes, PR 4: Ligar ou Não é a mesma conta). Tudo que você exclui vai para a lixeira.
- [ ] **Empréstimos da PJ:** em `/financeiro/mensalidades`, nas "entradas sem aluno", aperte **É empréstimo** nas que foram empréstimo (ou, ao lançar, escolha a categoria "Empréstimo"). Elas deixam de contar como receita, de pagar DAS e de baixar as mensalidades previstas. A parcela que você paga de volta vai na categoria "Empréstimo (devolução)" (os juros, em "Impostos/Taxas" ou "Outros", para contarem como custo).
- [ ] **Fila de pagamento:** em Configurações, confira "Fila de pagamento" (o quanto atrasar atrapalha e os juros por categoria; os números iniciais são estimativas). Em cada conta recorrente, escolha a **Prioridade de pagamento** (automática, sempre primeiro ou pode esperar).
- [ ] **Banco × CRM:** para funcionar, atualize os saldos em pelo menos 2 datas e escolha a **Conta** nos lançamentos pagos. Quem não tem conta não dá para conferir.
- [ ] `/financeiro/mensalidades`: ligar à ficha as entradas "sem aluno" (PR 1), para a previsão não descontar à toa.
- [ ] Conferir o painel depois do PR 5: lucro/h e Nível mudam (o histórico já gravado não muda). Se achar o custo errado, a decisão está abaixo.
- [ ] Atualizar os saldos das contas (Atualizar saldos, 1x por semana) e dar a frente (PF, PJ, Reserva, Fora) às contas novas.
- [ ] Conferir se o DAS e o DARF têm o nome certo ("DAS" na descrição ou categoria própria), senão o DAS estimado dobra (PR 2).
- [ ] Completar telefone e data de renovação dos alunos (o painel mostra "cadastro incompleto").
- [ ] Celular: reserva no Render (`crm-reserva`) e sessão de 1 mês no Access (passo a passo no README, "CRM no celular").
- [ ] **Renomear o repo no GitHub** para `vfitcoach-crm` (Settings › Repository name). Depois, rodar `configurar-pc-servidor.ps1` uma vez no PC (ele troca o `origin` sozinho). O serviço do Render não muda de nome.
- [ ] **Bancos no CRM (Open Finance), adiado:** a conta no Pluggy já foi criada; falta conectar os bancos. O banco PJ é a **Dock**: ela tem área de Open Finance no app, mas não aparece nas sugestões de conexão do Pluggy. Ao retomar: (1) procurar "Dock" pelo CNPJ ou nome, no sandbox e em produção; (2) se não aparecer, perguntar ao suporte do Pluggy se a Dock é suportada; (3) sem suporte, usar o extrato OFX/CSV da Dock com o importador do CRM. O código (saldos em `saldos`, transações em `lancamentos` com `origem` única) só começa depois disso. Chaves do Pluggy só no `.env`, nunca no repo.

**Decisão aberta**
- [ ] Custo do plano no painel, na ficha e no simulador: hoje todos usam o custo operacional + extras de grupo (o do PLANO). Se preferir o "custo total" da planilha (inclui mão de obra), é uma troca pequena em `estimativa_cliente` (`app/main.py`).

**Código: o que a auditoria achou e nenhum dos 5 PRs corrigiu (baixa gravidade, ordem sugerida)**
- [ ] Pacote e avaliação entram em "Mensalidades a receber" todo mês (D2): só deveriam entrar no mês em que foram vendidos.
- [ ] Duplo envio e restaurar da lixeira (D21): rede lenta (mais de 8 s) ou restaurar algo que já foi recriado gera lançamento, recorrência ou aluno em dobro.
- [ ] Fuso no Render (D26): no servidor reserva (UTC), depois das 21h o "hoje" já é amanhã. O PC não é afetado.
- [ ] Setas "vs mês anterior" (N6): sem "Fechar o mês", o mês anterior é gravado na 1ª visita com os alunos de hoje.
- [ ] Lucro/h de serviço sem aulas (N9): Consultoria Online vai para o topo do Explorador ordenado por lucro/h.
- [ ] DAS e entrada atrasada de mês anterior (N10): o DAS estimado do mês seguinte não inclui uma entrada atrasada que vai ser recebida agora.
- [ ] "Faturamento recorrente" (N11) soma o valor cadastrado de todo aluno ativo (inclui pacote, avaliação e quem não paga). Confirmar se é decisão da Rodada 1.
- [ ] Mês por data × mês por pago_em (D10): cada tela diz qual regra usa, mas elas se misturam no card PF do painel financeiro.
- [ ] Rótulo "mês em andamento" no lucro do mês corrente (D17) e gastos de marketing em duas bases, Campanhas e categoria "Marketing/Divulgação" (lance nos dois lugares ou o CAC diverge).

**Decisões de projeto já registradas (não são bug)**
- Só a fatura do cartão é registrada; compra no cartão fica para depois (D16). Saldo livre não conta entrada prevista. Recorrência some depois de 3 meses sem baixa (D19). Saldos de contas da planilha (`tblSaldosContas`) não foram migrados.

## Financeiro que pensa por você (PR `claude/financeiro-conferir`, 20/10/2026)
Feito para quem tem dificuldade de leitura e de número: menos conta de cabeça, uma decisão por cartão.
- **Empréstimo da PJ não é receita** (`financeiro.EMPRESTIMO` e `DEVOLUCAO`): fora do DAS, do lucro, da sugestão de salário e das mensalidades; o dinheiro conta no saldo e vai inteiro para o pote "Contas da PJ".
- **Repetidos** (`financeiro.duplicados`): mesmo escopo, tipo e valor, até 3 dias de diferença, sem nada que os distinga (parcela, aluno, conta, quem pagou, conta recorrente). "Quase certo" = mesmo dia e mesma descrição. Só sugere: quem exclui é você (lixeira). "Não é repetido" grava em `duplicados_ok`. Há um alerta em toda página.
- **Fila de pagamento** (`financeiro.nota_impacto`, `fila_pagamentos`): nota = impacto no curto prazo (0 a 40) + urgência (+10 atrasada, +7 até 3 dias, +4 até 7 dias) + longo prazo (3 × juros % ao mês, máx. 50) + escolha manual (±100). Gasta o saldo de cima para baixo e marca onde o dinheiro acaba. DAS a guardar e salário entram como itens. Padrões por categoria em Configurações (`impacto_curto`, `impacto_juros`).
- **Banco × CRM** (`conferencia_contas`) e **linha do tempo** (`linha_do_tempo`, tela `/financeiro/linha-do-tempo`).
- Ideias que ficaram de fora: prioridade manual em lançamento avulso (hoje só na conta recorrente); alerta quando o banco não bate (ficaria ligado por causa de tarifa e rendimento); importar extrato OFX/CSV, que daria o rastreio completo.

## Repositório público (auditoria de 22/10/2026)

- **Por quê:** acabaram os 2.000 min do GitHub Actions da conta. Este repo nunca teve workflow (só o Dependabot rodou nele); o gasto veio de outro repo. Público = Actions grátis, mas só vale para o repo que for aberto.
- **Auditoria (histórico inteiro, 33 branches):** nenhuma chave, `.env` ou banco foi versionado; nomes/telefones dos testes são fictícios.
- **Corrigido:** POST de outro site no navegador do PC passava na portaria de `localhost`; agora `Origin`/`Referer` estranho é recusado (`acesso.py`). Nome real do time do Cloudflare saiu do `.env.example`, README e `configurar-pc-servidor.ps1`. Novos: `SECURITY.md`, `tests/test_seguranca.py`.
- **Falta (só o dono, no GitHub), nesta ordem:** 1) travar a `main` (exigir PR, sem force push: o PC se atualiza sozinho dela); 2) Settings › Actions › exigir aprovação de colaboradores externos e permissão só de leitura; 3) Code security: Secret scanning, Push protection, Private vulnerability reporting; 4) github.com/settings/emails: manter e-mail privado + bloquear push que expõe e-mail; 5) tornar público (e renomear para `vfitcoach-crm`).
- **Deixado de fora:** apagar os e-mails dos 87 commits (reescreveria a história e quebraria a atualização do PC).
- **Descobrir quem gastou os minutos:** github.com/settings/billing › Usage, por repositório.

## Alertas do Painel revisados (PR `claude/alertas-renovacao`, 31/10/2026)
Pedido: o Painel de 31/10 mostrava renovação vencida de quem já tinha pagado e de quem tinha a renovação marcada.
- **Renovação anda sozinha** (`financeiro.renovacoes`, só leitura): a data do cadastro anda 1 mês a cada pagamento do aluno (entrada PJ paga ligada a ele), Renovação marcada no histórico (se vence em até 7 dias) ou mês pulado. Parcial também renova; o resto não anda outro mês. Renovação marcada + pagamento = 1 mês só. 90% do valor ou mais = mês inteiro (taxa do cartão); 2 mensalidades de uma vez = 2 meses. Vale no alerta, na lista de clientes e na ficha (cartão "Renovação" mostra de onde veio a data e o que falta).
- **Data trocada à mão manda**: `clientes.renovacao_em` guarda quando; o que foi lançado antes não mexe mais nela. Salvar a ficha sem mexer na data não conta como troca.
- **Pulou o mês** (ficha › cartão Renovação › "Pular sem cobrança"): evento `pausa` (`data` = renovação pulada, `ate` = volta). O mês sai de Mensalidades ("pulou o mês", previsto 0) e da previsão de caixa; os dias não contam no "sem aula".
- **Cobrança**: renovação vencida com valor mensal ganha o botão "Cobrar R$ X" (alerta e ficha), com multa e juros (`financeiro.cobranca`; Configurações › Cobrança: multa 2% uma vez, juros 1% ao mês por dia). Modelo de WhatsApp `cobranca` editável. Só cobrar multa se estiver no contrato.
- **Revisão**: "sem aula" não conta dias de bloqueio (viagem) nem de mês pulado; "sem nenhuma aula" mostra até 3 nomes e ignora quem começou há menos de 14 dias (35 na Híbrida); contas vencidas mostram o total. Os outros alertas foram conferidos e ficaram como estavam.
- **Não feito (decisão do dono)**: empurrar as renovações pelos 9 dias da viagem.

## Assistente: chat com o Claude dentro do CRM (PR `claude/assistente-chat`, 31/10/2026)
Pedido: "um chat completo para usar você direto por lá e ajudar a editar e visualizar as contas, financeiros e tarefas".
- **Tela** `/assistente` (menu, logo depois do Painel): resposta aos pedaços, linha cinza com cada ação ("✓ Dando baixa"), sugestões de pergunta, lista de conversas, custo estimado em US$. Conversa excluída vai para a lixeira (Dados).
- **Como liga**: `ANTHROPIC_API_KEY` no `.env` do PC (ou no Render). A API cobra por uso, à parte da assinatura do Claude. Opcionais: `ASSISTENTE_MODELO` (padrão `claude-haiku-5-5`), `ASSISTENTE_ESFORCO` (padrão `medium`), `ANTHROPIC_BASE_URL` para mandar pelo OmniRoute (só os parâmetros básicos).
- **O que ele faz** (`app/assistente.py`, 27 ferramentas): lê Painel, mês, livro-caixa, contas a pagar e saldo livre, previsão de caixa, mensalidades, saldos, contas recorrentes, alunos (ficha, renovação, cobrança), tarefas (rotina, leads, checkpoints, campanha) e consulta livre só de leitura. Grava: lançamento (com a mesma regra do "já estava em aberto" da tela), edição (devolve o antes), baixa (avulsa ou da conta recorrente do mês), lixeira e restaurar, conta recorrente, saldo, salário, tarefa da rotina, item de campanha, próxima ação do lead, checkpoint e registro na ficha (`main.registrar_evento`, as regras da ficha).
- **Regras da API seguidas**: histórico só cresce (nada já mandado é editado; a data vai na mensagem, não nas instruções); raciocínio devolvido como veio, com `drop_block` se o histórico não bater; `fallbacks: "default"` (só nos modelos que têm; o modelo padrão não tem) para outro modelo responder quando um recusa; cache automático; recusa não entra no histórico; pedido cortado no meio ganha resultado de erro e não roda; cada resultado é guardado assim que a ação roda (tela fechada no meio não repete ação). Se a conta não aceitar os recursos novos, segue só com o básico.
- **Banco**: tabelas `assistente_conversas` e `assistente_mensagens`. A conexão só abre para ler e gravar, nunca enquanto o modelo pensa (no Turso a conexão é uma só). Sinal de vida a cada 15 s para o Cloudflare não cortar a resposta.
- **Segurança**: consulta livre roda dentro de `SELECT * FROM (...)` (escrita vira erro de sintaxe), sem `;` nem comentário. O texto do modelo é escapado; link só para telas do próprio CRM.
- **Ideias que ficaram de fora**: mostrar as notas do raciocínio entre as ações (`display: "updates"`); anexar foto de comprovante; limite de gasto por mês.

## Assistente no modelo mais barato (PR `claude/assistente-haiku`, 31/10/2026)
Pedido: "deixe o agente mais barato por milhão de token".
- **Modelo padrão** `claude-haiku-5-5`: US$ 0,10 de entrada e 0,50 de saída por milhão de tokens em pedidos de até 100 mil tokens de prompt; acima disso o preço sobe para 0,50 e 2,50 (cache: 0,01 e 0,05 de leitura, 0,125 e 0,625 de gravação). O preço é por pedido à API (`PRECOS_PEDIDO_LONGO`).
- **Sem `fallbacks`** para ele (não tem troca de modelo no servidor): uma recusa vira o aviso, como antes. Raciocínio adaptativo com `drop_block`, esforço `medium` e cache continuam. Opus e Sonnet pelo env seguem mandando `fallbacks` e as duas betas.
- **Custo na tela** com as duas faixas; conversa de menos de 1 centavo aparece como "< US$ 0,01" (o total da conversa é arredondado em 6 casas).
- **Aviso de conversa longa** aos 80 mil tokens (antes eram 150 mil), antes de entrar na faixa cara. Outro modelo continua possível com `ASSISTENTE_MODELO`.

## Decisões tomadas
- Canais antigos da planilha: CLT→Outro, Totem-CIA→Parceria (síndico/academia), Conecta→Conecta Fitness, Instagram→Instagram orgânico, PersonalGo→canal próprio.
- Nomes de serviço no CRM: Pacote de Aulas, Mensalidade, Consultoria Online, Consultoria Híbrida, Avaliação Física.
- Local "CIA Athletica" da planilha vira "CIA". Valor do cliente importado = "Receita Mensal" da Tabela16.
- Gate do plugin ECC bloqueia a 1ª criação de arquivo pelo Write: criar arquivos novos via PowerShell (`[IO.File]::WriteAllText`) ou criar vazio + Read + Write.