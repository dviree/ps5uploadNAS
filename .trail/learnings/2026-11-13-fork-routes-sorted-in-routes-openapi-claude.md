---
title: "Fork routes: sorted in ROUTES, openapi from apidoc"
author: Claude
date: 2026-11-13
branch: main
id: l-0554669b
scope: repo
status: active
src: agent
touches:
  - "engine/crates/ps5upload-engine/src/mcp/catalog_routes.rs"
  - "engine/crates/ps5upload-engine/api/openapi.json"
---

Decided: a route the fork mounts (/api/nas-zstd, its {*path}) goes into mcp/catalog_routes.rs ROUTES at its sorted place (by path, then method); the_list_is_sorted_without_repeats fails otherwise. api/openapi.json is regenerated with `cargo run -p ps5upload-apidoc` in engine/, never edited by hand (a hand-written entry differs from the generator's and the file's escapes change). Tried and ruled out as merge blockers: join_net::rtc::track_bench, share::tests and join::tests::pad_internet are timing tests that can fail under a full parallel run in the cloud sandbox and pass alone.
