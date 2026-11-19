import { env } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import cenario from "./dados/cenario-clientes.sql?raw";
import roteiroJson from "./paridade/clientes.json";
import { definirAgora } from "../src/relogio.ts";
import { abrir, carregarCenario, normalizarTabela, pedido, semear, type Roteiro } from "./apoio.ts";
import { canonico, semVersao } from "./html.ts";

const py = roteiroJson as unknown as Roteiro;
beforeAll(async () => {
  definirAgora(new Date("2026-11-19T15:00:00Z"));
  await semear();
  await carregarCenario(cenario);
});
afterAll(() => definirAgora(null));

describe("telas de clientes e leads iguais ao Python", () => {
  for (const [url, html] of Object.entries(py.telas)) {
    it(url, async () => {
      const r = await abrir(url);
      if (url === "/clientes/99999") {
        expect(r.status).toBe(303);
        return;
      }
      expect(r.status, url).toBe(200);
      expect(Number(r.headers.get("x-crm-idas")), "idas ao banco").toBeLessThanOrEqual(12);
      expect(canonico(await r.text(), semVersao)).toEqual(canonico(html, semVersao));
    });
  }
});

describe("roteiro de cliques igual ao Python (respostas e banco no fim)", () => {
  it("37 cliques", async () => {
    for (const [metodo, url, dados, status, local] of py.respostas) {
      const r = await pedido(metodo, url, dados);
      expect([r.status, r.headers.get("location")], `${metodo} ${url} ${JSON.stringify(dados)}`).toEqual([status, local]);
    }
    for (const [tabela, esperado] of Object.entries(py.tabelas)) {
      const { results } = await env.DB.prepare(`SELECT * FROM "${tabela}" ORDER BY rowid`).all();
      const obtido = normalizarTabela(results as Record<string, unknown>[]);
      expect(obtido.length, tabela).toBe(esperado.length);
      obtido.forEach((linha, i) => expect(linha, `${tabela} linha ${i + 1}`).toEqual(esperado[i]));
    }
  });
});
