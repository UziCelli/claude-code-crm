import { expect, it } from "vitest";
import casos from "./paridade/formato.json";
import { dataBr, moeda, num, pct, preencher, wa } from "../src/formato.ts";

it("moeda igual ao Python", () => {
  for (const [v, r] of casos.moeda as [number | null, string][]) expect(moeda(v), String(v)).toBe(r);
});
it("data_br igual ao Python", () => {
  for (const [v, r] of casos.data_br as [string | null, string][]) expect(dataBr(v), String(v)).toBe(r);
});
it("pct e num iguais ao Python", () => {
  for (const [v, c, r] of casos.pct as [number | null, number, string][]) expect(pct(v, c), `${v} ${c}`).toBe(r);
  for (const [v, c, r] of casos.num as [number | null, number, string][]) expect(num(v, c), `${v} ${c}`).toBe(r);
});
it("link do WhatsApp igual ao Python", () => {
  for (const [t, x, r] of casos.wa as [string | number | null, string, string][]) expect(wa(t, x), `${t} ${x}`).toBe(r);
});
it("preencher igual ao Python", () => {
  for (const [x, n, d, e, r] of casos.preencher as [string, string, string, Record<string, unknown>, string][]) expect(preencher(x, n, d, e)).toBe(r);
});
