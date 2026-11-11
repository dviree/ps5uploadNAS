# This fork

The user works only with Zstd. Keep LZ4 packing controls unavailable; existing LZ4 readers
may remain for opening archives and existing games. Do not convert or delete existing
LZ4 game folders automatically. Preserve original games during every conversion.

## Memory files: read first, update when a task is done

- `SNAPSHOT.md`: a blueprint of the current architecture (upstream, the fork's additions, CI
  and Docker, local build quirks). Read it at the start of a session.
- `BACKLOG.md`: found bugs, stubs and ideas, with a `>RESUME HERE` block naming the last thing
  done and the next step. Read it at the start and pick up from `>RESUME HERE`.
- `CLAUDE.md` (this file): the rules every turn. Tune it when the user sets a new rule.
- When a task is complete, update all three in the same commit as the change: the snapshot if
  the shape changed, the backlog's `>RESUME HERE` always, and this file for new rules. Keep the
  user's network addresses, paths and ids out of them.
- Reply in Swedish when the user writes Swedish. End every reply with a "🌱 Trail: …" line
  saying which trail commands ran, and say plainly when something was read without Trail
  (workflow YAML, scripts and upstream's version via git are not in Trail's map).

## GitHub Actions: Docker only

Only the Docker images build by themselves. `docker-engine.yml` publishes
`ghcr.io/dviree/ps5upload-engine-webui` (tags `lz4`, `latest`, `lz4-<commit>`) on every push to
`main`. Every other workflow (`engine-ci.yml`, `publish.yml`, `pages.yml`, `ava1-soak.yml`,
`codeql.yml`, `ios.yml`, `release-tag.yml`, `release-cache.yml`, `ci-runner-retry.yml`, `publish-retry.yml`, `flake-hunter.yml`) runs only by hand (`workflow_dispatch`): no desktop, Android or release builds on push, tag,
pull request or schedule.

Keep it that way:

- Do not add push, tag, pull_request or schedule triggers to any workflow but
  `docker-engine.yml`, and do not add new workflows that build
  anything else.
- Follow quer3q/ps5-dump-forge and quer3q/ampr-emu-ng for Zstd updates.
- When merging upstream (`phantomptr/ps5upload` main), check every `on:` block in
  `.github/workflows/` afterwards: an upstream change there must not bring those triggers
  back. Resolve such conflicts by keeping this fork's `workflow_dispatch`-only blocks.
- A commit that only changes workflows or docs can say `[skip ci]` so it does not restart a
  running image build.

## Updating the NAS

The user runs the image on a NAS as the container `ps5upload`, updated by a script on the NAS
that pulls the image and recreates the container (it refuses while a conversion is running).
Whenever a change is pushed to `main`, end the reply by telling the user to run that update
script once the image build is done. Keep the user's network addresses, paths and ids out of
this repository.

## Trail-code

The user wants Trail-code (`@trailhq/trail-code`, the `trail` command) used in every session.
Install it if missing (`npm install -g @trailhq/trail-code`), build the code map (`trail build`;
`.trail/cache/` is a local cache (Trail 0.29.0)) and find code with `trail ask`, `trail grep`, `trail callers`,
`trail skeleton` and `trail map` before grepping or opening files. Read the learnings in
`.trail/learnings/` first, check a change with `trail check`, and save what a session worked
out with `trail note`, committed with the change it came from.
