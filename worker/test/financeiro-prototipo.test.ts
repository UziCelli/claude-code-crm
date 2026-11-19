import { env } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import cenario from "./dados/cenario-financeiro.sql?raw";
import py from "./paridade/financeiro-prototipo.json";
import { coberturaAdiantada, duplicados, mesesDoPagamento, palavras, somarMeses, vencimento } from "../src/regras/financeiro.ts";
import { banco, semear } from "./apoio.ts";

beforeAll(async () => {
  await semear();
  const cmds = cenario.split("\n").filter((l) => l.startsWith("INSERT"));
  await env.DB.batch(cmds.map((sql) => env.DB.prepare(sql)));
});

describe("financeiro (protótipo): igual ao Python no cenário 3x", () => {
  it("funções pequenas", () => {
    for (const [m, n, r] of py.somar_meses as [string, number, string][]) expect(somarMeses(m, n)).toBe(r);
    for (const [d, m, r] of py.vencimento as [number, string, string][]) expect(vencimento(d, m)).toBe(r);
    for (const [v, val, e, r] of py.meses_do_pagamento as [number | null, number | null, number | null, number][])
      expect(mesesDoPagamento(v, val, e), `${v} ${val} ${e}`).toBe(r);
    for (const [t, r] of py.palavras as [string | null, string[]][]) expect(palavras(t)).toEqual(r);
  });

  it("cobertura adiantada, mês a mês", async () => {
    for (const [mes, esperado] of Object.entries(py.cobertura)) {
      const b = banco();
      const r = await coberturaAdiantada(b, mes);
      expect(Object.fromEntries([...r].map(([k, v]) => [String(k), v])), mes).toEqual(esperado);
      expect(b.idas).toBe(1);
    }
  });

  it("lançamentos repetidos", async () => {
    const b = banco();
    const r = await duplicados(b, new Set(py.ja_avisadas as number[]));
    expect(r.length).toBe(py.duplicados.length);
    expect(r).toEqual(py.duplicados);
    expect(b.idas).toBe(1);
  });
});
