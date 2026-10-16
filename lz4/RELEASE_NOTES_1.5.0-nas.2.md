LZ4 Compression engine (`lz4-compression.elf`) from **PS5-LZ4-NAS**: the original
project's engine at 1.5.0 plus two additions for the NAS tool.

- **Rest mode on request:** `GET /api/lzc/rest?confirm=1` (port 5920) puts the PS5
  in rest mode two seconds later (`sceSystemStateMgrEnterStandby`), and is refused
  while the engine runs a job. ps5-lz4 on the NAS calls it a few minutes after the
  last game is sent, only when it woke the PS5 itself for the transfer, and from its
  **Rest mode now** button.
- **Keep awake for NAS transfers:** `GET /api/lzc/keep-awake?seconds=N` holds off
  rest mode for up to an hour; `seconds=0` releases it. ps5-lz4 renews it every
  minute while it sends a game over FTP.

Install: the NAS page's **Install ELF on PS5** button (or its automatic update)
puts it in Payload Manager at
`/data/pldmgr/payloads/lz4-compression/lz4-compression.elf`. By hand: copy it there,
replacing the engine that is there.

Everything else is the original LZ4 Compression 1.5.0:
https://github.com/theghostonline/PS5-LZ4-Compression/releases
