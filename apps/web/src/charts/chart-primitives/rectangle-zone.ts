import type { UTCTimestamp } from "lightweight-charts";

import type { HitBox } from "./geometry";
import type { ChartPalette } from "./palette";
import { plotPoint, SeriesPlugin } from "./plugin";

export interface ZoneModel {
  id: string;
  label: string;
  timeStart: UTCTimestamp;
  timeEnd: UTCTimestamp;
  priceHigh: number;
  priceLow: number;
  direction: "bullish" | "bearish" | "neutral";
}

/** Filled price/time rectangle for a fair-value gap or order block. */
export class RectangleZonePrimitive extends SeriesPlugin {
  constructor(
    private readonly zone: ZoneModel,
    private readonly colors: ChartPalette,
  ) {
    super();
  }

  measure(): HitBox[] {
    const top = plotPoint(this, this.zone.timeStart, this.zone.priceHigh);
    const bottom = plotPoint(this, this.zone.timeEnd, this.zone.priceLow);
    if (!top || !bottom) return [];
    const x = Math.min(top.x, bottom.x);
    const y = Math.min(top.y, bottom.y);
    const width = Math.max(8, Math.abs(bottom.x - top.x));
    const height = Math.max(4, Math.abs(bottom.y - top.y));
    return [{ id: this.zone.id, kind: "zone", x, y, width, height }];
  }

  draw(scope: { context: CanvasRenderingContext2D }): void {
    const box = this.boxes[0];
    if (!box) return;
    const context = scope.context;
    const bullish = this.zone.direction !== "bearish";
    context.save();
    context.fillStyle = bullish ? this.colors.zoneBull : this.colors.zoneBear;
    context.strokeStyle = bullish ? this.colors.zoneBullStroke : this.colors.zoneBearStroke;
    context.lineWidth = 1;
    context.fillRect(box.x, box.y, box.width, box.height);
    context.strokeRect(box.x + 0.5, box.y + 0.5, box.width - 1, box.height - 1);
    context.fillStyle = this.colors.label;
    context.font = "11px ui-sans-serif, system-ui, sans-serif";
    context.fillText(this.zone.label, box.x + 6, box.y + 14);
    context.restore();
  }
}
