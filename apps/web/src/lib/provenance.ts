import type { Provenance } from "../api/types";

export interface ProvenanceLabel {
  text: string;
  /** True for anything that must be displayed prominently as not-live. */
  isDemonstration: boolean;
}

/** Every result shows where its data came from; only `live` is unlabeled. */
export function provenanceLabel(provenance: Provenance): ProvenanceLabel {
  switch (provenance) {
    case "fixture":
      return { text: "FIXTURE DATA — synthetic, not market data", isDemonstration: true };
    case "recorded":
      return { text: "DEMONSTRATION — recorded model output", isDemonstration: true };
    case "live":
      return { text: "Live", isDemonstration: false };
  }
}

/** Decimal fields arrive as strings to preserve exactness; format for display without parsing to float. */
export function formatDecimal(value: string, maxFractionDigits = 8): string {
  const [whole, fraction = ""] = value.split(".");
  const trimmed = fraction.slice(0, maxFractionDigits).replace(/0+$/, "");
  return trimmed.length > 0 ? `${whole ?? "0"}.${trimmed}` : (whole ?? "0");
}
