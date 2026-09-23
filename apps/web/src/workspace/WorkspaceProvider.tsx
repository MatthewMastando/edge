import { useEffect, useMemo, useReducer, useRef, type ReactNode } from "react";

import { shouldUseMocks } from "../mocks/mode";
import { loadSavedWorkspace, saveDraftRemote } from "../research/fixture";
import { createLiveState, readView, saveView } from "./live";
import { workspaceReducer } from "./reducer";
import { loadWorkspace, saveWorkspace } from "./storage";
import { WorkspaceContext, type WorkspaceController } from "./useWorkspace";

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const live = !shouldUseMocks();
  const [state, dispatch] = useReducer(workspaceReducer, undefined, live ? createLiveState : loadWorkspace);
  const restored = useRef(false);

  useEffect(() => {
    if (live) saveView(state);
    else saveWorkspace(state);
  }, [live, state]);

  useEffect(() => {
    if (!live || restored.current) return;
    restored.current = true;
    const preferred = readView().selectedArtifactId;
    void loadSavedWorkspace(preferred).then((payload) => {
      if (!payload) return;
      dispatch({ type: "restoreSaved", ...payload });
    });
  }, [live]);

  const pendingKey = Object.values(state.drafts)
    .filter((draft) => draft.saveState === "pending")
    .map((draft) => `${draft.artifactId}:${draft.updatedAt}`)
    .join(",");

  useEffect(() => {
    if (!pendingKey) return;
    const pending = Object.values(state.drafts).filter((draft) => draft.saveState === "pending");
    const timer = window.setTimeout(() => {
      if (!live) {
        dispatch({ type: "draftsSaved" });
        return;
      }
      void Promise.all(pending.map((draft) => saveDraftRemote(draft)))
        .then(() => {
          dispatch({ type: "draftsSaved" });
        })
        .catch(() => {
          // Leave the draft pending so the next edit retries the save.
        });
    }, 400);
    return () => {
      window.clearTimeout(timer);
    };
  }, [live, pendingKey, state.drafts]);

  const value = useMemo<WorkspaceController>(() => ({ state, dispatch }), [state]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
