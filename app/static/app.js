// Abre o <dialog> indicado e copia os data-* do botão para os campos do formulário.
document.addEventListener("click", function (e) {
  var b = e.target.closest("[data-abrir]");
  if (!b) return;
  var d = document.getElementById(b.dataset.abrir);
  if (!d) return;
  var frm = d.querySelector("form"); if (frm) frm.reset();
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