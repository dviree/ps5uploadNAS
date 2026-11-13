# Notes for Claude Code

## Memory files (read first, update last)

- **SNAPSHOT.md**: where the code stands (pieces, pipeline, key functions, state,
  pins). Read it at the start instead of scanning the repo.
- **BACKLOG.md**: bugs found, stubs, ideas, and the `>RESUME HERE` block for work
  that spans sessions. Start there; put new findings there, not only in chat.
- When a task is done (pushed and checked), update all three: CLAUDE.md (new
  standing rules), BACKLOG.md (resume point, done/open items), SNAPSHOT.md (what
  changed in the layout). Keep them short.

## Standing rules from the owner

- Chat in Swedish; product, UI, repo and docs text in English. Short answers.
- Push to `nas-build`, then `main`. No force-push without permission. Commit
  trailers as the session gives them; no model IDs in commits.
- No real game names in the repo (Title IDs only), no personal data.
- Never delete or overwrite original games; deletes only with
  `DELETE_ORIGINALS=yes`. Keep temporary data after a failed run.
- Don't change other Docker containers or NAS settings.
- Tell "verified on the NAS" apart from "playable on the PS5".
- Packs are always made from the original: folder/exFAT → LZ4 or folder/exFAT →
  Zstd, never LZ4 → Zstd.
- New packs are LZ4 NG or Zstd only, both packed by PS5 Dump Forge for
  ampr-emu-ng (owner, 2026-11-10; replaces "LZ4 always with theghostonline's
  packer"). LZ4 with APR-EMU is no longer packed; existing copies stay.
- Nothing from theghostonline in the repo or image (owner, 2026-11-10): no
  engine, PS5 app, `ampr_pack`, APR-EMU file, profiles or loose-file rules, sync. Only
  quer3q's Forge and ampr-emu-ng. Don't bring any of it back.
- Third-party code (quer3q, James St-Pierre) only after review and the owner's OK. Don't route around proxy 403s.
- After a feature, give the update command:
  `cd /volume2/docker/ps5-lz4 && ./lz4-ps5.sh update --force`
  (after the `Build NAS image` run on `nas-build` is green).
- Older NAS installs must first replace their local `lz4-ps5.sh` with this repo's
  wrapper; its update migrates the Zstd mount and exports `COMPOSE_FILE`.
- A report for one codec must not make a fresh pack of the other codec count
  as done; select the requested codec before checking queue results.
- No theghostonline community reports in the page (no tab, counts or share
  links). Game reports come from and go to quer3q/ampr-emu-ng (Zstd, LZ4 NG).
- No TOML profiles (owner, 2026-11-10): no chooser, editor, upload or switch;
  Forge's own packing rules decide every pack.
- Show mockups/screenshots before building larger UI changes when asked.

## Current upstream integration

- ampr-emu-ng is pinned to upstream main `0a5670a` (after v0.3.5), including
  the fd read priority fix merged in PR #51 for issue #37. Forge is v0.5.5.

## Mandatory Trail-Code workflow

Always use [Trail-Code](https://github.com/trailhq/Trail-Code) as the primary codebase
navigation and context system.

At the start of every session, check `command -v trail`. If it is missing, install it with
`npm install -g @trailhq/trail-code` (cloud sessions: it belongs in the environment's setup
script), then run `trail build` if `graft/` is missing.

Use Trail-Code only for finding code: `trail ask`, `trail grep`, `trail callers`,
`trail skeleton` and `trail map`, never grep, rg, find, sed or reading whole files to
search. Read only the line ranges Trail points to (to edit them), and test with the repo's
own tools. Trail indexes code only (.py, .c/.h, .js/.jsx), not ui.html, Dockerfile,
shell scripts, workflows or Markdown: for those, say in the reply that Trail can't search
them before reading them, and read only the file that needs the change.

Before implementing changes:
- Consult Trail's code map (`trail ask`, `trail map`, `trail skeleton`, `trail grep`) and the
  relevant learnings in `.trail/`.
- Identify affected functions, callers and dependencies (`trail callers <symbol> -d N`).
- Check existing architectural decisions (learnings marked Decided / Tried and ruled out).

After modifying code:
- Review the impact radius (`trail blast --base origin/main`).
- Run `trail check` when applicable.
- Preserve and update relevant project learnings (`trail note --title "<about>"`).

Keep Trail's "[trail] tokens saved" lines in the output (don't filter them away) and end
every reply that used Trail with "🌱 trail saved ~N tokens this turn", N summed from them.

If Trail-Code is unavailable, report that explicitly. Do not claim Trail checks were
performed unless they actually ran.

Privacy: run Trail with `DO_NOT_TRACK=1`, and never with the look-back over past sessions
(`TRAIL_NO_LOOK_BACK=1`): they hold personal data that must not reach the repo. A learning
never names a real game (Title IDs only), a person, a user name or a LAN address.
