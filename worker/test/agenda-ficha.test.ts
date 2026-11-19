import { env } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import cenario from "./dados/cenario-agenda.sql?raw";
import roteiroJson from "./paridade/agenda-ficha.json";
import { definirAgora } from "../src/relogio.ts";
import { abrir, carregarCenario, normalizarTabela, pedido, semear, type Roteiro } from "./apoio.ts";
import { canonico, semVersao } from "./html.ts";

/** Etapa 3a: o que a ficha grava na Agenda (horários, status, evento, pular mês, salvar), igual ao Python. */
const py = roteiroJson as unknown as Roteiro;
beforeAll(async () => {
  definirAgora(new Date("2026-11-19T15:00:00Z"));
  await semear();
  await carregarCenario(cenario);
});
afterAll(() => definirAgora(null));

describe("fichas com horários da Agenda iguais ao Python", () => {
  for (const [url, html] of Object.entries(py.telas)) {
    it(url, async () => {
      const r = await abrir(url);
      expect(r.status, url).toBe(200);
      expect(canonico(await r.text(), semVersao)).toEqual(canonico(html, semVersao));
    });
  }
});

describe("roteiro da ficha na Agenda igual ao Python (respostas e banco no fim)", () => {
  it(`${py.respostas.length} cliques`, async () => {
    for (const [metodo, url, dados, status, local] of py.respostas) {
      const r = await pedido(metodo, url, dados);
      const quem = `${metodo} ${url} ${JSON.stringify(dados)}`;
      expect([r.status, r.headers.get("location")], quem).toEqual([status, local]);
      if (status === 303) expect(Number(r.headers.get("x-crm-idas")), `idas: ${quem}`).toBeLessThanOrEqual(10);
    }
    for (const [tabela, esperado] of Object.entries(py.tabelas)) {
      const { results } = await env.DB.prepare(`SELECT * FROM "${tabela}" ORDER BY rowid`).all();
      const obtido = normalizarTabela(results as Record<string, unknown>[]);
      expect(obtido.length, tabela).toBe(esperado.length);
      obtido.forEach((linha, i) => expect(linha, `${tabela} linha ${i + 1}`).toEqual(esperado[i]));
    }
  });
});
