import { DriverD1 } from "./d1.ts";
import { DriverTurso } from "./turso.ts";
import type { Comando, Driver, Gravacao, Linha, Valor } from "./tipos.ts";
import type { Env } from "../tipos.ts";

/** Acima disso o pedido para: o plano grátis aceita 50 idas (subpedidos no Turso, consultas no D1) e a portaria usa uma. */
export const TETO_IDAS = 45;

export class ErroConfig extends Error {}

interface Pendente {
  cmd: Comando;
  chave: string;
  ok: (l: Linha[]) => void;
  falha: (e: unknown) => void;
}

/**
 * O banco de um pedido. As telas do Python fazem de 95 a 580 consultas; aqui as leituras pedidas no mesmo instante
 * (por exemplo dentro de um Promise.all) saem juntas numa ida só, e a mesma consulta repetida é lida uma vez.
 * Gravação (run/batch) é sempre uma ida, numa transação, e limpa o que foi lido antes.
 */
export class Banco {
  /** idas ao banco neste pedido (o teste de cada tela confere que ficam abaixo do limite) */
  idas = 0;
  /** comandos SQL executados (depois de juntar as repetidas) */
  comandos = 0;
  /**
   * Valores de parâmetros (id -> valor) que valem só neste pedido, sem gravar: o POST de Configurações confere as margens
   * com os números novos antes de gravar (no Python isso era UPDATE + conferência + desfazer).
   */
  sobreposicao: Map<number, { valor?: number | null; valor_texto?: string | null }> | null = null;
  private fila: Pendente[] = [];
  private agendado = false;
  private lidas = new Map<string, Promise<Linha[]>>();

  constructor(private driver: Driver, private teto = TETO_IDAS) {}

  private contar(n: number) {
    this.idas += 1;
    this.comandos += n;
    if (this.idas > this.teto) throw new Error(`Muitas idas ao banco neste pedido (${this.idas}); o limite grátis é 50.`);
  }

  /**
   * Linhas da consulta. São as mesmas para todos que pedem a mesma consulta, por isso vêm congeladas: quem quiser
   * mudar uma linha faz a sua cópia ({ ...linha }), como o dict(r) do Python. Copiar sempre custava CPU demais.
   */
  async query<T extends Linha = Linha>(sql: string, params: readonly Valor[] = []): Promise<T[]> {
    const chave = sql + "\u0000" + JSON.stringify(params);
    let p = this.lidas.get(chave);
    if (!p) {
      p = new Promise<Linha[]>((ok, falha) => this.fila.push({ cmd: { sql, params }, chave, ok, falha }));
      this.lidas.set(chave, p);
      this.agendar();
    }
    return (await p) as T[];
  }

  /** Primeira linha (ou undefined), como fetchone(). */
  async um<T extends Linha = Linha>(sql: string, params: readonly Valor[] = []): Promise<T | undefined> {
    return (await this.query<T>(sql, params))[0];
  }

  /** Primeira coluna da primeira linha, como fetchone()[0]. */
  async valor<T = Valor>(sql: string, params: readonly Valor[] = []): Promise<T | undefined> {
    const l = await this.um(sql, params);
    return l === undefined ? undefined : (Object.values(l)[0] as T);
  }

  async run(sql: string, params: readonly Valor[] = []): Promise<Gravacao> {
    return (await this.batch([{ sql, params }]))[0];
  }

  /**
   * Várias gravações numa ida só, tudo ou nada. O cache de leituras é limpo antes e também depois: uma leitura feita
   * enquanto a gravação estava no ar pode ter visto o valor antigo e não pode servir a quem lê depois do await.
   */
  async batch(cmds: Comando[]): Promise<Gravacao[]> {
    if (!cmds.length) return [];
    await this.esvaziar();
    this.lidas.clear();
    this.contar(cmds.length);
    try {
      return await this.driver.gravar(cmds);
    } finally {
      this.lidas.clear();
    }
  }

  private agendar() {
    if (this.agendado) return;
    this.agendado = true;
    // setTimeout(0): espera todas as funções do mesmo Promise.all pedirem suas consultas antes de ir ao banco
    setTimeout(() => void this.despachar(), 0);
  }

  private async esvaziar() {
    while (this.fila.length || this.agendado) await new Promise((r) => setTimeout(r, 0));
  }

  private async despachar() {
    this.agendado = false;
    const lote = this.fila;
    this.fila = [];
    if (!lote.length) return;
    try {
      this.contar(lote.length);
      const res = await this.driver.ler(lote.map((p) => p.cmd));
      lote.forEach((p, i) => {
        for (const l of res[i]) Object.freeze(l);
        p.ok(Object.freeze(res[i]) as Linha[]);
      });
    } catch (e) {
      lote.forEach((p) => {
        this.lidas.delete(p.chave);
        p.falha(e);
      });
    }
  }
}

/** Driver escolhido pela variável BANCO. Sem ela (ou com valor errado), erro: nunca adivinha qual banco usar. */
export function abrirBanco(env: Env): Banco {
  if (env.BANCO === "d1") return new Banco(new DriverD1(env.DB));
  if (env.BANCO === "turso") {
    if (!env.TURSO_DATABASE_URL || !env.TURSO_AUTH_TOKEN) throw new ErroConfig("BANCO=turso sem TURSO_DATABASE_URL e TURSO_AUTH_TOKEN.");
    return new Banco(new DriverTurso(env.TURSO_DATABASE_URL, env.TURSO_AUTH_TOKEN));
  }
  throw new ErroConfig("A variável BANCO precisa ser 'turso' ou 'd1' (painel do Cloudflare).");
}
