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
  text: "#eceae4",
  textDim: "#b1ab9f",
  grid: "#31363f",
  border: "#4a5160",
  up: "#8eae86",
  down: "#c4847c",
  accent: "#d7b07a",
  accentInk: "#241c12",
  zoneBull: "rgba(142, 174, 134, 0.22)",
  zoneBullStroke: "#8eae86",
  zoneBear: "rgba(196, 132, 124, 0.22)",
  zoneBearStroke: "#c4847c",
  level: "#d7b07a",
  levelInk: "#241c12",
  markerBull: "#8eae86",
  markerBear: "#c4847c",
  markerNeutral: "#d7b07a",
  markerInk: "#14161c",
  rsiLine: "#d7b07a",
  rsiBand: "rgba(177, 171, 159, 0.85)",
  label: "#eceae4",
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

/** Colors follow the shell theme so labels stay readable in light and dark. */
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
