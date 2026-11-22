/** Contas automáticas (port de app/contas_auto.py). Por enquanto só o reconhecimento da conta da CIA; o resto entra com o Financeiro. */
import { semAcento } from "./texto.ts";

const RE_CIA = /\bcia\b|\b111\b|\bcreditos?\s+(?:d[aeo]s?\s+)?aulas?\b/;

/** O texto (descrição, contraparte) é a conta da CIA: 'CIA', '111' ou 'Crédito(s) de aula(s)', sem acento nem maiúsculas. */
export function ehCia(texto: string | null | undefined): boolean {
  return RE_CIA.test(semAcento(texto ?? "").toLowerCase());
}

/** O local é a CIA: 'CIA' no começo sem outra letra colada ('CIA', 'Cia 111', 'CIA2'); 'Ciagym' não. */
export function ehLocalCia(local: string | null | undefined): boolean {
  return /^cia(?![a-z])/.test(semAcento(local ?? "").trim().toLowerCase());
}
