/** Ajudas de texto que imitam o Python (unicodedata, str.split). */

/** unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode(): tira acentos e o que não é ASCII. */
export function semAcento(s: string): string {
  // eslint-disable-next-line no-control-regex
  return s.normalize("NFKD").replace(/[^\x00-\x7F]/g, "");
}

/** " ".join(s.split()): espaços repetidos viram um, sem espaço nas pontas. */
export function espacosSimples(s: string): string {
  return s.split(/\s+/).filter(Boolean).join(" ");
}

/** _sem_acento_low do Python: sem acento, sem espaços nas pontas, minúsculas. */
export function semAcentoLow(texto: string | null | undefined): string {
  return semAcento(texto ?? "").trim().toLowerCase();
}

/** \b do Python (Unicode): letra, número ou _ de qualquer alfabeto conta como parte da palavra. */
export function regexPalavra(fonte: string, flags = ""): RegExp {
  return new RegExp(`(?<![\\p{L}\\p{N}_])(?:${fonte})(?![\\p{L}\\p{N}_])`, flags.includes("u") ? flags : flags + "u");
}

/** re.escape do Python, para usar um texto qualquer dentro de uma expressão. */
export function escaparRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\\/-]/g, "\\$&");
}

/** float(x or 0) do Python: vazio, None e 0 viram 0. */
export function flt(x: unknown): number {
  return x === null || x === undefined || x === "" || x === 0 || x === false ? 0 : Number(x);
}
