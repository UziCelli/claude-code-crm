import { describe, expect, it } from "vitest";
import casos from "./paridade/arred.json";
import { arred } from "../src/arred.ts";

describe("arred = round() do Python", () => {
  it("bate em todos os casos gerados pelo Python", () => {
    const erros = (casos as [number, number, number][]).filter(([x, n, r]) => !Object.is(arred(x, n), r));
    expect(erros.slice(0, 5)).toEqual([]);
    expect(casos.length).toBeGreaterThan(3000);
  });
  it("casos clássicos", () => {
    expect(arred(2.675)).toBe(2.67);
    expect(arred(0.125)).toBe(0.12);
    expect(arred(0.375)).toBe(0.38);
    expect(arred(2.5, 0)).toBe(2);
    expect(arred(3.5, 0)).toBe(4);
  });
});
