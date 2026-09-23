import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, type RenderResult } from "@testing-library/react";
import { StrictMode } from "react";

import { createAppRouter } from "../router";
import { WorkspaceProvider } from "../workspace/WorkspaceProvider";

export async function renderApp(path = "/"): Promise<RenderResult> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  await router.load();
  return render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <WorkspaceProvider>
          <RouterProvider router={router} />
        </WorkspaceProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
}
