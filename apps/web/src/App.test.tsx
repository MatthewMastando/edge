import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "./test/render";

describe("App shell", () => {
  it("labels demonstration data and shows the research navigation", async () => {
    await renderApp();
    expect((await screen.findAllByText(/DEMONSTRATION/)).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "+ New chat" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Agents" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Analytics" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Integrations" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Output" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("heading", { name: "6EZ6 session note" })).toBeInTheDocument();
  });
});
