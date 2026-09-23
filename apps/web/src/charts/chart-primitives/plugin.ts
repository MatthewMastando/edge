import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  ISeriesPrimitiveAxisView,
  PrimitiveHoveredItem,
  SeriesAttachedParameter,
  SeriesType,
  UTCTimestamp,
} from "lightweight-charts";

interface MediaTarget {
  useMediaCoordinateSpace(callback: (scope: MediaScope) => void): void;
}

interface MediaScope {
  context: CanvasRenderingContext2D;
  mediaSize: { width: number; height: number };
}

import { hitTestBoxes, type HitBox } from "./geometry";

export interface Plotter {
  chart: IChartApiBase | null;
  series: ISeriesApi<SeriesType> | null;
  boxes: HitBox[];
  draw(scope: { context: CanvasRenderingContext2D; width: number; height: number }): void;
}

export function plotPoint(
  plotter: Plotter,
  time: UTCTimestamp,
  price: number,
): { x: number; y: number } | null {
  if (!plotter.chart || !plotter.series) return null;
  const x = plotter.chart.timeScale().timeToCoordinate(time);
  const y = plotter.series.priceToCoordinate(price);
  if (x === null || y === null) return null;
  return { x, y };
}

class PaneRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly plotter: Plotter) {}

  draw(target: MediaTarget): void {
    target.useMediaCoordinateSpace((scope) => {
      this.plotter.draw({
        context: scope.context,
        width: scope.mediaSize.width,
        height: scope.mediaSize.height,
      });
    });
  }
}

class PaneView implements IPrimitivePaneView {
  private readonly rendererImpl: PaneRenderer;
  constructor(plotter: Plotter) {
    this.rendererImpl = new PaneRenderer(plotter);
  }
  zOrder(): "top" {
    return "top";
  }
  renderer(): IPrimitivePaneRenderer {
    return this.rendererImpl;
  }
}

export class PriceTag implements ISeriesPrimitiveAxisView {
  coordinateValue = -1_000_000;
  label = "";
  color = "#d7b07a";
  ink = "#241c12";
  coordinate(): number {
    return this.coordinateValue;
  }
  text(): string {
    return this.label;
  }
  textColor(): string {
    return this.ink;
  }
  backColor(): string {
    return this.color;
  }
  visible(): boolean {
    return this.coordinateValue > -100_000;
  }
}

/**
 * Shared series-primitive lifecycle. Subclasses fill `boxes` during `updateAllViews`
 * and paint in media coordinates so hit testing matches the drawing.
 */
export abstract class SeriesPlugin implements ISeriesPrimitive, Plotter {
  chart: IChartApiBase | null = null;
  series: ISeriesApi<SeriesType> | null = null;
  boxes: HitBox[] = [];
  private readonly paneView = new PaneView(this);
  private readonly paneViewsCache: readonly IPrimitivePaneView[] = [this.paneView];

  attached(param: SeriesAttachedParameter): void {
    this.chart = param.chart;
    this.series = param.series;
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.boxes = [];
  }

  updateAllViews(): void {
    this.boxes = this.measure();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.paneViewsCache;
  }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    const hit = hitTestBoxes(this.boxes, x, y);
    if (!hit) return null;
    return {
      externalId: hit.id,
      cursorStyle: "pointer",
      zOrder: "top",
      hitTestPriority: hit.kind === "marker" ? 2 : hit.kind === "line" ? 1 : 0,
      distance: 0,
      itemType: hit.kind === "marker" ? "marker" : "primitive",
    };
  }

  abstract measure(): HitBox[];
  abstract draw(scope: { context: CanvasRenderingContext2D; width: number; height: number }): void;
}
