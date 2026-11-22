import jsQR from "jsqr";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import cenario from "./dados/cenario-alunos.sql?raw";
import py from "./paridade/cartao-ofertas.json";
import { estado } from "../src/regras/alunos.ts";
import { qrCaminho, svg } from "../src/regras/cartao.ts";
import { cobrancaAtual, diferencaCartao, pendenciaDiferenca } from "../src/regras/cobranca.ts";
import { diferencas } from "../src/regras/financeiro.ts";
import * as indicacoes from "../src/regras/indicacoes.ts";
import { dadosMensagem } from "../src/regras/mensagens.ts";
import * as ofertas from "../src/regras/ofertas.ts";
import { parametros } from "../src/regras/parametros.ts";
import { wrap } from "../src/regras/textwrap.ts";
import { definirAgora } from "../src/relogio.ts";
import { banco, carregarCenario, jsonavel, semear } from "./apoio.ts";

const HOJE = "2026-11-19";
beforeAll(async () => {
  definirAgora(new Date("2026-11-19T15:00:00Z"));
  await semear();
  await carregarCenario(cenario);
});
afterAll(() => definirAgora(null));

/** O QR é de outra biblioteca (uqr x segno): compara o resto do SVG e lê o QR para conferir o conteúdo. */
const semQr = (s: string) => s.replace(/<path transform="translate\([^)]*\) scale\([^)]*\)" d="[^"]*"/, "<path QR");

function lerQr(conteudo: string): string | null {
  const [caminho, lado] = qrCaminho(conteudo);
  const escala = 4, borda = 4, n = (lado + 2 * borda) * escala;
  const px = new Uint8ClampedArray(n * n * 4).fill(255);
  for (const m of caminho.matchAll(/M(\d+) (\d+)h1v1h-1z/g)) {
    const x0 = (Number(m[1]) + borda) * escala, y0 = (Number(m[2]) + borda) * escala;
    for (let y = y0; y < y0 + escala; y++) for (let x = x0; x < x0 + escala; x++) px.fill(0, (y * n + x) * 4, (y * n + x) * 4 + 3);
  }
  return jsQR(px, n, n)?.data ?? null;
}

describe("cartão de cobrança igual ao Python", () => {
  it("cobranças do dia: mesmo SVG (fora o desenho do QR) e o QR lê o mesmo código Pix", async () => {
    const b = banco();
    const [est, modelos, dados, par, clientes] = await Promise.all([estado(b, HOJE), parametros(b, "msg_whatsapp"), dadosMensagem(b),
      parametros(b, "cobranca"), b.query("SELECT * FROM clientes")]);
    const porId = new Map(clientes.map((c) => [c.id as number, c]));
    for (const [cid, codigo, esperado] of py.cartoes as [number, string, string][]) {
      const e = est.get(cid)!;
      const ca = cobrancaAtual(porId.get(cid) as never, { efetiva: e.renovacao!.efetiva, vence: e.renovacao!.vence, cob: e.cobranca, credito: e.credito },
        HOJE, modelos, dados)!;
      expect(ca.codigo, `aluno ${cid}`).toBe(codigo);
      expect(semQr(svg(ca, par)), `aluno ${cid}`).toBe(semQr(esperado));
      expect(lerQr(ca.codigo)).toBe(codigo);
    }
  });

  it("diferença de multa e juros: cartão e pendência", async () => {
    const b = banco();
    const [difs, modelos, dados, clientes] = await Promise.all([diferencas(b), parametros(b, "msg_whatsapp"), dadosMensagem(b), b.query("SELECT * FROM clientes")]);
    const porId = new Map(clientes.map((c) => [c.id as number, c]));
    for (const [cid, codigo, esperado] of py.dif_cartoes as [number, string, string][]) {
      const ca = diferencaCartao(porId.get(cid) as never, difs.get(cid)!, dados, modelos);
      expect(ca.codigo).toBe(codigo);
      expect(semQr(svg(ca)), `aluno ${cid}`).toBe(semQr(esperado));
    }
    for (const [cid, esperado] of Object.entries(py.pendencias))
      expect(jsonavel(pendenciaDiferenca(porId.get(Number(cid)) as never, difs.get(Number(cid))!, dados))).toEqual(esperado);
  });

  it("quebra de linha igual ao textwrap do Python", () => {
    for (const [t, w, r] of py.wrap as [string, number, string[]][]) expect(wrap(t, w, w !== 62), `${w}: ${t}`).toEqual(r);
  });
});

describe("ofertas e indicações iguais ao Python", () => {
  it("indicações", async () => {
    expect(jsonavel(await indicacoes.pendentes(banco()))).toEqual(py.indicacoes_pendentes);
    for (const [cid, r] of Object.entries(py.indicacoes_do_aluno)) expect(jsonavel(await indicacoes.doAluno(banco(), Number(cid))), cid).toEqual(r);
    for (const [cid, r] of Object.entries(py.quem_indicou)) expect(await indicacoes.quemIndicou(banco(), Number(cid))).toEqual(r);
    const primeiro = Number(Object.keys(py.quem_indicou)[0]);
    expect(jsonavel(await indicacoes.alunosParaEscolher(banco(), primeiro))).toEqual(py.escolher);
  });

  it("ofertas: ativas, situação do aluno, texto, elegíveis, descontos acabando e validação", async () => {
    expect(jsonavel(await ofertas.ativas(banco(), HOJE))).toEqual(py.ofertas_ativas);
    for (const [cid, r] of Object.entries(py.situacao)) expect(jsonavel(await ofertas.situacaoAluno(banco(), Number(cid), HOJE)), cid).toEqual(r);
    expect((await ofertas.todas(banco())).map((o) => ofertas.texto(o, "Ana"))).toEqual(py.texto_oferta);
    expect((await ofertas.pendentes(banco(), HOJE)).map((p) => [p.oferta.id, p.elegiveis.map((e) => e.id)])).toEqual(py.pendentes_oferta);
    expect(jsonavel(await ofertas.descontosAcabando(banco(), HOJE))).toEqual(py.descontos_acabando);
    const args = [["", "x", "1", "0,5", "", ""], ["T", "", 1, 1, "", ""], ["T", "I", "abc", "1", "", ""], ["T", "I", "0", "1", "", ""],
      ["T", "I", "100", "100", "", ""], ["T", "I", "100", "80", "37", ""], ["T", "I", "100", "80", "x", ""], ["T", "I", "100", "80", "3", "2026-02-30"],
      [" Treino  dupla ", " inclui ", "1.500", "1.200,50", " 12 ", "2026-12-01"]];
    args.forEach((a, i) => expect(ofertas.validar(...(a as [unknown, unknown, unknown, unknown, unknown, unknown])), String(i)).toEqual(py.validar[i]));
  });
});
