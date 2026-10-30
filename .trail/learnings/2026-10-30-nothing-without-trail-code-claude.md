---
title: Nothing without Trail-code
author: Claude
date: 2026-10-30
branch: main
id: l-790ba82b
scope: repo
status: active
src: agent
touches:
  - CLAUDE.md
---

The user's rule: nothing is done in this repo without Trail-code. Every session starts with trail status (trail build if the map is stale) and reads .trail/learnings; code is found and understood with trail ask, trail callers, trail grep, trail skeleton and trail map, not by grepping or opening files blind; every change is checked with trail check before it is pushed; what a session worked out is saved with trail note and committed with the change. Why: the user wants every session to work from the code map and the team's learnings.
