# LZ4 Compression 1.5.0

- The app updates itself now. When a new version is out you get a popup when
  you open the app: press Update and it downloads, installs and reopens on its
  own (engine included). No more FTP for updates after this one.
- Game reports: every packed game shows how it runs for other people, and
  `Report how it runs` lets you add yours. Pick an answer, scan the QR code
  with your phone and send the prefilled report. The more people report, the
  easier it is to know which games pack fine before you start.
- The packer and the app are open source under GPL-3.0 now.

Everything from 1.4.3 is included (Ghost of Yotei fix, permission fix,
`Verify LZ4 Packs` repairs).

## Install

This is the last manual update:

1. Add `lz4-compression.elf` to Payload Manager, so it sits at
   `/data/pldmgr/payloads/lz4-compression/lz4-compression.elf`.
2. Unzip `LZ4-Compression-PPSA99420.zip` and copy the `PPSA99420` folder to
   `/data/homebrew/PPSA99420` over FTP (replace the old one). ShadowMount+
   adds the `LZ4 Compression` tile (close any running game if it doesn't show
   up).
3. Open the tile.

Unofficial, and not affiliated with the projects it builds on. If it saved you
space, you can support the cost of building it:
[Buy Me a Coffee](https://buymeacoffee.com/theghostonline)
