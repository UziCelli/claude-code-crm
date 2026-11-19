/** O que toda tela recebe (port de main.render): listas, modelos de mensagem, dados das mensagens, locais e alertas. */
import type { Banco } from "../banco/banco.ts";
import type { Valor } from "../banco/tipos.ts";
import { referencias } from "../regras/locais.ts";
import { dadosMensagem, type DadosMsg } from "../regras/mensagens.ts";
import { parametros, todasAsListas, type Listas } from "../regras/parametros.ts";

export interface Acao {
  wa?: boolean;
  post?: string;
  dialogo?: string;
  rotulo?: string;
  href?: string;
  classe?: string;
  externo?: boolean;
  confirmar?: string;
  botao?: string;
  cartao?: Cartao | null;
  dados?: Record<string, unknown>;
}
export interface Cartao { acao: string; svg: string; codigo: string }
export interface Alerta {
  grav: number;
  cor: "vermelho" | "amarelo" | "azul";
  texto: string;
  url: string;
  tel?: string | null;
  modelo?: string | null;
  nome?: string | null;
  data?: string | null;
  extra?: Record<string, unknown> | null;
  botao?: string | null;
  acoes: Acao[];
  cartao?: Cartao | null;
}
export type { DadosMsg };

export interface Contexto {
  caminho: string;
  msg: string | null;
  erro: string | null;
  listas: Listas;
  modelos: Record<string, Valor>;
  dadosMsg: DadosMsg;
  locaisRef: string[];
  alertas: Alerta[];
}

/** Os alertas do topo (main.alertas) dependem das regras de alunos e do financeiro: entram quando elas forem portadas. */
export type CalcularAlertas = (b: Banco) => Promise<Alerta[]>;
let calcularAlertas: CalcularAlertas = async () => [];
export function definirAlertas(f: CalcularAlertas): void {
  calcularAlertas = f;
}

/** Tudo numa ida só ao banco (as consultas saem juntas no mesmo lote). */
export async function contextoBase(b: Banco, req: Request): Promise<Contexto> {
  const url = new URL(req.url);
  const [listas, modelos, dadosMsg, locaisRef, alertas] = await Promise.all([
    todasAsListas(b), parametros(b, "msg_whatsapp"), dadosMensagem(b), referencias(b), calcularAlertas(b),
  ]);
  return { caminho: url.pathname, msg: url.searchParams.get("msg"), erro: url.searchParams.get("erro"), listas, modelos, dadosMsg, locaisRef, alertas };
}
