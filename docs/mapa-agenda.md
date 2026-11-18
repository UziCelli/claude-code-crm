# Mapa da Agenda: a fonte dos horários (nov/2026)

**Ideia central:** a Agenda (`agenda_fixos`) é a única fonte dos horários fixos de cada aluno. As outras telas leem dela e gravam nela; nenhuma guarda a sua própria cópia. Pedido do Victor: Clientes, Agenda, Grade e Configurações interligados.

## Quem lê

Todos começam em `main.fixos_atuais(con, ids=None)`: os horários fixos que valem hoje, de alunos ativos, um por (aluno, dia, hora).

| Leitor | Função | Uso |
|---|---|---|
| Grade, Explorador, Propostas, Sugestões | `main.bloqueios_gerais` | Ocupação de cada (dia, hora), com todos os alunos, ids e vagas. Da `grade_slots` só valem "indisponível" e "ocupado sem aluno". |
| Horas de trabalho | `main.horas_trabalho_detalhe` | Cada (dia, hora) vale 4,33 aulas, contado uma vez mesmo com dupla. O deslocamento é o do local do horário. Aluno sem horário conta pelo plano. Alimenta `precos.carregar_parametros`, ou seja, o salário/hora e o rateio. |
| Aulas do mês | `main.resumo_aulas_mes` | Previstas = horários do mês, sem pausa nem bloqueio e sem reposição. Também calcula contratadas, feitas, faltam e passou, e o custo extra na CIA, dividido pela dupla. |
| Ficha e lista de clientes | `main.horarios_texto` | Texto "Seg 13h · Qui 17h". A coluna `clientes.dias_horarios` é só um texto antigo, de leitura. |
| Cálculos | `main.divergencias_plano_agenda` | Alunos cujo plano não bate com os horários da Agenda. |

## Quem grava

Toda gravação passa por `main.definir_horario(con, dia, hora, alunos, local)` ou `main.inserir_fixos`. Essas funções cuidam da vigência (`vigente_de`), da exclusão suave (lixeira) e de gravar só a diferença.

- **Agenda:** `/agenda/horario`, `/agenda/incluir`.
- **Ficha:** `POST /clientes/{id}/horarios`, que recebe a lista inteira de horários do aluno.
- **Grade:** `POST /grade/slot`.
  - Um horário: a lista escolhida passa a ser a do horário.
  - Vários horários de uma vez: soma alunos, sem tirar ninguém.
  - "Livre": tira da Agenda quem está no horário.
- **Migração:** `/grade/passar-para-agenda` cria na Agenda o que só existia na Grade antiga (`main.so_na_grade`). Nunca apaga nada.

A `grade_slots` com `cliente_id` é uma cópia antiga. Ela ainda é atualizada como espelho, mas **não é lida**.

## Regras que não podem quebrar

1. **Limite de alunos:** `agenda.max_alunos_horario` (padrão 2), lido por `main.max_alunos`. Vale na Agenda, na ficha, na Grade, ao restaurar da lixeira e quando um aluno volta a ficar ativo.
2. **Ninguém sai sem ser tirado.** `definir_horario` não corta a lista. Quem chama confere o limite: entrar aluno novo acima do limite é recusado. Uma turma que já passou do limite, porque o limite foi reduzido, fica como está.
3. **Reposição e avulsa** (`agenda_avulsas`) não são horário fixo. Não entram em horas, previstas nem Grade.
4. **Contratadas:** Mensalidade Nx vale N × `agenda.semanas_contratadas` (padrão 4); Pacote N vale N. A estimativa por aluno (ficha, propostas) continua pelo plano.
5. **Data de hoje:** sempre `app/relogio.py` (`hoje`, `agora`, `agora_txt`), no fuso do Brasil por zoneinfo. Nunca usar `date.today()`/`datetime.now()`: no Windows o `TZ` com nome de fuso vira UTC. Há um teste que barra isso.
6. **Nome do local** é chave de texto em várias tabelas. Renomear só por `locais.renomear_local`, numa transação só, inclusive nas linhas excluídas e nos textos das contas que citam o local.

Testes de referência: `test_grade_geral.py` (seção "Grade lê a Agenda"), `test_horas_agenda.py`, `test_aulas_mes.py`, `test_ficha_horarios.py`, `test_locais_editar.py` (renomear), `test_relogio.py`. Histórico das decisões: PROGRESSO.md, seções de 18/11/2026.
