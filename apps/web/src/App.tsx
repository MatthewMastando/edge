import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { useState } from "react";

import { createAppRouter } from "./router";
import { WorkspaceProvider } from "./workspace/WorkspaceProvider";

export function App() {
  const [router] = useState(() => createAppRouter());
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false, staleTime: 60_000 } },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <WorkspaceProvider>
        <RouterProvider router={router} />
      </WorkspaceProvider>
    </QueryClientProvider>
  );
}
