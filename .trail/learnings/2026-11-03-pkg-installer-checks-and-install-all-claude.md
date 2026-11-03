---
title: PKG Installer checks and Install all
author: Claude
date: 2026-11-03
branch: main
id: l-f09892ec
scope: repo
status: active
src: agent
touches:
  - client/src/lib/pkgInstallPlan.ts
  - client/src/screens/PkgInstaller/index.tsx
  - client/src/screens/InstallPackage/index.tsx
---

Decided: PKG Installer tells what the PS5 has of a package with ps5upload's own checks, not ps5-lz4's: the header from pkg_metadata_split (content_id, category, app_ver) and the console's pkgInstallPreflight, turned into a relation by installedFromPreflight. ps5-lz4 instead lists /user/app over pkg-receiver and /user/addcont over FTP, which this engine does not need. Install all follows ps5-lz4's pkg_install_plan rules (games, updates, DLC; newest update only; skip DLC and updates whose game is missing unless it is in the batch) in planInstallAll, and hands the list to InstallPackage as state.droppedPaths, which calls its queueStreamPaths (confirm, then queue). A single Install still uses state.droppedPath.
