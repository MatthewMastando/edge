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
