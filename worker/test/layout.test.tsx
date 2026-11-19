import { afterAll, beforeAll, expect, it } from "vitest";
import pythonBase from "./paridade/base.html?raw";
import { definirAgora } from "../src/relogio.ts";
import { Base } from "../src/telas/Base.tsx";
import { contextoBase } from "../src/telas/contexto.ts";
import { banco, semear } from "./apoio.ts";
import { canonico, semVersao } from "./html.ts";

beforeAll(async () => {
  await semear();
  definirAgora(new Date("2026-11-19T15:00:00Z"));
});
afterAll(() => definirAgora(null));

it("o layout sai igual ao base.html do Python, numa ida só ao banco", async () => {
  const b = banco();
  const ctx = await contextoBase(b, new Request("https://crm.vfitcoachapp.com/clientes?msg=Salvo&erro=Falhou"));
  expect(b.idas).toBe(1);
  const html = String(<Base ctx={ctx}><p>conteúdo da tela</p></Base>);
  expect(canonico(html, semVersao)).toEqual(canonico(pythonBase, semVersao));
});
