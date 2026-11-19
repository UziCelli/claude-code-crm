import { afterAll, beforeAll, describe, expect, it } from "vitest";
import cenario from "./dados/cenario-alunos.sql?raw";
import py from "./paridade/alunos.json";
import { diasParados, estado, fraseValor } from "../src/regras/alunos.ts";
import { cobranca, creditos, diferencas, mensalidades, pagoAdiantadoAte, renovacoes, type Credito } from "../src/regras/financeiro.ts";
import { parametros } from "../src/regras/parametros.ts";
import { brCode } from "../src/regras/pix.ts";
import { definirAgora } from "../src/relogio.ts";
import { banco, carregarCenario, jsonavel, semear } from "./apoio.ts";

const HOJE = "2026-11-19";
beforeAll(async () => {
  definirAgora(new Date("2026-11-19T15:00:00Z"));
  await semear();
  await carregarCenario(cenario);
});
afterAll(() => definirAgora(null));

/** Compara aluno a aluno, para o erro dizer qual. */
function porAluno(ts: unknown, esperado: Record<string, unknown>) {
  const obtido = jsonavel(ts) as Record<string, unknown>;
  expect(Object.keys(obtido).sort()).toEqual(Object.keys(esperado).sort());
  for (const k of Object.keys(esperado)) expect(obtido[k], `aluno ${k}`).toEqual(esperado[k]);
}

describe("estado do aluno igual ao Python (70 alunos sintéticos, 7 situações)", () => {
  it("todos de uma vez", async () => {
    const b = banco();
    porAluno(await estado(b, HOJE), py.estado);
    expect(b.idas).toBeLessThanOrEqual(4);
  });

  it("um aluno só (o caminho com filtro por aluno)", async () => {
    for (const [cid, esperado] of Object.entries(py.estado_um)) {
      const r = await estado(banco(), HOJE, [Number(cid)]);
      expect(jsonavel(r.get(Number(cid)) ?? null), `aluno ${cid}`).toEqual(esperado);
    }
  });
});

describe("financeiro dos alunos igual ao Python", () => {
  it("renovações, créditos, diferenças e pago adiantado", async () => {
    porAluno(await renovacoes(banco()), py.renovacoes);
    expect(jsonavel(await creditos(banco()))).toEqual(py.creditos);
    expect(jsonavel(await diferencas(banco()))).toEqual(py.diferencas);
    expect(jsonavel(await pagoAdiantadoAte(banco(), HOJE))).toEqual(py.pago_adiantado_ate);
  });

  it("mensalidades de 4 meses", async () => {
    for (const [mes, esperado] of Object.entries(py.mensalidades)) expect(jsonavel(await mensalidades(banco(), mes)), mes).toEqual(esperado);
  });

  it("cobrança: valores, datas tortas, crédito e dia do vencimento", async () => {
    const par = await parametros(banco(), "cobranca");
    for (const [v, venc, cred, dia, esperado] of py.cobranca as [number, string, number, number | null, unknown][])
      expect(cobranca(v, venc, HOJE, par, cred, dia), `${v} ${venc} ${cred} ${dia}`).toEqual(esperado);
  });

  it("dias parados, código Pix e frase do valor", () => {
    for (const [u, h, iv, r] of py.dias_parados as [string, string, [string, string][], number][]) expect(diasParados(u, h, iv)).toBe(r);
    for (const [c, nm, ci, v, r] of py.br_code as [string, string, string, number | null, string][]) expect(brCode(c, nm, ci, v), `${c} ${nm}`).toBe(r);
    for (const [v, cs, r] of py.frase_valor as [number, Credito[] | null, string][]) expect(fraseValor(v, cs)).toBe(r);
  });
});
