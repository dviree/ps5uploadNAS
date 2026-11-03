import { describe, expect, it } from "vitest";

import type { LocalEntry } from "../api/localFs";
import { scanPackages } from "./pkgScan";

const tree: Record<string, LocalEntry[]> = {
  "/pkgs": [
    { name: "PS4 Game.pkg", path: "/pkgs/PS4 Game.pkg", is_dir: false, size: 5 },
    { name: "notes.txt", path: "/pkgs/notes.txt", is_dir: false, size: 1 },
  ],
  "/backport-updates-dlc": [
    { name: "Sackboy", path: "/backport-updates-dlc/Sackboy", is_dir: true, size: 0 },
    { name: "Ghost [PPSA26344] [DLC].pkg", path: "/backport-updates-dlc/Ghost [PPSA26344] [DLC].pkg", is_dir: false, size: 2 },
  ],
  "/backport-updates-dlc/Sackboy": [
    { name: "UP9000-PPSA01.pkg", path: "/backport-updates-dlc/Sackboy/UP9000-PPSA01.pkg", is_dir: false, size: 3 },
  ],
  "/games": [
    { name: "Cyberpunk [PPSA04029]", path: "/games/Cyberpunk [PPSA04029]", is_dir: true, size: 0 },
    { name: "pkg", path: "/games/pkg", is_dir: true, size: 0 },
  ],
  "/games/Cyberpunk [PPSA04029]": [
    { name: "sce_sys", path: "/games/Cyberpunk [PPSA04029]/sce_sys", is_dir: true, size: 0 },
    { name: "inside.pkg", path: "/games/Cyberpunk [PPSA04029]/inside.pkg", is_dir: false, size: 9 },
  ],
  "/games/pkg": [{ name: "Made.pkg", path: "/games/pkg/Made.pkg", is_dir: false, size: 7 }],
  "/ps5pkg": [{ name: "Made.pkg", path: "/ps5pkg/Made.pkg", is_dir: false, size: 7 }],
};
const listDir = async (p: string) => {
  const e = tree[p];
  if (!e) throw new Error(`no such folder ${p}`);
  return e;
};

describe("scanPackages", () => {
  it("finds every package in the roots and their folders, once, and never inside a game folder", async () => {
    const found = await scanPackages(["/pkgs", "/backport-updates-dlc", "/games", "/ps5pkg", "/gone"], listDir);
    expect(found.map((f) => f.path)).toEqual([
      "/pkgs/PS4 Game.pkg",
      "/backport-updates-dlc/Ghost [PPSA26344] [DLC].pkg",
      "/backport-updates-dlc/Sackboy/UP9000-PPSA01.pkg",
      "/games/pkg/Made.pkg",
    ]);
    expect(found[2]).toMatchObject({ root: "/backport-updates-dlc", folder: "Sackboy", size: 3 });
  });

  it("stops after the folder budget", async () => {
    const found = await scanPackages(["/backport-updates-dlc"], listDir, { maxDirs: 1 });
    expect(found.map((f) => f.name)).toEqual(["Ghost [PPSA26344] [DLC].pkg"]);
  });
});
