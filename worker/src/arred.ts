/**
 * round(x, n) do Python, igual centavo por centavo: decide pelo valor exato do número (2.675 vira 2.67, porque
 * o double guardado é 2.67499...) e, no empate exato (0.125), arredonda para o dígito par (0.12).
 * Math.round(x * 100) / 100 erra nos dois casos.
 */
const POT = [1, 10, 100, 1000, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9, 1e10];

export function arred(x: number, n = 2): number {
  if (!Number.isFinite(x) || x === 0) return x;
  // Caminho rápido (quase sempre): longe do meio entre dois centavos, x * 10^n arredondado é exato.
  // A conta x * 10^n erra no máximo meio ulp; 1e-9 * |y| fica muito acima disso.
  const p = POT[n];
  if (p !== undefined) {
    const y = x * p;
    if (Math.abs(y) < 2 ** 52) {
      const f = y - Math.floor(y);
      if (Math.abs(f - 0.5) > 1e-9 * Math.max(1, Math.abs(y))) {
        const r = Math.round(y);
        return (r === 0 ? (x < 0 ? -0 : 0) : r) / p;
      }
    } else return x;
  }
  const sinal = x < 0 ? "-" : "";
  // toFixed é exato sobre o valor guardado; 30 casas além bastam para ver se depois do 5 vem algo (valores de dinheiro).
  const [inteiro, frac = ""] = Math.abs(x).toFixed(Math.min(100, n + 30)).split(".");
  const manter = frac.slice(0, n);
  const resto = frac.slice(n);
  let digitos = inteiro + manter;
  let sobe: boolean;
  if (resto[0] > "5") sobe = true;
  else if (resto[0] < "5") sobe = false;
  else sobe = /[1-9]/.test(resto.slice(1)) || Number(digitos[digitos.length - 1]) % 2 === 1;
  if (sobe) {
    const d = digitos.split("");
    let i = d.length - 1;
    while (i >= 0 && d[i] === "9") d[i--] = "0";
    if (i < 0) d.unshift("1");
    else d[i] = String(Number(d[i]) + 1);
    digitos = d.join("");
  }
  const corte = digitos.length - n;
  const txt = n > 0 ? `${digitos.slice(0, corte)}.${digitos.slice(corte)}` : digitos;
  return Number(sinal + txt); // como no Python, round(-0.001, 2) é -0.0
}
