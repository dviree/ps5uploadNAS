# LZ4 Compression 1.4.3

- Ghost of Yotei works now. Packed Yotei sat on a black screen because the PS5
  looks for some files on disk (PlayGo markers, empty language files and a few
  boot files) and they only existed inside the packs. Those files now stay
  loose when you pack. Huge thanks to edu-ruiz- on Reddit for finding the
  file list.
- Already have a packed game that won't start? Run `Verify LZ4 Packs` on it.
  It puts those files back on disk from the packs, puts back the right
  APR-EMU (`fakelib/libSceAmpr.sprx`) if something replaced it, and fixes
  permissions. No repack needed.
- Fixed games crashing on launch with SIGBUS or CE-108255-1 when the source
  files had 0666 permissions (seen on 007 First Light). Everything the app
  writes is 0777 now. Thanks OmgWhatIsThisss for spotting it.

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
