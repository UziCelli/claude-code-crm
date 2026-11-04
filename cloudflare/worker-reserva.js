// Worker do Cloudflare: crm-reserva.vfitcoachapp.com -> CRM no Google Cloud Run.
// O Cloudflare Access fica na frente (pede o e-mail e o código). Este Worker só repassa o pedido, com os cabeçalhos
// e o cookie do Access, e o CRM confere o token de novo (app/acesso.py). Passo a passo no README ("Reserva: Google Cloud Run").
//
// Troque o endereço abaixo pela URL que o Cloud Run mostra no topo do serviço (termina em .run.app).
const CLOUD_RUN = "https://COLE-AQUI-A-URL.run.app";

export default {
  async fetch(pedido) {
    const de = new URL(pedido.url);
    const para = new URL(de.pathname + de.search, CLOUD_RUN);
    // redirect "manual": o navegador segue os redirecionamentos do CRM, que são relativos e continuam no crm-reserva
    return fetch(new Request(para, pedido), { redirect: "manual" });
  },
};
