import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { FuturesContract, HealthResponse } from "./api/types";

const health: HealthResponse = {
  status: "ok",
  service: "trading-api",
  version: "0.1.0",
  mode: "fixture",
  provenance: "fixture",
  fixtures_loaded: true,
  data_revision: "fixture-1.0.0-s20260923-e593616b",
  order_write_capability: false,
};

const contract: FuturesContract = {
  id: "3614dae1-0db5-5de0-a5fd-0484316a0c45",
  instrument_id: "6acbb3f3-35c1-51e8-b38e-eae3c5993904",
  root: "GC",
  contract_code: "GCZ6",
  exchange: "COMEX",
  contract_month: "2026-12",
  expiry_date: "2026-12-29",
  last_trade_date: "2026-12-29",
  first_notice_date: "2026-11-30",
  tick_size: "0.10",
  tick_value: "10.00",
  point_multiplier: "100",
  currency: "USD",
  session_calendar_id: "comex_globex_metals",
  settlement_type: "physical",
  settlement_time_local: "12:30:00",
  is_active: true,
  provenance: "fixture",
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("App", () => {
  it("labels fixture data and renders contract metadata from the API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (url.endsWith("/health")) return Promise.resolve(jsonResponse(health));
        if (url.endsWith("/v1/instruments")) return Promise.resolve(jsonResponse([]));
        if (url.endsWith("/v1/futures-contracts")) return Promise.resolve(jsonResponse([contract]));
        return Promise.resolve(new Response("not found", { status: 404 }));
      }),
    );

    render(<App />);

    expect(await screen.findByText(/FIXTURE DATA/)).toBeInTheDocument();
    expect(await screen.findByText("GCZ6")).toBeInTheDocument();
    expect(screen.getByText("10 USD")).toBeInTheDocument();
    expect(screen.getByText("physical")).toBeInTheDocument();

    vi.unstubAllGlobals();
  });
});
