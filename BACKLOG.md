# BACKLOG

## >RESUME HERE

- 2026-11-20: merged upstream 4e813f5b (after 12.6.13: helper start fixes, ShadowMount+
  uninstall, AVA1 1.0.11, links without byte ranges, save a link to a PS5 folder, RAR room
  check, full review fixes).
  - One conflict: fpkgConversion.test.ts, upstream's swap test added before the fork's
    resume tests.
  - Workflow jobs and triggers are unchanged.
  Checks: engine 2192, core 891, fpkg 390, 6732 vitest tests, tsc, i18n and the NAS checks
  pass.
- Still waiting for the owner's OK: Forge v0.5.6 and ampr-emu-ng v0.4.1 for the NAS converter.
- Next: verify the Docker build (publishing jobs ran), then run the NAS updater.

- 2026-11-19: merged PS5Upload 12.6.9 plus 72cce211 (Remote Play on Linux, full audit fixes,
  speed limit on Windows, frame rate on firmware 4.x, the Files move line on a phone).
  - One conflict: docker-engine.yml's toolchain step keeps the fork's LLVM 22 fallback, not
    upstream's ci-apt-latest.sh. Jobs and triggers are unchanged.
  Checks: engine 2156, core 882, fpkg 383, 6683 vitest tests, tsc, i18n and the NAS checks
  pass.
- Still waiting for the owner's OK: Forge v0.5.6 and ampr-emu-ng v0.4.1 for the NAS converter.
- The Docker build (run 57) is green and published (merge and merge-webui ran). Next: the user
  runs the NAS updater.

- 2026-11-18: merged PS5Upload 12.6.7 (82978cdc; 12.6.3-12.6.7: Replace when a game is already
  on the PS5, trophies after offline activation, drive backups, higher bitrate, Send a package
  as a file, Docker prune). README stays the fork's.
  - Upstream's docker-engine.yml no longer publishes on a branch push (resolve off) and adds
    schedule/release triggers. Kept the fork's resolve (`!= pull_request`), PR-only verify and
    push/PR/dispatch triggers.
  - Removed engine-ci.yml's new nightly schedule.
  Checks: engine 2143, core 879, fpkg 383, 6649 vitest tests, tsc, i18n and the NAS checks
  pass.
- Still waiting for the owner's OK: Forge v0.5.6 (pinned 0.5.5) and ampr-emu-ng v0.4.1 (pinned
  920e917 / 0.4.0) in the NAS converter.
- The Docker build (run 56) is green and published: resolve, build, build-webui, merge and
  merge-webui all ran. Next: the user runs the NAS updater.

- 2026-11-17: merged PS5Upload 12.6.2 (0b7c3689; 12.5.1-12.6.2: zstd for every game, Convert
  on the PS5, Kraken Mount, save sync, copy .pkg as a file, payloads from you, every disk in
  the file browser). Four conflicts:
  - README stays the fork's.
  - ImageOptions takes upstream's emulator line without the Lz4Option.
  - api_surface_tests keeps lz4_packs_are_refused_in_this_fork; upstream's LZ4 build tests
    stay out.
  - RunCard tests keep the fork's LZ4-not-offered checks, and #828's LZ4 lines now check
    that LZ4 can't be picked.
  Checks: engine 2108, core 882, fpkg 383, 6559 vitest tests, tsc, eslint and the NAS checks
  pass.
- Open, needs the owner's OK (quer3q code is reviewed first):
  - PS5 Dump Forge v0.5.6 is out; the NAS converter pins 0.5.5 (install-forge.py).
  - ampr-emu-ng v0.4.1 is out; the NAS converter pins 920e917 (0.4.0).
- The Docker build (run 55) is green. Next: the user runs the NAS updater.

- 2026-11-16: merged PS5Upload 12.5.0 (449d3236; 12.4.19-12.4.23 too: Convert gets PS5 Dump
  Forge's features, Convert on the PS5 in Minion, in-place image editing, remove PS5Upload
  from a PS5, zstd runtime 0.4.1 in the engine). Resolved 23 conflicts:
  - Version files, CHANGELOG and lockfiles take upstream's.
  - README stays the fork's.
  - docker-engine.yml keeps the fork's LLVM fallback and adds upstream's converter build
    (CONVERT_REQUIRED).
  - folder_build.rs and fpkg_api.rs take upstream's, plus the fork's ampr_lz4 refusal
    (ZSTD_ONLY) on /api/exfat/build and /api/folder/build. The fork's dead LZ4 folder path
    (build_packed) is gone.
  - Client: upstream's new LZ4 controls are hidden and inert (ZSTD_ONLY in ImageOptions:
    Lz4Option renders nothing, lz4Offered/lz4Active are false for LZ4). Folder runs keep the
    fork's thenSend and resume.
  - Tests that expected LZ4 builds now check the refusal.
  Checks: engine 2062, fpkg 371 and core 891 Rust tests (core's RAR tests need
  `cargo build -p ps5upload-unrar` first; track_bench is timing-only), 6464 vitest tests,
  tsc, eslint, i18n, and the NAS Python/Node checks pass.
- Open: the NAS converter image still pins ampr-emu-ng 920e917 (0.4.0). quer3q released v0.4.1
  (upstream ps5upload now uses it for Workshop). Move the pin only with the owner's OK.
- The Docker build (run 54, converter included) is green. Next: the user runs the NAS
  updater.

- 2026-11-14: updated to PS5Upload 12.4.18 (c037a6ee): router diagnostics, fixed
  Play Together UDP port and persistent offline Tailscale pause. Corrected the
  estimate fixture that broke verify-nas and added codec-independent rejection
  coverage for PKG and packed inputs. Keep Zstd-only level 5, original retention
  and mounted library discovery. Verify Docker CI before the existing NAS updater;
  console and NAS deployment verification remain pending. Local checks: 308 focused
  frontend tests, TypeScript, Vite, 21-language coverage, 11 NAS tests and 24
  imported NAS tests passed (10 tool/binary-dependent checks skipped); both
  imported Node policy suites passed. Rust/Docker verification runs in CI.

- 2026-11-13: merged PS5Upload v12.4.17 (583cb971; includes v12.4.16 audit fixes,
  IPv6 Play Together and search scoped to the open folder). Refreshed the full NAS
  tools source from afbf5c38: ampr-emu-ng v0.4.0 (920e917), PS5 game PKG input,
  on-console Forge delivery and prefilled GitHub game reports. The combined image
  retains loopback-only converter HTTP, Zstd-only packing, level 5 and mounted
  library discovery. Synced version files to 12.4.17. Validation: 6406 frontend
  tests, TypeScript and production build; 11 NAS integration tests and 31 imported
  NAS tests pass, including real Forge folder/PKG round trips with the verified
  NG 0.4.0 release (two optional codec/MkPFS checks skipped). Rust and Docker builds
  need CI; real-console verification remains pending.

- 2026-11-13: merged upstream v12.4.15 (aba0ca38: Play Together PS block, Share fixes,
  dependency updates). README keeps the fork's NAS text; Share takes upstream's layout.
  Fixed the MCP route list order for /api/nas-zstd and regenerated api/openapi.json with
  ps5upload-apidoc. Engine, fpkg and core tests pass (three timing tests only fail under
  load), as do 6399 vitest tests, tsc, i18n and 33 NAS Python tests. The Zstd upstreams
  have nothing new (Forge v0.5.5, ampr-emu-ng 0a5670a). The Docker build (run 50) is green;
  next is the user running the NAS updater.

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
