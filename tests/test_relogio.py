"""Relógio do Brasil: depois das 21h o "hoje" continua sendo hoje, em qualquer servidor (Windows, nuvem em UTC)."""
import datetime as dt
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from app import db, main, relogio

UTC = dt.timezone.utc


@pytest.fixture
def noite(monkeypatch):
    """Quarta, 18/11/2026, 21:30 em Brasília = quinta 00:30 em UTC."""
    monkeypatch.setattr(relogio, "_utc", lambda: dt.datetime(2026, 11, 19, 0, 30, tzinfo=UTC))


def test_hoje_depois_das_21h_ainda_e_hoje(noite):
    assert relogio.hoje() == dt.date(2026, 11, 18)
    assert relogio.agora() == dt.datetime(2026, 11, 18, 21, 30)
    assert relogio.agora_txt() == "2026-11-18 21:30:00"


def test_virada_so_a_meia_noite(monkeypatch):
    monkeypatch.setattr(relogio, "_utc", lambda: dt.datetime(2026, 11, 19, 2, 59, tzinfo=UTC))   # 23:59 em Brasília
    assert relogio.hoje() == dt.date(2026, 11, 18)
    monkeypatch.setattr(relogio, "_utc", lambda: dt.datetime(2026, 11, 19, 3, 0, tzinfo=UTC))    # 00:00 em Brasília
    assert relogio.hoje() == dt.date(2026, 11, 19)


def test_agenda_as_21h30_mostra_o_dia_de_hoje(noite, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "crm.db")
    monkeypatch.setattr(db, "BACKUP_DIR", tmp_path / "backups")
    db.iniciar_banco()
    assert main.mes_atual() == "2026-11"
    html = TestClient(main.app, base_url="http://localhost").get("/agenda").text
    assert "16/11" in html and "21/11" in html   # a semana de segunda 16 a sábado 21, não a seguinte
    assert main.agora_txt() == "2026-11-18 21:30:00"


def test_ninguem_usa_o_relogio_do_sistema():
    """A data de hoje sai só do app/relogio.py (nuvem.py só mede intervalos, o fuso não importa lá)."""
    pasta = pathlib.Path(__file__).resolve().parent.parent / "app"
    achados = [f"{p.name}:{n}" for p in pasta.glob("*.py") if p.name not in ("relogio.py", "nuvem.py")
               for n, linha in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
               if re.search(r"\bdate\.today\(\)|\bdatetime\.now\(\)", linha)]
    assert achados == []


def test_requirements_tem_a_base_de_fusos():
    """No Windows o zoneinfo precisa do pacote tzdata (o Windows não traz a base de fusos)."""
    texto = (pathlib.Path(__file__).resolve().parent.parent / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^tzdata\b", texto, re.M)


def test_windows_nao_fica_com_tz_de_nome_iana(monkeypatch):
    """No Windows (sem time.tzset) TZ="America/Sao_Paulo" vira UTC no C do Windows: o app tira a variável."""
    import os
    import runpy
    import time
    monkeypatch.delattr(time, "tzset")
    monkeypatch.setenv("TZ", "America/Sao_Paulo")
    runpy.run_path(str(pathlib.Path(__file__).resolve().parent.parent / "app" / "__init__.py"))
    assert "TZ" not in os.environ
