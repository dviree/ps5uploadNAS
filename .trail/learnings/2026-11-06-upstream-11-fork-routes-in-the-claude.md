---
title: "Upstream 11: fork routes in the MCP catalog, ffpfsc through buildImage, upstream's staging cleanup"
author: Claude
date: 2026-11-06
branch: main
id: l-2b567735
scope: repo
status: active
src: agent
touches:
  - engine/crates/ps5upload-engine/src/mcp/catalog_routes.rs
  - client/src/screens/Convert/index.tsx
  - client/src/screens/FileSystem/index.tsx
  - client/src/state/fpkgConversion.ts
---

Upstream 11.x tests that every route the engine mounts is in mcp/catalog_routes.rs ROUTES and in api/openapi.json: a route the fork adds (the /api/lz4/* ones) must be added to ROUTES and the file regenerated with cargo run -p ps5upload-apidoc. Upstream removed the separate .ffpfsc compress (route, client compress and the ffpfsc pipeline mode): My games' Convert to .ffpfsc now calls buildImage(path, out, true, ...) for folders and images alike. Upstream's lib/browserStaging (stageWithTask, noteStaged) replaced the fork's own staging cleanup in Files: a staged copy is deleted once it has been seen in use and then is not (2 s debounce), so a test must let the transfer run a few polls. useFpkgConversion.buildFolder is (source, outputDir, keepBoth, own, lz4, thenSend). Upstream's default_console and the fork's ps5_addr are both in /api/version.
