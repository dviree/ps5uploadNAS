---
title: Payload toolchain falls back to Ubuntu LLVM 20
author: Claude
date: 2026-11-03
branch: main
id: l-20a42687
scope: repo
status: active
replaces: l-2adecfb0
src: agent
touches:
  - ".github/workflows/docker-engine.yml"
  - Makefile
---

Decided: the Docker build's payload step does not depend on apt.llvm.org alone (unreachable from GitHub's runners for hours, Could not resolve host). It tries LLVM 22 from apt.llvm.org and otherwise installs Ubuntu 24.04's own clang-20/llvm-20-dev/lld-20 from noble-updates, as ps5-lz4 builds with Ubuntu's LLVM; the PS5 payload SDK v0.45 supports LLVM 16 to 23 (Makefile). Tried and ruled out: Ubuntu's LLVM 18, whose PS5 driver leaves -nostartfiles unused, so -Werror stops the installer daemon (payload/installer) build; clang-20 and 22 take the flag. LLVM_CONFIG is written to GITHUB_ENV by the toolchain step, so the build step must not set it. Trail does not index workflow YAML or Makefiles: those were read with git.
