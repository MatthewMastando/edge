import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderApp } from "../test/render";

describe("conversation and artifact", () => {
  it("opens the artifact attached to a recent conversation", async () => {
    const user = userEvent.setup();
    await renderApp("/agents");

    const reopen = await screen.findAllByRole("button", { name: "Reopen" });
    const gold = reopen[1];
    if (!gold) throw new Error("GCZ6 reopen control is missing");
    await user.click(gold);
    expect(await screen.findByRole("heading", { name: "GCZ6 fixture brief" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "6EZ6 intraday" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "6EZ6 intraday" }));

    expect(await screen.findByRole("heading", { name: "6EZ6 session note" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "6EZ6 intraday" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "GCZ6 fixture brief" })).not.toBeInTheDocument();
  });

  it("keeps the open artifact when a new chat has no attachment", async () => {
    const user = userEvent.setup();
    await renderApp();
    expect(await screen.findByRole("heading", { name: "6EZ6 session note" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "+ New chat" }));
    await user.click(screen.getByRole("button", { name: "Start conversation" }));

    expect(screen.getByRole("heading", { name: "6EZ6 session note" })).toBeInTheDocument();
    expect(screen.getByText(/No attachment/)).toBeInTheDocument();
  });
});
