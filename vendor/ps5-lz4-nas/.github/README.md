# ps5lz4zstd: LZ4 NG and Zstd packing of PS5 games on a NAS

A Docker app for a NAS that packs PS5 game dumps (folders and exFAT images) into
**LZ4 NG** or **Zstd** packs for [ampr-emu-ng](https://github.com/quer3q/ampr-emu-ng),
using [PS5 Dump Forge](https://github.com/quer3q/ps5-dump-forge), with a web page
to manage the library, send games to the PS5 and install packages.

- Packs are always made from the original; originals are never changed.
- Every pack is read back against its source by Forge before it is published.
- Game reports come from, and go to, quer3q/ampr-emu-ng.
- "Verified on the NAS" is not "playable on the PS5": test each game on the console.

Install, update and use: [nas-lz4/README.md](nas-lz4/README.md).
Credits and licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Update on the NAS:

```sh
cd /volume2/docker/ps5-lz4 && ./lz4-ps5.sh update --force
```

License: GNU GPL v3 or later (`LICENSE`).
