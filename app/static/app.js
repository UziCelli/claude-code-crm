// Abre o <dialog> indicado e copia os data-* do botão para os campos do formulário (data-acao troca a action).
document.addEventListener("click", function (e) {
  var b = e.target.closest("[data-abrir]");
  if (!b) return;
  var d = document.getElementById(b.dataset.abrir);
  if (!d) return;
  var frm = d.querySelector("form"); if (frm) frm.reset();
  if (frm && !frm.dataset.padrao) frm.dataset.padrao = frm.getAttribute("action");
  if (frm) frm.action = b.dataset.acao || frm.dataset.padrao;   // diálogo que serve a vários registros (ex.: Dar baixa); sem data-acao volta ao original
  // o reset volta ao atributo value: sem isto o id de uma edição anterior vazaria para o "Novo"
  d.querySelectorAll("input[type=hidden][name=id]").forEach(function (i) { i.value = ""; });
  Object.keys(b.dataset).forEach(function (k) {
    if (k === "abrir") return;
    var campo = d.querySelector("[name='" + k + "']");
    if (campo) campo.value = b.dataset[k];
  });
  var titulo = d.querySelector("[data-titulo]");
  if (titulo && b.dataset.titulo) titulo.textContent = b.dataset.titulo;
  var nota = d.querySelector("[data-nota]");   // aviso opcional (ex.: "Crédito de R$ 100,00 descontado")
  if (nota) { nota.textContent = b.dataset.nota || ""; nota.hidden = !b.dataset.nota; }
  if (d.id === "dlg-local") {   // o mesmo pop-up cria e edita: na edição o nome trava e a referência some
    var editar = !!b.dataset.acao, nome = d.querySelector("[name=nome]"), bt = d.querySelector("[data-botao]");
    nome.readOnly = editar;
    if (!editar && titulo) titulo.textContent = "Novo local";
    if (bt) bt.textContent = editar ? "Salvar e refazer preços" : "Criar local";
    d.querySelectorAll("[data-so-novo]").forEach(function (x) { x.hidden = editar; });
  }
  // base do "cobre quantos meses?": a mensalidade cheia (data-mensal); sem ela, o valor do botão
  if (d.id === "dlg-pgto") d.dataset.mensal = b.dataset.mensal || b.dataset.valor || "";
  d.showModal();
  if (window.previaLocal) window.previaLocal(d, 0);   // pop-up do local / da CIA: mostra o preço com os números de agora
});
// Pop-up do local e da CIA: enquanto você digita, /locais/previa mostra como o custo vira preço (nada é gravado).
// Sem resposta (offline, erro), a caixa some e o Salvar continua funcionando.
(function () {
  var espera = null, pedido = 0;
  window.previaLocal = function (d, ms) {
    var box = d && d.querySelector("[data-previa]"), frm = box && box.closest("form");
    if (!box || !frm) return;
    clearTimeout(espera);
    espera = setTimeout(function () {
      var dados = new FormData(frm), meu = ++pedido;
      dados.set("tipo", box.dataset.tipo || "");
      dados.set("ref", box.dataset.ref || "0");
      if (box.dataset.cia) dados.set("cia", "1");
      fetch("/locais/previa", { method: "POST", body: dados, credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw r; return r.text(); })
        .then(function (html) { if (meu !== pedido) return; box.innerHTML = html; box.hidden = false; })
        .catch(function () { if (meu === pedido) box.hidden = true; });
    }, ms === undefined ? 350 : ms);
  };
  document.addEventListener("input", function (e) {
    var d = e.target.closest && e.target.closest("dialog");
    if (d && d.querySelector("[data-previa]")) window.previaLocal(d);
  });
})();
// Pagamento de aluno: valor digitado a partir de 1,5× a mensalidade sugere "cobre N meses" (a pessoa pode trocar)
(function () {
  function numero(t) {
    t = String(t || "").replace(/[^\d.,]/g, "");
    if (t.indexOf(",") >= 0) t = t.replace(/\./g, "").replace(",", ".");
    var n = parseFloat(t);
    return isFinite(n) ? n : 0;
  }
  // Vencido: o botão traz o total (data-valor) e a multa + juros (data-encargos). Valor digitado menor só por eles = pagou o Pix
  // antigo depois do vencimento: avisa quanto faltou e libera a caixa "Lançar a diferença a receber" (o servidor confere a conta).
  function diferenca(d) {
    var box = d.querySelector("[data-diferenca]"), campo = d.querySelector("[name=valor]");
    if (!box || !campo) return;
    var total = numero(d.dataset.total), enc = numero(d.dataset.encargos), v = numero(campo.value);
    var falta = Math.round((total - v) * 100) / 100;
    var mostra = total > 0 && enc > 0 && v > 0 && falta >= 0.01 && falta <= enc + 0.005;
    box.hidden = !mostra;
    box.querySelector("input[name=diferenca]").disabled = !mostra;
    if (mostra) box.querySelector("[data-diferenca-texto]").textContent =
      "Faltam R$ " + falta.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " de multa e juros.";
  }
  document.addEventListener("input", function (e) {
    var campo = e.target;
    if (!campo.matches || !campo.matches("#dlg-pgto [name=valor]")) return;
    var d = campo.closest("dialog"), sel = d.querySelector("select[name=meses]");
    diferenca(d);
    var mensal = numero(d.dataset.mensal), v = numero(campo.value);
    if (!sel || mensal <= 0 || sel.dataset.mexeu) return;   // quem escolheu à mão não é desfeito
    sel.value = v >= 1.5 * mensal ? String(Math.min(Math.max(Math.round(v / mensal), 1), 12)) : "1";
  });
  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches("#dlg-pgto select[name=meses]")) e.target.dataset.mexeu = "1";
  });
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-abrir=dlg-pgto]"), d = document.getElementById("dlg-pgto");
    if (!b || !d) return;
    var sel = d.querySelector("select[name=meses]");
    if (sel) delete sel.dataset.mexeu;   // diálogo reaberto: volta a sugerir
    d.dataset.total = b.dataset.encargos ? b.dataset.valor || "" : "";
    d.dataset.encargos = b.dataset.encargos || "";
    diferenca(d);
  });
})();
document.addEventListener("click", function (e) {
  if (e.target.matches("[data-fechar]")) e.target.closest("dialog").close();
});
// Link de alerta com ?abrir=saldos abre o diálogo dlg-saldos ao carregar (só diálogos "dlg-"; o parâmetro sai do endereço)
(function () {
  var q = new URLSearchParams(location.search), nome = q.get("abrir");
  var d = nome && /^[a-z]+$/.test(nome) ? document.getElementById("dlg-" + nome) : null;
  if (!d || !d.showModal) return;
  q.delete("abrir");
  history.replaceState(null, "", location.pathname + (q.toString() ? "?" + q : "") + location.hash);
  d.showModal();
})();
// Confirmação em 1 clique para ações sensíveis
document.addEventListener("submit", function (e) {
  var f = e.target;
  var msg = (e.submitter && e.submitter.dataset.confirmar) || f.dataset.confirmar;   // o botão pode ter a sua própria pergunta
  if (msg && !confirm(msg)) e.preventDefault();
  if (e.defaultPrevented) return;
  if (f.target === "_blank") return;   // abre em outra aba (menu WhatsApp): esta página não troca, o botão não pode ficar travado
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

// Menu WhatsApp da ficha: clicar fora fecha; escolher um item fecha (o formulário abre o WhatsApp em outra aba); "Cadastre o telefone" leva ao campo.
document.addEventListener("click", function (e) {
  var item = e.target.closest(".menu-wa-item");
  document.querySelectorAll("details.menu-wa[open]").forEach(function (m) {
    if (!m.contains(e.target) || item) setTimeout(function () { m.open = false; }, 0);   // depois do envio do formulário
  });
  if (item && item.matches("a[href='#telefone']")) {
    var t = document.getElementById("telefone");
    if (t) setTimeout(function () { t.focus(); }, 0);
  }
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") document.querySelectorAll("details.menu-wa[open]").forEach(function (m) { m.open = false; });
});

// Cobrança no WhatsApp: o cartão (SVG do servidor) vira PNG. No celular vai pelo compartilhar (imagem + código Pix de legenda);
// no PC copia o PNG para a área de transferência e o formulário abre o wa.me só com o código: na conversa é só Ctrl+V
// (o link do WhatsApp não aceita imagem). Sem área de transferência (navegador antigo ou bloqueou), baixa o PNG. O POST registra o evento.
(function () {
  var forms = document.querySelectorAll("form[data-cartao]");
  if (!forms.length) return;
  var celular = window.matchMedia && matchMedia("(pointer: coarse)").matches;
  var pngs = {};
  function gerar(url) {
    if (!pngs[url]) pngs[url] = fetch(url, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.blob(); })
      .then(function (svg) {
        return new Promise(function (ok, falha) {
          var img = new Image(), u = URL.createObjectURL(svg);
          img.onload = function () {
            setTimeout(function () {   // a fonte embutida termina de carregar
              var cv = document.createElement("canvas");
              cv.width = img.naturalWidth || 1080; cv.height = img.naturalHeight || 1600;
              cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
              URL.revokeObjectURL(u);
              cv.toBlob(function (b) { b ? ok(b) : falha(new Error("png")); }, "image/png");
            }, 150);
          };
          img.onerror = function () { URL.revokeObjectURL(u); falha(new Error("svg")); };
          img.src = u;
        });
      });
    return pngs[url];
  }
  function baixar(blob) {
    var a = document.createElement("a"), u = URL.createObjectURL(blob);
    a.href = u; a.download = "cobranca.png";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(u); }, 10000);
  }
  var prontos = {};
  function preparar(f) {   // prepara antes do clique: o compartilhar precisa sair no mesmo toque
    gerar(f.dataset.cartao).then(function (b) { prontos[f.dataset.cartao] = b; }).catch(function () {});
  }
  function enviado(f, texto) {
    var b = f.querySelector("button");
    if (b) b.textContent = texto || "Enviado ✓";
  }
  // PC: a imagem vai para a área de transferência no próprio clique (o navegador só deixa com o clique, em localhost ou https).
  // O ClipboardItem aceita a promessa do PNG: se ainda não ficou pronto, a cópia espera por ele sem perder o clique.
  function copiar(url) {
    if (!window.ClipboardItem || !navigator.clipboard || !navigator.clipboard.write) return Promise.reject(new Error("sem clipboard"));
    var png = prontos[url] || gerar(url);
    try {
      return navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
    } catch (erro) {
      return Promise.reject(erro);
    }
  }
  if ("IntersectionObserver" in window) {   // só gera quando aparece (os alertas também ficam no <details> do topo)
    var obs = new IntersectionObserver(function (vistos) {
      vistos.forEach(function (v) { if (v.isIntersecting) { obs.unobserve(v.target); preparar(v.target); } });
    });
    forms.forEach(function (f) { obs.observe(f); });
  } else forms.forEach(preparar);
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (!f.dataset || !f.dataset.cartao || e.defaultPrevented) return;
    var blob = prontos[f.dataset.cartao];
    var arq = blob && typeof File === "function" ? new File([blob], "cobranca.png", { type: "image/png" }) : null;
    if (celular && arq && navigator.canShare && navigator.canShare({ files: [arq] })) {
      e.preventDefault();
      navigator.share({ files: [arq], text: f.dataset.codigo || "" })
        .then(function () {
          return fetch(f.action, { method: "POST", body: new FormData(f), redirect: "manual", credentials: "same-origin" });
        })
        .then(function () { enviado(f); })
        .catch(function () { /* cancelou o compartilhar: nada registrado */ });
      return;
    }
    // PC (ou sem compartilhar arquivo): copia a imagem (Ctrl+V na conversa) e deixa o formulário abrir o wa.me com o código;
    // se não der para copiar, baixa a imagem como antes
    var url = f.dataset.cartao;
    copiar(url)
      .then(function () { enviado(f, "Copiada ✓ · Ctrl+V no WhatsApp"); })
      .catch(function () {
        (prontos[url] ? Promise.resolve(prontos[url]) : gerar(url)).then(baixar).catch(function () {});
        enviado(f);
      });
  }, true);
})();

// Copiar texto (ex.: código Pix copia-e-cola)
document.addEventListener("click", function (e) {
  var b = e.target.closest("[data-copiar]");
  if (!b) return;
  var texto = b.dataset.copiar, rotulo = b.textContent;
  function feito() { b.textContent = "Copiado!"; setTimeout(function () { b.textContent = rotulo; }, 1800); }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(texto).then(feito, function () { alert(texto); });
  } else {
    var t = document.createElement("textarea");
    t.value = texto; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    try { document.execCommand("copy"); feito(); } catch (err) { alert(texto); }
    t.remove();
  }
});
