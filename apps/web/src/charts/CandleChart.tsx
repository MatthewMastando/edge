import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  type IChartApi,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import type { Bar, TAFeature } from "../api/types";
import { provenanceLabel } from "../lib/provenance";
import { buildAnnotations, rsiPoints, type AnnotationView } from "./annotations";
import { AnnotationInspector } from "./AnnotationInspector";
import { attachResearchPrimitives, type TooltipState } from "./chart-primitives";
import { chartPalette } from "./chart-primitives/palette";

function hoverId(param: MouseEventParams): string | null {
  const candidate = param.hoveredInfo?.objectId;
  return typeof candidate === "string" ? candidate : null;
}

function canvasAvailable(): boolean {
  const canvas = document.createElement("canvas");
  return canvas.getContext("2d") !== null;
}

export function CandleChart({
  bars,
  features,
  provenance,
  selectedId,
  onSelect,
}: {
  bars: readonly Bar[];
  features: readonly TAFeature[];
  provenance: Bar["provenance"] | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const canDraw = useMemo(() => canvasAvailable(), []);
  const annotations = useMemo(() => buildAnnotations(features, bars), [features, bars]);
  const points = useMemo(() => rsiPoints(bars), [bars]);
  const selected = annotations.find((annotation) => annotation.id === selectedId) ?? null;
  const label = provenance ? provenanceLabel(provenance) : null;

  useEffect(() => {
    if (!canDraw) return;
    const host = hostRef.current;
    if (!host) return;
    const colors = chartPalette(host);
    const chart: IChartApi = createChart(host, {
      autoSize: true,
      height: 460,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: colors.textDim,
        fontFamily: "Segoe UI, Helvetica Neue, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      rightPriceScale: { borderColor: colors.border },
      timeScale: { borderColor: colors.border, timeVisible: true, secondsVisible: false },
      localization: {
        timeFormatter: (time: Time) => {
          if (typeof time !== "number") return "";
          return new Intl.DateTimeFormat("en-US", {
            timeZone: "America/New_York",
            month: "short",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
          }).format(new Date(time * 1000));
        },
      },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: colors.up,
      downColor: colors.down,
      borderUpColor: colors.up,
      borderDownColor: colors.down,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
    });
    series.setData(
      bars.map((bar) => ({
        time: (Math.floor(Date.parse(bar.origin_time) / 1000) as UTCTimestamp),
        open: Number(bar.open),
        high: Number(bar.high),
        low: Number(bar.low),
        close: Number(bar.close),
      })),
    );
    const detach = attachResearchPrimitives({
      chart,
      candleSeries: series,
      annotations,
      rsi: points,
      colors,
    });
    const selectFrom = (param: MouseEventParams) => {
      const id = hoverId(param);
      if (id && annotations.some((annotation) => annotation.id === id)) onSelect(id);
    };
    const move = (param: MouseEventParams) => {
      const id = hoverId(param);
      const annotation = annotations.find((item) => item.id === id && (item.kind === "marker" || item.kind === "rsi"));
      if (!annotation || !param.point) {
        setTooltip(null);
        return;
      }
      setTooltip({ id: annotation.id, label: annotation.label, x: param.point.x, y: param.point.y });
    };
    chart.subscribeClick(selectFrom);
    chart.subscribeCrosshairMove(move);
    chart.timeScale().fitContent();
    return () => {
      chart.unsubscribeClick(selectFrom);
      chart.unsubscribeCrosshairMove(move);
      detach();
      chart.remove();
    };
  }, [annotations, bars, canDraw, onSelect, points]);

  return (
    <section className="chart-frame" aria-label="Price chart">
      <header className="chart-head">
        <h3>Candles</h3>
        {label?.isDemonstration ? <span className="banner banner-inline">{label.text}</span> : null}
        <p className="hint">Axis times are America/New_York. The RSI pane is Wilder RSI(14) on these closes.</p>
      </header>
      {canDraw ? (
        <div className="chart-canvas-wrap">
          <div ref={hostRef} className="chart-canvas" data-testid="candle-chart" />
          {tooltip ? (
            <div className="chart-tooltip" style={{ left: tooltip.x + 12, top: tooltip.y + 12 }} role="tooltip">
              {tooltip.label}
            </div>
          ) : null}
        </div>
      ) : null}
      {!canDraw ? <p className="hint">The canvas chart renders in a browser. Annotations stay selectable below.</p> : null}
      <div className="legend" role="list" aria-label="Annotations">
        {annotations.length === 0 ? <p className="hint">No saved calculations on this artifact.</p> : null}
        {annotations.map((annotation) => (
          <div key={annotation.id} role="listitem">
            <button
              type="button"
              className={annotation.id === selectedId ? "legend-item is-selected" : "legend-item"}
              onClick={() => {
                onSelect(annotation.id);
              }}
            >
              {annotation.label}
            </button>
          </div>
        ))}
      </div>
      <AnnotationInspector annotation={selected} />
    </section>
  );
}

export type { AnnotationView };
