import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderApp } from "../test/render";

function holdScroll(element: HTMLElement, top: number): void {
  let value = 0;
  Object.defineProperty(element, "scrollTop", {
    configurable: true,
    get: () => value,
    set: (next: number) => {
      value = next;
    },
  });
  element.scrollTop = top;
  element.dispatchEvent(new Event("scroll"));
}

describe("layout preservation", () => {
  it("keeps the conversation, edits, and scroll when the mode pill changes", async () => {
    const user = userEvent.setup();
    await renderApp();

    const entry = await screen.findByRole("textbox", { name: "Entry" });
    await user.type(entry, "1.1740");

    const chat = screen.getByTestId("chat-scroll");
    const report = screen.getByTestId("report-scroll");
    holdScroll(chat, 140);
    holdScroll(report, 220);

    expect(screen.getByText(/Is there a level to work with/)).toBeInTheDocument();
    expect(screen.getByTestId("workspace")).toHaveAttribute("data-mode", "output");
    expect(screen.getByTestId("report-scroll")).toHaveAttribute("data-column", "main");
    expect(screen.getByTestId("chat-column")).toHaveAttribute("data-column", "side");

    await user.click(screen.getByRole("radio", { name: "Agent" }));

    expect(screen.getByTestId("workspace")).toHaveAttribute("data-mode", "agent");
    expect(screen.getByTestId("report-scroll")).toHaveAttribute("data-column", "side");
    expect(screen.getByTestId("chat-column")).toHaveAttribute("data-column", "main");
    expect(screen.getByRole("textbox", { name: "Entry" })).toHaveValue("1.1740");
    expect(screen.getByText(/Is there a level to work with/)).toBeInTheDocument();
    expect(screen.getByTestId("chat-scroll")).toHaveAttribute("data-scroll", "140");
    expect(screen.getByTestId("chat-scroll").scrollTop).toBe(140);
    expect(screen.getByTestId("report-scroll")).toHaveAttribute("data-scroll", "220");
    expect(screen.getByTestId("report-scroll").scrollTop).toBe(220);
    expect(screen.getByRole("heading", { name: "6EZ6 session note" })).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Output" }));
    expect(screen.getByRole("textbox", { name: "Entry" })).toHaveValue("1.1740");
    expect(screen.getByTestId("chat-scroll").scrollTop).toBe(140);
    expect(screen.getByTestId("report-scroll").scrollTop).toBe(220);
  });
});
