import { afterEach, expect, it } from "vitest";
import { agoraTxt, definirAgora, hoje } from "../src/relogio.ts";

afterEach(() => definirAgora(null));

it("depois das 21h de Brasília ainda é o mesmo dia (UTC já virou)", () => {
  definirAgora(new Date("2026-11-20T01:30:00Z"));
  expect(hoje()).toBe("2026-11-19");
  expect(agoraTxt()).toBe("2026-11-19 22:30:00");
});

it("meia-noite de Brasília", () => {
  definirAgora(new Date("2026-11-20T03:00:00Z"));
  expect(agoraTxt()).toBe("2026-11-20 00:00:00");
});
