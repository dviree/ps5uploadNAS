Vendored from https://github.com/dviree/PS5-LZ4-NAS at 2454c640bdaba70f0c3241c121e1581269edb9de (nas-build), 2026-11-11.

Forge 0.5.5; ampr-emu-ng v0.3.5 / a0dd88a2b6975b61ebc9d32d3cabefaf0dca2614.
The NAS HTTP server binds to loopback in the combined image. All access goes through the engine allowlist.
Original game folders are read-only; outputs and state use separate mounts.

Local integration changes: Zstd-only packing (including API/CLI checks), Zstd defaults, no LZ4 tabs/buttons, private loopback HTTP. Existing packed-file readers remain for inspection and decoding.
