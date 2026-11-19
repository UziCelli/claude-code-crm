import path from "node:path";
import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest(async () => ({
      wrangler: { configPath: "./wrangler.jsonc" },
      miniflare: {
        // Nos testes: banco D1 local com o esquema das migrações; portaria com equipe/AUD de teste.
        bindings: {
          TEST_MIGRATIONS: await readD1Migrations(path.join(import.meta.dirname, "migrations")),
          BANCO: "d1",
          CF_ACCESS_TEAM_DOMAIN: "vfit.cloudflareaccess.com",
          CF_ACCESS_AUD: "aud-do-crm",
        },
      },
    })),
  ],
  test: { setupFiles: ["./test/preparar.ts"] },
});
