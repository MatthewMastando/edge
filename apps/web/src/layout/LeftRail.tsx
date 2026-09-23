import { Link, useNavigate, useRouterState } from "@tanstack/react-router";

import { useHealth } from "../api/queries";
import type { SessionUser } from "../auth/session";
import { useWorkspace } from "../workspace/useWorkspace";

const PAGES = [
  { to: "/agents", label: "Agents" },
  { to: "/analytics", label: "Analytics" },
  { to: "/integrations", label: "Integrations" },
] as const;

function pageIsCurrent(pathname: string, to: string): boolean {
  return pathname === to || pathname.startsWith(`${to}/`);
}

export function LeftRail({ user }: { user: SessionUser }) {
  const { state, dispatch } = useWorkspace();
  const health = useHealth();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (router) => router.location.pathname });
  const onWorkspace = pathname === "/";
  const recent = state.conversations.slice(0, 6);

  return (
    <nav className="rail" aria-label="Workspace">
      <Link to="/" className="rail-brand" activeOptions={{ exact: true }}>
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
      {recent.length > 0 ? (
        <div className="rail-block rail-block-recent">
          <p className="rail-label" id="recent-label">
            Recent
          </p>
          <ul className="rail-recent" aria-labelledby="recent-label">
            {recent.map((conversation) => {
              const current = onWorkspace && conversation.id === state.activeConversationId;
              return (
                <li key={conversation.id}>
                  <button
                    type="button"
                    className={current ? "rail-link is-current" : "rail-link"}
                    aria-current={current ? "page" : undefined}
                    onClick={() => {
                      dispatch({ type: "selectConversation", id: conversation.id });
                      void navigate({ to: "/" });
                    }}
                  >
                    {conversation.title}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      <div className="rail-block">
        <p className="rail-label" id="pages-label">
          Go to
        </p>
        <ul className="rail-pages" aria-labelledby="pages-label">
          {PAGES.map((page) => {
            const current = pageIsCurrent(pathname, page.to);
            return (
              <li key={page.to}>
                <Link
                  to={page.to}
                  className={current ? "rail-link is-current" : "rail-link"}
                  aria-current={current ? "page" : undefined}
                >
                  {page.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
      <footer className="rail-footer">
        <p className="rail-user">{user.label}</p>
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
