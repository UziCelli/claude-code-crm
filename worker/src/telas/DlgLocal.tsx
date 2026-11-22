/** Pop-up "+ Novo local" e "Editar local" (port de _dlg_local.html), no fim da Grade, da Agenda e de Propostas. O app.js abre e preenche. */
import type { Child } from "hono/jsx";
import type { Contexto } from "./contexto.ts";

export function DlgLocal({ ctx, tipo, refGrade }: { ctx: Contexto; tipo?: string; refGrade?: number }): Child {
  return (
    <dialog id="dlg-local">
      <h2 data-titulo="">Novo local</h2>
      <p class="muted" data-so-novo="">Academia, condomínio, casa do aluno... Diga quanto custa dar aula lá: o motor monta os preços com isso.</p>
      <form method="post" action="/locais/novo">
        <input type="hidden" name="voltar" value="/grade" />
        <input type="hidden" name="nome_original" value="" />
        <div class="campo"><label>Nome do local</label><input name="nome" required autocomplete="off" placeholder="ex.: SmartFit Centro" /></div>
        <label class="muted" data-so-renomear="" hidden><input type="checkbox" name="atualizar_textos" value="1" checked /> Ao trocar o nome, trocar também nas contas e lançamentos (em aberto e pagos) que citam o local</label>
        <div class="form-grid">
          <div class="campo"><label>Taxa por aula (1 pessoa, R$)</label><input name="taxa_aula" inputmode="decimal" placeholder="0" /></div>
          <div class="campo" data-nao-cia=""><label>Taxa por pessoa a mais (R$/aula)</label><input name="taxa_pessoa_extra" inputmode="decimal" placeholder="0" /></div>
          <div class="campo" data-so-cia="" hidden><label>Aula com 2 pessoas (R$, total)</label><input name="taxa_2" inputmode="decimal" disabled /></div>
          <div class="campo" data-so-cia="" hidden><label>Aula com 3 pessoas (R$, total)</label><input name="taxa_3" inputmode="decimal" disabled /></div>
          <div class="campo"><label>Máximo de pessoas<span data-nao-cia=""> (0 = sem limite)</span></label><input name="max_pessoas" inputmode="numeric" placeholder="0" /></div>
          <div class="campo"><label>Deslocamento (R$ por aula)</label><input name="deslocamento" inputmode="decimal" placeholder="Uber, gasolina, estacionamento" /></div>
          <div class="campo"><label>Tempo de deslocamento (min por aula)</label><input name="tempo_deslocamento" inputmode="numeric" placeholder="ida e volta; entra no lucro/hora" /></div>
          <div class="campo"><label>Taxa mensal fixa (R$)</label><input name="taxa_mensal" inputmode="decimal" placeholder="0" /></div>
          <div class="campo"><label>Aulas por mês nesse local</label><input name="aulas_mes" inputmode="numeric" placeholder="para dividir a taxa mensal" /></div>
          <div class="campo" data-so-novo=""><label>Copiar a grade de</label><select name="referencia">{ctx.locaisRef.map((l) => <option selected={l === "CIA"}>{l}</option>)}</select></div>
        </div>
        <p class="muted" data-so-novo="">Todos os horários começam livres. Os preços saem destes custos + o seu salário/hora + o rateio dos custos fixos.</p>
        <div class="previa" data-previa="" data-tipo={tipo || ""} data-ref={String(refGrade || 0)} aria-live="polite" hidden></div>
        <div class="linha"><button class="verde" data-botao="">Criar local</button><button type="button" class="claro" data-fechar="">Cancelar</button></div>
      </form>
    </dialog>
  );
}
