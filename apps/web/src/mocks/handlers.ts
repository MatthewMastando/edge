import { http, HttpResponse } from "msw";

import type { BarSeries, Timeframe } from "../api/types";
import {
  calendarsFixture,
  capabilitiesFixture,
  contractsFixture,
  healthFixture,
  instrumentsFixture,
  snapshotsFixture,
} from "./catalog";
import { buildBars } from "./series";

const TIMEFRAMES = new Set<Timeframe>(["1m", "5m", "15m", "1h", "4h", "1d"]);

function isTimeframe(value: string | null): value is Timeframe {
  return value !== null && TIMEFRAMES.has(value as Timeframe);
}

/**
 * MSW handlers for the Stage 0 routes only. Artifact, chat, and run writes stay in the
 * client workspace until those API routes exist.
 */
export const handlers = [
  http.get("*/health", () => HttpResponse.json(healthFixture)),
  http.get("*/v1/capabilities", () => HttpResponse.json(capabilitiesFixture)),
  http.get("*/v1/instruments", () => HttpResponse.json(instrumentsFixture)),
  http.get("*/v1/futures-contracts", ({ request }) => {
    const root = new URL(request.url).searchParams.get("root");
    const rows = root ? contractsFixture.filter((contract) => contract.root === root) : contractsFixture;
    return HttpResponse.json(rows);
  }),
  http.get("*/v1/session-calendars", () => HttpResponse.json(calendarsFixture)),
  http.get("*/v1/snapshots", () => HttpResponse.json(snapshotsFixture)),
  http.get("*/v1/bars", ({ request }) => {
    const url = new URL(request.url);
    const symbol = url.searchParams.get("symbol");
    const requested = url.searchParams.get("timeframe");
    const timeframe: Timeframe = isTimeframe(requested) ? requested : "5m";
    if (!symbol) {
      return HttpResponse.json({ detail: [{ loc: ["query", "symbol"], msg: "Field required", type: "missing" }] }, { status: 422 });
    }
    const series: BarSeries | null = buildBars(symbol, timeframe);
    if (!series) {
      return HttpResponse.json({ detail: [{ loc: ["query", "symbol"], msg: "Unknown symbol", type: "value_error" }] }, { status: 422 });
    }
    return HttpResponse.json(series);
  }),
];
