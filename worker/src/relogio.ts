/**
 * Relógio do CRM: data e hora no fuso do Brasil (como app/relogio.py), em qualquer servidor.
 * Timestamps gravados pelo próprio SQL (datetime('now','localtime')) rodam no Turso/D1 em UTC, como já acontece hoje
 * no Render (as gravações vão ao Turso): continuam iguais, para os dois lados de uma comparação virem do mesmo relógio.
 */
const FUSO = "America/Sao_Paulo";
const formato = new Intl.DateTimeFormat("en-CA", {
  timeZone: FUSO, year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});

let fixo: Date | null = null;

/** Só nos testes: congela o relógio (null volta ao normal). */
export function definirAgora(d: Date | null): void {
  fixo = d;
}

/** "AAAA-MM-DD HH:MM:SS" no Brasil. */
export function agoraTxt(): string {
  const p = Object.fromEntries(formato.formatToParts(fixo ?? new Date()).map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
}

/** "AAAA-MM-DD" de hoje no Brasil. */
export function hoje(): string {
  return agoraTxt().slice(0, 10);
}
