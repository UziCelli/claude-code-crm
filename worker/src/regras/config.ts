/** Grupos da tela Configurações: [grupo, título, formato] (port de main.GRUPOS_CONFIG, mesma ordem e textos). */
export const GRUPOS_CONFIG: [string, string, "pct" | "num"][] = [
  ["taxa_pagamento", "Taxas por forma de pagamento", "pct"],
  ["margem_minima", "Margem mínima por serviço", "pct"],
  ["taxa_cia", "Taxa da CIA por pessoa (R$) e máximo de pessoas", "num"],
  ["cia_deslocamento", "Deslocamento até a CIA: R$ por aula (gasolina, Uber) e minutos por aula (contam como seu trabalho)", "num"],
  ["cia_mensal", "Taxa mensal fixa da CIA (R$) e aulas por mês nela (para dividir a taxa; 0 = sem taxa)", "num"],
  ["margem_alvo", "Margem alvo por serviço: a do preço de tabela, antes do desconto (fica acima da mínima)", "pct"],
  ["grupo_multiplicador", "Multiplicador por nº de pessoas: só a estimativa das Sugestões (o preço do grupo sai do custo)", "num"],
  ["grupo_mao_obra_extra", "Mão de obra extra por nº de pessoas", "pct"],
  ["metas", "Metas do painel", "num"],
  ["mao_obra", "Mão de obra = pró-labore (seu salário): valor da hora (R$; 0 = usa a planilha) e minutos de trabalho (aula, planejamento por pacote e por mês de mensalidade, consultoria por mês, avaliação; 0 = usa a planilha). O deslocamento vem de cada local (o da CIA fica em 'Deslocamento até a CIA'). O lucro é o que sobra depois disso", "num"],
  ["agenda", "Agenda: semanas contratadas por mês na Mensalidade (aulas do mês = vezes por semana × isto; a aula a mais num mês de 5 semanas aparece como 'passou') e máximo de alunos no mesmo horário fixo", "num"],
  ["lead_parado_dias", "Limite de dias parado por etapa", "num"],
  ["funil_chance", "Chance de fechar por etapa do funil", "pct"],
  ["fiscal", "Fiscal: salário mínimo (R$), pró-labore e INSS (frações, ex.: 0,28 = 28%)", "num"],
  ["salario", "Salário fixo da PJ para a PF: valor (R$ por mês; 0 = desligado) e dia do pagamento", "num"],
  ["contas_auto", "Contas automáticas: dia do mês em que vence a conta da CIA (o app a lança sozinho em Contas a pagar; fim de semana antecipa para a sexta)", "num"],
  ["colchao", "Reserva: meta em meses de custo fixo (0 = sem meta)", "num"],
  ["impacto_curto", "Fila de pagamento: o quanto atrasar atrapalha agora (0 a 40; quanto maior, mais cedo na fila)", "num"],
  ["impacto_juros", "Fila de pagamento: juros e multa por mês de atraso (quanto maior, mais cedo na fila)", "pct"],
  ["cobranca", "Cobrança de aluno atrasado: multa (uma vez) e juros ao mês, proporcional aos dias. Só cobre se estiver no contrato; pelo Código do Consumidor a multa vai até 2%", "pct"],
  ["familia", "Família: quantas pessoas vivem da renda da PF (Saúde financeira)", "num"],
  ["saude", "Saúde financeira: reserva mensal desejada em R$ (entra no ponto de equilíbrio econômico)", "num"],
  ["pacote_personalizado", "Pacote personalizado (1 a 20 aulas): desconto da consultoria no combo", "pct"],
];

/** Nome bonito de cada modelo de WhatsApp (main.WA_ROTULOS). */
export const WA_ROTULOS: Record<string, string> = {
  "cobranca": "Cobrar",
  "renovacao": "Renovação",
  "falta": "Falta",
  "boas_vindas": "Boas-vindas",
  "reativacao": "Reativação",
  "indicacao": "Indicação",
  "dupla": "Treino em dupla",
  "depoimento": "Pedir depoimento",
  "cobranca_lembrete": "Cobrança: lembrete",
  "cobranca_hoje": "Cobrança: vence hoje",
  "cobranca_moderada": "Cobrança: moderada",
  "cobranca_critica": "Cobrança: crítica",
  "cobranca_diferenca": "Cobrança: diferença de multa e juros"
};
