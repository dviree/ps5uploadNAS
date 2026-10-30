---
title: Packages Convert makes go to the pkg folder
author: Claude
date: 2026-10-30
branch: main
id: l-c628c845
scope: repo
status: active
src: agent
touches:
  - client/src/state/convertPrefs.ts
  - client/src/screens/FpkgConvert/index.tsx
---

A .pkg Convert makes goes to convertPrefs.pkgDir (default /ps5pkg in the web UI, mounted from the NAS's PS5 pkg folder), images and game folders to outputDir, because the user wants converted packages in their pkg share. FpkgConvert picks the folder through outputDir/setOutputDir derived from make === pkg; an empty pkgDir falls back to outputDir. Without the mount the engine cannot create /ps5pkg (non-root user) and the build fails, which is intended: nothing is written inside the container.
