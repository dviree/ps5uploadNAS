---
title: "Upstream merges: docker-engine resolve must run on a push to main"
author: Claude
date: 2026-11-18
branch: main
cost: { minutes: 25, tokens: 926741 }
id: l-04d4d6a0
scope: repo
status: active
src: agent
touches:
  - ".github/workflows/docker-engine.yml"
  - ".github/workflows/engine-ci.yml"
---

Tried and ruled out (upstream 12.6.7 merge): upstream's docker-engine.yml now publishes only on a tag push, a dispatch with a tag or a release (its `resolve` job is off for a branch push, and every publishing job needs it), and runs verify on every push to main and nightly. Taking that would make a push to this fork's main build nothing. Keep the fork's `resolve` condition `github.event_name != 'pull_request'`, verify on pull requests only, `push: branches: [main]` once (no duplicate key), and no `schedule:` or `release:` trigger (engine-ci.yml got a nightly `schedule:` too: remove it). Check every job's `if:`/`needs:` against the previous main after a merge.
