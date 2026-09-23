import { describe, expect, it } from "vitest";

import type { Bar, TAFeature } from "../api/types";
import { buildAnnotations, selectChartFeatures } from "./annotations";

const FEATURE_ID = "33333333-3333-4333-8333-333333333333";

function feature(): TAFeature {
  const levels = [
    { name: "zone_lower", price: "1.10125", role: "zone_lower" as const },
    { name: "zone_upper", price: "1.10255", role: "zone_upper" as const },
  ];
  return {
    id: FEATURE_ID,
    detector: "fvg",
    calc_version: "1.0.0",
    instrument_id: "11111111-1111-4111-8111-111111111111",
    contract_code: "6EZ6",
    timeframe: "5m",
    session: "current_session",
    session_calendar_id: "cme_globex_fx",
    session_calendar_version: "1.0.0",
    direction: "bullish",
    levels,
    state: "confirmed",
    origin_time: "2026-09-01T14:00:00.000Z",
    origin_tz: "America/Chicago",
    confirmation_time: "2026-09-01T14:05:00.000Z",
    confirmation_tz: "America/Chicago",
    as_of: "2026-09-01T14:10:00.000Z",
    as_of_tz: "America/Chicago",
    parameters: {},
    details: {
      chart_annotation: {
        id: `ann:${FEATURE_ID}`,
        feature_id: FEATURE_ID,
        detector: "fvg",
        calc_version: "1.0.0",
        kind: "zone",
        levels,
        direction: "bullish",
        state: "confirmed",
        origin_time: "2026-09-01T14:00:00.000Z",
        confirmation_time: "2026-09-01T14:05:00.000Z",
      },
    },
    snapshot_id: "22222222-2222-4222-8222-222222222222",
    data_revision: "fixture-test",
    provenance: "fixture",
    warnings: [],
  };
}

function bars(): Bar[] {
  return [0, 1, 2].map((index) => ({
    instrument_id: "11111111-1111-4111-8111-111111111111",
    contract_code: "6EZ6",
    timeframe: "5m" as const,
    origin_time: new Date(Date.parse("2026-09-01T14:00:00.000Z") + index * 300_000).toISOString(),
    origin_tz: "America/Chicago",
    open: "1.10",
    high: "1.11",
    low: "1.09",
    close: "1.105",
    volume: "1",
    is_complete: true,
    data_revision: "fixture-test",
    provenance: "fixture" as const,
  }));
}

describe("saved chart annotations", () => {
  it("draws the persisted calc 1.0.0 prices instead of bar-index geometry", () => {
    const saved = feature();
    const views = buildAnnotations(selectChartFeatures([saved]), bars());
    expect(views).toHaveLength(1);
    expect(views[0]?.calcVersion).toBe("1.0.0");
    expect(views[0]?.savedPrice).toBe("1.10255");
    expect(views[0]?.price).toBe(1.10255);
    expect(views[0]?.priceEnd).toBe(1.10125);
    expect(views[0]?.calculation).toContain("zone_upper 1.10255");
    expect(views[0]?.calculation).not.toContain("start_bar");
  });

  it("drops an annotation whose prices do not match the feature", () => {
    const saved = feature();
    const details = saved.details ?? {};
    const raw = details["chart_annotation"];
    if (typeof raw !== "object" || raw === null) throw new Error("missing annotation");
    const forged = {
      ...raw,
      levels: [
        { name: "zone_lower", price: "9.99", role: "zone_lower" },
        { name: "zone_upper", price: "9.98", role: "zone_upper" },
      ],
    };
    const tampered = { ...saved, details: { ...details, chart_annotation: forged } };
    expect(buildAnnotations([tampered], bars())).toEqual([]);
  });
});
