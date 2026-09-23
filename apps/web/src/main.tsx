import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { shouldUseMocks } from "./mocks/mode";
import "./styles.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("missing #root element");
}
const rootElement: HTMLElement = container;

async function boot(): Promise<void> {
  if (import.meta.env.DEV && shouldUseMocks()) {
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledRequest: "bypass" });
  }
  createRoot(rootElement).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void boot();
