# LZ4 Compression 1.3.0

The first release of LZ4 Compression: LZ4 packs for PS5 games, made right on
the console.

## LZ4 asset packs

- `Compress with LZ4` packs game data into seekable LZ4 packs that APR-EMU
  reads while the game runs. Executables, system files and already-compressed
  media stay loose.
- Works on any game that uses AMPR, not just the ones that ship APR-EMU. The
  app checks the game's `eboot.bin` and `sce_module` for `libSceAmpr`, and
  when there's no `fakelib/libSceAmpr.sprx` it adds the pack-capable APR-EMU
  runtime for you. Games that don't use AMPR get `.ffpfsc` compression
  instead.
- Compression level from 1 to 12, the same scale as Lazy_AMPR. 1 to 4 use
  LZ4's fast mode, 5 to 12 use LZ4 HC, and 9 is the default.
- Automatic profile, or your own `ampr_pack` TOML. `Import config` finds
  TOMLs on a USB drive or in `/data/LZ4Compression/import` and puts the ones
  named after the game first. You can also upload them from a PC or phone.
- Works on game folders and on `.exfat` and `.ffpfs` images. ShadowMount+
  only mounts images while a game runs, so the app mounts them itself for the
  job.
- Write the packed game next to the original, to the internal SSD or to
  external storage, or pack a folder in place to use the least free space.
- Every packed file is compared byte for byte with the original before
  anything is removed.
- `Verify LZ4 Packs` checks every block, and `Uncompress LZ4` gives you back
  the normal loose game.

## The app

- A native PS5 app (`PPSA99420`), no browser. D-pad and stick navigation,
  controller vibration, and Circle goes back.
- Your games run left to right like the home screen, every game opens its
  own page, and every action opens as a full page.
- The engine (`lz4-compression.elf`) does the work, and the app starts it
  through Payload Manager when it isn't running. The web page on port 5920
  is still there for a PC or phone.

It also does `.ffpfsc` compression and uncompression, exFAT/PFS images,
validate and repair, APR-EMU versions, and copy and move.

## Install

1. Add `lz4-compression.elf` to Payload Manager, so it sits at
   `/data/pldmgr/payloads/lz4-compression/lz4-compression.elf`.
2. Unzip `LZ4-Compression-PPSA99420.zip` and copy the `PPSA99420` folder to
   `/data/homebrew/PPSA99420` over FTP. ShadowMount+ adds the
   `LZ4 Compression` tile (close any running game if it doesn't show up).
3. Open the tile.

Tested on firmware 13.60 with Payload Manager, kstuff and ShadowMount+ 1.7.
It has its own tile, port (`5920`) and settings folder
(`/data/LZ4Compression`), so it can be installed next to Game Compressor.

Keep your original game until you've launched the packed version.
