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

The user's NAS runs the image as the container `ps5upload`. Whenever a change
is pushed to `main`, end the reply with the update command: once the image build is done,
`sudo /path/to/update.sh` on the NAS (it refuses while an LZ4 build is running,
an `*.lz4spool` in `/path/to/ps5-lz4`). The script holds the full `docker run` (user
1000:100, host network, `PS5_ADDR=192.168.1.50`,
`PS5UPLOAD_ALLOW_IP=192.168.1.0/24,100.64.0.1`, mounts `/games` (roms/ps5, ro), `/pkgs`
(roms/ps4, ro), `/lz4` (ps5-lz4), `/downloads` (`/path/to/downloads`, ro), `/data`,
`/tmp`; browse roots `/games,/pkgs,/lz4,/downloads`); when a setting changes, give the user the
updated script too.
