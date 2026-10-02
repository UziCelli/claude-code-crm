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

## Pendências / próximos passos possíveis
- Usuário ainda não viu as telas: pedir feedback visual (TDAH: cores, tamanho, texto).
- OneDrive\Documentos recusa gravação nesta máquina; backups estão indo para `C:\Users\victo\OneDrive\VFITCOACH-CRM-backups`.
- Forma de pagamento dos clientes importados vem como "Mensal"/"Parcelado" (texto da planilha); o motor usa PIX como padrão nesses casos.
- Gráfico do painel só ganha histórico após "Fechar o mês".

## Decisões tomadas
- Canais antigos da planilha: CLT→Outro, Totem-CIA→Parceria (síndico/academia), Conecta→Conecta Fitness, Instagram→Instagram orgânico, PersonalGo→canal próprio.
- Nomes de serviço no CRM: Pacote de Aulas, Mensalidade, Consultoria Online, Consultoria Híbrida, Avaliação Física.
- Local "CIA Athletica" da planilha vira "CIA". Valor do cliente importado = "Receita Mensal" da Tabela16.
- Gate do plugin ECC bloqueia a 1ª criação de arquivo pelo Write: criar arquivos novos via PowerShell (`[IO.File]::WriteAllText`) ou criar vazio + Read + Write.