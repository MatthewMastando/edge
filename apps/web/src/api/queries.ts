import { useQuery } from "@tanstack/react-query";

import { api } from "./client";
import type { Timeframe } from "./types";

function unwrap<T>(response: { data?: T; response: Response }, label: string): T {
  if (!response.response.ok || response.data === undefined) {
    throw new Error(`${label} failed (${String(response.response.status)})`);
  }
  return response.data;
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async () => unwrap(await api.GET("/health"), "Health"),
  });
}

export function useInstruments() {
  return useQuery({
    queryKey: ["instruments"],
    queryFn: async () => unwrap(await api.GET("/v1/instruments"), "Instruments"),
  });
}

export function useContracts() {
  return useQuery({
    queryKey: ["futures-contracts"],
    queryFn: async () => unwrap(await api.GET("/v1/futures-contracts"), "Futures contracts"),
  });
}

export function useSnapshots() {
  return useQuery({
    queryKey: ["snapshots"],
    queryFn: async () => unwrap(await api.GET("/v1/snapshots"), "Snapshots"),
  });
}

export function useCapabilities() {
  return useQuery({
    queryKey: ["capabilities"],
    queryFn: async () => unwrap(await api.GET("/v1/capabilities"), "Capabilities"),
  });
}

export function useImportPresets() {
  return useQuery({
    queryKey: ["import-presets"],
    queryFn: async () => unwrap(await api.GET("/v1/import/presets"), "Import presets"),
  });
}

export function useImportedFills(assetClass: string | null, symbol: string | null) {
  return useQuery({
    queryKey: ["trading-fills", assetClass, symbol],
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/trading/fills", {
          params: {
            query: {
              asset_class: assetClass ?? undefined,
              symbol: symbol ?? undefined,
              limit: 500,
            },
          },
        }),
        "Imported fills",
      ),
  });
}

export function useTradingSummary(assetClass: string | null, symbol: string | null) {
  return useQuery({
    queryKey: ["trading-summary", assetClass, symbol],
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/trading/summary", {
          params: {
            query: { asset_class: assetClass ?? undefined, symbol: symbol ?? undefined },
          },
        }),
        "Trading summary",
      ),
  });
}

export function useKalshiMarkets() {
  return useQuery({
    queryKey: ["kalshi-markets"],
    queryFn: async () => unwrap(await api.GET("/v1/kalshi/markets"), "Kalshi markets"),
  });
}

export function useKalshiBrief(ticker: string | null) {
  return useQuery({
    queryKey: ["kalshi-brief", ticker],
    enabled: ticker !== null,
    queryFn: async () => {
      if (!ticker) throw new Error("Ticker required");
      return unwrap(
        await api.GET("/v1/kalshi/markets/{ticker}/brief", { params: { path: { ticker } } }),
        "Kalshi brief",
      );
    },
  });
}

export function useBars(symbol: string | null, timeframe: Timeframe = "5m") {
  return useQuery({
    queryKey: ["bars", symbol, timeframe],
    enabled: symbol !== null,
    queryFn: async () => {
      if (!symbol) throw new Error("Symbol is required");
      return unwrap(await api.GET("/v1/bars", { params: { query: { symbol, timeframe } } }), "Bars");
    },
  });
}
