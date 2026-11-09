# SNAPSHOT: what this fork is, as built

A blueprint of the current architecture: what is upstream and what this fork adds. Update it
when a task changes the shape of the code (new module, route, screen, workflow step).
Last updated: 2026-11-09, upstream 12.4.1 merged.

## Upstream (phantomptr/ps5upload), in short

- `engine/`: Rust workspace. `ps5upload-engine` is the axum HTTP engine (`src/lib.rs` mounts
  every route; `mcp/catalog_routes.rs` and `api/openapi.json` must list them all, a test checks).
  `ps5upload-fpkg` builds and reads game images and packs (`ampr_pack/` LZ4 asset packs,
  `exfat`, `source` trees). `ps5upload-core` is the PS5 side (payload protocol, transfers).
  `ps5upload-tailnet` (12.x) builds C from `third_party/{bearssl,lwip}` plus ava1's Monocypher.
- `client/`: React + TypeScript (vite, zustand, vitest, Playwright e2e). The same UI runs in
  Tauri (desktop) and as the web UI the engine serves. Tauri commands are mirrored for the
  browser in `client/src/lib/browserInvoke.ts` (`postJson(path, body, long)`).
- `payload/`: the PS5 payload, built with LLVM 22 (clang/lld) in the Docker workflow.
- Submodules: `third_party/ava1` (follow upstream's pointer), `third_party/bearssl`
  (bearssl.org, blocked from the cloud sandbox), `third_party/lwip`.

## This fork's additions

### Convert Games (LZ4): My games, Convert, Compatibility
- Engine:
  - `src/lz4_api.rs`: `POST /api/lz4/status` (can a game be LZ4, is it packed, does it need
    a runtime; cached by mtime) and `GET /api/lz4/building` (the games converting now,
    through `building_start` guards held by the folder build job).
  - `src/lz4_compat.rs`: `GET /api/lz4/compat` aggregates the LZ4 Compression project's
    compatibility reports. `GET /api/lz4/ffpfsc` gives the .ffpfsc list.
- LZ4 game folder build (`fpkg_api.rs` folder build, `ampr_lz4` in the request):
  - `ampr_pack::image::prepare` packs into a spool beside the target.
  - `folder_build::build_packed` writes the overlay as `<name>-lz4` and reads it back
    against the overlay.
  - `lz4_ready` checks readiness first, and with `install_runtime` installs the release
    ampr runtime.
  - A Glacier game is refused (`image.rs` `is_glacier`).
  - LZ4 folders are local only (a server destination is refused).
- Image builds use upstream's own LZ4 packs path (`check_packs`, `install_runtime`).
- Client:
  - `client/src/screens/Convert/` holds My games, Convert and Compatibility.
  - `useFpkgConversion.buildFolder(source, outputDir, keepBoth, own, lz4, thenSend)` calls
    `fpkg.buildFolder(..., keepBoth, zstd, update, destination, lz4)`, with lz4 last.
  - "Convert to .ffpfsc" calls `buildImage(path, out, true, "exfat", thenUpload)`.

### Package output and PKG Installer
- `state/convertPrefs`: `pkgDir` (web UI default `/ps5pkg`), `lz4Dir` (`/lz4`), `outputPlace`.
  In FpkgConvert, `outFor` sends a package to `pkgDir`.
- More › PKG Installer: `screens/PkgInstaller/index.tsx` with `lib/pkgScan.ts` and
  `lib/pkgInstallPlan.ts`.
  - It reads metadata with `pkg_metadata_split` and checks what is installed with
    `pkgInstallPreflight`.
  - Install, or Install all, hands off to Send (`navigate("/send", {state: {droppedPath(s)}})`).

### Phone uploads
- Since 12.4.1, File System uses upstream's own "This device…" (`lib/devicePick`,
  `stagePicksWithTask`). The fork's own button was dropped.
- The staged copies are released by `lib/browserStaging`.
- `e2e/files-device-upload.spec.ts` covers it through the `fs-device-files` input.

### Misc
- `/api/version` includes the fork's `ps5_addr` (`lib/defaultConsole.ts`) next to upstream's
  `default_console`.

## CI and Docker

- `.github/workflows/docker-engine.yml` (push to main) builds
  `ghcr.io/dviree/ps5upload-engine-webui` with tags `lz4`, `latest` and `lz4-<commit>`.
  - The payload step installs LLVM 22 through `scripts/install-llvm-apt.sh`. When that fails,
    it falls back to the llvm/llvm-project GitHub release, unpacked to `/opt/llvm-22`.
  - LLVM 18 and LLVM 20 do not build the payload.
- `lz4-upstream-check.yml` runs daily and opens `lz4-upstream` issues.
- Every other workflow is `workflow_dispatch` only (see CLAUDE.md).

## Local builds in the cloud sandbox

- BearSSL cannot be cloned here. For a local compile only, copy the sources from the
  crates.io `bearssl-sys` crate (`lib/BearSSL`) into `third_party/bearssl/`. Never commit it.
- Run `git submodule update --init third_party/ava1 third_party/lwip` before building. A
  stale ava1 checkout rewrites `engine/Cargo.lock` (ava1-chaos version).
- If cargo says "failed to select a version … locked to", delete
  `~/.cargo/registry/index/*/.cache`.
