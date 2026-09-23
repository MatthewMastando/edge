import type { Bar, BarSeries, Timeframe } from "../api/types";
import { BAR_COUNT, barOpenIso, DATA_REVISION } from "./ids";

interface SeriesSpec {
  instrumentId: string;
  contractCode: string | null;
  start: number;
  tick: number;
  decimals: number;
  wave: number;
}

const SPECS: Record<string, SeriesSpec> = {
  "6E": {
    instrumentId: "edd6f053-f27c-564d-a895-01e646752c32",
    contractCode: "6EZ6",
    start: 1.1732,
    tick: 0.00005,
    decimals: 5,
    wave: 0.0008,
  },
  "6EZ6": {
    instrumentId: "edd6f053-f27c-564d-a895-01e646752c32",
    contractCode: "6EZ6",
    start: 1.1732,
    tick: 0.00005,
    decimals: 5,
    wave: 0.0008,
  },
  GC: {
    instrumentId: "6acbb3f3-35c1-51e8-b38e-eae3c5993904",
    contractCode: "GCZ6",
    start: 3418.5,
    tick: 0.1,
    decimals: 1,
    wave: 1.6,
  },
  GCZ6: {
    instrumentId: "6acbb3f3-35c1-51e8-b38e-eae3c5993904",
    contractCode: "GCZ6",
    start: 3418.5,
    tick: 0.1,
    decimals: 1,
    wave: 1.6,
  },
  CL: {
    instrumentId: "496a1f76-dc59-56bb-a0bd-ac481ae08593",
    contractCode: "CLX6",
    start: 64.82,
    tick: 0.01,
    decimals: 2,
    wave: 0.18,
  },
  ES: {
    instrumentId: "2b0c2d97-32fd-54e1-9acc-b766eb879be3",
    contractCode: "ESZ6",
    start: 6512.25,
    tick: 0.25,
    decimals: 2,
    wave: 4,
  },
  SPY: {
    instrumentId: "47a2f827-2084-5938-b373-29662da1aaf8",
    contractCode: null,
    start: 649.37,
    tick: 0.01,
    decimals: 2,
    wave: 0.4,
  },
  "BTC-USD": {
    instrumentId: "b4664dca-7f0e-53e4-87a9-0f875cf14a5e",
    contractCode: null,
    start: 112840,
    tick: 0.01,
    decimals: 2,
    wave: 180,
  },
};

function align(price: number, tick: number, decimals: number): string {
  const factor = 10 ** decimals;
  const tickUnits = Math.round(tick * factor);
  const units = Math.round(price * factor);
  const aligned = Math.round(units / tickUnits) * tickUnits;
  const sign = aligned < 0 ? "-" : "";
  const abs = Math.abs(aligned);
  const whole = Math.floor(abs / factor);
  const frac = String(abs % factor).padStart(decimals, "0");
  return `${sign}${String(whole)}.${frac}`;
}

function candle(spec: SeriesSpec, index: number, open: number, high: number, low: number, close: number): Bar {
  return {
    instrument_id: spec.instrumentId,
    contract_code: spec.contractCode,
    timeframe: "5m",
    origin_time: barOpenIso(index),
    origin_tz: "America/Chicago",
    open: align(open, spec.tick, spec.decimals),
    high: align(high, spec.tick, spec.decimals),
    low: align(low, spec.tick, spec.decimals),
    close: align(close, spec.tick, spec.decimals),
    volume: String(8 + (index % 5)),
    trade_count: 8 + (index % 5),
    vwap: align((high + low + close) / 3, spec.tick, spec.decimals),
    is_complete: true,
    data_revision: DATA_REVISION,
    provenance: "fixture",
  };
}

/**
 * Deterministic 5-minute candles. The 6E path includes a three-bar bullish gap so the
 * fair-value-gap primitive sits on real candles: low(C) > high(A).
 */
export function buildBars(symbol: string, timeframe: Timeframe = "5m"): BarSeries | null {
  const spec = SPECS[symbol];
  if (!spec || timeframe !== "5m") return null;
  const bars: Bar[] = [];
  for (let index = 0; index < BAR_COUNT; index += 1) {
    const mid = spec.start + Math.sin(index / 5) * spec.wave + index * spec.wave * 0.01;
    const open = mid - spec.wave * 0.15;
    const close = mid + spec.wave * 0.1 * (index % 2 === 0 ? 1 : -1);
    const high = Math.max(open, close) + spec.wave * 0.2;
    const low = Math.min(open, close) - spec.wave * 0.2;
    bars.push(candle(spec, index, open, high, low, close));
  }
  if (symbol === "6E" || symbol === "6EZ6") {
    bars[24] = candle(spec, 24, 1.1728, 1.173, 1.1724, 1.1726);
    bars[25] = candle(spec, 25, 1.1727, 1.1742, 1.1727, 1.174);
    bars[26] = candle(spec, 26, 1.174, 1.1744, 1.1735, 1.1741);
  }
  return {
    instrument_id: spec.instrumentId,
    contract_code: spec.contractCode,
    timeframe,
    bars,
    data_revision: DATA_REVISION,
    provenance: "fixture",
  };
}
