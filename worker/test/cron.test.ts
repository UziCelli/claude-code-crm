import { createExecutionContext, createScheduledController, env, waitOnExecutionContext } from "cloudflare:test";
import { afterEach, expect, it, vi } from "vitest";
import worker from "../src/index.ts";

afterEach(() => vi.restoreAllMocks());

it("a cada 10 min acorda o Render pelo /saude", async () => {
  const f = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("ok"));
  const ctx = createExecutionContext();
  await worker.scheduled(createScheduledController({ cron: "*/10 * * * *" }), { ...env, RENDER_URL: "https://claude-code-crm.onrender.com" }, ctx);
  await waitOnExecutionContext(ctx);
  expect(String((f.mock.calls[0][0] as URL).href)).toBe("https://claude-code-crm.onrender.com/saude");
});

it("sem RENDER_URL (Render desligado) não chama nada", async () => {
  const f = vi.spyOn(globalThis, "fetch");
  const ctx = createExecutionContext();
  await worker.scheduled(createScheduledController({ cron: "*/10 * * * *" }), { ...env, RENDER_URL: undefined }, ctx);
  await waitOnExecutionContext(ctx);
  expect(f).not.toHaveBeenCalled();
});
