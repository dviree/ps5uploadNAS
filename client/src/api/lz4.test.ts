import { describe, expect, it } from "vitest";

import {
  canBeLz4,
  compatReportUrl,
  compatVerdict,
  ffpfscCells,
  ffpfscRowsFor,
  ffpfscTone,
  type CompatEntry,
  type FfpfscSheet,
} from "./lz4";

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
    expect(compatVerdict(entry({ issues: 1, crash: 1, reports: 2 }))).toBe(
      "mixed",
    );
    expect(compatVerdict(entry({ works: 1, noStart: 2, reports: 3 }))).toBe(
      "bad",
    );
    expect(compatVerdict(entry({ crash: 1, reports: 1 }))).toBe("bad");
  });

  it("opens a prefilled game report", () => {
    const u = new URL(compatReportUrl("PPSA01289", "Sackboy"));
    expect(u.pathname).toBe("/theghostonline/PS5-LZ4-Compression/issues/new");
    expect(u.searchParams.get("template")).toBe("compat.yml");
    expect(u.searchParams.get("title_id")).toBe("PPSA01289");
    expect(u.searchParams.get("title")).toBe("[Game report] Sackboy");
  });

  it("finds a game in the .ffpfsc list by Title ID, else by name", () => {
    const sheet: FfpfscSheet = {
      url: "",
      headers: ["Game", "ID", "Works?"],
      rows: [
        { Game: "Astro Bot", ID: "PPSA01234", "Works?": "Yes" },
        { Game: "Marvel's Spider-Man 2", "Works?": "No, black screen" },
      ],
    };
    expect(ffpfscRowsFor(sheet, "ppsa01234", "x")).toHaveLength(1);
    expect(
      ffpfscRowsFor(sheet, "PPSA99999", "Marvel's Spider-Man 2 [PPSA99999]")[0][
        "Works?"
      ],
    ).toBe("No, black screen");
    expect(ffpfscRowsFor(sheet, "PPSA99999", "Unknown")).toEqual([]);
    expect(ffpfscCells(sheet.headers, sheet.rows[1])).toEqual([
      ["Game", "Marvel's Spider-Man 2"],
      ["Works?", "No, black screen"],
    ]);
  });

  it("reads a sheet cell as works or not", () => {
    expect(ffpfscTone("Yes")).toBe("good");
    expect(ffpfscTone("✅")).toBe("good");
    expect(ffpfscTone("Crashes in chapter 2")).toBe("bad");
    expect(ffpfscTone("01.005")).toBe(null);
  });
});
