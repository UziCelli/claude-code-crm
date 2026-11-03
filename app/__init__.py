"""Fuso do Brasil para o app inteiro: no servidor (Render) o relógio vem em UTC e "hoje" virava amanhã depois das 21h."""
import os
import time

os.environ.setdefault("TZ", "America/Sao_Paulo")
if hasattr(time, "tzset"):
    time.tzset()
