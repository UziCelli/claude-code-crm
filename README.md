# VFITCOACH CRM

CRM do VFITCOACH (personal trainer, São Paulo), usado pelo navegador do celular ou do computador em
**https://crm.vfitcoachapp.com**.

## Onde o CRM roda
- **Servidor:** Render, plano grátis (serviço `claude-code-crm.onrender.com`), com o código Python desta pasta (`app/`).
  Sem uso, o Render dorme e leva cerca de 1 minuto para acordar no primeiro acesso.
- **Portaria:** o Cloudflare Access fica na frente de `crm.vfitcoachapp.com`: pede o seu e-mail e manda um código. O CRM confere
  o token do Cloudflare em cada pedido (`app/acesso.py`). Sem `CF_ACCESS_TEAM_DOMAIN` e `CF_ACCESS_AUD`, nada aparece.
- **Banco:** Turso (plano grátis). O Render trabalha numa réplica local que sincroniza com o Turso; as gravações vão direto ao Turso.
- **Variáveis do serviço no Render:** `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD` e,
  se quiser, `ANTHROPIC_API_KEY`. Nunca no código (ver `.env.example`).
- **Saúde:** o workflow `Saúde do CRM` (GitHub Actions, a cada hora) confere se a portaria responde e abre uma Issue se cair.
- O PC, o Cloudflare Tunnel e a reserva no Google Cloud Run **não são mais usados**. Os arquivos daquela época
  (`iniciar-crm.bat`, `configurar-pc-servidor.ps1`, `app/atualizar.py`, `app/vigia.py`, `cloudflare/worker-reserva.js`, `Dockerfile`)
  saem na última fase da reescrita.

## Reescrita em andamento (Cloudflare Workers)
O CRM está sendo reescrito em TypeScript para o Cloudflare Workers (pasta `worker/`), numa PR só, que vai ao ar de uma vez no merge.
Até lá nada muda em produção. Decisões, limites do plano grátis, medições e passo a passo da ida ao ar:
[docs/reescrita-workers.md](docs/reescrita-workers.md).

## Primeiro uso e importação
1. Abra **Configurações** e importe a planilha de contabilidade (clientes, preços, matriz de horários, marketing e parâmetros).
   A planilha nunca é alterada; importar de novo não duplica e preserva o que foi preenchido só no CRM.
2. Confira os parâmetros (DAS, taxas de cartão, margens, CIA, grupos, metas) na mesma tela.
3. Complete nos clientes o que a planilha não tem: telefone, dias/horários, data de início e renovação.

## Repositório público: o que nunca vai para o GitHub

O código é público; os dados não. Nunca versionar: `.env` (chaves do Turso, do Cloudflare e da API da Anthropic), `data/` (banco e backups), qualquer `*.db`. O `.gitignore` já bloqueia e o `pytest` (`tests/test_seguranca.py`) falha se algum aparecer ou se um arquivo tiver cara de chave. Se uma chave vazar mesmo assim: gere outra (Turso, Cloudflare) antes de apagar o commit. Falhas de segurança: ver `SECURITY.md`.

## Backup e restauração
- **Dados › Fazer backup agora**: cria uma cópia imediata (no disco do servidor, que o Render apaga quando reinicia: para guardar, use **Dados › Exportar**).
- **Dados › Restaurar backup**: escolha o arquivo, digite RESTAURAR e confirme. O banco atual é guardado antes como `antes-restaurar-*.db`. Arquivo corrompido é recusado e nada muda.
- **Lixeira**: nada é apagado de verdade. Registros excluídos ficam na lixeira e podem ser restaurados em Dados.

## Telas
Painel (metas e nível) · Clientes (cards, ficha, histórico, alertas de renovação em 7 dias e 14 dias sem aula) ·
Leads (kanban; virar "Cliente" cria o cadastro) · Grade (segunda a sábado, 05h–23h, cores por margem, filtro de vale) ·
"+ Novo local" na Grade, Agenda e Propostas (taxas, deslocamento e taxa mensal do local; cria os preços e a grade copiando um local, mantendo a margem ou o preço) ·
Agenda (1 card por horário com até 2 alunos, escolhidos num seletor com o local; avisa a Grade; Copiar da Grade uma vez; aulas avulsas; marcar Feita, Faltou ou Desmarcou com 1 toque, que vai para o histórico do aluno; controle de reposições por aluno; marcar várias aulas e vários horários de uma vez) ·
Propostas (vários dias, horas e locais na mesma proposta, com preço médio; margem, lucro/hora, preço mínimo, desconto máximo; botão que sobe o preço até a margem mínima ou dá o desconto máximo; PDF com "de R$ X por R$ Y") · Explorador (todas as combinações) ·
Campanhas (fases, checklists, gastos por canal, checkpoints que você inclui e exclui) · Rotina (checklist semanal editável e lista de espera) · Configurações · Dados.

## Assistente (chat com o Claude)
A tela **Assistente** conversa com o Claude: ele lê o financeiro, as contas e as tarefas do CRM e também lança, dá baixa, edita e marca tarefas (pede confirmação antes de excluir ou mudar valor).
- **Ligar**: crie uma chave em console.anthropic.com › API Keys e cole em **Configurações › Assistente** (vale na hora; fica no banco). Também dá para usar a variável `ANTHROPIC_API_KEY` do serviço no Render, que vence a salva em Configurações.
- **Custo**: o modelo padrão é o mais barato (Haiku 5.5), em geral menos de 1 centavo de dólar por pergunta (a tela mostra uma estimativa em US$ por conversa); a API cobra por uso, à parte da assinatura do Claude, e precisa de crédito em console.anthropic.com › Billing.
- **Opcional**: `ASSISTENTE_MODELO`, `ASSISTENTE_ESFORCO` e `ANTHROPIC_BASE_URL` (OmniRoute). Ver `.env.example`.
- As perguntas e os dados que ele lê vão para a API da Anthropic. A conversa fica guardada no banco do CRM.

## Como atualizar o CRM
Cada mudança juntada na `main` do GitHub é publicada pelo Render conforme a configuração do serviço no painel do Render.
Mudança de banco, variável ou portaria é feita no painel de cada serviço (Render, Turso, Cloudflare), nunca no código.

## Testes (para quem programa)
```
python -m pytest -q                       # CRM em Python (app/)
cd worker && npm ci && npm test           # CRM novo (Cloudflare Workers): tipos, paridade com o Python e telas
```
Rodar o Python no computador, só para desenvolver: `python -m uvicorn app.main:app --port 8765` (sem `.env`, usa `data/crm.db` local).

## Agentes e documentação

Comece por [AGENTS.md](AGENTS.md) e pelo guia exclusivo do seu agente. Consulte o [índice](docs/README.md) somente conforme a tarefa.
