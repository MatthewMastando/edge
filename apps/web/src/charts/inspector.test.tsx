import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderApp } from "../test/render";

describe("annotation inspector", () => {
  it("shows the calculation and confirmation time for a selected annotation", async () => {
    const user = userEvent.setup();
    await renderApp();
    await user.click(await screen.findByRole("button", { name: "Bullish FVG" }));
    expect(screen.getByTestId("inspector")).toHaveTextContent("low(C) 1.17350");
    expect(screen.getByTestId("inspector")).toHaveTextContent(/Sep 22, 2026/);
    expect(screen.getByText("fvg")).toBeInTheDocument();
  });
});