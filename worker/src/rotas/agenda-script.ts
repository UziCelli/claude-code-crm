/** O script da Agenda (janelinha do horário, incluir aula, marcar várias), igual ao de agenda.html. */
export const SCRIPT_AGENDA = `<script>
(function () {
  // janelinha do horário: monta a parte de cima (marcar cada aluno) a partir do data-info do card e preenche o seletor de baixo.
  // Abre aqui mesmo (sem data-abrir): o app.js zeraria o 1º formulário depois do preenchimento.
  var dlg = document.getElementById("dlg-horario"), lista = document.getElementById("h-alunos"), titulo = document.getElementById("h-titulo");
  var fh = document.getElementById("f-horario"), a1 = fh.elements.aluno1, a2 = fh.elements.aluno2, loc = fh.elements.local;
  var COR = {feita: "verde", faltou: "vermelho", desmarcou: "amarelo", cancelada: "neutro"};
  var localMexido = false;

  function el(tag, cls, texto) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (texto != null) e.textContent = texto;
    return e;
  }
  function oculto(form, nome, valor) {
    var i = document.createElement("input");
    i.type = "hidden"; i.name = nome; i.value = valor == null ? "" : valor;
    form.appendChild(i);
  }
  function contexto(form) {   // aluno e mês do painel de controle (se aberto) voltam junto
    if (fh.elements.aluno) { oculto(form, "aluno", fh.elements.aluno.value); oculto(form, "mes", fh.elements.mes.value); }
  }
  function botao(texto, cls, estado) {
    var b = el("button", cls, texto);
    if (estado != null) { b.name = "estado"; b.value = estado; }
    return b;
  }
  function blocoAluno(a, info) {
    var bloco = el("div", "h-aluno"), marcada = a.estado in COR;
    var quem = el("div", "h-quem");
    quem.appendChild(el("strong", null, a.nome));
    if (a.reposicao) quem.appendChild(el("span", "tag azul", "reposição"));
    else if (a.avulsa) quem.appendChild(el("span", "tag azul", "avulsa"));
    if (a.repoe) quem.appendChild(el("span", "muted", "repõe a de " + a.repoe));
    if (a.local) quem.appendChild(el("span", "muted", a.local));
    bloco.appendChild(quem);
    var estado = el("p", "muted estado-atual");
    if (a.deve > 0) {   // reposições que ele ainda deve
      var deve = el("p", "deve-repor");
      deve.append("Deve " + a.deve + (a.deve === 1 ? " reposição" : " reposições") + " · ");
      var ver = el("a", null, "Ver controle");
      ver.href = "/agenda?semana=" + fh.elements.semana.value + (fh.elements.todas.value === "1" ? "&todas=1" : "") + "&aluno=" + a.cliente_id;
      deve.appendChild(ver);
      bloco.appendChild(deve);
    }
    if (marcada) {
      var tag = el("span", "tag " + COR[a.estado], a.estado);
      estado.append("Marcada como: ", tag);
    } else estado.textContent = a.pausa ? "Ainda não marcada (mês pulado)" : "Ainda não marcada";
    bloco.appendChild(estado);
    if (a.bloqueio && !marcada) bloco.appendChild(el("p", "dica-bloq", "Dia de bloqueio: use Cancelada (não repõe)"));
    var f = el("form", "botoes-estado" + (marcada ? "" : " sem-desfazer"));
    f.method = "post"; f.action = "/agenda/marcar";
    oculto(f, "cliente_id", a.cliente_id); oculto(f, "data", info.data); oculto(f, "hora", info.hora);
    oculto(f, "local", a.local); oculto(f, "avulsa", a.avulsa ? 1 : 0); oculto(f, "reposicao", a.reposicao ? 1 : 0);
    oculto(f, "semana", fh.elements.semana.value); oculto(f, "todas", fh.elements.todas.value); contexto(f);
    f.appendChild(botao("Feita", "btn-estado feita", "feita"));
    f.appendChild(botao("Faltou", "btn-estado faltou", "faltou"));
    if (a.reposicao) {   // reposição: cancelar é só cancelar (não gera outra reposição)
      var cr = botao("Cancelar reposição", "btn-estado cancelada", "cancelada");
      cr.title = "Só cancela esta reposição: não gera outra";
      f.appendChild(cr);
    } else {
      f.appendChild(botao("Desmarcou (repõe)", "btn-estado desmarcou", "desmarcou"));
      f.appendChild(botao("Cancelada (não repõe)", "btn-estado cancelada", "cancelada"));
    }
    if (marcada) f.appendChild(botao("Desfazer", "claro btn-estado", ""));
    bloco.appendChild(f);
    var acoes = el("div", "linha mt-p");
    var ficha = el("a", "btn claro pequeno", "Abrir ficha");
    ficha.href = "/clientes/" + a.cliente_id;
    acoes.appendChild(ficha);
    if (a.avulsa) {
      var fa = el("form"); fa.method = "post"; fa.action = "/agenda/avulsa/" + a.avulsa_id + "/excluir";
      fa.dataset.confirmar = "Excluir esta aula avulsa?";
      oculto(fa, "semana", fh.elements.semana.value); oculto(fa, "todas", fh.elements.todas.value); contexto(fa);
      fa.appendChild(botao("Excluir aula avulsa", "perigo pequeno"));
      acoes.appendChild(fa);
    }
    bloco.appendChild(acoes);
    return bloco;
  }
  function defineLocal(l) {
    if (l && !Array.prototype.some.call(loc.options, function (o) { return o.value === l; })) loc.appendChild(new Option(l, l));   // local fora da lista
    loc.value = l || "";
  }
  function ajustar() {   // 2º aluno só depois do 1º; local obrigatório quando tem aluno
    var tem = !!a1.value;
    a2.disabled = !tem;
    if (!tem || a2.value === a1.value) a2.value = "";
    loc.required = tem;
    Array.prototype.forEach.call(a2.options, function (o) { o.disabled = !!o.value && o.value === a1.value; });
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest(".cel[data-info]");
    if (!b) return;
    var info;
    try { info = JSON.parse(b.dataset.info); } catch (_) { return; }
    titulo.textContent = info.titulo;
    lista.textContent = "";
    info.alunos.forEach(function (a) { lista.appendChild(blocoAluno(a, info)); });
    lista.hidden = !info.alunos.length;
    fh.reset();
    fh.elements.dia.value = info.dia; fh.elements.hora.value = info.hora;
    var fx = info.fixos || [];
    a1.value = fx[0] ? String(fx[0].cliente_id) : "";
    a2.value = fx[1] ? String(fx[1].cliente_id) : "";
    var resto = fx.slice(2), ex = document.getElementById("h-extras-txt");   // limite maior que 2: os outros continuam no horário
    fh.elements.extras.value = resto.map(function (x) { return x.cliente_id; }).join(",");
    ex.hidden = !resto.length;
    ex.textContent = resto.length ? "Também neste horário (continua): " + resto.map(function (x) { return x.nome; }).join(", ") + "." : "";
    defineLocal(fx[0] ? fx[0].local : "");
    localMexido = false;
    ajustar();
    dlg.showModal();
  });
  a1.addEventListener("change", function () {
    var o = a1.selectedOptions[0], l = o && o.dataset.local;
    if (l && !localMexido && Array.prototype.some.call(loc.options, function (x) { return x.value === l; })) loc.value = l;   // local do cadastro
    ajustar();
  });
  loc.addEventListener("change", function () { localMexido = true; });   // só o usuário dispara change; defineLocal() não

  // incluir aula: "Toda semana" = linhas de dias (botões de marcar) + hora; "Só neste dia" = data, hora e "É reposição".
  // Os dias e horas das linhas viram os campos dias[] e horas[] (pares) só na hora de enviar. O local do aluno já vem escolhido.
  var f = document.getElementById("f-incluir"), linhasH = document.getElementById("linhas-horario"), maisH = document.getElementById("mais-horario");
  var MAX_LINHAS = 6, MAX_PARES = 12, primeiraLinha = linhasH.firstElementChild;
  function chips(l) { return l.querySelectorAll(".chip-dia input"); }
  function marcados(l) { return Array.prototype.filter.call(chips(l), function (c) { return c.checked; }); }
  function acertaLinhas() {
    var ls = linhasH.children, so1 = ls.length === 1;
    Array.prototype.forEach.call(ls, function (l) {
      l.querySelector(".tirar-linha").hidden = so1;
      l.querySelector(".hora-linha").required = f.elements.repetir.value === "1" && marcados(l).length > 0;   // hora só é obrigatória na linha que tem dia
    });
    maisH.hidden = ls.length >= MAX_LINHAS;
  }
  function modo() {
    var repete = f.elements.repetir.value === "1";
    document.getElementById("campo-dia").hidden = !repete;
    document.getElementById("campo-avulsa").hidden = repete;
    // campo escondido não é enviado nem exigido (hora vazia daria erro no servidor)
    ["data", "hora", "reposicao"].forEach(function (n) { f.elements[n].disabled = repete; });
    f.elements.data.required = !repete; f.elements.hora.required = !repete;
    acertaLinhas();
  }
  function limparLinhas() {   // volta a uma linha só, sem dias marcados
    while (linhasH.children.length > 1) linhasH.lastElementChild.remove();
    Array.prototype.forEach.call(chips(linhasH.firstElementChild), function (c) { c.checked = false; c.setCustomValidity(""); });
    linhasH.firstElementChild.querySelector(".hora-linha").value = "";
    acertaLinhas();
  }
  f.addEventListener("change", function (e) {
    if (e.target.name === "repetir") modo();
    else if (e.target.closest("#linhas-horario")) { chips(linhasH.firstElementChild)[0].setCustomValidity(""); acertaLinhas(); }
  });
  f.addEventListener("reset", function () { setTimeout(function () { limparLinhas(); modo(); }, 0); });   // o app.js reseta e preenche; depois disso acerta os campos
  maisH.addEventListener("click", function () {
    if (linhasH.children.length >= MAX_LINHAS) return;
    var nova = primeiraLinha.cloneNode(true);
    Array.prototype.forEach.call(chips(nova), function (c) { c.checked = false; });
    nova.querySelector(".hora-linha").value = "";
    linhasH.appendChild(nova);
    acertaLinhas();
  });
  linhasH.addEventListener("click", function (e) {
    var t = e.target.closest(".tirar-linha");
    if (!t || linhasH.children.length === 1) return;
    t.closest(".linha-horario").remove();
    acertaLinhas();
  });
  f.addEventListener("submit", function (e) {
    Array.prototype.forEach.call(f.querySelectorAll("input[data-gerado]"), function (i) { i.remove(); });
    if (f.elements.repetir.value !== "1") return;
    var pares = [], vistos = {};
    Array.prototype.forEach.call(linhasH.children, function (l) {
      var h = l.querySelector(".hora-linha").value;
      marcados(l).forEach(function (c) {
        if (h && !vistos[c.value + "-" + h]) { vistos[c.value + "-" + h] = 1; pares.push([c.value, h]); }
      });
    });
    var primeiro = chips(linhasH.firstElementChild)[0];
    if (!pares.length || pares.length > MAX_PARES) {
      e.preventDefault();
      primeiro.setCustomValidity(pares.length ? "No máximo " + MAX_PARES + " horários de uma vez." : "Marque ao menos um dia e a hora.");
      primeiro.reportValidity();
      return;
    }
    pares.forEach(function (p) {
      [["dias", p[0]], ["horas", p[1]]].forEach(function (kv) {
        var i = document.createElement("input");
        i.type = "hidden"; i.name = kv[0]; i.value = kv[1]; i.dataset.gerado = "1";
        f.appendChild(i);
      });
    });
  });
  function localDoAluno() {
    var o = f.elements.cliente_id.selectedOptions[0], l = o && o.dataset.local;
    if (l && Array.prototype.some.call(f.elements.local.options, function (x) { return x.value === l; })) f.elements.local.value = l;
  }
  f.elements.cliente_id.addEventListener("change", localDoAluno);
  modo();

  // "Agendar reposição" (painel do aluno): abre o incluir já com o aluno, "Só neste dia" e "É reposição".
  // Abre aqui (sem data-abrir): o app.js só copia valor e não marca botão de rádio nem caixa.
  document.addEventListener("click", function (e) {   // vale para o botão do painel (#btn-repor) e para a lista de Pendências (.btn-repor-aluno)
    var repor = e.target.closest(".btn-repor-aluno, #btn-repor");
    if (!repor) return;
    f.reset();
    f.elements.cliente_id.value = repor.dataset.aluno;
    f.elements.repetir.value = "0";
    modo();
    f.elements.reposicao.checked = true;
    localDoAluno();
    var t = document.querySelector("#dlg-incluir [data-titulo]");
    if (t) t.textContent = "Agendar reposição";
    document.getElementById("dlg-incluir").showModal();
  });

  // "Agendar reposição" de uma aula desmarcada (linha do painel): o mesmo incluir, já com o aluno e a desmarcação que ela repõe.
  // O id vai num campo escondido que volta a ficar vazio quando a janelinha fecha (o reset não limpa campo escondido).
  var dlgIncluir = document.getElementById("dlg-incluir"), aviso_repoe = document.getElementById("repoe-aviso");
  function limpaRepoe() { f.elements.repoe_evento_id.value = ""; aviso_repoe.hidden = true; }
  dlgIncluir.addEventListener("close", limpaRepoe);
  document.addEventListener("click", function (e) {
    var b = e.target.closest(".btn-repor-evento");
    if (!b) return;
    f.reset();
    f.elements.cliente_id.value = b.dataset.aluno;
    f.elements.repetir.value = "0";
    modo();
    f.elements.reposicao.checked = true;
    localDoAluno();
    f.elements.repoe_evento_id.value = b.dataset.evento;
    aviso_repoe.textContent = "Repõe a aula desmarcada de " + b.dataset.quando + ".";
    aviso_repoe.hidden = false;
    var t = document.querySelector("#dlg-incluir [data-titulo]");
    if (t) t.textContent = "Agendar reposição";
    dlgIncluir.showModal();
  });

  // trocar o aluno do controle já abre o painel
  document.getElementById("sel-aluno").addEventListener("change", function () { this.form.requestSubmit(); });

  // ===== Marcar várias: pinta aulas só na tela (sem falar com o servidor) e grava tudo com um Salvar =====
  var CORES = ["feita", "faltou", "desmarcou", "cancelada"], TIRAR = CORES.concat(["futura", "pendente", "bloq", "pausa"]);
  var ROTULO = {feita: "feita", faltou: "faltou", desmarcou: "desmarcou (repõe)", cancelada: "cancelada (não repõe)", "": "desfazer"};
  var barra = document.getElementById("barra-lote"), btnLote = document.getElementById("btn-lote");
  var btnSalvar = document.getElementById("lote-salvar"), aviso = document.getElementById("lote-aviso");
  var ligado = false, pincel = "feita", mud = new Map(), porChave = new Map(), enviando = false;

  function chave(m) { return m.cliente_id + "|" + m.data + "|" + m.hora; }
  function registra(e, m) {   // a mesma aula pode estar na grade e no "Hoje"
    e._marca = m;
    var k = chave(m);
    if (!porChave.has(k)) porChave.set(k, []);
    porChave.get(k).push(e);
  }
  document.querySelectorAll(".cel.aula[data-info]").forEach(function (card) {   // cada nome do card = um aluno do data-info
    var info;
    try { info = JSON.parse(card.dataset.info); } catch (_) { return; }
    card.querySelectorAll(".n").forEach(function (n, i) {
      var a = info.alunos[i];
      if (a) registra(n, {cliente_id: a.cliente_id, data: info.data, hora: info.hora, local: a.local, avulsa: a.avulsa, reposicao: a.reposicao, estado: a.estado, base: a.base});
    });
  });
  document.querySelectorAll("[data-marca]").forEach(function (e) {   // linhas do "Hoje" e das Pendências
    try { registra(e, JSON.parse(e.dataset.marca)); } catch (_) { }
  });
  function atual(m) { var x = mud.get(chave(m)); return x ? x.estado : (m.estado || ""); }
  function trocaCor(e, cls) {
    TIRAR.forEach(function (c) { e.classList.remove(c); });
    e.classList.add(cls);
  }
  function pinta(m) {
    var est = atual(m), mudou = mud.has(chave(m));
    (porChave.get(chave(m)) || []).forEach(function (e) {
      if (e.classList.contains("n")) {
        trocaCor(e, est || m.base);
        var card = e.closest(".cel.aula");
        if (card && !card.classList.contains("dupla")) trocaCor(card, est || m.base);   // card de 1 aluno: o card todo leva a cor
      } else {   // linha do "Hoje" ou das Pendências
        CORES.forEach(function (c) { e.classList.remove(c); });
        if (est) e.classList.add(est);
        var tag = e.querySelector(".estado-lote");
        if (tag) {
          tag.hidden = !mudou;
          tag.className = "tag estado-lote " + ({feita: "verde", faltou: "vermelho", desmarcou: "amarelo"}[est] || "neutro");   // cancelada: neutro, como a tag de fora do lote
          tag.textContent = (ROTULO[est] || "desfazer") + " (não salva)";
        }
      }
      e.classList.toggle("nao-salvo", mudou);
    });
  }
  function conta() {
    btnSalvar.textContent = "Salvar (" + mud.size + ")";
    btnSalvar.disabled = !mud.size || mud.size > 300;
    aviso.hidden = mud.size <= 300;
  }
  function alvoDe(m) { return m.reposicao && pincel === "desmarcou" ? "cancelada" : pincel; }   // na reposição, desmarcou = só cancelar
  function pintar(es) {   // es = 1 aula (nome, linha) ou as 2 da dupla (toque fora dos nomes)
    var ms = es.map(function (e) { return e._marca; }).filter(Boolean);
    if (!ms.length) return;
    var desfaz = ms.every(function (m) { return atual(m) === alvoDe(m); });   // tocar de novo com o mesmo pincel desfaz (a dupla inteira)
    ms.forEach(function (m) {
      var k = chave(m), alvo = alvoDe(m);
      if (desfaz || (m.estado || "") === alvo) mud.delete(k);   // volta ao que já estava salvo
      else mud.set(k, {m: m, estado: alvo});
      pinta(m);
    });
    conta();
  }
  function aulas(e) {   // o que foi tocado: o nome, uma linha (Hoje / Pendências), ou o card: com 2 alunos, fora dos nomes, pinta os dois
    var n = e.target.closest(".n");
    if (n && n._marca) return [n];
    var h = e.target.closest("[data-marca]");
    if (h && h._marca && !e.target.closest("a")) return [h];
    var card = e.target.closest(".cel.aula");
    return card ? Array.prototype.filter.call(card.querySelectorAll(".n"), function (x) { return x._marca; }) : [];
  }
  // fase de captura: com o modo ligado, o toque no card só pinta e nunca abre a janelinha do horário
  document.addEventListener("click", function (e) {
    if (!ligado) return;
    var alvo = aulas(e);
    if (alvo.length) { e.preventDefault(); e.stopImmediatePropagation(); pintar(alvo); return; }
    if (e.target.closest(".cel")) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);

  // Pendências: fora do "Marcar várias", tocar na linha abre o mesmo card da grade (se a célula não está na tela, nada acontece)
  function abreCelula(linha) {
    var cel = document.querySelector('.cel[data-dh="' + linha.dataset.dh + '"]');
    if (cel) cel.click();
  }
  document.querySelectorAll(".pend-linha").forEach(function (l) {
    l.addEventListener("click", function () { if (!ligado) abreCelula(l); });
    l.addEventListener("keydown", function (e) {   // div com role=button: o teclado não gera clique sozinho (Espaço também não rola a tela)
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      if (ligado) pintar([l]); else abreCelula(l);
    });
  });
  var btnTodas = document.getElementById("pend-todas");
  if (btnTodas) btnTodas.addEventListener("click", function () {   // liga o modo e pinta tudo como feita (não salva): o resto é corrigir as exceções e Salvar
    ligar(true);
    document.querySelectorAll(".pend-linha").forEach(function (l) {
      var m = l._marca;
      if (!m || atual(m) === "feita") return;
      mud.set(chave(m), {m: m, estado: "feita"});
      pinta(m);
    });
    conta();
  });

  function ligar(sim) {
    ligado = sim;
    document.body.classList.toggle("modo-lote", sim);
    barra.hidden = !sim;
    document.querySelector(".lote-info").hidden = !sim;
    btnLote.setAttribute("aria-pressed", sim);
  }
  function descartar() {
    var ms = Array.from(mud.values()).map(function (x) { return x.m; });
    mud.clear();
    ms.forEach(pinta);
    conta();
  }
  btnLote.addEventListener("click", function () { ligar(true); });
  barra.querySelectorAll("[data-pincel]").forEach(function (b) {
    b.addEventListener("click", function () {
      pincel = b.dataset.pincel;
      barra.querySelectorAll("[data-pincel]").forEach(function (x) { x.setAttribute("aria-pressed", x === b); });
    });
  });
  document.getElementById("lote-cancelar").addEventListener("click", function () {
    if (mud.size && !confirm("Descartar as marcações que ainda não foram salvas?")) return;
    descartar();
    ligar(false);
  });
  btnSalvar.addEventListener("click", function () {
    if (!mud.size || mud.size > 300 || enviando) return;
    enviando = true;   // sem aviso de "sair sem salvar" na ida para o servidor
    btnSalvar.disabled = true; btnSalvar.textContent = "Salvando…";
    var itens = Array.from(mud.values()).map(function (x) {
      var m = x.m;
      return {cliente_id: m.cliente_id, data: m.data, hora: m.hora, local: m.local, avulsa: m.avulsa ? 1 : 0, reposicao: m.reposicao ? 1 : 0, estado: x.estado};
    });
    var form = document.createElement("form");
    form.method = "post"; form.action = "/agenda/marcar-lote"; form.hidden = true;
    [["itens", JSON.stringify(itens)], ["semana", barra.dataset.semana], ["todas", barra.dataset.todas],
     ["aluno", barra.dataset.aluno], ["mes", barra.dataset.mes]].forEach(function (kv) {
      var i = document.createElement("input");
      i.type = "hidden"; i.name = kv[0]; i.value = kv[1];
      form.appendChild(i);
    });
    document.body.appendChild(form);
    form.submit();
  });
  // semanas anteriores com aula sem marcar: busca depois da página carregar (não atrasa a tela); se falhar, não mostra nada
  var ant = document.getElementById("pend-anteriores");
  if (ant && window.fetch) fetch("/agenda/pendentes", {credentials: "same-origin", headers: {Accept: "application/json"}})
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (d) {
      var ss = (d && d.semanas) || [];
      if (!ss.length) return;
      ant.appendChild(el("span", "muted", "Semanas anteriores: "));
      ss.forEach(function (s) {
        var a = el("a", "tag amarelo", "Semana de " + s.txt.slice(0, 5) + ": " + s.n + " sem marcar");
        a.href = "/agenda?semana=" + s.segunda + (ant.dataset.extra || "");
        ant.appendChild(a);
      });
    })
    .catch(function () { });
  window.addEventListener("beforeunload", function (e) {
    if (mud.size && !enviando) { e.preventDefault(); e.returnValue = ""; }
  });
  window.addEventListener("pageshow", function () { enviando = false; conta(); });   // voltou pelo histórico: libera o Salvar
})();
</script>`;
