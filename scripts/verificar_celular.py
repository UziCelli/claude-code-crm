"""Confere se as telas cabem no celular (ferramenta de desenvolvimento; não roda no CI).

Sobe o CRM num banco temporário com dados de exemplo, abre cada tela e cada janela (<dialog>) com o Playwright
em 360 e 390 px de largura e lista o que passa da borda (a página não pode rolar para o lado).

Precisa do Playwright para Python (pip install playwright; python -m playwright install chromium).
Uso:  python scripts/verificar_celular.py [pasta_das_fotos]
Sai com código 1 se alguma tela vazar."""
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

LARGURAS = (360, 390)
TELAS = ["/", "/clientes", "/clientes/novo", "/clientes/1", "/leads", "/grade", "/grade?local=CIA", "/agenda", "/simulador",
         "/propostas", "/explorador", "/campanhas", "/rotina", "/financeiro", "/financeiro/previsao", "/financeiro/conferir",
         "/financeiro/linha-do-tempo", "/financeiro/mensalidades", "/financeiro/painel", "/assistente", "/configuracoes",
         "/calculos", "/dados"]

# JS: elementos visíveis cuja borda direita passa da tela (ignora o que está dentro de uma caixa que rola de lado)
VAZAMENTOS = """() => {
  const w = document.documentElement.clientWidth, out = [];
  const rola = el => { for (let p = el.parentElement; p; p = p.parentElement) {
      const s = getComputedStyle(p); if (/(auto|scroll|hidden)/.test(s.overflowX) && p !== document.body && p !== document.documentElement) return true; }
    return false; };
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (!r.width || r.right <= w + 1 || rola(el) || el.closest('details:not([open]) > :not(summary)')) continue;
    const s = getComputedStyle(el); if (s.position === 'fixed' || s.visibility === 'hidden') continue;
    out.push(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : '')
             + ' (' + Math.round(r.right) + 'px)');
  }
  // caixas que rolam de lado (o conteúdo não cabe e o dedo precisa arrastar): também contam, menos as marcadas .rolavel
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (!/(auto|scroll)/.test(s.overflowX) || el.scrollWidth <= el.clientWidth + 2 || !el.getBoundingClientRect().width) continue;
    if (el.closest('.rolavel, .menu, dialog:not([open]), details:not([open]) > :not(summary)')) continue;
    out.push('rola de lado: ' + el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : '')
             + ' (' + el.scrollWidth + ' em ' + el.clientWidth + 'px)');
  }
  return {largura: document.documentElement.scrollWidth, tela: w, itens: [...new Set(out)].slice(0, 8)};
}"""


LONGO = "Condominio Residencial Parque das Arvores Bloco B"


def semear(db):
    con = db.conectar()
    with con:
        for nome, plano, local in (("Ana Exemplo", "Mensalidade 2x/semana", "CIA"), ("Bruno Exemplo", "Pacote 8 aulas", "CIA"),
                                   ("Carla Exemplo", "Consultoria Online", None),
                                   ("Maria Aparecida dos Santos Oliveira Fernandes", "Mensalidade 3x/semana", "Condominio Residencial Parque das Arvores Bloco B")):
            tipo = "Mensalidade" if "Mensal" in plano else "Pacote de Aulas" if "Pacote" in plano else "Consultoria Online"
            con.execute("INSERT INTO clientes (nome, telefone, local, tipo_servico, plano, valor, forma_pagamento, status, data_inicio, data_renovacao)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?)", (nome, "11999990000", local, tipo, plano, 800, "PIX", "ativo", "2026-09-01", "2026-12-05"))
        con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (1, 1, 7, 'CIA'), (1, 4, 7, 'CIA'), (2, 2, 18, 'CIA')")
        hoje = time.strftime("%Y-%m-%d")
        con.execute("INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, descricao) VALUES ('PJ','saida',?,150,'Outros','Conta de exemplo com um nome bem comprido')", (hoje,))
        con.execute("INSERT OR IGNORE INTO parametros (grupo, chave, valor_texto) VALUES ('lista_locais', ?, ?)", (LONGO, LONGO))
        con.execute("INSERT INTO agenda_fixos (cliente_id, dia, hora, local) VALUES (4, 3, 19, ?)", (LONGO,))
        con.execute("INSERT INTO leads (nome, telefone, etapa, canal_origem) VALUES ('Lead Exemplo', '11988887777', 'lead', 'Instagram orgânico')")
    con.close()


def porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    fotos = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    tmp = Path(tempfile.mkdtemp(prefix="crm-celular-"))
    os.environ.pop("CRM_NUVEM", None)
    from app import db
    db.DB_PATH, db.BACKUP_DIR = tmp / "crm.db", tmp / "backups"
    db.iniciar_banco()
    semear(db)
    import uvicorn
    from app import main as app_main
    porta = porta_livre()
    servidor = uvicorn.Server(uvicorn.Config(app_main.app, host="127.0.0.1", port=porta, log_level="warning", lifespan="off"))
    threading.Thread(target=servidor.run, daemon=True).start()
    while not servidor.started:
        time.sleep(0.1)

    from playwright.sync_api import sync_playwright
    falhas = 0
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception:   # navegador baixado pelo Playwright ausente: use um Chromium já instalado (CRM_CHROMIUM)
            nav = p.chromium.launch(executable_path=os.environ.get("CRM_CHROMIUM", "/opt/pw-browsers/chromium"))
        for largura in LARGURAS:
            pag = nav.new_page(viewport={"width": largura, "height": 800})
            for url in TELAS:
                pag.goto(f"http://127.0.0.1:{porta}{url}", wait_until="networkidle")
                r = pag.evaluate(VAZAMENTOS)
                nome = url.strip("/").replace("/", "_").replace("?", "_").replace("=", "-") or "painel"
                if fotos:
                    fotos.mkdir(parents=True, exist_ok=True)
                    pag.screenshot(path=str(fotos / f"{largura}-{nome}.png"), full_page=True)
                if r["largura"] > r["tela"] + 1 or r["itens"]:
                    falhas += 1
                    print(f"[{largura}px] {url}: página com {r['largura']}px; vazam: {', '.join(r['itens']) or '-'}")
                ja = set(r["itens"])   # o que vaza na página já foi contado; na janela, só o que é dela
                for i, dlg in enumerate(pag.query_selector_all("dialog")):
                    pag.evaluate("d => { document.querySelectorAll('dialog[open]').forEach(x => x.close()); d.showModal(); }", dlg)
                    r = pag.evaluate(VAZAMENTOS)
                    r["itens"] = [x for x in r["itens"] if x not in ja]
                    if r["itens"]:
                        falhas += 1
                        ident = dlg.get_attribute("id") or f"dialog {i}"
                        print(f"[{largura}px] {url} janela {ident}: vazam: {', '.join(r['itens'])}")
                    pag.evaluate("d => d.close()", dlg)
            pag.close()
        nav.close()
    servidor.should_exit = True
    print("Tudo cabe na tela." if not falhas else f"{falhas} problema(s).")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
