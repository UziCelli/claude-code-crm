/** O script da Grade (seleção de vários horários, seletores de aluno), igual ao de grade.html. */
export const SCRIPT_GRADE = `<script>
(function () {
  var tb = document.querySelector("table.grade"), dlg = document.getElementById("dlg-slot"), f = dlg.querySelector("form");
  var barra = document.getElementById("barra-sel"), btnModo = document.getElementById("modo-sel"), modo = false, ultima = null;
  var cels = Array.prototype.slice.call(tb.querySelectorAll("button.cel"));
  function marcados() { return cels.filter(function (c) { return c.classList.contains("sel"); }); }
  function marca(c, on) { c.classList.toggle("sel", on); c.setAttribute("aria-pressed", on); }
  function atualiza() {
    var n = marcados().length;
    document.getElementById("sel-txt").textContent = n + (n === 1 ? " horário selecionado" : " horários selecionados");
    barra.classList.toggle("on", n > 0);
  }
  function limpa() { cels.forEach(function (c) { marca(c, false); }); ultima = null; atualiza(); }
  function grupo(fn) {
    var g = cels.filter(fn), tudo = g.every(function (c) { return c.classList.contains("sel"); });
    g.forEach(function (c) { marca(c, !tudo); });
  }
  btnModo.addEventListener("click", function () {
    modo = !modo; btnModo.setAttribute("aria-pressed", modo); btnModo.classList.toggle("ativo", modo);
  });
  tb.addEventListener("click", function (e) {
    var c = e.target.closest("button.cel"), th = e.target.closest("th"), h = e.target.closest("td.hora");
    if (c && (modo || e.ctrlKey || e.metaKey)) {
      e.stopPropagation(); e.preventDefault();
      if (e.shiftKey && ultima) {
        var d1 = +ultima.dataset.dia, d2 = +c.dataset.dia, h1 = +ultima.dataset.hora, h2 = +c.dataset.hora;
        cels.forEach(function (x) {
          var d = +x.dataset.dia, hr = +x.dataset.hora;
          if (d >= Math.min(d1, d2) && d <= Math.max(d1, d2) && hr >= Math.min(h1, h2) && hr <= Math.max(h1, h2)) marca(x, true);
        });
      } else marca(c, !c.classList.contains("sel"));
      ultima = c; atualiza();
    } else if (modo && th && th.cellIndex > 0) {
      grupo(function (x) { return +x.dataset.dia === th.cellIndex; }); atualiza();
    } else if (modo && h) {
      grupo(function (x) { return +x.dataset.hora === parseInt(h.textContent, 10); }); atualiza();
    }
  }, true);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !dlg.open) limpa(); });
  document.getElementById("sel-limpar").addEventListener("click", limpa);
  document.getElementById("sel-editar").addEventListener("click", function () {
    var m = marcados(); if (!m.length) return;
    f.reset();
    m.forEach(function (c) {
      var i = document.createElement("input"); i.type = "hidden"; i.name = "celulas"; i.value = c.dataset.dia + "-" + c.dataset.hora; f.appendChild(i);
    });
    f.dia.value = 0; f.hora.value = 0;
    f.status.value = "";
    var nota = dlg.querySelector("[data-nota]"); nota.hidden = true; nota.textContent = "";
    dlg.querySelector("[data-titulo]").textContent = m.length + " horários selecionados — " + f.local.value;
    dlg.showModal();
  });
  dlg.addEventListener("close", function () {
    f.querySelectorAll('input[name="celulas"]').forEach(function (i) { i.remove(); });
  });
  // vários alunos no horário: um seletor por aluno (o 1º sempre; os outros com "+ outro aluno"), preenchidos com quem já está
  var sels = Array.prototype.slice.call(f.querySelectorAll('select[name="cliente_id"]')), mais = f.querySelector("[data-mais-aluno]");
  function mostraSels(n) {
    sels.forEach(function (s, i) { s.hidden = i >= Math.max(n, 1); });
    if (mais) mais.hidden = n >= sels.length;
  }
  if (mais) mais.addEventListener("click", function () {
    var n = sels.filter(function (s) { return !s.hidden; }).length; mostraSels(n + 1);
  });
  tb.addEventListener("click", function (e) {
    var c = e.target.closest("button.cel");
    if (!c || modo || e.ctrlKey || e.metaKey) return;
    setTimeout(function () {   // depois que o app.js preencheu o diálogo
      var ids = (c.dataset.alunos || "").split(",").filter(Boolean);
      while (sels.length < ids.length) {   // limite reduzido com a turma maior: um seletor para cada um, ninguém some ao salvar
        var novo = sels[0].cloneNode(true);
        novo.setAttribute("aria-label", (sels.length + 1) + "º aluno");
        sels[sels.length - 1].after(novo); sels.push(novo);
      }
      sels.forEach(function (s, i) { s.value = ids[i] || ""; });
      mostraSels(ids.length);
      f.dataset.quem = c.dataset.alunos ? c.dataset.quem : "";
    }, 0);
  });
  document.getElementById("sel-editar").addEventListener("click", function () { mostraSels(1); f.dataset.quem = ""; });
  f.addEventListener("submit", function (e) {   // Livre num horário com aluno na Agenda tira o horário dele: confirma antes
    if (f.status.value === "livre" && f.dataset.quem && !confirm("Tirar " + f.dataset.quem + " da Agenda nesse horário?")) e.preventDefault();
  });
})();
</script>`;
