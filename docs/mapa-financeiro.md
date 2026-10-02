# Mapa da planilha — Rodada 2, financeiro PF+PJ (gerado no planejamento, out/2026)

**Rodada 2: base para o financeiro PF + PJ no CRM (somente leitura)**

**0. Acesso**
- A planilha `C:\Users\victo\OneDrive\Documentos\Contabilidade.xlsx` abriu sem bloqueio. Nada foi salvo e nenhuma cópia foi criada.
- Carreguei com `data_only=True/False`, mas sem `read_only=True`, porque `ws.tables` não existe nesse modo. O importador atual faz o mesmo (`app/importar.py:271`).
- O banco `data/crm.db` foi lido com `mode=ro`.

---

## 1. Estrutura por aba

**Transações Empresariais** — `tblTransaçõesEmpresariais` B16:M210. A linha 210 é de totais (`SUBTOTAL`).
- **Volume:** 119 lançamentos (linhas 17–135), de 01/04 a 30/09/2026. Abr 19, mai 12, jun 10, jul 46, ago 12, set 20. Não estão em ordem de data.
- **Colunas:**
  - Data: datetime, sem hora.
  - Tipo: Entrada 35, Saída 84.
  - Cliente/Fornecedor: texto, 36 distintos.
  - Categoria.
  - Valor (R$): sempre positivo, 2 casas. O sentido vem só do Tipo.
  - Forma Pagamento e Status.
  - Descrição: 37 vazias.
  - Mês = `TEXT(Data,"mmmm")` e Ano = `YEAR(Data)`.
  - Emissão NFS-e.
  - Aulas: inteiro, só 4 linhas.
- **Categorias de entrada:** Pacotes de Aulas 18, Mensalidade (Aulas Presenciais) 8, Consultoria Online 5, Consultoria Híbrida 2, Outros 2.
- **Categorias de saída:** Alimentação 24, Impostos/Taxas 15, Outros 13, Software/Assinaturas 12, Aluguel 12, Transporte 8.
- **Forma:** PIX 100, Transferência 16, Cartão Crédito 3 (só em saídas).
- **Status:** Pago 117, Pendente 2. **NFS-e:** Emitida 15, Não Emitida 1, vazio 103.
- **Conta:** não há coluna. A linha do tempo assume Contabilizei Bank.
- **Ligação com alunos:** as entradas têm 11 contrapartes distintas. 9 batem com os 15 clientes do `crm.db`, ignorando acento e maiúsculas.

**Transações Pessoais** — `Tabela15` B7:N410. A linha 410 é de totais, com Data = texto "Total".
- **Volume:** 224 linhas (8–231), de 16/12/2025 a 21/08/2027.
- **Status:** Pago 192, todos com data até hoje. Pendente 32, todos no futuro (out/2026 a ago/2027). Ou seja, "Pendente" aqui significa agendado.
- **Colunas:**
  - Mês (fórmula), Data, Tipo (Saída 198, Entrada 26), Categoria, Descrição.
  - Valor (R$): positivo. 8 valores têm mais de 2 casas, por causa de fórmulas `=G191*1.00169` (a partir de G197).
  - Forma Pagto, Status, Forma, Parcela, Observação (7 preenchidas).
  - ID Obrigação: vazia.
  - Conciliação custo: fórmula matricial, 166 resultados "Sem correspondência".
- **Categorias:** Alimentação 74, Pessoal 53, Outros 35, Moradia 20, Transporte 20, Outro 12, Salário 5, Lazer 3, Educação 1, Vestuário 1. As entradas usam Outro 12, Outros 8, Salário 5 e Pessoal 1.
- **Forma Pagto:** PIX 188, Débito Auto 12, Boleto 11, Transferência 10, Débito 3. **Nenhum cartão.**
- **Forma:** Eventual 122, Parcelado 36, Variável 31, Mensal 12, Fixo 4, vazio 19.
- **Parcela:** o padrão "n de 12" aparece em 19 linhas, de 2 compras (uma com as 12 parcelas, outra com só as parcelas 6 a 12). Outras 17 linhas marcadas "Parcelado" não têm Parcela.
- **Conta:** não há coluna.

**Cartões** — `tblCartoes` B10:L135 e `tblResumoFaturas` E5:J7.
- **Volume:** 15 linhas reais (11–25), de 06/04 a 30/08/2026. 2 cartões: Itaú 8, Inter 7.
- **Valores:** Categoria é sempre "Fatura". Forma PIX 10, Boleto 3, Débito Auto 2. Status todos Pago. Tipo Variável 8, Parcelado 2, Eventual 2, Mensal 1, vazio 2. Parcela e Observação vazias.
- **O que realmente se registra:** só o total da fatura paga, nunca as compras.
- **Fechamento e vencimento:** não existem em nenhuma aba.
- **Resumo** (`'Cartões'!G6:J7`): por cartão, no mês vigente, Pendente e Atrasado vêm de `SUMIFS` por Status. A Data de referência vem de `MINIFS` sobre as linhas não pagas.
- **Sem duplicidade com a aba pessoal:** nenhuma coincidência de valor com até 3 dias de diferença, e a aba pessoal não tem forma "Cartão". O Painel soma as duas abas (`'Painel Central'!D12`).

**Custos Empresariais** — `tblCustosEmpresaFixos` B37:N47 (10 linhas) e `tblCustosEmpresaVariaveis` P37:AB48 (11 linhas).
- Só 3 + 3 linhas estão preenchidas.
- As tabelas copiam os blocos de entrada B5:F15 e H5:N15 com `=IF(B5="","",B5)`.

**Custos Pessoais** — `tblCustosPessoaisFixos` B7:N26 (19 linhas) e `tblCustosPessoaisVariaveis` P7:AB27 (20 linhas).
- Só 3 + 3 linhas estão preenchidas, digitadas direto na tabela.

**Colunas comuns às 4 tabelas de custos:**
- Descrição, Categoria, Valor, Dia Venc. (inteiro).
- Vencimento = `DATE(ano vigente, mês vigente, Dia Venc.)`.
- Baixa manual?: todas "Não".
- Competência baixa e Data pagamento.
- Status consolidado: Pago manual, Conciliado ou Pendente.
- Conta.
- Observação: Recorrente, Variável, Parcelado ou Eventual.
- ID: CEF-, CEV-, CPF- ou CPV- seguido de número.
- Conciliação: fórmula matricial, Automática ou Não conciliado.

**Valores nos custos:**
- **Categorias:** na empresa, Software/Assinaturas, Aluguel e Impostos/Taxas. No pessoal, Moradia, Pessoal e Dívidas.
- **Contas:** na empresa, sempre Contabilizei Bank. No pessoal, Inter ou Mercado Pago, mas só 6 das 39 linhas têm conta.

**Como o status dos custos é decidido:**
1. "Pago manual" se Baixa manual = Sim e a competência cai no mês.
2. Senão, "Conciliado" se existir uma Saída Paga com:
   - o mesmo valor (diferença até 0,01);
   - data a até 5 dias do vencimento (parâmetros `'Custos Empresariais'!C69` e `'Custos Pessoais'!C42`);
   - a mesma descrição. Na empresa também vale o Cliente/Fornecedor contido na descrição.
3. Senão, "Pendente". Hoje as 12 linhas estão Pendente.

**Painel Central**
- **Mês e ano:** `MesVigente` (C8) é o mês manual (C7) ou `PROPER(TEXT(TODAY(),"mmmm"))`. O ano (C9) é digitado.
- **`tblSaldosContas`** (U17:X22): 5 contas vindas de Backend_Fin, com a frente (PF/PJ) buscada por `XLOOKUP`. Saldo Atual e Atualizado em são digitados. Só 2 estão preenchidas (27/09/2026). **O saldo é uma foto manual, não um cálculo.**
- **`tblEntradasPontuais`** (U10:Y13): 3 linhas, competência set/2026.
  - Colunas: Competência, Fonte, Descrição, Valor e Incluir? (todas Sim).
  - Fontes: renda CLT/rescisão, outras rendas e ajustes manuais.
- **`tblObjetivos`** (B43:S54): 4 objetivos preenchidos, todos Planejado. As fórmulas estão no item 2.

**Backend_Fin (listas)**
- **Categorias de receita** (6) e **de despesa** (10): Aluguel, Internet/Telefone, Material de Trabalho, Transporte, Marketing/Divulgação, Impostos/Taxas, Alimentação, Software/Assinaturas, Manutenção, Outros.
- **Formas de pagamento:** PIX, Dinheiro, Cartão Crédito, Cartão Débito, Transferência, Boleto.
- **Status:** Pago, Pendente, Atrasado. "Atrasado" nunca é usado.
- **Tipo de custo:** Fixo, Variável.
- **Contas:** Contabilizei Bank (PJ); Inter, Itaú, Caixa e Mercado Pago (PF).
- **`tblRegrasPrioridade`** (6 critérios) e **`tblRegrasAgenda`** (10 regras): nenhuma fórmula usa.
- A aba pessoal usa categorias e formas que não estão nessas listas (Débito Auto, Débito, Pessoal, Moradia…).

**Clientes, bloco fiscal (C16:C21)**
- Salário mínimo: digitado em C16.
- Pró-labore = MAX(C10 × 0,28; C16).
- INSS = pró-labore × 0,11.
- DAS = C10 × 0,06, com o número escrito na fórmula.
- Alíquota efetiva = (INSS + DAS) ÷ C10.
- C10 = `SUMIF(Tabela16[Mês] = mês vigente, Total Recebido)`, ou seja, as entradas PJ pagas no mês, cruzadas pelo **nome** do aluno.

**Dashboard**
- D7 receita = entradas PJ pagas + pendentes do mês.
- D8 e D9 = totais dos blocos de custos (`SUM(D5:D14)` e `SUM(J5:J14)`), pagos ou não.
- D10 lucro, D12 margem e D13 ponto de equilíbrio = fixos ÷ margem de contribuição %.
- Série mensal C20:N22: cruza pelo texto do Mês e pelo ano 2026 escrito na fórmula, sem filtrar status.

**Previsão**
- Receita × (1 + K18)^n e clientes × (1 + K19)^n.
- Lucro = receita − fixos − (variáveis ÷ receita) × receita × (1 − K20)^n.
- Divide pela receita do mês, por isso dá `#DIV/0!` quando ela é zero.

## 2. Fórmulas-chave em palavras

**Caixa PF** (`'Painel Central'!B12:L12`)
- Realizado: entradas PF pagas no mês + entradas pontuais com Incluir? = Sim.
- Saídas realizadas: saídas PF pagas + faturas pagas.
- Projetado: as mesmas somas, sem filtrar status.
- Compromissos (N12): saídas PF não pagas do mês + faturas em aberto.

**Série mensal** (B24:F35)
- Entradas PF do mês + MAX(0; lucro PJ do mês) + pró-labore (quando o mês teve entrada PJ).

**Teto PF e PJ** (V32:W36)
- MAX(0; saldo da frente + entradas a receber − pagamentos pendentes da frente na linha do tempo).

**Linha do tempo de pagamentos por prioridade** (U41#)
1. **Junta as pendências do mês de 7 fontes:**
   - pessoais não pagas que não constam em Custos Pessoais (`COUNTIFS` por descrição + valor + vencimento);
   - faturas em aberto;
   - empresa não paga;
   - custos fixos e variáveis da empresa pendentes, que ainda não estão lançados;
   - custos fixos e variáveis pessoais pendentes.
2. **Pontuação, somando:**
   - 100 se já venceu;
   - +30 se vence em até 3 dias;
   - +40 se a categoria contém "Fatura" ou "Outros"; senão +45 se contém "Impostos"; senão +25 se contém "Aluguel" ou "Software"; senão +10;
   - + MIN(20; valor ÷ 500);
   - +60 se o valor é de 5.000 ou mais; +25 se é de 2.000 ou mais.
3. **Ordem:** pontuação decrescente; no empate, data crescente.
4. **Rótulos:**
   - Vencido: pontuação 100 ou mais. Ação: "Pagar hoje".
   - Crítico: pontuação 65 ou mais, ou valor de 5.000 ou mais. Ação: "Reservar agora".
   - Alto: pontuação 40 ou mais, ou valor de 2.000 ou mais. Ação: "Pagar no vencimento".
   - Normal: o resto. Ação: "Programar".
5. **Conta de cada item:**
   - empresa: Contabilizei Bank;
   - pessoal: "Mercado Pago" se a descrição contém esse nome, senão Inter;
   - fatura: o próprio cartão.
6. **Saldo após o pagamento:** saldo da conta − soma acumulada dos itens anteriores da mesma conta (`MAP` + `TAKE`).

A fórmula **diverge da `tblRegrasPrioridade`**: lá tributos valem 35, aqui 45; e "Outros" recebe o mesmo peso de fatura.

**Margem pessoal** (`'Custos Pessoais'!C32:C38`)
- Margem = entradas PF do mês − custos PF pendentes do mês.
- Reserva = 37,5% da margem, número escrito na fórmula.
- Disponível = margem − reserva.

**Objetivos**
- **Pontuação** (K44) = ROUND((Necessidade × 35 + Urgência × 30 + Impacto × 25 + Alternativa × 10) ÷ 4):
  - Necessidade, Urgência e Impacto valem de 1 a 4;
  - Alternativa: Adequada 1, Limitada 2,5, Não tenho 4.
- **Prioridade:** Imediata (80 ou mais), Alta (65 ou mais), Média (45 ou mais), Baixa.
- **Aporte recomendado** (O44) = o menor entre:
  - quanto falta guardar;
  - quanto falta ÷ prazo;
  - `LimiteSeguroObjetivos` × pontuação ÷ soma das pontuações dos objetivos Planejado e Em andamento.
- **`LimiteSeguroObjetivos`** (F41) = MIN(reserva sugerida; teto PF).
- **Prazo viável** = quanto falta ÷ aporte, arredondado para cima. **Data estimada** = `EDATE(TODAY(); prazo)`.

## 3. Esquema SQLite proposto (o menor que cobre PF + PJ)

Segue as convenções de `app/schema.sql:1-3`: dinheiro em REAL, datas ISO em TEXT e `excluido_em` para lixeira. Basta acrescentar ao `schema.sql`, porque o `executescript` em `app/db.py:94` já cria tabelas novas sem precisar de ferramenta de migração.

```sql
CREATE TABLE IF NOT EXISTS contas (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    escopo TEXT NOT NULL CHECK (escopo IN ('PF','PJ')),
    tipo TEXT NOT NULL DEFAULT 'banco' CHECK (tipo IN ('banco','cartao')),
    dia_fechamento INTEGER,          -- só cartão; a planilha não tem (vale quando lançar compras)
    dia_vencimento INTEGER,          -- só cartão
    saldo REAL,                      -- foto digitada, como tblSaldosContas
    saldo_em TEXT,
    excluido_em TEXT
);

CREATE TABLE IF NOT EXISTS recorrencias (
    id INTEGER PRIMARY KEY,
    escopo TEXT NOT NULL CHECK (escopo IN ('PF','PJ')),
    descricao TEXT NOT NULL,
    categoria TEXT NOT NULL,
    valor REAL NOT NULL CHECK (valor > 0),            -- previsto; a baixa grava o real
    dia_vencimento INTEGER NOT NULL CHECK (dia_vencimento BETWEEN 1 AND 31),
    fixo INTEGER NOT NULL DEFAULT 1,                  -- 1 fixo, 0 variável (ponto de equilíbrio)
    conta_id INTEGER REFERENCES contas(id),
    inicio TEXT NOT NULL,                             -- AAAA-MM
    fim TEXT,                                         -- AAAA-MM; NULL = sem fim
    origem TEXT UNIQUE,                               -- CEF-001, CPV-002…
    excluido_em TEXT
);

CREATE TABLE IF NOT EXISTS lancamentos (
    id INTEGER PRIMARY KEY,
    escopo TEXT NOT NULL CHECK (escopo IN ('PF','PJ')),
    tipo TEXT NOT NULL CHECK (tipo IN ('entrada','saida')),
    data TEXT NOT NULL,                               -- data do movimento / vencimento
    pago_em TEXT,                                     -- NULL = em aberto
    valor REAL NOT NULL CHECK (valor > 0),
    categoria TEXT NOT NULL,
    descricao TEXT,
    contraparte TEXT,
    cliente_id INTEGER REFERENCES clientes(id),
    conta_id INTEGER REFERENCES contas(id),
    forma TEXT,
    parcela_num INTEGER,
    parcela_total INTEGER,
    recorrencia_id INTEGER REFERENCES recorrencias(id),
    competencia TEXT,                                 -- AAAA-MM, só junto com recorrencia_id
    nfse INTEGER,                                     -- 1 emitida, 0 não, NULL não se aplica
    observacao TEXT,
    origem TEXT UNIQUE,                               -- 'PJ:17', 'PF:8', 'CC:11', 'EP:11'
    criado_em TEXT DEFAULT (datetime('now','localtime')),
    excluido_em TEXT,
    UNIQUE (recorrencia_id, competencia)
);
```

**Categorias e formas ficam sem tabela.** Viram listas em `parametros`: `lista_categorias_pj`, `lista_categorias_pf` e `lista_formas_lancamento`, cadastradas em `LISTAS_INICIAIS` (`app/db.py:59-66`).
- A tela Configurações já permite criar e apagar itens de qualquer grupo `lista_*` (`app/main.py:738`, `:762`, `:770`), então a interface sai de graça.
- **Não reaproveitar `lista_formas_pagamento`** (`app/db.py:65`): ela é da precificação (Cartão 1x, 3x…) e está ligada a `taxa_pagamento`.

**Parâmetros fiscais:** `parametros` no grupo `fiscal`, com `salario_minimo`, `pro_labore_pct` = 0,28 e `inss_pct` = 0,11. O DAS reaproveita o `('imposto','DAS')` = 0,06 que já existe no banco.

**Regras calculadas, sem coluna:**
- **Status:** pago se `pago_em` estiver preenchido; atrasado se `data` for anterior a hoje; senão pendente.
- **Pendências do mês:** lançamentos do mês com `pago_em` NULL + recorrências ativas que ainda não têm lançamento com aquele `(recorrencia_id, competencia)`. É uma consulta só, sem gerar linhas e sem tarefa agendada.
- **Dar baixa:**
  - numa recorrência: `INSERT` de um lançamento com `recorrencia_id`, `competencia` e o valor real;
  - num lançamento pendente: `UPDATE` de `pago_em`.
- **Vencimento da recorrência:** MIN(`dia_vencimento`; último dia do mês).
- **Compra parcelada:** N lançamentos com `parcela_num`/`parcela_total`, como a planilha já faz.
- **Fatura:** uma recorrência com o `conta_id` do cartão, categoria "Fatura" e valor estimado.
- **Total recebido por aluno:** soma dos lançamentos PJ de entrada pagos, por `cliente_id`. `cliente_eventos.tipo='pagamento'` tem 0 linhas e deve deixar de ser usado para dinheiro (`app/schema.sql:38-47`).
- **Prioridade:** os pesos da U41 viram uma constante em Python. Não precisa de tabela.

## 4. Mapeamento planilha → campo (migração única)

A leitura reaproveita `ler_tabela` (`app/importar.py:57-69`), filtrando só as linhas cuja Data é datetime. A gravação usa `INSERT OR IGNORE` pela coluna `origem`, então pode rodar de novo sem duplicar.

| Fonte | Coluna | Destino |
|---|---|---|
| **Transações Empresariais** (escopo PJ, conta Contabilizei Bank, origem `PJ:<linha>`) | Data | `data`; se Pago, também `pago_em = data` |
| | Tipo | `tipo` (entrada/saida) |
| | Cliente/Fornecedor | `contraparte`; e `cliente_id` quando é Entrada e o nome normalizado bate (9 de 11) |
| | Categoria, Forma Pagamento, Descrição | `categoria`, `forma`, `descricao` |
| | Valor (R$) | `round(valor, 2)` |
| | Status | Pago → `pago_em`; Pendente → NULL |
| | Emissão NFS-e | `nfse` (Emitida 1, Não Emitida 0, vazio NULL) |
| | Aulas | `observacao` ("aulas: N") |
| | Mês, Ano | descartar |
| **Transações Pessoais** (escopo PF, origem `PF:<linha>`) | Data, Tipo, Descrição, Forma Pagto, Status | iguais aos da empresa |
| | Categoria | normalizar "Outro" → "Outros" |
| | Valor | `round(valor, 2)` |
| | Parcela "n de N" | `parcela_num`, `parcela_total` |
| | Forma, Observação | `observacao` |
| | conta | regra da U41: "Mercado Pago" se a descrição contém, senão Inter |
| | Mês, ID Obrigação, Conciliação custo | descartar |
| **Cartões** (escopo PF, tipo saida, origem `CC:<linha>`) | Data, Valor, Forma de Pagamento, Status | `data`, `valor`, `forma`, `pago_em` |
| | Cartão | `conta_id` (conta do tipo cartão); `descricao` = "Fatura <cartão>" |
| | Categoria | "Fatura" |
| | Tipo | `observacao` |
| | Mês; `tblResumoFaturas` inteira | descartar (vira consulta) |
| **Custos ×4** → `recorrencias` (origem = ID) | Descrição, Categoria, Valor, Dia Venc., Conta | campos de mesmo nome (Dia Venc. → `dia_vencimento`) |
| | Tabela Fixos / Variáveis | `fixo` = 1 / 0 |
| | Aba | Empresariais → PJ; Pessoais → PF |
| | início | `inicio` = '2026-10' |
| | Observação "Eventual" | não vira recorrência: vira 1 lançamento pendente na data do Vencimento |
| | Observação "Parcelado" | recorrência com `fim`, ou nenhuma se já houver pendentes futuros (armadilha 6) |
| | Vencimento, Baixa manual?, Competência baixa, Data pagamento, Status consolidado, Conciliação | descartar |
| **tblContasFinanceiras + tblSaldosContas** | Conta, Frente, Saldo Atual, Atualizado em | `contas` (`nome`, `escopo`, `saldo`, `saldo_em`), mais 2 contas do tipo cartão |
| **tblEntradasPontuais** (origem `EP:<linha>`) | Competência, Valor, Descrição | lançamento PF de entrada; `data` = `pago_em` = Competência; categoria pela Fonte; só as linhas com Incluir? = Sim |
| **Backend_Fin** | CatReceita + CatDespesa | `lista_categorias_pj` |
| | Categorias PF distintas + Saúde, Dívidas, Fatura | `lista_categorias_pf` |
| | FormaPag + Débito Auto + Débito | `lista_formas_lancamento` |
| | Status, TipoCusto, Meses | descartar |
| **Clientes** | C16 | `fiscal.salario_minimo` |
| | 0,28 e 0,11 | `fiscal.pro_labore_pct` e `fiscal.inss_pct` |

**Volume:** cerca de 361 lançamentos (119 + 224 + 15 + 3), até 12 recorrências (menos as já cobertas por pendentes) e 7 contas.

## 5. O que pode ficar para a P2 sem perder controle
- **Objetivos:** são só 4 linhas, e a pontuação cabe em umas 15 linhas de Python.
- **Previsão de 6 meses, cenários** e "onde investir".
- **Compras itemizadas no cartão** usando `dia_fechamento`. Hoje só existem faturas.
- **Conciliação automática:** a baixa explícita a substitui.
- **Sugestão de categoria por palavra-chave** (`tblRegrasAgenda`) e a tabela de regras de prioridade.
- **Taxa segura por fase e perfil** (`'Painel Central'!C41`): a F41 não usa esse valor.
- **Saldo calculado por conta:** exigiria conta em todo lançamento PF, e a planilha não registra isso.
- **Ligar o histórico PJ às recorrências** (`recorrencia_id` retroativo).
- **Investimentos e Calculadora CLT.**

## 6. Armadilhas

**Leitura das tabelas**
1. **Linhas de total dentro do intervalo da tabela:** `Tabela15` linha 410 (Data = "Total"), `tblTransaçõesEmpresariais` linha 210 e `Tabela16` linha 211. O `ler_tabela` não as remove. Filtrar por `isinstance(Data, datetime)`.
2. **Linhas fantasma:** a `tblCartoes` tem 110 linhas vazias com Mês = "Janeiro", que é o `TEXT` de uma data vazia. O `ler_tabela` só pula linhas totalmente vazias, então elas entrariam. O mesmo filtro resolve.
3. **Mês sem ano:** as colunas Mês (`TEXT "mmmm"`, que depende do idioma) e os filtros por nome do mês ignoram o ano.
   - `'Painel Central'!I26:I33` e a `tblResumoFaturas` juntam outubro de 2026 com outubro de 2027.
   - Exemplo: "maio" tem 63 linhas = 60 de 2026 + 3 de 2027.
   - Nunca importar Mês/Ano; derivar da data.
4. **Datas:** são todas datetime reais, sem hora (só a linha de total é texto). Converter com `.date().isoformat()`.

**Valores**
5. **Sinal:** todos os valores são positivos e o sentido está só no Tipo. Manter `valor > 0` + `tipo` (com `CHECK`) e nunca gravar negativo.
6. **Arredondamento:** 8 valores PF têm mais de 2 casas por causa do ×1,00169. Aplicar `round(…, 2)`.

**Duplicidades**
7. **A mesma obrigação PF aparece duas vezes na planilha.** Itens de Custos Pessoais já existem como pendentes futuros em Transações Pessoais, com a mesma descrição:
   - CPF-002: 8 pendentes;
   - CPF-003: 11;
   - CPF-004: 5;
   - CPV-003: 8.

   A planilha só evita contar em dobro graças ao `COUNTIFS` da U41. Migrar os dois lados dobra as pendências. Regra: se já existem pendentes com a mesma descrição, não criar a recorrência (ou criar e apagar os pendentes — escolher um dos dois).
8. **Pagamentos de custos PJ já lançados:** os meses anteriores já estão em Transações Empresariais, com descrição ou fornecedor e valor iguais:
   - CEF-001: 6 coincidências;
   - CEF-002: 7;
   - CEF-003: 5;
   - CEV-003: 6.

   Não transformar a "Data pagamento" dos custos em lançamento.
9. **A conciliação falha por desenho:** o Vencimento é sempre recalculado para o mês vigente, então meses passados nunca ficam a 5 dias dele. O par `recorrencia_id` + `competencia` elimina o problema.
10. **Duplicatas dentro das abas:**
    - Empresa: 1 par idêntico.
    - Pessoal: 1 par idêntico, mais 3 pares com mesma data, tipo, valor e categoria, mas descrição diferente.

    Não deduplicar pelo conteúdo. A coluna `origem` ('aba:linha') garante que a migração não duplica, e esses pares devem ser listados para você revisar.

**Contas e nomes**
11. **Conta ausente:** as abas pessoal e Cartões não registram conta, e a empresa assume Contabilizei Bank. Usar a mesma regra da U41 ou deixar NULL.
12. **Nomes repetidos entre banco e cartão:** Inter e Itaú são ao mesmo tempo conta PF e cartão. Como `contas.nome` é `UNIQUE`, usar nomes distintos (por exemplo, "Cartão Inter").
13. **Cruzamento por nome:** 2 das 11 contrapartes de entrada PJ não batem com os clientes do CRM. Ficam com `cliente_id` NULL e o nome em `contraparte`, para revisão.

**Listas e categorias**
14. **Categorias e formas inconsistentes:**
    - "Outro" e "Outros" coexistem na aba pessoal;
    - a aba pessoal usa formas fora da Backend_Fin ("Débito Auto", "Débito");
    - "Saúde" só existe no Painel, e "Dívidas" só em Custos.
15. **`lista_formas_pagamento` do CRM é de preço** (`app/db.py:65`). Usar a lista nova.

**Regras de negócio da planilha**
16. **Pendente não é atrasado:** na aba pessoal, "Pendente" significa futuro, e "Atrasado" nunca é usado. O status passa a ser calculado de `pago_em` + `data`.
17. **Vencimento nos dias 29 a 31:** no Excel, `DATE(ano, 2, 31)` vira uma data de março. No CRM, usar MIN(dia; fim do mês).
18. **Pró-labore contado duas vezes na renda PF:** a série B24:C35 soma MAX(0; lucro PJ) + pró-labore, e a empresa não lança o pró-labore como saída. Não replicar sem você decidir.
19. **"Realizado" mistura status:** a receita do Dashboard (D7) soma pagos + pendentes, e a série mensal (C20) não filtra status. No CRM, realizado = `pago_em` preenchido.

**Execução**
20. **Bloqueio do arquivo:** desta vez a planilha abriu, mas na rodada anterior deu `PermissionError`. Rodar a migração com o Excel fechado. Como cada linha tem `origem`, a migração pode ser repetida sem duplicar.

**Arquivos citados**
- `C:\Users\victo\OneDrive\Documentos\Contabilidade.xlsx`
- `C:\Users\victo\VFITCOACH-CRM\app\schema.sql`
- `C:\Users\victo\VFITCOACH-CRM\app\db.py`
- `C:\Users\victo\VFITCOACH-CRM\app\importar.py`
- `C:\Users\victo\VFITCOACH-CRM\app\main.py`
- `C:\Users\victo\VFITCOACH-CRM\data\crm.db`