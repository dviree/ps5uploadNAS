# SNAPSHOT

Last updated: 2026-11-11. Upstream phantomptr/ps5upload main 51660dbe (VERSION 12.4.7).

The Rust engine and React client retain this fork's PKG output folder and installer.
Convert Games now opens the Zstd NAS converter; Workshop remains alongside it.
There are no LZ4 packing controls, and old ampr_lz4 build requests are rejected.
Workshop defaults to Zstd packs; its tested runtime is ampr-emu-ng 0.3.5 (release
SHA-256 verified). Existing LZ4 readers remain to support existing files and archives.

The current PS5-LZ4-NAS backend is vendored at vendor/ps5-lz4-nas from 2454c640.
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

Trail-code 0.29.0: refreshed local code map (3532 files), with current Zstd-only
learnings in .trail/learnings. The generated map stays in ignored .trail/cache/.
