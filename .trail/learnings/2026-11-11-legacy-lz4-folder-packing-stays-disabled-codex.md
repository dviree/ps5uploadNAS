---
title: Legacy LZ4 folder packing stays disabled
author: Codex
date: 2026-11-11
branch: main
id: l-15a36210
scope: repo
status: active
replaces: l-9ffc3631
src: agent
touches:
  - engine/crates/ps5upload-engine/src/fpkg_api.rs
  - client/src/screens/FpkgConvert/ImageOptions.tsx
---

The user only works with Zstd. fpkg_api.rs rejects ampr_lz4 folder and image requests; ImageOptions.tsx offers only Zstd controls. The previous LZ4 build_packed integration is historical code, not a feature to restore. Keep readers needed to open existing files, and never automatically convert or delete old LZ4 folders. New packing goes through the integrated NAS Zstd converter or the native Workshop Zstd path; both use ampr-emu-ng v0.3.5. Phone uploads still use upstream devicePick and fs-device-files, as before.
