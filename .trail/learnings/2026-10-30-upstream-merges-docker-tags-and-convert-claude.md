---
title: "Upstream merges: docker tags and Convert Games route"
author: Claude
date: 2026-10-30
branch: main
id: l-306e5d29
scope: repo
status: active
src: agent
touches:
  - ".github/workflows/docker-engine.yml"
  - client/src/App.tsx
  - client/src/layout/navItems.ts
  - client/src/screens/Convert/index.tsx
---

When merging phantomptr/ps5upload: upstream's docker-engine.yml tags only the version and moves :latest on release promotion; this fork has no releases, so the merge jobs must keep tagging lz4-<commit>, lz4 and latest (the NAS pulls :lz4), or the NAS never updates. Upstream renamed Convert to /workshop (FpkgConvert); here /workshop renders screens/Convert (My games, Convert, Compatibility) and the menu entry says Convert Games, because the LZ4 tabs live there. A link with state.source/state.sources or ?view= opens the Convert tab. New upstream workflows get workflow_dispatch only (release-cache and ci-runner-retry would build desktop code).
