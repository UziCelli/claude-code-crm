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

## Backup e restauração
- **Dados › Fazer backup agora**: cria uma cópia imediata.
- **Dados › Restaurar backup**: escolha o arquivo, digite RESTAURAR e confirme. O banco atual é guardado antes como `antes-restaurar-*.db`. Arquivo corrompido é recusado e nada muda.
- **Lixeira**: nada é apagado de verdade. Registros excluídos ficam na lixeira e podem ser restaurados em Dados.

## Telas
Painel (metas e nível) · Clientes (cards, ficha, histórico, alertas de renovação em 7 dias e 14 dias sem aula) ·
Leads (kanban; virar "Cliente" cria o cadastro) · Grade (segunda a sábado, 05h–23h, cores por margem, filtro de vale) ·
Simulador (preço, margem, lucro/hora, preço mínimo, desconto máximo; bloqueio abaixo da margem) · Explorador (todas as combinações) ·
Campanhas (fases, checklists, gastos por canal, checkpoints) · Rotina (checklist semanal e lista de espera) · Configurações · Dados.

## Como atualizar o CRM
Substitua a pasta `app\` pela nova versão e abra o CRM normalmente. O banco e os backups não são tocados.
Se `requirements.txt` mudar, apague a pasta `.venv` e abra o CRM: ele reinstala tudo.

## Testes (para quem programa)
```
.venv\Scripts\python.exe -m pytest tests
```