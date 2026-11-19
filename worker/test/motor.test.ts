import { afterAll, beforeAll, describe, expect, it } from "vitest";
import cenario from "./dados/cenario-motor.sql?raw";
import py from "./paridade/motor.json";
import { ehCia, ehLocalCia } from "../src/regras/contas_auto.ts";
import { utilAnterior } from "../src/regras/datas.ts";
import { custoPessoalMedio, custosFixosRateio, dasCompetencia, ehDas, textoPct, vencimentoUtil } from "../src/regras/financeiro.ts";
import { baseMotor, calcular, calcularMisto, carregarParametros, corMargem, decompor, multHorario, type Params } from "../src/regras/precos.ts";
import { aulasMes, baseDoCliente, fixosAtuais, horasTrabalhoDetalhe } from "../src/regras/trabalho.ts";
import { definirAgora } from "../src/relogio.ts";
import { banco, carregarCenario, jsonavel, semear } from "./apoio.ts";

let p: Params;
beforeAll(async () => {
  definirAgora(new Date("2026-11-19T15:00:00Z"));
  await semear();
  await carregarCenario(cenario);
  p = await carregarParametros(banco());
});
afterAll(() => definirAgora(null));

describe("motor de preços igual ao Python (cenário do motor)", () => {
  it("carregar_parametros, com salário automático e rateio", () => {
    expect(jsonavel(p)).toEqual(py.params);
  });

  it("carregar_parametros em 2 idas ao banco (o RBT12 depende do 1º mês com receita)", async () => {
    const b = banco();
    await carregarParametros(b);
    expect(b.idas).toBe(2);
  });

  it("horas de trabalho e horários fixos", async () => {
    expect(jsonavel(await horasTrabalhoDetalhe(banco(), p))).toEqual(py.trabalho);
    expect(jsonavel(await fixosAtuais(banco()))).toEqual(py.fixos);
  });

  it("DAS, custo pessoal e custos fixos", async () => {
    for (const [mes, d] of Object.entries(py.das)) expect(jsonavel(await dasCompetencia(banco(), mes)), mes).toEqual(d);
    expect(jsonavel(await custoPessoalMedio(banco(), "2026-11"))).toEqual(py.custo_pessoal);
    expect(jsonavel(await custosFixosRateio(banco(), "2026-11", [...p.locais.keys()]))).toEqual(py.custos_fixos);
  });

  it("calcular: todos os planos, locais, grupos, formas e preço final (inclusive os erros)", () => {
    for (const [tipo, qtd, freq, local, pessoas, forma, final, esperado] of py.calculos as [string, number, number, string | null, number, string, number | null, unknown][]) {
      let r: unknown;
      try {
        r = calcular(baseMotor(tipo, qtd, freq, local), p, { pessoas, forma_pagamento: forma, preco_final: final, local, mult_horario: 1.1 });
      } catch (e) {
        r = { erro: (e as Error).message };
      }
      expect(r, `${tipo} ${qtd} ${freq} ${local} ${pessoas} ${forma} ${final}`).toEqual(esperado);
    }
  });

  it("calcular_misto e decompor", () => {
    const m = baseMotor("Mensalidade", 0, 2, "CIA");
    const r = [
      calcularMisto([[m, 1, "CIA"], [baseMotor("Mensalidade", 0, 2, "Smart Fit"), 1.2, "Smart Fit"]], p, { pessoas: 2, desconto: 0.05, forma_pagamento: "PIX" }),
      calcularMisto([[m, null, "Box Centro"]], p, { pessoas: 1, forma_pagamento: "Cartão 1x", extra: [120, 40] }),
      calcularMisto([[m, 1, "CIA"]], p, { forma_pagamento: "PIX", extra: [100, 30, 10, 2.5] }),
    ];
    expect(r).toEqual(py.misto);
    for (const [tipo, qtd, freq, local, esperado] of py.decompor as [string, number, number, string, unknown][])
      expect(decompor(baseMotor(tipo, qtd, freq, local), p, local), `${tipo} ${local}`).toEqual(esperado);
  });

  it("multiplicadores, plano do aluno, cores e textos", async () => {
    expect(jsonavel(await multHorario(banco()))).toEqual(py.mult_horario);
    for (const [c, base, aulas] of py.base_cliente as [Record<string, unknown>, unknown, number][]) {
      expect(baseDoCliente(c), String(c.nome)).toEqual(base);
      expect(aulasMes(c)).toBe(aulas);
    }
    for (const [x, t] of py.texto_pct as [number, string][]) expect(textoPct(x), String(x)).toBe(t);
    for (const [m, mi, cor] of py.cor_margem as [number | null, number, string][]) expect(corMargem(m, mi)).toBe(cor);
    for (const [d, c, r] of py.eh_das as [string | null, string | null, boolean][]) expect(ehDas(d, c), `${d} / ${c}`).toBe(r);
    for (const [t, cia, local] of py.eh_cia as [string | null, boolean, boolean][]) {
      expect(ehCia(t), String(t)).toBe(cia);
      expect(ehLocalCia(t), String(t)).toBe(local);
    }
    for (const [d, r] of py.util as [string, string][]) {
      if (d.includes("|")) {
        const [dia, mes] = d.split("|");
        expect(vencimentoUtil(Number(dia), mes)).toBe(r);
      } else expect(utilAnterior(d)).toBe(r);
    }
  });
});
