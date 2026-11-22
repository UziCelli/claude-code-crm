/**
 * Configurações (port de main.py: configuracoes, configuracoes_salvar, _checar_margens, lista, vantagem e chave do Assistente).
 * O POST grava só o que mudou, numa ida só ao banco, e confere as margens com os números novos antes de gravar
 * (no Python eram 141 UPDATEs um por um: a causa do 503 no Render).
 */
import type { Hono } from "hono";
import type { Child } from "hono/jsx";
import { banco, type Ambiente } from "../app.ts";
import type { Banco } from "../banco/banco.ts";
import type { Comando, Linha } from "../banco/tipos.ts";
import { capitalizar, moeda, num, pct, reprFloat } from "../formato.ts";
import { arred } from "../arred.ts";
import { chaveSalva, info, removerChave, salvarChave, type InfoAssistente } from "../regras/assistente.ts";
import { GRUPOS_CONFIG, WA_ROTULOS } from "../regras/config.ts";
import { dasCompetencia, pctDas, textoPct, type Das } from "../regras/financeiro.ts";
import { nomes } from "../regras/locais.ts";
import { relogioMes } from "../regras/mes.ts";
import { LISTAS } from "../regras/parametros.ts";
import { carregarParametros, margemAlvo, type SalarioHora } from "../regras/precos.ts";
import { cobraPorAula, doLocal, lista as listaVantagens, MAX_LEQUE, texto as textoVantagem, type Vantagem } from "../regras/vantagens.ts";
import { Base } from "../telas/Base.tsx";
import { contextoBase, type Contexto } from "../telas/contexto.ts";
import { ErroValor, intPy, numBr, voltar } from "./util.ts";

/** Caminho da planilha no PC (db.PLANILHA). Na nuvem ela não existe: a importação pelo navegador entra na Fase 7. */
export const PLANILHA = "C:\\Users\\victo\\OneDrive\\Documentos\\Contabilidade.xlsx";
const GRUPO_VANTAGEM = "vantagem_indicacao";

export function waRotulo(modelo: string): string {
  return WA_ROTULOS[modelo] || capitalizar(modelo.replaceAll("_", " "));
}

/** O valor no campo da tela: % com 2 casas ou o número com 4, com vírgula (como o Jinja: round + str do float). */
export function valorCampo(valor: number, fmt: string): string {
  return reprFloat(fmt === "pct" ? arred(valor * 100, 2) : arred(valor, 4)).replaceAll(".", ",");
}

/** Margem mínima ou alvo + imposto + a maior taxa passam de 100%: o preço mínimo não existe. Devolve a frase do erro ou null. */
export async function checarMargens(b: Banco): Promise<string | null> {
  const p = await carregarParametros(b);
  const taxas = Object.values(p.taxas);
  const taxa = p.das + (taxas.length ? Math.max(...taxas) : 0);
  for (const [servico, m] of Object.entries(p.margens))
    if (m >= 1 || taxa + m >= 1) return `Margem mínima de ${servico} (${pct(m)}) + imposto e taxas passam de 100%. Use uma margem menor.`;
  for (const servico of new Set([...Object.keys(p.margens), ...Object.keys(p.margens_alvo)])) {
    const m = margemAlvo(p, servico);
    if (taxa + m >= 1) return `Margem alvo de ${servico} (${pct(m)}) + imposto e taxas passam de 100%. Use uma margem menor.`;
  }
  return null;
}

/**
 * As gravações do formulário de Configurações: só o que mudou. p_<id> = número (f_<id> diz se é %), t_<id> = texto
 * (só dos modelos e dos dados das mensagens). Número inválido: ErroValor com a frase do Python.
 */
export async function mudancasDoFormulario(b: Banco, form: Record<string, string>): Promise<{ cmds: Comando[]; valores: Map<number, number> }> {
  const atuais = new Map((await b.query<{ id: number; grupo: string; valor: number | null; valor_texto: string | null }>(
    "SELECT id, grupo, valor, valor_texto FROM parametros")).map((r) => [r.id, r]));
  const cmds: Comando[] = [];
  const valores = new Map<number, number>();
  for (const [k, v] of Object.entries(form)) {
    if (k.startsWith("p_") && v !== "") {
      const pid = intPy(k.slice(2));
      const fmt = form[`f_${pid}`] ?? "num";
      const val = numBr(v);
      const novo = fmt === "pct" ? val / 100 : val;
      const atual = atuais.get(pid);
      if (atual && !Object.is(atual.valor, novo)) {
        valores.set(pid, novo);
        cmds.push({ sql: "UPDATE parametros SET valor=? WHERE id=?", params: [novo, pid] });
      }
    } else if (k.startsWith("t_")) {
      const pid = intPy(k.slice(2));
      const novo = v.trim();
      const atual = atuais.get(pid);
      if (atual && (atual.grupo === "msg_whatsapp" || atual.grupo === "msg_dados") && atual.valor_texto !== novo)
        cmds.push({ sql: "UPDATE parametros SET valor_texto=? WHERE id=? AND grupo IN ('msg_whatsapp','msg_dados')", params: [novo, pid] });
    }
  }
  return { cmds, valores };
}

interface Grupo { grupo: string; titulo: string; fmt: string; itens: Linha[] }
interface Dados {
  grupos: Grupo[]; listas: [string, string, Linha[]][]; ultima: Linha | undefined; msgs: Linha[]; msgsDados: Linha[];
  vantagens: Vantagem[]; previa: { local: string; cobra: boolean; texto: string }[]; assistente: InfoAssistente;
  salario: SalarioHora; das: Das; dasTxt: string;
}

async function dadosDaTela(b: Banco, env: Ambiente["Bindings"]): Promise<Dados> {
  const sqlGrupo = "SELECT * FROM parametros WHERE grupo=? ORDER BY ordem, chave";
  const [porGrupo, porLista, ultima, msgs, msgsDados, leque, locais, salva, p, das, pctHoje] = await Promise.all([
    Promise.all(GRUPOS_CONFIG.map(([g]) => b.query(sqlGrupo, [g]))),
    Promise.all(LISTAS.map((k) => b.query("SELECT * FROM parametros WHERE grupo=? ORDER BY ordem", [k]))),
    b.um("SELECT * FROM importacoes ORDER BY id DESC LIMIT 1"),
    b.query("SELECT id, chave, valor_texto FROM parametros WHERE grupo='msg_whatsapp' ORDER BY ordem"),
    b.query("SELECT id, chave, valor_texto FROM parametros WHERE grupo='msg_dados' ORDER BY ordem"),
    listaVantagens(b), nomes(b), chaveSalva(b), carregarParametros(b),
    dasCompetencia(b, relogioMes.mesAtual()), pctDas(b, relogioMes.hoje()),
  ]);
  const previa = await Promise.all(locais.map(async (nome) => {
    const [cobra, opcoes] = await Promise.all([cobraPorAula(b, nome), doLocal(b, nome, leque)]);
    return { local: nome, cobra, texto: textoVantagem(opcoes) };
  }));
  return {
    grupos: GRUPOS_CONFIG.map(([grupo, titulo, fmt], i) => ({ grupo, titulo, fmt, itens: porGrupo[i] })).filter((g) => g.itens.length),
    listas: LISTAS.map((k, i) => [k, capitalizar(k.replace("lista_", "").replaceAll("_", " ")), porLista[i]]),
    ultima, msgs, msgsDados, vantagens: leque, previa, assistente: info(env, salva), salario: p.salario_hora!, das, dasTxt: textoPct(pctHoje),
  };
}

/** De onde sai o valor da hora (port de _salario_hora.html). */
export function SalarioHoraTxt({ sh }: { sh: SalarioHora }): Child {
  let corpo: Child;
  if (sh.usado)
    corpo = <>{"Salário por hora em uso: "}<strong>{moeda(sh.valor_hora)}</strong>{` = custos pessoais ${moeda(sh.custo_pessoal)}/mês (média de ${sh.meses} mês(es) da PF) ÷ ${num(sh.horas_base, 1)} h` +
      (sh.piso ? ` (agenda cheia: hoje você trabalha só ${num(sh.horas, 1)} h).` : " de trabalho no mês.")}</>;
  else if (sh.ligado)
    corpo = <>{"Salário por hora em uso: "}<strong>{moeda(sh.fixo)}</strong>{` (o fixo). O automático precisa de ${sh.custo_pessoal ? "alunos ativos" : "saídas pagas na PF nos últimos 3 meses"}.`}</>;
  else if (sh.fixo) corpo = <>{"Salário por hora em uso: "}<strong>{moeda(sh.fixo)}</strong>{" (fixo; valor_hora_auto = 0)."}</>;
  else corpo = "Regra do tempo desligada (valor_hora = 0): vale a mão de obra da planilha.";
  return <p class="muted" style="margin:8px 0 0">{corpo}</p>;
}

const ROTULOS_DADOS: Record<string, [string, string]> = {
  pix: ["Chave PIX", "CPF, e-mail, telefone ou chave aleatória"], link_avaliacao: ["Link para avaliação (Google, opcional)", "https://..."],
  vantagem: ["Vantagem da indicação", "uma avaliação física grátis"], pix_nome: ["Favorecido do PIX (nome da conta)", "Victor Celli"],
  pix_cidade: ["Cidade do PIX", "São Paulo"], pix_banco: ["Banco do PIX", "Nubank"],
};

function Tela({ ctx, d }: { ctx: Contexto; d: Dados }): Child {
  const dm = ctx.dadosMsg;
  return (
    <Base ctx={ctx} titulo="Configurações — VFITCOACH CRM">
      <h1>Configurações</h1>

      <div class="card">
        <div class="linha topo">
          <div>
            <h2>Planilha Contabilidade.xlsx</h2>
            <div class="muted">{`${PLANILHA} — NÃO encontrada. A planilha nunca é alterada; só lida.`}</div>
            {d.ultima && <div class="muted">Última importação: {d.ultima.data}</div>}
          </div>
          <form method="post" action="/importar" data-confirmar="Importar da planilha agora? Um backup é feito antes.">
            <button type="submit" disabled>Importar da planilha</button>
          </form>
        </div>
      </div>

      <div class="card mt">
        <h2>Assistente (chave da API)</h2>
        {d.assistente.origem === "env" ? <p>{`Ligado pela chave do .env (${d.assistente.final}). A chave do .env vence a salva aqui.`}</p>
          : d.assistente.origem === "config" ? <p>{`Ligado pela chave salva aqui (${d.assistente.final}).`}</p>
          : <p>Desligado.</p>}
        <form method="post" action="/configuracoes/assistente" class="linha">
          <input type="password" name="chave" autocomplete="off" placeholder="sk-ant-..." style="flex:1" />
          <button type="submit">Salvar chave</button>
        </form>
        {d.assistente.origem === "config" && (
          <form method="post" action="/configuracoes/assistente/remover" data-confirmar="Remover a chave do Assistente?" class="mt">
            <button class="perigo pequeno">Remover a chave</button>
          </form>
        )}
        <p class="muted mt">A chave fica no banco do CRM (vai junto para o Turso e os backups). Crie em console.anthropic.com › API Keys.</p>
      </div>

      <div class="card mt" id="cfg-das">
        <h2>Imposto (DAS)</h2>
        <p>{`DAS pela tabela do Simples (Anexo III): alíquota efetiva hoje ${d.dasTxt}% (faturamento dos últimos 12 meses: ${moeda(d.das.rbt12)}).`}</p>
        {d.das.base === "media" ? <p class="muted">{`Ainda não há 12 meses de uso: o valor é a média dos ${d.das.meses_base} meses anteriores × 12.`}</p>
          : d.das.base === "primeiro" ? <p class="muted">Primeiro mês com receita: o valor é a receita do mês × 12.</p>
          : d.das.base === "sem receita" ? <p class="muted">Sem receita lançada ainda: vale a primeira faixa (6%).</p> : null}
        <p class="muted">A alíquota sobe sozinha quando o faturamento muda de faixa. O DAS do mês passado é lançado em Contas a pagar, vence dia 20 (fim de semana antecipa para a sexta).</p>
      </div>

      <form method="post" action="/configuracoes" class="mt">
        <div class="grid c2">
          {d.grupos.map((g) => (
            <div class="card" id={`cfg-${g.grupo}`}>
              <h2>{g.titulo}</h2>
              {g.itens.map((it) => (
                <div class="campo linha">
                  <label style="flex:1;margin:0">{it.chave}</label>
                  <input type="hidden" name={`f_${it.id}`} value={g.fmt} />
                  <input name={`p_${it.id}`} class="num-curto" value={valorCampo(it.valor, g.fmt)} />
                  <span class="muted" style="width:18px">{g.fmt === "pct" ? "%" : ""}</span>
                </div>
              ))}
              {g.grupo === "mao_obra" && <><SalarioHoraTxt sh={d.salario} /><p><a href="/calculos">Ver a conta do lucro e todas as variáveis num lugar só</a></p></>}
            </div>
          ))}
        </div>
        <div class="card mt" id="cfg-msg_dados">
          <h2>Dados das mensagens</h2>
          <div class="muted">Entram no texto das mensagens. Vazio = some da mensagem.</div>
          {!(dm.pix && dm.pix_nome && dm.pix_cidade) && (
            <div class="aviso mt">Preencha a chave, o favorecido e a cidade do PIX para o cartão de cobrança sair com o QR Code (com o valor).</div>
          )}
          <div class="muted mt">{"A vantagem da indicação ({vantagem}) muda conforme o local do aluno: veja "}<a href="#cfg-vantagens">Vantagens da indicação</a>.</div>
          {d.msgsDados.filter((m) => m.chave !== "vantagem").map((m) => (
            <div class="campo"><label for={`t_${m.id}`}>{ROTULOS_DADOS[m.chave]?.[0] ?? m.chave}</label>
              <input id={`t_${m.id}`} name={`t_${m.id}`} value={m.valor_texto || ""} placeholder={ROTULOS_DADOS[m.chave]?.[1] ?? ""} /></div>
          ))}
        </div>
        <div class="card mt" id="cfg-msg_whatsapp">
          <h2>Mensagens de WhatsApp</h2>
          <div class="muted">{"Variáveis: "}<code>{"{nome}"}</code> <code>{"{data}"}</code> <code>{"{valor}"}</code> <code>{"{pix}"}</code> <code>{"{link_avaliacao}"}</code> <code>{"{vantagem}"}</code>.
            {" Na cobrança (texto do cartão com o QR Pix) também "}<code>{"{faltam}"}</code> <code>{"{dias}"}</code> <code>{"{total}"}</code>.
            {" Na renovação, "}<code>{"{valor}"}</code>{" já traz o desconto do crédito, se houver."}</div>
          {d.msgs.map((m) => (
            <div class="campo"><label>{waRotulo(m.chave)}</label><textarea name={`t_${m.id}`} rows={3}>{m.valor_texto ?? "None"}</textarea></div>
          ))}
        </div>
        <div class="mt"><button type="submit">Salvar parâmetros</button></div>
      </form>

      <div class="card mt" id="cfg-vantagens">
        <h2>Vantagens da indicação</h2>
        <div class="muted">{"Quem indica ganha uma destas. O CRM olha o local de quem indica: num local que cobra por aula (a CIA), as que "}
          <strong>gastam uma aula</strong>{` somem da mensagem. A mensagem mostra até ${MAX_LEQUE}, na ordem da lista.`}</div>
        {d.vantagens.length ? d.vantagens.map((v) => (
          <div class="linha" style="justify-content:space-between;padding:4px 0;border-top:1px solid var(--borda)">
            <span style="flex:1">{v.texto}</span>
            <form method="post" action={`/configuracoes/vantagem/${v.id}/marcar`} class="inline">
              <button class={`claro pequeno${v.gasta_aula ? " ativo" : ""}`} title="Clique para trocar">{v.gasta_aula ? "Gasta uma aula" : "Não gasta aula"}</button>
            </form>
            <form method="post" action={`/configuracoes/vantagem/${v.id}/remover`} class="inline" data-confirmar={`Remover '${v.texto}' das vantagens?`}><button class="claro pequeno">x</button></form>
          </div>
        )) : <div class="aviso mt">Nenhuma vantagem cadastrada: a mensagem de indicação sai sem a vantagem.</div>}
        <form method="post" action="/configuracoes/vantagem" class="linha mt" style="flex-wrap:wrap">
          <input name="texto" placeholder="ex.: uma camiseta" required style="flex:1 1 220px" />
          <label class="linha" style="margin:0;gap:4px"><input type="checkbox" name="gasta_aula" value="1" style="width:auto" /> gasta uma aula no local</label>
          <button class="pequeno">Adicionar</button>
        </form>
        <div class="mt">
          <div class="muted">Como a mensagem sai em cada local:</div>
          {d.previa.map((p) => (
            <div style="margin-top:6px"><strong>{p.local}</strong> <span class="muted">{`(${p.cobra ? "cobra por aula" : "não cobra por aula"})`}</span>{`: ${p.texto || "—"}`}</div>
          ))}
        </div>
      </div>

      <h2 class="mt">Listas</h2>
      <div class="grid c4">
        {d.listas.map(([grupo, titulo, itens]) => (
          <div class="card">
            <h3>{titulo}</h3>
            {itens.map((it) => (
              <div class="linha" style="justify-content:space-between;padding:3px 0">
                <span>{it.chave}</span>
                <form method="post" action={`/configuracoes/lista/${it.id}/remover`} class="inline" data-confirmar={`Remover '${it.chave}' da lista?`}><button class="claro pequeno">x</button></form>
              </div>
            ))}
            <form method="post" action="/configuracoes/lista" class="linha mt">
              <input type="hidden" name="grupo" value={grupo} />
              <input name="nome" placeholder="Novo item" required style="flex:1" />
              <button class="pequeno">Adicionar</button>
            </form>
          </div>
        ))}
      </div>
    </Base>
  );
}

/** Texto do formulário (o último valor de cada campo, como o FormData do Starlette). */
async function formulario(c: { req: { parseBody: () => Promise<Record<string, unknown>> } }): Promise<Record<string, string>> {
  const corpo = await c.req.parseBody();
  return Object.fromEntries(Object.entries(corpo).map(([k, v]) => [k, typeof v === "string" ? v : ""]));
}

export function rotasConfiguracoes(app: Hono<Ambiente>): void {
  app.get("/configuracoes", async (c) => {
    const b = banco(c);
    const [ctx, d] = await Promise.all([contextoBase(b, c.req.raw), dadosDaTela(b, c.env)]);
    return c.html(String(<Tela ctx={ctx} d={d} />));
  });

  app.post("/configuracoes", async (c) => {
    const b = banco(c);
    const form = await formulario(c);
    const destino = form.voltar === "/calculos" ? "/calculos" : "/configuracoes"; // lista fechada: nada de redirecionar para fora
    let cmds: Comando[];
    try {
      const m = await mudancasDoFormulario(b, form);
      cmds = m.cmds;
      if (m.valores.size) {
        b.sobreposicao = new Map([...m.valores].map(([id, valor]) => [id, { valor }]));
        const erro = await checarMargens(b);
        b.sobreposicao = null;
        if (erro) return voltar(c, destino, null, erro); // nada é gravado
      }
    } catch (e) {
      if (e instanceof ErroValor) return voltar(c, destino, null, e.message);
      throw e;
    }
    await b.batch(cmds);
    return voltar(c, destino, "Parâmetros salvos.");
  });

  app.post("/configuracoes/assistente", async (c) => {
    const chave = (await formulario(c)).chave?.trim() ?? "";
    if (!chave.startsWith("sk-ant-") || chave.length < 20)
      return voltar(c, "/configuracoes", null, "Chave inválida: ela começa com sk-ant- e é bem mais longa. Copie de novo em console.anthropic.com.");
    await salvarChave(banco(c), chave);
    return voltar(c, "/configuracoes", "Chave salva: o Assistente está ligado.");
  });

  app.post("/configuracoes/assistente/remover", async (c) => {
    await removerChave(banco(c));
    return voltar(c, "/configuracoes", "Chave do Assistente removida.");
  });

  app.post("/configuracoes/vantagem", async (c) => {
    const f = await formulario(c);
    const texto = (f.texto ?? "").split(/\s+/).filter(Boolean).join(" ");
    if (!texto) return voltar(c, "/configuracoes#cfg-vantagens", null, "Escreva a vantagem.");
    const g = await banco(c).run(`INSERT OR IGNORE INTO parametros (grupo, chave, valor, valor_texto, ordem)
      VALUES (?,?,?,?, (SELECT COALESCE(MAX(ordem),0)+1 FROM parametros WHERE grupo=?))`, [GRUPO_VANTAGEM, texto, f.gasta_aula ? 1 : 0, texto, GRUPO_VANTAGEM]);
    if (!g.mudancas) return voltar(c, "/configuracoes#cfg-vantagens", null, `'${texto}' já está na lista.`);
    return voltar(c, "/configuracoes#cfg-vantagens", `'${texto}' adicionada.`);
  });

  app.post("/configuracoes/vantagem/:pid{[0-9]+}/marcar", async (c) => {
    await banco(c).run("UPDATE parametros SET valor = CASE WHEN valor THEN 0 ELSE 1 END WHERE id=? AND grupo=?", [Number(c.req.param("pid")), GRUPO_VANTAGEM]);
    return voltar(c, "/configuracoes#cfg-vantagens", "Vantagem atualizada.");
  });

  app.post("/configuracoes/vantagem/:pid{[0-9]+}/remover", async (c) => {
    const b = banco(c);
    const pid = Number(c.req.param("pid"));
    const item = await b.um<{ chave: string }>("SELECT chave FROM parametros WHERE id=? AND grupo=?", [pid, GRUPO_VANTAGEM]);
    const cmds: Comando[] = [{ sql: "DELETE FROM parametros WHERE id=? AND grupo=?", params: [pid, GRUPO_VANTAGEM] }];
    if (item) cmds.push(marcarRemovido(GRUPO_VANTAGEM, item.chave)); // a vantagem inicial não volta quando o app abre de novo
    await b.batch(cmds);
    return voltar(c, "/configuracoes#cfg-vantagens", "Vantagem removida.");
  });

  app.post("/configuracoes/lista", async (c) => {
    const f = await formulario(c);
    if (!f.grupo || !f.nome) return c.text("Campo obrigatório faltando", 422);
    const nome = f.nome.trim();
    await banco(c).run(`INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem)
      VALUES (?,?,?, (SELECT COALESCE(MAX(ordem),0)+1 FROM parametros WHERE grupo=?))`, [f.grupo, nome, nome, f.grupo]);
    return voltar(c, "/configuracoes", `'${f.nome}' adicionado.`);
  });

  app.post("/configuracoes/lista/:pid{[0-9]+}/remover", async (c) => {
    const b = banco(c);
    const pid = Number(c.req.param("pid"));
    const item = await b.um<{ grupo: string; chave: string }>("SELECT grupo, chave FROM parametros WHERE id=? AND grupo LIKE 'lista_%'", [pid]);
    const cmds: Comando[] = [{ sql: "DELETE FROM parametros WHERE id=? AND grupo LIKE 'lista_%'", params: [pid] }];
    if (item) cmds.push(marcarRemovido(item.grupo, item.chave)); // item da lista inicial não volta quando o app abre de novo
    await b.batch(cmds);
    return voltar(c, "/configuracoes", "Item removido da lista.");
  });
}

/** db.marcar_removido: o item tirado da lista não volta na próxima abertura do app. */
export function marcarRemovido(grupo: string, nome: string): Comando {
  return { sql: "INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto, ordem) VALUES ('removido_lista', ?, ?, 0)", params: [`${grupo}|${nome}`, nome] };
}
