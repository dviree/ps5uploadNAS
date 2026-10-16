# LZ4 Compression 1.4.2

- Fixed the PS5 app freezing when you open History (the clock button, top
  right). Thanks @delacruzrl for reporting it (#1). Job times now show as
  "5 min ago", "Yesterday" and so on.
- A small Buy Me a Coffee QR code in the corner of the home screen, the same
  one PS5VR has. Scan it with your phone if the app saved you space.

Everything from 1.4.0 and 1.4.1 is included: bundled LZ4 profiles picked
automatically, a games-only library, LZ4 and read speed on `.exfat` images
while the app is open, and the `.ffpfsc` uncompress fix.

## Install

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
