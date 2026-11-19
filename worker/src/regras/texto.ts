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
