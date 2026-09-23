import type { Bar, TAFeature } from "../api/types";
import type { UTCTimestamp } from "lightweight-charts";

import type { OverlayAnnotation } from "./chart-primitives";
import { wilderRsi } from "./chart-primitives";

export interface AnnotationView extends OverlayAnnotation {
  featureId: string;
  detector: TAFeature["detector"];
  calculation: string;
  confirmationTime: string | null;
  parameters: readonly { name: string; value: string }[];
}

function detail(feature: TAFeature, key: string): unknown {
  return feature.details?.[key];
}

function detailNumber(feature: TAFeature, key: string): number | null {
  const value = detail(feature, key);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function detailString(feature: TAFeature, key: string): string | null {
  const value = detail(feature, key);
  return typeof value === "string" ? value : null;
}

function levelPrice(feature: TAFeature, name: string): number | null {
  const level = feature.levels.find((item) => item.name === name);
  if (!level) return null;
  const price = Number(level.price);
  return Number.isFinite(price) ? price : null;
}

function barUnix(bars: readonly Bar[], index: number): UTCTimestamp | null {
  const bar = bars[index];
  if (!bar) return null;
  const ms = Date.parse(bar.origin_time);
  if (Number.isNaN(ms)) return null;
  return Math.floor(ms / 1000) as UTCTimestamp;
}

function parametersOf(feature: TAFeature): { name: string; value: string }[] {
  const rows: { name: string; value: string }[] = [];
  const source = feature.parameters ?? {};
  for (const [name, value] of Object.entries(source)) {
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      rows.push({ name, value: String(value) });
    }
  }
  return rows;
}

export function buildAnnotations(features: readonly TAFeature[], bars: readonly Bar[]): AnnotationView[] {
  const closes = bars.map((bar) => Number(bar.close));
  const rsi = wilderRsi(closes);
  const views: AnnotationView[] = [];

  for (const feature of features) {
    const kind = detailString(feature, "kind");
    const calculation = detailString(feature, "calculation") ?? feature.detector;
    const start = detailNumber(feature, "start_bar");
    const end = detailNumber(feature, "end_bar");
    const shared = {
      featureId: feature.id,
      detector: feature.detector,
      calculation,
      confirmationTime: feature.confirmation_time,
      parameters: parametersOf(feature),
      direction: feature.direction,
      label: detailString(feature, "label") ?? feature.detector,
    };

    if (kind === "zone" && start !== null && end !== null) {
      const time = barUnix(bars, start);
      const timeEnd = barUnix(bars, end);
      const upper = levelPrice(feature, "zone_upper");
      const lower = levelPrice(feature, "zone_lower");
      if (time === null || timeEnd === null || upper === null || lower === null) continue;
      views.push({
        ...shared,
        id: feature.id,
        kind: "zone",
        time,
        timeEnd,
        price: upper,
        priceEnd: lower,
      });
    }

    if (kind === "level" && start !== null && end !== null) {
      const time = barUnix(bars, start);
      const timeEnd = barUnix(bars, end);
      const price = levelPrice(feature, "level") ?? levelPrice(feature, feature.levels[0]?.name ?? "");
      if (time === null || timeEnd === null || price === null) continue;
      views.push({ ...shared, id: feature.id, kind: "level", time, timeEnd, price });
    }

    if (kind === "marker" && end !== null) {
      const time = barUnix(bars, end);
      const price = levelPrice(feature, "level") ?? levelPrice(feature, feature.levels[0]?.name ?? "");
      if (time === null || price === null) continue;
      views.push({ ...shared, id: feature.id, kind: "marker", time, price });
    }

    if (kind === "rsi" && end !== null) {
      const time = barUnix(bars, end);
      const value = rsi[end];
      if (time === null || value === null || value === undefined) continue;
      views.push({
        ...shared,
        id: feature.id,
        kind: "rsi",
        time,
        price: value,
      });
    }
  }

  return views;
}

export function rsiPoints(bars: readonly Bar[]): { time: UTCTimestamp; value: number }[] {
  const closes = bars.map((bar) => Number(bar.close));
  const values = wilderRsi(closes);
  const points: { time: UTCTimestamp; value: number }[] = [];
  values.forEach((value, index) => {
    if (value === null) return;
    const time = barUnix(bars, index);
    if (time === null) return;
    points.push({ time, value });
  });
  return points;
}
