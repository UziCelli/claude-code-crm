# VFITCOACH CRM

CRM local para o VFITCOACH (personal trainer, São Paulo). Roda no seu computador, sem internet, em `http://localhost:8765`.

## Como iniciar
1. Dê dois cliques no atalho do CRM na Área de Trabalho (ou em `iniciar-crm.bat` nesta pasta).
2. Na primeira vez ele prepara o ambiente (1–2 minutos) e, se nenhum atalho da Área de Trabalho abrir o CRM, cria um.
   O servidor roda sem janela; a janela preta some sozinha quando o navegador abre.
3. Para fechar o CRM, clique em **Encerrar** no menu (canto direito). Abrir de novo com o CRM já rodando só abre o navegador.
   Mensagens do servidor ficam em `data\crm.log` e `data\crm-erro.log`.

Precisa do Python 3 instalado (https://www.python.org/downloads/, marque "Add python.exe to PATH").

## Primeiro uso
1. Abra **Configurações** e clique em **Importar da planilha**. Isso lê `C:\Users\victo\OneDrive\Documentos\Contabilidade.xlsx`
   (clientes, preços, matriz de horários, marketing e parâmetros). A planilha nunca é alterada.
2. Confira os parâmetros (DAS, taxas de cartão, margens, CIA, grupos, metas) na mesma tela.
3. Complete nos clientes o que a planilha não tem: telefone, dias/horários, data de início e renovação.

Pode importar de novo sempre que atualizar a planilha: nada duplica e os campos preenchidos só no CRM são preservados.

## Onde ficam os dados
- Banco: `C:\Users\victo\VFITCOACH-CRM\data\crm.db` (fora do OneDrive, de propósito).
- Backups: `C:\Users\victo\VFITCOACH-CRM\data\backups\` (só neste computador, fora do OneDrive e do git).
  A tela **Dados** mostra a pasta em uso. Os backups antigos em `OneDrive\Documentos\VFITCOACH-CRM-backups\`
  continuam lá; para restaurar um deles, copie o `.db` para `data\backups\`.
- Um backup automático é feito ao abrir o CRM (1 por dia) e antes de cada importação; ficam os 30 mais recentes de cada tipo.
  Se o backup falhar, o CRM abre mesmo assim e registra um aviso em `data\crm.log`.

## Banco na nuvem (Turso, opcional)
Com o Turso ligado, os dados ficam no banco da nuvem (plano grátis) e o CRM trabalha numa réplica local, `data\crm-nuvem.db`.
- **Python:** a biblioteca do Turso ainda não tem versão para o Python 3.14 no Windows. Instale o Python 3.13
  (`winget install -e --id Python.Python.3.13`), feche o CRM, apague a pasta `.venv` e rode `py -3.13 -m venv .venv`
  e `.venv\Scripts\python.exe -m pip install -r requirements.txt`. O Python 3.14 do computador continua instalado.
- **Ligar:** copie `.env.example` como `.env`, preencha `TURSO_DATABASE_URL` e `TURSO_AUTH_TOKEN` e rode uma vez, com o CRM fechado,
  `.venv\Scripts\python.exe -m app.subir_nuvem`. Isso envia o `crm.db` atual, que fica intacto como cópia de segurança.
- **Sem internet:** dá para consultar tudo (réplica local), mas gravar precisa de conexão. O painel avisa quando a conexão cai.
- **Desligar:** apague ou renomeie o `.env`. O CRM volta a usar o `crm.db`, que não recebe o que foi lançado no Turso nesse período.
- O `.env` contém a chave do banco e nunca vai para o GitHub (está no `.gitignore`).

## CRM no celular (túnel no PC + reserva no Google Cloud Run)
- **Principal: o próprio PC.** O Cloudflare Tunnel (grátis) leva `https://crm.vfitcoachapp.com` até o CRM deste PC. Abre rápido.
  O PC precisa ficar ligado, na tomada e com a sua conta do Windows aberta (pode bloquear a tela com Windows+L).
- **Reserva: Google Cloud Run**, em `https://crm-reserva.vfitcoachapp.com`. Funciona com o PC desligado.
  Sem uso, o servidor dorme, mas acorda em poucos segundos (o Render levava cerca de 1 minuto). Cabe na cota grátis do Google.
- **Portaria:** nos dois endereços o Cloudflare Access pede o seu e-mail e manda um código. O CRM confere o token do Cloudflare
  em cada pedido que vem da internet (`app/acesso.py`). Sem `CF_ACCESS_TEAM_DOMAIN` e `CF_ACCESS_AUD`, nada aparece pela internet.
  No próprio PC, `http://localhost:8765` entra direto, como sempre.
- PC, celular e reserva usam o mesmo banco (Turso). O que é lançado num aparelho aparece no outro em até 30 segundos.
- **Encerrar** só aparece no PC e desliga também o acesso pelo celular. Para religar, abra o CRM pelo atalho.
- Se o CRM cair, o vigia religa sozinho em até 2 minutos (o botão Encerrar desliga de verdade; o atalho ou reiniciar o PC liga de novo).

### Configurar (uma vez só)
Os nomes dos botões no Cloudflare e no Google Cloud podem mudar um pouco.

**1. Liberar o nome `crm` (Cloudflare › DNS)**
1. Em dash.cloudflare.com, abra `vfitcoachapp.com` › **DNS** › **Records**.
2. Apague o CNAME `crm` (aponta para `claude-code-crm.onrender.com`). O túnel precisa desse nome.

**2. Criar o túnel (Cloudflare Zero Trust)**
1. **Networks** › **Tunnels** › **Create a tunnel** › **Cloudflared**. Nome: `pc-crm`. Salve.
2. Escolha **Windows** e baixe o instalador do cloudflared (64-bit, `.msi`). Instale no PC.
3. Copie o comando que aparece: `cloudflared.exe service install <token>`.
4. No PC, abra o PowerShell **como Administrador** (botão direito no Iniciar › Terminal (Administrador)). Cole o comando e aperte Enter.
   Abra o PowerShell só depois de instalar (se já estava aberto, feche e abra de novo).
   Se disser que não acha o `cloudflared.exe`, use o caminho completo:
   `& 'C:\Program Files (x86)\cloudflared\cloudflared.exe' service install <token>` (ou `C:\Program Files\cloudflared\`).
5. Volte ao painel: o conector aparece como conectado. Clique em **Next**.
6. Em **Public Hostname**: subdomínio `crm`, domínio `vfitcoachapp.com`, tipo `HTTP`, URL `localhost:8765`. **Save**.

**3. Ajustar a portaria (Zero Trust › Access › Applications › CRM › Configure)**
1. Acrescente o domínio `crm-reserva.vfitcoachapp.com` no mesmo app. Assim o AUD não muda.
2. **Session Duration**: `1 month`. Assim o celular não pede o código todo dia.
3. Salve.

**4. Reserva: Google Cloud Run**
A imagem sai do `Dockerfile` deste repositório. Ele já deixa fixos o fuso, a portaria (`CRM_NUVEM=1`) e o endereço `crm-reserva`.
1. **Conta:** em console.cloud.google.com, crie um projeto (ex.: `vfitcoach-crm`) e ative o faturamento (pede cartão).
   Em **Faturamento › Orçamentos e alertas**, crie um orçamento de **US$ 1** com aviso por e-mail. Assim nenhuma cobrança passa despercebida.
2. **Criar o serviço:** Cloud Run › **Implantar contêiner** › **Implantar continuamente a partir de um repositório (GitHub)**.
   - Conecte o GitHub e escolha `UziCelli/crm-locais`, branch `^main$`, tipo de build **Dockerfile** (caminho `/Dockerfile`).
   - Nome: `vfitcoach-crm`. Região: `us-east1`. É perto do Turso: confira a região do banco no painel do Turso e escolha a mais próxima.
   - **Autenticação:** "Permitir acesso público" (quem barra é o Cloudflare Access e o próprio CRM).
   - **Faturamento:** "Com base em solicitações". **Escalonamento:** mínimo `0`, máximo **`1`** instância.
   - **Contêiner › Recursos:** memória `512 MiB`, CPU `1`, e marque **Aumento de CPU na inicialização**.
   - **Variáveis e secrets:** `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `CF_ACCESS_TEAM_DOMAIN` e `CF_ACCESS_AUD`. São os mesmos valores do `.env` do PC.
   - **Criar.** No topo do serviço aparece a URL (`https://vfitcoach-crm-....run.app`). Abrir essa URL direto tem que mostrar "Acesso restrito": está certo.
3. **Limpar imagens velhas:** Artifact Registry › repositório `cloud-run-source-deploy` › **Editar** › **Políticas de limpeza**:
   "Manter as versões mais recentes", contagem `2`. Sem isso, as imagens se acumulam e passam da cota grátis de armazenamento.
4. **Endereço `crm-reserva` (Cloudflare › Workers e Pages)**
   - **Criar** › **Worker** › nome `crm-reserva` › **Implantar**. Depois, **Editar código**: cole o conteúdo de `cloudflare/worker-reserva.js`,
     troque `COLE-AQUI-A-URL.run.app` pela URL do passo 2 e clique em **Implantar**.
   - Worker › **Configurações › Domínios e rotas › Adicionar › Domínio personalizado**: `crm-reserva.vfitcoachapp.com`. O Cloudflare cria o DNS sozinho.
     Se reclamar que o nome já existe, apague antes o registro `crm-reserva` antigo em DNS › Records.
   - O app do Access (passo 3) já cobre `crm-reserva.vfitcoachapp.com`. Abra o endereço no celular: ele pede o código e mostra o CRM.
5. Depois que funcionar, apague o serviço antigo no Render (dashboard.render.com › serviço › Settings › Delete).

**5. Preparar o PC**
1. Na pasta do CRM: `git pull`.
2. Abra o `.env` no Bloco de Notas e acrescente as duas linhas (os mesmos das variáveis do Cloud Run):
   ```
   CF_ACCESS_TEAM_DOMAIN=SEU-TIME.cloudflareaccess.com
   CF_ACCESS_AUD=cole-aqui-o-AUD
   ```
   O AUD é o "Application Audience (AUD) Tag" do app CRM no Zero Trust.
3. No PowerShell (normal), na pasta do CRM, rode uma vez:
   ```
   powershell -ExecutionPolicy Bypass -File .\configurar-pc-servidor.ps1
   ```
   Ele faz o CRM ligar sozinho ao entrar no Windows (sem abrir o navegador), tira a suspensão na tomada,
   confere o `.env` e o túnel e reinicia o CRM. Em notebook, ele mostra como deixar "Ao fechar a tampa: Não fazer nada" na tomada.
   Para desfazer: o mesmo comando com `-Desfazer` no fim.

**6. iPhone**
1. Abra `crm.vfitcoachapp.com` no Safari e entre com o código do e-mail.
2. Toque em **Compartilhar** › **Adicionar à Tela de Início**. Vira um ícone de app.

### Se o celular não abrir
- **Erro 1033 ou erro de "tunnel"**: o PC está desligado ou o cloudflared parou. Use `https://crm-reserva.vfitcoachapp.com`.
  No PC, confira no PowerShell: `Get-Service cloudflared` (deve dizer `Running`). Se não, no PowerShell como Administrador: `Start-Service cloudflared`.
- **Erro 502 (Bad gateway)**: o PC está ligado, mas o CRM não. Abra o CRM pelo atalho.
  Acontece se o Windows reiniciou e ninguém entrou na conta, ou se alguém clicou em Encerrar.
- **"A portaria do Cloudflare Access ainda não foi configurada"**: faltam as linhas `CF_ACCESS_*` no `.env`.
  Preencha e rode `configurar-pc-servidor.ps1` de novo.
- **Reserva com "Acesso restrito"** depois de entrar com o código: confira as variáveis `CF_ACCESS_*` no Cloud Run (serviço › **Editar e implantar nova revisão**).
- **Reserva com erro 1101 ou 5xx do Worker**: a URL do Cloud Run no Worker está errada. Confira o `CLOUD_RUN` no código do Worker.
- **Reserva demorando sempre**: Cloud Run › serviço › **Registros**. Confira se o banco sincroniza (procure "AVISO") e a região perto do Turso.
- Cada mudança juntada na `main` do GitHub vai sozinha para a reserva (Cloud Run) e para o PC (veja "Como atualizar o CRM").

## Repositório público: o que nunca vai para o GitHub

O código é público; os dados não. Nunca versionar: `.env` (chaves do Turso, do Cloudflare e da API da Anthropic), `data/` (banco e backups), qualquer `*.db`. O `.gitignore` já bloqueia e o `pytest` (`tests/test_seguranca.py`) falha se algum aparecer ou se um arquivo tiver cara de chave. Se uma chave vazar mesmo assim: gere outra (Turso, Cloudflare) antes de apagar o commit. Falhas de segurança: ver `SECURITY.md`.

## Backup e restauração
- **Dados › Fazer backup agora**: cria uma cópia imediata.
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
- **Ligar**: crie uma chave em console.anthropic.com › API Keys e cole em **Configurações › Assistente** (o jeito fácil: vale na hora e vai junto para a reserva pelo Turso). Também dá para acrescentar ao `.env` do PC a linha `ANTHROPIC_API_KEY=` seguida da chave e reiniciar o CRM (ou usar as variáveis do Cloud Run); a chave do `.env` vence a salva em Configurações.
- **Custo**: o modelo padrão é o mais barato (Haiku 5.5), em geral menos de 1 centavo de dólar por pergunta (a tela mostra uma estimativa em US$ por conversa); a API cobra por uso, à parte da assinatura do Claude, e precisa de crédito em console.anthropic.com › Billing.
- **Opcional**: `ASSISTENTE_MODELO`, `ASSISTENTE_ESFORCO` e `ANTHROPIC_BASE_URL` (OmniRoute). Ver `.env.example`.
- As perguntas e os dados que ele lê vão para a API da Anthropic. A conversa fica guardada no banco do CRM.

## Como atualizar o CRM
**Sozinho.** O CRM do PC confere o GitHub a cada 15 minutos. Se tiver versão nova, espera ficar 5 minutos sem ninguém usando,
baixa e reinicia (cerca de 10 segundos fora do ar). Bibliotecas novas são instaladas na hora. O banco e os backups não são tocados.
- A tela **Dados** mostra a versão e se deu algum problema. Histórico em `data\atualizacao.log`.
- Se a versão nova não abrir, o CRM volta sozinho para a anterior e espera a próxima.
- Precisa: Windows, o `git` instalado e a pasta baixada com `git clone` (ramo `main`).
- Desligar: acrescente `CRM_AUTOATUALIZAR=0` no `.env` e reinicie o CRM. Aí, para atualizar: `git pull` e `configurar-pc-servidor.ps1`.

## Testes (para quem programa)
```
.venv\Scripts\python.exe -m pytest tests
```