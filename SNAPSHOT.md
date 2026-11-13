# SNAPSHOT

Last updated: 2026-11-13. Upstream phantomptr/ps5upload release v12.4.14 / 1761a866.

The Rust engine and React client retain this fork's PKG output folder and installer.
Convert Games now opens the Zstd NAS converter; Workshop remains alongside it.
There are no LZ4 packing controls, and old ampr_lz4 build requests are rejected.
Workshop defaults to Zstd packs; its tested runtime is ampr-emu-ng 0.3.5 (release
SHA-256 verified). Existing LZ4 readers remain to support existing files and archives.

The current PS5-LZ4-NAS backend is vendored at vendor/ps5-lz4-nas from 48cd52ca.
Local patches restrict packing to Zstd, select level 5 by default and bind HTTP to loopback.
The combined web UI image builds Forge 0.5.5 and ampr-emu-ng v0.3.5/a0dd88a,
including corresponding runtime source and licenses. The engine proxies /api/nas-zstd
and its subpaths to private port 19114 under its existing access guard. Binary downloads
stream through a bounded channel; HTML API/store links retain reverse-proxy prefixes.
A Python supervisor manages the engine, NAS request agent and private UI together.

Mount /ps5 read-only for originals, /zstd writable for outputs; state is in
/data/ps5lz4 on the existing data volume. Never share a state directory with a second
standalone converter worker. engine/compose.yaml documents the mounts.

Docker is the only automatic build workflow. The old LZ4-only watcher has been removed.
Local checks: TypeScript, Vite, Python codec/default/source-retention tests, UI script
syntax. Rust and the combined Docker image require CI; no local Rust/Docker toolchain.

Trail-code 0.29.0: refreshed local code map (3555 files), with current Zstd-only
learnings in .trail/learnings. The generated map stays in ignored .trail/cache/.

2026-11-12: merged upstream 12.4.12 (streaming tar/Zstd upload, audit fixes, media
playback and cross-user save restore fixes). Ported the per-codec NAS queue/report
fix: an old LZ4 report cannot mark a new Zstd request done. The previous combined
Docker build (104e2d41, run 43004788346) completed successfully.

Validation for the update: TypeScript and 91 converter/queue UI tests passed;
five NAS Zstd tests passed, including the cross-codec report regression.

Mounted Zstd library discovery: nas-supervisor.py includes the configured Zstd output
in PS5UPLOAD_BROWSE_ROOTS and PS5UPLOAD_COLLECTION_ROOTS when it exists, retaining
older docker-run deployments' other roots. Collection merges these extra local roots
with saved roots on read, ignoring missing folders and duplicates. Preferences and
game files are not rewritten. Compose accepts PS5UPLOAD_ZSTD_PATH for its /zstd bind.
configure-zstd-folder.py adds that bind to a named docker-run NAS updater once,
without executing it or replacing an existing different /zstd mapping.

2026-11-13: applied the upstream v12.4.12..v12.4.14 delta, preserving the fork
Zstd converter, mounted library roots and Docker-only automatic workflow policy.
Includes larger cheats, download timestamp preservation and the revised Share page.
Trail build/ask was attempted but automatic review blocked its external telemetry;
this session used local source inspection and checks instead.

Validation: TypeScript and Vite production build passed; 53 focused Share/API/queue
tests and 11 Python NAS tests passed. Workflow triggers remain Docker-only.
Rust and full Docker verification run in GitHub Actions.
