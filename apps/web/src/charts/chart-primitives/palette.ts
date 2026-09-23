export interface ChartPalette {
  text: string;
  textDim: string;
  grid: string;
  border: string;
  up: string;
  down: string;
  accent: string;
  accentInk: string;
  zoneBull: string;
  zoneBullStroke: string;
  zoneBear: string;
  zoneBearStroke: string;
  level: string;
  levelInk: string;
  markerBull: string;
  markerBear: string;
  markerNeutral: string;
  markerInk: string;
  rsiLine: string;
  rsiBand: string;
  label: string;
}

const FALLBACK: ChartPalette = {
  text: "#e7ebf2",
  textDim: "#b0b8c6",
  grid: "#313846",
  border: "#4a5366",
  up: "#3fbf86",
  down: "#e36d74",
  accent: "#d4b483",
  accentInk: "#1c160e",
  zoneBull: "rgba(63, 191, 134, 0.22)",
  zoneBullStroke: "#3fbf86",
  zoneBear: "rgba(227, 109, 116, 0.22)",
  zoneBearStroke: "#e36d74",
  level: "#d4b483",
  levelInk: "#1c160e",
  markerBull: "#3fbf86",
  markerBear: "#e36d74",
  markerNeutral: "#d4b483",
  markerInk: "#e7ebf2",
  rsiLine: "#d4b483",
  rsiBand: "rgba(176, 184, 198, 0.85)",
  label: "#e7ebf2",
};

function withAlpha(color: string, alpha: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(color.trim());
  if (!match?.[1]) return color;
  const value = Number.parseInt(match[1], 16);
  const red = (value >> 16) & 255;
  const green = (value >> 8) & 255;
  const blue = value & 255;
  return `rgba(${String(red)}, ${String(green)}, ${String(blue)}, ${String(alpha)})`;
}

function readColor(style: CSSStyleDeclaration, name: string, fallback: string): string {
  const value = style.getPropertyValue(name).trim();
  return value.length > 0 ? value : fallback;
}

/** Colors follow the shell theme so candles, zones, levels, markers, and RSI match the page. */
export function chartPalette(element: Element): ChartPalette {
  const style = getComputedStyle(element);
  const text = readColor(style, "--text", FALLBACK.text);
  const textDim = readColor(style, "--text-dim", FALLBACK.textDim);
  const up = readColor(style, "--up", FALLBACK.up);
  const down = readColor(style, "--down", FALLBACK.down);
  const accent = readColor(style, "--accent", FALLBACK.accent);
  const accentInk = readColor(style, "--accent-ink", FALLBACK.accentInk);
  return {
    text,
    textDim,
    grid: readColor(style, "--line", FALLBACK.grid),
    border: readColor(style, "--line-strong", FALLBACK.border),
    up,
    down,
    accent,
    accentInk,
    zoneBull: withAlpha(up, 0.22),
    zoneBullStroke: up,
    zoneBear: withAlpha(down, 0.22),
    zoneBearStroke: down,
    level: accent,
    levelInk: accentInk,
    markerBull: up,
    markerBear: down,
    markerNeutral: accent,
    markerInk: text,
    rsiLine: accent,
    rsiBand: withAlpha(textDim, 0.85),
    label: text,
  };
}
