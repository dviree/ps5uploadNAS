---
title: "PKG Installer hands packages to Upload & Install"
author: Claude
date: 2026-11-03
branch: main
id: l-1c835917
scope: repo
status: active
src: agent
touches:
  - client/src/screens/PkgInstaller/index.tsx
  - client/src/lib/pkgScan.ts
  - client/src/layout/navItems.ts
---

Decided: More › PKG Installer (/pkg-installer) does not install packages itself. It lists every .pkg/.fpkg under localFs.storageRoots() (the engine's PS5UPLOAD_BROWSE_ROOTS in Docker) with scanPackages, and Install navigates to /send with state.droppedPath, which InstallPackage's location effect turns into Stream & install, as the share sheet and AppShell's drop do. So installs keep upstream's checks and queue. The scan skips game folders (a folder holding sce_sys) and lists a file seen through two mounts (same name and size) once, because the pkg folder sits inside the read-only games mount and is mounted again on its own.
