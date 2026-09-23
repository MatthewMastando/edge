import type { UTCTimestamp } from "lightweight-charts";

import { boxAroundPoint, type HitBox } from "./geometry";
import { CHART_COLORS, plotPoint, SeriesPlugin } from "./plugin";

export interface MarkerModel {
  id: string;
  label: string;
  time: UTCTimestamp;
  price: number;
  direction: "bullish" | "bearish" | "neutral";
}

const RADIUS = 6;

/** Point marker. The HTML tooltip is positioned by the chart when this primitive is hovered. */
export class MarkerPrimitive extends SeriesPlugin {
  constructor(private readonly marker: MarkerModel) {
    super();
  }

  measure(): HitBox[] {
    const point = plotPoint(this, this.marker.time, this.marker.price);
    if (!point) return [];
    return [boxAroundPoint(this.marker.id, point.x, point.y, RADIUS + 3)];
  }

  draw(scope: { context: CanvasRenderingContext2D }): void {
    const box = this.boxes[0];
    if (!box) return;
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    const context = scope.context;
    const fill =
      this.marker.direction === "bearish"
        ? CHART_COLORS.markerBear
        : this.marker.direction === "bullish"
          ? CHART_COLORS.markerBull
          : CHART_COLORS.markerNeutral;
    context.save();
    context.beginPath();
    context.arc(x, y, RADIUS, 0, Math.PI * 2);
    context.fillStyle = fill;
    context.fill();
    context.lineWidth = 1.5;
    context.strokeStyle = CHART_COLORS.ink;
    context.stroke();
    context.restore();
  }
}

export interface TooltipState {
  id: string;
  label: string;
  x: number;
  y: number;
}
