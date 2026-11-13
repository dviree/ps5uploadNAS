# ps5lz4zstd: LZ4 NG and Zstd packing of PS5 games on a NAS

A Docker app for a NAS that packs PS5 game dumps (folders and exFAT images) into
**LZ4 NG** or **Zstd** packs for [ampr-emu-ng](https://github.com/quer3q/ampr-emu-ng),
using [PS5 Dump Forge](https://github.com/quer3q/ps5-dump-forge), with a web page
to manage the library, send games to the PS5 and install packages.

- Packs are always made from the original; originals are never changed.
- Every pack is read back against its source by Forge before it is published.
- Game reports come from, and go to, quer3q/ampr-emu-ng.
- "Verified on the NAS" is not "playable on the PS5": test each game on the console.

## What the web app looks like

The web page works on a phone or desktop. **My games** shows original folders
and images alongside their LZ4 NG and Zstd copies, their sizes, and the space
saved. **Activity** shows the current packing step, progress, speed, queued
work, and PS5 transfers. Other tabs manage PS5 games, package installation,
ShadowMount and game reports.

<table>
<tr><th>Activity: packing progress</th><th>My games: format and space saved</th></tr>
<tr><td><img src="docs/screenshots/activity-demo.jpg" alt="Illustrative dark theme Activity view with a fictional game, Zstd packing steps, progress and speed" width="420"></td><td><img src="docs/screenshots/library-demo.jpg" alt="Illustrative dark theme library view with fictional games and Zstd and LZ4 NG format options" width="420"></td></tr>
</table>

These are illustrative UI mockups with fictional games. No real game names,
cover art, title IDs, or private network addresses are shown. Sizes and speeds
are examples, not expected results for every game.

Choose **Zstd** for smaller packs or **LZ4 NG** for faster loading. Select a
game to pack it, then verify the copy and send it to the PS5. Packing uses the
original as its source and publishes a separate copy.

Install, update and use: [nas-lz4/README.md](nas-lz4/README.md).
Credits and licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Update on the NAS:

```sh
cd /volume2/docker/ps5-lz4 && ./lz4-ps5.sh update --force
```

License: GNU GPL v3 or later (`LICENSE`).
