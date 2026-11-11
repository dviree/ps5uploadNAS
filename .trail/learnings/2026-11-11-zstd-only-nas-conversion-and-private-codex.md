---
title: Zstd-only NAS conversion and private gateway
author: Codex
date: 2026-11-11
branch: main
id: l-aacc39f5
scope: repo
status: active
replaces: l-306e5d29
src: agent
touches:
  - client/src/screens/Convert/index.tsx
  - engine/crates/ps5upload-engine/src/nas_zstd.rs
  - engine/Dockerfile.webui
---

The user only works with Zstd. Convert Games opens the integrated NAS Zstd UI; Workshop remains available. Keep LZ4 packing controls unavailable and reject legacy ampr_lz4 requests. Existing LZ4 readers may remain for opening files, but never convert or delete old LZ4 folders automatically. The vendored NAS converter uses Forge 0.5.5, Zstd level 5 by default, and ampr-emu-ng v0.3.5. The engine proxies /api/nas-zstd to loopback port 19114 under its existing IP guard, so no extra public port is required. Originals mount at /ps5:ro, outputs at /zstd, state at /data/ps5lz4; never share that state with another worker. Binary downloads stream through a bounded channel. Large uploads use the main Files screen because the gateway keeps the engine default request-body limit. This supersedes the older My games/Convert/Compatibility tab description; keep the lz4 image tags for existing NAS update scripts.
