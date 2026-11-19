/**
 * Teste de risco da CPU (Fase 0): mede no V8 (o mesmo motor do Worker) o custo de CPU das partes de uma tela pesada,
 * no cenário 3x do financeiro (test/dados/cenario-financeiro.sql). Rodar: npm run cpu.
 * O tempo do banco não conta (no Worker é espera, não CPU): o driver daqui guarda as respostas e só o cálculo é medido.
 */
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { html } from "hono/html";
import { Banco } from "../src/banco/banco.ts";
import type { Comando, Driver, Gravacao, Linha } from "../src/banco/tipos.ts";
import { moeda, dataBr } from "../src/formato.ts";
import { definirAgora } from "../src/relogio.ts";
import { coberturaAdiantada, duplicados } from "../src/regras/financeiro.ts";
import { Base } from "../src/telas/Base.tsx";
import { contextoBase } from "../src/telas/contexto.ts";

const db = new DatabaseSync(":memory:");
for (const f of ["migrations/0001_inicial.sql", "test/dados/semente.sql", "test/dados/cenario-financeiro.sql"]) db.exec(readFileSync(f, "utf8"));

/** Driver que guarda as respostas: a partir da 2ª vez o banco não gasta nada; sobra o que o Worker faz com as linhas. */
class DriverGuardado implements Driver {
  cache = new Map<string, string>();
  async ler(cmds: Comando[]): Promise<Linha[][]> {
    return cmds.map((c) => {
      const k = c.sql + JSON.stringify(c.params);
      let j = this.cache.get(k);
      if (j === undefined) {
        j = JSON.stringify(db.prepare(c.sql).all(...((c.params ?? []) as (string | number | null)[])));
        this.cache.set(k, j);
      }
      return JSON.parse(j) as Linha[]; // a resposta do banco chega como texto: o Worker paga para ler
    });
  }
  async gravar(): Promise<Gravacao[]> {
    throw new Error("só leitura");
  }
}

async function medir(nome: string, f: () => Promise<unknown>, vezes = 30): Promise<number> {
  for (let i = 0; i < 5; i++) await f();
  const t: number[] = [];
  for (let i = 0; i < vezes; i++) {
    const c0 = process.cpuUsage();
    await f();
    const c = process.cpuUsage(c0);
    t.push((c.user + c.system) / 1000);
  }
  t.sort((a, b) => a - b);
  const med = t[Math.floor(t.length / 2)];
  console.log(`${nome.padEnd(44)} ${med.toFixed(2).padStart(6)} ms (CPU, mediana)`);
  return med;
}

definirAgora(new Date("2026-11-19T15:00:00Z"));
const driver = new DriverGuardado();
const req = new Request("https://crm.vfitcoachapp.com/financeiro");

const cob = await medir("cobertura adiantada x14 (Python: 20,0 ms)", async () => {
  const b = new Banco(driver);
  await Promise.all(Array.from({ length: 14 }, () => coberturaAdiantada(b, "2026-11")));
});
const dup = await medir("lançamentos repetidos (Python: 7,8 ms)", () => duplicados(new Banco(driver), new Set()));

// ler ~700 KB de linhas (o que /financeiro/painel lê no cenário 3x): JSON.parse + cópia das linhas
const todas = JSON.stringify(db.prepare("SELECT * FROM lancamentos").all());
const linhas700 = JSON.stringify(Array.from({ length: Math.ceil(700_000 / todas.length) }, () => JSON.parse(todas)).flat());
const ler = await medir(`ler ${(linhas700.length / 1024).toFixed(0)} KB de linhas do banco`, async () => {
  (JSON.parse(linhas700) as Linha[]).map((l) => ({ ...l }));
});

// HTML grande: a tabela do livro-caixa de /financeiro (332 KB no cenário 3x)
const lancs = db.prepare("SELECT * FROM lancamentos ORDER BY data, id").all() as Linha[];
const ctx = await contextoBase(new Banco(driver), req);
function Tabela({ itens }: { itens: Linha[] }) {
  return (
    <table class="tabela"><tbody>
      {itens.map((l) => (
        <tr>
          <td>{dataBr(l.data)}</td>
          <td>{l.descricao || "—"} <span class="tag neutro">{l.escopo}</span></td>
          <td>{l.categoria}</td><td>{l.contraparte || "—"}</td><td>{l.conta || "—"}</td><td>{l.forma || "—"}</td>
          <td class={`num v-${l.tipo}`}>{l.tipo === "entrada" ? "+" : "−"} {moeda(l.valor)}</td>
          <td><span class={`tag ${l.pago_em ? "verde" : "amarelo"}`}>{l.pago_em ? "pago" : "pendente"}</span></td>
          <td class="linha" style="flex-wrap:nowrap">
            {!l.pago_em && <button class="verde pequeno" data-abrir="dlg-baixa" data-acao={`/financeiro/lancamento/${l.id}/baixa`} data-titulo={`Dar baixa: ${l.descricao || l.categoria}`} data-conta={l.conta || ""}>Dar baixa</button>}
            <button class="claro pequeno" data-abrir="dlg-lanc" data-titulo="Editar lançamento" data-id={l.id} data-escopo={l.escopo} data-tipo={l.tipo} data-data={l.data} data-valor={String(l.valor)} data-categoria={l.categoria} data-descricao={l.descricao || ""} data-contraparte={l.contraparte || ""} data-cliente_id={l.cliente_id || ""} data-conta={l.conta || ""} data-forma={l.forma || ""} data-pago_em={l.pago_em || ""}>Editar</button>
            <form method="post" action={`/financeiro/lancamento/${l.id}/excluir`} class="inline" data-confirmar="Enviar este lançamento para a lixeira?"><input type="hidden" name="volta" value="mes=2026-11" /><button class="claro pequeno" aria-label="Excluir lançamento">x</button></form>
          </td>
        </tr>
      ))}
    </tbody></table>
  );
}
/** A mesma tabela com html`` do Hono (texto direto, sem árvore JSX): o jeito para listas grandes. */
const TabelaRapida = ({ itens }: { itens: Linha[] }) => html`<table class="tabela"><tbody>${itens.map((l) => html`<tr>
<td>${dataBr(l.data)}</td><td>${l.descricao || "—"} <span class="tag neutro">${l.escopo}</span></td><td>${l.categoria}</td><td>${l.contraparte || "—"}</td><td>${l.conta || "—"}</td><td>${l.forma || "—"}</td>
<td class="num v-${l.tipo}">${l.tipo === "entrada" ? "+" : "−"} ${moeda(l.valor)}</td><td><span class="tag ${l.pago_em ? "verde" : "amarelo"}">${l.pago_em ? "pago" : "pendente"}</span></td>
<td class="linha" style="flex-wrap:nowrap">${!l.pago_em ? html`<button class="verde pequeno" data-abrir="dlg-baixa" data-acao="/financeiro/lancamento/${l.id}/baixa" data-titulo="Dar baixa: ${l.descricao || l.categoria}" data-conta="${l.conta || ""}">Dar baixa</button>` : ""}
<button class="claro pequeno" data-abrir="dlg-lanc" data-titulo="Editar lançamento" data-id="${l.id}" data-escopo="${l.escopo}" data-tipo="${l.tipo}" data-data="${l.data}" data-valor="${String(l.valor)}" data-categoria="${l.categoria}" data-descricao="${l.descricao || ""}" data-contraparte="${l.contraparte || ""}" data-cliente_id="${l.cliente_id || ""}" data-conta="${l.conta || ""}" data-forma="${l.forma || ""}" data-pago_em="${l.pago_em || ""}">Editar</button>
<form method="post" action="/financeiro/lancamento/${l.id}/excluir" class="inline" data-confirmar="Enviar este lançamento para a lixeira?"><input type="hidden" name="volta" value="mes=2026-11"><button class="claro pequeno" aria-label="Excluir lançamento">x</button></form></td></tr>`)}</tbody></table>`;

const n = Math.round(lancs.length * 0.28);
let kbJsx = 0, kbHtml = 0;
const tJsx = await medir(`HTML com JSX (${n} linhas)`, async () => {
  kbJsx = String(<Base ctx={ctx}><Tabela itens={lancs.slice(0, n)} /></Base>).length / 1024;
});
const tHtml = await medir(`HTML com html\`\` na tabela (${n} linhas)`, async () => {
  kbHtml = String(<Base ctx={ctx}><TabelaRapida itens={lancs.slice(0, n)} /></Base>).length / 1024;
});
console.log(`  (${kbJsx.toFixed(0)} KB com JSX, ${kbHtml.toFixed(0)} KB com html\`\`)`);
const ratio = (19.98 + 7.83) / (cob + dup);
const porKb = tHtml / kbHtml;
console.log(`\nV8 x Python no mesmo cálculo: ${ratio.toFixed(1)}x mais rápido; HTML: ${(porKb * 100).toFixed(2)} ms por 100 KB`);
console.log("Estimativa por tela no cenário 3x (cálculo do Python ÷ fator + ler 700 KB de linhas + HTML):");
for (const [tela, calc, kb] of [["/financeiro/painel", 48.2, 66], ["/", 44.2, 48], ["/financeiro", 29.1, 332], ["/financeiro/previsao", 40.5, 109]] as const) {
  const est = calc / ratio + ler + porKb * kb;
  console.log(`  ${tela.padEnd(22)} ≈ ${est.toFixed(1)} ms de CPU (3x); ≈ ${(est / 3).toFixed(1)} ms no volume de hoje (limite 10 ms)`);
}
