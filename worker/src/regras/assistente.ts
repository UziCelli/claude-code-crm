/** Chave do Assistente (port das partes de app/assistente.py usadas em Configurações). O resto entra na fase do Assistente. */
import type { Banco } from "../banco/banco.ts";
import type { Env } from "../tipos.ts";

export const CHAVE_SEGREDO = "anthropic_api_key";
export const MODELO_PADRAO = "claude-haiku-5-5";

/** A chave salva em Configurações (tabela segredos); "" sem chave. */
export async function chaveSalva(b: Banco): Promise<string> {
  const v = await b.valor<string | null>("SELECT valor FROM segredos WHERE chave=?", [CHAVE_SEGREDO]);
  return (v ?? "").trim();
}

/** A chave do Worker (secret ANTHROPIC_API_KEY) vence a salva em Configurações. */
export function chaveEnv(env: Env): string {
  return (env.ANTHROPIC_API_KEY ?? "").trim();
}

export interface InfoAssistente { ligado: boolean; origem: "env" | "config" | ""; final: string }

export function info(env: Env, salva: string): InfoAssistente {
  const e = chaveEnv(env);
  const origem = e ? "env" : salva ? "config" : "";
  const chave = e || salva;
  return { ligado: Boolean(origem), origem, final: chave ? "…" + chave.slice(-4) : "" };
}

export async function salvarChave(b: Banco, valor: string): Promise<void> {
  await b.run(`INSERT INTO segredos (chave, valor) VALUES (?, ?)
    ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor, atualizado_em=datetime('now','localtime')`, [CHAVE_SEGREDO, valor.trim()]);
}

export async function removerChave(b: Banco): Promise<void> {
  await b.run("DELETE FROM segredos WHERE chave=?", [CHAVE_SEGREDO]);
}
