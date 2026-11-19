import { env } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { abrirBanco, ErroConfig } from "../src/banco/banco.ts";
import { banco, semear } from "./apoio.ts";

beforeAll(semear);

describe("Banco: várias leituras numa ida só", () => {
  it("consultas pedidas juntas saem num lote", async () => {
    const b = banco();
    const grupos = ["fiscal", "previsao", "salario", "cobranca", "msg_dados"];
    const res = await Promise.all(grupos.map((g) => b.query("SELECT chave, valor FROM parametros WHERE grupo=?", [g])));
    expect(res.every((r) => r.length > 0)).toBe(true);
    expect(b.idas).toBe(1);
  });

  it("funções aninhadas também juntam: a profundidade é que conta", async () => {
    const b = banco();
    const conta = async (g: string) => (await b.query("SELECT count(*) AS n FROM parametros WHERE grupo=?", [g]))[0].n as number;
    const soma = async () => (await Promise.all(["fiscal", "previsao"].map(conta))).reduce((a, n) => a + n, 0);
    const [a, b2] = await Promise.all([soma(), conta("salario")]);
    expect(a).toBeGreaterThan(0);
    expect(b2).toBeGreaterThan(0);
    expect(b.idas).toBe(1);
  });

  it("a mesma consulta repetida é lida uma vez; as linhas vêm congeladas (quem muda faz a sua cópia)", async () => {
    const b = banco();
    const sql = "SELECT id, texto FROM rotina_tarefas ORDER BY id";
    const [x, y] = await Promise.all([b.query(sql), b.query(sql)]);
    expect(() => { x[0].texto = "mexido"; }).toThrow(TypeError);
    expect(y[0].texto).not.toBe("mexido");
    expect({ ...x[0], texto: "cópia" }.texto).toBe("cópia");
    expect(b.comandos).toBe(1);
  });

  it("valor() e um() imitam fetchone()", async () => {
    const b = banco();
    expect(await b.valor("SELECT count(*) AS n FROM rotina_tarefas")).toBeGreaterThan(0);
    expect(await b.um("SELECT * FROM clientes WHERE id=?", [999])).toBeUndefined();
  });
});

describe("Banco: gravação", () => {
  it("batch é tudo ou nada", async () => {
    const b = banco();
    await expect(
      b.batch([
        { sql: "INSERT INTO clientes (nome) VALUES (?)", params: ["Fica?"] },
        { sql: "INSERT INTO clientes (nome) VALUES (NULL)" }, // NOT NULL: falha
      ]),
    ).rejects.toThrow();
    expect(await b.valor("SELECT count(*) FROM clientes WHERE nome='Fica?'")).toBe(0);
  });

  it("run devolve id e linhas alteradas; a leitura seguinte vê a gravação", async () => {
    const b = banco();
    expect(await b.valor("SELECT count(*) FROM clientes")).toBe(0);
    const g = await b.run("INSERT INTO clientes (nome) VALUES (?)", ["Ana"]);
    expect(g.id).toBeGreaterThan(0);
    expect(g.mudancas).toBe(1);
    expect(await b.valor("SELECT count(*) FROM clientes")).toBe(1);
  });

  it("passou do teto de idas: erro claro em vez de estourar o limite do plano", async () => {
    const b = banco(2);
    await b.query("SELECT 1 AS um");
    await b.query("SELECT 2 AS dois");
    await expect(b.query("SELECT 3 AS tres")).rejects.toThrow(/Muitas idas/);
  });
});

describe("abrirBanco", () => {
  it("sem BANCO não adivinha", () => {
    expect(() => abrirBanco({ ...env, BANCO: undefined })).toThrow(ErroConfig);
    expect(() => abrirBanco({ ...env, BANCO: "turso", TURSO_DATABASE_URL: undefined })).toThrow(ErroConfig);
    expect(abrirBanco(env).idas).toBe(0);
  });
});
