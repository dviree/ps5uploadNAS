# This fork (dviree/ps5uploadNAS)

ps5upload (phantomptr/ps5upload) with LZ4: Convert Games has My games (which PS5 games in the
library can be LZ4), the converter, and Compatibility (LZ4 reports and the .ffpfsc list). It
runs as the Docker web UI on a NAS.

## GitHub Actions: Docker only

Only the Docker images build by themselves. `docker-engine.yml` publishes
`ghcr.io/dviree/ps5upload-engine-webui` (tags `lz4`, `latest`, `lz4-<commit>`) on every push to
`main`. Every other workflow (`engine-ci.yml`, `publish.yml`, `pages.yml`, `ava1-soak.yml`,
`codeql.yml`, `ios.yml`, `release-tag.yml`, `release-cache.yml`, `ci-runner-retry.yml`) runs only by hand (`workflow_dispatch`): no desktop, Android or release builds on push, tag,
pull request or schedule.

Keep it that way:

- Do not add push, tag, pull_request or schedule triggers to any workflow but
  `docker-engine.yml` and `lz4-upstream-check.yml`, and do not add new workflows that build
  anything else.
- `lz4-upstream-check.yml` runs daily and builds nothing: it checks the LZ4 Compression
  project (theghostonline/PS5-LZ4-Compression on theghostonline.dev, which left GitHub on
  2026-10-17) and opens an `lz4-upstream` issue listing new commits and releases to review and
  port (packing rules in `ampr_pack`, game fixes; dviree/PS5-LZ4-NAS ports them too).
- `lz4-upstream-diff.yml` (by hand, builds nothing) prints the LZ4 Compression project's
  source diff between two release tags into its log, to review a new release from here.
- When merging upstream (`phantomptr/ps5upload` main), check every `on:` block in
  `.github/workflows/` afterwards: an upstream change there must not bring those triggers
  back. Resolve such conflicts by keeping this fork's `workflow_dispatch`-only blocks.
- A commit that only changes workflows or docs can say `[skip ci]` so it does not restart a
  running image build.

## Updating the NAS

The user runs the image on a NAS as the container `ps5upload`, updated by a script on the NAS
that pulls the image and recreates the container (it refuses while an LZ4 build is running).
Whenever a change is pushed to `main`, end the reply by telling the user to run that update
script once the image build is done. Keep the user's network addresses, paths and ids out of
this repository.
