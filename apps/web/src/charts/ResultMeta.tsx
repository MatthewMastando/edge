import type { AdapterCapabilities, MarketSnapshot, Run } from "../api/types";
import { freshnessLabel, formatInstant } from "../lib/format";
import { provenanceLabel } from "../lib/provenance";
import { StatusBadge } from "../components/StatusBadge";
import type { ArtifactRecord } from "../workspace/types";

export function ResultMeta({
  artifact,
  snapshot,
  run,
  capabilities,
}: {
  artifact: ArtifactRecord;
  snapshot: MarketSnapshot | undefined;
  run: Run | undefined;
  capabilities: AdapterCapabilities | undefined;
}) {
  const thesis = artifact.thesis;
  const feature = artifact.features[0];
  const provenance = snapshot?.provenance ?? thesis.provenance;
  const label = provenanceLabel(provenance);
  const asOf = snapshot?.as_of ?? thesis.as_of;
  return (
    <section className="result-meta" aria-label="Result details">
      {label.isDemonstration ? (
        <div className="banner" role="status">
          {label.text}
        </div>
      ) : null}
      <dl className="meta-grid">
        <div>
          <dt>Instrument</dt>
          <dd>
            {thesis.symbol}
            {thesis.contract_code ? <span className="num"> · {thesis.contract_code}</span> : null}
          </dd>
        </div>
        <div>
          <dt>Venue</dt>
          <dd>{thesis.venue}</dd>
        </div>
        <div>
          <dt>Timeframe / session</dt>
          <dd>
            {feature ? `${feature.timeframe} · ${feature.session.replaceAll("_", " ")}` : "Not calculated"}
          </dd>
        </div>
        <div>
          <dt>As of</dt>
          <dd>{formatInstant(asOf)}</dd>
        </div>
        <div>
          <dt>Source / feed</dt>
          <dd>{snapshot ? `${snapshot.provider} · ${snapshot.kind}` : thesis.versions.provider}</dd>
        </div>
        <div>
          <dt>Coverage</dt>
          <dd>{capabilities?.coverage_note ?? snapshot?.coverage_note ?? "Not reported"}</dd>
        </div>
        <div>
          <dt>Freshness</dt>
          <dd>{freshnessLabel(provenance, asOf)}</dd>
        </div>
        <div>
          <dt>Run</dt>
          <dd>{run ? <StatusBadge status={run.status} /> : "No run"}</dd>
        </div>
      </dl>
    </section>
  );
}
