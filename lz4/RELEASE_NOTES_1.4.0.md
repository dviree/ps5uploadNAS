# LZ4 Compression 1.4.0

## Bundled LZ4 profiles

- The tested community TOMLs ship with the app: ASTRO BOT, EA Sports UFC 6,
  and the Insomniac and Unity engine profiles, all from danthespal's
  MkPFS.CSharp.
- `Automatic` picks one on its own by Title ID, name, or the game's file
  layout, so a matching game already has the right TOML when you open it. The
  game page shows which profile it will use.
- `Scan only` skips the bundled profile, and a config you imported yourself
  still wins.

## Games only

- The library only lists games now. Apps that ShadowMount+ mounts next to them
  (homebrew, media apps) are left out: anything under 2 GB counts as an app.

## Fixes

- Compress with LZ4 and Test Read Speed work on `.exfat` images while the app
  is open. ShadowMount+ won't mount anything while a game or app is running,
  so the engine now mounts the image read-only itself for the job. It also
  works on a second copy of a game that ShadowMount+ isn't using.
- Uncompressing an `.ffpfsc` to an image on another drive used the folder
  name and failed after writing the whole image. It gets the right name now.
- The Uncompress page shows the real uncompressed size, greys out drives
  without room, and picks one that fits. Job errors show sizes in GB instead
  of bytes.

## Install

1. Add `lz4-compression.elf` to Payload Manager, so it sits at
   `/data/pldmgr/payloads/lz4-compression/lz4-compression.elf`.
2. Unzip `LZ4-Compression-PPSA99420.zip` and copy the `PPSA99420` folder to
   `/data/homebrew/PPSA99420` over FTP (replace the old one). ShadowMount+
   adds the `LZ4 Compression` tile (close any running game if it doesn't show
   up).
3. Open the tile.

Tested on firmware 13.60 with Payload Manager, kstuff and ShadowMount+ 1.7.
Keep your original game until you've launched the packed version.

Unofficial, and not affiliated with the projects it builds on. If it saved you
space, you can support the cost of building it:
[Buy Me a Coffee](https://buymeacoffee.com/theghostonline)
