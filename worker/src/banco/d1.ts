import type { Comando, Driver, Gravacao, Linha } from "./tipos.ts";

/** D1: db.batch() é uma consulta só no limite do plano grátis (50 por pedido) e roda como transação. */
export class DriverD1 implements Driver {
  constructor(private db: D1Database) {}

  private preparar(cmds: Comando[]) {
    return cmds.map((c) => this.db.prepare(c.sql).bind(...(c.params ?? [])));
  }

  async ler(cmds: Comando[]): Promise<Linha[][]> {
    const res = await this.db.batch<Linha>(this.preparar(cmds));
    return res.map((r) => r.results ?? []);
  }

  async gravar(cmds: Comando[]): Promise<Gravacao[]> {
    const res = await this.db.batch<Linha>(this.preparar(cmds));
    return res.map((r) => ({
      mudancas: r.meta?.changes ?? 0,
      id: r.meta?.last_row_id ?? null,
      linhas: r.results ?? [],
    }));
  }
}
