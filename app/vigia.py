"""Vigia do CRM no PC: se o servidor cair, religa sozinho (o celular não fica em erro 502).

Roda como processo separado e sem janela (`pythonw -m app.vigia`), ligado pelo iniciar-crm.bat /servidor.
A cada minuto confere a porta; se estiver fechada, abre o CRM pelo iniciar-crm.bat /servidor.
Não religa se o botão Encerrar foi clicado (data/desligado.txt) nem no meio de uma atualização (data/atualizando.txt).
Só biblioteca padrão. Log em data/atualizacao.log."""
import os
import time

from . import atualizar

DATA = atualizar.DATA
DESLIGADO = DATA / "desligado.txt"               # criado pelo botão Encerrar; o atalho do CRM apaga
ATUALIZANDO = atualizar.ATUALIZANDO              # criado pelo ajudante da atualização automática
TRAVA = DATA / "vigia.pid"                       # PID do vigia que está rodando (só um por vez)
INTERVALO = 60                                   # segundos entre uma conferida e outra
ATUALIZANDO_MAX = 15 * 60                        # arquivo de atualização mais velho que isso sobrou de um erro: ignora
FORA_MIN = 2                                     # só religa depois de 2 conferidas seguidas fora (o CRM pode levar até 2 min para subir)
fora = 0


def atualizando():
    try:
        return time.time() - ATUALIZANDO.stat().st_mtime < ATUALIZANDO_MAX
    except OSError:
        return False


def rodada():
    """Uma conferida. Devolve True se tentou religar o CRM."""
    global fora
    try:
        if atualizar.porta_ocupada() or DESLIGADO.exists() or atualizando():
            fora = 0
            return False
        fora += 1
        if fora < FORA_MIN:
            return False
        fora = 0
        if atualizar.abrir_crm():
            atualizar.log("vigia: o CRM estava fora; religado")
        else:
            atualizar.log("vigia: o CRM estava fora e não religou; veja data/crm-erro.log")
        return True
    except Exception as e:  # noqa: BLE001 — o vigia nunca pode morrer
        atualizar.log(f"vigia: erro na conferida: {e}")
        return False


def processo_vivo(pid):
    if pid <= 0:
        return False
    if atualizar.WINDOWS:
        import ctypes   # os.kill(pid, 0) no Windows ENCERRA o processo: aqui só pergunta se ainda está rodando
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        codigo = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(codigo))
        k.CloseHandle(h)
        return bool(ok) and codigo.value == 259   # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True   # existe, é de outro usuário
    except OSError:
        return False
    return True


def assumir_trava():
    """False se já existe outro vigia vivo; senão grava o PID deste e devolve True."""
    try:
        if processo_vivo(int(TRAVA.read_text(encoding="utf-8").strip())):
            return False
    except (OSError, ValueError):
        pass   # sem arquivo ou com lixo: ninguém está vigiando
    try:
        DATA.mkdir(exist_ok=True)
        TRAVA.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    return True


def laco():
    if not assumir_trava():
        return
    atualizar.log("vigia: ligado")
    while True:
        time.sleep(INTERVALO)   # o iniciar-crm.bat acabou de ligar o servidor: espera antes da primeira conferida
        rodada()


if __name__ == "__main__":
    laco()
