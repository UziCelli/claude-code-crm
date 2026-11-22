/** Hoje e o mês atual (main.mes_atual), pelo relógio do Brasil. Num objeto, para os testes poderem trocar. */
import { hoje } from "../relogio.ts";

export const relogioMes = {
  hoje: (): string => hoje(),
  mesAtual: (): string => hoje().slice(0, 7),
};
