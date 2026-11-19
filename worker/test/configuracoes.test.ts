import { env } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import cenarioConfig from "./dados/cenario-config.sql?raw";
import cenarioMotor from "./dados/cenario-motor.sql?raw";
import pythonHtml from "./paridade/configuracoes.html?raw";
import { definirAgora } from "../src/relogio.ts";
import { abrir, aviso, carregarCenario, enviar, semear } from "./apoio.ts";
import { canonico, semVersao } from "./html.ts";

const valor = async (sql: string, p: (string | number)[] = []) => (await env.DB.prepare(sql).bind(...p).first()) as Record<string, unknown> | null;
const idDe = async (grupo: string, chave: string) => (await valor("SELECT id FROM parametros WHERE grupo=? AND chave=?", [grupo, chave]))!.id as number;

beforeAll(async () => {
  definirAgora(new Date("2026-11-19T15:00:00Z"));
  await semear();
  await carregarCenario(cenarioMotor);
  await carregarCenario(cenarioConfig);
});
afterAll(() => definirAgora(null));

describe("GET /configuracoes", () => {
  it("o mesmo HTML do Python (sem os alertas do topo, que entram depois)", async () => {
    const r = await abrir("/configuracoes");
    expect(r.status).toBe(200);
    expect(canonico(await r.text(), semVersao)).toEqual(canonico(pythonHtml, semVersao));
  });
});

describe("POST /configuracoes (fim do 503: grava só o que mudou, numa ida)", () => {
  it("salvar a tela como está grava só os números que a tela arredonda; a 2ª vez não grava nada", async () => {
    const campos = async () => {
      const html = await (await abrir("/configuracoes")).text();
      return Object.fromEntries([...html.matchAll(/name="([pft]_\d+)"[^>]*value="([^"]*)"/g)].map((m) => [m[1], m[2]]));
    };
    const mudancas = async () => Number((await valor("SELECT total_changes() AS n"))!.n);
    const c1 = await campos();
    expect(Object.keys(c1).length).toBeGreaterThan(100);
    let antes = await mudancas();
    expect(aviso(await enviar("/configuracoes", c1)).msg).toBe("Parâmetros salvos.");
    expect(await mudancas() - antes).toBeLessThanOrEqual(5); // ex.: margem alvo 0.30000000000000004 vira 0.3, como no Python
    antes = await mudancas();
    expect(aviso(await enviar("/configuracoes", await campos())).msg).toBe("Parâmetros salvos.");
    expect(await mudancas()).toBe(antes);
  });

  it("voltar=/calculos volta para lá; endereço de fora não", async () => {
    const pid = await idDe("metas", "horas_vendaveis");
    let r = await enviar("/configuracoes", { voltar: "/calculos", [`p_${pid}`]: "120", [`f_${pid}`]: "num" });
    expect(r.status).toBe(303);
    expect(r.headers.get("location")).toMatch(/^\/calculos\?msg=/);
    expect((await valor("SELECT valor FROM parametros WHERE id=?", [pid]))!.valor).toBe(120);
    r = await enviar("/configuracoes", { voltar: "https://fora.com" });
    expect(r.headers.get("location")).toMatch(/^\/configuracoes/);
  });

  it("taxa com três casas sobrevive a salvar a tela", async () => {
    const pid = await idDe("taxa_cia", "1");
    await enviar("/configuracoes", { [`p_${pid}`]: "70,125", [`f_${pid}`]: "num" });
    expect(await (await abrir("/configuracoes")).text()).toContain('value="70,125"');
    expect((await valor("SELECT valor FROM parametros WHERE id=?", [pid]))!.valor).toBe(70.125);
  });

  it("recusa margem mínima que, com imposto e taxas, passa de 100%: nada é gravado", async () => {
    const pid = await idDe("margem_minima", "Pacote de Aulas");
    const outro = await idDe("metas", "cac_max");
    let r = await enviar("/configuracoes", { [`p_${outro}`]: "999", [`f_${outro}`]: "num", [`p_${pid}`]: "99", [`f_${pid}`]: "pct" });
    expect(aviso(r).erro).toBe("Margem mínima de Pacote de Aulas (99%) + imposto e taxas passam de 100%. Use uma margem menor.");
    expect((await valor("SELECT valor FROM parametros WHERE id=?", [pid]))!.valor).toBeCloseTo(0.15);
    expect((await valor("SELECT valor FROM parametros WHERE id=?", [outro]))!.valor).not.toBe(999);
    r = await enviar("/configuracoes", { [`p_${pid}`]: "20", [`f_${pid}`]: "pct" });
    expect(aviso(r).msg).toBe("Parâmetros salvos.");
    expect((await valor("SELECT valor FROM parametros WHERE id=?", [pid]))!.valor).toBeCloseTo(0.2);
  });

  it("número inválido: a mesma frase do Python e nada gravado", async () => {
    const pid = await idDe("metas", "cac_max");
    const r = await enviar("/configuracoes", { [`p_${pid}`]: "abc", [`f_${pid}`]: "num" });
    expect(aviso(r).erro).toBe("could not convert string to float: 'abc'");
  });

  it("dados das mensagens: salva sem espaços nas pontas; texto não grava em outro grupo; modelos salvam", async () => {
    const pix = await idDe("msg_dados", "pix");
    const link = await idDe("msg_dados", "link_avaliacao");
    const taxa = await idDe("taxa_pagamento", "PIX");
    const dupla = await idDe("msg_whatsapp", "dupla");
    const r = await enviar("/configuracoes", { [`t_${pix}`]: " 11999990000 ", [`t_${link}`]: "https://g.page/r/abc", [`t_${taxa}`]: "x",
      [`t_${dupla}`]: "Oi, {nome}! Vem treinar com alguém?" });
    expect(r.status).toBe(303);
    expect((await valor("SELECT valor_texto FROM parametros WHERE id=?", [pix]))!.valor_texto).toBe("11999990000");
    expect((await valor("SELECT valor_texto FROM parametros WHERE id=?", [link]))!.valor_texto).toBe("https://g.page/r/abc");
    expect((await valor("SELECT valor_texto FROM parametros WHERE id=?", [taxa]))!.valor_texto).toBeNull();
    expect((await valor("SELECT valor_texto FROM parametros WHERE id=?", [dupla]))!.valor_texto).toBe("Oi, {nome}! Vem treinar com alguém?");
  });

  it("a tela abre em poucas idas ao banco; salvar usa uma ida de gravação", async () => {
    expect(Number((await abrir("/configuracoes")).headers.get("x-crm-idas"))).toBeLessThanOrEqual(4);
    const pid = await idDe("metas", "cac_max");
    const r = await enviar("/configuracoes", { [`p_${pid}`]: "301", [`f_${pid}`]: "num" });
    expect(Number(r.headers.get("x-crm-idas"))).toBeLessThanOrEqual(5); // 1 leitura do formulário + 2 da conferência + 1 gravação
  });
});

describe("vantagens, listas e chave do Assistente", () => {
  it("vantagem: adiciona (espaços somem), marca, recusa repetida e remove sem voltar", async () => {
    let r = await enviar("/configuracoes/vantagem", { texto: "  um   squeeze ", gasta_aula: "" });
    expect(r.status).toBe(303);
    const v = (await valor("SELECT id, valor FROM parametros WHERE grupo='vantagem_indicacao' AND chave='um squeeze'"))!;
    expect(v.valor).toBe(0);
    await enviar(`/configuracoes/vantagem/${v.id}/marcar`);
    expect((await valor("SELECT valor FROM parametros WHERE id=?", [v.id as number]))!.valor).toBe(1);
    r = await enviar("/configuracoes/vantagem", { texto: "um squeeze" });
    expect(aviso(r).erro).toBe("'um squeeze' já está na lista.");
    await enviar(`/configuracoes/vantagem/${v.id}/remover`);
    expect(await valor("SELECT 1 FROM parametros WHERE id=? AND grupo='vantagem_indicacao'", [v.id as number])).toBeNull();
    expect(await valor("SELECT 1 FROM parametros WHERE grupo='removido_lista' AND chave='vantagem_indicacao|um squeeze'")).not.toBeNull();
  });

  it("marcar e remover vantagem não mexem em outro grupo", async () => {
    const pid = await idDe("taxa_cia", "2");
    const antes = (await valor("SELECT valor FROM parametros WHERE id=?", [pid]))!.valor;
    await enviar(`/configuracoes/vantagem/${pid}/marcar`);
    await enviar(`/configuracoes/vantagem/${pid}/remover`);
    expect((await valor("SELECT valor FROM parametros WHERE id=?", [pid]))!.valor).toBe(antes);
  });

  it("lista: adiciona e remove (o removido não volta)", async () => {
    let r = await enviar("/configuracoes/lista", { grupo: "lista_locais", nome: " Parque " });
    expect(aviso(r).msg).toBe("' Parque ' adicionado.");
    const it = (await valor("SELECT id FROM parametros WHERE grupo='lista_locais' AND chave='Parque'"))!;
    r = await enviar(`/configuracoes/lista/${it.id}/remover`);
    expect(aviso(r).msg).toBe("Item removido da lista.");
    expect(await valor("SELECT 1 FROM parametros WHERE grupo='removido_lista' AND chave='lista_locais|Parque'")).not.toBeNull();
  });

  it("chave do Assistente: recusa inválida, salva, mostra o final e remove", async () => {
    let r = await enviar("/configuracoes/assistente", { chave: "abc" });
    expect(aviso(r).erro).toMatch(/^Chave inválida/);
    r = await enviar("/configuracoes/assistente", { chave: " sk-ant-nova-chave-1234567890qrst " });
    expect(aviso(r).msg).toBe("Chave salva: o Assistente está ligado.");
    expect(await (await abrir("/configuracoes")).text()).toContain("Ligado pela chave salva aqui (…qrst).");
    await enviar("/configuracoes/assistente/remover");
    expect(await (await abrir("/configuracoes")).text()).toContain("<p>Desligado.</p>");
  });
});
