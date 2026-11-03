import { describe, expect, it } from "vitest";

import {
  checkFrom,
  planInstallAll,
  titleIdOf,
  type PkgCheck,
} from "./pkgInstallPlan";

const item = (name: string, check: Partial<PkgCheck>) => ({
  path: `/pkgs/${name}`,
  name,
  check: {
    relation: "not-installed",
    installedVer: null,
    version: "01.00",
    category: "gd",
    contentId: "",
    ...check,
  } as PkgCheck,
});

describe("pkgInstallPlan", () => {
  it("reads the Title ID out of a content ID", () => {
    expect(titleIdOf("UP9000-PPSA01234_00-SACKBOYDLC000001")).toBe("PPSA01234");
    expect(titleIdOf("nonsense")).toBe("");
  });

  it("says what the console's preflight means for the package", () => {
    expect(
      checkFrom(
        { app_ver: "01.10", category: "gp" },
        { state: "different_version_installed", installedVersion: "01.00" },
      ),
    ).toMatchObject({
      relation: "newer",
      installedVer: "01.00",
      version: "01.10",
      category: "gp",
    });
    expect(
      checkFrom(
        { app_ver: "01.00" },
        { state: "installed", installedVersion: "01.00" },
      ).relation,
    ).toBe("same");
    expect(checkFrom({}, null).relation).toBe("unknown");
  });

  it("installs games, then updates, then DLC, and leaves out what the PS5 has or cannot take", () => {
    const plan = planInstallAll([
      item("dlc.pkg", {
        category: "ac",
        relation: "base-missing",
        contentId: "UP9000-PPSA00001_00-DLC1",
      }),
      item("update-old.pkg", {
        category: "gp",
        version: "01.02",
        relation: "newer",
        contentId: "UP9000-PPSA00002_00-X",
      }),
      item("update-new.pkg", {
        category: "gp",
        version: "01.10",
        relation: "newer",
        contentId: "UP9000-PPSA00002_00-X",
      }),
      item("game.pkg", {
        category: "gd",
        relation: "not-installed",
        contentId: "UP9000-PPSA00001_00-GAME",
      }),
      item("have.pkg", {
        category: "gd",
        relation: "same",
        contentId: "UP9000-PPSA00003_00-GAME",
      }),
      item("orphan-dlc.pkg", {
        category: "ac",
        relation: "base-missing",
        contentId: "UP9000-PPSA00009_00-DLC",
      }),
    ]);
    expect(plan.install.map((i) => i.name)).toEqual([
      "game.pkg",
      "update-new.pkg",
      "dlc.pkg",
    ]);
    expect(plan.skipped.map((s) => [s.item.name, s.why])).toEqual([
      ["update-old.pkg", "a newer update is in the list"],
      ["have.pkg", "same"],
      ["orphan-dlc.pkg", "the game isn't on the PS5"],
    ]);
  });
});
