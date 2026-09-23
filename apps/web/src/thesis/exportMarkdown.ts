import { provenanceLabel } from "../lib/provenance";
import { formatInstant, stanceLabel } from "../lib/format";
import type { ArtifactRecord, DraftRecord } from "../workspace/types";

export function thesisToMarkdown(artifact: ArtifactRecord, draft: DraftRecord): string {
  const thesis = artifact.thesis;
  const label = provenanceLabel(thesis.provenance);
  const lines = [
    `# ${artifact.title}`,
    "",
    label.isDemonstration ? `> ${label.text}` : `> ${label.text}`,
    "",
    `- Instrument: ${thesis.symbol}`,
    `- Contract: ${thesis.contract_code ?? "n/a"}`,
    `- Venue: ${thesis.venue}`,
    `- Horizon: ${thesis.horizon}`,
    `- As of: ${formatInstant(thesis.as_of)}`,
    `- Stance: ${stanceLabel(draft.structured.stance)}`,
    `- Entry: ${draft.structured.entry || "unset"}`,
    `- Invalidation: ${draft.structured.invalidation || "unset"}`,
    `- Target: ${draft.structured.target || "unset"}`,
    `- Contracts: ${draft.structured.contracts || "unset"}`,
    `- Estimated costs: ${draft.structured.estimatedCosts || "unset"}`,
    draft.structured.unsetReason ? `- Unset reason: ${draft.structured.unsetReason}` : "",
    "",
    "## Narrative",
    "",
    draft.presentationMarkdown.trim(),
    "",
  ];
  return lines.filter((line) => line !== "").join("\n") + "\n";
}

export function downloadMarkdown(filename: string, markdown: string): void {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
