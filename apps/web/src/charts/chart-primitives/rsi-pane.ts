import type { IChartApi, ISeriesPrimitiveAxisView, LineData, UTCTimestamp } from "lightweight-charts";
import { LineSeries } from "lightweight-charts";

import type { HitBox } from "./geometry";
import { CHART_COLORS, PriceTag, SeriesPlugin } from "./plugin";
import { MarkerPrimitive, type MarkerModel } from "./marker";

export interface RsiPoint {
  time: UTCTimestamp;
  value: number;
}

/**
 * RSI subpane: a line series on pane 1 supplies the 0–100 scale, and series primitives
 * draw the 30/70 guides. Divergence markers attach to the same series.
 */
export function attachRsiSubpane(
  chart: IChartApi,
  points: readonly RsiPoint[],
  marker: MarkerModel | null,
): () => void {
  const data: LineData[] = points.map((point) => ({ time: point.time, value: point.value }));
  const series = chart.addSeries(
    LineSeries,
    {
      color: CHART_COLORS.rsiLine,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
    },
    1,
  );
  series.setData(data);
  series.getPane().setHeight(112);
  const guides = new RsiGuidePrimitive();
  series.attachPrimitive(guides);
  const markerPrimitive = marker ? new MarkerPrimitive(marker) : null;
  if (markerPrimitive) series.attachPrimitive(markerPrimitive);
  return () => {
    series.detachPrimitive(guides);
    if (markerPrimitive) series.detachPrimitive(markerPrimitive);
    chart.removeSeries(series);
  };
}

class RsiGuidePrimitive extends SeriesPlugin {
  private readonly upper = new PriceTag();
  private readonly lower = new PriceTag();
  private readonly axisCache: readonly ISeriesPrimitiveAxisView[];

  constructor() {
    super();
    this.upper.label = "70";
    this.lower.label = "30";
    this.upper.color = CHART_COLORS.rsiBand;
    this.lower.color = CHART_COLORS.rsiBand;
    this.axisCache = [this.upper, this.lower];
  }

  priceAxisViews(): readonly ISeriesPrimitiveAxisView[] {
    return this.axisCache;
  }

  override hitTest(): null {
    return null;
  }

  measure(): HitBox[] {
    const width = this.chart?.timeScale().width() ?? 0;
    const upper = this.series?.priceToCoordinate(70);
    const lower = this.series?.priceToCoordinate(30);
    this.upper.coordinateValue = upper ?? -1_000_000;
    this.lower.coordinateValue = lower ?? -1_000_000;
    const boxes: HitBox[] = [];
    if (upper !== null && upper !== undefined) {
      boxes.push({ id: "rsi-70", kind: "line", x: 0, y: upper - 3, width, height: 6 });
    }
    if (lower !== null && lower !== undefined) {
      boxes.push({ id: "rsi-30", kind: "line", x: 0, y: lower - 3, width, height: 6 });
    }
    return boxes;
  }

  draw(scope: { context: CanvasRenderingContext2D; width: number }): void {
    const context = scope.context;
    context.save();
    context.strokeStyle = CHART_COLORS.rsiBand;
    context.lineWidth = 1;
    context.setLineDash([2, 3]);
    context.font = "10px ui-sans-serif, system-ui, sans-serif";
    context.fillStyle = CHART_COLORS.rsiBand;
    for (const price of [30, 70]) {
      const y = this.series?.priceToCoordinate(price);
      if (y === null || y === undefined) continue;
      context.beginPath();
      context.moveTo(0, y);
      context.lineTo(scope.width, y);
      context.stroke();
      context.fillText(String(price), 6, y - 3);
    }
    context.restore();
  }
}

