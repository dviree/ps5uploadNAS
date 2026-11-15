# Snapshot: how the code is laid out (2026-11-07)

Read this before scanning the repo. Find symbols with Trail (`trail ask/grep/
callers/skeleton`); line numbers below drift, names don't.

## Pieces

| Folder | What | Language |
|---|---|---|
| `nas-lz4/` | **The NAS app** (Docker): packing agent + web page. | Python, HTML/JS |
| `pkg-receiver/` | Glass theme + extras for pkg-receiver (PS5 package installer payload) | C, JS, Py |
| `tools/` | `quer3q_update.py` (follow quer3q only) | Python |
| `tests/nas/` | `python3 -m unittest discover -s tests/nas`, `node tests/nas/*.cjs` | Py, JS |
| `.github/workflows/` | `build-image.yml` (NAS image on `nas-build`), `quer3q-update.yml`, `pkg-receiver.yml` | YAML |

theghostonline's parts (`src/`, `app/`, `assets/`, `nas/`, `tests/host`,
`third_party/`, `compat/`, bundled profiles, release and sync workflows) were
removed on 2026-11-10. Its PS5 engine/app code is pruned from `ps5lz4.py` and the page too.

## NAS app (`nas-lz4/`)

- `ps5lz4.py` (~8 300 lines, one file): CLI (`main`/`job_opts`), packing
  agent (`cmd_agent`, request files in `state/requests`), web server
  (`cmd_ui` → class `H`, port 5921) and catalog server (port 9898).
- `ui.html`: the whole page (vanilla JS; not indexed by Trail). Tabs: My games
  (sub-tabs Folder/exFAT · LZ4 · Zstd), Activity, PS5 games, PKG installer,
  PS4 games, ShadowMount, Saves, PS5 Upload, Game reports (quer3q's ampr-emu-ng reports, `/api/ng-reports`),
  Remote, FTP. Header:
  Check all, Full re-check (no Compress all / Repair buttons; CLI only).
- `Dockerfile`: stage `ng-runtime` builds ampr-emu-ng (quer3q main as is, no
  patch), `forge`
  installs PS5 Dump Forge (`install-forge.py`, pinned + SHA-256), final image
  adds `lz4`, `zstd`, `unrar`, MkPFS.
- `install.sh` (first install, writes compose), `lz4-ps5.sh` (`update`,
  `update --force`, wrapper for CLI commands in the container).

### Packing pipeline (class `Job`)

`step_source` (folder as is; `.exfat`, PS5 game `.pkg` (library and package folder, `Entry.host_path`) and orphaned LZ4 copies (`pack_sources`) read in place by Forge; `.ffpfs/.ffpfsc` unpacked to a work folder)
→ `step_check` (unpacked, has eboot.bin) → `step_pack` (Forge) →
`step_verify` → `step_restore` (full unpack + byte compare, games ≤ 25 GB) →
`step_publish` (boot files, permissions, report in `state/reports/<id>.json`).

- **Zstd only** (LZ4 NG no longer packed): PS5 Dump Forge (`forge_command`), then our ampr-emu-ng
  build (`install_ng_runtime`); no profile: Forge's own rules. APR-EMU LZ4 is no longer packed (`Job` refuses runtime legacy).
  Zstd output in the Zstd output folder (`zstd_output`).
- On older NAS installs, `lz4-ps5.sh update` creates a Zstd Compose override,
  saves its path in `.env` and exports `COMPOSE_FILE` before recreating services.
- Always from the original; never from an LZ4 copy.
- Queue: `state/queue.json`; `cmd_start` → background `run --from-queue`.
- Queue checks set the requested codec on each entry; `result_for` treats an
  existing report as done only when it belongs to that codec.

### Key helpers

- Paths: `output_roots/output_items/output_item/output_for`, `host_output_path`.
- Pack format: `is_packed`, `packed_codec`, `lz4_format_problem`,
  `runtime_sha/requires_ng/runtime_ok` (report counts only for the copy it
  describes), `update_runtime_index`.
- Library: `scan_library` → `Entry` (`kind` folder/exfat/ffpfs/ffpfsc),
  `classify`, `result_for`, `CheckDB` cache (`state/ps5lz4.db`).
- Profiles: none. Forge's own packing rules decide (no TOML anywhere).
- Estimates: `estimate_game` (`/api/estimate`), `pack_speeds`.
- Page data: `dashboard_data` (`/api/dashboard`: `games` rows for originals,
  `copies` one per packed folder, `pkgs`, …), `game_detail`.
- PS5 side: FTP (`ps5_ftp_*`), pkg-receiver (`receiver_*`, port 12800),
  Forge console ELF (`forge_ps5_elf`/`forge_ps5_install`: verified v0.5.5,
  Payload Manager or elfldr, console UI on port 8095),
  ShadowMountPlus via receiver (`smp`, `launch_check`), packages
  (`scan_pkgs`, `pkg_install*`, `ps5_installed`, `pkg_on_ps5`).
- Community reports (`compat_*`, `report_url`): off unless `PS5LZ4_COMMUNITY=yes`.
- quer3q's reports: `ng_reports_refresh/aggregate` (state `ng-reports.json`, every
  3 h), `ng_report_url` (form link), shown by `ngReportsHtml` in ui.html;
  sending: `ng_report_issue/ng_report_submit` (token `github_token`, state
  `github-token`, `ng-submitted.json`), form `ngReportFormHtml`.

### State on the NAS (`/volume2/docker/ps5-lz4/state`)

`queue.json`, `reports/`, `requests/`, `actions.log` (every page action, append-only), `verify/`, `transfers/`, `settings.json`, `ps5lz4.db`.

## Upstreams and pins

- quer3q/ampr-emu-ng main (pin `NG_COMMIT` in Dockerfile, `920e917` v0.4.0,
  including PR #51 fd read priority for issue #37, on-demand index reads and
  exact-size pack reads; kernel AIO built in).
- quer3q/ps5-dump-forge releases (pin in `install-forge.py`).
- `tools/quer3q_update.py` moves pins (checks SHA256SUMS); quer3q only.
