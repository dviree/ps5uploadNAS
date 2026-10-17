import { describe, expect, it } from "vitest";

import { canBeLz4, compatReportUrl, compatVerdict, type CompatEntry } from "./lz4";

const entry = (p: Partial<CompatEntry>): CompatEntry => ({
  works: 0,
  issues: 0,
  noStart: 0,
  crash: 0,
  reports: 0,
  ...p,
});

describe("lz4", () => {
  it("only a game that reads through AMPR can be LZ4", () => {
    expect(canBeLz4("ok")).toBe(true);
    expect(canBeLz4("runtime")).toBe(true);
    expect(canBeLz4("packed")).toBe(false);
    expect(canBeLz4("no_ampr")).toBe(false);
    expect(canBeLz4(undefined)).toBe(false);
  });

  it("sums up the community's reports", () => {
    expect(compatVerdict(entry({ works: 2, reports: 2 }))).toBe("good");
    expect(compatVerdict(entry({ issues: 1, crash: 1, reports: 2 }))).toBe("mixed");
    expect(compatVerdict(entry({ works: 1, noStart: 2, reports: 3 }))).toBe("bad");
    expect(compatVerdict(entry({ crash: 1, reports: 1 }))).toBe("bad");
  });

  it("opens a prefilled game report", () => {
    const u = new URL(compatReportUrl("PPSA01289", "Sackboy"));
    expect(u.pathname).toBe("/theghostonline/PS5-LZ4-Compression/issues/new");
    expect(u.searchParams.get("template")).toBe("compat.yml");
    expect(u.searchParams.get("title_id")).toBe("PPSA01289");
    expect(u.searchParams.get("title")).toBe("[Game report] Sackboy");
  });
});
