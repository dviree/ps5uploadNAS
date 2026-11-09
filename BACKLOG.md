# BACKLOG

Found bugs, stubs and ideas. Update it when a task is done or something new turns up.

## >RESUME HERE

- Last done (2026-11-09):
  - Merged upstream 12.4.1, with conflicts resolved:
    - `folder_build::build_packed` replaces the fork's `reopen: Option` change to upstream's
      folder build.
    - `fpkg_api.rs` keeps upstream's zstd, update and destination steps next to `ampr_lz4`.
    - Phone upload now uses upstream's device pick.
  - Engine, fpkg and core tests, vitest, tsc and the e2e tests listed in the commit pass.
- The Docker build of the merge (run 43) is green: images `lz4`, `latest` and `lz4-2281602`.
- Next: nothing pending. On "Uppdatera", merge the latest upstream and check the LZ4 original.

## Open

- Delete the stale remote branch `codex/files-iphone-upload` (Trail flagged it). Ask the user
  first.
- dviree/PS5-LZ4-NAS: Trail hooks are not automatic there (`trail init` was blocked here). The
  user can run it in a Codespace.
- An LZ4 game folder cannot be written to a saved server: `build_packed` writes locally only.
  It could follow upstream's `server_out::write_folder` if wanted.
- An optional amd64-only Docker build (faster) was offered and not decided.

## Ideas

- A `/saves` mount for save backups was suggested to the user. Not confirmed.
- My games could show the zstd packs state (upstream 12.x) next to the LZ4 state.

## Done (recent)

- 12.4.1 merge: the fork's phone-upload button was dropped for upstream's identical feature.
- PKG Installer with installed status and Install all.
- Packages go to the pkg folder. The DLC folder is mounted under its own name.
