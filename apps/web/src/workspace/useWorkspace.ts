import { createContext, useContext } from "react";

import type { WorkspaceAction, WorkspaceState } from "./types";

export interface WorkspaceController {
  state: WorkspaceState;
  dispatch: (action: WorkspaceAction) => void;
}

export const WorkspaceContext = createContext<WorkspaceController | null>(null);

export function useWorkspace(): WorkspaceController {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error("WorkspaceProvider is missing");
  return context;
}
