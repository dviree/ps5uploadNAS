LZ4 Compression engine (`lz4-compression.elf`) from **PS5-LZ4-NAS**: the original
project's engine at 1.5.0 plus one addition for the NAS tool.

- **Keep awake for NAS transfers:** `GET /api/lzc/keep-awake?seconds=N` (port 5920)
  holds off rest mode for up to an hour, using the engine's own power guard, without
  a job of its own; `seconds=0` releases it. ps5-lz4 on the NAS calls it every minute
  while it sends a game over FTP, so the PS5 stays awake until the transfer is done.

Install: put `lz4-compression.elf` in Payload Manager at
`/data/pldmgr/payloads/lz4-compression/lz4-compression.elf` (replacing the original
engine). The app's in-app update fetches the original project's engine and would
replace this one; send this one again after such an update.

Everything else is the original LZ4 Compression 1.5.0:
https://github.com/theghostonline/PS5-LZ4-Compression/releases
