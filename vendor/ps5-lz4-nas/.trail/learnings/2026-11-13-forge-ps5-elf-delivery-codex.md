---
title: Forge PS5 ELF delivery
author: Codex
date: 2026-11-13
branch: main
id: l-84374635
scope: repo
status: active
src: agent
touches:
  - BACKLOG.md
  - CLAUDE.md
  - SNAPSHOT.md
  - nas-lz4/ps5lz4.py
  - nas-lz4/ui.html
---

nas-lz4/ps5lz4.py forge_ps5_install sends pinned checksum-verified quer3q PS5 ELF over FTP to Payload Manager and starts it; falls back to elfldr 9021/9020. Console runtime differs from NAS runtime.
