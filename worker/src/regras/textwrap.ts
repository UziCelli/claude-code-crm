/** textwrap.wrap do Python (CPython 3.13, com as opções padrão), para quebrar o texto do cartão nos mesmos pontos. */
const WP = String.raw`[\p{L}\p{N}_!"'&.,?]`;
const LT = String.raw`[\p{L}\p{Nl}\p{No}_]`;
const WS = String.raw`[\t\n\x0b\x0c\r ]`;
const NWS = String.raw`[^\t\n\x0b\x0c\r ]`;
const W = String.raw`[\p{L}\p{N}_]`;
const WORDSEP = new RegExp(`(${WS}+|(?<=${WP})-{2,}(?=${W})|${NWS}+?(?:-(?:(?<=${LT}{2}-)|(?<=${LT}-${LT}-))(?=${LT}-?${LT})|(?=${WS}|$)|(?<=${WP})(?=-{2,}${W})))`, "u");
const WORDSEP_SIMPLES = new RegExp(`(${WS}+)`, "u");
const PY_WS = /^[\s\x1c-\x1f\x85]*$/u;

const tam = (s: string) => Array.from(s).length;
const vazio = (s: string) => PY_WS.test(s); // s.strip() == ''

function expandirTabs(s: string, tab = 8): string {
  let out = "", col = 0;
  for (const ch of s) {
    if (ch === "\t") {
      const n = tab - (col % tab);
      out += " ".repeat(n);
      col += n;
    } else {
      out += ch;
      col = ch === "\n" || ch === "\r" ? 0 : col + 1;
    }
  }
  return out;
}

export function wrap(texto: string, largura: number, quebrarHifen = true): string[] {
  const munged = expandirTabs(texto).replace(/[\t\n\x0b\x0c\r]/g, " ");
  const pedacos = munged.split(quebrarHifen ? WORDSEP : WORDSEP_SIMPLES).filter((c) => c);
  const chunks = pedacos.reverse();
  const linhas: string[] = [];
  while (chunks.length) {
    const atual: string[] = [];
    let len = 0;
    if (vazio(chunks[chunks.length - 1]) && linhas.length) chunks.pop();
    while (chunks.length) {
      const l = tam(chunks[chunks.length - 1]);
      if (len + l <= largura) {
        atual.push(chunks.pop()!);
        len += l;
      } else break;
    }
    if (chunks.length && tam(chunks[chunks.length - 1]) > largura) {
      const espaco = largura < 1 ? 1 : largura - len;
      if (espaco > 0) {
        const chunk = Array.from(chunks[chunks.length - 1]);
        let fim = espaco;
        if (quebrarHifen && chunk.length > espaco) {
          const hifen = chunk.slice(0, espaco).lastIndexOf("-");
          if (hifen > 0 && chunk.slice(0, hifen).some((c) => c !== "-")) fim = hifen + 1;
        }
        atual.push(chunk.slice(0, fim).join(""));
        chunks[chunks.length - 1] = chunk.slice(fim).join("");
      } else if (!atual.length) atual.push(chunks.pop()!);
      len = atual.reduce((a, c) => a + tam(c), 0);
    }
    if (atual.length && vazio(atual[atual.length - 1])) {
      len -= tam(atual[atual.length - 1]);
      atual.pop();
    }
    if (atual.length) linhas.push(atual.join(""));
  }
  return linhas;
}

/** str.splitlines() do Python. */
export function splitlines(s: string): string[] {
  const partes = s.split(/\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/);
  if (partes.length && partes[partes.length - 1] === "") partes.pop();
  return partes;
}
