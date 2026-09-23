import type { ISeriesApi, UTCTimestamp } from "lightweight-charts";

import { LabeledLevelPrimitive } from "./level-line";
import { MarkerPrimitive } from "./marker";
import { RectangleZonePrimitive } from "./rectangle-zone";
import { attachRsiSubpane, type RsiPoint } from "./rsi-pane";
import type { IChartApi } from "lightweight-charts";

export interface OverlayAnnotation {
  id: string;
  label: string;
  kind: "zone" | "level" | "marker" | "rsi";
  direction: "bullish" | "bearish" | "neutral";
  time: UTCTimestamp;
  timeEnd?: UTCTimestamp;
  price: number;
  priceEnd?: number;
}

export interface ResearchOverlayInput {
  chart: IChartApi;
  candleSeries: ISeriesApi<"Candlestick">;
  annotations: readonly OverlayAnnotation[];
  rsi: readonly RsiPoint[];
}

/** Attaches zone, level, marker, and RSI-subpane primitives. Returns a detach function. */
export function attachResearchPrimitives(input: ResearchOverlayInput): () => void {
  const detach: Array<() => void> = [];
  const lastTime = input.annotations.reduce<UTCTimestamp | null>((latest, annotation) => {
    const end = annotation.timeEnd ?? annotation.time;
    if (latest === null || end > latest) return end;
    return latest;
  }, null);
  const firstTime = input.annotations.reduce<UTCTimestamp | null>((earliest, annotation) => {
    if (earliest === null || annotation.time < earliest) return annotation.time;
    return earliest;
  }, null);

  for (const annotation of input.annotations) {
    if (annotation.kind === "zone" && annotation.priceEnd !== undefined && annotation.timeEnd !== undefined) {
      const primitive = new RectangleZonePrimitive({
        id: annotation.id,
        label: annotation.label,
        timeStart: annotation.time,
        timeEnd: annotation.timeEnd,
        priceHigh: Math.max(annotation.price, annotation.priceEnd),
        priceLow: Math.min(annotation.price, annotation.priceEnd),
        direction: annotation.direction,
      });
      input.candleSeries.attachPrimitive(primitive);
      detach.push(() => {
        input.candleSeries.detachPrimitive(primitive);
      });
    }
    if (annotation.kind === "level" && firstTime !== null && lastTime !== null) {
      const primitive = new LabeledLevelPrimitive({
        id: annotation.id,
        label: annotation.label,
        price: annotation.price,
        timeStart: firstTime,
        timeEnd: lastTime,
      });
      input.candleSeries.attachPrimitive(primitive);
      detach.push(() => {
        input.candleSeries.detachPrimitive(primitive);
      });
    }
    if (annotation.kind === "marker") {
      const primitive = new MarkerPrimitive({
        id: annotation.id,
        label: annotation.label,
        time: annotation.time,
        price: annotation.price,
        direction: annotation.direction,
      });
      input.candleSeries.attachPrimitive(primitive);
      detach.push(() => {
        input.candleSeries.detachPrimitive(primitive);
      });
    }
  }

  const rsiMarker = input.annotations.find((annotation) => annotation.kind === "rsi");
  if (input.rsi.length > 0) {
    const detachRsi = attachRsiSubpane(
      input.chart,
      input.rsi,
      rsiMarker
        ? {
            id: rsiMarker.id,
            label: rsiMarker.label,
            time: rsiMarker.time,
            price: rsiMarker.price,
            direction: rsiMarker.direction,
          }
        : null,
    );
    detach.push(detachRsi);
  }

  return () => {
    for (const fn of detach) fn();
  };
}

export { hitTestBoxes } from "./geometry";
export { wilderRsi } from "./rsi";
export type { TooltipState } from "./marker";
