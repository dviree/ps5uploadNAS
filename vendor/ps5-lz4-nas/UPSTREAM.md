# PS5-LZ4-NAS integration

Complete tracked source imported from [dviree/PS5-LZ4-NAS](https://github.com/dviree/PS5-LZ4-NAS)
at `6e58069198d4fe997a1f531ddc2f33541ed8888d` (`nas-build`), 2026-11-13.
Includes the NAS application, installer/update scripts, Glass receiver sources,
upstream test suite, update tooling, documentation, licenses and original workflow definitions.
The workflows in this directory are reference source, not root Actions workflows.

Forge 0.5.5; ampr-emu-ng commit `0a5670a5d629c78572c61b66353a04e56f1b53d2`
(main after v0.3.5, including the merged packed-read priority fix / #51).
The combined image builds this exact runtime and includes its corresponding source and license.
The build runs the runtime's workspace tests and `make verify`.

Local integration changes to `nas-lz4/ps5lz4.py`, `ui.html` and `store.html`:
Zstd-only packing (API/CLI validation), Zstd level 5 defaults, no LZ4 packing controls,
and loopback-only HTTP. Existing packed-file readers remain for inspection and decoding.
Original game folders stay read-only; outputs and state use separate mounts.
`engine/Dockerfile.webui` adapts the upstream Docker stages to the combined image.

`pkg-receiver/` contains the full Glass overlay and its build recipe under
`.github/workflows/pkg-receiver.yml`. The application obtains its existing receiver
release from PS5-LZ4-NAS on demand; importing this source does not install a payload
on a console or add a second automatic workflow.

Imported tests are adapted where necessary to this combined app's Zstd-only policy.
The root `tests/test_nas_zstd.py` additionally verifies API/CLI rejection of LZ4,
source retention and the per-codec queue regression. LZ4 copy readers remain covered.
The compression dialog's leftover LZ4 card is removed; invalid choices cannot change
its Zstd selection. Runtime and source defaults use level 5 consistently.
