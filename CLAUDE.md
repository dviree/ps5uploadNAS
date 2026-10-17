# This fork (dviree/ps5uploadNAS)

ps5upload (phantomptr/ps5upload) with LZ4: Convert Games has My games (which PS5 games in the
library can be LZ4), the converter, and Compatibility (LZ4 reports and the .ffpfsc list). It
runs as the Docker web UI on a NAS.

## GitHub Actions: Docker only

Only the Docker images build by themselves. `docker-engine.yml` publishes
`ghcr.io/dviree/ps5upload-engine-webui` (tags `lz4`, `latest`, `lz4-<commit>`) on every push to
`main`. Every other workflow (`engine-ci.yml`, `publish.yml`, `pages.yml`, `ava1-soak.yml`)
runs only by hand (`workflow_dispatch`): no desktop, Android or release builds on push, tag,
pull request or schedule.

Keep it that way:

- Do not add push, tag, pull_request or schedule triggers to any workflow but
  `docker-engine.yml`, and do not add new workflows that build anything else.
- When merging upstream (`phantomptr/ps5upload` main), check every `on:` block in
  `.github/workflows/` afterwards: an upstream change there must not bring those triggers
  back. Resolve such conflicts by keeping this fork's `workflow_dispatch`-only blocks.
- A commit that only changes workflows or docs can say `[skip ci]` so it does not restart a
  running image build.
