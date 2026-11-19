import type { D1Migration } from "@cloudflare/vitest-plugin";
import type { Env } from "../src/tipos.ts";

declare global {
  namespace Cloudflare {
    interface Env extends Omit<import("../src/tipos.ts").Env, never> {
      TEST_MIGRATIONS: D1Migration[];
    }
  }
}
export type { Env };
