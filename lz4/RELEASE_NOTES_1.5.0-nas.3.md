LZ4 Compression engine (`lz4-compression.elf`) from **PS5-LZ4-NAS**: the original
project's engine plus three additions for the NAS tool.

- **Drive size and free space:** `GET /api/lzc/df?path=/mnt/usb0` (port 5920) returns
  `{"ok":true,"total":…,"free":…}` for the file system holding a path under `/data`
  or `/mnt` (statvfs). ps5-lz4 shows it in its PS5 storage view; ftpsrv can't tell.
- **Rest mode on request:** `GET /api/lzc/rest?confirm=1` puts the PS5 in rest mode two
  seconds later; refused while the engine runs a job.
- **Keep awake for NAS transfers:** `GET /api/lzc/keep-awake?seconds=N` holds off rest
  mode for up to an hour; `seconds=0` releases it.

Install: the NAS page's **Install ELF on PS5** / **Update available** button (or its
automatic update) puts it in Payload Manager at
`/data/pldmgr/payloads/lz4-compression/lz4-compression.elf`.

Everything else is the original LZ4 Compression:
https://github.com/theghostonline/PS5-LZ4-Compression/releases
