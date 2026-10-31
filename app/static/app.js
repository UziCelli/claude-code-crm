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
  // classes do cabeçalho que valem para a coluna inteira: dest = o que importa (destaque), sec = detalhe (discreto)
  var tipos = [];
  Array.prototype.forEach.call(cab.cells, function (th) {
    var c = ["dest", "sec"].filter(function (k) { return th.classList.contains(k); });
    for (var i = 0; i < (th.colSpan || 1); i++) tipos.push(c);
  });
  cab.classList.add("cab");
  var n = 0;
  Array.prototype.forEach.call(t.rows, function (tr) {
    if (tr === cab) return;
    if (n++ % 2) tr.classList.add("par");   // linhas alternadas: o olho não pula de linha
    var col = 0, temSec = false;
    Array.prototype.forEach.call(tr.cells, function (td) {
      if (td.colSpan > 1) td.classList.add("larga");
      else {
        td.setAttribute("data-rot", rotulos[col] || "");
        (tipos[col] || []).forEach(function (k) { td.classList.add(k); });
        if ((tipos[col] || []).indexOf("sec") >= 0 && td.textContent.trim()) temSec = true;
      }
      col += td.colSpan || 1;
    });
    if (temSec) {   // celular: detalhes ficam guardados atrás de "+ detalhes"
      var mais = document.createElement("td");
      mais.className = "mais";
      mais.innerHTML = '<button type="button" class="claro pequeno" aria-expanded="false">+ detalhes</button>';
      tr.appendChild(mais);
    }
  });
  t.classList.add("cartoes");
});

// "+ detalhes" (celular) e régua de leitura: tocar/clicar numa linha a deixa marcada até tocar de novo
document.addEventListener("click", function (e) {
  var bt = e.target.closest("td.mais button");
  if (bt) {
    var aberto = bt.closest("tr").classList.toggle("aberto");
    bt.setAttribute("aria-expanded", aberto);
    bt.textContent = aberto ? "– menos" : "+ detalhes";
    return;
  }
  if (e.target.closest("a, button, input, select, textarea, label, summary, form")) return;
  var tr = e.target.closest("table.cartoes tr:not(.cab)");
  if (tr) tr.classList.toggle("foco");
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

// Assistente: manda a mensagem e mostra a resposta chegando aos pedaços (cada linha "data:" do fluxo é um evento JSON).
// No fim troca tudo pela versão formatada que o servidor guardou; erro que não foi guardado continua à vista.
(function () {
  var form = document.querySelector("form[data-chat]");
  if (!form) return;
  var lista = document.getElementById("chat-mensagens");
  var texto = form.querySelector("textarea");
  var botao = form.querySelector("button");
  var campo = form.querySelector("[name=conversa]");
  var rolar = function () { lista.scrollTop = lista.scrollHeight; };
  var novo = function (tag, classe, conteudo) {
    var e = document.createElement(tag);
    if (classe) e.className = classe;
    if (conteudo != null) e.textContent = conteudo;
    return e;
  };
  var crescer = function () { texto.style.height = "auto"; texto.style.height = Math.min(texto.scrollHeight, 160) + "px"; };
  // enquanto chega: escapa tudo e só troca **negrito**, títulos e marcadores (no fim vem a versão formatada do servidor)
  var formatar = function (t) {
    return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/^#{1,6} +(.*)$/gm, "<strong>$1</strong>")
      .replace(/^(\s*)[-*•] +/gm, "$1• ");
  };
  // o chat ocupa o que sobra da tela (com ou sem a faixa de alertas): só as mensagens rolam, a página não
  var chat = form.closest(".chat");
  var ajustar = function () {
    chat.style.height = Math.max(360, window.innerHeight - (chat.getBoundingClientRect().top + window.scrollY) - 12) + "px";
  };
  ajustar();
  window.addEventListener("resize", ajustar);
  document.querySelectorAll(".alertas-topo").forEach(function (d) { d.addEventListener("toggle", ajustar); });
  rolar();
  // a fonte chega depois e aumenta o texto: desce de novo até a última mensagem
  if (document.fonts) document.fonts.ready.then(function () { ajustar(); rolar(); });
  window.addEventListener("load", function () { ajustar(); rolar(); });
  texto.addEventListener("input", crescer);
  lista.addEventListener("click", function (e) {
    var s = e.target.closest("[data-sugestao]");
    if (!s || botao.disabled) return;
    texto.value = s.dataset.sugestao;
    form.requestSubmit();
  });
  // computador: Enter envia e Shift+Enter quebra a linha; no celular o Enter só quebra a linha (envia pelo botão)
  texto.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && window.matchMedia("(pointer: fine)").matches) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", function (e) {
    e.preventDefault();   // o envio é pelo fetch abaixo (e o aviso de botão ocupado do resto do CRM não entra)
    var msg = texto.value.trim();
    if (!msg || botao.disabled) return;
    var vazio = lista.querySelector(".chat-vazio");
    if (vazio) vazio.remove();
    var eu = novo("div", "msg eu");
    eu.appendChild(novo("div", "balao", msg));
    lista.appendChild(eu);
    var ele = novo("div", "msg ele"), balao = novo("div", "balao"), pensando = novo("div", "acao pensando", "Pensando");
    balao.appendChild(pensando);
    ele.appendChild(balao);
    lista.appendChild(ele);
    var dados = new FormData(form);
    texto.value = "";
    crescer();
    botao.disabled = true;
    botao.setAttribute("aria-busy", "true");
    rolar();
    var cid = campo.value, atual = null, soltos = [];
    var poe = function (el) { balao.insertBefore(el, pensando); };
    var tratar = function (ev) {
      if (ev.tipo === "conversa") {
        cid = String(ev.id);
        campo.value = cid;
        history.replaceState(null, "", "/assistente?c=" + cid);
      } else if (ev.tipo === "texto") {
        if (!atual) { atual = novo("div", "md chegando", ""); atual.bruto = ""; poe(atual); }
        atual.bruto += ev.texto;
        atual.innerHTML = formatar(atual.bruto);
      } else if (ev.tipo === "ferramenta") {
        atual = null;
        poe(novo("div", "acao", "… " + ev.texto));
      } else if (ev.tipo === "aviso" || ev.tipo === "erro") {
        atual = null;
        poe(novo("div", ev.tipo === "erro" ? "acao erro" : "acao aviso", ev.texto));
        if (!ev.guardado) soltos.push(ev.texto);
      }
      rolar();
    };
    fetch(form.action, { method: "POST", body: dados, headers: { Accept: "text/event-stream" } })
      .then(function (r) {
        if (!r.ok || !r.body) throw new Error("HTTP " + r.status);
        var leitor = r.body.getReader(), dec = new TextDecoder(), resto = "";
        var ler = function () {
          return leitor.read().then(function (p) {
            resto += dec.decode(p.value || new Uint8Array(0), { stream: !p.done });
            var blocos = resto.split("\n\n");
            resto = p.done ? "" : blocos.pop();
            blocos.forEach(function (b) {
              b.split("\n").forEach(function (linha) {
                if (linha.indexOf("data: ") !== 0) return;
                try { tratar(JSON.parse(linha.slice(6))); } catch (err) { /* linha incompleta: ignora */ }
              });
            });
            if (!p.done) return ler();
          });
        };
        return ler();
      })
      .catch(function () { tratar({ tipo: "erro", texto: "Sem resposta do CRM. Confira a conexão e mande de novo." }); })
      .then(function () {
        pensando.remove();
        botao.disabled = false;
        botao.removeAttribute("aria-busy");
        if (!cid) return;
        return fetch("/assistente/conversa/" + cid).then(function (r) {
          if (!r.ok) return;
          var custo = decodeURIComponent(r.headers.get("X-Custo") || "");
          var alvo = document.getElementById("custo-conversa");
          if (alvo) alvo.textContent = custo ? custo + " nesta conversa" : "";
          return r.text().then(function (html) {
            lista.innerHTML = html;
            soltos.forEach(function (t) { lista.appendChild(novo("div", "msg aviso-chat", t)); });
            rolar();
          });
        });
      })
      .catch(function () { /* a resposta já está na tela; a versão formatada volta ao recarregar */ })
      .then(function () { texto.focus({ preventScroll: true }); });
  });
})();
