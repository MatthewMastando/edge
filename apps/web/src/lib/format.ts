import type { Provenance, Run } from "../api/types";

export const DISPLAY_TIMEZONE = "America/New_York";

const STATUS_LABEL: Record<Run["status"], string> = {
  queued: "Queued",
  running: "Running",
  partial: "Partial",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  budget_exceeded: "Budget exceeded",
};

export function runStatusLabel(status: Run["status"]): string {
  return STATUS_LABEL[status];
}

export function formatInstant(iso: string, timeZone = DISPLAY_TIMEZONE): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

/** Fixture and recorded results are not a live feed, regardless of the as-of clock. */
export function freshnessLabel(provenance: Provenance, asOf: string, now = Date.now()): string {
  if (provenance !== "live") return "Synthetic snapshot — not a live feed";
  const then = Date.parse(asOf);
  if (Number.isNaN(then)) return "Freshness unknown";
  const minutes = Math.max(0, Math.round((now - then) / 60_000));
  if (minutes < 2) return "Fresh · under 2 minutes";
  if (minutes < 60) return `Updated ${String(minutes)} minutes ago`;
  const hours = Math.round(minutes / 60);
  return `Updated ${String(hours)} hours ago`;
}

export function stanceLabel(stance: string): string {
  switch (stance) {
    case "bullish":
      return "Bullish";
    case "bearish":
      return "Bearish";
    case "neutral":
      return "Neutral";
    case "insufficient_evidence":
      return "Insufficient evidence";
    default:
      return stance;
  }
}

export function normalizeMarkdown(value: string): string {
  return value.replace(/\r\n/g, "\n").replace(/\s+$/g, "");
}
