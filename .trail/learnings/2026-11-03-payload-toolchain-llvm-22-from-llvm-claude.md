---
title: "Payload toolchain: LLVM 22 from LLVM's GitHub release when apt.llvm.org is down"
author: Claude
date: 2026-11-03
branch: main
id: l-33e46f11
scope: repo
status: active
replaces: l-20a42687
src: agent
touches:
  - ".github/workflows/docker-engine.yml"
---

Decided: the Docker build's payload needs LLVM 22. When apt.llvm.org cannot be reached from GitHub's runners (it was down for hours), the toolchain step downloads LLVM 22's Linux-X64 release from llvm/llvm-project on GitHub with gh (GH_TOKEN set on the step) into /opt/llvm-22 and writes LLVM_CONFIG to GITHUB_ENV. Tried and ruled out: Ubuntu 24.04's LLVM 18 (its PS5 driver leaves -nostartfiles unused: -Werror stops payload/installer) and LLVM 20 (its headers lack _mm256_aesenc_epi128, which 7-Zip's AesOpt.c in payload/extractor calls). ps5-lz4 builds with Ubuntu's LLVM 18 because its payload has neither. Trail does not index workflow YAML or Makefiles: those were read with git.
