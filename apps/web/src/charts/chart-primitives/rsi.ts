/** Wilder RSI. Seed is the first `period` gains and losses; later values use (n-1)*prior + current. */
export function wilderRsi(closes: readonly number[], period = 14): (number | null)[] {
  const out: (number | null)[] = Array.from({ length: closes.length }, () => null);
  if (closes.length <= period || period < 1) return out;

  let gain = 0;
  let loss = 0;
  for (let index = 1; index <= period; index += 1) {
    const previous = closes[index - 1];
    const current = closes[index];
    if (previous === undefined || current === undefined) return out;
    const change = current - previous;
    if (change > 0) gain += change;
    else loss -= change;
  }

  let avgGain = gain / period;
  let avgLoss = loss / period;
  const first = rsiFromAverages(avgGain, avgLoss);
  out[period] = first;

  for (let index = period + 1; index < closes.length; index += 1) {
    const previous = closes[index - 1];
    const current = closes[index];
    if (previous === undefined || current === undefined) break;
    const change = current - previous;
    const up = change > 0 ? change : 0;
    const down = change < 0 ? -change : 0;
    avgGain = (avgGain * (period - 1) + up) / period;
    avgLoss = (avgLoss * (period - 1) + down) / period;
    out[index] = rsiFromAverages(avgGain, avgLoss);
  }
  return out;
}

function rsiFromAverages(avgGain: number, avgLoss: number): number {
  if (avgGain === 0 && avgLoss === 0) return 50;
  if (avgLoss === 0) return 100;
  if (avgGain === 0) return 0;
  const relative = avgGain / avgLoss;
  return 100 - 100 / (1 + relative);
}
