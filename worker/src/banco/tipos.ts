/** Camada de banco: a mesma interface para o Turso (HTTP) e o D1. O SQL é o mesmo do CRM em Python. */
export type Valor = string | number | null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Linha = Record<string, any>;
export interface Comando {
  sql: string;
  params?: readonly Valor[];
}
export interface Gravacao {
  /** linhas alteradas */
  mudancas: number;
  /** id da linha inserida (last_insert_rowid) */
  id: number | null;
  /** linhas devolvidas (RETURNING) */
  linhas: Linha[];
}
/** Cada chamada é UMA ida ao banco (um subpedido no Turso, uma consulta no D1). */
export interface Driver {
  /** Várias leituras de uma vez. */
  ler(cmds: Comando[]): Promise<Linha[][]>;
  /** Várias gravações numa transação: tudo ou nada. */
  gravar(cmds: Comando[]): Promise<Gravacao[]>;
}
