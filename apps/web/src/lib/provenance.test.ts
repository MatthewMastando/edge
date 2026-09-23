import { describe, expect, it } from "vitest";

import { formatDecimal, provenanceLabel } from "./provenance";

describe("provenanceLabel", () => {
  it("marks fixture and recorded output as demonstration", () => {
    expect(provenanceLabel("fixture").isDemonstration).toBe(true);
    expect(provenanceLabel("recorded").isDemonstration).toBe(true);
    expect(provenanceLabel("live").isDemonstration).toBe(false);
  });
});

describe("formatDecimal", () => {
  it("keeps exact decimals and trims trailing zeros", () => {
    expect(formatDecimal("1.17250000")).toBe("1.1725");
    expect(formatDecimal("6512.25000000")).toBe("6512.25");
    expect(formatDecimal("48.00000000")).toBe("48");
    expect(formatDecimal("112840")).toBe("112840");
  });

  it("does not round through floating point", () => {
    expect(formatDecimal("0.10000000000000001")).toBe("0.1");
    expect(formatDecimal("123456789.12345678")).toBe("123456789.12345678");
  });
});
