---
title: Upstream merges re-add workflow triggers
author: Claude
date: 2026-10-31
branch: main
id: l-35c22d54
scope: repo
status: active
src: agent
touches:
  - ".github/workflows/pages.yml"
  - client/src/screens/Upload/BrowserFilePicker.tsx
---

Upstream keeps adding automatic triggers to workflows this fork runs by hand: 10.0.x gave pages.yml push, workflow_run and schedule again (it would deploy the website from this fork). Merges resolve to the fork's workflow_dispatch-only on: block. BrowserFilePicker carries the fork's upload percentage beside upstream's archive check, which 10.0.x widened to split archives .r00 to .y99; keep both when it conflicts.
