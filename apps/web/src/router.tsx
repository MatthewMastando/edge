import { createRootRoute, createRoute, createRouter, type createMemoryHistory } from "@tanstack/react-router";

import { Shell } from "./layout/Shell";
import { ResearchWorkspace } from "./layout/Workspace";
import { AgentsPage } from "./pages/AgentsPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { IntegrationsPage } from "./pages/IntegrationsPage";

const rootRoute = createRootRoute({ component: Shell });

const workspaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: ResearchWorkspace,
});

const agentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/agents",
  component: AgentsPage,
});

const analyticsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/analytics",
  component: AnalyticsPage,
});

const integrationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/integrations",
  component: IntegrationsPage,
});

const routeTree = rootRoute.addChildren([workspaceRoute, agentsRoute, analyticsRoute, integrationsRoute]);

type MemoryHistory = ReturnType<typeof createMemoryHistory>;

export function createAppRouter(history?: MemoryHistory) {
  return createRouter({
    routeTree,
    ...(history ? { history } : {}),
  });
}
