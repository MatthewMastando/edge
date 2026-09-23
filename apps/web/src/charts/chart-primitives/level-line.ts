import type { ISeriesPrimitiveAxisView, UTCTimestamp } from "lightweight-charts";

import type { HitBox } from "./geometry";
import type { ChartPalette } from "./palette";
import { plotPoint, PriceTag, SeriesPlugin } from "./plugin";

export interface LevelModel {
  id: string;
  label: string;
  price: number;
  timeStart: UTCTimestamp;
  timeEnd: UTCTimestamp;
}

/** Horizontal labeled level (session high/low, POC, VAH, VAL). */
export class LabeledLevelPrimitive extends SeriesPlugin {
  private readonly tag = new PriceTag();
  private readonly axisCache: readonly ISeriesPrimitiveAxisView[];

  constructor(
    private readonly level: LevelModel,
    private readonly colors: ChartPalette,
  ) {
    super();
    this.tag.label = level.label;
    this.tag.color = colors.level;
    this.tag.ink = colors.levelInk;
    this.axisCache = [this.tag];
  }

  priceAxisViews(): readonly ISeriesPrimitiveAxisView[] {
    return this.axisCache;
  }

  measure(): HitBox[] {
    const start = plotPoint(this, this.level.timeStart, this.level.price);
    const end = plotPoint(this, this.level.timeEnd, this.level.price);
    if (!start) return [];
    const x2 = end?.x ?? start.x + 24;
    const x = Math.min(start.x, x2);
    const width = Math.max(12, Math.abs(x2 - start.x));
    this.tag.coordinateValue = start.y;
    return [{ id: this.level.id, kind: "line", x, y: start.y - 4, width, height: 8 }];
  }

  override detached(): void {
    super.detached();
    this.tag.coordinateValue = -1_000_000;
  }

  draw(scope: { context: CanvasRenderingContext2D; width: number }): void {
    const box = this.boxes[0];
    if (!box) return;
    const y = box.y + 4;
    const context = scope.context;
    context.save();
    context.strokeStyle = this.colors.level;
    context.lineWidth = 1;
    context.setLineDash([4, 3]);
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(scope.width, y);
    context.stroke();
    context.setLineDash([]);
    context.font = "11px ui-sans-serif, system-ui, sans-serif";
    const text = this.level.label;
    const pad = 4;
    const width = context.measureText(text).width + pad * 2;
    context.fillStyle = this.colors.level;
    context.fillRect(8, y - 16, width, 14);
    context.fillStyle = this.colors.levelInk;
    context.fillText(text, 8 + pad, y - 5);
    context.restore();
  }
}
