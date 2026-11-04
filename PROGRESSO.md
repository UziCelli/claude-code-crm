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
- **Potes e colchão (16/10/2026; os potes saíram em 31/10/2026, ver "Financeiro simples"):** cada entrada PJ recebida enche em cascata imposto (DAS%) → contas da PJ do mês → salário PF → colchão (`potes_mes`). Ao salvar entrada PJ paga, a mensagem diz quanto separar em cada pote. Painel: card do colchão (1 e 3 meses de custo fixo, guardado nas contas Reserva, meta em Configurações, grupo `colchao`; 0 = sem meta).
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
- [x] Custo do plano: resolvido pela regra do tempo da mão de obra (seção "Mão de obra = pró-labore", 04/11/2026).
- [ ] Configurações → "Mão de obra": preencher os minutos da consultoria por mês e da avaliação (0 = ainda usa a planilha).

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

## Chave do Assistente em Configurações (PR `claude/assistente-chave-config`, 31/10/2026)
Pedido: colar a chave da API na tela, sem mexer no `.env`.
- **Onde fica**: tabela `segredos` (linha `anthropic_api_key`), separada das tabelas comuns para o assistente e as telas nunca a listarem sem querer. Fica em memória (`assistente._chave_salva`), lida na partida; o `_cliente()` não abre o banco.
- **Prioridade**: `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` do ambiente vencem a salva. A tela mostra só o final (`…abcd`) e o campo vem sempre vazio.
- **`consultar_banco` bloqueado** para qualquer SQL com "segredos": o modelo não lê a chave.
- **Render**: pega a chave pelo Turso (o banco é o mesmo); backups também a levam, então guarde-os como senha.

## Financeiro simples (PR `claude/financeiro-simples`, 31/10/2026)
Pedido: os painéis de Potes e Banco × CRM eram incompreensíveis. Agora são frases curtas.
- **Imposto em uma frase**: `financeiro.imposto_mes(con, mes, hoje)` é a única conta do imposto (DAS% × entradas PJ pagas do mês, sem empréstimo, menos o DAS já lançado/previsto). O Saldo livre usa a mesma função; `/financeiro` mostra "Imposto a separar este mês: R$ X (DAS N%)"; ao salvar entrada PJ paga a mensagem é "Separe R$ X para o imposto (DAS N%)." (`aviso_imposto`; vale também para o Assistente). `potes_mes`, `texto_divisao` e a tela de Potes foram removidos.
- **"Colchão" some das telas**: contas Reserva mostram "Reserva: R$ X"; o painel diz "Reserva: N meses de custo fixo". A barra salário × gasto PF ficou só em `/financeiro`. O grupo `colchao` do banco e `financeiro.colchao()` mantêm o nome (só o texto mudou).
- **Banco × CRM por conta**: "Inter: você digitou R$ A em dd/mm. Pelos lançamentos, devia ter R$ B. Diferença: R$ C." + uma linha de causa (saldo 0 digitado; lançamento repetido; lançamentos pagos sem conta; senão falta entrada ou saída). Botões: "Lançar a diferença" (abre o Novo lançamento já preenchido, na data da foto, via `/financeiro?novo=1&conta=...`), "Ver lançamentos desta conta" (`/financeiro?conta=...&mes=...`, filtro só do livro-caixa) e "Está certo" (grava em `parametros` grupo `conferencia_ok`: chave = conta, valor_texto = data da foto, valor = saldo; some até haver foto nova ou saldo diferente no mesmo dia).
- **Contador**: as diferenças entram em "Conferir (N)" e no "Tudo certo". O card repetido de Conferir no `/financeiro` saiu.
- **Salário na PF com conta**: `pagar_salario` grava a entrada PF na conta PF com a foto de saldo mais recente (sem foto, fica sem conta). Antes a PF sempre "tinha a mais" o valor do salário.
- **Telas de dentro do Financeiro** têm todas o mesmo link "← Financeiro" no topo.

## Propostas com vários horários (PR `claude/propostas-varios-horarios`, 03/11/2026)
Pedido: a aba Simulador vira **Propostas**; vários dias/horas/locais na mesma proposta; ajuste de preço; PDF com desconto.
- **Aba renomeada**: `/propostas` (o antigo `/simulador` redireciona com os mesmos filtros). Links do menu, ficha, Leads, Explorador e alertas atualizados.
- **Vários horários**: marque os dias (Seg…Sáb), escolha hora e local e "+ Adicionar horário". Cada horário vira `dia-hora-local` na URL (`h=`) e, ao salvar, uma linha em `proposta_horarios`. Pode misturar locais (ex.: Seg SmartFit + Sex CIA).
- **Preço**: `precos.calcular_misto` faz a média do preço cheio e do custo de todos os horários (mesmo preço = fica igual). Aviso se o horário está ocupado/indisponível na grade ou se o nº de horários não bate com o plano (ex.: 3x/sem com 1 horário).
- **Ajuste**: abaixo da margem, botão "Subir para R$ Y (margem mínima)"; acima, "Dar o desconto máximo"; "Voltar ao preço cheio". Desconto (%) ou Preço final (R$): um apaga o outro; preço acima do cheio aparece como acréscimo.
- **PDF**: com desconto mostra "de ~~R$ X~~ por **R$ Y**", o "−Z% de desconto" e quanto economiza (`propostas.preco_cheio`, coluna nova). Sem desconto, só o valor.

## Novo local pelo pop-up (PR `claude/novo-local-popup`, 03/11/2026, depende do PR anterior)
Pedido: cadastrar academias novas direto da Grade, Agenda e Propostas, com taxas e deslocamento, gerando a grade com preços.
- **Pop-up "+ Novo local"** (`_dlg_local.html`, rota `POST /locais/novo`): nome; taxa por aula (1 pessoa); taxa por pessoa a mais; máximo de pessoas; deslocamento (R$/aula); tempo de deslocamento (min/aula); taxa mensal fixa + aulas por mês; "copiar preços e grade de" (padrão CIA).
- **Como montar os preços** (pergunta do pop-up): "Manter a margem" = o preço acompanha o custo; "Manter o preço" = só a margem muda.
- **Custos** ficam na tabela nova `locais_custos`. Custo por aula = taxa + deslocamento + taxa mensal ÷ aulas do mês.
- **Preços** (`app/locais.py`): copia Pacote de Aulas e Mensalidade da referência (origem `local:<ref>`), trocando o custo por aula da referência pelo do novo local × sessões.
- **Motor** (`precos.py`): o local novo cobra a taxa por pessoa a mais, respeita o máximo de pessoas e soma o tempo de deslocamento às horas (o lucro/hora cai).
- **Grade**: copia horários e multiplicadores da referência, todos livres (sem grade na referência: Seg–Sáb 05h–23h). A lista de locais da Grade agora junta a lista de Configurações + os locais que já têm grade.
- **Base para copiar**: só a CIA ou um local criado pelo pop-up (dos locais da planilha o sistema não sabe a taxa por aula; copiar cobraria a taxa duas vezes). Nome repetido com outra caixa ("cia") dá erro.
- Fora do escopo: conta mensal automática (como a da CIA) para o local novo; ajuste fino continua em Configurações > Preços base.

## Bugs graves — PR 1: preços e locais (PR `claude/bugs-precos-locais`, 03/11/2026)
Revisão com 4 agentes; plano dos 10 bugs graves em 3 PRs (este, agenda, custos dos locais no financeiro).
- **Taxa da CIA**: mudar `taxa_cia[1]` em Configurações agora ajusta o custo dos preços da CIA (Pacote/Mensalidade/Aula avulsa) em (nova − antiga) × sessões (`locais.ajustar_custos_cia`). Antes a margem da CIA não mudava e o "+ Novo local" descontava a taxa nova de um custo com a velha.
- **Manter a margem com custo zero**: o preço não vira mais R$ 0; fica o da referência e o aviso diz em quantos planos ("Mantive o preço…").
- **Grupo maior que a tabela** (5+ pessoas): usa o maior multiplicador/mão de obra/taxa da CIA configurado (`precos.por_grupo`). Antes um grupo de 5 custava o preço de 1.
- **"Pacote de 8 aulas"** (rótulo das Propostas) agora é entendido por `aulas_mes` (antes só "Pacote 8").
- **Local da CIA**: "CIA" no começo sem outra letra colada ("CIA", "Cia 111", "CIA2", "CIA Athletica"); "Ciagym" e "Ciática Studio" não geram conta da CIA.
- Reimportar a planilha não desfaz a taxa da tela: o custo da CIA importado troca a taxa da planilha (Tabela18) pela de Configurações.
- Configurações mostra números com vírgula ("70,125"): com ponto, salvar a tela lia "70.125" como 70 mil.
- Testes: `tests/test_precos_bugs.py`.

## Bugs graves — PR 2: agenda (PR `claude/bugs-agenda`, 03/11/2026)
- **Fuso do Brasil**: `app/__init__.py` põe `TZ=America/Sao_Paulo` (e `render.yaml` também). Datas gravadas saem do Python (`dt.date.today()`), não de `date('now','localtime')`: no Turso o SQL roda em UTC e depois das 21h "hoje" virava amanhã.
- **No máximo 2 por horário**: avulsa em horário com 2 alunos é recusada ("Horário cheio"; quem desmarcou/cancelou não conta). Avulsa no horário fixo do próprio aluno também. Aluno que volta a ficar ativo (status, ficha, mês pulado, renovação ou lixeira) sai do horário fixo que lotou enquanto estava parado, com aviso (`tirar_dos_lotados`).
- **Avulsa repetida** (clique duplo): recusada. Reposições e o controle do mês contam cada (data, hora) uma vez, mesmo com duplicatas antigas no banco.
- **Mudar horário ou local não reescreve o passado**: nova coluna `agenda_fixos.vigente_de`. Tirar um horário é exclusão suave com data; trocar o local cria linha nova. `aulas_da_semana` usa a linha que valia em cada dia (`fixo_vale`). Linha criada e tirada no mesmo dia é ajuste e não conta. Aluno novo fica com `vigente_de` vazio (vale desde a data de início).
- **Lixeira de horário fixo**: restaurar um horário tirado antes de hoje cria uma cópia que vale de hoje em diante (a linha antiga fica como estava). Tirado hoje, só desfaz. A lixeira mostra só a linha mais nova do aluno em cada dia e hora.
- Testes: `tests/test_agenda_bugs.py`.

## Bugs graves — PR 3: custos dos locais novos no financeiro (PR `claude/contas-locais`, 03/11/2026)
- **Conta automática de cada local** criado pelo "+ Novo local" (menos a CIA, que tem a dela): chave `local:<nome>:AAAA-MM`, categoria Aluguel, descrição "<local>: aulas de MM/AAAA". Mesmo fluxo da CIA: nasce no mês seguinte, recalcula enquanto em aberto, não nasce se já foi lançada à mão (o nome do local inteiro na descrição) e liga na recorrência que cita o local.
- **Valor**: cada (data, hora) com aula Feita no local = taxa por aula; + taxa por pessoa a mais × (pessoas − 1); + taxa mensal uma vez, só se teve aula no mês. Vence no dia `contas_auto.dia_locais` (padrão: o da CIA).
- **Prévia do Financeiro** mostra "<local> este mês até agora".
- **CIA e locais olham o local que valia no dia** (`app/vigencia.py: fixo_vale`, o mesmo da Agenda): mudar o local do horário não muda a conta do mês que passou.
- **Deslocamento fica fora da conta**: é a gasolina do personal, não um pagamento ao local (continua no custo da proposta). Gasto com o nome do local na categoria Transporte não impede a conta do local.
- **Nome mais específico ganha**: "Aluguel Smart Fit" é do "Smart Fit", não do "Fit"; "Aluguel Studio 111" é do Studio, não da CIA. Vale para a recorrência e para a conta lançada à mão.
- **Aula sem hora (pela ficha) conta uma vez**: vai para o primeiro horário do aluno no dia (avulsa ou fixo, em qualquer local).
- **Mesmo nome sem acento é o mesmo local**: "Acadêmia" com "Academia" já criado dá erro; dado antigo repetido gera uma conta só.
- **Uma leitura por rodada**: aulas, custos, parâmetros e contas já lançadas são lidos uma vez, não um por local (Turso).
- Fica para depois: conta em aberto não zera se a única aula for desfeita (igual à CIA); nome de local genérico ("Centro") pode casar gastos sem relação.
- Testes: `tests/test_contas_locais.py`.

## Bugs médios (PR `claude/bugs-medios`, 03/11/2026)
- Cores da Grade seguem a margem mínima do plano (verde ≥ mínima, amarelo até 5 pontos abaixo); a legenda mostra os números.
- Local com "&" no nome: links e redirecionamento da Grade codificados.
- Margem mínima + imposto + taxas ≥ 100%: Configurações recusa e o cálculo dá mensagem em vez de cair.
- Aluno parado/inativo solta as células da Grade; voltando a ativo, retoma os horários fixos.
- "+ Novo local" volta para a mesma tela (semana da Agenda, Propostas com filtros). Testes: `tests/test_bugs_medios.py`.

## Bugs pequenos (PR `claude/bugs-pequenos`, 03/11/2026)
- Propostas: as observações voltam preenchidas quando o salvar dá erro.
- Contas automáticas: conta em aberto (do app, sem edição) cujo mês zerou é apagada; volta sozinha se o valor voltar. Paga ou editada fica.

## Editar e excluir local (PR `claude/locais-editar`, 04/11/2026)
- Grade de um local criado pelo "+ Novo local": botões **Editar local** (mesmo pop-up, nome travado) e **Excluir local**.
- Editar troca os custos e refaz os preços de Pacote e Mensalidade pela diferença do custo por aula (manter margem ou manter preço). A grade fica.
- O nome não muda: está gravado em alunos, agenda, grade e contas automáticas.
- Excluir é recusado enquanto houver aluno não inativo, horário fixo ou célula ocupada no local; senão apaga custos, preços, grade e o nome da lista. Aulas e contas antigas ficam.

## Aviso de dois locais seguidos (PR `claude/aviso-deslocamento`, 04/11/2026)
- Ao incluir um horário fixo na Agenda ou salvar uma proposta, o sistema confere a mesma hora, a hora anterior e a seguinte do dia.
- Se houver aula fixa (de aluno ativo) em **outro local**, a mensagem de sucesso ganha um "Atenção: ..." com o deslocamento em minutos (quando o local tem). Não bloqueia.
- Uma consulta só (`aviso_deslocamento` em `app/main.py`). O próprio aluno na mesma hora não conta (é ele mudando de local).
- Testes: `tests/test_aviso_deslocamento.py`.

## Excluir horário hoje não some com a aula de hoje (PR `claude/vigencia-hoje`, 04/11/2026)
- `fixo_vale`: o horário vale até o dia da exclusão, inclusive. Excluir hoje vale a partir de amanhã; a aula de hoje fica na Agenda e na chamada.
- Trocar de hora ou de local hoje: vale só a linha nova no dia (`trocada_no_dia`), sem aula dupla.
- Criado e excluído no mesmo dia continua sendo engano (nunca vale).
- Aluno inativo: as aulas já marcadas da semana continuam aparecendo (histórico). As não marcadas não aparecem (não viram "pendente").
- Testes: `tests/test_vigencia_hoje.py`.

## Revisão de segurança (PR `claude/seguranca-revisao`, 04/11/2026)
- Conferido e OK: portaria do Cloudflare Access (falha fechada), CSRF por Origin/Referer, Host localhost contra DNS rebinding, escape dos templates e do markdown do assistente, SQL com `?`.
- "+ Novo local": o destino de volta usa `_caminho_seguro` (antes `/\mal.com` levava para outro site).
- `_num_br`: "inf"/"nan" viram erro de número na tela (antes davam erro 500 ou preço infinito).
- Proposta com lead/cliente que não é número: volta com aviso (antes erro 500).
- Consulta SQL do assistente roda com `PRAGMA query_only=ON` (2ª trava contra gravação).
- Testes: `tests/test_seguranca.py`.

## Cobrança no WhatsApp por estágio + cartão com QR Pix (PR `claude/cobranca-whatsapp`, 04/11/2026)
- 5 estágios pelo dia do vencimento (só aluno ativo): Lembrete (faltam 1–2 dias), Vence hoje, Esquecimento (1–9 dias de atraso), Moderada (10–29), Crítica (30+). O menu mostra só o do dia, em destaque.
- Textos editáveis em Configurações (`cobranca_lembrete`, `cobranca_hoje`, `cobranca`, `cobranca_moderada`, `cobranca_critica`), sem multa e juros no texto. Migração troca o texto antigo de `cobranca` só se ainda for o original.
- Cartão-imagem (`app/cartao.py`, rota `/clientes/{cid}/cobranca/cartao.svg`): texto do estágio, QR Pix com valor, valor/vencimento/favorecido/banco/chave, código copia-e-cola, logo e "Victor | VFITCOACH".
- Pix copia-e-cola e QR sem serviço externo (`app/pix.py`, lib `segno`). Precisa de favorecido e cidade em Configurações; sem eles o cartão sai sem QR, só com a chave.
- O botão gera o PNG: no celular abre o compartilhar (imagem + código); no PC baixa o PNG e abre o wa.me com só o código (anexar a imagem à mão). O evento registra o estágio.
- Testes: `tests/test_pix.py`, `tests/test_menu_whatsapp.py`, `tests/test_alertas.py`.

## Botão WhatsApp dos Alertas já envia o cartão (PR `claude/cobranca-whatsapp`, 04/11/2026)
- Alerta de aluno vencido ou vencendo em até 2 dias: o botão tem o rótulo do estágio ("Cobrar R$ X · 5 dias" etc.) e faz o mesmo que o da ficha (gera o PNG, compartilha ou baixa + wa.me, registra o evento).
- Depois de enviar, o botão vira "Enviado ✓".
- O PNG só é gerado quando o botão fica visível na tela (`IntersectionObserver`), porque os alertas também estão no topo de todas as páginas.
- Outros alertas (renovação com 3–7 dias, faltas etc.) continuam como antes.
- Testes: `tests/test_alertas.py`.

## Pacote personalizado de 1 a 20 aulas, com ou sem consultoria (PR `claude/pacotes-1-a-20`, 04/11/2026)
- Propostas → plano "Pacote personalizado": você digita o nº de aulas (1 a 20, ímpar também) e, se quiser, as aulas por semana.
- Tamanho que não está cadastrado: o preço é interpolado entre os pacotes vizinhos (7 = meio caminho entre 6 e 8). A "Aula avulsa" vale como pacote de 1. Fora da faixa cadastrada: proporcional por aula (`precos.base_pacote`).
- Campo "Consultoria": "Sem consultoria (pacote avulso)" ou "+ Consultoria Online/Híbrida (acompanhamento completo)". Soma preço e custo da consultoria × meses do pacote × pessoas. Os meses vêm de aulas ÷ aulas por semana (2 se ficar em branco).
- Desconto da consultoria no combo: Configurações → "Pacote personalizado" (15% de início).
- A proposta salva guarda a consultoria (coluna `propostas.consultoria`) e o PDF mostra "+ Consultoria … (acompanhamento completo)".
- Testes: `tests/test_precos.py`, `tests/test_propostas.py`.

## Mão de obra = pró-labore, pela regra do tempo (PR `claude/mao-de-obra-regra-tempo`, 04/11/2026)
- Decisão do Victor: **mão de obra = pró-labore (salário)**, sempre custo; **lucro = o que sobra para investir na empresa**.
- Regra (`precos.minutos_trabalho` e `precos.custo_servico`): **mão de obra = horas de trabalho × valor da hora** (Configurações → "Mão de obra").
  - Pacote / Aula avulsa: aulas × (aula + deslocamento do local) + planejamento do pacote.
  - Mensalidade: aulas do mês × (aula + deslocamento) + planejamento do mês.
  - Consultoria: minutos por mês (+ as aulas da Híbrida). Avaliação: minutos + deslocamento. **0 = usa o valor da planilha.**
  - Grupo: o esforço extra (`grupo_mao_obra_extra`, +20%/+35%/+55%) incide sobre essa mão de obra.
  - Valor da hora 0 = regra desligada (tudo como a planilha).
- Valores iniciais = a conta da planilha: 46,17/h × (aulas + 1 h de planejamento). Pacote de 8 = 415,51; de 4 = 230,84. Os preços de hoje não mudam.
- O "Custo Operacional" da planilha já traz a mão de obra dentro: o motor tira a da planilha e põe a da regra.
- Corrigido: o acompanhamento completo somava a mão de obra da consultoria **duas vezes** (custo operacional + mão de obra).
- Lucro/hora divide pelas **horas de trabalho** (aulas + deslocamento + planejamento + consultoria). Propostas mostram o pró-labore e as horas.
- O deslocamento de um local agora custa pró-labore (antes só baixava o lucro/hora).
- `mao_obra_aula` (Tabela24) saiu de Configurações: nenhum cálculo usava.
- Testes: `tests/test_precos.py`, `tests/test_propostas.py`, `tests/test_locais.py`.

## Decisões tomadas
- Canais antigos da planilha: CLT→Outro, Totem-CIA→Parceria (síndico/academia), Conecta→Conecta Fitness, Instagram→Instagram orgânico, PersonalGo→canal próprio.
- Nomes de serviço no CRM: Pacote de Aulas, Mensalidade, Consultoria Online, Consultoria Híbrida, Avaliação Física.
- Local "CIA Athletica" da planilha vira "CIA". Valor do cliente importado = "Receita Mensal" da Tabela16.
- Gate do plugin ECC bloqueia a 1ª criação de arquivo pelo Write: criar arquivos novos via PowerShell (`[IO.File]::WriteAllText`) ou criar vazio + Read + Write.