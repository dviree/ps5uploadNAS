---
title: Mounted Zstd folder joins Files and Collection
author: Codex
date: 2026-11-12
branch: main
id: l-0957f43f
scope: repo
status: active
src: agent
touches:
  - scripts/nas-supervisor.py
  - engine/crates/ps5upload-engine/src/collection/store.rs
  - engine/compose.yaml
---

A NAS image cannot read an unmounted sibling of the games folder. Mount the existing host Zstd directory at /zstd (Compose PS5UPLOAD_ZSTD_PATH). nas-supervisor.py appends the existing mount to Files browse roots and Collection extra roots without removing older docker-run configuration. Collection Settings.with_extra_roots merges existing directories on read with saved roots, preserving refresh and delete preferences and avoiding duplicates. configure-zstd-folder.py can add only this bind to the named container in a legacy docker-run update script; it keeps a backup, does not run the updater and refuses an existing different /zstd mapping. Do not hard-code personal host paths in the repository or move game files.
