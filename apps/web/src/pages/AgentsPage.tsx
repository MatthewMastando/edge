import { useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { StatusBadge } from "../components/StatusBadge";
import { formatInstant, stanceLabel } from "../lib/format";
import { useWorkspace } from "../workspace/useWorkspace";
import type { ArtifactRecord } from "../workspace/types";

export function AgentsPage() {
  const { state, dispatch } = useWorkspace();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [stance, setStance] = useState("all");
  const [tag, setTag] = useState("all");
  const tags = useMemo(() => [...new Set(state.artifacts.flatMap((artifact) => artifact.tags))].sort(), [state.artifacts]);

  const artifacts = state.artifacts.filter((artifact) => matches(artifact, state.drafts[artifact.id]?.presentationMarkdown ?? "", state.drafts[artifact.id]?.structured.stance ?? artifact.thesis.stance, query, stance, tag));

  return (
    <div className="page">
      <header className="page-head">
        <h2>Agents</h2>
        <p className="hint">Routines, runs, and saved artifacts. Search stays on this page; reopen returns to the workspace.</p>
      </header>

      <section aria-labelledby="routines">
        <h3 id="routines">Routines</h3>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Kind</th>
              <th>Schedule</th>
              <th>Cooldown</th>
              <th>Daily cap</th>
              <th>Last run</th>
              <th>Next</th>
            </tr>
          </thead>
          <tbody>
            {state.routines.map((routine) => (
              <tr key={routine.id}>
                <td>
                  {routine.name}
                  <div className="hint">{routine.instrumentLabel}</div>
                </td>
                <td>{routine.kind.replaceAll("_", " ")}</td>
                <td>{routine.schedule ? `${routine.schedule} · ${routine.timezone}` : "Trigger"}</td>
                <td className="num">{Math.round(routine.cooldownSeconds / 3600)}h</td>
                <td className="num">{routine.dailyCap}</td>
                <td>{routine.lastRunAt ? formatInstant(routine.lastRunAt) : "—"}</td>
                <td>{routine.nextRunAt ? formatInstant(routine.nextRunAt) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-labelledby="runs">
        <h3 id="runs">Runs</h3>
        <ul className="run-list">
          {state.runs.map((run) => {
            const artifact = state.artifacts.find((item) => item.runId === run.id);
            return (
              <li key={run.id}>
                <StatusBadge status={run.status} />
                <span>{artifact?.title ?? run.id}</span>
                <span className="hint">
                  {run.provider} · {run.provenance} · {formatInstant(run.started_at)}
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      <section aria-labelledby="artifacts">
        <h3 id="artifacts">Saved artifacts</h3>
        <div className="filters">
          <input
            aria-label="Search artifacts"
            value={query}
            placeholder="Search title, symbol, tag, or narrative"
            onChange={(event) => {
              setQuery(event.target.value);
            }}
          />
          <label>
            Stance
            <select
              aria-label="Filter by stance"
              value={stance}
              onChange={(event) => {
                setStance(event.target.value);
              }}
            >
              <option value="all">All</option>
              <option value="bullish">Bullish</option>
              <option value="bearish">Bearish</option>
              <option value="neutral">Neutral</option>
              <option value="insufficient_evidence">Insufficient evidence</option>
            </select>
          </label>
          <label>
            Tag
            <select
              aria-label="Filter by tag"
              value={tag}
              onChange={(event) => {
                setTag(event.target.value);
              }}
            >
              <option value="all">All</option>
              {tags.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>
        {artifacts.length === 0 ? <p className="hint">No artifacts match.</p> : null}
        <ul className="artifact-list">
          {artifacts.map((artifact) => {
            const draft = state.drafts[artifact.id];
            return (
              <li key={artifact.id}>
                <div>
                  <strong>{artifact.title}</strong>
                  <p className="hint">
                    {artifact.thesis.symbol}
                    {artifact.thesis.contract_code ? ` · ${artifact.thesis.contract_code}` : ""} ·{" "}
                    {stanceLabel(draft?.structured.stance ?? artifact.thesis.stance)}
                  </p>
                  <p className="tags-inline">{artifact.tags.join(" · ")}</p>
                </div>
                <button
                  type="button"
                  className="primary"
                  onClick={() => {
                    dispatch({ type: "selectArtifact", id: artifact.id });
                    void navigate({ to: "/" });
                  }}
                >
                  Reopen
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}

function matches(
  artifact: ArtifactRecord,
  narrative: string,
  stance: string,
  query: string,
  stanceFilter: string,
  tag: string,
): boolean {
  if (stanceFilter !== "all" && stance !== stanceFilter) return false;
  if (tag !== "all" && !artifact.tags.includes(tag)) return false;
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  const haystack = [artifact.title, artifact.thesis.symbol, artifact.thesis.contract_code ?? "", narrative, ...artifact.tags]
    .join(" ")
    .toLowerCase();
  return haystack.includes(needle);
}
