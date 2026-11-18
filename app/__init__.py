"""Fuso do Brasil para o app inteiro: no servidor da nuvem o relógio vem em UTC e "hoje" virava amanhã depois das 21h.
A data de hoje sai de app/relogio.py (zoneinfo), que não depende disto; aqui fica só o fuso do SQLite local e dos logs.
No Windows a variável TZ com nome de fuso ("America/Sao_Paulo") é lida como UTC pelo C do Windows: lá ela não é usada."""
import os
import time

if hasattr(time, "tzset"):   # Linux/macOS (nuvem): entende o nome do fuso
    os.environ.setdefault("TZ", "America/Sao_Paulo")
    time.tzset()
elif "/" in os.environ.get("TZ", ""):   # Windows com TZ de nome IANA: viraria UTC; o Windows já sabe o fuso do PC
    del os.environ["TZ"]
