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
  calcVersion: string;
  /** Exact persisted level price, not a float derived for drawing. */
  savedPrice: string;
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

const CHART_CAPS: Partial<Record<TAFeature["detector"], number>> = {
  volume_profile: 1,
  session_levels: 2,
  fvg: 3,
  order_block: 2,
  liquidity_sweep: 2,
  bos: 2,
  rsi_divergence: 2,
};

interface SavedAnnotation {
  id: string;
  feature_id: string;
  detector: TAFeature["detector"];
  calc_version: string;
  kind: "zone" | "level" | "marker";
  levels: TAFeature["levels"];
  direction: TAFeature["direction"];
  origin_time: string;
  confirmation_time: string | null;
}

/** Prefer features that carry a saved chart annotation. Shell fixtures keep their own list. */
export function selectChartFeatures(features: readonly TAFeature[]): TAFeature[] {
  const saved = features.filter((feature) => readSaved(feature) !== null);
  if (saved.length === 0) return [...features];
  const grouped = new Map<TAFeature["detector"], TAFeature[]>();
  for (const feature of saved) {
    const bucket = grouped.get(feature.detector) ?? [];
    bucket.push(feature);
    grouped.set(feature.detector, bucket);
  }
  const chosen: TAFeature[] = [];
  for (const [detector, bucket] of grouped) {
    const cap = CHART_CAPS[detector] ?? 0;
    if (cap === 0) continue;
    const ranked = [...bucket].sort((left, right) => timeOf(right) - timeOf(left));
    chosen.push(...ranked.slice(0, cap));
  }
  return chosen.sort((left, right) => timeOf(left) - timeOf(right));
}

function timeOf(feature: TAFeature): number {
  const raw = feature.confirmation_time ?? feature.origin_time;
  const parsed = Date.parse(raw);
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function buildAnnotations(features: readonly TAFeature[], bars: readonly Bar[]): AnnotationView[] {
  const closes = bars.map((bar) => Number(bar.close));
  const rsi = wilderRsi(closes);
  const views: AnnotationView[] = [];

  for (const feature of features) {
    const saved = readSaved(feature);
    if (saved) {
      views.push(...viewsFromSaved(feature, saved, bars));
      continue;
    }
    const kind = detailString(feature, "kind");
    const calculation = detailString(feature, "calculation") ?? feature.detector;
    const start = detailNumber(feature, "start_bar");
    const end = detailNumber(feature, "end_bar");
    const shared = {
      featureId: feature.id,
      detector: feature.detector,
      calculation,
      confirmationTime: feature.confirmation_time ?? null,
      parameters: parametersOf(feature),
      direction: feature.direction,
      label: detailString(feature, "label") ?? feature.detector,
      calcVersion: feature.calc_version,
      savedPrice: feature.levels[0]?.price ?? "",
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

function readSaved(feature: TAFeature): SavedAnnotation | null {
  const raw = feature.details?.["chart_annotation"];
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  const kind = record["kind"];
  const levels = record["levels"];
  if (kind !== "zone" && kind !== "level" && kind !== "marker") return null;
  if (!Array.isArray(levels)) return null;
  if (record["feature_id"] !== feature.id) return null;
  if (record["calc_version"] !== feature.calc_version) return null;
  if (record["detector"] !== feature.detector) return null;
  if (typeof record["id"] !== "string" || typeof record["origin_time"] !== "string") return null;
  const parsedLevels = feature.levels;
  if (!sameLevelIdentity(parsedLevels, levels)) return null;
  const confirmation = record["confirmation_time"];
  return {
    id: record["id"],
    feature_id: feature.id,
    detector: feature.detector,
    calc_version: feature.calc_version,
    kind,
    levels: parsedLevels,
    direction: feature.direction,
    origin_time: record["origin_time"],
    confirmation_time: typeof confirmation === "string" ? confirmation : null,
  };
}

function sameLevelIdentity(saved: TAFeature["levels"], raw: unknown[]): boolean {
  if (saved.length !== raw.length) return false;
  const left = saved.map((level) => `${level.name}|${level.price}|${level.role}`).sort();
  const right = raw.map((item) => {
    if (typeof item !== "object" || item === null) return "";
    const record = item as { name?: unknown; price?: unknown; role?: unknown };
    return `${String(record.name)}|${String(record.price)}|${String(record.role)}`;
  }).sort();
  return left.every((item, index) => item === right[index]);
}

function viewsFromSaved(feature: TAFeature, saved: SavedAnnotation, bars: readonly Bar[]): AnnotationView[] {
  const figures = saved.levels.map((level) => `${level.name} ${level.price}`).join(", ");
  const shared = {
    featureId: feature.id,
    detector: feature.detector,
    calculation: `Saved calc ${saved.calc_version}. ${figures}.`,
    confirmationTime: feature.confirmation_time ?? null,
    parameters: parametersOf(feature),
    direction: feature.direction,
    calcVersion: saved.calc_version,
  };
  const origin = snapTime(bars, saved.origin_time);
  const confirmed = snapTime(bars, saved.confirmation_time ?? feature.as_of);
  const spanStart = barUnix(bars, 0);
  const spanEnd = barUnix(bars, bars.length - 1);
  const views: AnnotationView[] = [];

  if (saved.kind === "zone") {
    const upper = saved.levels.find((level) => level.role === "zone_upper" || level.name === "zone_upper" || level.name === "vah");
    const lower = saved.levels.find((level) => level.role === "zone_lower" || level.name === "zone_lower" || level.name === "val");
    const time = origin ?? spanStart;
    const timeEnd = confirmed ?? spanEnd;
    if (time !== null && timeEnd !== null && upper && lower) {
      views.push({
        ...shared,
        id: saved.id,
        kind: "zone",
        label: `${feature.detector} ${feature.direction} · calc ${saved.calc_version}`,
        time,
        timeEnd: timeEnd < time ? time : timeEnd,
        price: Number(upper.price),
        priceEnd: Number(lower.price),
        savedPrice: upper.price,
      });
    }
    const poc = saved.levels.find((level) => level.name === "poc");
    if (poc && spanStart !== null && spanEnd !== null) {
      views.push({
        ...shared,
        id: `${saved.id}:poc`,
        kind: "level",
        label: `poc · calc ${saved.calc_version}`,
        time: spanStart,
        timeEnd: spanEnd,
        price: Number(poc.price),
        savedPrice: poc.price,
      });
    }
  }

  if (saved.kind === "level" && spanStart !== null && spanEnd !== null) {
    for (const level of saved.levels) {
      views.push({
        ...shared,
        id: `${saved.id}:${level.name}`,
        kind: "level",
        label: `${level.name} · calc ${saved.calc_version}`,
        time: spanStart,
        timeEnd: spanEnd,
        price: Number(level.price),
        savedPrice: level.price,
      });
    }
  }

  if (saved.kind === "marker") {
    const level = saved.levels[0];
    const time = confirmed ?? origin;
    if (level && time !== null) {
      views.push({
        ...shared,
        id: saved.id,
        kind: "marker",
        label: `${feature.detector} ${feature.direction} · calc ${saved.calc_version}`,
        time,
        price: Number(level.price),
        savedPrice: level.price,
      });
    }
    const rsiValue = rsiSecond(feature);
    const rsiTime = confirmed ?? origin;
    if (feature.detector === "rsi_divergence" && rsiValue !== null && rsiTime !== null) {
      views.push({
        ...shared,
        id: `${saved.id}:rsi`,
        kind: "rsi",
        label: `rsi · calc ${saved.calc_version}`,
        time: rsiTime,
        price: rsiValue.value,
        savedPrice: rsiValue.saved,
      });
    }
  }

  return views;
}

function rsiSecond(feature: TAFeature): { value: number; saved: string } | null {
  const direct = feature.details?.["rsi_second"];
  if (typeof direct === "string") {
    const value = Number(direct);
    return Number.isFinite(value) ? { value, saved: direct } : null;
  }
  const first = firstUnknown(feature.details?.["signals"]);
  if (typeof first !== "object" || first === null) return null;
  const nested = recordField(first, "rsi_second");
  if (typeof nested !== "string") return null;
  const value = Number(nested);
  return Number.isFinite(value) ? { value, saved: nested } : null;
}

function firstUnknown(value: unknown): unknown {
  if (typeof value !== "object" || value === null || !("0" in value)) return null;
  return recordField(value, "0");
}

function recordField(value: object, key: string): unknown {
  if (!(key in value)) return null;
  return (value as Record<string, unknown>)[key];
}

function snapTime(bars: readonly Bar[], iso: string | null): UTCTimestamp | null {
  if (!iso) return null;
  const target = Date.parse(iso);
  if (Number.isNaN(target)) return null;
  let best: Bar | null = null;
  let bestDelta = Number.POSITIVE_INFINITY;
  for (const bar of bars) {
    const parsed = Date.parse(bar.origin_time);
    if (Number.isNaN(parsed)) continue;
    const delta = Math.abs(parsed - target);
    if (delta < bestDelta) {
      best = bar;
      bestDelta = delta;
    }
  }
  if (!best) return null;
  return Math.floor(Date.parse(best.origin_time) / 1000) as UTCTimestamp;
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
