import { applyD1Migrations, env } from "cloudflare:test";

// Cada arquivo de teste começa com o esquema do CRM (migrations/) no D1 local.
await applyD1Migrations(env.DB, env.TEST_MIGRATIONS);
