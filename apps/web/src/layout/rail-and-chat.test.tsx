import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderApp } from "../test/render";

describe("rail and chat polish", () => {
  it("marks the open page in the rail", async () => {
    const user = userEvent.setup();
    await renderApp();

    expect(await screen.findByRole("button", { name: "6EZ6 intraday" })).toHaveClass("is-current");
    expect(screen.getByRole("link", { name: "Agents" })).not.toHaveAttribute("aria-current");

    await user.click(screen.getByRole("link", { name: "Analytics" }));

    expect(await screen.findByRole("link", { name: "Analytics" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Agents" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("button", { name: "6EZ6 intraday" })).not.toHaveClass("is-current");
  });

  it("scrolls a new chat reply into view", async () => {
    const user = userEvent.setup();
    await renderApp();

    const chat = await screen.findByTestId("chat-scroll");
    Object.defineProperty(chat, "scrollHeight", { configurable: true, value: 640 });
    let value = 12;
    Object.defineProperty(chat, "scrollTop", {
      configurable: true,
      get: () => value,
      set: (next: number) => {
        value = next;
      },
    });

    await user.type(screen.getByRole("textbox", { name: "Message" }), "Where is the level?");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/I can discuss 6EZ6/)).toBeInTheDocument();
    expect(chat.scrollTop).toBe(640);
    expect(chat).toHaveAttribute("data-scroll", "640");
  });
});
