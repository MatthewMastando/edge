import { useEffect, useMemo, useReducer, type ReactNode } from "react";

import { workspaceReducer } from "./reducer";
import { loadWorkspace, saveWorkspace } from "./storage";
import { WorkspaceContext, type WorkspaceController } from "./useWorkspace";

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(workspaceReducer, undefined, loadWorkspace);

  useEffect(() => {
    saveWorkspace(state);
  }, [state]);

  const pendingKey = Object.values(state.drafts)
    .filter((draft) => draft.saveState === "pending")
    .map((draft) => `${draft.artifactId}:${draft.updatedAt}`)
    .join(",");

  useEffect(() => {
    if (!pendingKey) return;
    const timer = window.setTimeout(() => {
      dispatch({ type: "draftsSaved" });
    }, 400);
    return () => {
      window.clearTimeout(timer);
    };
  }, [pendingKey]);

  const value = useMemo<WorkspaceController>(() => ({ state, dispatch }), [state]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
