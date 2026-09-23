import type { Instrument, TAFeature } from "../api/types";
import { formatDecimal } from "../lib/provenance";
import { stanceLabel } from "../lib/format";
import type { StructuredDraft } from "../workspace/types";

const STANCES = ["bullish", "bearish", "neutral", "insufficient_evidence"] as const;

export function StructuredBlock({
  draft,
  features,
  instrument,
  readOnly,
  onChange,
}: {
  draft: StructuredDraft;
  features: readonly TAFeature[];
  instrument: Instrument | undefined;
  readOnly: boolean;
  onChange: (patch: Partial<StructuredDraft>) => void;
}) {
  const levelsMissing = draft.entry === "" || draft.invalidation === "" || draft.target === "";
  return (
    <fieldset className="structured" disabled={readOnly}>
      <legend>Structured block</legend>
      <p className="hint">
        Stance, levels, sizing, and costs. Saving a change here records a new revision and requests recalculation.
        Narrative edits do not.
      </p>

      <label className="field">
        <span>Stance</span>
        <select
          aria-label="Stance"
          value={draft.stance}
          onChange={(event) => {
            const stance = STANCES.find((item) => item === event.target.value);
            if (stance) onChange({ stance });
          }}
        >
          {STANCES.map((stance) => (
            <option key={stance} value={stance}>
              {stanceLabel(stance)}
            </option>
          ))}
        </select>
      </label>

      <div className="level-readout">
        <h3>Calculated levels</h3>
        {features.length === 0 ? <p className="hint">No saved calculations.</p> : null}
        <ul data-testid="saved-levels">
          {features.flatMap((feature) =>
            feature.levels.map((level) => (
              <li key={`${feature.id}-${level.name}`} data-calc={feature.calc_version} data-saved-level={level.price}>
                <span>{level.name}</span>
                <span className="num">{formatDecimal(level.price)}</span>
              </li>
            )),
          )}
        </ul>
      </div>

      <div className="field-row">
        <label className="field">
          <span>Entry</span>
          <input
            aria-label="Entry"
            inputMode="decimal"
            value={draft.entry}
            placeholder="unset"
            onChange={(event) => {
              onChange({ entry: event.target.value });
            }}
          />
        </label>
        <label className="field">
          <span>Invalidation</span>
          <input
            aria-label="Invalidation"
            inputMode="decimal"
            value={draft.invalidation}
            placeholder="unset"
            onChange={(event) => {
              onChange({ invalidation: event.target.value });
            }}
          />
        </label>
        <label className="field">
          <span>Target</span>
          <input
            aria-label="Target"
            inputMode="decimal"
            value={draft.target}
            placeholder="unset"
            onChange={(event) => {
              onChange({ target: event.target.value });
            }}
          />
        </label>
      </div>

      {levelsMissing ? (
        <label className="field">
          <span>Why a level is unset</span>
          <input
            aria-label="Unset reason"
            value={draft.unsetReason}
            onChange={(event) => {
              onChange({ unsetReason: event.target.value });
            }}
          />
        </label>
      ) : null}

      <div className="field-row">
        <label className="field">
          <span>Sizing (contracts)</span>
          <input
            aria-label="Contracts"
            inputMode="numeric"
            value={draft.contracts}
            placeholder="unset"
            onChange={(event) => {
              onChange({ contracts: event.target.value });
            }}
          />
        </label>
        <label className="field">
          <span>Estimated costs (USD)</span>
          <input
            aria-label="Estimated costs"
            inputMode="decimal"
            value={draft.estimatedCosts}
            placeholder="unset"
            onChange={(event) => {
              onChange({ estimatedCosts: event.target.value });
            }}
          />
        </label>
      </div>

      <p className="hint">
        {instrument
          ? `Verified terms from the instrument record: tick ${formatDecimal(instrument.tick_size)}, tick value ${formatDecimal(instrument.tick_value)} ${instrument.currency}, point multiplier ${formatDecimal(instrument.multiplier)}.`
          : "Instrument terms load from the fixture catalog."}{" "}
        Hypothetical risk is recalculated with the harness. This form does not invent a P&amp;L.
      </p>
    </fieldset>
  );
}
