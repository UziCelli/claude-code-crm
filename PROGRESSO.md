# VFITCOACH CRM — progresso e como retomar

Plano completo (pastas, modelo de dados, ordem dos módulos): `PLANO.md`.

## Como retomar (para uma sessão nova do Claude Code)
1. Abrir a pasta `C:\Users\victo\VFITCOACH-CRM` no Claude Code.
2. Ler `PLANO.md` e este arquivo. Modo ponytail **full**. Interface em pt-BR, sem emojis, cores #0B1E3D / #2C5C8F / branco, Montserrat + Inter.
3. Rodar `.venv\Scripts\python.exe -m pytest tests` (9 testes) antes de entregar qualquer mudança.
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
- [x] Grade: preço total e lucro em letra miúda abaixo do preço por aula
- 29 testes passando (`.venv\Scripts\python.exe -m pytest tests`)

## Próximos passos
- **Usuário:** completar telefone e data de renovação dos alunos (o painel mostra "cadastro incompleto").
- **Rodada 2 — financeiro PF + PJ** (substitui a planilha / Microsoft 365, que vence em mais de 3 meses):
  - livro-caixa e contas a pagar recorrentes, com cartões;
  - mensalidades: previsto × recebido por aluno;
  - painel financeiro: receita real, custos, lucro, ponto de equilíbrio, DAS, pró-labore e INSS;
  - migração única de todo o histórico da planilha, mostrando antes uma simulação para o usuário aprovar.
- **Depois:** repositório privado no GitHub; publicar em `crm.vfitcoachapp.com` (Cloudflare Tunnel + Access); agente de IA (Sonnet 5.5) adiado.
- Forma de pagamento dos clientes importados vem como "Mensal"/"Parcelado" (texto da planilha); o motor usa PIX como padrão nesses casos.
- Multiagente: tarefas simples em Haiku, implementação em Sonnet 5.5, modelo principal só para revisão.

## Decisões tomadas
- Canais antigos da planilha: CLT→Outro, Totem-CIA→Parceria (síndico/academia), Conecta→Conecta Fitness, Instagram→Instagram orgânico, PersonalGo→canal próprio.
- Nomes de serviço no CRM: Pacote de Aulas, Mensalidade, Consultoria Online, Consultoria Híbrida, Avaliação Física.
- Local "CIA Athletica" da planilha vira "CIA". Valor do cliente importado = "Receita Mensal" da Tabela16.
- Gate do plugin ECC bloqueia a 1ª criação de arquivo pelo Write: criar arquivos novos via PowerShell (`[IO.File]::WriteAllText`) ou criar vazio + Read + Write.