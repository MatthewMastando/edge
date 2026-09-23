import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderApp } from "../test/render";
import { WORKSPACE_STORAGE_KEY } from "../workspace/storage";
import type { WorkspaceState } from "../workspace/types";

describe("draft autosave", () => {
  it("autosaves structured edits without creating a revision, then keeps an immutable revision", async () => {
    const user = userEvent.setup();
    await renderApp();

    const costs = await screen.findByRole("textbox", { name: "Estimated costs" });
    expect(screen.getByTestId("draft-status")).toHaveTextContent("Draft saved");
    expect(screen.getAllByRole("button", { name: /Revision 1/ })).toHaveLength(1);

    await user.type(costs, "3.25");
    expect(screen.getByTestId("draft-status")).toHaveTextContent("Saving draft");
    await waitFor(() => {
      expect(screen.getByTestId("draft-status")).toHaveTextContent("Draft saved");
    });
    expect(screen.getAllByRole("button", { name: /Revision 1/ })).toHaveLength(1);

    const raw = localStorage.getItem(WORKSPACE_STORAGE_KEY);
    expect(raw).toContain("3.25");

    await user.click(screen.getByRole("button", { name: "Save structured revision" }));
    expect(screen.getByRole("button", { name: /Revision 2 Structured edit/ })).toBeInTheDocument();

    await user.clear(costs);
    await user.type(costs, "9.00");
    await user.click(screen.getByRole("button", { name: /Revision 1 Generated/ }));
    expect(screen.getByRole("textbox", { name: "Estimated costs" })).toHaveValue("");
    expect(screen.getByTestId("draft-status")).toHaveTextContent("Viewing revision 1");
  });
});

describe("workspace storage", () => {
  it("reopens the autosaved draft after a remount", async () => {
    const user = userEvent.setup();
    const first = await renderApp();
    const costs = await screen.findByRole("textbox", { name: "Estimated costs" });
    await user.type(costs, "4.50");
    await waitFor(() => {
      expect(screen.getByTestId("draft-status")).toHaveTextContent("Draft saved");
    });
    first.unmount();

    await renderApp();
    expect(await screen.findByRole("textbox", { name: "Estimated costs" })).toHaveValue("4.50");
    const stored = localStorage.getItem(WORKSPACE_STORAGE_KEY);
    const parsed = JSON.parse(stored ?? "{}") as { state?: WorkspaceState };
    expect(parsed.state?.drafts).toBeTruthy();
  });
});
