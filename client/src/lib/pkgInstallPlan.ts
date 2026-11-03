// PKG Installer: what is already on the PS5, per package, and what Install all sends, after
// ps5-lz4's pkg_install_plan: games first, then updates, then DLC; a package already on the
// PS5 (or an older one than what is there) is left out, and so is an update or DLC whose game
// is neither on the PS5 nor in the batch.

import { inStreamOrder } from "./streamSelection";
import {
  installedFromPreflight,
  type InstalledRelation,
} from "./packageChecks";

/** What the header read and the console's preflight said about one package. */
export interface PkgCheck {
  /** "checking" while it is read; "unknown" when the header or the console could not say. */
  relation: InstalledRelation | "checking" | "unknown";
  installedVer: string | null;
  /** The package's APP_VER. */
  version: string;
  /** PARAM.SFO CATEGORY: "gd" a game, "gp" an update, "ac" DLC. */
  category: string;
  contentId: string;
}

/** The Title ID in a content ID ("UP9000-PPSA01234_00-..." gives "PPSA01234"). */
export function titleIdOf(contentId: string): string {
  const m = /^[A-Z0-9]{6}-([A-Z]{4}\d{5})_/i.exec(contentId);
  return m ? m[1].toUpperCase() : "";
}

/** A package's check from its header and the console's preflight answer. */
export function checkFrom(
  head:
    | {
        content_id?: string;
        category?: string;
        app_ver?: string;
        platform?: string;
      }
    | undefined,
  preflight: { state: string; installedVersion: string | null } | null,
): PkgCheck {
  const version = head?.app_ver ?? "";
  const r = installedFromPreflight(version, preflight, head?.platform);
  return {
    relation: r?.relation ?? "unknown",
    installedVer: r?.installedVer ?? null,
    version,
    category: head?.category ?? "",
    contentId: head?.content_id ?? "",
  };
}

/** Whether Install all sends it by itself: not on the PS5 yet, or newer than what is there. */
function wanted(c: PkgCheck): boolean {
  return c.relation === "not-installed" || c.relation === "newer";
}

/** The packages Install all sends, in the order the PS5 needs them, with why each other one
 *  is left out. */
export function planInstallAll<T extends { path: string; name: string }>(
  items: (T & { check: PkgCheck })[],
): { install: T[]; skipped: { item: T; why: string }[] } {
  const games = new Set(
    items
      .filter((i) => i.check.category === "gd" && wanted(i.check))
      .map((i) => titleIdOf(i.check.contentId)),
  );
  // Of several updates for one game, only the newest goes.
  const newest = new Map<string, T & { check: PkgCheck }>();
  for (const i of items) {
    if (i.check.category !== "gp") continue;
    const t = titleIdOf(i.check.contentId);
    const cur = newest.get(t);
    if (
      !cur ||
      i.check.version.localeCompare(cur.check.version, undefined, {
        numeric: true,
      }) > 0
    )
      newest.set(t, i);
  }
  const install: (T & { check: PkgCheck })[] = [];
  const skipped: { item: T; why: string }[] = [];
  for (const i of items) {
    const c = i.check;
    const t = titleIdOf(c.contentId);
    if (c.category === "gp" && newest.get(t) !== i)
      skipped.push({ item: i, why: "a newer update is in the list" });
    else if (c.relation === "base-missing" && !games.has(t))
      skipped.push({ item: i, why: "the game isn't on the PS5" });
    else if (c.relation === "base-missing" || wanted(c)) install.push(i);
    else
      skipped.push({
        item: i,
        why: c.relation === "checking" ? "still checking" : c.relation,
      });
  }
  return {
    install: inStreamOrder(
      install.map((i) => ({ ...i, category: i.check.category })),
    ),
    skipped,
  };
}
