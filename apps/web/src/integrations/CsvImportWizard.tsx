import { useCallback, useMemo, useState } from "react";

import { api } from "../api/client";
import { useImportPresets } from "../api/queries";
import { Modal } from "../components/Modal";
import type { components } from "../api/schema";

type CsvColumnMapping = components["schemas"]["CsvColumnMapping"];
type ImportPreview = components["schemas"]["ImportPreview"];

const FIELD_LABELS: Record<string, string> = {
  symbol: "Symbol",
  side: "Side",
  quantity: "Quantity",
  price: "Price",
  fees: "Fees",
  fill_time: "Fill time",
  currency: "Currency",
  contract_code: "Contract code",
  venue: "Venue",
  fill_tz: "Timezone",
};

const REQUIRED = new Set(["symbol", "side", "quantity", "price", "fill_time"]);

type Props = {
  onClose: () => void;
  onImported: () => void;
};

export function CsvImportWizard({ onClose, onImported }: Props) {
  const presets = useImportPresets();
  const [filename, setFilename] = useState<string | null>(null);
  const [csvText, setCsvText] = useState<string | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<CsvColumnMapping | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [presetName, setPresetName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onFile = useCallback((file: File) => {
    setFilename(file.name);
    setError(null);
    void file.text().then((text) => {
      setCsvText(text);
      const first = text.split(/\r?\n/).find((line) => line.trim().length > 0) ?? "";
      const cols = first.split(",").map((c) => c.trim()).filter(Boolean);
      setHeaders(cols);
      const columns: Record<string, string> = {};
      const guess = (field: string, hints: string[]) => {
        const hit = cols.find((h) => hints.some((hint) => h.toLowerCase() === hint));
        if (hit) columns[field] = hit;
      };
      guess("symbol", ["symbol", "ticker", "instrument"]);
      guess("side", ["side", "action", "buy/sell"]);
      guess("quantity", ["quantity", "qty", "shares", "contracts"]);
      guess("price", ["price", "fill price", "avg price"]);
      guess("fill_time", ["date", "fill time", "datetime", "time"]);
      guess("fees", ["fees", "commission", "fee"]);
      guess("contract_code", ["contract", "contract code", "expiry"]);
      setMapping({
        columns,
        default_currency: "USD",
        default_fill_tz: "America/New_York",
      });
      setPreview(null);
    });
  }, []);

  const mappingReady =
    mapping !== null &&
    [...REQUIRED].every((field) => mapping.columns[field as keyof typeof mapping.columns] !== undefined);

  const runPreview = async () => {
    if (!csvText || !filename || !mapping) return;
    setBusy(true);
    setError(null);
    const response = await api.POST("/v1/import/preview", {
      body: { filename, csv_text: csvText, mapping },
    });
    setBusy(false);
    if (!response.response.ok || !response.data) {
      setError(`Preview failed (${String(response.response.status)})`);
      return;
    }
    setPreview(response.data);
  };

  const runCommit = async () => {
    if (!csvText || !filename || !mapping) return;
    setBusy(true);
    setError(null);
    const response = await api.POST("/v1/import/commit", {
      body: { filename, csv_text: csvText, mapping },
    });
    setBusy(false);
    if (!response.response.ok || !response.data) {
      setError(`Import failed (${String(response.response.status)})`);
      return;
    }
    onImported();
    onClose();
  };

  const savePreset = async () => {
    if (!mapping || !presetName.trim()) return;
    setBusy(true);
    const preset = { name: presetName.trim(), mapping };
    const response = await api.PUT("/v1/import/presets/{name}", {
      params: { path: { name: preset.name } },
      body: { preset },
    });
    setBusy(false);
    if (!response.response.ok) {
      setError("Could not save preset");
      return;
    }
    await presets.refetch();
  };

  const applyPreset = (name: string) => {
    const hit = presets.data?.presets.find((p) => p.name === name);
    if (hit) {
      setMapping(hit.mapping);
      setPreview(null);
    }
  };

  const previewRows = useMemo(() => preview?.rows.slice(0, 12) ?? [], [preview]);

  return (
    <Modal title="CSV import" onClose={onClose}>
      <p className="hint">
        Map your broker&apos;s columns to fill fields. Nothing is broker-specific; save a preset once and reuse it on reimports (duplicates are skipped by row hash).
      </p>

      {presets.data && presets.data.presets.length > 0 ? (
        <div className="field-row">
          <label htmlFor="preset-select">Saved preset</label>
          <select
            id="preset-select"
            onChange={(e) => {
              applyPreset(e.target.value);
            }}
            defaultValue=""
          >
            <option value="" disabled>Select…</option>
            {presets.data.presets.map((p) => (
              <option key={p.name} value={p.name}>{p.name}</option>
            ))}
          </select>
        </div>
      ) : null}

      <input
        aria-label="CSV file"
        type="file"
        accept=".csv,text/csv"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
        }}
      />

      {mapping && headers.length > 0 ? (
        <section aria-labelledby="mapping-fields">
          <h4 id="mapping-fields">Column mapping</h4>
          <div className="mapping-grid">
            {Object.entries(FIELD_LABELS).map(([field, label]) => (
              <div key={field} className="field-row">
                <label htmlFor={`map-${field}`}>
                  {label}
                  {REQUIRED.has(field) ? " *" : ""}
                </label>
                <select
                  id={`map-${field}`}
                  value={mapping.columns[field as keyof typeof mapping.columns] ?? ""}
                  onChange={(e) => {
                    const value = e.target.value;
                    setMapping({
                      ...mapping,
                      columns: {
                        ...mapping.columns,
                        ...(value ? { [field]: value } : {}),
                      },
                    });
                    setPreview(null);
                  }}
                >
                  <option value="">—</option>
                  {headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          <div className="field-row">
            <label htmlFor="preset-name">Save as preset</label>
            <input
              id="preset-name"
              value={presetName}
              onChange={(e) => {
                setPresetName(e.target.value);
              }}
              placeholder="e.g. Generic futures export"
            />
            <button type="button" disabled={busy || !presetName.trim()} onClick={() => { void savePreset(); }}>
              Save preset
            </button>
          </div>
        </section>
      ) : null}

      {error ? <p role="alert">{error}</p> : null}

      <div className="button-row">
        <button type="button" className="primary" disabled={!mappingReady || busy} onClick={() => { void runPreview(); }}>
          Preview validation
        </button>
        <button
          type="button"
          className="primary"
          disabled={!preview || preview.trusted_row_count === 0 || busy}
          onClick={() => { void runCommit(); }}
        >
          Import trusted rows
        </button>
      </div>

      {preview ? (
        <section aria-labelledby="preview-summary">
          <h4 id="preview-summary">Preview</h4>
          <dl className="meta-grid">
            <div><dt>Rows</dt><dd className="num">{preview.row_count}</dd></div>
            <div><dt>Trusted</dt><dd className="num">{preview.trusted_row_count}</dd></div>
            <div><dt>Incomplete</dt><dd className="num">{preview.incomplete_count}</dd></div>
            <div><dt>Duplicates</dt><dd className="num">{preview.duplicate_count}</dd></div>
          </dl>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Price</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {previewRows.map((row) => (
                <tr key={row.source_row_number} className={row.is_complete ? "" : "row-flagged"}>
                  <td>{row.source_row_number}</td>
                  <td>{row.symbol_raw}</td>
                  <td>{row.side ?? "—"}</td>
                  <td className="num">{row.quantity ?? "—"}</td>
                  <td className="num">{row.price ?? "—"}</td>
                  <td>
                    {row.is_duplicate ? "Duplicate" : null}
                    {!row.is_complete ? "Incomplete" : null}
                    {row.is_complete && !row.is_duplicate ? "OK" : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {preview.rows.length > previewRows.length ? (
            <p className="hint">Showing first {previewRows.length} rows. Fees total in summary after import.</p>
          ) : null}
          <p className="hint">
            Realized P&amp;L uses contract multipliers for futures. Portfolio return is not shown without balances and cash flows.
          </p>
        </section>
      ) : null}
    </Modal>
  );
}
