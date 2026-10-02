# Mapa do código — Rodada 1 (gerado no planejamento, out/2026)

# Mapa da Rodada 1: CRM VFITCOACH (leitura apenas, nada alterado)

Caminhos relativos a `C:\Users\victo\VFITCOACH-CRM`, salvo o site em `C:\Users\victo\VFITCOACH-Site`.

**Estado real do banco** (lido em `mode=ro`):
- 15 clientes: 10 ativos e 5 inativos.
- Nenhum cliente tem telefone, data de início ou data de renovação preenchidos.
- Estão vazios: leads, lead_etapas_log, cliente_eventos, metricas_mensais e propostas. Existem 4 registros em gastos_marketing.
- O journal_mode é `delete` (não é WAL).

## 1) Logo
- **CRM:** a marca hoje é só texto em `base.html:14` (`VFIT<span>COACH</span>`). O estilo está em `style.css:8` (fonte), `:21` (`.menu .marca`) e `:22` (span em `#8fb6e6`). A barra do menu tem 52px (`style.css:17`).
- **Favicon do CRM:** `base.html:7` aponta para `/static/favicon.png`, um PNG de 128x128 com 18 KB. Existe também `vfitcoach_crm.ico` na raiz (6 tamanhos), que nenhum arquivo referencia. O atalho criado em `iniciar-crm.bat:14` não define ícone.
- **SVG do logo no site:** em `src/prototipo.html` o `<svg>` vai da linha 215 à 250 (o path de 217 a 248). Em `public/index.html` vai da linha 257 à 292 (path de 259 a 290). O conteúdo é idêntico (mesmo hash md5): `viewBox="191 399 570 140"` e `fill="#FFFFFF"`. O site usa altura de 24px (`index.html:102`).
- **Extras do site:**
  - `index.html:293` traz o ícone `logo-icon`: um círculo "VFC" com `viewBox 0 0 200 200` e path único. Serve como favicon.
  - `public/favicon.svg` é um "V" branco sobre fundo `#0B1E3D`, 64x64.
  - O `index.html:10-12` declara svg, png-32 e apple-touch.
- **Reaproveitar:** colar o SVG de `index.html:257-292` no lugar de `base.html:14`, com `aria-label`. Copiar `favicon.svg` para `app/static/` e usar `type="image/svg+xml"`.

## 2) Paleta
**Tokens do CRM** (`style.css:2-4`):

| Token | Cor |
|---|---|
| `--marinho` | #0B1E3D |
| `--aco` | #2C5C8F |
| `--branco` | #fff |
| `--fundo` | #f3f5f9 |
| `--borda` | #d9dfe8 |
| `--texto` | #16213a |
| `--cinza` | #6b7590 |
| `--verde` / `--verde-f` | #1f9d55 / #e3f6ea |
| `--amarelo` / `--amarelo-f` | #d99a06 / #fff5d6 |
| `--vermelho` / `--vermelho-f` | #d0342c / #fde5e3 |
| `--roxo` / `--roxo-f` | #6b2ecf / #ece3fb |

**Cores fixas no `style.css`, fora do `:root`:**
- Texto do menu: `:18` #cdd8ea. Hover: `:19` rgba(255,255,255,.08). Branco em `:19`, `:20`, `:21`. Span da marca: `:22` #8fb6e6.
- Verde escuro #14663a em `:27`, `:50`, `:74`. Borda verde clara #b6e6c7 em `:27`.
- Vermelho escuro #8f1d17 em `:28`, `:52`, `:80`. Borda vermelha clara #f3b6b1 em `:28`.
- Amarelo: #f1d98a em `:29`, texto #7a5300 em `:30` e `:51`.
- Branco #fff também em `:32`, `:61`, `:73`, `:77`, `:85`, `:93`, `:109`, `:126`, `:134`.
- Azul claro #e3ecf8 em `:53` e `:79`.
- Cinza claro #e9edf3 em `:54`, `:68`, `:72`, `:105`.
- Hover de botão #24507d em `:78`. Cabeçalho de tabela #eef2f8 em `:95`.
- Prejuízo: #7a1a14 em `:100` e #f5c9c5 em `:125`.
- Fundos do kanban: perdido #f3e6e5 em `:107`, cliente #e2f3e8 em `:108`.
- Indisponível #dfe3ea em `:127`.
- Sombra e backdrop: rgba em `:142` e `:143`.

**Cores fixas nos templates (style inline):**
- `simulador.html:36`: `color:#8f1d17`
- `painel.html:19`: `border-color:#f1d98a`
- `grade.html:14`: `#f5c9c5`
- `grade.html:15`: `#dfe3ea`

As demais declarações inline já usam `var()`: `grade.html:13-15`, `cliente.html:68`, `dados.html:8`. Os arquivos `app.js` e `*.py` não têm cor.

**Paleta do site** (`public/index.html:37-62`):

| Token | Claro | Escuro (`:53-54`, `:59-60`) |
|---|---|---|
| `--navy` | #0B1E3D | — |
| `--navy-2` | #0F2A52 | — |
| `--steel` | #2C5C8F | — |
| `--steel-light` | #4A7BAF | #5C93CC |
| `--cta` (azul do botão) | #3F72A6 | — |
| `--accent-text` | #2C5C8F | #7FAEDD |
| `--ink` | #0A0A0A | #EDF1F8 |
| `--bg` | #F5F7FA | #0A1424 |
| `--card` | #FFFFFF | #101B30 |
| `--muted` | #54607A | #98A6C2 |
| `--border` | #E1E6EE | #1E2C46 |

- Botão (`:115-126`): `.btn-accent` usa `--cta` e muda para `--steel` no hover. Raio de 6px.
- Tons de texto sobre o azul-marinho:
  - #CBD8ED: `:146`, `:152`
  - #D7E2F2: `:162`, `:247`
  - #B9C9E4: `:142`, `:245`
  - #9CB0D1: `:197`, `:201`
  - #8FB3DE: `:183`, `:198`, `:206`
  - #C3D3EA: `:191`
  - #E4EDF9: `:154`, `:240`
- O rodapé usa `--navy-2` (`:245`).
- Fontes: o site hospeda Montserrat e Inter em `public/assets/fonts/*.woff2` (`:34-35`). O CRM carrega as fontes do Google (`base.html:8-9`), o que contradiz "roda sem internet" no `README.md:3`.

**Equivalências:** `--marinho` e `--aco` já são iguais a navy e steel. Diferem `--fundo`, `--borda`, `--texto` e `--cinza`. O site não tem cores de status: verde, amarelo e vermelho continuam sendo do CRM.

## 3) Painel
- **Rota:** `painel()` em `main.py:210-217`. Usa `calcular_metricas` (`:141-174`) e `db.parametros(con,"metas")`. O histórico vem de `SELECT metricas_mensais`, com o mês atual calculado na hora e acrescentado (`:215`), limitado a 12 meses. Também chama `metricas_por_canal` (`:177-207`) e `fase_atual` (`:598-600`).
- **O que `calcular_metricas` calcula:**
  - Clientes ativos, horas (`aulas_mes`, `:95-106`), receita, receita de grupos e lucro (`base_do_cliente` em `:109-118` com `precos.carregar_parametros`).
  - Perdidos: eventos de status com "inativo" no mês.
  - Propostas aceitas com margem abaixo de 10%.
  - Lista de espera em horário de pico.
  - Nível de 1 a 4 conforme as metas (`:165-171`).
- **Fechar mês:** `main.py:220-234` faz upsert em `metricas_mensais` e marca o item `fim_mes` da rotina. Ele sempre calcula o mês corrente: quem fechar no dia 1 grava o mês novo, não o anterior.
- **Mês anterior calculado na hora: não é confiável.** O parâmetro `mes` só filtra perdidos e vendas abaixo de 10% (`:159-162`). Clientes, horas, receita e lucro vêm do estado atual de `clientes`, sem histórico. Em `metricas_por_canal`, os leads e o funil não são filtrados por mês (`:182-189`); só gastos e clientes por canal são.
  - Saída mínima: fechar o mês anterior automaticamente (no startup ou no painel) quando ele não existir em `metricas_mensais`. É uma foto aproximada do primeiro acesso no mês novo.
- **Alertas de hoje:** `alertas()` em `main.py:122-135`.
  - Renovação: data de renovação até hoje+7 dias, sem limite inferior, então as vencidas entram.
  - Sem aula: nenhuma aula registrada há 14 dias, excluindo só Consultoria Online.
  - Ações: leads com `data_proxima_acao` até hoje.
  - `_alertas.html:1-11` mostra as três listas (amarelo, vermelho, azul).
  - `render()` chama `alertas()` em todas as telas (`:79`).
  - No painel, o card "Atenção hoje" fica em `painel.html:18-20`. O `base.html:32` esconde o alerta do topo na rota `/`.
- **O que falta para uma lista "O que precisa de você hoje" priorizada:**
  - Separar vencido, hoje e próximos 7 dias.
  - Incluir leads parados (item 4).
  - Incluir o item da rotina do dia (`ROTINA`, `main.py:21-22`, por dia da semana).
  - Incluir checkpoints de campanha pendentes com prazo próximo (`campanha_checkpoints`).
  - Incluir propostas com status `enviada` (só existe `data` de criação, não há data de envio).
  - Incluir "cadastro incompleto", porque hoje os 15 clientes estão sem renovação, então o alerta de renovação nunca dispara.
  - Ordenar por gravidade numa única lista de dicts dentro de `alertas()`.

## 4) Lead esfriando
- **Schema:** tabela `leads` em `schema.sql:49-66`. `data_entrada` (`:61`) e `data_mudanca_etapa` (`:62`) são DATE com default hoje. `lead_etapas_log` (`:68-73`) guarda `data` como datetime.
- **Onde a etapa muda:** só em `POST /leads/{lid}/etapa` (`main.py:392-409`). O `:398` grava a data de mudança e o `:400` grava o log. O "Reabrir" volta para `lead` pela mesma rota (`leads.html:29`). A criação loga `lead` em `main.py:377`. A edição (`:381-389`) não mexe na etapa.
- **Selo "parado há X dias":**
  - Calcular em `leads()` (`main.py:359-367`), junto com `atrasado` (`:365`). Atenção: ali `hoje` é string ISO (`:363`).
  - Exibir no card em `leads.html`, perto da linha 16, com `.tag amarelo`. O CSS `.lead.atrasado` está em `style.css:110`.
- **Limites por etapa:** usar a tabela `parametros` (`schema.sql:5-13`, com UNIQUE em grupo+chave). Semear um grupo, por exemplo `lead_parado_dias`, com chaves lead, conversa e avaliacao, em `PARAMETROS_INICIAIS` (`db.py:16-58`). O INSERT OR IGNORE em `db.py:95-98` semeia também bancos que já existem.
  - Para editar sem UI nova, basta acrescentar o grupo em `GRUPOS_CONFIG` (`main.py:724-728`) com fmt `num`.

## 5) Mensagens de WhatsApp
- **Telefone:** campo TEXT livre, sem normalização, em `clientes` (`schema.sql:18`), `leads` (`:51`) e `lista_espera` (`:203`). Hoje há 0 de 15 clientes com telefone e 0 leads. O `README.md:16` diz que a planilha não tem telefone.
- **Link existente:** `leads.html:15` monta `wa.me/55…` com uma cadeia de `replace` (espaço, hífen, parênteses). Não trata `+55`, `55` já presente nem ponto.
  - Melhor criar um filtro Jinja (`re.sub(r'\D','',…)` e prefixo 55 quando tiver 10 ou 11 dígitos) registrado em `main.py:64-65`.
  - O filtro `urlencode` já vem no Jinja.
  - O site usa o padrão `wa.me/…?text=` (`index.html:295`).
- **Onde pôr os botões:**
  - Cabeçalho da ficha do cliente: `cliente.html:6-12` (hoje não há link de WhatsApp na ficha; o telefone está em `:21`).
  - Card do lead: `leads.html:15`.
  - Itens de alerta: `_alertas.html:3`, `:6`, `:9`. Para isso, os SELECTs de `alertas()` (`main.py:125`, `:127`, `:132`) precisam incluir `telefone`.
- **Modelos de mensagem em `parametros`:** dá para guardar em `valor_texto`, com `valor` NULL; `db.parametros` devolve `valor_texto` nesse caso (`db.py:117-122`).
  - Ressalva: a tela de Configurações só edita números. `configuracoes.html:28` faz `it.valor*100` ou `round`, que quebra com None. `configuracoes_salvar` (`main.py:746-756`) usa `_num_br`, que gera ValueError com texto.
  - Precisa de um card com textarea e de um ramo `t_{id}` que faça UPDATE em `valor_texto`. O grupo não pode entrar em `GRUPOS_CONFIG`.

## 6) Backup
- **Pastas:** `BACKUP_DIR` aponta para OneDrive\Documentos e a reserva é `BACKUP_DIR_RESERVA` (`db.py:10-11`).
  - `pasta_backup()` (`db.py:130-140`) tenta `mkdir` nas duas a cada chamada e altera a variável global.
  - Se as duas falharem, dispara `raise OSError` (`:140`).
  - Nesta máquina a pasta de Documentos não existe e tudo vai para a reserva.
- **Backup:** `fazer_backup` (`db.py:143-155`) usa a API de backup do SQLite.
  - A limpeza mantém 30 cópias, mas só filtra o padrão `crm-*.db` (`:153`). Os arquivos `antes-importar-*` e `antes-restaurar-*` nunca são apagados.
  - `backup_diario` (`:158-163`) faz um por dia. `listar_backups` (`:166-171`) lista todos os `*.db`.
- **Caminho de falha que impede o CRM de abrir:** o lifespan em `main.py:27-31` chama `db.backup_diario()` sem try/except.
  - Qualquer erro aborta o startup do uvicorn: OSError em `db.py:140`, ou erro no `.backup()` ou no `unlink` (OneDrive bloqueando).
  - O mesmo erro gera HTTP 500 em `/dados` (`main.py:818`, via `listar_backups`) e em `/backup` (`:821-824`).
  - `/importar` já captura a exceção (`:796`).
- **Restauração:** `restaurar_backup` (`db.py:174-181`) chama `fazer_backup("antes-restaurar")` e depois `shutil.copy2` por cima do `DB_PATH`.
  - Não roda `integrity_check` no arquivo escolhido.
  - Deixa restaurar qualquer `.db` da pasta.
  - A rota exige digitar "RESTAURAR" (`main.py:827-835`).

## 7) Análise semanal por agente externo
- **Conexão:** `db.conectar(caminho)` em `db.py:81-85`: `check_same_thread=False`, `Row`, `PRAGMA foreign_keys=ON`. Não há WAL nem busy_timeout explícito; vale o timeout padrão de 5s do `sqlite3`.
  - `iniciar_banco()` (`db.py:88-113`) é idempotente.
- **O que um processo externo precisa:** um script rodado com `.venv\Scripts\python.exe` a partir da raiz do projeto.
  - Ler: `from app import db, main` e chamar `main.calcular_metricas(con)`, `main.metricas_por_canal(con, mes)` e `main.alertas(con)`.
  - Importar `app.main` cria o app e monta `/static`, mas não roda o lifespan nem toca no banco.
  - Gravar: uma tabela nova, `analises` (id, criado_em, periodo, texto), via `CREATE TABLE IF NOT EXISTS` no `schema.sql`. Antes, o script chama `db.iniciar_banco()` e depois faz um único `with con: INSERT`.
  - Não precisa de rota HTTP: o servidor normalmente está desligado.
- **Exibição:** acrescentar uma query em `painel()` (`main.py:216`) e um card em `painel.html` depois da linha 20, com `white-space:pre-wrap`. O autoescape do Jinja já vem ligado.
- **Privacidade:** `alertas()` devolve nomes. Para o agente, mandar só contagens.

## Helpers a reutilizar
- **Filtros Jinja:** `moeda`, `data`, `pct`, `num`, `dia`, `dia_curto` e `cor` em `main.py:40-65`. `cor` vem de `precos.cor_margem` (`precos.py:71`).
- **Globais do Jinja:** `ETAPAS`, `DIAS` e `hoje()` em `main.py:66`.
- **Funções de `main.py`:**
  - `get_db`: `:69-74`
  - `render`, que injeta listas, alertas, msg e erro: `:77-80`
  - `voltar` (redirect com msg ou erro): `:83-88`
  - `mes_atual`: `:91`
  - `semana_atual`: `:677`
  - `_num_br`: `:244`
- **Parâmetros:** `db.parametros` e `db.lista` em `db.py:117-126`; `precos.carregar_parametros` em `precos.py:4-17`. Para novos parâmetros, usar a semente de `PARAMETROS_INICIAIS`.
- **Exclusão lógica:** coluna `excluido_em` mais o registro `LIXEIRA` (`main.py:805-807`). Uma tabela nova acrescentada ali ganha lixeira e restauração prontas (`:838-844`).
- **Datas de registro:** `criado_em` e `atualizado_em` têm default no schema. `atualizado_em` é setado à mão nos UPDATEs (`main.py:322`, `:332`, `:386`).
- **JS (`app.js`):** `data-abrir` (copia `data-*` para o dialog, `:2-16`), `data-fechar` (`:17-19`) e `data-confirmar` (`:21-24`).
- **CSS:** `.tag` com variantes de cor, `.kpi`, `.card`, `.lista-alertas li.<cor>`, `.borda-*`, variantes de `.btn` e `.grafico`.
- **Migração de schema:** só existe `CREATE TABLE IF NOT EXISTS` no `schema.sql`, executado a cada startup (`db.py:94`). Não há ALTER: colunas novas em tabelas existentes não chegam aos bancos já criados.
  - A Rodada 1 não precisa de coluna nova (usa `data_mudanca_etapa`, `parametros` e uma tabela nova).
  - Se precisar no futuro: checar `PRAGMA table_info` e rodar `ALTER TABLE ADD COLUMN` dentro de `iniciar_banco`.
- **Testes:** `tests/test_precos.py` (funções puras) e `tests/test_importar.py` (pulado se a planilha não existir).
  - Rodar com `.venv\Scripts\python.exe -m pytest tests` (`README.md:44`).
  - O padrão de banco temporário é `tmp_path` + `db.iniciar_banco(banco)` + `db.conectar(banco)` (`test_importar.py:11-13`).
  - O httpx não está instalado, então não há TestClient: testar `alertas()` e as outras funções diretamente.
  - Testar backup exige monkeypatch de `db.DB_PATH` e `db.BACKUP_DIR`.

## Riscos
1. **Alertas em massa a partir de 02/10:** sem `data_inicio` e sem eventos, cai no `COALESCE` para `criado_em` (17/09). Então 9 clientes ativos passam a gerar "sem aula", incluindo 4 de Consultoria Híbrida, que tem 1 sessão por mês e não cabe na regra de 14 dias.
2. **Renovação e WhatsApp sem efeito prático:** os 15 clientes estão sem data de renovação e sem telefone. As duas funções dependem de cadastro preenchido.
3. **Falha de backup bloqueia o startup** (`main.py:30`). Os arquivos `antes-*` crescem sem limite.
4. **Ativar WAL quebraria a restauração:** `copy2` por cima do banco deixaria `-wal`/`-shm` obsoletos. Recomendo não ativar WAL.
5. **Fechar mês grava o mês corrente**, não o anterior. Sem fechar mês, o gráfico fica vazio (está vazio hoje).
6. **Fontes do Google** quebram o uso offline e chamam um servidor de terceiros.
7. **Remover item de lista é DELETE físico** (`main.py:770`), a única exceção à lixeira.
8. **Edição em paralelo:** o projeto não é git, então não dá para usar worktrees nem fazer merge. Arquivos compartilhados por vários itens:

| Arquivo | Itens que mexem nele |
|---|---|
| `main.py` | 3, 4, 5, 6, 7 |
| `style.css` | 1, 2, 4, 5 |
| `db.py` | 4, 6, 7 |
| `painel.html` | 3, 7 |
| `_alertas.html` | 3, 5 |
| `leads.html` | 4, 5 |
| `base.html` | 1 |
| `schema.sql` | 7 |

   Sugestão:
   - Fazer `git init` com um commit de base antes da Rodada 1.
   - Dividir os agentes por arquivo: (a) logo e paleta (`base.html`, `style.css`, templates com cor fixa); (b) backup (só `db.py`, mais o lifespan); (c) lead esfriando, WhatsApp e lista priorizada em série, porque mexem nos mesmos trechos de `main.py`, `leads.html` e `_alertas.html`; (d) análise externa por último (`schema.sql`, script novo, card no painel).