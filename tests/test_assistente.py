"""Assistente (chat com o Claude): ferramentas, histórico que só cresce, recusa, corte, erros da API e a tela.
Tudo com um cliente falso: nenhum teste chama a API de verdade (nem gasta crédito)."""
import copy
import datetime as dt
import json
import time
from types import SimpleNamespace
from urllib.parse import unquote

import anthropic
import httpx2
import pytest
from anthropic._models import construct_type
from anthropic.types.beta.parsed_beta_message import ParsedBetaMessage
from fastapi.testclient import TestClient

from app import assistente, db, main

HOJE = dt.date.today().isoformat()


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    """Sem chave, sem proxy e sem modelo trocado (o ambiente de quem roda os testes não interfere)."""
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ASSISTENTE_MODELO", "ASSISTENTE_ESFORCO"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setitem(assistente._estado, "basico", False)
    monkeypatch.setitem(assistente._chave_salva, "valor", "")


@pytest.fixture
def con_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    con = db.conectar()
    yield con
    con.close()


def resposta(conteudo, stop="end_turn", modelo="claude-haiku-5-5", entrada=1000):
    return construct_type(type_=ParsedBetaMessage, value={
        "id": "msg_teste", "type": "message", "role": "assistant", "model": modelo, "content": conteudo, "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": entrada, "output_tokens": 200, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 5000}})


def texto(t):
    return {"type": "text", "text": t}


def pensou(assinatura="assinatura-1"):
    return {"type": "thinking", "thinking": "", "signature": assinatura}


def pede(nome, entrada, i="tu_1"):
    return {"type": "tool_use", "id": i, "name": nome, "input": entrada}


class Fluxo:
    def __init__(self, msg, aberto):
        self.msg, self.aberto = msg, aberto

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        for b in self.msg.content:
            if b.type == "text":
                yield SimpleNamespace(type="text", text=b.text)

    def get_final_message(self):
        return self.msg


class ClienteFalso:
    """Imita client.beta.messages.stream / client.messages.stream e guarda cada pedido."""

    def __init__(self, respostas, abertas=None):
        self.respostas, self.pedidos, self.qual, self.abertas = list(respostas), [], [], abertas
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **p: self._stream("beta", p)))
        self.messages = SimpleNamespace(stream=lambda **p: self._stream("normal", p))

    def _stream(self, qual, params):
        if self.abertas is not None:
            assert self.abertas["n"] == 0, "conexão com o banco aberta enquanto o modelo pensa"
        self.pedidos.append(copy.deepcopy(params))
        self.qual.append(qual)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return Fluxo(r, self.abertas)


def rodar(cliente, msg, cid=None):
    return list(assistente.responder(msg, cid, cliente=cliente))


def linhas(con, cid):
    return [(r["papel"], json.loads(r["conteudo"])) for r in con.execute(
        "SELECT papel, conteudo FROM assistente_mensagens WHERE conversa_id=? ORDER BY id", (cid,))]


def erro_api(classe, status, mensagem):
    return classe(mensagem, response=httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")),
                  body=None)


# ---------- definição das ferramentas ----------
def test_ferramentas_bem_formadas():
    nomes = [f["name"] for f in assistente.FERRAMENTAS]
    assert len(nomes) == len(set(nomes)) == len(assistente.EXECUTORES)
    assert set(nomes) == set(assistente.EXECUTORES) == set(assistente.ROTULOS)
    for f in assistente.FERRAMENTAS:
        s = f["input_schema"]
        assert f["description"] and s["type"] == "object"
        assert set(s["required"]) <= set(s["properties"]), f["name"]
    json.dumps(assistente.FERRAMENTAS)   # vai para a API como está


def test_instrucoes_fixas_sem_data():
    """A data muda todo dia: fica na mensagem do usuário, senão o cache e o raciocínio guardado se perdem."""
    assert HOJE not in assistente.SISTEMA and dt.date.today().strftime("%d/%m/%Y") not in assistente.SISTEMA


# ---------- conversa ----------
def test_pergunta_com_ferramenta_e_historico_que_so_cresce(con_temp):
    c = ClienteFalso([resposta([pensou(), texto("Vou olhar."), pede("contas_a_pagar", {})], "tool_use"),
                      resposta([texto("Nada vence esta semana.")]),
                      resposta([texto("De nada!")])])
    ev = rodar(c, "o que vence?")
    tipos = [e["tipo"] for e in ev]
    assert tipos == ["conversa", "texto", "ferramenta", "texto", "uso"]
    cid = ev[0]["id"]
    assert ev[2]["texto"] == assistente.rotulo("contas_a_pagar")
    papeis = [p for p, _ in linhas(con_temp, cid)]
    assert papeis == ["user", "assistant", "user", "assistant"]
    _, primeira = linhas(con_temp, cid)[0]
    assert primeira[0]["text"].startswith("(Hoje: ") and primeira[0]["text"].endswith("o que vence?")
    # o raciocínio volta igualzinho (com a assinatura) e o resultado da ferramenta responde ao pedido certo
    segundo = c.pedidos[1]["messages"]
    assert segundo[1]["content"][0] == pensou()
    assert segundo[2]["content"][0]["type"] == "tool_result" and segundo[2]["content"][0]["tool_use_id"] == "tu_1"
    assert "is_error" not in segundo[2]["content"][0]
    # segunda mensagem na mesma conversa: tudo o que já foi mandado vai de novo, igual, e só acrescenta
    rodar(c, "obrigado", cid)
    for antes, depois in zip(c.pedidos, c.pedidos[1:]):
        assert depois["messages"][:len(antes["messages"])] == antes["messages"]
        assert depois["system"] == antes["system"] and depois["tools"] == antes["tools"]
    assert c.pedidos[2]["messages"][-1]["content"][0]["text"].endswith("obrigado")


def test_pedido_completo_na_api_direta(con_temp):
    c = ClienteFalso([resposta([texto("Oi")])])
    rodar(c, "oi")
    p = c.pedidos[0]
    assert c.qual == ["beta"]
    assert p["model"] == "claude-haiku-5-5" and p["max_tokens"] >= 16000
    assert p["thinking"] == {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
    assert "fallbacks" not in p and p["output_config"] == {"effort": "medium"}   # o modelo padrão não tem troca no servidor
    assert p["betas"] == ["thinking-binding-controls-2026-08-01"]
    assert p["cache_control"] == {"type": "ephemeral"} and p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "tool_choice" not in p   # ferramenta forçada: erro em alguns modelos; no padrão, pula o raciocínio
    assert not {"temperature", "top_p", "top_k"} & set(p)


def test_modelo_com_troca_no_servidor_manda_fallbacks(con_temp, monkeypatch):
    monkeypatch.setenv("ASSISTENTE_MODELO", "claude-opus-5-5")
    c = ClienteFalso([resposta([texto("Oi")], modelo="claude-opus-5-5")])
    rodar(c, "oi")
    p = c.pedidos[0]
    assert p["model"] == "claude-opus-5-5" and p["fallbacks"] == "default"
    assert set(p["betas"]) == {"thinking-binding-controls-2026-08-01", "server-side-fallback-2026-07-01"}
    assert p["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"} and "tool_choice" not in p


def test_modelo_e_esforco_pelo_env(con_temp, monkeypatch):
    monkeypatch.setenv("ASSISTENTE_MODELO", "claude-sonnet-5-5")
    monkeypatch.setenv("ASSISTENTE_ESFORCO", "high")
    c = ClienteFalso([resposta([texto("Oi")], modelo="claude-sonnet-5-5")])
    rodar(c, "oi")
    assert c.pedidos[0]["model"] == "claude-sonnet-5-5" and c.pedidos[0]["output_config"] == {"effort": "high"}
    monkeypatch.setenv("ASSISTENTE_ESFORCO", "turbo")   # valor estranho: volta ao padrão
    assert assistente.esforco() == "medium"


def test_proxy_manda_so_o_basico(con_temp, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:20128")
    c = ClienteFalso([resposta([texto("Oi")])])
    rodar(c, "oi")
    assert c.qual == ["normal"]
    assert set(c.pedidos[0]) == {"model", "max_tokens", "system", "tools", "messages"}
    assert isinstance(c.pedidos[0]["system"], str)


def test_recurso_recusado_tenta_de_novo_com_o_basico(con_temp):
    c = ClienteFalso([erro_api(anthropic.BadRequestError, 400, "Unexpected value(s) for the anthropic-beta header"),
                      resposta([texto("Oi")])])
    ev = rodar(c, "oi")
    assert [e["tipo"] for e in ev] == ["conversa", "texto", "uso"]
    assert c.qual == ["beta", "normal"]
    assert not {"betas", "fallbacks", "thinking"} & set(c.pedidos[1])
    assert c.pedidos[1]["tools"] == c.pedidos[0]["tools"] and c.pedidos[1]["system"] == c.pedidos[0]["system"]
    assert assistente._estado["basico"] is True


def test_banco_fechado_enquanto_o_modelo_pensa(con_temp, monkeypatch):
    """No modo Turso a conexão é uma só: aberta durante a resposta, travaria o CRM inteiro."""
    abertas = {"n": 0}
    original = db.conectar

    class Contada:
        def __init__(self):
            self.con = original()
            abertas["n"] += 1

        def __getattr__(self, k):
            return getattr(self.con, k)

        def __enter__(self):
            return self.con.__enter__()

        def __exit__(self, *a):
            return self.con.__exit__(*a)

        def close(self):
            abertas["n"] -= 1
            self.con.close()
    c = ClienteFalso([resposta([pede("ver_painel", {})], "tool_use"), resposta([texto("Tudo certo.")])], abertas)
    ev = list(assistente.responder("e hoje?", conectar=Contada, cliente=c))
    assert [e["tipo"] for e in ev] == ["conversa", "ferramenta", "texto", "uso"] and abertas["n"] == 0


def test_recusa_nao_entra_no_historico(con_temp):
    c = ClienteFalso([resposta([texto("Começo de respo")], "refusal"), resposta([texto("Claro.")])])
    ev = rodar(c, "pergunta 1")
    cid = ev[0]["id"]
    assert ev[-2]["tipo"] == "aviso" and ev[-2]["guardado"]
    assert [p for p, _ in linhas(con_temp, cid)] == ["user", "aviso"]
    rodar(c, "pergunta 2", cid)
    msgs = c.pedidos[1]["messages"]
    assert len(msgs) == 1 and msgs[0]["role"] == "user" and len(msgs[0]["content"]) == 2   # as duas perguntas juntas


def test_pedido_cortado_nao_roda_a_ferramenta(con_temp):
    lanc = {"escopo": "PF", "tipo": "saida", "data": HOJE, "valor": 10, "categoria": "Lazer"}
    c = ClienteFalso([resposta([pede("criar_lancamento", lanc)], "max_tokens"), resposta([texto("Ok")])])
    ev = rodar(c, "lança")
    cid = ev[0]["id"]
    assert ev[-2]["tipo"] == "aviso" and "cortada" in ev[-2]["texto"]
    assert con_temp.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 0
    papel, resultado = linhas(con_temp, cid)[-1]
    assert papel == "user" and resultado[0]["is_error"] and resultado[0]["tool_use_id"] == "tu_1"
    rodar(c, "de novo", cid)   # a próxima mensagem não quebra: o pedido cortado já tem resposta
    assert c.pedidos[1]["messages"][2]["content"][0]["type"] == "tool_result"


def test_troca_de_modelo_no_meio_so_devolve_texto_de_antes():
    blocos = construct_type(type_=ParsedBetaMessage, value={
        "id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5", "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "content": [pensou(), texto("parcial "), pede("ver_painel", {}), {"type": "fallback", "from": {"model": "a"}, "to": {"model": "b"}},
                    pensou("assinatura-2"), texto("final"), texto("  ")]}).content
    assert assistente.blocos_para_historico(blocos) == [texto("parcial "), pensou("assinatura-2"), texto("final")]


def test_pedido_sem_resposta_e_fechado_antes_da_proxima_mensagem(con_temp):
    """Queda entre o pedido de ferramenta e o resultado: a API exige um resultado para cada pedido."""
    cid = assistente.criar_conversa(con_temp, "x")
    assistente._gravar(con_temp, cid, "user", [texto("(Hoje: x)\n\noi")])
    assistente._gravar(con_temp, cid, "assistant", [pede("ver_painel", {}, "tu_9")])
    c = ClienteFalso([resposta([texto("Oi")])])
    rodar(c, "oi de novo", cid)
    msgs = c.pedidos[0]["messages"]
    assert msgs[2]["role"] == "user" and msgs[2]["content"][0] == {
        "type": "tool_result", "tool_use_id": "tu_9", "is_error": True, "content": "Interrompido antes de rodar: nada foi feito."}
    assert msgs[2]["content"][1]["text"].endswith("oi de novo")


def test_tela_fechada_no_meio_nao_repete_a_acao(con_temp):
    """Duas ações seguidas e a tela fecha entre elas: a 1ª já gravou e o resultado dela fica guardado (senão o modelo
    acharia que não fez e faria de novo); a 2ª não rodou e é avisada como interrompida."""
    c = ClienteFalso([resposta([pede("criar_tarefa", {"texto": "pagar boleto"}, "tu_a"), pede("ver_tarefas", {}, "tu_b")], "tool_use"),
                      resposta([texto("Pronto.")])])
    fluxo = assistente.responder("cria a tarefa", cliente=c)
    cid, acoes = None, 0
    for ev in fluxo:
        cid = ev.get("id", cid) if ev["tipo"] == "conversa" else cid
        acoes += ev["tipo"] == "ferramenta"
        if acoes == 2:
            break
    fluxo.close()   # a tela fechou antes da 2ª ação rodar
    assert con_temp.execute("SELECT COUNT(*) FROM rotina_tarefas WHERE texto='pagar boleto'").fetchone()[0] == 1
    rodar(c, "e aí?", cid)
    juntos = c.pedidos[1]["messages"][2]["content"]
    resultados = {b["tool_use_id"]: b for b in juntos if b["type"] == "tool_result"}
    assert "is_error" not in resultados["tu_a"] and resultados["tu_b"]["is_error"]
    assert [b["type"] for b in juntos] == ["tool_result", "tool_result", "text"]   # a pergunta nova vem depois dos resultados


def test_limite_de_rodadas(con_temp):
    c = ClienteFalso([resposta([pede("ver_painel", {}, f"tu_{i}")], "tool_use") for i in range(assistente.MAX_PASSOS)])
    ev = rodar(c, "loop")
    assert sum(e["tipo"] == "ferramenta" for e in ev) == assistente.MAX_PASSOS
    assert ev[-2]["tipo"] == "aviso" and "continue" in ev[-2]["texto"]


def test_conversa_ocupada(con_temp):
    cid = assistente.criar_conversa(con_temp, "x")
    trava = assistente._trava(cid)
    trava.acquire()
    try:
        ev = rodar(ClienteFalso([]), "oi", cid)
    finally:
        trava.release()
    assert ev == [{"tipo": "erro", "texto": "Esta conversa ainda está respondendo. Espere terminar e mande de novo."}]


@pytest.mark.parametrize("erro, trecho", [
    (lambda: erro_api(anthropic.AuthenticationError, 401, "invalid x-api-key"), "chave da API não foi aceita"),
    (lambda: erro_api(anthropic.BadRequestError, 400, "Your credit balance is too low"), "sem crédito"),
    (lambda: erro_api(anthropic.RateLimitError, 429, "rate limit"), "Espere um minuto"),
    (lambda: erro_api(anthropic.NotFoundError, 404, "model not found"), "ASSISTENTE_MODELO"),
    (lambda: erro_api(anthropic.InternalServerError, 529, "overloaded"), "instável"),
    (lambda: anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), "Sem conexão"),
])
def test_erros_da_api_em_portugues(con_temp, erro, trecho):
    ev = rodar(ClienteFalso([erro()]), "oi")
    assert ev[1]["tipo"] == "erro" and trecho in ev[1]["texto"]


def test_sem_chave_nao_chama_nada(con_temp):
    ev = list(assistente.responder("oi"))
    assert ev == [{"tipo": "erro", "texto": assistente.DESLIGADO}]
    assert con_temp.execute("SELECT COUNT(*) FROM assistente_conversas").fetchone()[0] == 0


def test_custo_estimado():
    uso = {"modelo": "claude-opus-5-5", "entrada": 1_000_000, "saida": 100_000, "cache_leitura": 1_000_000, "cache_gravacao": 0}
    assert assistente.custo(uso) == pytest.approx(4 + 2 + 0.2)
    assert assistente.custo(dict(uso, modelo="modelo-desconhecido")) is None


def test_custo_estimado_haiku_por_faixa_do_pedido():
    h = {"modelo": "claude-haiku-5-5", "entrada": 50_000, "saida": 10_000, "cache_leitura": 40_000, "cache_gravacao": 0}
    assert assistente.custo(h) == pytest.approx(0.0104)   # prompt de 90 mil: faixa barata
    longo = dict(h, entrada=60_000, cache_leitura=50_000)
    assert assistente.custo(longo) == pytest.approx(0.0575)   # prompt de 110 mil: faixa cara
    exato = dict(h, entrada=50_000, saida=0, cache_leitura=50_000)
    assert assistente.custo(exato) == pytest.approx(0.0055)   # exatamente 100 mil ainda é a faixa barata
    assert assistente.custo(dict(exato, cache_gravacao=1)) > 0.0275   # 100 mil e 1: faixa cara
    assert assistente.custo(dict(h, entrada=1, saida=0, cache_leitura=0)) == pytest.approx(1e-7)


def test_custo_br():
    assert main._custo_br(0.033) == "≈ US$ 0,03"
    assert main._custo_br(0.000825) == "< US$ 0,01"
    assert main._custo_br(None) == "" and main._custo_br(0) == ""


def test_aviso_de_conversa_longa(con_temp):
    c = ClienteFalso([resposta([texto("Oi")], entrada=assistente.CONVERSA_LONGA - 4999)])   # mais 5.000 no cache: 80.001
    assert any(e["tipo"] == "aviso" and "ficou longa" in e["texto"] for e in rodar(c, "oi"))
    c = ClienteFalso([resposta([texto("Oi")], entrada=assistente.CONVERSA_LONGA - 6000)])   # mais 5.000 gravados no cache: 79.000
    assert not any(e["tipo"] == "aviso" for e in rodar(c, "oi"))


# ---------- ferramentas ----------
def ok(con, nome, entrada):
    saida, erro = assistente.executar(con, nome, entrada)
    assert not erro, saida
    return json.loads(saida)


def falha(con, nome, entrada):
    saida, erro = assistente.executar(con, nome, entrada)
    assert erro, saida
    return saida


def test_leituras_rodam_no_banco_vazio(con_temp):
    for nome in ("ver_painel", "resumo_do_mes", "listar_lancamentos", "contas_a_pagar", "previsao_de_caixa", "mensalidades_do_mes",
                 "saldos_das_contas", "listar_contas_recorrentes", "buscar_alunos", "ver_tarefas"):
        ok(con_temp, nome, {})


def test_consulta_livre_so_le(con_temp):
    with con_temp:
        con_temp.execute("INSERT INTO clientes (nome) VALUES ('Ana')")
    assert ok(con_temp, "consultar_banco", {"sql": "SELECT nome FROM clientes;"})["linhas"] == [["Ana"]]
    for sql in ("WITH x AS (SELECT 1) DELETE FROM clientes", "SELECT 1; DELETE FROM clientes", "DELETE FROM clientes",
                "SELECT 1 -- comentário", "SELECT 1 /* x */", "UPDATE clientes SET nome='x'", "PRAGMA writable_schema=1"):
        falha(con_temp, "consultar_banco", {"sql": sql})
    assert con_temp.execute("SELECT nome FROM clientes").fetchall()[0][0] == "Ana"


def test_criar_lancamento_valida_e_avisa_os_potes(con_temp):
    base = {"escopo": "PJ", "tipo": "entrada", "data": HOJE, "valor": 300, "categoria": "Pacotes de Aulas"}
    assert "não existe" in falha(con_temp, "criar_lancamento", dict(base, categoria="Inventada"))
    amanha = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    assert "futuro" in falha(con_temp, "criar_lancamento", dict(base, pago_em=amanha))
    assert "maior que zero" in falha(con_temp, "criar_lancamento", dict(base, valor=-5))
    assert "não encontrado" in falha(con_temp, "criar_lancamento", dict(base, cliente_id=999))
    r = ok(con_temp, "criar_lancamento", dict(base, categoria="pacotes de aulas", pago_em=HOJE, conta="inter", valor="1.234,50"))
    l = con_temp.execute("SELECT * FROM lancamentos WHERE id=?", (r["id"],)).fetchone()
    assert (l["categoria"], l["conta"], l["valor"], l["pago_em"]) == ("Pacotes de Aulas", "Inter", 1234.5, HOJE)
    assert "Separe:" in r["mensagem"] and r["para_desfazer"] == f"excluir_lancamento(id={r['id']})"


def test_pagamento_de_aluno_ja_lancado_em_aberto_vira_baixa(con_temp):
    with con_temp:
        cid = con_temp.execute("INSERT INTO clientes (nome, valor) VALUES ('Ana', 300)").lastrowid
        aberta = con_temp.execute("""INSERT INTO lancamentos (escopo, tipo, data, valor, categoria, cliente_id)
                                     VALUES ('PJ','entrada',?,300,'Pacotes de Aulas',?)""", (HOJE, cid)).lastrowid
    r = ok(con_temp, "criar_lancamento", {"escopo": "PJ", "tipo": "entrada", "data": HOJE, "valor": 300,
                                          "categoria": "Pacotes de Aulas", "cliente_id": cid, "pago_em": HOJE})
    assert r["id"] == aberta and con_temp.execute("SELECT COUNT(*) FROM lancamentos").fetchone()[0] == 1


def test_editar_reabrir_excluir_e_restaurar(con_temp):
    lid = ok(con_temp, "criar_lancamento", {"escopo": "PF", "tipo": "saida", "data": HOJE, "valor": 80, "categoria": "Lazer",
                                            "pago_em": HOJE})["id"]
    r = ok(con_temp, "editar_lancamento", {"id": lid, "valor": 95.5, "pago_em": ""})
    assert r["antes"] == {"valor": 80.0, "pago_em": HOJE} and r["depois"] == {"valor": 95.5, "pago_em": None}
    assert "Categoria 'Lazer' não existe" in falha(con_temp, "editar_lancamento", {"id": lid, "escopo": "PJ"})   # Lazer é só da PF
    ok(con_temp, "dar_baixa", {"lancamento_id": lid})
    assert "já está pago" in falha(con_temp, "dar_baixa", {"lancamento_id": lid})
    ok(con_temp, "excluir_lancamento", {"id": lid})
    assert "não encontrado" in falha(con_temp, "editar_lancamento", {"id": lid, "valor": 1})
    ok(con_temp, "restaurar_lancamento", {"id": lid})
    assert con_temp.execute("SELECT valor, pago_em, excluido_em FROM lancamentos WHERE id=?", (lid,)).fetchone()[:] == (95.5, HOJE, None)


def test_conta_recorrente_paga_uma_vez_por_mes(con_temp):
    rid = ok(con_temp, "salvar_conta_recorrente", {"escopo": "PJ", "descricao": "Aluguel sala", "categoria": "Aluguel", "valor": 500,
                                                   "dia_vencimento": 5})["id"]
    assert "Salário" in falha(con_temp, "salvar_conta_recorrente", {"escopo": "PJ", "descricao": "x", "categoria": "Retirada",
                                                                     "valor": 1, "dia_vencimento": 5})
    r = ok(con_temp, "dar_baixa", {"recorrencia_id": rid, "competencia": HOJE[:7]})
    assert con_temp.execute("SELECT valor, competencia FROM lancamentos WHERE id=?", (r["id"],)).fetchone()[:] == (500.0, HOJE[:7])
    assert "já foi baixada" in falha(con_temp, "dar_baixa", {"recorrencia_id": rid, "competencia": HOJE[:7]})
    assert "competencia" in falha(con_temp, "dar_baixa", {"recorrencia_id": rid})
    alterada = ok(con_temp, "salvar_conta_recorrente", {"id": rid, "valor": 550})
    assert alterada["antes"]["valor"] == 500 and alterada["conta_recorrente"]["valor"] == 550
    ok(con_temp, "excluir_conta_recorrente", {"id": rid})
    assert ok(con_temp, "listar_contas_recorrentes", {})["contas_recorrentes"] == []


def test_saldo_salario_e_tarefas(con_temp):
    assert ok(con_temp, "atualizar_saldo", {"conta": "inter", "saldo": "-50,25"})["saldo"] == -50.25
    assert financeiro_saldo(con_temp, "Inter") == -50.25
    assert "salário" in falha(con_temp, "pagar_salario", {}).lower()
    chave = ok(con_temp, "criar_tarefa", {"texto": "ligar para o contador", "dia": 2})["chave"]
    ok(con_temp, "marcar_tarefa", {"chave": chave, "feito": True})
    rotina = {t["chave"]: t for t in ok(con_temp, "ver_tarefas", {})["rotina"]}
    assert rotina[chave]["feita"] and rotina[chave]["tarefa"] == "Terça: ligar para o contador"
    ok(con_temp, "marcar_tarefa", {"chave": chave, "feito": False})
    assert not {t["chave"]: t for t in ok(con_temp, "ver_tarefas", {})["rotina"]}[chave]["feita"]
    ok(con_temp, "excluir_tarefa", {"chave": chave})
    assert chave not in {t["chave"] for t in ok(con_temp, "ver_tarefas", {})["rotina"]}


def financeiro_saldo(con, conta):
    from app import financeiro
    return financeiro.saldos_atuais(con)[conta]["saldo"]


def test_registrar_no_aluno_usa_as_regras_da_ficha(con_temp):
    with con_temp:
        cid = con_temp.execute("INSERT INTO clientes (nome, valor, data_renovacao) VALUES ('Ana', 300, ?)", (HOJE,)).lastrowid
    r = ok(con_temp, "registrar_no_aluno", {"cliente_id": cid, "tipo": "pausa"})
    assert "Mês pulado" in r["mensagem"]
    assert "precisa ser um destes" in falha(con_temp, "registrar_no_aluno", {"cliente_id": cid, "tipo": "pagamento"})


def test_entrada_estranha_nao_derruba(con_temp):
    assert "objeto JSON" in falha(con_temp, "ver_painel", "texto")
    assert "desconhecida" in falha(con_temp, "apagar_tudo", {})
    assert "data AAAA-MM-DD" in falha(con_temp, "listar_lancamentos", {"de": "ontem"})


# ---------- tela ----------
def test_markdown_escapa_html():
    h = str(assistente.markdown_simples("**Total:** <script>x</script>\n\n- um\n- [Financeiro](/financeiro)\n"
                                        "- [mau](javascript:alert(1)) [fora](//site.com)"))
    assert "<script>" not in h and "&lt;script&gt;" in h
    assert "<strong>Total:</strong>" in h and "<ul><li>um</li>" in h
    assert '<a href="/financeiro">Financeiro</a>' in h
    assert 'href="javascript' not in h and 'href="//' not in h


def test_para_tela_esconde_data_e_resultados(con_temp):
    cid = assistente.criar_conversa(con_temp, "x")
    assistente._gravar(con_temp, cid, "user", [texto(assistente._com_data("quanto tenho?"))])
    assistente._gravar(con_temp, cid, "assistant", [pensou(), texto("Vou ver."), pede("saldos_das_contas", {})])
    assistente._gravar(con_temp, cid, "user", [{"type": "tool_result", "tool_use_id": "tu_1", "content": "{}"}])
    assistente._gravar(con_temp, cid, "assistant", [texto("R$ 10,00")])
    t = assistente.para_tela(con_temp, cid)
    assert t[0] == {"papel": "user", "texto": "quanto tenho?"}
    assert [p["tipo"] for p in t[1]["partes"]] == ["texto", "ferramenta", "texto"] and len(t) == 2


@pytest.fixture
def http(con_temp):
    return TestClient(main.app, base_url="http://localhost")


def eventos(r):
    return [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]


def test_tela_sem_chave_explica_como_ligar(http):
    r = http.get("/assistente")
    assert r.status_code == 200 and "Falta ligar o assistente" in r.text and "ANTHROPIC_API_KEY" in r.text
    ev = eventos(http.post("/assistente/enviar", data={"texto": "oi", "conversa": ""}))
    assert [e["tipo"] for e in ev] == ["erro", "fim"]
    assert http.get("/assistente/conversa/999").status_code == 404
    assert http.get("/assistente?c=999").url.path == "/assistente"


def test_sinal_de_vida_enquanto_o_modelo_pensa(http, monkeypatch):
    """Pelo celular passa pelo Cloudflare: conexão muda por muito tempo pode cair. A tela ignora o comentário."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    monkeypatch.setattr(assistente, "VIVO", 0.05)

    class Lento(ClienteFalso):
        def _stream(self, qual, params):
            fluxo = super()._stream(qual, params)
            time.sleep(0.4)   # pensando em silêncio
            return fluxo
    monkeypatch.setattr(assistente, "_cliente", lambda: Lento([resposta([texto("Oi")])]))
    r = http.post("/assistente/enviar", data={"texto": "oi", "conversa": ""})
    assert ": vivo" in r.text
    assert [e["tipo"] for e in eventos(r)] == ["conversa", "texto", "uso", "fim"]


def test_conversa_pela_tela(http, con_temp, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    c = ClienteFalso([resposta([texto("Você tem **R$ 10,00**.")])])
    monkeypatch.setattr(assistente, "_cliente", lambda: c)
    r = http.post("/assistente/enviar", data={"texto": "quanto tenho?", "conversa": ""})
    assert r.headers["content-type"].startswith("text/event-stream")
    ev = eventos(r)
    assert [e["tipo"] for e in ev] == ["conversa", "texto", "uso", "fim"] and ev[-1]["id"] == ev[0]["id"]
    cid = ev[0]["id"]
    frag = http.get(f"/assistente/conversa/{cid}")
    assert "<strong>R$ 10,00</strong>" in frag.text and "quanto tenho?" in frag.text and "(Hoje:" not in frag.text
    assert unquote(frag.headers["X-Custo"]) == "< US$ 0,01"   # 1.000 de entrada, 200 de saída, 5.000 no cache: US$ 0,000825
    tela = http.get(f"/assistente?c={cid}")
    assert tela.status_code == 200 and "quanto tenho?" in tela.text and "nesta conversa" in tela.text
    http.post(f"/assistente/{cid}/excluir")
    assert http.get(f"/assistente/conversa/{cid}").status_code == 404
    assert "Conversa do assistente" in http.get("/dados").text   # dá para restaurar na lixeira


# ---------- chave salva em Configurações ----------
CHAVE = "sk-" + "ant-teste-1234567890abcd"   # montada aqui para o teste de segredos não achar chave no código


def _stub_anthropic(monkeypatch):
    achados = {}
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: achados.update(kw) or object())
    return achados


def test_salvar_chave_liga_o_assistente_e_o_cliente_recebe_a_chave(http, monkeypatch):
    achados = _stub_anthropic(monkeypatch)
    assert not assistente.configurado()
    r = http.post("/configuracoes/assistente", data={"chave": f"  {CHAVE}  "}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    assert assistente.configurado() and assistente.origem_chave() == "config"
    assistente._cliente()
    assert achados["api_key"] == CHAVE


def test_tela_mostra_so_o_final_da_chave(http):
    http.post("/configuracoes/assistente", data={"chave": CHAVE})
    r = http.get("/configuracoes")
    assert "…abcd" in r.text and CHAVE not in r.text and "chave salva aqui" in r.text and "Remover a chave do Assistente?" in r.text
    assert assistente.info()["final"] == "…abcd"


def test_remover_chave_desliga(http, con_temp):
    http.post("/configuracoes/assistente", data={"chave": CHAVE})
    http.post("/configuracoes/assistente/remover")
    assert not assistente.configurado() and assistente.origem_chave() == ""
    assert con_temp.execute("SELECT COUNT(*) FROM segredos").fetchone()[0] == 0
    assert "Desligado" in http.get("/configuracoes").text


def test_chave_do_env_vence_a_salva(http, monkeypatch):
    achados = _stub_anthropic(monkeypatch)
    http.post("/configuracoes/assistente", data={"chave": CHAVE})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-" + "ant-do-env-9999")
    assert assistente.origem_chave() == "env" and assistente.info()["final"] == "…9999"
    assistente._cliente()
    assert "api_key" not in achados
    assert "chave do .env" in http.get("/configuracoes").text


def test_chave_invalida_e_recusada(http, con_temp):
    for ruim in ("abc", "sk-" + "ant-curta", "x" * 30):
        r = http.post("/configuracoes/assistente", data={"chave": ruim}, follow_redirects=False)
        assert r.status_code == 303 and "erro=" in r.headers["location"]
    assert not assistente.configurado()
    assert con_temp.execute("SELECT COUNT(*) FROM segredos").fetchone()[0] == 0


def test_consultar_banco_nao_le_segredos(http, con_temp):
    http.post("/configuracoes/assistente", data={"chave": CHAVE})
    for sql in ("SELECT * FROM segredos", "select valor from SEGREDOS"):
        assert "reservada" in falha(con_temp, "consultar_banco", {"sql": sql})


def test_carregar_chave_sem_a_tabela_nao_quebra(tmp_path):
    import sqlite3
    con = sqlite3.connect(tmp_path / "velho.db")
    assistente.carregar_chave(con)
    assert assistente._chave_salva["valor"] == "" and not assistente.configurado()
    con.close()


def test_carregar_chave_le_a_salva(con_temp):
    assistente.salvar_chave(con_temp, CHAVE)
    assistente._chave_salva["valor"] = ""
    assistente.carregar_chave(con_temp)
    assert assistente._chave_salva["valor"] == CHAVE
