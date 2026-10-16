# Changelog

## 1.5.0 - 2026-10-14

Release notes: [RELEASE_NOTES_1.5.0.md](RELEASE_NOTES_1.5.0.md).

- In-app updates: the PS5 app checks the latest GitHub release when it opens
  and offers to update. It downloads the app zip and the engine, checks both
  against the SHA-256 GitHub lists, swaps them in and reopens. Errors say
  which step failed and why. `Skip this version` hides a release. The web page
  shows a `vX is out` link.
- Game reports: each packed game's page shows how it runs for other people,
  and `Report how it runs` sends yours as a prefilled GitHub issue (a QR code
  to scan on the PS5, a link on the web page). A workflow counts the reports
  into `compat/compat.json`, one vote per GitHub account per game.
- The engine draws QR codes (`GET /api/lzc/qr`, Project Nayuki's MIT QR
  library).
- The LZ4 packer and the PS5 app are licensed GPL-3.0-or-later (`LICENSE`).

## 1.4.3 - 2026-10-14

Release notes: [RELEASE_NOTES_1.4.3.md](RELEASE_NOTES_1.4.3.md).

- Ghost of Yotei starts instead of sitting on a black screen. The PS5 checks
  some files outside the game (PlayGo's `pgc_*_dummy_file` markers,
  `playgo.pgm`, the empty language placeholders) where the APR-EMU can't show
  packed files, and Yotei also needs a few boot files on disk. The packer now
  keeps all empty files, PlayGo markers and those Yotei files loose. Found by
  edu-ruiz- on Reddit.
- `Verify LZ4 Packs` repairs a packed folder: it puts those files back on disk
  from the packs (for games packed by older versions or other tools), puts
  back the PackedStdio APR-EMU if another tool swapped it, and fixes file
  permissions.
- Games packed from a dump or an `.exfat` image with 0666 files kept those
  permissions, so `eboot.bin` and the modules weren't executable and the game
  crashed with SIGBUS / CE-108255-1 (007 First Light). Everything the engine
  writes is now 0777, and packing fixes the permissions of the whole folder.
  Found by OmgWhatIsThisss.

## 1.4.2 - 2026-10-11

Release notes: [RELEASE_NOTES_1.4.2.md](RELEASE_NOTES_1.4.2.md).

- Fix the PS5 app freezing when History is opened (#1). The page formatted
  job times with `Date` objects, which the app's JS engine doesn't have, and
  the page had lost its back handling. Times now show as "5 min ago".
- A small Buy Me a Coffee QR code in the corner of the home screen, the same
  design PS5VR uses. The About card uses the same code.

## 1.4.1 - 2026-10-11

Release notes: [RELEASE_NOTES_1.4.1.md](RELEASE_NOTES_1.4.1.md).

- Buy Me a Coffee on the About page: a QR code in the PS5 app and a button on
  the web page.
- The PS5 app's About page cut the credits off mid-sentence; the PS5 React
  attribution is shown in full again.

## 1.4.0 - 2026-10-11

Release notes: [RELEASE_NOTES_1.4.0.md](RELEASE_NOTES_1.4.0.md).

- Bundled LZ4 profiles: the tested community TOMLs (ASTRO BOT, EA Sports UFC
  6, and the Insomniac and Unity engine profiles from danthespal's
  MkPFS.CSharp) ship with the engine. `Automatic` picks one by Title ID,
  name or the game's file layout, the game page shows which profile it will
  use, and `Scan only` skips it. An imported config still wins.
- The library lists games only: entries under 2 GB (homebrew and media apps)
  are left out.
- Jobs that only read an `.exfat` image (Compress with LZ4, Test Read Speed)
  mount it read-only themselves instead of asking ShadowMountPlus, which
  refuses while any game or the PS5 app is open and only mounts the copy it
  registered for a title.
- Uncompressing an `.ffpfsc` to an image on another drive kept the folder
  name and failed after writing the whole image; it now gets the right name,
  and the Uncompress page shows the real size and picks a drive with room.

## 1.3.0 - 2026-10-11

First release of LZ4 Compression. Release notes:
[RELEASE_NOTES_1.3.0.md](RELEASE_NOTES_1.3.0.md).

### LZ4 asset packs

- `Compress with LZ4`, `Verify LZ4 Packs` and `Uncompress LZ4`, all on the
  PS5. Packs use drakmor's AMPRPAK4 / AMPRDAT3 format (the packer is a C port
  of his `ampr_pack.py`): AMPR index, automatic scan-based profile with safety
  exclusions and auto-loose sampling, LZ4 or LZ4 HC compression on all cores,
  byte-for-byte verification against the originals, loose-file copy and the
  pinned APR-EMU 0.4.2.1 PackedStdio runtime in `fakelib`.
- LZ4 is the main action for every game that imports `libSceAmpr`, including
  games that ship no APR-EMU: packing adds the runtime to `fakelib`. The
  import check is cached in `/data/LZ4Compression/ampr-imports.txt`.
- Compression level 1 to 12 like Lazy_AMPR (1 to 4 LZ4 fast mode, 5 to 12
  LZ4 HC, default 9).
- Custom and trace-generated `ampr_pack` TOML profiles per title: upload
  them with their `include_from` lists, or `Import config` from a USB drive
  or `/data/LZ4Compression/import` (matched to the game by name like
  Lazy_AMPR). The automatic profile learns loose patterns from every profile.
- `.exfat` and `.ffpfs` images that ShadowMountPlus mounts only while playing
  are mounted for the job and released afterwards.
- `Pack in place`, which verifies the packs and then removes only the
  originals now stored in them, with a full rollback on failure.
- LZ4 output next to the game, to internal SSD or to external storage, keep or
  delete after verified, and in-place or new-folder uncompress.
- `Build AMPR Index`, APR-EMU version changes and original restores are
  blocked for LZ4 packed games, and compress or Make Image keep their
  `ampr_emu.index` untouched, since the packs are tied to it.

### The app

- Native PS5 app `PPSA99420` built with PS5 React: left-to-right library,
  a page per game with its options as grouped cards, full-page screens for
  every action, D-pad and stick navigation with controller vibration, and a
  done screen when a job finishes. It starts the engine through Payload
  Manager when needed.
- Engine `lz4-compression.elf`, web page on port `5920`, settings, caches and
  logs in `/data/LZ4Compression`. The web page has the same black UI.
- Black `LZ4` block tile icon and home-screen art, plus a matching in-app logo
  and favicon.

### Also included

- `.ffpfsc` compress and uncompress, exFAT/PFS images, validate and repair,
  APR-EMU index building and version switching, copy and move, and job
  history, on firmware 13.60 with ShadowMountPlus 1.7.

### Tooling

- Host build of the packer (`tests/host`), a PS5 self-test payload
  (`tests/ps5`) and a web UI test harness (`tests/ui`).
