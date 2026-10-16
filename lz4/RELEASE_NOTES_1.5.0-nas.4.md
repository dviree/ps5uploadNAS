LZ4 Compression engine (`lz4-compression.elf`) from **PS5-LZ4-NAS**.

- **Glass theme for the web page** (`http://<PS5>:5920`): a violet-blue gradient
  behind frosted, see-through panels, purple buttons with white text. On by default;
  the ✨ button in the top bar switches back to the original black theme (remembered
  in the browser).
- **Drive size and free space:** `GET /api/lzc/df?path=/mnt/usb0` (statvfs) for the
  NAS tool's storage view.
- **Rest mode on request:** `GET /api/lzc/rest?confirm=1`, refused while a job runs.
- **Keep awake for NAS transfers:** `GET /api/lzc/keep-awake?seconds=N`.

Install: the NAS page's **Update available** / **Install ELF on PS5** button (or its
automatic update) puts it in Payload Manager at
`/data/pldmgr/payloads/lz4-compression/lz4-compression.elf`.

Everything else is the original LZ4 Compression:
https://github.com/theghostonline/PS5-LZ4-Compression/releases
