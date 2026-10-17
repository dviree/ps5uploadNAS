import { describe, expect, it } from "vitest";

import { defaultLz4Url, normalizeLz4Url } from "./lz4Url";

describe("lz4Url", () => {
  it("puts ps5-lz4 on the ps5upload engine's host", () => {
    expect(defaultLz4Url("http://127.0.0.1:19113")).toBe(
      "http://127.0.0.1:5921",
    );
    expect(defaultLz4Url("http://nas.local:19113/ui")).toBe(
      "http://nas.local:5921",
    );
    expect(defaultLz4Url("https://192.168.1.10")).toBe(
      "https://192.168.1.10:5921",
    );
    expect(defaultLz4Url("http://[::1]:19113")).toBe("http://[::1]:5921");
    expect(defaultLz4Url("not a url")).toBe("http://127.0.0.1:5921");
  });

  it("normalizes what the user types", () => {
    expect(normalizeLz4Url("  192.168.1.10:5921/ ")).toBe(
      "http://192.168.1.10:5921",
    );
    expect(normalizeLz4Url("https://nas:5921")).toBe("https://nas:5921");
    expect(normalizeLz4Url("   ")).toBe("");
  });
});
