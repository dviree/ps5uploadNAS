---
title: "Folder builds: keepBoth before lz4"
author: Claude
date: 2026-11-03
branch: main
id: l-40af7c07
scope: repo
status: active
src: agent
touches:
  - client/src/state/fpkgConversion.ts
  - client/src/api/fpkg.ts
  - engine/crates/ps5upload-engine/src/fpkg_api.rs
---

Upstream 10.7 added keepBoth (number a taken name instead of refusing) to folder builds in the same argument slot where this fork had lz4. Decided: upstream's keepBoth comes first in useFpkgConversion.buildFolder(source, outputDir, keepBoth, lz4, thenSend) and fpkg.buildFolder(..., entry, keepBoth, lz4), so upstream's callers (the queue runner, Workshop, ImageBrowser) need no change; the fork's Convert Games and its tests pass false before lz4. The engine's FolderBuildReq carries both keep_both and ampr_lz4, and the web UI sends both with the long timeout. A package Convert makes still goes to the pkg folder even when Output is set to beside the source.
