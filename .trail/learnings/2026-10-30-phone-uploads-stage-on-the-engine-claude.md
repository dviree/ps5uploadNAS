---
title: Phone uploads stage on the engine
author: Claude
date: 2026-10-30
branch: main
id: l-023750ee
scope: repo
status: active
src: agent
touches:
  - client/src/api/pkgUpload.ts
  - client/src/screens/FileSystem/index.tsx
  - client/src/state/fsUpload.ts
---

Files picked on a phone (From this device…) are first POSTed to /api/files/upload and kept in the engine's temp dir (7-day sweep). stageBrowserFile takes onProgress and then uses XMLHttpRequest, since fetch reports no upload progress. Files deletes the staged copies in fsUpload's onDone (only when the run put everything on the console; a stopped run keeps them to resume). Do not delete them in the engine when a transfer job ends: the upload queue can send the same staged file to several consoles.
