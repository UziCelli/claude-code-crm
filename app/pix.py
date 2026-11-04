"""Pix copia-e-cola (BR Code / EMV do BACEN) e QR Code, sem chamar serviço externo."""
import unicodedata

import segno


def crc16(texto: str) -> str:
    """CRC16-CCITT-FALSE (poly 0x1021, início 0xFFFF), em 4 dígitos hexa maiúsculos."""
    crc = 0xFFFF
    for byte in texto.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def _campo(idc: str, valor: str) -> str:
    return f"{idc}{len(valor):02d}{valor}"


def _limpo(texto: str, limite: int) -> str:
    """Sem acento, maiúsculo, só ASCII imprimível e no tamanho máximo do campo."""
    sem = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sem.upper().split())[:limite].strip()


def br_code(chave: str, nome: str, cidade: str, valor: float | None = None) -> str:
    """Código Pix estático. Devolve "" se faltar chave, favorecido ou cidade."""
    chave, nome, cidade = (chave or "").strip(), _limpo(nome, 25), _limpo(cidade, 15)
    if not (chave and nome and cidade):
        return ""
    conta = _campo("00", "br.gov.bcb.pix") + _campo("01", chave)
    corpo = (_campo("00", "01") + _campo("26", conta) + _campo("52", "0000") + _campo("53", "986")
             + (_campo("54", f"{valor:.2f}") if valor and valor > 0 else "")
             + _campo("58", "BR") + _campo("59", nome) + _campo("60", cidade)
             + _campo("62", _campo("05", "***")) + "6304")
    return corpo + crc16(corpo)


def qr_matriz(texto: str) -> list[list[bool]]:
    return [[bool(m) for m in linha] for linha in segno.make(texto, error="m").matrix]


def qr_caminho(texto: str) -> tuple[str, int]:
    """O QR como um `d` de <path> (um quadrado de 1x1 por módulo escuro) e o lado em módulos."""
    matriz = qr_matriz(texto)
    partes = [f"M{x} {y}h1v1h-1z" for y, linha in enumerate(matriz) for x, m in enumerate(linha) if m]
    return "".join(partes), len(matriz)


def qr_svg(texto: str) -> str:
    d, lado = qr_caminho(texto)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-4 -4 {lado + 8} {lado + 8}">'
            f'<rect x="-4" y="-4" width="{lado + 8}" height="{lado + 8}" fill="#fff"/>'
            f'<path d="{d}" fill="#000"/></svg>')
