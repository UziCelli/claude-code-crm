"""Atualização automática do CRM no PC: o PC não precisa mais de `git pull` na mão.

A cada 15 minutos confere a `main` no GitHub. Se houver versão nova, espera o CRM ficar 5 minutos sem uso,
baixa (git) e reinicia pelo iniciar-crm.bat (que instala bibliotecas novas, se houver). Se a versão nova não abrir,
volta para a anterior e não tenta mais aquela versão (data/atualizacao-recusada.txt).

Só liga no Windows, fora do Render, com a pasta clonada pelo git. Para desligar: CRM_AUTOATUALIZAR=0 no .env.
Só biblioteca padrão: o ajudante (`python -m app.atualizar reiniciar <commit>`) roda com o CRM fechado."""
import datetime as dt
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

PASTA = Path(__file__).resolve().parent.parent
DATA = PASTA / "data"
RECUSADA = DATA / "atualizacao-recusada.txt"
LOG = DATA / "atualizacao.log"
ATUALIZANDO = DATA / "atualizando.txt"   # existe enquanto o ajudante troca de versão: o vigia não religa por cima
RAMO = "main"
PORTA = 8765
INTERVALO = 15 * 60       # entre uma conferida e outra
ESPERA_INICIAL = 2 * 60   # depois de abrir o CRM
OCIOSO = 5 * 60           # sem ninguém usando há esse tempo: pode reiniciar
WINDOWS = os.name == "nt"
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # no Windows: git e o ajudante sem piscar janela preta

status = {"mostrar": False, "ligado": False, "motivo": "", "ultima": None, "versao": "", "pendente": False, "erro": None}
ultimo_uso = time.monotonic()


def registrar_uso():
    global ultimo_uso
    ultimo_uso = time.monotonic()


def log(texto):
    print("atualização:", texto, flush=True)
    try:
        DATA.mkdir(exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {texto}\n")
    except OSError:
        pass


def _git(*args, pasta=None):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}   # nunca parar esperando senha
    return subprocess.run(["git", *args], cwd=pasta or PASTA, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=120, env=env, stdin=subprocess.DEVNULL, creationflags=SEM_JANELA)


ERROS_GIT = [   # (trecho da mensagem do git, explicação)
    (("could not resolve host", "unable to access", "timed out", "connection"), "sem internet ou GitHub fora do ar; tenta de novo em 15 minutos"),
    (("authentication", "could not read username", "permission denied", "repository not found"),
     "o git deste PC perdeu o login do GitHub (rode git pull na pasta do CRM uma vez)"),
    (("would be overwritten", "local changes"), "tem arquivo mudado neste PC que a versão nova também muda (rode git status na pasta do CRM)"),
]


def git(*args, pasta=None):
    r = _git(*args, pasta=pasta)
    if r.returncode != 0:
        texto = (r.stderr or r.stdout).strip()
        for trechos, explicacao in ERROS_GIT:
            if any(t in texto.lower() for t in trechos):
                raise RuntimeError(explicacao)
        raise RuntimeError(texto.splitlines()[-1] if texto else f"git {args[0]} falhou")
    return r.stdout.strip()


def motivo_desligado():
    if os.environ.get("CRM_NUVEM") == "1":
        return "no Render quem atualiza é o próprio Render"
    if not WINDOWS:
        return "só no PC com Windows"
    if os.environ.get("CRM_AUTOATUALIZAR", "").strip() == "0":
        return "desligada no .env (CRM_AUTOATUALIZAR=0)"
    if not (PASTA / ".git").exists():
        return "a pasta do CRM não foi baixada pelo git"
    if not shutil.which("git"):
        return "o git não está instalado neste PC"
    return ""


def conferir(pasta=None):
    """Busca a main no GitHub. Devolve o commit novo (só avançar, sem conflito) ou None se já está em dia."""
    if git("rev-parse", "--abbrev-ref", "HEAD", pasta=pasta) != RAMO:
        raise RuntimeError(f"a pasta do CRM não está no ramo {RAMO} (rode: git checkout {RAMO})")
    git("fetch", "--quiet", "origin", RAMO, pasta=pasta)
    atual = git("rev-parse", "HEAD", pasta=pasta)
    novo = git("rev-parse", f"origin/{RAMO}", pasta=pasta)
    status["versao"] = atual[:7]
    if novo == atual:
        return None
    if _git("merge-base", "--is-ancestor", "HEAD", f"origin/{RAMO}", pasta=pasta).returncode != 0:
        raise RuntimeError("o PC tem mudanças próprias que não estão no GitHub (rode git status na pasta do CRM)")
    try:
        if RECUSADA.read_text(encoding="utf-8").strip() == novo:
            raise RuntimeError(f"a versão {novo[:7]} não abriu neste PC; o CRM ficou na anterior e espera a próxima")
    except OSError:
        pass
    return novo


def rodada():
    """Uma conferida. Devolve quantos segundos esperar até a próxima, ou None se já mandou reiniciar."""
    try:
        novo = conferir()
        status.update(ultima=dt.datetime.now(), pendente=bool(novo), erro=None)
        if not novo:
            return INTERVALO
        if time.monotonic() - ultimo_uso < OCIOSO:
            return 60   # tem versão nova: espera ninguém estar usando
        antigo = git("rev-parse", "HEAD")
        git("merge", "--ff-only", "--quiet", f"origin/{RAMO}")
        log(f"atualizado de {antigo[:7]} para {novo[:7]}; reiniciando o CRM")
        reiniciar(antigo)
        return None
    except Exception as e:  # noqa: BLE001 — sem internet, sem login no GitHub etc.: tenta de novo depois
        if str(e) != status["erro"]:
            log(f"não deu para atualizar: {e}")
        status.update(ultima=dt.datetime.now(), erro=str(e))
        return INTERVALO


def _laco():
    time.sleep(ESPERA_INICIAL)
    while (espera := rodada()) is not None:
        time.sleep(espera)


def iniciar():
    motivo = motivo_desligado()
    status.update(mostrar=WINDOWS and os.environ.get("CRM_NUVEM") != "1", ligado=not motivo, motivo=motivo)
    if not motivo:
        threading.Thread(target=_laco, name="atualizar", daemon=True).start()


def reiniciar(antigo):
    """Liga o ajudante (processo separado, sem janela), que espera este CRM fechar e abre de novo; depois fecha este."""
    subprocess.Popen([sys.executable, "-m", "app.atualizar", "reiniciar", antigo], cwd=PASTA,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                     creationflags=SEM_JANELA | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    threading.Timer(1.0, signal.raise_signal, (signal.SIGINT,)).start()   # mesmo desligamento do botão Encerrar


# ---------- ajudante: roda com o CRM fechado ----------
def porta_ocupada():
    try:
        with socket.create_connection(("127.0.0.1", PORTA), timeout=1):
            return True
    except OSError:
        return False


def abrir_crm():
    """iniciar-crm.bat /servidor: instala bibliotecas novas, liga sem janela e confere se respondeu (código 0)."""
    DATA.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as saida:   # arquivo, não pipe: o servidor herda a saída e nunca a fecha
        r = subprocess.run(["cmd", "/c", str(PASTA / "iniciar-crm.bat"), "/servidor"], cwd=PASTA, stdin=subprocess.DEVNULL,
                           stdout=saida, stderr=subprocess.STDOUT, creationflags=SEM_JANELA, timeout=900)
    return r.returncode == 0


def ajudante(antigo):
    try:
        DATA.mkdir(exist_ok=True)
        ATUALIZANDO.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    try:
        _trocar(antigo)
    finally:
        ATUALIZANDO.unlink(missing_ok=True)


def _trocar(antigo):
    for _ in range(240):   # até 2 minutos para o CRM antigo fechar
        if not porta_ocupada():
            break
        time.sleep(0.5)
    else:
        log("o CRM antigo não fechou em 2 minutos")
    if abrir_crm():
        log("CRM reiniciado com a versão nova")
        return
    novo = git("rev-parse", "HEAD")
    log(f"a versão {novo[:7]} não abriu; voltando para {antigo[:7]}")
    try:
        git("reset", "--keep", antigo)
        RECUSADA.write_text(novo, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log(f"não consegui voltar para a versão anterior: {e}")
    if not abrir_crm():
        log("o CRM não abriu; veja data/crm-erro.log")


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "reiniciar":
    ajudante(sys.argv[2])
