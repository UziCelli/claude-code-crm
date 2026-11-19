/** Pix copia-e-cola (BR Code / EMV do BACEN), port de app/pix.py. O QR Code entra com o cartão de cobrança. */
import { arred } from "../arred.ts";
import { semAcento } from "./texto.ts";

/** CRC16-CCITT-FALSE (poly 0x1021, início 0xFFFF), em 4 dígitos hexa maiúsculos, sobre os bytes UTF-8. */
export function crc16(texto: string): string {
  let crc = 0xffff;
  for (const byte of new TextEncoder().encode(texto)) {
    crc ^= byte << 8;
    for (let i = 0; i < 8; i++) crc = (crc & 0x8000 ? (crc << 1) ^ 0x1021 : crc << 1) & 0xffff;
  }
  return crc.toString(16).toUpperCase().padStart(4, "0");
}

/** Campo EMV: id + tamanho (em caracteres, como o len() do Python) + valor. */
function campo(id: string, valor: string): string {
  return `${id}${String(Array.from(valor).length).padStart(2, "0")}${valor}`;
}

/** Sem acento, maiúsculo, só ASCII e no tamanho máximo do campo. */
function limpo(texto: string | null | undefined, limite: number): string {
  return Array.from(semAcento(texto ?? "").toUpperCase().split(/\s+/).filter(Boolean).join(" ")).slice(0, limite).join("").trim();
}

/** Código Pix estático. "" se faltar chave, favorecido ou cidade. */
export function brCode(chaveBruta: string | null | undefined, nomeBruto: string | null | undefined, cidadeBruta: string | null | undefined,
  valor?: number | null): string {
  const chave = (chaveBruta ?? "").trim(), nome = limpo(nomeBruto, 25), cidade = limpo(cidadeBruta, 15);
  if (!(chave && nome && cidade)) return "";
  const conta = campo("00", "br.gov.bcb.pix") + campo("01", chave);
  const corpo = campo("00", "01") + campo("26", conta) + campo("52", "0000") + campo("53", "986")
    + (valor && valor > 0 ? campo("54", arred(valor, 2).toFixed(2)) : "")
    + campo("58", "BR") + campo("59", nome) + campo("60", cidade) + campo("62", campo("05", "***")) + "6304";
  return corpo + crc16(corpo);
}
