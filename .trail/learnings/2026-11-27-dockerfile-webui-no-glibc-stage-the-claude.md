---
title: "Dockerfile.webui: no glibc stage, the final image is Debian"
author: Claude
date: 2026-11-27
branch: main
cost: { minutes: 1, tokens: 1631 }
id: l-13849ea3
scope: repo
status: active
src: agent
touches:
  - "engine/Dockerfile.webui"
---

Tried and ruled out (upstream 12.6.42 merge): keep upstream's `COPY --from=glibc /rootfs-glibc/ /` out of engine/Dockerfile.webui, because this fork's final stage is FROM nas-runtime (python:3.12-slim-bookworm), where /lib is a symlink: the COPY fails with "cannot copy to non-directory ... /lib" and both webui builds break (docker-engine run 61). Upstream needs it only because its images end in scratch; the Debian base already has glibc 2.36 and ca-certificates for Go live's downloaded ffmpeg (ffmpeg_tool.rs). engine/Dockerfile, the plain engine image, keeps upstream's glibc stage.
