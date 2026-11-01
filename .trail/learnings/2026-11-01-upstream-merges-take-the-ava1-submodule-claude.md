---
title: "Upstream merges: take the ava1 submodule along"
author: Claude
date: 2026-11-01
branch: main
id: l-2e528613
scope: repo
status: active
src: agent
touches:
  - payload/src/ava1_glue.c
  - ".gitmodules"
---

third_party/ava1 is a submodule. A merge moves its pointer, but the checked-out copy stays at the old commit, so a git add -A after the merge stages the old commit again and silently reverts upstream's bump. The 10.3.0 merge did that: the payload then called ava1_thread_set_start_hook, which only the new ava1 declares, and the Docker image's build-payload job failed. After a merge, compare git ls-tree HEAD third_party/ava1 with upstream/main, or run git submodule update --init before staging. The payload builds only in CI (PS5 SDK), so local tests do not catch it.
