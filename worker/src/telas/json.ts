/** O filtro tojson do Jinja: json.dumps(sort_keys=True, ensure_ascii=True) e <, >, & e ' trocados por \uXXXX (seguro em atributo). */
import { reprFloat } from "../formato.ts";

function dumps(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (v === true) return "true";
  if (v === false) return "false";
  if (typeof v === "number") return Number.isInteger(v) && !Object.is(v, -0) ? String(v) : reprFloat(v);
  if (typeof v === "string") return JSON.stringify(v).replace(/[^\x20-\x7e]/g, (ch) => "\\u" + ch.charCodeAt(0).toString(16).padStart(4, "0"));
  if (Array.isArray(v)) return "[" + v.map(dumps).join(", ") + "]";
  const o = v as Record<string, unknown>;
  return "{" + Object.keys(o).sort().map((k) => dumps(k) + ": " + dumps(o[k])).join(", ") + "}";
}

export function tojson(v: unknown): string {
  return dumps(v).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026").replace(/'/g, "\\u0027");
}
