# BACKLOG

Found bugs, stubs and ideas. Update it when a task is done or something new turns up.

## >RESUME HERE

- Last done (2026-11-10):
  - Merged upstream 12.4.2 (helper rest detection, helper at boot, payload updates, the
    Workshop output folder; Hearbridge removed upstream) and the CodeQL nonce fix, with no
    conflicts.
  - The LZ4 original has nothing new since 2026-10-28 (issues #4, #5 and #7 were already
    reviewed).
- Next: check that the Docker build of the merge is green, then tell the user to run the NAS
  update script.
- If the cloud sandbox's disk fills, delete `engine/target/debug/incremental` and
  `output/playwright`.

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
