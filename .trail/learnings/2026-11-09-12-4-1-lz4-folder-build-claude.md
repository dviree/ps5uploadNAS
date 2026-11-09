---
title: "12.4.1: LZ4 folder build is build_packed"
author: Claude
date: 2026-11-09
branch: main
id: l-9ffc3631
scope: repo
status: active
src: agent
touches:
  - "engine/crates/ps5upload-engine/src/folder_build.rs"
  - "engine/crates/ps5upload-engine/src/fpkg_api.rs"
  - "client/src/api/fpkg.ts"
  - "client/src/state/fpkgConversion.ts"
  - "client/src/screens/FileSystem/index.tsx"
  - "client/e2e/files-device-upload.spec.ts"
---

Decided (upstream 12.4.1 merge): upstream's folder build now goes through write_checked_to/write_checked_here with a Check closure (Written::Dir|Tree) and build_to takes a required reopen. The fork no longer changes build()'s reopen to Option: an LZ4 pack overlay is written by folder_build::build_packed, which calls write_checked_here_with (the same writer, its check also given the tree written) and reads back against the overlay itself. LZ4 folders are local only (a server destination is refused in fpkg_api). fpkg.buildFolder takes lz4 LAST (after zstd, update, destination); fpkgConversion calls it with all four when lz4 is set. Phone upload in File System is upstream's devicePick ("This device…", fs-device-files input) since 12.4.1; the fork's own button and fsUpload onDone were dropped.
