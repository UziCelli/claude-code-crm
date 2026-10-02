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
});