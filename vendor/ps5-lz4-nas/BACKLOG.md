# Backlog

Bugs found, stubs, ideas and work that spans sessions. Update it when a task
ends (see `CLAUDE.md`). No real game names (Title IDs only), no personal data.

## >RESUME HERE

Done 2026-11-13: Remote page can copy the checksum-verified quer3q Forge
v0.5.5 PS5 ELF to Payload Manager and start it there (ELF loader fallback),
then link to the console's port 8095 Pack page. Console runs Forge's bundled
runtime, not the newer NAS runtime. Needs a hardware test on the PS5.

Done 2026-11-12: ampr-emu-ng pinned to upstream `0a5670a` (after v0.3.5),
including PR #51 for PPSA21704 / issue #37. One console tested the PR's debug
build; the newer pinned build still needs a PS5 play test. Forge stays v0.5.5.

Done 2026-11-11: a previously packed LZ4 copy no longer makes the Zstd queue
skip that source as already done. Per-codec queue selection and worker checks
now use the requested format; existing packs are not overwritten.

Done 2026-11-11: the NAS update wrapper now adds the missing Zstd output bind
on older installs, exports the Compose override on later updates, and recreates
the containers even when the image is already current. The NAS still needs the
new wrapper installed once; existing output folders are left in place.

Done 2026-11-10 (owner): everything from theghostonline removed; only quer3q's
Forge and ampr-emu-ng remain. Open after it: rewrite the stale APR-EMU sections of nas-lz4/README.md; the
verdict words "can be LZ4 / LZ4 / not LZ4" and `ampr_status_folder` are old
names (kept: the page filters use them). Rest mode after a send: owner said
leave it (2026-11-13); the PS5's own power-saving setting does it.

Also waiting on the owner: the PPSA26344 folder went missing. The code can't
remove an original (only `delete-original` with `DELETE_ORIGINALS=yes`); the
owner is to run the log commands from chat (logs, `state/requests`, Recent
actions; PS5: ShadowMount *Hide* renames to `.name`). Last finished
(2026-11-07): Compress all and Repair buttons removed from the page (CLI
`lz4 --fix` / `apr --fix` stay); quer3q/James pins up to date.

## Needs the owner

- Enable *Allow GitHub Actions to create and approve pull requests* (Settings ›
  Actions › General); until then the quer3q follower pushes a branch only.
- Test on the NAS/PS5 (the session can't reach the NAS): Compress dialog and
  estimates, TOML chooser, sub-tabs, LZ4 NG with theghostonline's packer +
  ampr-emu-ng `cbdafd8`, Start check (ShadowMountPlus fields `runtime_path`,
  `fakelib_mode` are taken from exFAT2AMPR's code, unverified); LZ4 NG/Zstd games
  on ampr-emu-ng v0.3.4 (upstream kernel AIO, save-load hang fix, 192 MiB pool:
  check save loading and memory-tight games).
- quer3q reports: the fetch (GitHub REST, no token) and the pre-filled issue form
  are built from the form's file and fixtures; the session's proxy blocks the
  API, so check on the NAS that counts appear and the link fills the form.
- Without the old loose rules Forge packs `cache_ps5/pgc_*_dummy_file`,
  `playgo.pgm` and the PPSA26344 boot files (seen in a local Zstd pack). quer3q
  says ampr-emu-ng serves such reads; check PPSA26344 and PPSA34547 on the PS5.
- Check on the NAS that Send to GitHub opens the issue (labels from a
  non-collaborator are dropped by GitHub; the body still parses back).
- Old git tags still point to history before the personal-data rewrite (owner
  has the retag commands).
- PR #2 (Trail-Code + Claude Code in Codespaces) is open, not merged.

## Known issues

- A game's report (`state/reports/<id>.json`) describes only its last pack; the
  page now uses `copies` per folder and `requires_ng` checks the report's
  `output`, but other report readers (e.g. community report level) still see
  the last pack only.
- With Repair gone from the page, a wrong APR-EMU is fixed by repacking or
  `./lz4-ps5.sh apr --fix`.
- GitHub runs scheduled workflows rarely for this repo (~every 6 h).
- `trail note` can't save learnings: `.trail/` needs `trail init` (blocked as
  self-modification in an earlier session).

## Ideas

- Compress dialog: a real Zstd estimate per level (now zstd -5 only).
- Copies tab: show the exFAT image of a copy and its transfer state on the PS5.
- `.ffpfsc` sources: owner to decide whether only folder/exFAT may be packed.

## Done recently (newest first)

- Zstd only (owner): LZ4 NG removed from the format bar, the Compress dialog,
  the queue, run_request and the CLI (`--codec zstd`, default level 5 or
  PS5LZ4_ZSTD_LEVEL). Existing LZ4 copies stay and still get runtime upgrades.
- PS5 game packages (.pkg, fake PKG, base game only) in the library are games:
  Forge packs them straight to LZ4 NG or Zstd (no unpacking); updates, DLC, apps
  and PS4 packages stay on the PKG tabs. Encrypted store PKGs can't be read.
- `lz4-ps5.sh update` now runs `apr --fix`: every LZ4 NG and Zstd copy with an
  older ampr-emu-ng build gets the image's build (cache key includes the image's
  runtime; any non-APR-EMU runtime counts as NG). PS5LZ4_SKIP_RUNTIME_UPGRADE=1 skips.
- ampr-emu-ng → `920e917` (v0.4.0: FPKG games, writable /app0, split reads for
  LZ4 and pkg packs; quer3q says LZ4 with split reads is not run on a console yet).
- Game reports can be sent from the page as an issue on quer3q/ampr-emu-ng
  (classic token with public_repo saved on the Remote tab, state/github-token
  0600) or opened on GitHub filled in; same result per game not sent twice a day.
- Packing uses every CPU core (owner), still at nice 19 (PS5LZ4_WORKERS overrides).
- Page stays responsive while packing: /api/dashboard answers from the last
  result and rebuilds in the background; runtime SHA-256 cached; packing runs
  at nice 19 and ionice idle (PS5LZ4_IONICE=besteffort for the old class).
- .exfat sources are packed in place: Forge reads the image (blake3 per file),
  no MkPFS extraction or work copy. The old "does not use AMPR" skip on .exfat
  is gone (it stopped PPSA21704); stale APR-era skip reports no longer hide a game.
- Stopped following James St-Pierre's branches: follower, workflow and docs
  cover quer3q only; `tools/james-branches.json` removed.
- Updated ampr-emu-ng to upstream v0.3.5 (`a0dd88a`), including the smaller
  PRX memory pool and load-based thread retirement. Forge remains v0.5.5.
  NAS/PS5 hardware validation remains open.

- Updated ampr-emu-ng to upstream main `f9aa923` (save overwrite, packed save
  icons and pread idle wakeups). Forge remains v0.5.5. NAS tests and JS checks
  passed locally; runtime host tests and PRX verification run in the image build.
  Hardware validation remains pending.

- Pruned the dead code of the original PS5 engine/app (backend and page), its
  rest-mode and free-space calls, Compress on PS5, KNOWN_GAMES and the old
  community helpers; every unpacked game is now packable (Forge injects
  ampr-emu-ng), not only titles that import libSceAmpr.
- TOML profiles removed (chooser, editor, upload, the TOML switch, `/api/profile`,
  `profile_*` actions, state/profiles); Forge's own rules decide every pack.
- `profiles/nas-ng.toml` and the added loose rules (PlayGo markers, the
  PPSA26344 boot files, `*.rmdtoc`, empty files) removed: they came from
  theghostonline's packer. Forge now packs those files unless a game TOML
  keeps them loose.
- Removed theghostonline's engine, PS5 app, packer, APR-EMU file, bundled
  profiles, compat data and sync/release workflows; APR-EMU copies are only
  listed and structure-checked; no Compress on PS5.
- LZ4 NG is packed by Forge (`--to lz4 --lz4-runtime ng`), with the mandatory
  loose-file rules like Zstd; APR-EMU LZ4 can no longer be chosen or queued.
- Game reports tab: quer3q's reports as a compatibility list (search, filters,
  in-your-library mark); list-style reports (a table of Title IDs) count per row.
- quer3q's game reports (issues labelled `test report` on quer3q/ampr-emu-ng):
  counts per Title ID for Zstd/LZ4 in the game sheet, and a filled-in report
  link after setting the PS5 result of a Zstd or LZ4 NG copy.
- theghostonline community reports off: no tab, counts, share link or fetching
  (`PS5LZ4_COMMUNITY=yes` turns the backend on again; the page parts are gone).
  The PS5 result is still saved on the NAS. The `.ffpfsc` sheet stays.
- Forge → v0.5.5 (`8a3c7d3`: .ini files never packed, bundles ampr-emu-ng
  v0.3.4, naming template); round trips pass with the real binary.
- Removing a copy keeps the report (and PS5 result) of the other format's copy.
- Follower no longer crashes when a Forge tag has no release files yet. (`--learn`
  only reads the bundled profiles; the old known issue was wrong.)
- ampr-emu-ng → `cbdafd8` (v0.3.4). Delete packed copy names and sends the exact
  folder; `cmd_remove` prints the right folder; `state/actions.log` keeps every
  page action (the page still shows the last 20).
- TOML switch off no longer drops theghostonline's bundled game/engine profiles
  (e.g. Insomniac layout) for LZ4 or Zstd.
- ampr-emu-ng → `e18a703` (v0.3.3, quer3q's own kernel AIO); our AIO patch removed.
- Removed Compress all (header) and Repair (after Check all) from the page.
- Compress all in the chosen format (`run_request` passes codec/runtime/level/
  profile to `lz4 --fix`; Zstd/LZ4 NG queue every AMPR original without that copy).
- TOML editor: `include_from` lists allowed (from state/profiles or copied from
  next to the TOML in use).
- Owner: legacy packed-folder cache refresh; copies classified by actual format.
- My games sub-tabs Folder/exFAT · LZ4 · Zstd; `requires_ng` per copy.
- LZ4 always with theghostonline's packer (LZ4 NG too); Forge = Zstd only.
- PR #6 (LZ4 → Zstd conversion) reverted: packs always from originals.
- ampr-emu-ng `b6a54d1` (James PRs #23/#24), AIO patch ported; Forge v0.5.4.
- Follow quer3q and James workflow; Compress dialog with estimates; TOML chooser.
