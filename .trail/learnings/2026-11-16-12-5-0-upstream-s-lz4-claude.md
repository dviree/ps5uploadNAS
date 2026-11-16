---
title: "12.5.0: upstream's LZ4 controls hidden, ampr_lz4 refused"
author: Claude
date: 2026-11-16
branch: main
cost: { minutes: 24, tokens: 429248 }
id: l-6461e922
scope: repo
status: active
src: agent
touches:
  - "client/src/screens/FpkgConvert/ImageOptions.tsx"
  - "engine/crates/ps5upload-engine/src/fpkg_api.rs"
  - "engine/crates/ps5upload-engine/src/api_surface_tests.rs"
---

Decided (upstream 12.5.0 merge): upstream now offers LZ4 packs for folders and images (Lz4Option, lz4Offered, folderLz4Options, extra.lz4, ampr_lz4 in folder and exfat builds). This fork is Zstd only. Rather than deleting upstream's code (merge conflicts every release), ImageOptions.tsx has `const ZSTD_ONLY = true`: Lz4Option renders nothing, lz4Offered is false, and lz4Active is false unless kind is zstd, so no LZ4 options are ever sent. fpkg_api.rs refuses `ampr_lz4` at the top of exfat_build_handler and folder_build_handler (const ZSTD_ONLY message). Upstream's api_surface LZ4 build tests are replaced by lz4_packs_are_refused_in_this_fork; RunCard LZ4 tests check that LZ4 is not offered. The fork's own build_packed LZ4 folder path is gone (folder_build.rs is upstream's). ps5upload-core RAR tests need `cargo build -p ps5upload-unrar` first.
