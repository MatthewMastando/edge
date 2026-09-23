import { describe, expect, it } from "vitest";

import { hitTestBoxes } from "./geometry";
import { wilderRsi } from "./rsi";

describe("chart primitive hit testing", () => {
  it("prefers a marker that sits inside a zone", () => {
    const hit = hitTestBoxes(
      [
        { id: "zone", kind: "zone", x: 0, y: 0, width: 100, height: 80 },
        { id: "marker", kind: "marker", x: 40, y: 30, width: 12, height: 12 },
      ],
      46,
      36,
    );
    expect(hit?.id).toBe("marker");
  });

  it("ignores points outside every box", () => {
    expect(
      hitTestBoxes([{ id: "level", kind: "line", x: 0, y: 20, width: 200, height: 8 }], 10, 40),
    ).toBeNull();
  });
});

describe("wilderRsi", () => {
  it("returns 50 when the seed window has no gain and no loss", () => {
    const closes = Array.from({ length: 15 }, () => 1);
    const rsi = wilderRsi(closes);
    expect(rsi[14]).toBe(50);
    expect(rsi[0]).toBeNull();
  });

  it("returns 100 when price only rises", () => {
    const closes = Array.from({ length: 16 }, (_, index) => index + 1);
    const rsi = wilderRsi(closes);
    expect(rsi[14]).toBe(100);
  });
});
