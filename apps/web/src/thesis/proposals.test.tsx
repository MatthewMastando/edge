import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderApp } from "../test/render";

describe("agent proposals", () => {
  it("accepts a proposal into the draft and an immutable revision", async () => {
    const user = userEvent.setup();
    await renderApp();
    const costs = await screen.findByRole("textbox", { name: "Estimated costs" });
    expect(costs).toHaveValue("");

    await user.click(screen.getByRole("button", { name: "Accept proposal" }));

    expect(screen.getByRole("textbox", { name: "Estimated costs" })).toHaveValue("2.50");
    expect(screen.getByRole("button", { name: /Revision 2 Accepted proposal/ })).toBeInTheDocument();
    expect(screen.getByText(/Proposal accepted/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept proposal" })).not.toBeInTheDocument();
    expect(await screen.findByText(/not as a setup to trade/)).toBeInTheDocument();
  });

  it("rejects a proposal without changing the draft or revisions", async () => {
    const user = userEvent.setup();
    await renderApp();
    expect(await screen.findByRole("textbox", { name: "Estimated costs" })).toHaveValue("");

    await user.click(screen.getByRole("button", { name: "Reject proposal" }));

    expect(screen.getByRole("textbox", { name: "Estimated costs" })).toHaveValue("");
    expect(screen.getByText(/Proposal rejected/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Revision 2/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Revision 1/ })).toHaveLength(1);
  });
});
