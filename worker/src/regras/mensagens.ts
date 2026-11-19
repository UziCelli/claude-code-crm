/** Dados das mensagens do WhatsApp (port de main.dados_mensagem). */
import type { Banco } from "../banco/banco.ts";
import { parametros } from "./parametros.ts";
import { doAluno } from "./vantagens.ts";

export interface DadosMsg { pix: string; pix_nome: string; pix_cidade: string; pix_banco: string; link_avaliacao: string; vantagem: string }

/** {pix, pix_nome, pix_cidade, pix_banco, link_avaliacao, vantagem} de Configurações > Dados das mensagens. */
export async function dadosMensagem(b: Banco): Promise<DadosMsg> {
  const [d, vantagem] = await Promise.all([parametros(b, "msg_dados"), doAluno(b, null)]);
  const t = (k: string) => String(d[k] ?? "").trim();
  return { pix: t("pix"), pix_nome: t("pix_nome"), pix_cidade: t("pix_cidade"), pix_banco: t("pix_banco"), link_avaliacao: t("link_avaliacao"), vantagem };
}

