/** Diálogos que vêm em toda tela (port de _dlg_pagamento, _dlg_estado, _dlg_premio e _dlg_oferta). O app.js abre e preenche. */
import type { Child } from "hono/jsx";
import { hoje } from "../relogio.ts";
import type { Contexto } from "./contexto.ts";

/** Pagamento de aluno (Mensalidades, ficha e alertas). Venda só mensal: sem "Cobre quantos meses?". */
export function DlgPagamento({ ctx, volta }: { ctx: Contexto; volta: string }): Child {
  const h = hoje();
  return (
    <dialog id="dlg-pgto">
      <h2 data-titulo="">Registrar pagamento</h2>
      <p class="muted" data-nota="" hidden></p>
      <form method="post" action="/financeiro/lancamento">
        <input type="hidden" name="escopo" value="PJ" /><input type="hidden" name="tipo" value="entrada" /><input type="hidden" name="cliente_id" value="" /><input type="hidden" name="volta" value={volta} /><input type="hidden" name="voltar" value="" />
        <div class="form-grid">
          <div class="campo"><label>Data</label><input name="data" type="date" value={h} required /></div>
          <div class="campo"><label>Valor (R$)</label><input name="valor" inputmode="decimal" required /></div>
          <div class="campo largo"><label>Categoria</label><select name="categoria" required>{ctx.listas.lista_categorias_pj.map((k) => <option selected={k === "Mensalidade (Aulas Presenciais)"}>{k}</option>)}</select></div>
          <div class="campo largo"><label>Descrição</label><input name="descricao" /></div>
          <div class="campo"><label>Conta</label><select name="conta"><option value="">—</option>{ctx.listas.lista_contas.map((k) => <option>{k}</option>)}</select></div>
          <div class="campo"><label>Forma</label><select name="forma"><option value="">—</option>{ctx.listas.lista_formas_lancamento.map((k) => <option>{k}</option>)}</select></div>
          <div class="campo largo"><label>Pago em (deixe vazio se ainda não caiu)</label><input name="pago_em" type="date" value={h} max={h} /></div>
        </div>
        <div class="aviso-diferenca" data-diferenca="" hidden>
          <p style="margin:0 0 6px" data-diferenca-texto=""></p>
          <label class="linha" style="gap:8px;align-items:flex-start;flex-wrap:nowrap;margin:0;font-weight:400"><input type="checkbox" name="diferenca" value="1" checked disabled style="width:auto;margin-top:3px" /><span>Lançar a diferença a receber, para cobrar depois</span></label>
        </div>
        <div class="linha"><button class="verde">Salvar</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
      </form>
    </dialog>
  );
}

/** Crédito na próxima e Pulou o mês (soluções do estado do aluno). */
export function DlgEstado(): Child {
  return (
    <>
      <dialog id="dlg-credito">
        <h2>Crédito na próxima</h2>
        <p class="muted" data-titulo=""></p>
        <form method="post" action="">
          <input type="hidden" name="voltar" value="" /><input type="hidden" name="mes" value="" />
          <div class="campo"><label>Valor do crédito (R$)</label><input name="valor" inputmode="decimal" required /></div>
          <p class="muted">Sugerido pelas aulas não usadas; pode mudar. Sai sozinho do próximo pagamento do aluno.</p>
          <div class="linha"><button class="verde">Dar crédito</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
        </form>
      </dialog>
      <dialog id="dlg-pulou">
        <h2>Pulou o mês</h2>
        <p data-titulo=""></p>
        <form method="post" action="">
          <input type="hidden" name="voltar" value="" />
          <div class="linha"><button class="verde">Pulou o mês</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
        </form>
      </dialog>
    </>
  );
}

/** Presente da indicação: é presente, nunca desconto. */
export function DlgPremio(): Child {
  return (
    <dialog id="dlg-presente">
      <h2>Registrar presente</h2>
      <p class="muted" data-titulo=""></p>
      <form method="post" action="">
        <input type="hidden" name="voltar" value="" />
        <div class="campo"><label>O que você deu?</label><input name="o_que" list="presentes" placeholder="ex.: Camiseta" autocomplete="off" required />
          <datalist id="presentes">{["Avaliação física", "Camiseta", "Garrafa", "Treino extra para casa"].map((p) => <option value={p} />)}</datalist></div>
        <div class="campo"><label>Custo (R$, se quiser anotar)</label><input name="custo" inputmode="decimal" placeholder="opcional" /></div>
        <div class="campo"><label>Data</label><input name="data" type="date" value={hoje()} required /></div>
        <p class="muted">Só presente: não vira desconto nem crédito.</p>
        <div class="linha"><button class="verde">Registrar presente</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
      </form>
    </dialog>
  );
}

const SCRIPT_OFERTA = `
// o app.js cuida do resto (action, título, nota); aqui só o valor em destaque do "Aceitou"
document.addEventListener("click", function (e) {
  var b = e.target.closest("[data-abrir='dlg-oferta-aceitou']");
  var n = document.querySelector("#dlg-oferta-aceitou [data-novo]");
  if (b && n) n.textContent = b.dataset.novo || "";
});
`;

/** Ofertas de upsell: Aceitou e fim do valor da oferta. */
export function DlgOferta(): Child {
  return (
    <>
      <dialog id="dlg-oferta-aceitou">
        <h2>Aceitou a oferta</h2>
        <p data-titulo=""></p>
        <form method="post" action="">
          <input type="hidden" name="voltar" value="" />
          <label class="linha" style="gap:8px;align-items:flex-start;margin:8px 0"><input type="checkbox" name="atualizar" value="1" checked style="width:auto;margin-top:3px" /><span>Atualizar a mensalidade para <strong data-novo=""></strong></span></label>
          <p class="muted" data-nota="" hidden></p>
          <div class="linha"><button class="verde">Aceitou</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
        </form>
      </dialog>
      <dialog id="dlg-oferta-encerrar">
        <h2>Fim do valor da oferta</h2>
        <p data-titulo=""></p>
        <form method="post" action="">
          <input type="hidden" name="voltar" value="" />
          <div class="linha"><button class="verde">Atualizar valor</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
        </form>
      </dialog>
      <script dangerouslySetInnerHTML={{ __html: SCRIPT_OFERTA }} />
    </>
  );
}
