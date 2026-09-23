import { describe, expect, it } from "vitest";

import { chartPalette } from "./palette";

describe("chartPalette", () => {
  it("uses the shell text color for labels so light mode stays readable", () => {
    const host = document.createElement("div");
    host.style.setProperty("--text", "#1d1b17");
    host.style.setProperty("--text-dim", "#5e584e");
    host.style.setProperty("--up", "#2f6b45");
    host.style.setProperty("--down", "#8d3d36");
    host.style.setProperty("--accent", "#8a5a22");
    host.style.setProperty("--accent-ink", "#fff8ee");
    host.style.setProperty("--line", "#d5cfc3");
    host.style.setProperty("--line-strong", "#b7b0a2");
    document.body.appendChild(host);

    const palette = chartPalette(host);

    expect(palette.label).toBe("#1d1b17");
    expect(palette.textDim).toBe("#5e584e");
    expect(palette.zoneBullStroke).toBe("#2f6b45");
    expect(palette.zoneBull).toBe("rgba(47, 107, 69, 0.22)");
    expect(palette.level).toBe("#8a5a22");
    expect(palette.levelInk).toBe("#fff8ee");
    host.remove();
  });
});
