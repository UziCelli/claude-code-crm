/** Ligações e variáveis do Worker (wrangler.jsonc + painel do Cloudflare). */
export interface Env {
  ASSETS: Fetcher;
  DB: D1Database;
  /** "turso" (durante a troca, mesmo banco do Render) ou "d1" (depois da cópia). Obrigatória: sem ela o CRM não abre. */
  BANCO?: string;
  TURSO_DATABASE_URL?: string;
  TURSO_AUTH_TOKEN?: string;
  CF_ACCESS_TEAM_DOMAIN?: string;
  CF_ACCESS_AUD?: string;
  /** Outros endereços públicos aceitos no Origin/Referer de um POST, separados por vírgula. */
  CRM_ENDERECOS?: string;
  /** Endereço direto do Render (ex.: https://claude-code-crm.onrender.com): o Cron o acorda a cada 10 min. */
  RENDER_URL?: string;
  /** Emergência: prefixos de rota (separados por vírgula) que voltam a ser atendidos pelo Render. */
  ROTAS_RENDER?: string;
  ANTHROPIC_API_KEY?: string;
}
