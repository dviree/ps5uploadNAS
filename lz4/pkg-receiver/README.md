# pkg-receiver with the Glass theme

[pkg-receiver](https://github.com/Loopayeh/pkg-sender) (Loopayeh, MIT, see
`LICENSE-pkg-sender`) is the PS5 payload the NAS page uses to install
packages. This folder only restyles its *pkg remote installer* page:

- `glass.css`: the Glass theme, applied after pkg-sender's own CSS.
- `glass.js`: on the Images tab, one card per game with a choice of its
  images (**exFAT** / **FFPFSC** original or **LZ4**), from the catalog's
  `game` and `variant` fields.
- `awake.c`: keeps the PS5 out of rest mode (auto power-down timer reset
  every 20 s): always unless switched off with the header's **Stay awake**,
  and while it installs, copies or the NAS asks (`/api/keep-awake`).
- `installed.c` + the end of `glass.js`: `/api/installed` lists the apps in
  `/user/app` (version from their `param.sfo` / `param.json`, patch folder
  in `/user/patch`) and the files in the homebrew folders; the page marks
  cards **✓ Installed · v…**, **✓ On PS5** (an image, or the LZ4 copy's
  `<game>-lz4` folder), **Partly copied**, or a patch newer than the
  installed game. Refreshed every 30 seconds.
- `installed.c` also adds `GET /api/df?path=` (free space of any drive)
  and `POST /api/uninstall?tid=` (takes a title off the home screen with
  `sceAppInstUtilAppUnInstall`; never the page's own launcher).
- `smp.c`: `POST /api/smp?route=…` passes ShadowMountPlus API routes
  (version, games, games/info, games/unmount, games/uninstall, scan,
  storage, logs, games/move and its job status/cancel) to 127.0.0.1:10101, `GET /api/smp-icon?title_id=` its icon
  thumbnails, and `POST /api/notify` shows a notification on the PS5.
- `glass.py path/to/payload/main.c`: adds these to `main.c` (and `-lSceSystemService` to the Makefile),
  appends `-glass.N` to the build (bump `REV` on every change, so the NAS
  restarts a running receiver), closes the game window on Install so the
  answer shows, and adds a `;` the newer page script is missing.

`.github/workflows/pkg-receiver.yml` builds it from a pinned pkg-sender
commit with the PS5 payload SDK and publishes `pkg-receiver.elf` in the
`pkg-receiver-glass` release. To try a newer pkg-sender, change
`PKG_SENDER_REF` there.
