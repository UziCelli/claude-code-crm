/**
 * Datas como o Python usa no CRM: textos ISO "AAAA-MM-DD" e meses "AAAA-MM".
 * Contas só com números (dias desde 1970-01-01), sem criar Date: é o caminho mais quente das telas do financeiro.
 */

const DIAS_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

export function bissexto(a: number): boolean {
  return (a % 4 === 0 && a % 100 !== 0) || a % 400 === 0;
}

export function ultimoDiaDoMes(ano: number, mes: number): number {
  return mes === 2 && bissexto(ano) ? 29 : DIAS_MES[mes - 1];
}

/** Dias desde 1970-01-01 (algoritmo days_from_civil, de Howard Hinnant). */
export function diaCivil(a: number, m: number, d: number): number {
  a -= m <= 2 ? 1 : 0;
  const era = Math.floor(a / 400);
  const yoe = a - era * 400;
  const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}

/** Inverso de diaCivil: [ano, mês, dia]. */
export function civil(z: number): [number, number, number] {
  z += 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp + (mp < 10 ? 3 : -9);
  return [yoe + era * 400 + (m <= 2 ? 1 : 0), m, d];
}

const RE_ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

/** date.fromisoformat estrito: o número do dia de uma "AAAA-MM-DD" válida, senão null. */
export function numeroDoDia(s: unknown): number | null {
  if (typeof s !== "string" || s.length !== 10) return null;
  const m = RE_ISO.exec(s);
  if (!m) return null;
  const a = +m[1], me = +m[2], d = +m[3];
  if (a < 1 || me < 1 || me > 12 || d < 1 || d > ultimoDiaDoMes(a, me)) return null;
  return diaCivil(a, me, d);
}

export function dataValida(s: unknown): boolean {
  return numeroDoDia(s) !== null;
}

export function isoDoDia(z: number): string {
  const [a, m, d] = civil(z);
  return `${zeros(a, 4)}-${m < 10 ? "0" : ""}${m}-${d < 10 ? "0" : ""}${d}`;
}

function exigir(data: string): number {
  const z = numeroDoDia(data);
  if (z === null) throw new RangeError(`data inválida: ${data}`);
  return z;
}

/** data ISO mais n dias (erro se a data for inválida, como no Python). */
export function somarDias(data: string, n: number): string {
  return isoDoDia(exigir(data) + n);
}

/** (b - a) em dias. */
export function diasEntre(a: string, b: string): number {
  return exigir(b) - exigir(a);
}

/** isoweekday(): 1 = segunda ... 7 = domingo (1970-01-01 foi quinta). */
export function diaDaSemana(data: string): number {
  return modPy(exigir(data) + 3, 7) + 1;
}

/** Divisão inteira e resto do Python (para negativos, // arredonda para baixo). */
export const divPy = (a: number, b: number) => Math.floor(a / b);
export const modPy = (a: number, b: number) => ((a % b) + b) % b;

/** f"{n:0Wd}" do Python: o sinal conta na largura ("-002"). */
export function zeros(n: number, largura: number): string {
  return n < 0 ? "-" + String(-n).padStart(largura - 1, "0") : String(n).padStart(largura, "0");
}

/** Sábado e domingo antecipam para a sexta (feriado não entra na conta). */
export function utilAnterior(data: string): string {
  const semana = diaDaSemana(data) - 1; // weekday() do Python: segunda = 0
  return somarDias(data, -Math.max(semana - 4, 0));
}
