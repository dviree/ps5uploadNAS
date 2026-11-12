---
title: Zstd queue checks the requested codec
author: Codex
date: 2026-11-12
branch: main
id: l-23668a26
scope: repo
status: active
src: agent
touches:
  - vendor/ps5-lz4-nas/nas-lz4/ps5lz4.py
  - tests/test_nas_zstd.py
---

result_for must accept a completed report only for the Entry requested pack_codec. Set pack_codec before selecting cmd_start/cmd_run --all targets and before process_one checks completion. Otherwise a saved LZ4 report makes a fresh Zstd conversion disappear from the queue as already done. Ported from PS5-LZ4-NAS 48cd52ca with Zstd-only defaults retained; a regression test covers queue selection, worker execution and the separate Zstd destination. Preserve originals and never overwrite an existing pack.
