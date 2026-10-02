"""Exportação para .xlsx e .csv (clientes, leads, propostas, métricas)."""
import io

import openpyxl

CONSULTAS = {
    "clientes": """SELECT id, nome, telefone, local, tipo_servico, plano, pessoas, dias_horarios, valor, forma_pagamento, status,
                   canal_origem, data_inicio, data_renovacao, observacoes FROM clientes WHERE excluido_em IS NULL ORDER BY nome""",
    "leads": """SELECT id, nome, telefone, canal_origem, etapa, motivo_perda, interesse, proxima_acao, data_proxima_acao,
                data_entrada, data_mudanca_etapa, observacoes FROM leads WHERE excluido_em IS NULL ORDER BY id""",
    "propostas": """SELECT p.id, p.data, l.nome AS lead, c.nome AS cliente, p.tipo_servico, p.qtd_aulas, p.freq_semanal, p.local,
                    p.forma_pagamento, p.pessoas, p.dia, p.hora, p.desconto, p.preco_total, p.preco_pessoa, p.custo_total, p.lucro,
                    p.margem, p.lucro_hora, p.preco_minimo, p.status, p.observacoes FROM propostas p
                    LEFT JOIN leads l ON l.id=p.lead_id LEFT JOIN clientes c ON c.id=p.cliente_id
                    WHERE p.excluido_em IS NULL ORDER BY p.id""",
}


def tabela(con, nome):
    if nome not in CONSULTAS:
        raise ValueError(nome)
    cur = con.execute(CONSULTAS[nome])
    return [d[0] for d in cur.description], [tuple(r) for r in cur.fetchall()]


def de_dicts(rows):
    if not rows:
        return [], []
    cab = list(rows[0].keys())
    return cab, [tuple(r.get(k) for k in cab) for r in rows]


def xlsx(cab, linhas, titulo="dados") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = titulo[:30]
    ws.append(cab)
    for l in linhas:
        ws.append(list(l))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
