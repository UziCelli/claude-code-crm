"""Importação da planilha real (se existir): rodar 2x não duplica e não altera o arquivo."""
import os

import pytest

from app import db, importar


@pytest.mark.skipif(not db.PLANILHA.exists(), reason="planilha não encontrada")
def test_importar_duas_vezes_nao_duplica(tmp_path):
    banco = tmp_path / "crm.db"
    db.iniciar_banco(banco)
    con = db.conectar(banco)
    mtime = os.path.getmtime(db.PLANILHA)

    r1 = importar.importar_tudo(con, db.PLANILHA)
    contagem = lambda: {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
                        for t in ("clientes", "precos_base", "grade_slots", "gastos_marketing", "parametros")}
    antes = contagem()
    r2 = importar.importar_tudo(con, db.PLANILHA)

    assert r1["Clientes"]["inseridos"] > 0 and r2["Clientes"]["inseridos"] == 0
    assert r2["Grade de horários"]["inseridos"] == 0
    assert contagem() == antes
    assert os.path.getmtime(db.PLANILHA) == mtime, "a planilha foi modificada"
    # campos só do CRM não são sobrescritos pela reimportação
    con.execute("UPDATE clientes SET telefone='11 99999-0000', data_renovacao='2026-10-01' WHERE planilha_id=1")
    con.commit()
    importar.importar_tudo(con, db.PLANILHA)
    c = con.execute("SELECT telefone, data_renovacao FROM clientes WHERE planilha_id=1").fetchone()
    assert (c["telefone"], c["data_renovacao"]) == ("11 99999-0000", "2026-10-01")
    # horas da grade vieram certas (05h–23h) e canais mapeados
    assert con.execute("SELECT MIN(hora), MAX(hora) FROM grade_slots").fetchone()[:] == (5, 23)
    canais = {r[0] for r in con.execute("SELECT DISTINCT canal_origem FROM clientes")}
    assert "CLT" not in canais and canais <= set(db.LISTAS_INICIAIS["lista_canais"]) | {None}