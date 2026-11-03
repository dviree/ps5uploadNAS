// PKG Installer's scan: every install package in the engine's folders (in Docker, the NAS
// folders mounted into the container), found without walking into game folders.

import type { LocalEntry } from "../api/localFs";

export interface FoundPkg {
  name: string;
  path: string;
  size: number;
  /** The folder it was found under (one of the roots), for grouping. */
  root: string;
  /** Its folder inside that root ("" when it sits in the root itself). */
  folder: string;
}

const PKG = /\.f?pkg$/i;

/** Walk `roots` up to `maxDepth` folders down and return every .pkg (and .fpkg), each file once
 *  even when two roots show the same files (a folder mounted twice): the same name and size
 *  count as one. A game folder (one holding sce_sys) is not walked into, and a folder that
 *  cannot be read is skipped. At most `maxDirs` folders are read in all. */
export async function scanPackages(
  roots: string[],
  listDir: (path: string) => Promise<LocalEntry[]>,
  { maxDepth = 4, maxDirs = 3000 }: { maxDepth?: number; maxDirs?: number } = {},
): Promise<FoundPkg[]> {
  const found: FoundPkg[] = [];
  const seen = new Set<string>();
  let read = 0;
  for (const root of roots) {
    const queue: { dir: string; depth: number }[] = [{ dir: root, depth: 0 }];
    while (queue.length > 0 && read < maxDirs) {
      const { dir, depth } = queue.shift()!;
      read++;
      let entries: LocalEntry[];
      try {
        entries = await listDir(dir);
      } catch {
        continue;
      }
      if (depth > 0 && entries.some((e) => e.is_dir && e.name === "sce_sys")) continue;
      for (const e of entries) {
        if (e.is_dir) {
          if (depth + 1 <= maxDepth && !e.name.startsWith(".")) queue.push({ dir: e.path, depth: depth + 1 });
        } else if (PKG.test(e.name)) {
          const key = `${e.name}\u0000${e.size}`;
          if (seen.has(key)) continue;
          seen.add(key);
          const rel = dir === root ? "" : dir.slice(root.length).replace(/^[\\/]+/, "");
          found.push({ name: e.name, path: e.path, size: e.size, root, folder: rel });
        }
      }
    }
  }
  return found;
}
