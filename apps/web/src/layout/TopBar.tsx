import { useRouterState } from "@tanstack/react-router";

import { useWorkspace } from "../workspace/useWorkspace";
import type { LayoutMode } from "../workspace/types";

export function TopBar() {
  const { state, dispatch } = useWorkspace();
  const pathname = useRouterState({ select: (router) => router.location.pathname });
  const artifact = state.artifacts.find((item) => item.id === state.selectedArtifactId);
  const onWorkspace = pathname === "/";

  return (
    <header className="topbar">
      <p className="top-title">{onWorkspace ? (artifact?.title ?? "Workspace") : pageTitle(pathname)}</p>
      {onWorkspace ? (
        <div className="mode-pill" role="radiogroup" aria-label="Layout">
          <ModeOption mode="output" current={state.mode} onSelect={(mode) => { dispatch({ type: "setMode", mode }); }} />
          <ModeOption mode="agent" current={state.mode} onSelect={(mode) => { dispatch({ type: "setMode", mode }); }} />
        </div>
      ) : (
        <p className="hint">Layout applies to the research workspace.</p>
      )}
    </header>
  );
}

function ModeOption({
  mode,
  current,
  onSelect,
}: {
  mode: LayoutMode;
  current: LayoutMode;
  onSelect: (mode: LayoutMode) => void;
}) {
  const label = mode === "output" ? "Output" : "Agent";
  return (
    <button
      type="button"
      role="radio"
      aria-checked={current === mode}
      className={current === mode ? "mode-option is-selected" : "mode-option"}
      data-testid={`mode-${mode}`}
      onClick={() => {
        onSelect(mode);
      }}
    >
      {label}
    </button>
  );
}

function pageTitle(pathname: string): string {
  if (pathname.startsWith("/agents")) return "Agents";
  if (pathname.startsWith("/analytics")) return "Analytics";
  if (pathname.startsWith("/integrations")) return "Integrations";
  return "Workspace";
}
