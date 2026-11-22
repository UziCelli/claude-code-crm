import { createClient, type Client, type ResultSet } from "@libsql/client/web";
import type { Comando, Driver, Gravacao, Linha } from "./tipos.ts";

/** Turso por HTTP: client.batch() manda tudo num pedido só (um subpedido do Worker). */
export class DriverTurso implements Driver {
  private cliente: Client;

  constructor(url: string, token: string) {
    this.cliente = createClient({ url, authToken: token, intMode: "number" });
  }

  private static linhas(rs: ResultSet): Linha[] {
    return rs.rows.map((r) => {
      const o: Linha = {};
      rs.columns.forEach((nome, i) => (o[nome] = r[i] as Linha[string]));
      return o;
    });
  }

  private static stmts(cmds: Comando[]) {
    return cmds.map((c) => ({ sql: c.sql, args: [...(c.params ?? [])] }));
  }

  async ler(cmds: Comando[]): Promise<Linha[][]> {
    const res = await this.cliente.batch(DriverTurso.stmts(cmds), "read");
    return res.map(DriverTurso.linhas);
  }

  async gravar(cmds: Comando[]): Promise<Gravacao[]> {
    const res = await this.cliente.batch(DriverTurso.stmts(cmds), "write");
    return res.map((rs) => ({
      mudancas: rs.rowsAffected,
      id: rs.lastInsertRowid === undefined ? null : Number(rs.lastInsertRowid),
      linhas: DriverTurso.linhas(rs),
    }));
  }
}
