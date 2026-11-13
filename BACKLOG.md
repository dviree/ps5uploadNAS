# BACKLOG

## >RESUME HERE

- 2026-11-13: full PS5-LZ4-NAS 6e580691 source import, runtime 0a5670a,
  Zstd-only compression dialog and screenshot-led NAS README. Keep the combined
  web UI's packing restricted to Zstd; imported receiver source is not a new
  payload deployment. Docker CI gates the web UI on NAS regression checks.
  Verify the Docker build, then run the existing NAS updater. Console tests pending.

- 2026-11-13: updated to upstream stable v12.4.14 (1761a866), retaining Zstd-only
  conversion and mounted folder discovery. Verify the new Docker image build
  before running the existing NAS updater. No game files are changed by this update.

- 2026-11-12: added mounted Zstd output to Files and Collection automatically,
  retaining saved roots/settings. Compose accepts PS5UPLOAD_ZSTD_PATH; the new
  configure-zstd-folder.py can add /zstd to existing docker-run update scripts.
  The NAS must recreate the container with the existing host folder mounted.

- 2026-11-12: merged upstream 900feb68 and release version sync e4826074 / 12.4.12; ported the per-codec Zstd
  queue/report fix from PS5-LZ4-NAS 48cd52ca. The previous combined Docker build
  is green. Local TypeScript, 91 UI/queue tests and 5 NAS Zstd tests pass. Keep new packing restricted to Zstd; preserve original and old packed games.

- 2026-11-11: merged upstream main 51660dbe (VERSION 12.4.7).
- User will only use Zstd: removed LZ4 packing controls, rejected legacy packing requests,
  integrated the current NAS converter with Forge 0.5.5 / NG v0.3.5, and updated the native
  converter's tested runtime to v0.3.5 with the release digest.
- Verify the combined Docker build before updating a NAS container. Add /ps5:ro and /zstd
  bind mounts; use the existing /data volume for separate converter state.
- Trail-code 0.29.0 installed after explicit user authorization. Rebuilt the code map and saved the Zstd-only policy in .trail/learnings; the earlier installation block is resolved.
- Rust compilation and Docker integration need CI; these tools are absent locally.

## Open

- Validate conversion and sending with a real game/console after the image builds.
- The NAS gateway accepts normal small JSON actions; use the main Files screen for large
  uploads (the converter gateway retains the engine's default request-body limit).
