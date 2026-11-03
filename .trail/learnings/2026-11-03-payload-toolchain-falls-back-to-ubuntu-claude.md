---
title: Payload toolchain falls back to Ubuntu LLVM 18
author: Claude
date: 2026-11-03
branch: main
id: l-2adecfb0
scope: repo
status: active
src: agent
touches:
  - ".github/workflows/docker-engine.yml"
  - Makefile
---

Decided: the Docker build's payload step no longer depends on apt.llvm.org alone. It was unreachable from GitHub's runners for hours (Could not resolve host), three attempts in a row, and nothing could be built. The step tries LLVM 22 from apt.llvm.org and, when that fails, installs Ubuntu 24.04's own clang-18/llvm-18-dev/lld-18, as ps5-lz4's release workflow builds its payload; the PS5 payload SDK v0.45 supports LLVM 16 to 23 (Makefile). LLVM_CONFIG is written to GITHUB_ENV by that step, so the build step must not set it. Trail does not index workflow YAML or Makefiles: those were read with git grep.
