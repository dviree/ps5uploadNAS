---
title: "Merges: run submodule update before git add -u"
author: Claude
date: 2026-11-23
branch: main
cost: { minutes: 30, tokens: 1225950 }
id: l-4c272f8d
scope: repo
status: active
src: agent
touches:
  - "third_party/ava1"
  - ".gitmodules"
---

Tried and ruled out (seen 2026-11-21, fixed 2026-11-23): `git add -u` after a merge stages a submodule at whatever is checked out. When third_party/ava1 was not updated first, the merge commit took an old ava1 (80fe957) over upstream's pointer, and the next upstream merge reported a submodule conflict. After every upstream merge, before `git add -u`, run `git submodule update --init third_party/ava1 third_party/lwip`, then check `git ls-files -s third_party/ava1` against `git ls-tree upstream/main third_party/ava1`. On a submodule conflict, set upstream's pointer with `git update-index --cacheinfo 160000,<sha>,third_party/ava1`.
