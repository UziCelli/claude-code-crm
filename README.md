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

## CRM no celular (túnel no PC + reserva no Render)
- **Principal: o próprio PC.** O Cloudflare Tunnel (grátis) leva `https://crm.vfitcoachapp.com` até o CRM deste PC. Abre rápido.
  O PC precisa ficar ligado, na tomada e com a sua conta do Windows aberta (pode bloquear a tela com Windows+L).
- **Reserva: Render grátis**, em `https://crm-reserva.vfitcoachapp.com`. Funciona com o PC desligado, mas é lenta:
  depois de 15 minutos sem uso o servidor dorme e o primeiro acesso leva cerca de 1 minuto.
- **Portaria:** nos dois endereços o Cloudflare Access pede o seu e-mail e manda um código. O CRM confere o token do Cloudflare
  em cada pedido que vem da internet (`app/acesso.py`). Sem `CF_ACCESS_TEAM_DOMAIN` e `CF_ACCESS_AUD`, nada aparece pela internet.
  No próprio PC, `http://localhost:8765` entra direto, como sempre.
- PC, celular e reserva usam o mesmo banco (Turso). O que é lançado num aparelho aparece no outro em até 30 segundos.
- **Encerrar** só aparece no PC e desliga também o acesso pelo celular. Para religar, abra o CRM pelo atalho.

### Configurar (uma vez só)
Os nomes dos botões no Cloudflare e no Render podem mudar um pouco.

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

**4. Render vira a reserva**
1. Render › serviço `claude-code-crm` › **Settings** › **Custom Domains**: remova `crm.vfitcoachapp.com` e adicione `crm-reserva.vfitcoachapp.com`.
2. Cloudflare › DNS › **Add record**: tipo `CNAME`, nome `crm-reserva`, destino `claude-code-crm.onrender.com`, **DNS only** (nuvem cinza).
3. No Render, clique em **Verify**. Depois de verificado, volte ao Cloudflare e mude o registro para **Proxied** (nuvem laranja).
4. As variáveis do Render (Environment) continuam as mesmas. A configuração do serviço está em `render.yaml` (Blueprint).

**5. Preparar o PC**
1. Na pasta do CRM: `git pull`.
2. Abra o `.env` no Bloco de Notas e acrescente as duas linhas (copie os valores de Render › Environment):
   ```
   CF_ACCESS_TEAM_DOMAIN=summer-scene-f0e8.cloudflareaccess.com
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
- Cada mudança juntada na `main` do GitHub vai sozinha para a reserva e para o PC (veja "Como atualizar o CRM").

## Backup e restauração
- **Dados › Fazer backup agora**: cria uma cópia imediata.
- **Dados › Restaurar backup**: escolha o arquivo, digite RESTAURAR e confirme. O banco atual é guardado antes como `antes-restaurar-*.db`. Arquivo corrompido é recusado e nada muda.
- **Lixeira**: nada é apagado de verdade. Registros excluídos ficam na lixeira e podem ser restaurados em Dados.

## Telas
Painel (metas e nível) · Clientes (cards, ficha, histórico, alertas de renovação em 7 dias e 14 dias sem aula) ·
Leads (kanban; virar "Cliente" cria o cadastro) · Grade (segunda a sábado, 05h–23h, cores por margem, filtro de vale) ·
Simulador (preço, margem, lucro/hora, preço mínimo, desconto máximo; bloqueio abaixo da margem) · Explorador (todas as combinações) ·
Campanhas (fases, checklists, gastos por canal, checkpoints que você inclui e exclui) · Rotina (checklist semanal editável e lista de espera) · Configurações · Dados.

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