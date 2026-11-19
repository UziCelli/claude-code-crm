/**
 * HTML canônico, para comparar a tela do Worker com a do Python sem ligar para espaços, aspas, ordem de atributos,
 * comentários e escapes: cada tag vira "<nome a=1 b=2>", cada texto vira o texto com espaços simples.
 * Usar só em HTML gerado pelas duas versões do CRM (não é um parser completo).
 */
const ENT: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

export function decodificar(s: string): string {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e: string) => {
    if (e[0] === "#") return String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
    return ENT[e.toLowerCase()] ?? m;
  });
}

const espacos = (s: string) => s.replace(/\s+/g, " ").trim();
// fechamento opcional no HTML: <option>x é o mesmo que <option>x</option>
const FECHA_OPCIONAL = new Set(["option", "input", "br", "img", "meta", "link", "hr"]);

function tag(bruta: string, trocas: (nome: string, valor: string) => string): string {
  const m = /^<\s*(\/?)\s*([A-Za-z!][\w:-]*)([\s\S]*?)\/?\s*>$/.exec(bruta);
  if (!m) return bruta;
  const [, fecha, nome, resto] = m;
  if (fecha) return `</${nome.toLowerCase()}>`;
  const attrs: string[] = [];
  const re = /([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
  for (let a; (a = re.exec(resto)); ) {
    const n = a[1].toLowerCase();
    const v = decodificar(a[2] ?? a[3] ?? a[4] ?? "");
    attrs.push(`${n}=${JSON.stringify(trocas(n, v))}`);
  }
  attrs.sort();
  return `<${nome.toLowerCase()}${attrs.length ? " " + attrs.join(" ") : ""}>`;
}

/** Lista de pedaços canônicos. `trocas` deixa igualar valores que mudam por natureza (ex.: ?v= dos estáticos). */
export function canonico(html: string, trocas: (nome: string, valor: string) => string = (_, v) => v): string[] {
  const out: string[] = [];
  const re = /<!--[\s\S]*?-->|<(script|style)\b([^>]*)>([\s\S]*?)<\/\1\s*>|<[^>]+>|[^<]+/gi;
  for (let m; (m = re.exec(html)); ) {
    const s = m[0];
    if (s.startsWith("<!--")) continue;
    if (m[1]) {
      out.push(tag(`<${m[1]}${m[2]}>`, trocas));
      const corpo = espacos(m[3]);
      if (corpo) out.push(corpo);
      out.push(`</${m[1].toLowerCase()}>`);
    } else if (s.startsWith("<")) {
      const t = tag(s, trocas);
      if (!(t.startsWith("</") && FECHA_OPCIONAL.has(t.slice(2, -1)))) out.push(t);
    }
    else {
      const t = espacos(decodificar(s));
      if (t) out.push(t);
    }
  }
  return out;
}

/** Os estáticos levam ?v= diferente nas duas versões (data do arquivo x conteúdo): iguala. */
export const semVersao = (_: string, v: string) => v.replace(/\?v=[\w]+$/, "?v=*");
