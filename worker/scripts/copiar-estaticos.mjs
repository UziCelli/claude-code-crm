// Copia app/static (o mesmo visual do CRM em Python) para public/static e gera src/gerado/estaticos.ts
// com a etiqueta ?v= de cada arquivo (muda quando o conteúdo muda) e o logo. Roda antes de testar e publicar.
import { createHash } from "node:crypto";
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const raiz = join(dirname(fileURLToPath(import.meta.url)), "..");
const origem = join(raiz, "..", "app", "static");
const destino = join(raiz, "public", "static");
rmSync(destino, { recursive: true, force: true });
mkdirSync(destino, { recursive: true });
cpSync(origem, destino, { recursive: true });

const etiqueta = (arquivo) => createHash("sha256").update(readFileSync(join(origem, arquivo))).digest("hex").slice(0, 10);
const logo = readFileSync(join(raiz, "..", "app", "templates", "_logo.html"), "utf8").trim();
mkdirSync(join(raiz, "src", "gerado"), { recursive: true });
writeFileSync(join(raiz, "src", "gerado", "estaticos.ts"),
  "// Gerado por scripts/copiar-estaticos.mjs: não editar.\n" +
  `export const VERSOES: Record<string, string> = ${JSON.stringify({ "style.css": etiqueta("style.css"), "app.js": etiqueta("app.js") })};\n` +
  `export const LOGO_SVG = ${JSON.stringify(logo)};\n`);
console.log("estáticos copiados para public/static");
