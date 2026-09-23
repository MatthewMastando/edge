import { Link, useNavigate } from "@tanstack/react-router";

import type { SessionUser } from "../auth/session";
import { useHealth } from "../api/queries";
import { useWorkspace } from "../workspace/useWorkspace";

export function LeftRail({ user }: { user: SessionUser }) {
  const { state, dispatch } = useWorkspace();
  const health = useHealth();
  const navigate = useNavigate();
  const recent = state.conversations.slice(0, 6);

  return (
    <nav className="rail" aria-label="Workspace">
      <Link to="/" className="rail-brand">
        <span className="mark">TRW</span>
        <span>Research</span>
      </Link>
      <button
        type="button"
        className="rail-button"
        onClick={() => {
          dispatch({ type: "openNewChat" });
          void navigate({ to: "/" });
        }}
      >
        + New chat
      </button>
      <ul className="rail-recent">
        {recent.map((conversation) => (
          <li key={conversation.id}>
            <button
              type="button"
              className={conversation.id === state.activeConversationId ? "rail-link is-current" : "rail-link"}
              onClick={() => {
                dispatch({ type: "selectConversation", id: conversation.id });
                void navigate({ to: "/" });
              }}
            >
              {conversation.title}
            </button>
          </li>
        ))}
      </ul>
      <div className="rail-section">
        <Link to="/agents" className="rail-link">
          Agents
        </Link>
        <Link to="/analytics" className="rail-link">
          Analytics
        </Link>
        <Link to="/integrations" className="rail-link">
          Integrations
        </Link>
      </div>
      <footer className="rail-footer">
        <p>{user.label}</p>
        <p className="hint">{user.source === "supabase" ? "Signed in" : "Local session"}</p>
        <p className="hint">Research only. No order routing.</p>
        {health.data ? (
          <p className="hint">
            {health.data.service} {health.data.version} · order writes off
          </p>
        ) : health.isError ? (
          <p className="hint">API unreachable. The local workspace is still editable.</p>
        ) : (
          <p className="hint">Checking the API…</p>
        )}
      </footer>
    </nav>
  );
}
