// Abre o <dialog> indicado e copia os data-* do botão para os campos do formulário.
document.addEventListener("click", function (e) {
  var b = e.target.closest("[data-abrir]");
  if (!b) return;
  var d = document.getElementById(b.dataset.abrir);
  if (!d) return;
  var frm = d.querySelector("form"); if (frm) frm.reset();
  // o reset volta ao atributo value: sem isto o id de uma edição anterior vazaria para o "Novo"
  d.querySelectorAll("input[type=hidden][name=id]").forEach(function (i) { i.value = ""; });
  Object.keys(b.dataset).forEach(function (k) {
    if (k === "abrir") return;
    var campo = d.querySelector("[name='" + k + "']");
    if (campo) campo.value = b.dataset[k];
  });
  var titulo = d.querySelector("[data-titulo]");
  if (titulo && b.dataset.titulo) titulo.textContent = b.dataset.titulo;
  d.showModal();
});
document.addEventListener("click", function (e) {
  if (e.target.matches("[data-fechar]")) e.target.closest("dialog").close();
});
// Confirmação em 1 clique para ações sensíveis
document.addEventListener("submit", function (e) {
  var f = e.target;
  if (f.dataset.confirmar && !confirm(f.dataset.confirmar)) e.preventDefault();
  if (e.defaultPrevented) return;
  // Botão ocupado: impede duplo envio. Desabilita depois do envio para o name/value do botão ir junto.
  var b = e.submitter || f.querySelector("button:not([type=button]), [type=submit]");
  if (!b) return;
  if (b.getAttribute("aria-busy") === "true") { e.preventDefault(); return; }
  b.setAttribute("aria-busy", "true");
  setTimeout(function () { b.disabled = true; }, 0);
  // se a página não trocar (download, erro de rede), libera de novo
  setTimeout(function () { b.disabled = false; b.removeAttribute("aria-busy"); }, 8000);
});
// Voltar pelo histórico (bfcache) não pode deixar botão travado
window.addEventListener("pageshow", function () {
  document.querySelectorAll("button[aria-busy='true']").forEach(function (b) { b.disabled = false; b.removeAttribute("aria-busy"); });
});
// Aviso de sucesso some sozinho; erro fica
document.querySelectorAll(".aviso.ok").forEach(function (a) {
  setTimeout(function () {
    a.classList.add("saindo");
    setTimeout(function () { a.remove(); }, 150); // = --dur-fast
  }, 4000);
});
// Celular: as regras de layout ficam no style.css (@media max-width: 760px); aqui só se marcam as tabelas e a grade.
// Tabelas comuns viram cartões: cada célula ganha o rótulo da coluna (data-rot), mostrado antes do valor.
document.querySelectorAll("main table:not(.grade)").forEach(function (t) {
  var cab = t.querySelector("thead tr") || t.rows[0];
  if (!cab || cab.querySelector("td")) return;   // sem linha de cabeçalho: fica como está
  var rotulos = [];
  Array.prototype.forEach.call(cab.cells, function (th) {
    for (var i = 0; i < (th.colSpan || 1); i++) rotulos.push(th.textContent.trim());
  });
  cab.classList.add("cab");
  Array.prototype.forEach.call(t.rows, function (tr) {
    if (tr === cab) return;
    var col = 0;
    Array.prototype.forEach.call(tr.cells, function (td) {
      if (td.colSpan > 1) td.classList.add("larga");
      else td.setAttribute("data-rot", rotulos[col] || "");
      col += td.colSpan || 1;
    });
  });
  t.classList.add("cartoes");
});

// Grade: no celular mostra um dia por vez (abre no dia de hoje; domingo abre na segunda).
document.querySelectorAll("table.grade").forEach(function (g) {
  var nomes = Array.prototype.map.call(g.rows[0].cells, function (th) { return th.textContent.trim().slice(0, 3); }).slice(1);
  var hoje = new Date().getDay();
  var escolher = function (d) {
    g.setAttribute("data-dia", d);
    abas.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.d == d); });
  };
  var abas = document.createElement("div");
  abas.className = "dias-celular";
  abas.setAttribute("role", "group");
  abas.setAttribute("aria-label", "Dia da grade");
  nomes.forEach(function (n, i) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "claro pequeno"; b.dataset.d = i + 1; b.textContent = n;
    b.addEventListener("click", function () { escolher(i + 1); });
    abas.appendChild(b);
  });
  (g.closest(".rolagem") || g).before(abas);
  escolher(hoje >= 1 && hoje <= nomes.length ? hoje : 1);
});
