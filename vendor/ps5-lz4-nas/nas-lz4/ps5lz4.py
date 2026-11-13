#!/usr/bin/env python3
"""ps5lz4 - LZ4 HC packing of PS5 games for APR-EMU, run entirely on a NAS.

Pipeline for each game (folder, .exfat, .ffpfs or .ffpfsc):

  1. source    use the folder as is, or extract the image with MkPFS into the
               work area (.ffpfsc inner images are checked against their
               .vhash sidecar when one exists)
  2. check     only games that use AMPR (libSceAmpr import or APR-EMU in
               fakelib/) can read LZ4 packs; anything else is skipped
  3. pack      ampr_pack_cli: LZ4 HC (level 9 by default), AMPR index,
               PackedStdio runtime, byte-for-byte check against the source
  4. verify    ampr_pack_cli verify: manifest, CRC sidecar, every chunk
               decoded, every packed file compared byte for byte again
  5. restore   unpack into a scratch folder and compare every file with the
               source; only ampr_emu.index and fakelib/libSceAmpr.sprx may
               differ, and the runtime must be the pinned PackedStdio build
  6. publish   move the result to OUTPUT/<name>-lz4, write the report, remove
               the work folder

Originals are never written: the library is mounted read-only and every
removal is limited to the work area. A failed or interrupted job keeps its
work folder; running it again resumes after the last finished step.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

VERSION = "1.1.0"

LIBRARY = Path(os.environ.get("PS5LZ4_LIBRARY", "/library"))
OUTPUT = Path(os.environ.get("PS5LZ4_OUTPUT", "/output"))
ZSTD_OUTPUT = Path(os.environ["PS5LZ4_ZSTD_OUTPUT"]) if os.environ.get("PS5LZ4_ZSTD_OUTPUT") else None
STATE = Path(os.environ.get("PS5LZ4_STATE", "/state"))
WORK = OUTPUT / ".ps5lz4-work"
MKPFS = os.environ.get("PS5LZ4_MKPFS", "mkpfs")
LOGS = STATE / "logs"
REPORTS = STATE / "reports"
PLAYED = STATE / "played"  # PS5 result of games that are not LZ4 (a sent original, an extracted RAR)
LOCK_PATH = STATE / "run.lock"
QUEUE_PATH = STATE / "queue.json"
PREFERRED = STATE / "preferred.json"  # Title ID -> the library copy chosen with "Use this one"
# The same folders as the NAS sees them, for reports.
HOST_LIBRARY = os.environ.get("PS5LZ4_HOST_LIBRARY", str(LIBRARY))
HOST_OUTPUT = os.environ.get("PS5LZ4_HOST_OUTPUT", str(OUTPUT))
HOST_ZSTD_OUTPUT = os.environ.get("PS5LZ4_HOST_ZSTD_OUTPUT")
HOST_STATE = os.environ.get("PS5LZ4_HOST_STATE", "/volume2/docker/ps5-lz4/state"
                            if str(STATE) == "/state" else str(STATE))
FREE_MARGIN = int(float(os.environ.get("PS5LZ4_FREE_MARGIN_GB", "20")) * 1024**3)

# The APR-EMU runtime older LZ4 copies carry: recognised, no longer shipped or packed.
RUNTIME_SHA256 = "69e6c4d5e4f5fb83c9e01815db5861c4c75734acbf4595cafa50d4c218116d1a"
RUNTIME_NAME = "APR-EMU PackedStdio 0.4.2.1"
NG_UPSTREAM_SHA256 = "5f39ca8ebe169aa15d8a8ba8ec2f9cd4195f509d55daaf4b4edbfa80b145035c"
NG_MANIFEST = Path(os.environ.get("PS5LZ4_NG_MANIFEST", "/opt/ps5lz4/ng-runtime.json"))
_ng_build = json.loads(NG_MANIFEST.read_text()) if NG_MANIFEST.is_file() else {}
NG_SHA256 = _ng_build.get("sha256", NG_UPSTREAM_SHA256)
NG_NAME = _ng_build.get("name", "ampr-emu-ng 0.3.0")
NG_FILE = Path(os.environ.get("PS5LZ4_NG_RUNTIME", "/opt/ps5lz4/libSceAmpr-ng.sprx"))
FORGE = os.environ.get("PS5LZ4_FORGE", "/usr/local/bin/ps5-dump-forge")
RUNTIME_REL = "fakelib/libSceAmpr.sprx"



PLAY_STATES = {  # ours -> (report form answer, label)
    "works": ("Works", "works"),
    "issues": ("Works with issues", "works with issues"),
    "nostart": ("Won't start (black screen or crash on launch)", "won't start"),
    "crash": ("Crashes in game", "crashes in game"),
}

IMAGE_EXTS = {".exfat": "exfat", ".ffpfs": "ffpfs", ".ffpfsc": "ffpfsc"}
BARE_TID_RE = re.compile(r"(PPSA|CUSA)\d{5}([-_ ]?app\d*)?([-_ ]?v?[\d.]+)?", re.I)  # a name that is only a Title ID
TITLE_RE = re.compile(r"(PPSA|CUSA|PPSM)\d{5}", re.I)
VHASH_MAGIC = b"PFSCVHS1"
EXFAT_SIG = b"EXFAT   "

STEPS = ("source", "check", "pack", "verify", "restore", "publish")
# Restore test (a full unpack to disk compared with the original) only up to this
# size; 0 runs it for every game. Verify compares every packed file either way.
RESTORE_TEST_MAX = int(float(os.environ.get("PS5LZ4_RESTORE_TEST_MAX_GB", "25")) * (1 << 30))

_child: subprocess.Popen | None = None
_stop_requested = False


class JobError(Exception):
    """A step failed; the work folder is kept."""


class Interrupted(JobError):
    """Stopped from outside; the game stays queued and resumes."""


class Skip(Exception):
    """The game can't be handled safely and is left alone."""


# --------------------------------------------------------------------------
# small helpers

def now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def human(n: float | int | None) -> str:
    if n is None:
        return "-"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def tree_bytes(root: Path) -> tuple[int, int]:
    """(file count, total bytes) of every regular file under root."""
    files = total = 0
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            p = os.path.join(dirpath, name)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if os.path.isfile(p) and not os.path.islink(p):
                files += 1
                total += st.st_size
    return files, total


def free_bytes(path: Path) -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def under(path: Path, root: Path) -> bool:
    try:
        Path(os.path.abspath(path)).relative_to(os.path.abspath(root))
        return True
    except ValueError:
        return False


def zstd_output() -> Path:
    return ZSTD_OUTPUT if ZSTD_OUTPUT is not None else OUTPUT


def output_roots() -> list[Path]:
    return list(dict.fromkeys((OUTPUT, zstd_output())))


def output_items(pattern: str = "*") -> list[Path]:
    return sorted(p for root in output_roots() if root.is_dir() for p in root.glob(pattern))


def output_item(name: str) -> Path:
    # Existing outputs win, including Zstd copies created in the old shared folder.
    for root in output_roots():
        if (root / name).exists():
            return root / name
    return (zstd_output() if name.endswith(("-zstd", "-zstd.exfat")) else OUTPUT) / name


def host_output_path(path: Path) -> str:
    roots = [(zstd_output(), HOST_ZSTD_OUTPUT or (HOST_OUTPUT if ZSTD_OUTPUT is None else str(zstd_output()))),
             (OUTPUT, HOST_OUTPUT)]
    for root, host in roots:
        if under(path, root):
            return str(Path(host) / path.relative_to(root))
    raise ValueError(f"not a generated output: {path}")


def zstd_stage() -> Path:
    return zstd_output() / ".ps5lz4-zstd-stage"


def remove_work_path(path: Path) -> None:
    """rm -rf, but only inside the work area; never the library or output."""
    if not path.exists() and not path.is_symlink():
        return
    if not any(under(path, root) and os.path.abspath(path) != os.path.abspath(root)
               for root in (WORK, zstd_stage())):
        raise RuntimeError(f"refusing to delete outside the work area: {path}")
    if under(path, LIBRARY):
        raise RuntimeError(f"refusing to delete inside the library: {path}")
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def safe_name(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return s or "game"


def nice_prefix() -> list[str]:
    """Packing runs at the lowest CPU priority and, by default, in the idle disk
    class, so the web page and the NAS's own work keep answering while a game
    packs (PS5LZ4_IONICE=besteffort for the old best-effort class 7)."""
    prefix = []
    if shutil.which("nice"):
        prefix += ["nice", "-n", "19"]
    if shutil.which("ionice"):
        idle = os.environ.get("PS5LZ4_IONICE", "idle") != "besteffort"
        prefix += ["ionice", "-c3"] if idle else ["ionice", "-c2", "-n7"]
    return prefix


def workers() -> int:
    env = os.environ.get("PS5LZ4_WORKERS")
    if env:
        return max(1, int(env))
    # Every core (owner's choice): packing runs at nice 19, so the web page and
    # the NAS still get the CPU whenever they need it.
    return max(1, os.cpu_count() or 4)


# --------------------------------------------------------------------------
# game metadata and AMPR compatibility

def parse_param_json(data: bytes) -> tuple[str, str]:
    try:
        j = json.loads(data.decode("utf-8-sig", "replace"))
    except ValueError:
        return "", ""
    title_id = str(j.get("titleId") or "")
    name = ""
    loc = j.get("localizedParameters") or {}
    lang = loc.get("defaultLanguage") or "en-US"
    for key in (lang, "en-US", "en-GB"):
        entry = loc.get(key) if isinstance(loc, dict) else None
        if isinstance(entry, dict) and entry.get("titleName"):
            name = str(entry["titleName"])
            break
    if not name and isinstance(loc, dict):
        for entry in loc.values():
            if isinstance(entry, dict) and entry.get("titleName"):
                name = str(entry["titleName"])
                break
    return title_id, name


def game_version(*folders: Path, name: str = "") -> dict:
    """Version of a game: sce_sys/param.json (contentVersion, masterVersion,
    required firmware) in the first folder that has it, else [v1.2.3] in the name."""
    for d in folders:
        p = d / "sce_sys" / "param.json" if d else None
        try:
            if p and p.is_file() and p.stat().st_size < 1 << 20:
                j = json.loads(p.read_bytes().decode("utf-8-sig", "replace"))
                v = {"version": str(j.get("contentVersion") or ""), "master": str(j.get("masterVersion") or "")}
                fw = j.get("requiredSystemSoftwareVersion")
                if isinstance(fw, str) and fw.startswith("0x") and len(fw) >= 6:
                    v["firmware"] = f"{int(fw[2:4], 16):x}.{fw[4:6]}"  # 0x0750000000000000 -> 7.50
                if v["version"]:
                    return v
        except (OSError, ValueError):
            pass
    m = re.search(r"[\[_ ]v(\d+(?:\.\d+)+)", name)
    return {"version": m.group(1)} if m else {}


def stream_has(chunks, needle: bytes) -> bool:
    tail = b""
    for chunk in chunks:
        buf = tail + chunk
        if needle in buf:
            return True
        tail = buf[-(len(needle) - 1):]
    return False


def file_chunks(path: Path, size: int = 4 << 20):
    with open(path, "rb") as f:
        while True:
            b = f.read(size)
            if not b:
                return
            yield b


def find_game_root(top: Path) -> Path | None:
    """The shallowest folder holding eboot.bin (any letter case, any depth),
    the same rule exfat_inspect uses on the image directory."""
    hits = []
    for dirpath, _dirs, names in os.walk(top):
        if any(n.lower() == "eboot.bin" for n in names):
            hits.append(Path(dirpath))
    if not hits:
        return None
    return min(hits, key=lambda d: (len(d.relative_to(top).parts), str(d)))


PROGRAM_MAGICS = (b"\x7fELF", b"\x4f\x15\x3d\x1d", b"\x54\x14\xf5\xee")
DEEP_SCAN_MAX = 512 << 20


def program_like(name: str) -> bool:
    low = name.lower()
    return low.endswith((".prx", ".sprx", ".elf", ".self", ".bin"))


def deep_reason(rel: str) -> str:
    return (f"{rel} imports libSceAmpr (deep scan, outside eboot.bin/sce_module: "
            "test the packed game on the PS5 before deleting anything)")


def deep_scan_folder(root: Path) -> str | None:
    """Every program file in the game, not only eboot.bin and sce_module."""
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() != "fakelib"]
        for name in sorted(names):
            if not program_like(name):
                continue
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            if rel.lower() == "eboot.bin" or rel.lower().startswith("sce_module/"):
                continue
            try:
                if p.stat().st_size > DEEP_SCAN_MAX:
                    continue
                with open(p, "rb") as f:
                    if f.read(4) not in PROGRAM_MAGICS:
                        continue
            except OSError:
                continue
            if stream_has(file_chunks(p), b"libSceAmpr"):
                return rel
    return None


# IOI's Glacier engine keeps its data in .rpkg packages in a runtime/ folder and
# opens them straight from disk, not through APR-EMU: packed, they are gone from
# disk and the game stops at boot. Such games can't be LZ4 packed (the
# original's 1.6.2; seen on PPSA11386, the same layout as another Glacier title).
GLACIER_WHY = ("IOI Glacier engine (.rpkg packages in runtime/): it opens them straight from disk, "
               "so it can't start from LZ4 packs; keep it unpacked")


def glacier_names(names) -> bool:
    """True for a runtime/ listing with packagedefinition.txt or a .rpkg file."""
    return any(n.lower() == "packagedefinition.txt" or n.lower().endswith(".rpkg") for n in names)


def glacier_folder(root: Path) -> bool:
    try:
        rt = next((d for d in root.iterdir() if d.is_dir() and d.name.lower() == "runtime"), None)
        return bool(rt) and glacier_names(p.name for p in rt.iterdir())
    except OSError:
        return False


# Unity games often don't start once LZ4 packed (seen by exFAT2AMPR's author).
UNITY_WHY = ("made with Unity: Unity games often don't start once LZ4 packed; "
             "keep the original until the LZ4 copy has started once")
UNITY_FILES = {"globalgamemanagers", "data.unity3d", "unityplayer.prx", "libunity.prx", "unityplayer.sprx",
               "libil2cpp.prx", "il2cpp.prx", "global-metadata.dat"}


def unity_names(names) -> bool:
    """True for a file listing (relative paths) of a Unity game."""
    return any(n.lower().rsplit("/", 1)[-1] in UNITY_FILES or "/il2cpp_data/" in "/" + n.lower() + "/"
               for n in names)


def unity_folder(root: Path, limit: int = 20000) -> bool:
    """unity_names over a game folder, three levels deep at most."""
    names, stack = [], [(root, "", 0)]
    try:
        while stack and len(names) < limit:
            d, rel, depth = stack.pop()
            for p in d.iterdir():
                r = f"{rel}{p.name}"
                names.append(r)
                if p.is_dir() and depth < 3 and not p.is_symlink():
                    stack.append((p, r + "/", depth + 1))
    except OSError:
        pass
    return unity_names(names)


def ampr_status_folder(root: Path) -> tuple[str, str]:
    """('packed'|'compatible'|'incompatible', reason) for a game folder.

    Mirrors the PS5 engine (populate_lz4_state / title_imports_ampr)."""
    if (root / "ampr_zstd.index").exists():
        return "packed", "already zstd packed (ampr_zstd.index present)"
    if (root / "ampr_assets.index").exists():
        return "packed", "already LZ4 packed (ampr_assets.index present)"
    if glacier_folder(root):
        return "incompatible", GLACIER_WHY
    for d in root.iterdir():
        if d.is_dir() and d.name.lower() == "fakelib":
            for f in d.iterdir():
                if f.is_file() and f.name.lower() == "libsceampr.sprx":
                    return "compatible", "ships APR-EMU (fakelib/libSceAmpr.sprx)"
    eboot = root / "eboot.bin"
    if eboot.is_file() and stream_has(file_chunks(eboot), b"libSceAmpr"):
        return "compatible", "eboot.bin imports libSceAmpr"
    mod = root / "sce_module"
    if mod.is_dir():
        for f in sorted(mod.iterdir()):
            if f.is_file() and f.name.lower().endswith(".prx") and \
                    stream_has(file_chunks(f), b"libSceAmpr"):
                return "compatible", f"sce_module/{f.name} imports libSceAmpr"
    hit = deep_scan_folder(root)
    if hit:
        return "compatible", deep_reason(hit)
    return "incompatible", ("does not use AMPR: no program file imports libSceAmpr "
                            "(deep scan), so APR-EMU would never load")


def _chain(first: bytes, rest):
    yield first
    yield from rest


def exfat_game_prefix(files: dict) -> str:
    if "eboot.bin" in files:
        return ""
    return min((k[:-len("eboot.bin")] for k in files if k.endswith("/eboot.bin")), default="")


def exfat_inspect(image: Path) -> dict:
    """Title, name, size and AMPR status read straight from an .exfat image."""
    from mkpfs.exfat import ExfatReader  # pinned MkPFS 1.1.0

    with open(image, "rb") as fh:
        reader = ExfatReader(fh)
        files = {e.rel_path.lower(): e for e in reader.iter_files()}
        prefix = exfat_game_prefix(files)
        def get(rel: str):
            return files.get((prefix + rel).lower())
        title_id = name = ""
        pj = get("sce_sys/param.json")
        if pj:
            title_id, name = parse_param_json(b"".join(reader.read_file(pj)))
        total = sum(e.length for e in files.values())
        rt = prefix + "runtime/"
        if get("ampr_zstd.index"):
            status = ("packed", "already zstd packed (ampr_zstd.index present)")
        elif get("ampr_assets.index"):
            status = ("packed", "already LZ4 packed (ampr_assets.index present)")
        elif glacier_names(k[len(rt):] for k in files if k.startswith(rt) and "/" not in k[len(rt):]):
            status = ("incompatible", GLACIER_WHY)
        elif get("fakelib/libsceampr.sprx"):
            status = ("compatible", "ships APR-EMU (fakelib/libSceAmpr.sprx)")
        elif get("eboot.bin") and stream_has(reader.read_file(get("eboot.bin")), b"libSceAmpr"):
            status = ("compatible", "eboot.bin imports libSceAmpr")
        else:
            status = ("incompatible", "does not use AMPR: no program file imports libSceAmpr "
                                      "(deep scan), so APR-EMU would never load")
            for key, entry in sorted(files.items()):
                if key.startswith(prefix + "sce_module/") and key.endswith(".prx") and \
                        stream_has(reader.read_file(entry), b"libSceAmpr"):
                    status = ("compatible", f"{entry.rel_path} imports libSceAmpr")
                    break
            else:
                for key, entry in sorted(files.items()):
                    rel = key[len(prefix):]
                    if (not key.startswith(prefix) or not program_like(key)
                            or rel == "eboot.bin" or rel.startswith(("sce_module/", "fakelib/"))
                            or entry.length > DEEP_SCAN_MAX):
                        continue
                    chunks = reader.read_file(entry)
                    first = next(chunks, b"")
                    if first[:4] not in PROGRAM_MAGICS:
                        continue
                    if stream_has(_chain(first, chunks),
                                  b"libSceAmpr"):
                        status = ("compatible", deep_reason(entry.rel_path[len(prefix):]))
                        break
        listing = {e.rel_path[len(prefix):]: e.length for e in files.values()}
        return {"title_id": title_id, "name": name, "logical_bytes": total,
                "files": len(files), "status": status[0], "reason": status[1],
                "game_prefix": prefix, "listing": listing}


def game_entry(game_id: str) -> Entry:
    entry = next((e for e in scan_library() if e.id == game_id), None)
    if entry is None:
        raise ValueError("original game not found in the library")
    return entry



_estimates: dict = {}


def pack_speeds() -> dict:
    """Bytes per second the NAS packed at, per mode (median of its reports)."""
    seen: dict = {}
    for f in REPORTS.glob("*.json"):
        r = read_json(f, {}) or {}
        secs, size = r.get("pack_seconds"), r.get("source_bytes")
        if not (isinstance(secs, (int, float)) and secs > 0 and isinstance(size, int) and size > 0):
            continue
        mode = "zstd" if r.get("pack_codec") == "zstd" else "ng" if r.get("pack_runtime") == "ng" else "legacy"
        seen.setdefault(mode, []).append(size / secs)
    return {k: sorted(v)[len(v) // 2] for k, v in seen.items()}


def estimate_game(game_id: str) -> dict:
    """LZ4 HC and Zstd sizes of a game, from a sample of its files (64 spots
    spread by size, 512 KiB each, compressed with the lz4 and zstd tools at
    the page's levels), and how long a pack took here per mode."""
    entry = game_entry(game_id)
    st = entry.path.stat()
    key = (str(entry.path), st.st_mtime_ns, st.st_size)
    if key in _estimates:
        return {**_estimates[key], "speed": pack_speeds()}
    spot = 512 * 1024
    if entry.path.is_dir():
        files = []
        for p in sorted(entry.path.rglob("*")):
            try:
                if p.is_file() and not p.is_symlink():
                    files.append((p, p.stat().st_size))
            except OSError:
                pass
        def read(item, off):
            with open(item[0], "rb") as fh:
                fh.seek(off)
                return fh.read(spot)
    elif entry.path.suffix.lower() == ".exfat":
        from mkpfs.exfat import ExfatReader  # pinned MkPFS 1.1.0
        fh = open(entry.path, "rb")
        reader = ExfatReader(fh)
        files = [(e, e.length) for e in reader.iter_files()]
        def read(item, off):  # an image is read from each file's start
            out = b""
            for chunk in reader.read_file(item[0]):
                out += chunk
                if len(out) >= spot:
                    break
            return out[:spot]
    else:
        what = "a .pkg (its files are compressed inside)" if entry.kind == "pkg" else \
            "a .ffpfsc or .ffpfs: it is compressed or packed already"
        raise ValueError(f"no estimate for {what}; the result is shown after packing")
    total = sum(n for _, n in files)
    if not total:
        raise ValueError("the game has no data to sample")
    sample, step, pos, i, acc, spots = [], total / 64, total / 128, 0, 0, set()
    while pos < total and i < len(files) and len(sample) < 64:
        while i < len(files) and acc + files[i][1] <= pos:
            acc += files[i][1]
            i += 1
        if i >= len(files):
            break
        off = max(0, min(int(pos - acc), files[i][1] - spot)) if entry.path.is_dir() else 0
        off -= off % spot
        if (i, off) not in spots:  # a small game: no spot twice
            spots.add((i, off))
            sample.append(read(files[i], off))
        pos += step
    if not entry.path.is_dir():
        fh.close()
    raw = b"".join(sample)
    if not raw:
        raise ValueError("the game has no data to sample")
    import tempfile
    # Each 256 KiB piece on its own, as the packs compress chunks independently
    # (one stream would find repeats across samples that no pack can use).
    with tempfile.TemporaryDirectory() as tmp:
        pieces = [Path(tmp) / f"{n:05d}" for n in range(0, len(raw), 256 * 1024)]
        for n, f in enumerate(pieces):
            f.write_bytes(raw[n * 256 * 1024:(n + 1) * 256 * 1024])
        def packed(argv, ext):
            out = subprocess.run(argv + [str(f) for f in pieces], capture_output=True, timeout=300)
            if out.returncode != 0:
                raise ValueError(f"{argv[0]} failed: {out.stderr.decode(errors='replace')[:200]}")
            return sum(f.with_name(f.name + ext).stat().st_size for f in pieces)
        ratio_lz4 = packed(["lz4", "-9", "-B4", "-m", "-q"], ".lz4") / len(raw)  # HC, 64 KiB blocks like the packs
        ratio_zstd = packed(["zstd", "-5", "-q"], ".zst") / len(raw)
    res = {"source_bytes": total, "sample_bytes": len(raw), "files": len(files),
           "lz4": {"bytes": min(total, int(total * ratio_lz4))}, "zstd": {"bytes": min(total, int(total * ratio_zstd))},
           "method": f"{len(sample)} sample{'s' if len(sample) != 1 else ''}, {human(len(raw))}"}
    _estimates[key] = res
    return {**res, "speed": pack_speeds()}


# --------------------------------------------------------------------------
# library

class Entry:
    def __init__(self, path: Path, kind: str):
        self.path = path
        self.kind = kind  # folder | exfat | ffpfs | ffpfsc | pkg
        self.rel = str(path.relative_to(LIBRARY))
        stem = path.name if kind == "folder" else path.name[: -len(path.suffix)]
        self.id = safe_name(stem)
        self.title_id = ""
        self.name = ""
        self.duplicate_of: str | None = None
        m = TITLE_RE.search(path.name)
        if m:
            self.title_id = m.group(0).upper()

    @property
    def output(self) -> Path:
        codec = getattr(self, "pack_codec", None)
        if codec is None:
            rep = read_json(REPORTS / f"{self.id}.json", {}) or {}
            codec = rep.get("pack_codec", "lz4")
        name = f"{self.id}-{'zstd' if codec == 'zstd' else 'lz4'}"
        return output_item(name)

    @property
    def work(self) -> Path:
        return WORK / self.id

    def size(self) -> int:
        if self.kind == "folder":
            return tree_bytes(self.path)[1]
        return self.path.stat().st_size


UNREADABLE: set = set()  # library folders this container may not read (shown on the page)


def scan_library() -> list[Entry]:
    entries: list[Entry] = []
    if not LIBRARY.is_dir():
        return entries

    def walk(d: Path, depth: int):
        try:
            children = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for p in children:
            if p.name.startswith("."):
                continue
            try:
                if p.is_dir():
                    if (p / "eboot.bin").is_file():
                        e = Entry(p, "folder")
                        pj = p / "sce_sys" / "param.json"
                        if pj.is_file():
                            tid, name = parse_param_json(pj.read_bytes())
                            e.title_id = tid.upper() or e.title_id
                            e.name = name
                        entries.append(e)
                    elif depth < 3:
                        walk(p, depth + 1)
                elif p.is_file() and p.suffix.lower() == ".pkg":
                    # A PS5 game package (fake PKG): Forge packs it straight to LZ4 NG
                    # or Zstd. Updates, DLC, apps and PS4 packages stay on the PKG tabs.
                    info = pkg_info(p)
                    if pkg_is_ps5_game(info):
                        e = Entry(p, "pkg")
                        e.title_id = info["title_id"].upper()
                        e.name = info.get("name") or ""
                        entries.append(e)
                elif p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                    e = Entry(p, IMAGE_EXTS[p.suffix.lower()])
                    if not e.title_id:
                        # No Title ID in the name ("Some Game.exfat"): read it from the
                        # image's own sce_sys/param.json (as the original's 1.6.4 does).
                        e.title_id = (_safe(lambda: image_meta(p).get("title_id"), "") or "").upper()
                    entries.append(e)
            except PermissionError:
                # One unreadable game must not stop the rest of the library.
                UNREADABLE.add(str(p.relative_to(LIBRARY)))
                print(f"cannot read {p} as uid {os.getuid()}: fix with "
                      f"chown -R <NAS user> \"{HOST_LIBRARY}/{p.relative_to(LIBRARY)}\"",
                      file=sys.stderr)

    walk(LIBRARY, 0)
    # An unpacked folder wins over an image of the same game.
    folders = {e.title_id: e for e in entries if e.kind == "folder" and e.title_id and not is_packed(e.path)}
    for e in entries:
        if e.kind != "folder" and e.title_id in folders:
            e.duplicate_of = folders[e.title_id].rel
    # A copy chosen on the page ("Use this one") wins over the others with its Title ID.
    prefs = read_json(PREFERRED, {}) or {}
    for tid, rel in prefs.items():
        group = [e for e in entries if (e.title_id or "").upper() == tid]
        if any(e.rel == rel for e in group):
            for e in group:
                e.duplicate_of = None if e.rel == rel else rel
    # Two library entries must never share an output folder.
    seen: dict[str, Entry] = {}
    for e in entries:
        if e.id in seen:
            e.id = safe_name(e.rel.replace("/", "__"))
        seen[e.id] = e
    return entries


def nice_folder_name(e: "Entry", games: dict | None = None) -> str:
    """A name for a game whose param.json gave none: from inside an image, else the
    folder name unless it is only a Title ID ("PPSA12345-app0"), else the
    community list's name, else the parent folder without release tags."""
    if e.kind != "folder":
        name = _safe(lambda: image_meta(e.path).get("title"), None) or e.path.stem
    else:
        name = e.path.name
    if not BARE_TID_RE.fullmatch(re.sub(r"(?i)[-_ ]?app0$", "", name)):
        return name
    g = (games if games is not None else ng_reports()).get((e.title_id or "").upper()) or {}
    if g.get("name"):
        return g["name"]
    parent = e.path.parent
    if parent != LIBRARY:
        clean = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", parent.name)
        clean = re.sub(r"(?i)\b(PPSA|CUSA)\d{5}\b|[-_.]+", " ", clean)
        clean = re.sub(r"(?i)\b(duplex|app0?|ps5|fpkg|v?\d+\.\d+)\b", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        if len(clean) > 2:
            return clean
    return name


def resolve_targets(args_targets: list[str], entries: list[Entry]) -> list[Entry]:
    out: list[Entry] = []
    for t in args_targets:
        tl = t.lower().rstrip("/")
        hits = []
        if t.isdigit() and 1 <= int(t) <= len(entries):
            hits = [entries[int(t) - 1]]
        else:
            for e in entries:
                keys = {e.rel.lower(), e.id.lower(), e.path.name.lower(),
                        str(e.path).lower(), e.title_id.lower()}
                if tl in keys:
                    hits.append(e)
        if not hits:
            raise SystemExit(f"no game matches '{t}' (see: ps5lz4 scan)")
        if len(hits) > 1:
            names = ", ".join(h.rel for h in hits)
            raise SystemExit(f"'{t}' matches several entries: {names}")
        out.append(hits[0])
    return out


# --------------------------------------------------------------------------
# job

class Job:
    def __init__(self, entry: Entry, level: int, restore_test: bool,
                 require_vhash: bool, codec: str = "zstd", runtime: str = "ng",
                 use_profile: bool = True):
        if codec not in ("lz4", "zstd") or runtime not in ("legacy", "ng"):
            raise JobError("invalid codec or runtime")
        if runtime != "ng" or codec != "zstd":
            # Owner's decisions (2026-11-10, 2026-11-13): new packs are Zstd only, packed by
            # PS5 Dump Forge for ampr-emu-ng. Existing LZ4 and APR-EMU copies stay as they are.
            raise JobError("only Zstd is packed now (LZ4 and LZ4 NG are no longer made)")
        if not 1 <= level <= (22 if codec == "zstd" else 12):
            raise JobError("compression level out of range")
        self.codec, self.runtime = codec, runtime
        self.use_profile = use_profile  # kept for old queue entries; TOML profiles are gone
        entry.pack_codec = codec
        self.e = entry
        self.level = level
        self.restore_test = restore_test
        self.require_vhash = require_vhash
        self.work = entry.work
        self.state_path = self.work / "state.json"
        self.log_path = LOGS / f"{entry.id}.log"
        self.state = {}

    # logging -------------------------------------------------------------
    def log(self, msg: str) -> None:
        line = f"[{now()}] {self.e.id}: {msg}"
        print(line, flush=True)
        with open(self.log_path, "a") as f:
            f.write(line + "\n")

    def save(self) -> None:
        write_json(self.state_path, self.state)

    def done(self, step: str) -> bool:
        return step in self.state.get("done", [])

    def mark(self, step: str, **info) -> None:
        self.state.setdefault("done", [])
        if step not in self.state["done"]:
            self.state["done"].append(step)
        self.state.update(info)
        self.state["step"] = step
        self.state["updated"] = now()
        self.save()

    def expect(self, folder: Path, total: int, phase: str) -> None:
        """MkPFS runs without progress output: the page measures folder against total."""
        self.state["expect"] = {"folder": folder.name, "total": int(total), "phase": phase}
        self.save()

    def set_step(self, step: str) -> None:
        self.state["step"] = f"{step} (running)"
        self.state["updated"] = now()
        self.state["step_at"] = time.time()
        self.save()

    def need_space(self, nbytes: int, what: str) -> None:
        free = free_bytes(self.e.output.parent)
        if free < nbytes + FREE_MARGIN:
            raise JobError(f"not enough free space for {what}: need {human(nbytes)} "
                           f"+ {human(FREE_MARGIN)} margin, {human(free)} free on the output volume")

    def run_tool(self, argv: list[str], step: str) -> str:
        """Run a tool niced, its output in the work folder; returns stdout."""
        global _child
        out_path = self.work / f"{step}.out"
        err_path = self.work / f"{step}.err"
        self.log(f"$ {' '.join(argv)}")
        with open(out_path, "w") as out, open(err_path, "w") as err:
            _child = subprocess.Popen(nice_prefix() + argv, stdout=out, stderr=err,
                                      stdin=subprocess.DEVNULL)
            rc = _child.wait()
            _child = None
        if _stop_requested:
            raise Interrupted("stopped by request; run again to resume")
        if rc < 0:
            # Killed by a signal: container restart, NAS reboot, docker stop.
            raise Interrupted(f"{step} interrupted by signal {-rc}; run again to resume")
        if rc != 0:
            tail = err_path.read_text(errors="replace").replace("\r", "\n").strip().splitlines()
            tail = [l for l in tail if not l.startswith("[progress]")][-6:]
            raise JobError(f"{step} failed (exit {rc}): " + " | ".join(tail))
        return out_path.read_text(errors="replace")

    # steps ---------------------------------------------------------------
    def step_source(self) -> Path:
        e = self.e
        if e.kind == "folder":
            root = e.path
            self.mark("source", source_root=str(root), extraction="none (folder used as is)")
            return root
        if self.done("source"):
            root = Path(self.state["source_root"])
            if root.is_dir() or (root == e.path and root.is_file()):
                self.log(f"resume: source already checked at {root}")
                return root
        self.set_step("source")
        image = e.path
        if e.kind == "exfat":
            # PS5 Dump Forge reads an .exfat in place and checks every file it packs
            # against it (blake3): nothing is unpacked or mounted on the NAS.
            meta = exfat_inspect(image)
            self.state["precheck"] = {k: meta[k] for k in ("title_id", "name", "status", "reason")}
            if meta["status"] == "packed":
                raise Skip(meta["reason"])
            if not any(k.lower() == "eboot.bin" for k in meta["listing"]):
                raise Skip("no eboot.bin in the image")
            self.mark("source", source_root=str(image), image_bytes=image.stat().st_size,
                      extraction="none (PS5 Dump Forge reads the .exfat directly)",
                      source_files=meta["files"], source_bytes=meta["logical_bytes"])
            self.log(f"source: {image.name}, {meta['files']} files, {human(meta['logical_bytes'])}, read in place by Forge")
            return image
        if e.kind == "pkg":
            info = pkg_info(image)
            self.state["precheck"] = {"title_id": info.get("title_id", ""), "name": info.get("name", ""),
                                      "status": "compatible", "reason": "PS5 game package"}
            if not pkg_is_ps5_game(info):
                raise Skip(info.get("error") or f"not a PS5 game package ({info.get('category') or 'unknown type'})")
            self.mark("source", source_root=str(image), image_bytes=info["size"],
                      extraction="none (PS5 Dump Forge reads the .pkg directly)",
                      source_files=0, source_bytes=info["size"])
            self.log(f"source: {image.name}, {human(info['size'])} package, read in place by Forge")
            return image
        extract = self.work / "extract"
        partial = self.work / "extract.partial"
        outer = self.work / "outer.partial"
        remove_work_path(partial)
        remove_work_path(outer)
        remove_work_path(extract)
        info: dict = {"image_bytes": image.stat().st_size}

        if e.kind == "exfat":
            meta = exfat_inspect(image)
            self.state["precheck"] = {k: meta[k] for k in ("title_id", "name", "status", "reason")}
            if meta["status"] != "compatible":
                raise Skip(meta["reason"])
            self.need_space(meta["logical_bytes"], "extraction")
            self.expect(partial, meta["logical_bytes"], "unpacking the image")
            self.run_tool([MKPFS, "unpack", "--format", "exfat", "--no-progress",
                           str(image), str(partial)], "extract")
            info["extraction"] = "MkPFS exFAT reader"
            info["vhash"] = "n/a (.exfat has no hash sidecar)"
            root = find_game_root(partial)
            if not root:
                raise JobError("no eboot.bin in the extracted image")
            # Every file the image lists must be on disk with its exact size.
            bad = []
            for rel, length in meta["listing"].items():
                p = root / rel
                if not p.is_file() or p.stat().st_size != length:
                    bad.append(rel)
            if bad:
                raise JobError(f"extraction incomplete: {len(bad)} files missing or wrong size, e.g. {bad[:3]}")
            info["listing_check"] = f"{len(meta['listing'])} files match the image directory"
        else:
            self.need_space(image.stat().st_size * 3, "extraction")
            self.expect(outer, image.stat().st_size, "unpacking the outer image")
            self.run_tool([MKPFS, "unpack", "--format", "pfs", "--no-progress",
                           str(image), str(outer)], "extract-outer")
            info["extraction"] = "MkPFS PFS reader"
            if find_game_root(outer):
                outer.rename(partial)
                info["vhash"] = "n/a (plain PFS image)"
            else:
                files = [p for p in outer.rglob("*") if p.is_file()]
                if len(files) != 1:
                    raise JobError(f"unexpected image layout: {len(files)} files and no eboot.bin")
                nested = files[0]
                info["nested"] = nested.name
                info["vhash"] = self.check_vhash(image, nested)
                with open(nested, "rb") as f:
                    f.seek(3)
                    fmt = "exfat" if f.read(8) == EXFAT_SIG else "pfs"
                info["nested_format"] = fmt
                self.need_space(nested.stat().st_size, "inner extraction")
                self.expect(partial, nested.stat().st_size, "unpacking the inner image")
                self.run_tool([MKPFS, "unpack", "--format", fmt, "--no-progress",
                               str(nested), str(partial)], "extract-inner")
                remove_work_path(outer)
            root = find_game_root(partial)
            if not root:
                raise JobError("no eboot.bin in the extracted image")
        rel_root = root.relative_to(partial)
        partial.rename(extract)
        root = extract / rel_root
        files, total = tree_bytes(root)
        info.update(source_root=str(root), source_files=files, source_bytes=total)
        self.state.pop("expect", None)
        self.mark("source", **info)
        self.log(f"extracted {files} files, {human(total)} ({info['vhash']})")
        for f in ("extract.out", "extract.err", "extract-outer.out", "extract-outer.err",
                  "extract-inner.out", "extract-inner.err"):
            remove_work_path(self.work / f)
        return root

    def check_vhash(self, image: Path, nested: Path) -> str:
        sidecar = Path(str(image) + ".vhash")
        if not sidecar.is_file():
            if self.require_vhash:
                raise Skip("no .vhash sidecar to check the extraction against (--require-vhash)")
            return "no .vhash sidecar: extraction not checked against a reference"
        data = sidecar.read_bytes()
        if len(data) < 4096 or data[:8] != VHASH_MAGIC:
            return "invalid .vhash sidecar: not used"
        block = struct.unpack_from("<Q", data, 16)[0]
        nested_size = struct.unpack_from("<Q", data, 32)[0]
        count = struct.unpack_from("<Q", data, 40)[0]
        size = nested.stat().st_size
        if block != 65536 or nested_size != size or count != (size + block - 1) // block \
                or len(data) != 4096 + count * 32:
            if self.require_vhash:
                raise Skip("stale .vhash sidecar (--require-vhash)")
            return "stale .vhash sidecar (sizes differ): not used"
        self.log(f"checking {count} blocks of {nested.name} against {sidecar.name}")
        bad = 0
        with open(nested, "rb") as f:
            for i in range(count):
                b = f.read(block)
                if len(b) < block:
                    b += b"\0" * (block - len(b))
                if hashlib.sha256(b).digest() != data[4096 + i * 32: 4096 + i * 32 + 32]:
                    bad += 1
        if bad:
            raise JobError(f"extracted image does not match {sidecar.name}: {bad} of {count} blocks differ "
                           "(the image or its extraction is damaged)")
        return f"all {count} blocks match {sidecar.name}"

    def step_check(self, root: Path) -> None:
        if root.is_file():  # an .exfat or .pkg Forge reads directly; step_source checked it
            pre = self.state.get("precheck") or {}
            self.state.update(title_id=pre.get("title_id") or self.e.title_id, title_name=pre.get("name") or "")
            if not self.done("check"):
                self.mark("check", ampr=NG_NAME, profile_path=None, profile="Forge's own packing rules")
            return
        status, reason = ampr_status_folder(root)
        tid, name = "", ""
        pj = root / "sce_sys" / "param.json"
        if pj.is_file():
            tid, name = parse_param_json(pj.read_bytes())
        self.state.update(title_id=tid or self.e.title_id, title_name=name)
        if self.runtime == "ng":
            if is_packed(root):
                raise Skip("source is already packed; unpack it before making a new copy")
            if not (root / "eboot.bin").is_file():
                raise Skip("no eboot.bin in source")
            if self.done("check"):
                return
            self.mark("check", ampr=NG_NAME, profile_path=None, profile="Forge's own packing rules")
            return
        if status != "compatible":
            raise Skip(reason)
        self.mark("check", ampr=reason, profile_path=None, profile="Forge's own packing rules")
        self.log(f"compatible: {reason}")

    def step_pack(self, root: Path) -> Path:
        pack = zstd_stage() / self.e.id / "pack" if self.codec == "zstd" else self.work / "pack"
        pack.parent.mkdir(parents=True, exist_ok=True)
        if self.done("pack") and is_packed(pack):
            self.log("resume: packs already built")
            return pack
        self.set_step("pack")
        remove_work_path(pack)
        total = self.source_size(root)[1]
        self.need_space(total, f"{self.codec.upper()} packs")
        # Forge packs both formats: codec, runtime injection, indexes and full read-back
        # verification. Our own ampr-emu-ng build then replaces the one Forge ships.
        t0 = time.time()
        self.run_tool(forge_command(root, pack, self.codec, self.level), "pack")
        install_ng_runtime(pack)
        problem = lz4_format_problem(pack)
        if problem or runtime_sha(pack) != NG_SHA256:
            raise JobError(problem or "Forge installed an unexpected runtime")
        self.mark("pack", pack_stats={"engine": "PS5 Dump Forge", "full_verify": True},
                  pack_seconds=round(time.time() - t0))
        return pack

    def step_verify(self, root: Path, pack: Path) -> None:
        if self.done("verify"):
            return
        self.set_step("verify")
        problem = lz4_format_problem(pack)
        if problem or not self.state.get("pack_stats", {}).get("full_verify"):
            raise JobError(problem or "missing full verification from Forge")
        self.mark("verify", verify_stats={"full_verify": True, "engine": "Forge"},
                  pak_volumes=len(list(pack.glob("ampr_zstd-*.pak" if self.codec == "zstd" else "ampr_assets-*.pak"))),
                  runtime_sha256=NG_SHA256)
        self.log("verified: Forge read every output file back against the source; runtime SHA-256 matches")

    def source_size(self, root: Path) -> tuple[int, int]:
        """(files, bytes) of the game: the folder, or the .exfat's listing."""
        if root.is_file():
            return int(self.state.get("source_files") or 0), int(self.state.get("source_bytes") or root.stat().st_size)
        return tree_bytes(root)

    def step_restore(self, root: Path, pack: Path) -> None:
        if self.done("restore") or not self.restore_test:
            if not self.restore_test:
                self.state["restore_test"] = "skipped (--no-restore-test)"
            return
        if root.is_file():
            why = f"not needed: Forge compared every packed file with the {root.suffix} (blake3) while packing"
            self.mark("restore", restore_test=why)
            self.log(f"restore test {why}")
            return
        _files, total = tree_bytes(root)
        # Verify already decoded every packed file and compared it byte for byte
        # with the original. The restore test does it again through a full
        # unpack to disk: for a big game that is hours of disk thrash (writing
        # the whole game and reading it and the original back), so by default
        # it only runs for games up to PS5LZ4_RESTORE_TEST_MAX_GB.
        if RESTORE_TEST_MAX and total > RESTORE_TEST_MAX:
            why = (f"skipped for a {human(total)} game (over {human(RESTORE_TEST_MAX)}): Verify already "
                   "compared every packed file byte for byte with the original")
            for left in ("restore", "restore.out", "restore.err", "restore-compare.err"):
                remove_work_path(self.work / left)  # a restore test interrupted by an older version
            self.mark("restore", restore_test=why)
            self.log(f"restore test {why}")
            return
        self.set_step("restore")
        restore = self.work / "restore"
        remove_work_path(restore)
        self.need_space(total, "restore test")
        self.run_tool(forge_command(pack, restore, self.codec, self.level, unpack=True), "restore")
        expected_extra = {"ampr_emu.index", RUNTIME_REL}
        same = 0
        problems: list[str] = []
        notes: list[str] = []
        src_files: set[str] = set()
        # The unpack reports its own progress; the byte compare after it is as
        # long, so it writes the same kind of progress line for the web page.
        compare_err = self.work / "restore-compare.err"
        compared, last = 0, 0.0
        for dirpath, _dirs, names in os.walk(root):
            for name in names:
                sp = Path(dirpath) / name
                rel = sp.relative_to(root).as_posix()
                src_files.add(rel)
                rp = restore / rel
                if time.monotonic() - last > 2:
                    compare_err.write_text(f"[progress] {compared} / {total}\n")
                    last = time.monotonic()
                try:
                    compared += sp.stat().st_size
                except OSError:
                    pass
                if rel in expected_extra or rel.lower() == RUNTIME_REL.lower():
                    notes.append(f"{rel} replaced by the PackedStdio runtime"
                                 if rel.lower() == RUNTIME_REL.lower() else f"{rel} rebuilt")
                    continue
                if not rp.is_file():
                    problems.append(f"missing {rel}")
                elif sp.stat().st_size != rp.stat().st_size or not files_equal(sp, rp):
                    problems.append(f"differs {rel}")
                else:
                    same += 1
        for dirpath, _dirs, names in os.walk(restore):
            for name in names:
                rel = (Path(dirpath) / name).relative_to(restore).as_posix()
                if rel not in src_files and rel not in expected_extra:
                    problems.append(f"unexpected {rel}")
                elif rel in expected_extra and rel not in src_files:
                    notes.append(f"{rel} added")
        if problems:
            raise JobError(f"restore test failed ({len(problems)} problems): {problems[:5]}")
        remove_work_path(restore)
        remove_work_path(self.work / "restore.out")
        remove_work_path(self.work / "restore.err")
        remove_work_path(compare_err)
        self.mark("restore", restore_test=f"passed: {same} files byte-identical after unpack",
                  restore_notes=sorted(set(notes)))
        self.log(f"restore test passed: {same} files byte-identical; {', '.join(sorted(set(notes)))}")

    def step_publish(self, root: Path, pack: Path) -> dict:
        e = self.e
        if e.output.exists():
            raise JobError(f"{e.output} already exists; it is never overwritten")
        boot = boot_files(pack, repair=True)
        for line in boot["changed"] + boot["needed"] + boot["notes"]:
            self.log(f"boot files: {line}")
        programs = ps5_permissions(pack)
        os.rename(pack, e.output)
        out_files, out_bytes = tree_bytes(e.output)
        src_files, src_bytes = self.source_size(root)
        st = self.state
        report = {
            "id": e.id,
            "source": str(Path(HOST_LIBRARY) / e.rel),
            "source_kind": e.kind,
            "title_id": st.get("title_id"),
            "title_name": st.get("title_name"),
            "output": host_output_path(e.output),
            "finished": now(),
            "codec": f"Zstd level {self.level}" if self.codec == "zstd" else f"LZ4 level {self.level}",
            "pack_codec": self.codec,
            "pack_runtime": self.runtime,
            "workers": workers(),
            "profile": st.get("profile"),
            "ampr": st.get("ampr"),
            "image_bytes": st.get("image_bytes"),
            "source_files": src_files,
            "source_bytes": src_bytes,
            "output_files": out_files,
            "output_bytes": out_bytes,
            "saved_bytes": src_bytes - out_bytes,
            "saved_percent": round(100.0 * (src_bytes - out_bytes) / src_bytes, 2) if src_bytes else 0,
            "pack": st.get("pack_stats"),
            "pack_seconds": st.get("pack_seconds"),
            "verification": {
                "extraction": st.get("extraction", "none (folder used as is)"),
                "vhash": st.get("vhash", "n/a"),
                "listing_check": st.get("listing_check", "n/a"),
                "pack_byte_compare": "passed (ampr_pack_cli pack: every packed file compared, loose copies re-read)",
                "full_verify": "passed (ampr_pack_cli verify: manifest, CRC, every chunk decoded, byte compare)",
                "restore_test": st.get("restore_test"),
                "restore_notes": st.get("restore_notes", []),
                "format": f"AMPRPAK4 index, {st.get('pak_volumes')} AMPRDAT3 volumes",
                "runtime": f"{NG_NAME} {NG_SHA256}",
                "permissions": f"folders and {programs} program files 755, other files 644",
            },
            "verified_on_nas": True,
            "playable_on_ps5": "not tested: needs a console run (see README)",
        }
        if self.codec == "zstd":
            report["verification"].update(
                pack_byte_compare="passed (PS5 Dump Forge --full-verify)",
                full_verify="passed (every output file read back and compared by Forge)",
                format="AMPRZPK1 / AMPRZDT1", runtime=f"{NG_NAME} {NG_SHA256}")
        elif self.runtime == "ng":
            report["verification"].update(runtime=f"{NG_NAME} {NG_SHA256}")
        if any(boot.values()):
            report["boot_files"] = boot
        if report["image_bytes"]:
            ib = report["image_bytes"]
            report["saved_vs_image_percent"] = round(100.0 * (ib - out_bytes) / ib, 2)
        write_json(REPORTS / f"{e.id}.json", report)
        self.mark("publish", output=str(e.output))
        return report

    def run(self) -> dict:
        e = self.e
        self.work.mkdir(parents=True, exist_ok=True)
        self.state = read_json(self.state_path, {}) or {}
        old_options = (self.state.get("codec", "lz4"), self.state.get("runtime", "legacy"), self.state.get("level", self.level))
        if self.state.get("done") and old_options != (self.codec, self.runtime, self.level):
            raise JobError("unfinished job uses different compression settings; resume with its original options")
        self.state.update(codec=self.codec, runtime=self.runtime, level=self.level)
        self.state.setdefault("id", e.id)
        self.state.setdefault("source", e.rel)
        self.state.setdefault("started", now())
        self.state.pop("error", None)
        self.save()
        self.log(f"start {e.kind} {e.rel} ({self.codec.upper()} level {self.level}, {self.runtime} runtime, {workers()} workers)")
        if self.state.get("done"):
            self.log(f"resuming after: {', '.join(self.state['done'])}")
        root = self.step_source()
        self.step_check(root)
        pack = self.step_pack(root)
        self.step_verify(root, pack)
        self.step_restore(root, pack)
        report = self.step_publish(root, pack)
        # Success: the work folder (extraction, tool logs) is no longer needed.
        remove_work_path(self.work)
        self.log(f"DONE {human(report['source_bytes'])} -> {human(report['output_bytes'])} "
                 f"(saved {human(report['saved_bytes'])}, {report['saved_percent']}%) -> {report['output']}")
        return report


PROGRAM_EXTS = (".prx", ".sprx", ".elf", ".self")


def ps5_permissions(root: Path) -> int:
    """Modes the PS5 accepts: the game must read everything and execute its
    programs (APR-EMU in fakelib/ does not load without the execute bit).
    Folders and programs 755, everything else 644. Returns program count."""
    programs = 0
    for dirpath, dirs, names in os.walk(root):
        os.chmod(dirpath, 0o755)
        for name in names:
            p = os.path.join(dirpath, name)
            if os.path.islink(p):
                continue
            low = name.lower()
            if low == "eboot.bin" or low.endswith(PROGRAM_EXTS):
                os.chmod(p, 0o755)
                programs += 1
            else:
                os.chmod(p, 0o644)
    return programs


def files_equal(a: Path, b: Path, size: int = 8 << 20) -> bool:
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x = fa.read(size)
            y = fb.read(size)
            if x != y:
                return False
            if not x:
                return True


# --------------------------------------------------------------------------
# results bookkeeping

def result_for(entry: Entry) -> dict:
    rep = read_json(REPORTS / f"{entry.id}.json")
    requested_codec = getattr(entry, "pack_codec", None)
    if rep and (requested_codec is None or rep.get("pack_codec", "lz4") == requested_codec):
        return {"status": "done", "detail": f"saved {rep.get('saved_percent')}%"}
    skip = read_json(REPORTS / f"{entry.id}.skipped.json")
    if skip:
        return {"status": "skipped", "detail": skip.get("reason", "")}
    st = read_json(entry.work / "state.json")
    if st:
        if st.get("error") and not str(st.get("step", "")).endswith("(interrupted)"):
            return {"status": "failed", "detail": st["error"]}
        return {"status": "partial", "detail": f"after {', '.join(st.get('done', [])) or 'start'}"}
    if entry.output.exists():
        return {"status": "exists", "detail": "output folder exists without a report"}
    return {"status": "pending", "detail": ""}


def process_one(e: Entry, args) -> str:
    """Handle one library entry: 'ok', 'failed' or 'interrupted'."""
    e.pack_codec = getattr(args, "codec", "zstd")
    res = result_for(e)
    if res["status"] == "done":
        print(f"[{now()}] {e.id}: already done ({res['detail']}), skipping", flush=True)
        return "ok"
    if res["status"] == "exists":
        print(f"[{now()}] {e.id}: {e.output} exists without a report; not touching it", flush=True)
        return "failed"
    if e.duplicate_of and not args.force_image:
        print(f"[{now()}] {e.id}: skipped, the folder {e.duplicate_of} has the same game "
              "(use --force-image to pack the image)", flush=True)
        return "ok"
    job = Job(e, args.level, not args.no_restore_test, args.require_vhash,
              getattr(args, "codec", "zstd"), getattr(args, "runtime", "ng"),
              not getattr(args, "no_profile", False))
    try:
        job.run()
        (REPORTS / f"{e.id}.skipped.json").unlink(missing_ok=True)
        return "ok"
    except Skip as s:
        job.log(f"SKIPPED: {s}")
        write_json(REPORTS / f"{e.id}.skipped.json",
                   {"id": e.id, "source": e.rel, "reason": str(s), "when": now()})
        # Nothing useful in the work area of a skipped game.
        remove_work_path(e.work)
        return "ok"
    except (JobError, OSError, ValueError, RuntimeError) as err:
        job.state["error"] = str(err)
        job.state["failed"] = now()
        kind = "interrupted" if isinstance(err, Interrupted) else "failed"
        job.state["step"] = str(job.state.get("step", "")).replace(" (running)", "") + f" ({kind})"
        try:
            job.save()
        except OSError:
            pass
        if kind == "interrupted":
            job.log(f"INTERRUPTED: {err}")
            job.log(f"work kept; continue with: ps5lz4 start --resume")
        else:
            job.log(f"FAILED: {err}")
            job.log(f"work folder kept for troubleshooting: {e.work}")
        return kind


def process(entries: list[Entry], args) -> int:
    failures = 0
    queue = read_json(QUEUE_PATH, {}) if args.from_queue else None
    for e in entries:
        if _stop_requested:
            break
        if queue is not None:
            # The page can take a game out of the queue while another one packs.
            queue = read_json(QUEUE_PATH, {}) or queue
            if e.id not in queue.get("remaining", []):
                continue
            queue["current"] = e.id
            write_json(QUEUE_PATH, queue)
        outcome = process_one(e, args)
        failures += outcome != "ok"
        if queue is not None:
            queue = read_json(QUEUE_PATH, {}) or queue
            queue["current"] = None
            if outcome != "interrupted" and not _stop_requested:
                queue.setdefault("failed" if outcome == "failed" else "finished", []).append(e.id)
                queue["remaining"] = [x for x in queue.get("remaining", []) if x != e.id]
            write_json(QUEUE_PATH, queue)
        if outcome == "interrupted":
            break
    return 1 if failures else 0


# --------------------------------------------------------------------------
# commands

def ensure_dirs() -> None:
    for d in (STATE, LOGS, REPORTS):
        d.mkdir(parents=True, exist_ok=True)
    if OUTPUT.is_dir():
        WORK.mkdir(exist_ok=True)


def acquire_lock():
    fh = open(LOCK_PATH, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.seek(0)
        raise SystemExit(f"another job is running ({fh.read().strip()}); see: ps5lz4 status")
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()} since={now()}")
    fh.flush()
    return fh


def on_signal(signum, _frame):
    global _stop_requested
    _stop_requested = True
    if _child and _child.poll() is None:
        _child.terminate()


def cmd_run(args) -> int:
    ensure_dirs()
    entries = scan_library()
    if args.from_queue:
        q = read_json(QUEUE_PATH, {}) or {}
        ids = q.get("remaining", [])
        targets = [e for e in entries if e.id in ids]
    elif args.all:
        for e in entries:
            e.pack_codec = getattr(args, "codec", "zstd")
        targets = [e for e in entries if result_for(e)["status"] in ("pending", "partial", "failed")]
    else:
        if not args.targets:
            raise SystemExit("name at least one game, or --all (see: ps5lz4 scan)")
        targets = resolve_targets(args.targets, entries)
    if not targets:
        print("nothing to do")
        return 0
    lock = acquire_lock()
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        return process(targets, args)
    finally:
        lock.close()


def cmd_start(args) -> int:
    """Queue games and run them in the background with nohup."""
    ensure_dirs()
    entries = scan_library()
    if args.resume:
        q = read_json(QUEUE_PATH, {}) or {}
        if not q.get("remaining"):
            raise SystemExit("no unfinished queue to resume")
    else:
        if args.all:
            for e in entries:
                e.pack_codec = getattr(args, "codec", "zstd")
            targets = [e for e in entries if result_for(e)["status"] in ("pending", "partial", "failed")]
        else:
            if not args.targets:
                raise SystemExit("name at least one game, or --all (see: ps5lz4 scan)")
            targets = resolve_targets(args.targets, entries)
        q = {"created": now(), "remaining": [e.id for e in targets], "finished": [], "failed": [],
             "current": None, "options": {"level": args.level,
                                          "codec": getattr(args, "codec", "zstd"),
                                          "runtime": getattr(args, "runtime", "ng"),
                                          "no_restore_test": args.no_restore_test,
                                          "require_vhash": args.require_vhash,
                                          "force_image": args.force_image,
                                          "no_profile": getattr(args, "no_profile", False)}}
    # Refuse early if a job holds the lock.
    try:
        with open(LOCK_PATH, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh, fcntl.LOCK_UN)
    except OSError:
        raise SystemExit("a job is already running; see: ps5lz4 status")
    write_json(QUEUE_PATH, q)
    opts = q.get("options", {})
    log = LOGS / f"queue-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    argv = ["nohup", sys.executable, os.path.abspath(__file__), "run", "--from-queue",
            "--level", str(opts.get("level", 9)), "--codec", opts.get("codec", "zstd"),
            "--runtime", opts.get("runtime", "ng")]
    for flag in ("no_restore_test", "require_vhash", "force_image", "no_profile"):
        if opts.get(flag):
            argv.append("--" + flag.replace("_", "-"))
    with open(log, "a") as out:
        proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    print(f"started in the background (pid {proc.pid}): {len(q['remaining'])} game(s)")
    print(f"  queue: {', '.join(q['remaining'])}")
    print(f"  log:   {log}")
    print("  watch: ps5lz4 status   |   stop: ps5lz4 stop   |   continue later: ps5lz4 start --resume")
    return 0


def cmd_stop(_args) -> int:
    try:
        text = LOCK_PATH.read_text()
    except OSError:
        text = ""
    m = re.search(r"pid=(\d+)", text)
    with open(LOCK_PATH, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print("no job is running")
            return 0
        except OSError:
            pass
    if not m:
        raise SystemExit("a job is running but its pid is unknown")
    os.kill(int(m.group(1)), signal.SIGTERM)
    print(f"asked job pid {m.group(1)} to stop; its work is kept, continue with: ps5lz4 start --resume")
    return 0


def cmd_scan(args) -> int:
    ensure_dirs()
    entries = scan_library()
    if not entries:
        print(f"no games found in {LIBRARY}")
        return 0
    print(f"{'#':>3}  {'kind':6}  {'size':>10}  {'title':9}  {'status':8}  game")
    for i, e in enumerate(entries, 1):
        res = result_for(e)
        status = res["status"]
        extra = ""
        if args.check and status == "pending":
            try:
                if e.kind == "folder":
                    s, reason = ampr_status_folder(e.path)
                elif e.kind == "exfat":
                    meta = exfat_inspect(e.path)
                    e.title_id = meta["title_id"] or e.title_id
                    s, reason = meta["status"], meta["reason"]
                else:
                    s, reason = "unknown", "checked after extraction"
                extra = f"  [{s}: {reason}]"
            except Exception as err:  # report, don't stop the listing
                extra = f"  [check failed: {err}]"
        if e.duplicate_of:
            extra += f"  (same game as folder {e.duplicate_of})"
        if res["detail"] and status != "pending":
            extra += f"  ({res['detail']})"
        print(f"{i:>3}  {e.kind:6}  {human(e.size()):>10}  {e.title_id or '-':9}  {status:8}  {e.rel}{extra}")
    return 0


def packed_codec(game: Path) -> str:
    return "zstd" if (game / "ampr_zstd.index").is_file() else "lz4"


def packed_index(game: Path) -> Path:
    return game / ("ampr_zstd.index" if packed_codec(game) == "zstd" else "ampr_assets.index")


def is_packed(game: Path) -> bool:
    return packed_index(game).is_file()


_rt_sha: dict = {}


def runtime_sha(game: Path) -> str:
    """SHA-256 of a copy's runtime, cached by path, size and time: the page asks
    for it every few seconds for every copy."""
    rt = find_runtime(game)
    if not rt:
        return ""
    try:
        st = rt.stat()
    except OSError:
        return ""
    key = (str(rt), st.st_size, st.st_mtime_ns)
    if key not in _rt_sha:
        if len(_rt_sha) > 2000:
            _rt_sha.clear()
        _rt_sha[key] = hashlib.sha256(rt.read_bytes()).hexdigest()
    return _rt_sha[key]


def runtime_name(sha: str) -> str:
    return NG_NAME if sha == NG_SHA256 else "ampr-emu-ng 0.3.0" if sha == NG_UPSTREAM_SHA256 else RUNTIME_NAME if sha == RUNTIME_SHA256 else f"unknown runtime ({sha[:12]})"


def requires_ng(game: Path) -> bool:
    rep = read_json(REPORTS / (re.sub(r"-(lz4|zstd)$", "", game.name) + ".json"), {}) or {}
    # A game's report describes its last pack only: it counts for this copy only if it is this copy.
    try:
        mine = rep.get("output") in (None, host_output_path(game))
    except ValueError:  # a pack still in the work folder: no report describes it yet
        mine = False
    if packed_codec(game) == "zstd" or (mine and rep.get("pack_runtime") == "ng"):
        return True
    # Any runtime but the pinned APR-EMU build is an ampr-emu-ng build, older ones
    # included: those copies get the image's newer build on repair.
    sha = runtime_sha(game)
    return bool(sha) and sha != RUNTIME_SHA256


def runtime_ok(game: Path, sha: str) -> bool:
    return sha in (NG_SHA256, NG_UPSTREAM_SHA256) if requires_ng(game) else sha in (NG_SHA256, NG_UPSTREAM_SHA256, RUNTIME_SHA256)


def update_runtime_index(root: Path, runtime: Path) -> None:
    """Change only the loose runtime record; retain all packed-file records/hash slots."""
    index = root / "ampr_emu.index"
    buf = bytearray(index.read_bytes())
    if len(buf) < 48 or buf[:8] != b"AMPRIDX3" or struct.unpack_from("<II", buf, 8) != (3, 24):
        raise JobError("unsupported AMPR runtime index")
    count, path_bytes = struct.unpack_from("<QQ", buf, 16)
    blob = 48 + count * 24
    if blob > len(buf) or path_bytes > len(buf) - blob:
        raise JobError("truncated AMPR runtime index")
    target = ("/app0/" + runtime.relative_to(root).as_posix()).encode()
    found = 0
    for i in range(count):
        record = 48 + i * 24
        off, length = struct.unpack_from("<II", buf, record)
        if off + length >= path_bytes or buf[blob + off + length] != 0:
            raise JobError("invalid AMPR index path")
        if bytes(buf[blob + off:blob + off + length]) == target:
            st = runtime.stat()
            struct.pack_into("<Qq", buf, record + 8, st.st_size, int(st.st_mtime))
            found += 1
    if found != 1:
        raise JobError("AMPR index must contain exactly one runtime record")
    temp = index.with_suffix(".tmp")
    temp.write_bytes(buf)
    os.replace(temp, index)


def install_ng_runtime(root: Path) -> None:
    if runtime_sha(root) == NG_SHA256:
        return
    if not NG_FILE.is_file() or hashlib.sha256(NG_FILE.read_bytes()).hexdigest() != NG_SHA256:
        raise JobError("built ampr-emu-ng runtime is missing or corrupt")
    runtime = find_runtime(root) or root / RUNTIME_REL
    runtime.parent.mkdir(parents=True, exist_ok=True)
    temporary = runtime.with_suffix(".tmp")
    shutil.copyfile(NG_FILE, temporary)
    temporary.chmod(0o755)
    os.replace(temporary, runtime)
    update_runtime_index(root, runtime)


def compare_game_files(source: Path, decoded: Path) -> list[str]:
    generated = {"ampr_emu.index", RUNTIME_REL, "ampr_commands.bin", "ampr_emu.log", "apr_emu.log"}
    expected = {p.relative_to(source).as_posix(): p for p in source.rglob("*") if p.is_file()}
    actual = {p.relative_to(decoded).as_posix(): p for p in decoded.rglob("*") if p.is_file()}
    problems = []
    for name in expected.keys() | actual.keys():
        if name in generated:
            continue
        if name not in expected or name not in actual or not files_equal(expected[name], actual[name]):
            problems.append(name)
    return problems


def forge_command(source: Path, output: Path, codec: str, level: int, unpack: bool = False) -> list[str]:
    if codec not in ("lz4", "zstd") or not 1 <= level <= (22 if codec == "zstd" else 12):
        raise JobError("invalid compression codec or level")
    argv = [FORGE, "convert", str(source), "--to", "folder", "-o", str(output), "--full-verify", "--threads", str(workers())]
    if unpack:
        return argv + ["--zstd-unpack" if codec == "zstd" else "--lz4-unpack"]
    if codec != "zstd":
        raise JobError("only Zstd packing is supported")
    if codec == "zstd":
        return argv + ["--zstd-pack", "--zstd-level", str(level)]
    return argv + ["--lz4-pack", "--lz4-runtime", "ng", "--lz4-level", str(level if level >= 5 else 0)]


def lz4_format_problem(game: Path) -> str | None:
    """None when the folder is a complete supported AMPR packed game."""
    zstd = packed_codec(game) == "zstd"
    index = packed_index(game)
    if not index.is_file():
        return "no AMPR pack index"
    with open(index, "rb") as f:
        magic = f.read(8)
    expected = b"AMPRZPK1" if zstd else b"AMPRPAK4"
    if magic != expected:
        return f"{index.name} has magic {magic!r}, expected {expected!r}"
    paks = sorted(game.glob("ampr_zstd-*.pak" if zstd else "ampr_assets-*.pak"))
    if not paks:
        return "no .pak volumes"
    for p in paks:
        with open(p, "rb") as f:
            if f.read(8) != (b"AMPRZDT1" if zstd else b"AMPRDAT3"):
                return f"{p.name} has the wrong pack volume format"
    runtime = find_runtime(game)
    if runtime is None:
        return f"{RUNTIME_REL} missing"
    sha = hashlib.sha256(runtime.read_bytes()).hexdigest()
    if not runtime_ok(game, sha):
        return f"{RUNTIME_REL} is not a supported {'ampr-emu-ng' if zstd else 'LZ4'} runtime ({sha[:12]})"
    # ampr_assets.index.runtime is optional: profiles without a [runtime]
    # section (e.g. Insomniac) leave APR-EMU on its default cache settings.
    for side in (("ampr_emu.index",) if zstd else ("ampr_assets.index.crc", "ampr_emu.index")):
        if not (game / side).is_file():
            return f"{side} missing"
    return None


CHECKS_PATH = STATE / "checks.json"  # before the database; migrated once
DB_PATH = STATE / "ps5lz4.db"


class CheckDB(dict):
    """Results of earlier checks (SQLite in state/ps5lz4.db), keyed by what was
    checked and valid while its signature (sizes, mtimes) is unchanged. Works
    like a dict; save() writes the entries that changed."""

    def __init__(self):
        super().__init__()
        import sqlite3
        self._dirty = set()
        self._db = sqlite3.connect(DB_PATH, timeout=30)
        self._db.execute("CREATE TABLE IF NOT EXISTS checks (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
                         "checked TEXT NOT NULL)")
        for key, value in self._db.execute("SELECT key, value FROM checks"):
            try:
                dict.__setitem__(self, key, json.loads(value))
            except ValueError:
                pass
        if not self and CHECKS_PATH.is_file():
            for key, value in (read_json(CHECKS_PATH, {}) or {}).items():
                self[key] = value
            self.save()

    def __setitem__(self, key, value):
        if isinstance(value, dict):
            value.setdefault("checked", now())
        dict.__setitem__(self, key, value)
        self._dirty.add(key)

    def save(self):
        if self._dirty:
            with self._db:
                self._db.executemany("INSERT OR REPLACE INTO checks (key, value, checked) VALUES (?, ?, ?)",
                                     [(k, json.dumps(self[k]), now()) for k in self._dirty if k in self])
            self._dirty.clear()

    def close(self):
        self.save()
        self._db.close()


def file_sig(*paths: Path) -> str:
    parts = []
    for p in paths:
        try:
            st = p.stat()
            parts.append(f"{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            parts.append("-")
    return "|".join(parts)


def stale_skip(reason: str) -> bool:
    """A skip from the APR-EMU days (no libSceAmpr import, or a Glacier title):
    Forge injects ampr-emu-ng into any game, so it no longer stops a pack."""
    return "libSceAmpr" in (reason or "") or "APR-EMU would never load" in (reason or "") or "Glacier" in (reason or "")


def classify(e: "Entry", res: dict, cache: dict | None = None) -> tuple[str, str, bool]:
    """(verdict, why, can_queue) for one library entry. verdict is one of
    LZ4 / can be LZ4 / not LZ4 / error. AMPR checks of unpacked games are
    cached by path, size and mtime (reading eboot.bin from a 100 GB image
    takes a moment)."""
    st = res["status"]
    if st == "done":
        problem = lz4_format_problem(e.output) if e.output.is_dir() else "output folder missing"
        return ("LZ4", res["detail"], False) if not problem else ("error", problem, False)
    if st == "skipped" and not stale_skip(res["detail"]):
        return "not LZ4", res["detail"], False
    if st == "exists":
        return "error", res["detail"], False
    key = sig = None
    if cache is not None:
        try:
            stt = e.path.stat()
            key, sig = str(e.path), f"g1:{stt.st_size}:{int(stt.st_mtime)}"  # g1: with the Glacier check
        except OSError:
            pass
    hit = cache.get(key) if key else None
    if hit and hit.get("sig") == sig:
        ok, why = hit["ok"], hit["why"]
    else:
        try:
            if e.kind == "folder":
                ok, why = ampr_status_folder(e.path)
            elif e.kind == "exfat":
                meta = exfat_inspect(e.path)
                ok, why = meta["status"], meta["reason"]
            elif e.kind == "pkg":
                ok, why = "compatible", "PS5 game package: Forge packs it directly"
            else:
                ok, why = "compatible", "checked after extraction"
        except Exception as err:
            ok, why = "compatible", f"checked when packed ({err})"
        if key:
            cache[key] = {"sig": sig, "ok": ok, "why": why}
    if ok == "incompatible":
        # Forge injects ampr-emu-ng into any title: importing libSceAmpr is not needed.
        ok, why = "compatible", "packs with ampr-emu-ng (injected by PS5 Dump Forge)"
    if ok == "compatible":
        if st in ("partial", "failed"):
            why = f"{st}: {res['detail']}"
        elif e.kind == "ffpfsc":
            why = "already compressed (.ffpfsc): a packed copy is usually about as large or larger"
        return "can be LZ4", why, True
    if ok == "packed":
        return "LZ4", why, False
    return "not LZ4", why, False


def cmd_lz4(args) -> int:
    """One line per game: LZ4 already, can become LZ4, or why not. --fix queues the rest."""
    ensure_dirs()
    entries = scan_library()
    todo: list[Entry] = []
    compressed: list[Entry] = []  # .ffpfsc: already PFSC-compressed, little or nothing to gain
    games = ng_reports()
    counts = {"LZ4": 0, "can be LZ4": 0, "not LZ4": 0, "error": 0}
    codec, runtime = getattr(args, "codec", "zstd"), getattr(args, "runtime", "ng")
    packable: list[Entry] = []  # AMPR games (LZ4 copy or not): what Zstd and LZ4 NG are made from
    # Saved results for unchanged sources; --full scans every one again and
    # stores the new results.
    cache = CheckDB()
    if getattr(args, "full", False):
        for k in [k for k in cache if k.startswith("/")]:
            del cache[k]
    for e in entries:
        res = result_for(e)
        st = res["status"]
        if e.duplicate_of and st != "done":
            continue  # the folder copy of the same game is listed instead
        verdict, why, can = classify(e, res, cache)
        if verdict in ("LZ4", "can be LZ4"):
            packable.append(e)
        if can and e.kind == "ffpfsc" and res["status"] not in ("partial", "failed") \
                and not getattr(args, "include_compressed", False):
            compressed.append(e)
        elif can:
            todo.append(e)
        counts[verdict] += 1
        print(f"{verdict:12} {e.title_id or '-':9}  {e.rel}  ({why})")
        c = ngr_text(games.get((e.title_id or "").upper()))
        if c:
            print(f"{'':12} {'':9}  {c}")
    for out in output_items():
        if out.is_dir() and is_packed(out) and not any(e.output == out for e in entries):
            problem = lz4_format_problem(out)
            counts["LZ4" if not problem else "error"] += 1
            print(f"{'LZ4' if not problem else 'error':12} {'-':9}  {out.name}  "
                  f"({'no library source' if not problem else problem})")
    cache.close()
    if codec == "zstd" or runtime == "ng":
        # Compress all in Zstd or LZ4 NG: every AMPR original without a copy in
        # that format yet, always packed from the original (never from an LZ4 copy).
        suffix = "-zstd" if codec == "zstd" else "-lz4"
        todo = [e for e in packable if not output_item(e.id + suffix).is_dir()
                and (e.kind != "ffpfsc" or getattr(args, "include_compressed", False))]
        compressed = [e for e in packable if e.kind == "ffpfsc" and not getattr(args, "include_compressed", False)
                      and not output_item(e.id + suffix).is_dir()]
    print("\n" + ", ".join(f"{k}: {v}" for k, v in counts.items()))
    if compressed:
        print(f"{len(compressed)} already-compressed .ffpfsc image(s) left out (an LZ4 copy is usually as large or "
              f"larger); pack one with: ps5lz4 start <game>, or all with: lz4 --fix --include-compressed")
    if not todo:
        print("nothing left to pack")
        return 1 if counts["error"] else 0
    if not args.fix:
        print(f"pack the {len(todo)} that can be LZ4: ps5lz4 lz4 --fix")
        return 0
    start = argparse.Namespace(targets=[e.id for e in todo], all=False, resume=False,
                               level=args.level, no_restore_test=args.no_restore_test,
                               require_vhash=args.require_vhash, force_image=args.force_image,
                               codec=codec, runtime=runtime, no_profile=getattr(args, "no_profile", False))
    return cmd_start(start)


def cmd_status(_args) -> int:
    ensure_dirs()
    running = False
    with open(LOCK_PATH, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            running = True
    lock_text = LOCK_PATH.read_text().strip() if LOCK_PATH.exists() else ""
    print(f"job: {'RUNNING (' + lock_text + ')' if running else 'idle'}")
    q = read_json(QUEUE_PATH)
    if q:
        print(f"queue: current={q.get('current') or '-'} remaining={q.get('remaining')} "
              f"finished={q.get('finished')} failed={q.get('failed', [])}")
    print(f"free on output volume: {human(free_bytes(OUTPUT))}")
    if WORK.is_dir():
        for w in sorted(WORK.iterdir()):
            st = read_json(w / "state.json", {}) or {}
            step = str(st.get("step", "?"))
            if not running and step.endswith("(running)"):
                step = step.replace("(running)", "(interrupted; continue with: start --resume)")
            line = f"  work/{w.name}: step={step} done={st.get('done', [])}"
            if st.get("error"):
                line += f"\n      error: {st['error']}"
            print(line)
            if running and "running" in str(st.get("step", "")):
                for errf in sorted(w.glob("*.err")):
                    tail = errf.read_text(errors="replace").replace("\r", "\n").strip().splitlines()
                    if tail:
                        print(f"      {errf.stem}: {tail[-1][:160]}")
    return 0


def ps5_result(eid: str) -> str | None:
    """What the user saw on the PS5 for this game: from its LZ4 report, else from state/played."""
    return ((read_json(REPORTS / f"{eid}.json") or {}).get("ps5_result")
            or (read_json(PLAYED / f"{eid}.json") or {}).get("result"))


# quer3q's game reports: issues labelled "test report" on quer3q/ampr-emu-ng
# (its game-report.yml form). They cover LZ4 NG and Zstd, the formats this
# NAS packs for ampr-emu-ng.
NG_REPORT_REPO = "quer3q/ampr-emu-ng"
NG_REPORT_WEB = f"https://github.com/{NG_REPORT_REPO}"
NG_REPORTS = STATE / "ng-reports.json"
NG_REPORTS_ON = os.environ.get("PS5LZ4_NG_REPORTS", "yes") != "no"
NG_REPORTS_REFRESH = int(os.environ.get("PS5LZ4_NG_REPORTS_REFRESH", "10800"))
NG_RESULTS = [  # start of the form's Result answer -> (our key, its full text)
    ("works", "works", "Works (played past the first level load)"),
    ("fails at launch", "noStart", 'Fails at launch ("Something went wrong" or similar)'),
    ("crashes", "crash", "Crashes later"),
    ("hangs", "hang", "Hangs (loading screen or black screen)"),
    ("runs, but", "issues", "Runs, but slow or stutters"),
]
NG_FORM_RESULT = {"works": NG_RESULTS[0][2], "issues": NG_RESULTS[4][2], "nostart": NG_RESULTS[1][2],
                  "crash": NG_RESULTS[2][2]}


def ng_form_sections(body: str) -> dict:
    """An issue form's body ("### Label\n\nanswer") as {label lower-cased: answer}."""
    out = {}
    for part in re.split(r"^###\s+", body or "", flags=re.M)[1:]:
        label, _, answer = part.partition("\n")
        answer = answer.strip()
        out[label.strip().lower()] = "" if answer == "_No response_" else answer
    return out


NG_TABLE_ROW = re.compile(r"^\|\s*\**((?:PPSA|CUSA|PPSM)\d{5})\**\s*\|\s*([^|\n]+?)\s*\|", re.I | re.M)


def ng_reports_aggregate(issues: list[dict]) -> dict:
    """quer3q's report issues -> {"games": {TITLEID: {"name", "zstd": counts, "lz4": counts,
    "plain": counts, "latest": {...}}}}. An issue is one report for the game in its
    title or Game field; one that lists several games in a table (no Title ID in the
    title) counts once for each row. Pull requests and issues without a Title ID
    are left out."""
    games = {}
    for issue in sorted(issues, key=lambda i: i.get("created_at") or ""):
        if issue.get("pull_request"):
            continue
        labels = {(lb.get("name") or "").lower() for lb in issue.get("labels") or []}
        if labels & {"invalid", "duplicate", "spam"}:
            continue
        body = issue.get("body") or ""
        f = ng_form_sections(body)
        game = f.get("game, title id and game version", "")
        m = TITLE_RE.search(issue.get("title") or "") or TITLE_RE.search(game)
        if m:
            name = re.sub(r"\s+", " ", TITLE_RE.sub("", game).split(",")[0]).strip(" ,:-[]")[:60]
            found = [(m.group(0).upper(), name)]
        else:
            found = list({t.upper(): (t.upper(), re.sub(r"\s+", " ", n).strip("* ")[:60])
                          for t, n in NG_TABLE_ROW.findall(body)}.values())
        answer = (f.get("result") or "").lower()
        key = next((k for start, k, _ in NG_RESULTS if answer.startswith(start)), "works" if "works" in labels else "other")
        packs = (f.get("packs") or "").lower()
        packs = "zstd" if packs.startswith("zstd") else "lz4" if packs.startswith("lz4") else "plain" if packs.startswith("plain") else "other"
        for tid, name in found:
            g = games.setdefault(tid, {"name": ""})
            c = g.setdefault(packs, {"works": 0, "issues": 0, "noStart": 0, "crash": 0, "hang": 0, "other": 0, "reports": 0})
            c[key] += 1
            c["reports"] += 1
            g["name"] = name or g["name"]
            g["reports"] = g.get("reports", 0) + 1
            g["latest"] = {"issue": issue.get("number"), "result": key, "packs": packs,
                           "version": re.sub(r"\s+", " ", f.get("ampr-emu-ng version", ""))[:24],
                           "date": (issue.get("created_at") or "")[:10], "open": issue.get("state") == "open"}
    return {"updated": now(), "repo": NG_REPORT_REPO, "games": games}


def ng_reports() -> dict:
    return ((read_json(NG_REPORTS, {}) or {}).get("games") or {}) if NG_REPORTS_ON else {}


def ng_reports_refresh() -> dict:
    """Fetch quer3q's report issues (GitHub REST, no token) and save the counts."""
    import urllib.request
    issues = []
    for page in range(1, 11):
        url = (f"https://api.github.com/repos/{NG_REPORT_REPO}/issues?labels=test%20report&state=all"
               f"&per_page=100&page={page}")
        req = urllib.request.Request(url, headers={"User-Agent": f"ps5-lz4/{VERSION}",
                                                   "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            batch = json.load(r)
        issues += batch
        if len(batch) < 100:
            break
    data = ng_reports_aggregate(issues)
    write_json(NG_REPORTS, data)
    return data


def ng_reports_refresher() -> None:
    while True:
        try:
            ng_reports_refresh()
        except Exception as err:
            print(f"[{now()}] quer3q reports not refreshed: {err}", flush=True)
        time.sleep(max(NG_REPORTS_REFRESH, 900))


def ng_report_url(tid: str, name: str, result: str, packs: str, game_ver: str = "", firmware: str = "") -> str:
    """A new game report on quer3q/ampr-emu-ng, its form filled in (GitHub fills
    issue-form fields from query parameters named after the field ids)."""
    from urllib.parse import urlencode
    ver = (re.search(r"\(v([\d.]+)\)", NG_NAME) or [None, ""])[1]
    answer = NG_FORM_RESULT[result]
    setup = (f"Firmware: {firmware}\nLoader (e.g. ShadowMountPlus x.y), fakelib updates off: yes/no\n"
             f"Packer (e.g. ps5-dump-forge x.y): "
             + f"ps5-dump-forge {forge_pin_version()}"
             + f" via ps5lz4zstd NAS {VERSION}\nInstall: folder / ffpkg / pkg\n"
               "Storage: internal SSD / extended M.2 / USB exFAT")
    q = {"template": "game-report.yml", "title": f"[{tid}] {name}: {answer.split(' (')[0]}",
         "game": ", ".join(x for x in (name, tid, game_ver) if x), "version": f"v{ver}" if ver else "",
         "build": "release (libSceAmpr.sprx)", "packs": packs, "result": answer, "setup": setup}
    return f"{NG_REPORT_WEB}/issues/new?" + urlencode(q)


# Submitting a game report from the page: a GitHub token the owner adds on the
# Remote tab (a classic token with the public_repo scope), kept in state with
# mode 0600 and never sent back to the page. Only the web page container posts.
GITHUB_TOKEN_PATH = STATE / "github-token"
NG_SUBMITTED = STATE / "ng-submitted.json"  # game id -> issues opened from here
NG_INSTALLS = ("folder", "ffpkg", "pkg")
NG_STORAGE = ("internal SSD", "extended M.2", "USB exFAT")


def github_token() -> str:
    env = os.environ.get("PS5LZ4_GITHUB_TOKEN", "").strip()
    if env:
        return env
    try:
        return GITHUB_TOKEN_PATH.read_text().strip()
    except OSError:
        return ""


def set_github_token(token: str) -> dict:
    token = (token or "").strip()
    if not token:
        GITHUB_TOKEN_PATH.unlink(missing_ok=True)
        return {"github_token": ""}
    if not re.fullmatch(r"(ghp_|github_pat_)[A-Za-z0-9_]{20,250}", token):
        raise ValueError("that does not look like a GitHub token (ghp_… or github_pat_…)")
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = GITHUB_TOKEN_PATH.with_suffix(".tmp")
    tmp.write_text(token + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, GITHUB_TOKEN_PATH)
    return {"github_token": "set"}


def ng_report_issue(game_id: str, fields: dict) -> dict:
    """Title and body of a game report in quer3q's game-report.yml layout
    ("### Label" sections, the same the page reads back), for one packed copy."""
    rep = read_json(REPORTS / f"{safe_name(game_id)}.json") or {}
    if not rep:
        raise ValueError("this game has no packed copy made here")
    packs = str(fields.get("packs") or ("zstd" if rep.get("pack_codec") == "zstd" else "lz4"))
    if packs not in ("zstd", "lz4"):
        raise ValueError("packs must be zstd or lz4")
    result = str(fields.get("result") or "")
    if result not in NG_FORM_RESULT and result not in [full for _s, _k, full in NG_RESULTS] + ["Other"]:
        raise ValueError("choose a result")
    answer = NG_FORM_RESULT.get(result, result)
    what = str(fields.get("what") or "").strip()
    if len(what) < 10:
        raise ValueError("say in a sentence or two what happened")
    tid = (rep.get("title_id") or "").upper() or "PPSA?????"
    name = re.sub(r"\s+", " ", str(rep.get("title_name") or game_id))[:60]
    clean = lambda v, n=200: re.sub(r"[\r\n]+", " ", str(v or "")).strip()[:n]
    install = clean(fields.get("install")) if fields.get("install") in NG_INSTALLS else "folder"
    storage = clean(fields.get("storage")) if fields.get("storage") in NG_STORAGE else ""
    game_ver = clean(fields.get("game_version"), 20) or str((rep.get("version") or ""))
    ver = (re.search(r"\(v([\d.]+)\)", NG_NAME) or [None, ""])[1]
    setup = "\n".join([f"Firmware: {clean(fields.get('firmware'), 20)}",
                       f"Loader: {clean(fields.get('loader')) or '-'}",
                       f"Packer: ps5-dump-forge {forge_pin_version()} via ps5lz4zstd NAS {VERSION}"
                       + (f" ({rep['codec']})" if rep.get("codec") else ""),
                       f"Install: {install}", f"Storage: {storage or '-'}"])
    sections = [("Game, title ID and game version", ", ".join(x for x in (name, tid, game_ver) if x)),
                ("ampr-emu-ng version", f"v{ver}" if ver else NG_NAME),
                ("Build", "release (libSceAmpr.sprx)"), ("Packs", packs), ("Result", answer),
                ("Setup", setup), ("What happened", what[:6000]),
                ("Logs", "_No response_")]
    body = "\n\n".join(f"### {k}\n\n{v or '_No response_'}" for k, v in sections)
    body += "\n\n<sub>Sent from ps5lz4zstd on the owner's NAS.</sub>"
    return {"title": f"[{tid}] {name}: {answer.split(' (')[0]}", "body": body, "packs": packs, "result": answer}


def ng_report_submit(game_id: str, fields: dict, dry: bool = False) -> dict:
    """Open the game report as an issue on quer3q/ampr-emu-ng with the owner's token.
    The same result for the same game is not sent twice within a day."""
    import urllib.error
    import urllib.request
    issue = ng_report_issue(game_id, fields)
    if dry:
        return {**issue, "dry": True}
    token = github_token()
    if not token:
        raise ValueError("add a GitHub token on the Remote tab first (or use Open on GitHub)")
    sent = read_json(NG_SUBMITTED, {}) or {}
    for old in sent.get(game_id, []):
        if old.get("result") == issue["result"] and old.get("packs") == issue["packs"] \
                and time.time() - old.get("ts", 0) < 86400 and not fields.get("again"):
            raise ValueError(f"already sent today: {old.get('url')}")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{NG_REPORT_REPO}/issues", method="POST",
        data=json.dumps({"title": issue["title"], "body": issue["body"], "labels": ["test report"]}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": f"ps5-lz4/{VERSION}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.load(r)
    except urllib.error.HTTPError as err:
        why = {401: "the GitHub token is wrong or expired", 403: "the token may not open issues (it needs the public_repo scope)",
               404: "the token may not open issues (it needs the public_repo scope)", 410: "issues are turned off on that repository",
               422: "GitHub refused the report"}.get(err.code, f"GitHub answered HTTP {err.code}")
        raise ValueError(why)
    except OSError as err:
        raise ValueError(f"GitHub could not be reached: {err}")
    entry = {"number": j.get("number"), "url": j.get("html_url"), "result": issue["result"],
             "packs": issue["packs"], "at": now(), "ts": time.time()}
    sent.setdefault(game_id, []).append(entry)
    write_json(NG_SUBMITTED, sent)
    print(f"[{now()}] game report #{entry['number']} opened for {game_id}", flush=True)
    return entry


def forge_pin_version() -> str:
    """The Forge version in this image (its SOURCE.txt), or the pin in a checkout."""
    here = Path(__file__).parent
    for path, pat in ((here / "licenses" / "ps5-dump-forge" / "SOURCE.txt", r"PS5 Dump Forge v([\d.]+)"),
                      (here / "install-forge.py", r"^VERSION = '([^']+)'")):
        try:
            return re.search(pat, path.read_text(), re.M).group(1)
        except (OSError, AttributeError):
            continue
    return ""


def tested_ok(eid: str) -> bool:
    return ps5_result(eid) in ("works", "issues")


def ps5_text(rep: dict) -> str:
    st = rep.get("ps5_result")
    return f"PS5 {PLAY_STATES[st][1]}" if st in PLAY_STATES else "PS5 untested"


def ngr_text(g: dict | None) -> str:
    """'quer3q: zstd 2 work, lz4 1 crash' for a game's ampr-emu-ng reports, or ''."""
    parts = []
    for kind in ("zstd", "lz4", "plain", "other"):
        c = (g or {}).get(kind)
        if c:
            parts.append(f"{kind} " + ", ".join(f"{c[k]} {k}" for k in ("works", "issues", "noStart", "crash", "hang", "other") if c.get(k)))
    return "quer3q: " + "; ".join(parts) if parts else ""


def cmd_community(args) -> int:
    """Community reports for the library, or record and share your own result."""
    ensure_dirs()
    games = ng_reports()
    if not args.game:
        print(f"game reports from {NG_REPORT_REPO}")
        seen = set()
        for e in scan_library():
            tid = (e.title_id or "").upper()
            if not tid or tid in seen:
                continue
            seen.add(tid)
            rep = read_json(REPORTS / f"{e.id}.json") or {}
            mine = ps5_text(rep) if rep else "not LZ4"
            print(f"{tid:9}  {e.rel[:44]:44}  you: {mine:22}  {ngr_text(games.get(tid)) or 'no reports yet'}")
        print("\nrecord your result: ps5lz4 community <game> works|issues|nostart|crash")
        return 0
    if args.result not in PLAY_STATES:
        raise SystemExit("result must be one of: " + ", ".join(PLAY_STATES))
    e = resolve_targets([args.game], scan_library())[0]
    rep_path = REPORTS / f"{e.id}.json"
    rep = read_json(rep_path)
    form, label = PLAY_STATES[args.result]
    if not rep:
        # Not LZ4 (an original or an extracted RAR game): keep the result here, nothing to share.
        PLAYED.mkdir(parents=True, exist_ok=True)
        write_json(PLAYED / f"{e.id}.json", {"result": args.result, "at": now(), "rel": e.rel})
        print(f"saved: {e.id}: PS5 {label}")
        return 0
    rep["ps5_result"] = args.result
    rep["playable_on_ps5"] = f"{label} (reported {now()})"
    write_json(rep_path, rep)
    print(f"saved: {e.id}: PS5 {label}")
    source = {"folder": "Folder", "exfat": "exFAT image", "ffpfsc": "Uncompressed .ffpfsc"}.get(e.kind, "")
    name = (rep.get("title_name") or e.id)[:60]
    if rep.get("pack_codec") == "zstd" or rep.get("pack_runtime") == "ng":
        if not NG_REPORTS_ON:
            print("result saved on this NAS only")
            return 0
        ver = game_version(e.output, *([e.path] if e.kind == "folder" else []), name=e.rel).get("version", "")
        print("report it to quer3q (ampr-emu-ng; open on your phone or computer, fill in the rest, submit):")
        print(ng_report_url(rep.get("title_id") or e.title_id, name, args.result,
                            "zstd" if rep.get("pack_codec") == "zstd" else "lz4", ver,
                            os.environ.get("PS5LZ4_FIRMWARE", "")))
        return 0
    print("result saved on this NAS only (an APR-EMU copy: quer3q's reports cover ampr-emu-ng)")
    return 0


def cmd_report(args) -> int:
    ensure_dirs()
    rows = [read_json(p) for p in sorted(REPORTS.glob("*.json")) if not p.name.endswith(".skipped.json")]
    rows = [r for r in rows if r]
    skipped = [read_json(p) for p in sorted(REPORTS.glob("*.skipped.json"))]
    if args.json:
        print(json.dumps({"done": rows, "skipped": skipped}, indent=2, ensure_ascii=False))
        return 0
    tot_src = tot_out = 0
    games = ng_reports()
    print(f"{'game':40} {'title':9} {'original':>10} {'LZ4':>10} {'saved':>10} {'%':>6}  verified")
    for r in rows:
        tot_src += r["source_bytes"]
        tot_out += r["output_bytes"]
        print(f"{r['id'][:40]:40} {r.get('title_id') or '-':9} {human(r['source_bytes']):>10} "
              f"{human(r['output_bytes']):>10} {human(r['saved_bytes']):>10} {r['saved_percent']:>5}%  "
              f"{'NAS ok' if r.get('verified_on_nas') else 'NO'} / {ps5_text(r)}")
        c = ngr_text(games.get((r.get("title_id") or "").upper()))
        if c:
            print(f"{'':40} {c}")
    if rows:
        pct = 100.0 * (tot_src - tot_out) / tot_src if tot_src else 0
        print(f"{'TOTAL':40} {'':9} {human(tot_src):>10} {human(tot_out):>10} "
              f"{human(tot_src - tot_out):>10} {pct:>5.1f}%")
    for s in skipped:
        if s:
            print(f"skipped: {s['id']}: {s['reason']}")
    # Keep a plain TSV next to the JSON reports.
    with open(REPORTS / "summary.tsv", "w") as f:
        f.write("id\ttitle_id\tsource_bytes\toutput_bytes\tsaved_bytes\tsaved_percent\tcodec\tfinished\n")
        for r in rows:
            f.write(f"{r['id']}\t{r.get('title_id')}\t{r['source_bytes']}\t{r['output_bytes']}\t"
                    f"{r['saved_bytes']}\t{r['saved_percent']}\t{r['codec']}\t{r['finished']}\n")
    return 0


def cmd_verify(args) -> int:
    """Re-check a finished output (all chunks decoded, CRC, manifest)."""
    ensure_dirs()
    target = Path(args.output)
    if not target.is_absolute():
        target = output_item(args.output)
    if not is_packed(target):
        raise SystemExit(f"{target} has no packed index")
    if requires_ng(target):
        problem = lz4_format_problem(target)
        if problem:
            print(problem)
            return 3
        import tempfile
        # Independent full decode; Forge validates every frame and compares all
        # logical output bytes. Temporary files stay in the configured work area.
        with tempfile.TemporaryDirectory(prefix="verify-ng-", dir=WORK) as tmp:
            decoded = Path(tmp) / "decoded"
            rc = subprocess.call(nice_prefix() + forge_command(target, decoded, packed_codec(target), 5, unpack=True))
            if rc == 0 and args.source:
                rc = 3 if compare_game_files(Path(args.source), decoded) else 0
        print("verify passed" if rc == 0 else f"verify FAILED (exit {rc})")
        return rc
    # An older APR-EMU LZ4 copy: its packer is gone, so only the structure is checked.
    problem = lz4_format_problem(target)
    print(problem or "structure ok (APR-EMU LZ4 copy: a full decode is no longer available; "
                     "repack it as LZ4 NG or Zstd for a verified copy)")
    return 3 if problem else 0


VERIFIES = STATE / "verify"


def cmd_verify_lz4(args) -> int:
    """The page's Verify LZ4: cmd_verify on one LZ4 copy, its result kept in
    state/verify/<name>.json for the page (in the background)."""
    out = output_for(args.game)
    VERIFIES.mkdir(parents=True, exist_ok=True)
    p = VERIFIES / f"{out.name}.json"
    write_json(p, {"state": "running", "started": now(), "pid": os.getpid()})
    me = [sys.executable, os.path.abspath(__file__)]
    res = subprocess.run(me + ["verify", out.name], capture_output=True, text=True)
    text = (res.stdout + res.stderr).strip()
    write_json(p, {"state": "passed" if res.returncode == 0 else "failed", "started": (read_json(p, {}) or {}).get("started"),
                   "finished": now(), "output": text[-1500:]})
    print(text[-1500:])
    return res.returncode


def verify_states() -> dict:
    out = {}
    if VERIFIES.is_dir():
        for f in VERIFIES.glob("*.json"):
            st = read_json(f, {}) or {}
            if st.get("state") == "running":
                try:
                    os.kill(int(st.get("pid", 0)), 0)
                except (OSError, ValueError):
                    st["state"] = "interrupted"
            out[f.stem] = st
    return out


def find_runtime(game: Path) -> Path | None:
    for d in game.iterdir():
        if d.is_dir() and d.name.lower() == "fakelib":
            for f in d.iterdir():
                if f.is_file() and f.name.lower() == "libsceampr.sprx":
                    return f
    return None


# --------------------------------------------------------------------------
# boot files (upstream src/lzc_boot_files.c): some folder dumps (PPSA11386)
# stop with SIGBUS a few seconds in when the folder named by RUNTIME_PATH= in
# eboot.bin exists only in another case (Runtime/ for runtime/; the PS5 is
# case-sensitive) or when they import libScePlayGo and fakelib/ has none.

PLAYGO_LIB = "libScePlayGo.sprx"
PLAYGO_EMU_MARKER = b"PlayGo PRX stub"
PLAYGO_DIR = STATE / "playgo"  # put a PlayGo emulator here: state/playgo/libScePlayGo.sprx


def scan_file(path: Path, needle: bytes, value: bool = False) -> bytes | bool | None:
    """True (or, with value, the printable bytes after it) when needle is in
    the file; False/None when not or unreadable."""
    keep = len(needle) + (64 if value else 0)
    tail = b""
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(4 << 20)
                buf = tail + chunk
                i = buf.find(needle)
                if i >= 0 and (not value or not chunk or len(buf) - i >= keep):
                    if not value:
                        return True
                    m = re.match(rb"[\x21-\x7e]{0,63}", buf[i + len(needle):])
                    return m.group(0)
                if not chunk:
                    return None if value else False
                tail = buf[-keep:] if i < 0 else buf[i:]
    except OSError:
        return None if value else False


def entry_nocase(d: Path, name: str) -> str | None:
    try:
        return next((x for x in os.listdir(d) if x.lower() == name.lower()), None)
    except OSError:
        return None


def is_playgo_emu(p: Path) -> bool:
    try:
        st = p.stat()
    except OSError:
        return False
    return p.is_file() and 0 < st.st_size <= 4 << 20 and scan_file(p, PLAYGO_EMU_MARKER) is True


def find_playgo_emu(root: Path) -> Path | None:
    """state/playgo first, then the fakelib/ of other LZ4 games and library folders."""
    p = PLAYGO_DIR / PLAYGO_LIB
    if is_playgo_emu(p):
        return p
    for base in (*output_roots(), LIBRARY):
        try:
            games = sorted(x for x in base.iterdir() if x.is_dir() and not x.name.startswith("."))
        except OSError:
            continue
        for g in games:
            if g.resolve() == root.resolve():
                continue
            fl = entry_nocase(g, "fakelib")
            lib = entry_nocase(g / fl, PLAYGO_LIB) if fl else None
            if lib and is_playgo_emu(g / fl / lib):
                return g / fl / lib
    return None


def ampr_index_stale(root: Path) -> str | None:
    """The first file a shipped ampr_emu.index (AMPRIDX3) lists that is not in root
    with that size, or None. APR-EMU trusts the index for every /app0 lookup, so a
    stale one (e.g. /app0/Runtime/... after Runtime/ became runtime/) crashes the
    game at boot (from the original project's Verify)."""
    import struct
    p = root / "ampr_emu.index"
    try:
        size = p.stat().st_size
        if size < 48 or size > 256 << 20:
            return None
        buf = p.read_bytes()
    except OSError:
        return None
    if buf[:8] != b"AMPRIDX3" or struct.unpack_from("<II", buf, 8) != (3, 24):
        return None
    count, path_bytes = struct.unpack_from("<QQ", buf, 16)
    blob = 48 + count * 24
    if count > (size - 48) // 24 or path_bytes > size - blob:
        return None
    for i in range(count):
        off, ln, want = struct.unpack_from("<IIQ", buf, 48 + i * 24)
        if off + ln >= path_bytes or buf[blob + off + ln] != 0:
            continue
        name = buf[blob + off: blob + off + ln].decode("utf-8", "replace")
        if not name.startswith("/app0/"):
            continue
        f = root / name[6:]
        try:
            if f.is_symlink() or not f.is_file() or f.stat().st_size != want:
                return name[6:]
        except OSError:
            return name[6:]
    return None


def boot_files(root: Path, repair: bool) -> dict:
    """What root needs to boot: {"changed": [...], "needed": [...], "notes": [...]}.
    With repair the runtime folder is renamed, a PlayGo emulator copied in and,
    on an unpacked folder, a stale ampr_emu.index moved aside."""
    r = {"changed": [], "needed": [], "notes": []}
    eboot = root / "eboot.bin"
    if not eboot.is_file():
        return r
    with open(eboot, "rb") as f:
        if f.read(4) == b"\x7fELF":
            r["notes"].append("eboot.bin is a plain ELF; if the game won't start, convert it to FSELF")
    want = scan_file(eboot, b"RUNTIME_PATH=", value=True)
    name = (want or b"").decode("ascii", "replace")
    while name.startswith("./"):
        name = name[2:]
    name = name.rstrip("/")
    if name and "/" not in name and name not in (".", "..") and name not in os.listdir(root):
        have = entry_nocase(root, name)
        if have and (root / have).is_dir():
            if repair:
                tmp = root / (name + ".ps5lz4-rename")
                os.rename(root / have, tmp)  # through a temporary name: case-only renames
                os.rename(tmp, root / name)
                r["changed"].append(f"renamed {have}/ to {name}/")
            else:
                r["needed"].append(f"runtime folder {have}/ must be named {name}/")
    fl = entry_nocase(root, "fakelib")
    if not (fl and entry_nocase(root / fl, PLAYGO_LIB)):
        imports = scan_file(eboot, b"libScePlayGo") is True
        mods = root / "sce_module"
        if not imports and mods.is_dir():
            imports = any(scan_file(m, b"libScePlayGo") is True for m in mods.iterdir()
                          if m.name.lower().endswith(".prx"))
        if imports:
            src = find_playgo_emu(root)
            if not src:
                r["needed"].append(f"a PlayGo emulator: none found; put {PLAYGO_LIB} in "
                                   f"{Path(HOST_STATE) / 'playgo'} and repair")
            elif repair:
                d = root / (fl or "fakelib")
                d.mkdir(exist_ok=True)
                os.chmod(d, 0o755)
                tmp = d / (PLAYGO_LIB + ".tmp")
                shutil.copyfile(src, tmp)
                os.chmod(tmp, 0o755)
                os.replace(tmp, d / PLAYGO_LIB)
                r["changed"].append(f"PlayGo emulator added to fakelib (from {src})")
            else:
                r["needed"].append("a PlayGo emulator in fakelib")
    # After the runtime rename. LZ4 packs list files that live inside the packs: skipped.
    if not is_packed(root):
        miss = ampr_index_stale(root)
        if miss and repair:
            os.replace(root / "ampr_emu.index", root / "ampr_emu.index.stale")
            r["changed"].append(f"moved the out-of-date ampr_emu.index aside (lists {miss}); APR-EMU builds a new one")
        elif miss:
            r["needed"].append(f"ampr_emu.index is out of date (lists {miss}, which is not there): "
                               "it must be moved aside or the game crashes at boot")
    return r


def lz4_game_sig(g: Path) -> str:
    """Changes when the packs, the runtime or the top level of the folder change."""
    rt = find_runtime(g)
    # The image's runtime is part of it: a new ampr-emu-ng build re-checks every copy.
    return NG_SHA256[:12] + ":" + file_sig(g, packed_index(g), g / "ampr_assets.index.crc", rt or g / RUNTIME_REL)


def cmd_apr(args) -> int:
    """Check every packed game: its matching AMPR runtime, on-disk files, the runtime folder
    name and PlayGo emulator a game needs to boot; --fix repairs them.
    Games whose files haven't changed since their last check reuse that result
    (state/ps5lz4.db) unless --full is given."""
    ensure_dirs()
    games = [p for p in output_items() if p.is_dir() and is_packed(p)]
    if not games:
        print(f"no packed games in {OUTPUT}")
        return 0
    db = CheckDB()
    bad = cached = 0
    for g in games:
        key = "apr:" + g.name
        hit = db.get(key)
        if hit and not args.full and hit.get("sig") == lz4_game_sig(g) and (hit.get("ok") or not args.fix):
            cached += 1
            bad += 0 if hit.get("ok") else 1
            print(f"{hit['state']:<45} {g.name}  (cached {hit.get('checked', '')})")
            continue
        rt = find_runtime(g)
        ok = True
        if rt is None:
            state = "MISSING APR-EMU"
        else:
            sha = hashlib.sha256(rt.read_bytes()).hexdigest()
            state = "ok" if runtime_ok(g, sha) else f"WRONG RUNTIME ({sha[:12]})"
            if args.fix and requires_ng(g) and sha != NG_SHA256:
                state = "NG runtime upgrade needed"
        if state != "ok":
            ok = False
            if not requires_ng(g):
                # An APR-EMU copy: its runtime and packer are no longer in this image.
                state += " (APR-EMU copy: repack as LZ4 NG or Zstd)"
            elif args.fix:
                dst = rt or (g / RUNTIME_REL)
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.chmod(dst.parent, 0o755)
                tmp = dst.with_name(dst.name + ".tmp")
                runtime_file, expected_sha = NG_FILE, NG_SHA256
                if not runtime_file.is_file() or hashlib.sha256(runtime_file.read_bytes()).hexdigest() != expected_sha:
                    raise SystemExit("matching pinned runtime is missing; update the container")
                shutil.copyfile(runtime_file, tmp)
                os.chmod(tmp, 0o755)
                os.replace(tmp, dst)
                update_runtime_index(g, dst)
                state += " -> FIXED"
                ok = True
        try:
            boot = boot_files(g, repair=args.fix)
        except OSError as err:
            boot = {"changed": [], "needed": [f"boot files not fixed: {err}"], "notes": []}
        for part in boot["changed"]:
            state += f"; {part}"
        for part in boot["needed"]:
            state += f"; NEEDS {part}"
            ok = False
        for part in boot["notes"]:
            state += f"; note: {part}"
        bad += 0 if ok else 1
        db[key] = {"sig": lz4_game_sig(g), "ok": ok, "state": state, "checked": now()}
        print(f"{state:<45} {g.name}")
    db.close()
    if cached:
        print(f"{cached} of {len(games)} unchanged since their last check (results from the database; --full checks again)")
    if bad and not args.fix:
        print(f"{bad} game(s) need repair; run: ps5lz4 apr --fix")
    return 1 if bad and not args.fix else 0


DELETE_ORIGINALS = os.environ.get("PS5LZ4_DELETE_ORIGINALS", "no") == "yes"


def cmd_delete_original(args) -> int:
    """Delete an original game (folder or image) from the library. Only when
    installed with DELETE_ORIGINALS=yes; the LZ4 copy, if any, stays."""
    ensure_dirs()
    if not DELETE_ORIGINALS:
        raise SystemExit("deleting originals is off; reinstall with DELETE_ORIGINALS=yes to allow it")
    e = next((x for x in scan_library() if x.id == args.game), None)
    if e is None:
        raise SystemExit(f"{args.game} is not in the library")
    if not under(e.path, LIBRARY) or os.path.abspath(e.path) == os.path.abspath(LIBRARY):
        raise SystemExit(f"refusing to delete outside the library: {e.path}")
    running, _ = job_running()
    q = read_json(QUEUE_PATH, {}) or {}
    if running and q.get("current") == e.id:
        raise SystemExit("that game is being packed right now; stop the job first")
    if e.output.is_dir() and not tested_ok(e.id):
        raise SystemExit("test the LZ4 copy on the PS5 first: mark it 'works' (PS5 result), "
                         "then the original can go; nothing was deleted")
    files, size = tree_bytes(e.path) if e.path.is_dir() else (1, e.path.stat().st_size)
    if e.path.is_dir():
        shutil.rmtree(e.path)
    else:
        e.path.unlink()
        for side in (e.path.with_name(e.path.name + ".vhash"),):
            side.unlink(missing_ok=True)
    print(f"deleted the original {e.rel} ({human(size)}) from {HOST_LIBRARY}"
          + (f"; the LZ4 copy {e.output.name} stays" if e.output.is_dir() else ""))
    return 0


def cmd_remove(args) -> int:
    """Delete a finished LZ4 copy from the output folder (never an original).
    Its report goes too, so the game shows as 'can be LZ4' again."""
    ensure_dirs()
    out = output_for(args.game)
    if out.parent not in output_roots() or not out.name.endswith(("-lz4", "-zstd")) or not is_packed(out):
        raise SystemExit(f"{out} is not an LZ4 copy in {OUTPUT}")
    if under(out, LIBRARY):
        raise SystemExit(f"refusing to delete inside the library: {out}")
    running, _ = job_running()
    q = read_json(QUEUE_PATH, {}) or {}
    if running and q.get("current") and out.name in (f"{q['current']}-lz4", f"{q['current']}-zstd"):
        raise SystemExit("that game is being packed right now; stop the job first")
    _files, size = tree_bytes(out)
    host = host_output_path(out)
    shutil.rmtree(out)
    # A game's report describes its last pack only: drop it when it is about the
    # copy just removed (or names none), not when it belongs to the other format.
    names = {e.id for e in scan_library() if e.output == out} | {out.name.rsplit("-", 1)[0]}
    for name in names:
        rep = read_json(REPORTS / f"{name}.json") or {}
        if rep.get("output") in (None, host):
            (REPORTS / f"{name}.json").unlink(missing_ok=True)
    print(f"deleted {out.name} ({human(size)}) from {Path(host).parent}; the original is untouched")
    return 0


def cmd_clean(args) -> int:
    """Remove the work folder of a failed or skipped game."""
    ensure_dirs()
    for t in args.ids:
        w = WORK / safe_name(t)
        if not w.exists():
            print(f"{t}: no work folder")
            continue
        remove_work_path(w)
        print(f"{t}: removed {w}")
    return 0


def cmd_doctor(_args) -> int:
    ok = True
    def line(good: bool, msg: str):
        nonlocal ok
        ok &= good
        print(f"[{'ok' if good else 'FAIL'}] {msg}")
    print(f"ps5lz4 {VERSION}  arch={os.uname().machine}  cpus={os.cpu_count()}  workers={workers()}")
    line(LIBRARY.is_dir(), f"library {LIBRARY} readable")
    probe = LIBRARY / ".ps5lz4-write-test"
    try:
        probe.write_text("x")
        probe.unlink()
        line(DELETE_ORIGINALS, "library is writable (DELETE_ORIGINALS=yes: originals can be deleted from the web page)"
             if DELETE_ORIGINALS else "library is WRITABLE: mount it read-only (:ro)")
    except OSError as err:
        line(err.errno in (errno.EROFS, errno.EACCES, errno.EPERM), "library is read-only")
    line(OUTPUT.is_dir() and os.access(OUTPUT, os.W_OK), f"output {OUTPUT} writable")
    line(STATE.is_dir() and os.access(STATE, os.W_OK), f"state {STATE} writable")
    line(WORK.is_dir() and os.access(WORK, os.W_OK), f"work area {WORK} writable")
    try:
        same_fs = os.stat(OUTPUT).st_dev == os.stat(WORK if WORK.exists() else OUTPUT).st_dev
        line(same_fs, "work area on the output volume (atomic publish)")
    except OSError:
        line(False, "work area")
    if OUTPUT.is_dir():
        print(f"     free on output volume: {human(free_bytes(OUTPUT))}")
    try:
        out = subprocess.run([FORGE], capture_output=True, text=True)
        line("ps5-dump-forge" in out.stdout + out.stderr, f"packer {FORGE} (PS5 Dump Forge {forge_pin_version()})")
    except OSError as err:
        line(False, f"packer {FORGE}: {err}")
    line(NG_FILE.is_file() and hashlib.sha256(NG_FILE.read_bytes()).hexdigest() == NG_SHA256, f"runtime {NG_NAME}")
    try:
        out = subprocess.run([MKPFS, "-V"], capture_output=True, text=True)
        txt = (out.stdout + out.stderr).strip().splitlines()
        line(any("1.1.0" in t for t in txt), f"MkPFS: {txt[0] if txt else '?'}")
    except OSError as err:
        line(False, f"MkPFS: {err}")
    return 0 if ok else 1


# --------------------------------------------------------------------------
# web page: `ui` serves it (own container, LAN only), `agent` runs in the
# ps5-lz4 container and carries out what the page asks for. The page never
# runs jobs itself and needs no Docker socket.

# --------------------------------------------------------------------------
# transfer to the PS5 over FTP (ftpsrv). Runs where there is a network: the
# ps5-lz4-ui container, never the network-less ps5-lz4 container.

SETTINGS_PATH = STATE / "settings.json"
TRANSFERS = STATE / "transfers"


def get_settings() -> dict:
    s = {"ps5_ftp": os.environ.get("PS5LZ4_PS5_FTP", ""),
         "ps5_dest": os.environ.get("PS5LZ4_PS5_DEST", "/mnt/usb0/homebrew"),
         "ps5_wake_key": os.environ.get("PS5LZ4_PS5_WAKE_KEY", ""),
         "ps4_dest": os.environ.get("PS5LZ4_PS4_DEST", "/mnt/usb0"),
         "notify_url": os.environ.get("PS5LZ4_NOTIFY_URL", "")}
    s.update({k: v for k, v in (read_json(SETTINGS_PATH, {}) or {}).items() if k in s and isinstance(v, str)})
    return s


def save_settings(new: dict) -> dict:
    s = get_settings()
    ftp = str(new.get("ps5_ftp", s["ps5_ftp"])).strip()
    dest = str(new.get("ps5_dest", s["ps5_dest"])).strip().rstrip("/") or "/"
    if ftp and not re.fullmatch(r"[A-Za-z0-9.\-]+(:\d{1,5})?", ftp):
        raise ValueError("FTP address must look like 192.168.1.20:2121")
    if not dest.startswith("/") or ".." in dest.split("/"):
        raise ValueError("destination must be an absolute path on the PS5")
    key = str(new.get("ps5_wake_key", s["ps5_wake_key"])).strip()
    if key and not re.fullmatch(r"[0-9A-Fa-f]{1,8}", key):
        raise ValueError("the Remote Play key is up to 8 hex characters (rp_regist_key in Chiaki)")
    pdest = str(new.get("ps4_dest", s["ps4_dest"])).strip().rstrip("/") or "/mnt/usb0"
    if not pdest.startswith("/") or ".." in pdest.split("/"):
        raise ValueError("the PS4 package folder must be an absolute path on the PS5")
    nurl = str(new.get("notify_url", s["notify_url"])).strip()
    if nurl and not re.fullmatch(r"https?://[^\s]+", nurl):
        raise ValueError("the notification address must start with http:// or https://")
    s.update(ps5_ftp=ftp, ps5_dest=dest, ps5_wake_key=key, ps4_dest=pdest, notify_url=nurl)
    stored = read_json(SETTINGS_PATH, {}) or {}
    stored.update(s)  # keeps the pairing details (RP key, MAC, name)
    write_settings(stored)
    return s


def write_settings(data: dict) -> None:
    write_json(SETTINGS_PATH, data)
    try:
        os.chmod(SETTINGS_PATH, 0o600)  # Remote Play keys
    except OSError:
        pass


# Remote Play discovery, the way Chiaki wakes a PS5 from rest mode: a UDP
# WAKEUP to port 9302 carrying the registration key (rp_regist_key).
PS5_DISCOVERY_PORT = 9302
PS5_DISCOVERY_VERSION = "00030010"


def _discovery_socket():
    """UDP socket on a local port in Chiaki's range (9303-9319) when free."""
    import socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for port in range(9303, 9320):
        try:
            sk.bind(("", port))
            break
        except OSError:
            continue
    return sk


def ps5_status(host: str, timeout: float = 1.5) -> str:
    """'on', 'standby' or 'unknown' (no answer)."""
    import socket
    msg = f"SRCH * HTTP/1.1\ndevice-discovery-protocol-version:{PS5_DISCOVERY_VERSION}\n".encode()
    with _discovery_socket() as sk:
        sk.settimeout(timeout)
        try:
            sk.sendto(msg, (host, PS5_DISCOVERY_PORT))
            data = sk.recv(2048).decode(errors="replace")
        except OSError:
            return "unknown"
    first = data.split("\n", 1)[0]
    if " 200 " in first:
        return "on"
    if " 620 " in first:
        return "standby"
    return "unknown"


def ps5_find(hint: str = "") -> list[dict]:
    """PS5s on the local network: the discovery message (as Remote Play sends
    it) to every address of the /24 the PS5 address or this page is on. Each
    console answers, on (200) or in rest mode (620), with its name."""
    import ipaddress
    import socket
    nets = []
    for h in (hint, (get_settings().get("ps5_ftp") or "").partition(":")[0]):
        h = (h or "").partition(":")[0]
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(h)) if h else None
        except (OSError, ValueError):
            ip = None
        if ip and ip.is_private:
            net = ipaddress.ip_network(f"{ip}/24", strict=False)
            if net not in nets:
                nets.append(net)
    if not nets:
        raise ValueError("open this page by the NAS's IP address (e.g. http://192.168.1.10:5921) so the network is known")
    msg = f"SRCH * HTTP/1.1\ndevice-discovery-protocol-version:{PS5_DISCOVERY_VERSION}\n".encode()
    found = {}
    with _discovery_socket() as sk:
        sk.settimeout(0.2)
        for _round in range(2):
            for net in nets:
                for host in net.hosts():
                    try:
                        sk.sendto(msg, (str(host), PS5_DISCOVERY_PORT))
                    except OSError:
                        pass
            end = time.time() + 1.5
            while time.time() < end:
                try:
                    data, (addr, _port) = sk.recvfrom(2048)
                except OSError:
                    continue
                text = data.decode(errors="replace")
                first = text.split("\n", 1)[0]
                fields = dict(l.split(":", 1) for l in text.splitlines()[1:] if ":" in l)
                found[addr] = {"ip": addr, "status": "on" if " 200 " in first else "standby" if " 620 " in first else "?",
                               "name": fields.get("host-name", "").strip(), "type": fields.get("host-type", "").strip(),
                               "id": fields.get("host-id", "").strip()}
    return sorted(found.values(), key=lambda d: [int(x) for x in d["ip"].split(".")])


def ps5_wake(host: str, key: str) -> None:
    import socket
    credential = int(key, 16)
    msg = ("WAKEUP * HTTP/1.1\nclient-type:vr\nauth-type:R\nmodel:w\napp-type:r\n"
           f"user-credential:{credential}\ndevice-discovery-protocol-version:{PS5_DISCOVERY_VERSION}\n").encode()
    with _discovery_socket() as sk:
        for _ in range(3):
            sk.sendto(msg, (host, PS5_DISCOVERY_PORT))
            time.sleep(0.3)


# Where a PlayGo emulator may be on the console (upstream lzc_boot_files.c);
# "games:" folders hold game folders whose fakelib/ is checked.
PS5_PLAYGO_SOURCES = ("/data/LZ4Compression/import/libs", "/data/shadowmount/emus",
                      "/data/shadowmount/fakelib", "games:/data/homebrew", "games:/data/etaHEN/games",
                      "games:/mnt/ext0/homebrew", "games:/mnt/ext1/homebrew",
                      "games:/mnt/ext0/etaHEN/games", "games:/mnt/ext1/etaHEN/games",
                      "games:/mnt/usb0/homebrew", "games:/mnt/usb1/homebrew")


def fetch_playgo_emu(ftp, rsize, skip: str) -> Path | None:
    """Download a PlayGo emulator from the PS5 into state/playgo (SELF decryption
    is already off on this connection). None when the console has none."""
    import ftplib
    cands = []
    for src in PS5_PLAYGO_SOURCES:
        if not src.startswith("games:"):
            cands.append(f"{src}/{PLAYGO_LIB}")
            continue
        games = sorted(ps5_ftp_names(ftp, src[6:]) or [])
        cands += [f"{src[6:]}/{g}/fakelib/{PLAYGO_LIB}" for g in games
                  if not g.startswith(".") and f"{src[6:]}/{g}" != skip]
    for path in cands:
        size = rsize(ftp, path)
        if not size or size > 4 << 20:
            continue
        buf = bytearray()
        try:
            ftp.retrbinary(f"RETR {path}", buf.extend)
        except ftplib.all_errors:
            continue
        if PLAYGO_EMU_MARKER in buf:
            PLAYGO_DIR.mkdir(parents=True, exist_ok=True)
            dst = PLAYGO_DIR / PLAYGO_LIB
            tmp = dst.with_name(dst.name + ".tmp")
            tmp.write_bytes(bytes(buf))
            os.replace(tmp, dst)
            return dst
    return None


def ps5_ftp_names(ftp, path: str) -> list[str] | None:
    """Names in a folder on the PS5, or None when it can't be listed (missing).
    MLSD, then LIST, then NLST: ftpsrv builds differ in what they take."""
    import ftplib
    try:
        return [i["name"] for i in ps5_ftp_list_conn(ftp, path)]
    except ftplib.all_errors:
        pass
    try:
        return [n.rsplit("/", 1)[-1] for n in ftp.nlst(path) if n.rsplit("/", 1)[-1] not in (".", "..")]
    except ftplib.all_errors:
        pass
    try:
        ftp.cwd(path)
        ftp.cwd("/")
        return []  # it exists but can't be listed
    except ftplib.all_errors:
        return None


def ps5_ftp_path(path: str) -> str:
    path = "/" + path.strip().strip("/")
    if any(c in path for c in "\r\n\0") or ".." in path.split("/"):
        raise ValueError("bad path")
    return path


def ps5_ftp_connect():
    """FTP to the PS5's ftpsrv, binary, SELF decryption off (files as they are on disk)."""
    import ftplib
    cfg = get_settings()
    if not cfg["ps5_ftp"]:
        raise ValueError("set the PS5 address on the Remote tab first")
    host, _, port = cfg["ps5_ftp"].partition(":")
    f = ftplib.FTP()
    try:
        f.connect(host, int(port or 2121), timeout=15)
    except OSError as err:
        raise ValueError(f"no FTP server at {cfg['ps5_ftp']}: is the PS5 on with ftpsrv running? ({err})")
    f.login()
    try:
        f.sendcmd("SELF")
    except ftplib.all_errors:
        pass
    f.voidcmd("TYPE I")
    return f


LIST_RE = re.compile(r"^([-dlcbps])\S*\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\w{3}\s+\d+\s+[\d:]+)\s+(.+)$")


def ps5_ftp_list(path: str) -> dict:
    """Folders and files in one folder on the PS5, folders first."""
    import ftplib
    path = ps5_ftp_path(path)
    f = ps5_ftp_connect()
    try:
        items = ps5_ftp_list_conn(f, path)
    except ftplib.error_perm as err:
        raise ValueError(f"{path}: {err}")
    finally:
        try:
            f.quit()
        except Exception:
            pass
    items.sort(key=lambda i: (not i["dir"], i["name"].lower()))
    return {"path": path, "items": items}


def ps5_ftp_list_conn(f, path: str) -> list[dict]:
    import ftplib
    items = []
    try:
        for name, facts in f.mlsd(path, ["type", "size", "modify"]):
            if name in (".", "..") or facts.get("type") in ("cdir", "pdir"):
                continue
            m = facts.get("modify", "")
            items.append({"name": name, "dir": facts.get("type") == "dir",
                          "size": int(facts["size"]) if facts.get("size", "").isdigit() else None,
                          "modified": f"{m[:4]}-{m[4:6]}-{m[6:8]} {m[8:10]}:{m[10:12]}" if len(m) >= 12 else ""})
    except ftplib.error_perm:
        lines = []
        f.retrlines(f"LIST {path}", lines.append)
        for line in lines:
            m = LIST_RE.match(line)
            if not m:
                continue
            kind, size, date, name = m.groups()
            if kind == "l":
                name = name.split(" -> ")[0]
            if name in (".", ".."):
                continue
            items.append({"name": name, "dir": kind == "d", "link": kind == "l",
                          "size": None if kind == "d" else int(size), "modified": date})
    return items


def ps5_ftp_apr(path: str) -> dict:
    """APR-EMU in a game folder on the PS5: fakelib/libSceAmpr.sprx and whether
    it is the PackedStdio build LZ4 packs need."""
    import ftplib
    path = ps5_ftp_path(path)
    f = ps5_ftp_connect()
    try:
        entries = ps5_ftp_list_conn(f, path)
        zstd = any(i["name"] == "ampr_zstd.index" for i in entries)
        fl = next((i["name"] for i in entries if i["dir"] and i["name"].lower() == "fakelib"), None)
        if not fl:
            return {"path": None, "ok": False, "build": "missing: no fakelib folder"}
        lib = next((i["name"] for i in ps5_ftp_list_conn(f, f"{path}/{fl}")
                    if not i["dir"] and i["name"].lower() == "libsceampr.sprx"), None)
        if not lib:
            return {"path": None, "ok": False, "build": "missing: no libSceAmpr.sprx in fakelib"}
        h = hashlib.sha256()
        f.retrbinary(f"RETR {path}/{fl}/{lib}", h.update)
        sha = h.hexdigest()
        return {"path": f"{path}/{fl}/{lib}", "ok": sha in (NG_SHA256, NG_UPSTREAM_SHA256) if zstd else sha in (RUNTIME_SHA256, NG_SHA256, NG_UPSTREAM_SHA256),
                "build": runtime_name(sha)}
    except ftplib.error_perm as err:
        raise ValueError(f"{path}: {err}")
    finally:
        try:
            f.quit()
        except Exception:
            pass


ICON_CACHE = STATE / "icons"
_icon_lock = __import__("threading").Lock()
_icon_missing: dict[str, float] = {}


def ps5_ftp_icon(path: str) -> bytes | None:
    """sce_sys/icon0.png of a game folder on the PS5, cached in state/icons.
    One FTP connection at a time, so a long folder list doesn't flood ftpsrv."""
    import ftplib
    path = ps5_ftp_path(path)
    cached = ICON_CACHE / (hashlib.sha1(path.encode()).hexdigest() + ".png")
    if cached.is_file():
        return cached.read_bytes()
    if time.time() - _icon_missing.get(path, 0) < 600:
        return None
    with _icon_lock:
        if cached.is_file():
            return cached.read_bytes()
        try:
            f = ps5_ftp_connect()
        except ValueError:
            return None
        buf = bytearray()
        try:
            for name in ("sce_sys/icon0.png", "sce_sys/ICON0.PNG", "icon0.png"):
                try:
                    f.retrbinary(f"RETR {path}/{name}", buf.extend)
                    break
                except ftplib.error_perm:
                    buf.clear()
        except ftplib.all_errors:
            buf.clear()
        finally:
            try:
                f.quit()
            except Exception:
                pass
        if not buf.startswith(b"\x89PNG") or len(buf) > 8 << 20:
            _icon_missing[path] = time.time()
            return None
        ICON_CACHE.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".tmp")
        tmp.write_bytes(bytes(buf))
        os.replace(tmp, cached)
        return bytes(buf)


def nas_icon(game_id: str) -> bytes | None:
    """sce_sys/icon0.png from a packed game folder, its source folder, or from
    inside its .exfat / .ffpfsc / .ffpfs image."""
    cands = [output_item(game_id), output_item(f"{game_id}-lz4"), output_item(f"{game_id}-zstd")]
    image = None
    for e in scan_library():
        if e.id == game_id:
            cands = [e.output, e.path] + cands
            image = e.path if e.kind != "folder" else None
            break
    for d in cands:
        for name in ("sce_sys/icon0.png", "sce_sys/ICON0.PNG"):
            p = d / name
            try:
                if p.is_file() and p.stat().st_size < 8 << 20:
                    return p.read_bytes()
            except OSError:
                pass
    if image is not None:
        try:
            return image_meta(image).get("icon")
        except OSError:
            pass
    return None


# Uploads and new folders: anywhere inside /data, /mnt/usbN or /mnt/extN.
FTP_WRITE_ROOTS = re.compile(r"^/(data|mnt/(usb|ext)\d+)/.+")


def ps5_ftp_mkdirs(f, path: str) -> None:
    import ftplib
    cur = ""
    for part in path.strip("/").split("/"):
        cur += "/" + part
        try:
            f.mkd(cur)
        except ftplib.error_perm:
            pass  # exists


def ps5_ftp_put(path: str, stream, length: int) -> dict:
    """Store `length` bytes from stream as path on the PS5 (folders made as needed)."""
    path = ps5_ftp_path(path)
    if not FTP_WRITE_ROOTS.match(path):
        raise ValueError("uploads go inside /data, /mnt/usbN or /mnt/extN")

    class Exact:
        def __init__(self):
            self.left = length

        def read(self, n=-1):
            n = self.left if n < 0 else min(n, self.left)
            data = stream.read(n) if n else b""
            self.left -= len(data)
            return data

    f = ps5_ftp_connect()
    try:
        ps5_ftp_mkdirs(f, path.rsplit("/", 1)[0])
        src = Exact()
        f.storbinary(f"STOR {path}", src, blocksize=1 << 20)
        if src.left:
            raise ValueError("upload cut off")
        try:
            f.voidcmd("TYPE I")
            got = f.size(path)
        except Exception:
            got = None
        if got is not None and got != length:
            raise ValueError(f"the PS5 has {got} bytes, expected {length}")
        return {"path": path, "bytes": length}
    finally:
        try:
            f.quit()
        except Exception:
            pass


# The LZ4 Compression engine on the PS5 (port 5920): see whether it runs and
# whether it is this fork's build (which answers keep-awake), and install that
# build into the Payload Manager over FTP (overwriting the file there).
ENGINE_REPO = os.environ.get("PS5LZ4_ENGINE_REPO", "dviree/PS5-LZ4-NAS")
ENGINE_DIR = STATE / "engine"
# ELF loaders: elfldr / etaHEN on 9021, the exploit stage's loader on 9020.
PLDMGR_PORT = int(os.environ.get("PS5LZ4_PLDMGR_PORT", "8084"))  # Payload Manager's loadpayload
ELFLDR_PORTS = [int(p) for p in os.environ.get("PS5LZ4_ELFLDR_PORTS", "9021,9020").split(",") if p.strip()]


# Payload Manager 0.6 keeps uploaded payloads in payloads/local/<name>/ and takes
# loadpayload as a POST with its request marker; older ones use payloads/<name>/
# and GET (the original project's 1.6 does the same).
_PM_PATHS: dict = {}


def pm_path(old_path: str, f=None) -> str:
    """Where Payload Manager keeps this payload: the copy that exists (0.6's local/
    first), else local/ when that folder exists, else the old place."""
    import ftplib
    name = old_path.rsplit("/", 2)[-2]
    new_path = f"/data/pldmgr/payloads/local/{name}/{old_path.rsplit('/', 1)[1]}"
    own = f is None
    try:
        if own:
            f = ps5_ftp_connect()
        payloads = set(ps5_ftp_names(f, "/data/pldmgr/payloads") or [])
        if "local" in payloads:
            local = set(ps5_ftp_names(f, "/data/pldmgr/payloads/local") or [])
            if name in local or name not in payloads:
                _PM_PATHS[old_path] = new_path
                return new_path
        _PM_PATHS[old_path] = old_path
        return old_path
    except (OSError, ValueError, *ftplib.all_errors):
        return _PM_PATHS.get(old_path, old_path)
    finally:
        if own and f is not None:
            try:
                f.quit()
            except Exception:
                pass


def pm_load(host: str, path: str) -> str:
    """Ask Payload Manager to load a payload: POST with X-PLDMGR-Request (0.6),
    GET for older ones. The answer's text."""
    import urllib.error
    import urllib.request
    url = f"http://{host}:{PLDMGR_PORT}/loadpayload:{path}"
    try:
        req = urllib.request.Request(url, data=b"", method="POST", headers={"X-PLDMGR-Request": "1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read(65536).decode(errors="replace").strip()
    except urllib.error.HTTPError as err:
        if err.code not in (404, 405):
            raise
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read(65536).decode(errors="replace").strip()


def ps5_ftp_zip(path: str, out) -> None:
    """Write a folder on the PS5 to out as a ZIP (stored, streamed, zip64)."""
    import zipfile
    path = ps5_ftp_path(path)
    f = ps5_ftp_connect()
    base = path.rsplit("/", 1)[-1] or "ps5"
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            def walk(p, rel):
                items = ps5_ftp_list_conn(f, p)
                if not items:
                    z.writestr(rel + "/", b"")
                for i in items:
                    child, crel = f"{p}/{i['name']}", f"{rel}/{i['name']}"
                    if i["dir"]:
                        walk(child, crel)
                    elif not i.get("link"):
                        with z.open(crel, "w", force_zip64=True) as w:
                            f.retrbinary(f"RETR {child}", w.write, blocksize=1 << 20)
            walk(path, base)
    finally:
        try:
            f.quit()
        except Exception:
            pass


DRIVES_PATH = STATE / "ps5_drives.json"  # per drive: size you entered, last measured use
DRIVE_ROOT = re.compile(r"^/(data|mnt/(usb|ext)\d+)$")


def parse_size(text: str) -> int:
    """'1TB', '931.5 GB', '2000' (GB) -> bytes (decimal units, as the PS5 shows them)."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(tb|gb|t|g)?\s*", str(text).lower())
    if not m:
        raise ValueError("enter a size like 1 TB, 2TB or 931 GB")
    n = float(m.group(1).replace(",", "."))
    return int(n * (1000 ** 4 if (m.group(2) or "g").startswith("t") else 1000 ** 3))


def ps5_ftp_du(path: str) -> dict:
    """Total size, files and folders under a folder on the PS5 (ftpsrv has no
    command for free space, so this adds up what is there)."""
    path = ps5_ftp_path(path)
    f = ps5_ftp_connect()
    tot = {"path": path, "bytes": 0, "files": 0, "folders": 0}
    try:
        todo = [path]
        while todo and tot["files"] + tot["folders"] < 500000:
            p = todo.pop()
            try:
                items = ps5_ftp_list_conn(f, p)
            except Exception:
                continue
            for i in items:
                child = f"{p.rstrip('/')}/{i['name']}"
                if i["dir"]:
                    tot["folders"] += 1
                    todo.append(child)
                elif not i.get("link"):
                    tot["files"] += 1
                    tot["bytes"] += i.get("size") or 0
    finally:
        try:
            f.quit()
        except Exception:
            pass
    tot["measured"] = now()
    if re.match(r"^/(data|mnt/(usb|ext)\d+)/(homebrew|etaHEN/games)/[^/]+$", path):
        sizes = read_json(GAME_SIZES, {}) or {}
        sizes[path] = {"bytes": tot["bytes"], "measured": tot["measured"]}
        write_json(GAME_SIZES, sizes)
    if DRIVE_ROOT.match(path):
        info = read_json(DRIVES_PATH, {}) or {}
        info.setdefault(path, {}).update(used=tot["bytes"], files=tot["files"], measured=tot["measured"])
        write_json(DRIVES_PATH, info)
    return tot


def ps5_drives() -> dict:
    """Which PS5 drives answer over FTP, and the games ps5-lz4 sent to each."""
    f = ps5_ftp_connect()
    drives = []
    try:
        mnt = ps5_ftp_names(f, "/mnt") or []
        for path in ["/data"] + [f"/mnt/{n}" for n in sorted(mnt) if re.fullmatch(r"(usb|ext)\d+", n)]:
            if ps5_ftp_names(f, path) is not None:
                drives.append({"path": path, "label": "internal SSD" if path == "/data" else
                               ("USB drive " if "usb" in path else "extended storage ") + path[-1]})
    finally:
        try:
            f.quit()
        except Exception:
            pass
    for d in drives:
        sent = [read_json(t, {}) or {} for t in transfer_files()]
        sent = [t for t in sent if isinstance(t, dict) and t.get("state") == "done"
                and t.get("dest", "").partition("/")[2].startswith(d["path"].lstrip("/") + "/")]
        d["games"] = len(sent)
        d["game_bytes"] = sum(t.get("total") or 0 for t in sent)
        d.update((read_json(DRIVES_PATH, {}) or {}).get(d["path"], {}))
    # Real size and free space: from our engine (any drive) or pkg-receiver
    # (internal SSD); ftpsrv can't tell.
    for d in drives:
        try:
            d.update(drive_space(d["path"]))
        except Exception:
            pass
    # Game folders on each drive, wherever they came from.
    try:
        f = ps5_ftp_connect()
        try:
            for d in drives:
                n = 0
                for sub in ("homebrew", "etaHEN/games"):
                    n += len([x for x in ps5_ftp_names(f, f"{d['path']}/{sub}") or [] if not x.startswith(".")])
                d["game_folders"] = n
        finally:
            f.quit()
    except Exception:
        pass
    return {"drives": drives}


def drive_space(path: str) -> dict:
    """{"live_total", "live_free", "live_from"} for a PS5 drive, or {}."""
    import urllib.parse
    import urllib.request
    host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
    if not host:
        return {}
    try:
        j = _recv_get(f"/api/df?path={urllib.parse.quote(path)}")
        if j.get("ok") and j.get("total", -1) > 0:
            return {"live_total": j["total"], "live_free": j["free"], "live_from": "pkg-receiver"}
    except Exception:
        pass
    if path == "/data":
        try:
            j = _recv_get("/api/space")
            if j.get("total", -1) > 0:
                return {"live_total": j["total"], "live_free": j["free"], "live_from": "pkg-receiver"}
        except Exception:
            pass
    return {}


GAME_SIZES = STATE / "ps5_game_sizes.json"  # measured sizes of game folders on the PS5
GAME_DIRS = ("homebrew", "etaHEN/games")  # where ShadowMountPlus / etaHEN look, per drive


def ps5_games() -> dict:
    """Every game folder on the PS5's drives: name, title ID and version from
    param.json, LZ4 or not, APR-EMU present, measured size, duplicates."""
    import ftplib
    f = ps5_ftp_connect()
    sizes = read_json(GAME_SIZES, {}) or {}
    nas = {}
    for e in scan_library():
        if e.title_id:
            nas.setdefault(e.title_id.upper(), []).append(e.output.name if e.output.is_dir() else None)
    games = []
    try:
        mnt = ps5_ftp_names(f, "/mnt") or []
        drives = ["/data"] + [f"/mnt/{n}" for n in sorted(mnt) if re.fullmatch(r"(usb|ext)\d+", n)]
        for drive in drives:
            for sub in GAME_DIRS:
                base = f"{drive}/{sub}"
                try:
                    listing = ps5_ftp_list_conn(f, base)
                except ftplib.all_errors:
                    continue
                folders = [i for i in listing if i["dir"] and not i["name"].startswith(".")]
                # What ShadowMountPlus won't pick up (idea from game-library-manager-ps5):
                # hidden folders and images, and archives still to unpack.
                for it in listing:
                    low = it["name"].lower()
                    if it["name"].startswith(".") and it["name"] not in (".", "..") and (
                            it["dir"] or low.endswith((".exfat", ".ffpfs", ".ffpfsc"))):
                        games.append({"path": f"{base}/{it['name']}", "folder": it["name"], "drive": drive,
                                      "modified": it.get("modified", ""), "title_id": "", "version": "",
                                      "name": it["name"].lstrip("."), "lz4": False, "fakelib": False,
                                      "image": "", "size": it.get("size"), "on_nas": [], "attention": True,
                                      "issues": [{"code": "hidden", "fix": True,
                                                  "text": "the name starts with a dot, so ShadowMountPlus skips it"}]})
                    elif (not it["dir"] and low.endswith((".zip", ".rar", ".7z"))
                          and not re.search(r"\.part0*([2-9]|\d\d+)\.rar$", low)):
                        games.append({"path": f"{base}/{it['name']}", "folder": it["name"], "drive": drive,
                                      "modified": it.get("modified", ""), "title_id": "", "version": "",
                                      "name": it["name"], "lz4": False, "fakelib": False, "image": "",
                                      "size": it.get("size"), "on_nas": [], "attention": True,
                                      "issues": [{"code": "archive", "fix": False,
                                                  "text": "an archive: ShadowMountPlus can't use it until it is unpacked"}]})
                # Images ShadowMountPlus mounts as they are.
                for it in listing:
                    if not it["dir"] and it["name"].lower().endswith((".exfat", ".ffpfs", ".ffpfsc")):
                        m = TITLE_RE.search(it["name"])
                        games.append({"path": f"{base}/{it['name']}", "folder": it["name"], "drive": drive,
                                      "modified": it.get("modified", ""), "title_id": m.group(0).upper() if m else "",
                                      "name": re.sub(r"\s*\[[^]]*\]", "", it["name"].rsplit(".", 1)[0]).strip() or it["name"],
                                      "version": game_version(name=it["name"]).get("version", ""),
                                      "lz4": False, "fakelib": False, "image": it["name"].rsplit(".", 1)[1].lower(),
                                      "size": it.get("size"), "on_nas": []})
                for it in sorted(folders, key=lambda i: i["name"].lower()):
                    path = f"{base}/{it['name']}"
                    g = {"path": path, "folder": it["name"], "drive": drive, "modified": it.get("modified", ""),
                         "title_id": "", "name": "", "version": ""}
                    try:
                        names = {i["name"].lower(): i for i in ps5_ftp_list_conn(f, path)}
                    except ftplib.all_errors:
                        names = {}
                    g["lz4"] = "ampr_assets.index" in names or "ampr_zstd.index" in names
                    g["pack_codec"] = "zstd" if "ampr_zstd.index" in names else "lz4"
                    g["fakelib"] = "fakelib" in names
                    buf = bytearray()
                    try:
                        f.voidcmd("TYPE I")
                        f.retrbinary(f"RETR {path}/sce_sys/param.json", buf.extend)
                        j = json.loads(bytes(buf).decode("utf-8-sig", "replace"))
                        g["title_id"], g["name"] = parse_param_json(bytes(buf))
                        g["version"] = str(j.get("contentVersion") or "")
                    except (*ftplib.all_errors, ValueError):
                        m = TITLE_RE.search(it["name"])
                        g["title_id"] = m.group(0).upper() if m else ""
                        # No sce_sys/param.json here: the game may sit one folder deeper.
                        inner = []
                        for sub in [n for n, i in names.items() if i["dir"] and n not in ("sce_sys", "sce_module", "fakelib")][:8]:
                            try:
                                if "sce_sys" in {i["name"].lower() for i in ps5_ftp_list_conn(f, f"{path}/{names[sub]['name']}")}:
                                    inner.append(names[sub]["name"])
                            except ftplib.all_errors:
                                pass
                        if "sce_sys" in names:
                            try:
                                has = "param.json" in {i["name"].lower() for i in ps5_ftp_list_conn(f, f"{path}/sce_sys")}
                            except ftplib.all_errors:
                                has = False
                            g["issues"] = [{"code": "noparam", "fix": False, "text":
                                            "sce_sys/param.json is there but could not be read (damaged copy, or FTP hiccup: Refresh)"
                                            if has else "sce_sys has no param.json: an incomplete copy?"}]
                        elif len(inner) == 1:
                            g["issues"] = [{"code": "wrapper", "fix": True, "inner": inner[0],
                                            "text": f"the game is one folder deeper ({inner[0]}), where ShadowMountPlus doesn't look"}]
                        else:
                            g["issues"] = [{"code": "notgame", "fix": False,
                                            "text": "no sce_sys/param.json: not a game folder ShadowMountPlus can use"}]
                        g["attention"] = True
                    if not g["version"]:
                        g["version"] = game_version(name=it["name"]).get("version", "")
                    g["name"] = g["name"] or it["name"]
                    g["size"] = (sizes.get(path) or {}).get("bytes")
                    g["on_nas"] = [x for x in nas.get(g["title_id"].upper(), []) if x] if g["title_id"] else []
                    games.append(g)
        games += ps4_apps(f, drives)
    finally:
        try:
            f.quit()
        except Exception:
            pass
    # ShadowMountPlus mounts one copy per title ID: flag the others.
    seen = {}
    for g in games:
        if g["title_id"]:
            seen.setdefault(g["title_id"].upper(), []).append(g["path"])
    for g in games:
        others = ([p for p in seen.get(g["title_id"].upper(), []) if p != g["path"]]
                  if g["title_id"] and not g.get("ps4") else [])
        g["duplicates"] = others
        g.setdefault("issues", [])
        if others:
            g["attention"] = True
    return {"games": games, "listed": now()}


def ps4_apps(f, drives: list[str]) -> list[dict]:
    """PS4 games installed on the PS5 (/user/app/CUSAxxxxx, and on extended
    storage): name and version from their appmeta param.sfo, size of app.pkg
    and of an installed patch."""
    import ftplib
    nas = {}
    try:
        for p in scan_pkgs():
            if p.get("title_id"):
                nas.setdefault(p["title_id"].upper(), []).append(p["file"])
    except Exception:
        pass
    out = []
    roots = ["/user"] + [f"{d}/user" for d in drives if d.startswith("/mnt/ext")]
    for root in roots:
        try:
            apps = [i["name"] for i in ps5_ftp_list_conn(f, f"{root}/app") if i["dir"] and re.fullmatch(r"CUSA\d{5}", i["name"])]
        except ftplib.all_errors:
            continue
        for tid in sorted(apps):
            g = {"path": f"{root}/app/{tid}", "folder": tid, "drive": "/data" if root == "/user" else root[:-5],
                 "title_id": tid, "name": tid, "version": "", "lz4": False, "fakelib": False, "image": "",
                 "size": None, "ps4": True, "meta": "", "patch": None, "modified": "",
                 "on_nas": nas.get(tid, [])}
            for meta in (f"{root}/appmeta/{tid}", f"/system_data/priv/appmeta/{tid}"):
                buf = bytearray()
                try:
                    f.voidcmd("TYPE I")
                    f.retrbinary(f"RETR {meta}/param.sfo", buf.extend)
                except ftplib.all_errors:
                    continue
                sfo = parse_sfo(bytes(buf))
                g["name"] = str(sfo.get("TITLE") or tid)
                g["version"] = str(sfo.get("APP_VER") or sfo.get("VERSION") or "")
                g["meta"] = meta
                break
            try:
                items = {i["name"]: i for i in ps5_ftp_list_conn(f, g["path"])}
                g["size"] = (items.get("app.pkg") or {}).get("size")
                g["modified"] = (items.get("app.pkg") or {}).get("modified", "")
            except ftplib.all_errors:
                pass
            try:
                items = {i["name"]: i for i in ps5_ftp_list_conn(f, f"{root}/patch/{tid}")}
                g["patch"] = (items.get("patch.pkg") or {}).get("size")
            except ftplib.all_errors:
                pass
            out.append(g)
    return out


_verify: dict = {}


def ps5_remote_sizes(f, path: str) -> dict:
    """Every file under path on the PS5: relative path -> size (listings only)."""
    out: dict = {}

    def walk(d, rel):
        for i in ps5_ftp_list_conn(f, d):
            r = f"{rel}{i['name']}"
            if i["dir"]:
                walk(f"{d}/{i['name']}", r + "/")
            else:
                out[r] = i.get("size")
    walk(path, "")
    return out
SAMPLE_MIN = 256 << 20   # files from this size get spot checks
SAMPLE_COUNT = 4         # 1 MiB pieces read back per file (start, end, two random)


def ampr_log(path: str, limit: int = 256 << 10) -> dict:
    """The end of APR-EMU's own log in a game folder on the PS5 (/app0/ampr_emu.log),
    plus the problem lines (aborts and missing paths) picked out of it."""
    import ftplib
    path = ps5_ftp_path(path)
    if not FTP_DELETE_ROOTS.match(path):
        raise ValueError("only game folders inside /data, /mnt/usbN or /mnt/extN")
    f = ps5_ftp_connect()
    try:
        remote = f"{path}/ampr_emu.log"
        try:
            size = f.size(remote) or 0
        except ftplib.all_errors:
            return {"exists": False, "path": remote}
        data = ftp_read_at(f, remote, max(0, size - limit), limit)
    finally:
        try:
            f.quit()
        except Exception:
            pass
    text = data.decode("utf-8", "replace")
    lines = text.splitlines()[1 if size > limit else 0:]
    hits = [ln for ln in lines if re.search(r"abort|missing|not found|fail|error|ENOENT", ln, re.I)]
    return {"exists": True, "path": remote, "size": size, "lines": lines[-400:], "problems": hits[-60:]}


def ftp_read_at(f, remote: str, offset: int, n: int) -> bytes:
    """n bytes of a file on the PS5 from offset (REST + RETR, stopped early)."""
    import ftplib
    f.voidcmd("TYPE I")
    conn = f.transfercmd(f"RETR {remote}", rest=offset or None)
    buf = bytearray()
    try:
        conn.settimeout(30)
        while len(buf) < n:
            d = conn.recv(min(1 << 16, n - len(buf)))
            if not d:
                break
            buf += d
    finally:
        conn.close()
    try:
        f.voidresp()  # 226, or 426 for the early stop
    except ftplib.all_errors:
        pass
    return bytes(buf)


def spot_check(f, local: Path, remote: str) -> str | None:
    """Compare SAMPLE_COUNT 1 MiB pieces of a large file on the PS5 with the
    NAS copy: catches a damaged or misplaced write while reading back only a
    few MiB (the drive on the PS5 isn't read through). None when they match."""
    import random
    size = local.stat().st_size
    if size < SAMPLE_MIN:
        return None
    piece = 1 << 20
    offs = {0, size - piece} | {random.randrange(0, size - piece) for _ in range(SAMPLE_COUNT - 2)}
    with open(local, "rb") as fh:
        for off in sorted(offs):
            fh.seek(off)
            want = fh.read(piece)
            got = ftp_read_at(f, remote, off, len(want))
            if got != want:
                return f"bytes at {human(off)} differ"
    return None


def ps5_verify_start(path: str) -> dict:
    """Compare a game folder on the PS5 with its copy on the NAS (the LZ4 copy
    of the same name, or the library folder): every file there with the same
    size, and the program files (eboot, PRX, ELF; what ftpsrv could decrypt)
    byte for byte with SHA-256. Runs in the background; ps5_verify_status
    reports it."""
    path = ps5_ftp_path(path)
    name = path.rsplit("/", 1)[1]
    local = output_item(name)
    if not local.is_dir():
        local = next((e.path for e in scan_library() if e.path.is_dir() and e.path.name == name), None)
    if not local:
        raise ValueError(f"no folder named {name} on the NAS to compare with (only games sent from here can be verified)")
    st = _verify.get(path)
    if st and st.get("state") == "running":
        return st
    st = _verify[path] = {"state": "running", "local": str(local), "done": 0, "total": 0, "missing": [],
                          "wrong": [], "extra": [], "hashed": 0, "error": None, "started": now()}

    def run():
        import ftplib
        import hashlib
        try:
            files = sorted(q for q in local.rglob("*") if q.is_file())
            st["total"] = len(files)
            f = ps5_ftp_connect()
            try:
                remote = ps5_remote_sizes(f, path)
                for q in files:
                    rel = q.relative_to(local).as_posix()
                    st["done"] += 1
                    st["current"] = rel
                    size = q.stat().st_size
                    if rel not in remote:
                        st["missing"].append(rel)
                        continue
                    if remote[rel] is not None and remote[rel] != size:
                        st["wrong"].append(f"{rel} ({human(remote[rel])} on the PS5, {human(size)} here)")
                        continue
                    with open(q, "rb") as fh:
                        prog = fh.read(4) in PROGRAM_MAGICS
                    if not prog and size >= SAMPLE_MIN:
                        bad = spot_check(f, q, f"{path}/{rel}")
                        if bad:
                            st["wrong"].append(f"{rel} ({bad})")
                        st["sampled"] = st.get("sampled", 0) + 1
                    if prog:
                        h = hashlib.sha256()
                        f.voidcmd("TYPE I")
                        f.retrbinary(f"RETR {path}/{rel}", h.update, blocksize=1 << 20)
                        if h.hexdigest() != hashlib.sha256(q.read_bytes()).hexdigest():
                            st["wrong"].append(f"{rel} (other bytes)")
                        st["hashed"] += 1
                known = {q.relative_to(local).as_posix() for q in files}
                st["extra"] = sorted(r for r in remote if r not in known)[:50]
            finally:
                try:
                    f.quit()
                except Exception:
                    pass
            st["state"] = "done"
        except Exception as err:
            st.update(state="failed", error=str(err))
        st["current"] = ""
        st["finished"] = now()
    __import__("threading").Thread(target=run, daemon=True).start()
    return st



def ps5_fix(path: str, code: str) -> dict:
    """Fix what keeps ShadowMountPlus from seeing a game, by renaming over
    FTP (nothing is deleted but an emptied wrapper folder): "hidden" drops the
    leading dot; "wrapper" moves the game folder inside up next to it."""
    import ftplib
    path = ps5_ftp_path(path)
    if not FTP_DELETE_ROOTS.match(path):
        raise ValueError("only games inside /data, /mnt/usbN or /mnt/extN")
    base, _, name = path.rpartition("/")
    f = ps5_ftp_connect()
    try:
        have = {i["name"] for i in ps5_ftp_list_conn(f, base)}
        if code == "hidden":
            new = name.lstrip(".")
            if not new or new in have:
                raise ValueError(f"{base}/{new} already exists")
            f.rename(path, f"{base}/{new}")
            return {"renamed": f"{base}/{new}"}
        if code == "wrapper":
            inner = [i["name"] for i in ps5_ftp_list_conn(f, path) if i["dir"]
                     and "sce_sys" in {j["name"].lower() for j in ps5_ftp_list_conn(f, f"{path}/{i['name']}")}]
            if len(inner) != 1:
                raise ValueError("expected exactly one game folder inside")
            target = inner[0] if inner[0] not in have else f"{inner[0]}-moved"
            if target in have:
                raise ValueError(f"{base}/{target} already exists")
            f.rename(f"{path}/{inner[0]}", f"{base}/{target}")
            try:
                if not ps5_ftp_list_conn(f, path):
                    f.rmd(path)
            except ftplib.all_errors:
                pass
            return {"moved": f"{base}/{target}"}
        raise ValueError("nothing to fix for that")
    except ftplib.all_errors as err:
        raise ValueError(f"FTP: {err}")
    finally:
        try:
            f.quit()
        except Exception:
            pass


# Deleting is allowed only inside these, and never the drive or its top folders.
FTP_DELETE_ROOTS = re.compile(r"^/(data|mnt/(usb|ext)\d+)/[^/]+")
# Folders directly in /data that the jailbreak, payloads and homebrew need:
# only what is inside them can be deleted.
FTP_KEEP = {"etahen", "pldmgr", "homebrew", "shadowmount", "lz4compression", "goldhen", "payloads",
            "kstuff", "elfldr", "websrv", "ftpsrv", "itemzflow", "toolbox", "app", "system_data"}


def ps5_ftp_delete(path: str) -> dict:
    """Delete a file, or a folder with everything in it, on the PS5."""
    import ftplib
    path = ps5_ftp_path(path)
    if not FTP_DELETE_ROOTS.match(path):
        raise ValueError("only files and folders inside /data, /mnt/usbN or /mnt/extN can be deleted here")
    if path.count("/") == 2 and path.startswith("/data/") and path.rsplit("/", 1)[1].lower() in FTP_KEEP:
        raise ValueError(f"{path} is needed by the jailbreak, payloads or homebrew; delete what is inside it instead")
    # Other folders can go while a transfer runs. If the folder is the game
    # being sent, that transfer is stopped first; queued sends of it are dropped.
    inside = lambda t: (t.get("dest", "").partition("/")[2] and
                        ("/" + t["dest"].partition("/")[2] + "/").startswith(path + "/"))
    run = transfer_running()
    if run and inside(run):
        try:
            os.kill(int(run["pid"]), signal.SIGTERM)
        except (OSError, ValueError, KeyError):
            pass
        for _ in range(20):
            if not transfer_running():
                break
            time.sleep(0.5)
    cfg_dest = get_settings()["ps5_dest"].rstrip("/")
    transfer_queue_set([g for g in transfer_queue() if not (cfg_dest + "/" + g + "/").startswith(path + "/")])
    f = ps5_ftp_connect()
    count = {"files": 0, "folders": 0}

    def dele(p):
        # ftpsrv answers DELE with 226, which ftplib.delete() (250 or 200
        # only) takes for an error after the file is gone; any 2xx is fine.
        resp = f.sendcmd("DELE " + p)
        if not resp.startswith("2"):
            raise ftplib.error_reply(resp)

    def entries(p):
        """LIST (not MLSD): it marks symlinks, which are removed, never followed."""
        lines = []
        f.retrlines(f"LIST {p}", lines.append)
        out = []
        for line in lines:
            m = LIST_RE.match(line)
            if m and m.group(4).split(" -> ")[0] not in (".", ".."):
                out.append((m.group(4).split(" -> ")[0], m.group(1)))
        return out

    def rm_tree(p, kind):
        if kind != "d":
            dele(p)
            count["files"] += 1
            return
        for name, k in entries(p):
            rm_tree(f"{p}/{name}", k)
        f.voidcmd("RMD " + p)
        count["folders"] += 1

    parent, name = path.rsplit("/", 1)
    kind = next((k for n, k in entries(parent) if n == name), None)
    if kind is None:
        f.quit()
        raise ValueError(f"{path} is not on the PS5")
    # The game's Title ID, so its home screen tile can go too.
    tid = ""
    if kind == "d":
        buf = bytearray()
        try:
            f.voidcmd("TYPE I")
            f.retrbinary(f"RETR {path}/sce_sys/param.json", buf.extend)
            tid = parse_param_json(bytes(buf))[0].upper()
        except ftplib.all_errors:
            pass
    elif name.lower().endswith((".exfat", ".ffpfs", ".ffpfsc")):
        m = TITLE_RE.search(name)
        tid = m.group(0).upper() if m else ""

    try:
        rm_tree(path, kind)
    except ftplib.all_errors as err:
        raise ValueError(f"stopped after {count['files']} files: {err}")
    finally:
        try:
            f.quit()
        except Exception:
            pass
    # The game is no longer on the PS5: forget its transfer record.
    for t in transfer_files():
        st = read_json(t, {}) or {}
        if isinstance(st, dict) and st.get("state") != "running" and inside(st):
            t.unlink(missing_ok=True)
    return {"deleted": path, **count, **({"home_screen": untile(tid)} if tid else {})}


def ps5_uninstall(tid: str) -> str:
    """Uninstall an installed app (a PS4 game in /user/app) through pkg-receiver."""
    import urllib.request
    tid = tid.upper()
    if not re.fullmatch(r"CUSA\d{5}|PPSA\d{5}", tid):
        raise ValueError("bad Title ID")
    host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
    try:
        req = urllib.request.Request(f"http://{host}:{RECV_PORT}/api/uninstall?tid={tid}", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            j = json.load(r)
    except Exception as err:
        raise ValueError(f"pkg-receiver (Glass build 6 or newer) does not answer on the PS5: {err}")
    if not j.get("ok"):
        raise ValueError(f"the PS5 refused: {j.get('error') or j.get('rc')}")
    return "uninstalled"


# Save data backups (idea from P5 Manager): the PS5's save folders, read over
# FTP into state/saves/<date>/<user>/<kind>/<TITLE>/, with a manifest. Only
# reading on the PS5; a restore writes one title's folder back.
SAVES = STATE / "saves"
SAVE_KINDS = ("savedata_prospero", "savedata")  # PS5, PS4
_saves_job: dict = {}


def title_names() -> dict:
    names = {}
    try:
        for e in scan_library():
            if e.title_id and e.name:
                names.setdefault(e.title_id.upper(), e.name)
    except Exception:
        pass
    try:
        for p in scan_pkgs():
            if p.get("title_id") and p.get("name") and p.get("category") == "Game":
                names.setdefault(p["title_id"].upper(), p["name"])
    except Exception:
        pass
    return names


def saves_backup_start(only: str = "") -> dict:
    """Copy every save folder on the PS5 (or only one Title ID's) to the NAS, in the background."""
    if _saves_job.get("state") == "running":
        return _saves_job
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    _saves_job.clear()
    _saves_job.update(state="running", backup=stamp, files=0, bytes=0, titles=0, current="", error=None, started=now())

    def run():
        import ftplib
        dest = SAVES / stamp
        manifest = {"created": now(), "ps5": get_settings().get("ps5_ftp"), "titles": {}}
        names = title_names()
        try:
            f = ps5_ftp_connect()
            try:
                users = [u for u in (ps5_ftp_names(f, "/user/home") or []) if re.fullmatch(r"[0-9a-fA-F]{8}", u)]
                if not users:
                    raise ValueError("no users in /user/home on the PS5 (is ftpsrv running with full access?)")
                for uid in users:
                    for kind in SAVE_KINDS:
                        base = f"/user/home/{uid}/{kind}"
                        try:
                            tids = [i["name"] for i in ps5_ftp_list_conn(f, base) if i["dir"]]
                        except ftplib.all_errors:
                            continue
                        for tid in sorted(tids):
                            if only and tid.upper() != only.upper():
                                continue
                            _saves_job["current"] = f"{tid} ({uid})"
                            files = ps5_remote_sizes(f, f"{base}/{tid}")
                            n = b = 0
                            for rel in sorted(files):
                                local = dest / uid / kind / tid / rel
                                local.parent.mkdir(parents=True, exist_ok=True)
                                with open(local, "wb") as fh:
                                    f.voidcmd("TYPE I")
                                    f.retrbinary(f"RETR {base}/{tid}/{rel}", fh.write, blocksize=1 << 20)
                                size = local.stat().st_size
                                if files[rel] is not None and size != files[rel]:
                                    raise ValueError(f"{tid}/{rel}: got {size} bytes, the PS5 lists {files[rel]}")
                                n += 1
                                b += size
                                _saves_job["files"] += 1
                                _saves_job["bytes"] += size
                            if not names.get(tid.upper()):
                                for meta in (f"/user/appmeta/{tid}/param.sfo", f"/system_data/priv/appmeta/{tid}/param.sfo",
                                             f"/system_data/priv/appmeta/{tid}/param.json", f"/user/app/{tid}/sce_sys/param.json"):
                                    buf = bytearray()
                                    try:
                                        f.voidcmd("TYPE I")
                                        f.retrbinary(f"RETR {meta}", buf.extend)
                                    except ftplib.all_errors:
                                        continue
                                    nm = parse_sfo(bytes(buf)).get("TITLE") if meta.endswith(".sfo") else parse_param_json(bytes(buf))[1]
                                    if nm:
                                        names[tid.upper()] = str(nm)
                                        break
                            manifest["titles"][f"{uid}/{kind}/{tid}"] = {
                                "title_id": tid, "user": uid, "kind": kind, "platform": "PS5" if kind == "savedata_prospero" else "PS4",
                                "name": names.get(tid.upper(), ""), "files": n, "bytes": b}
                            _saves_job["titles"] += 1
            finally:
                try:
                    f.quit()
                except Exception:
                    pass
            if not manifest["titles"]:
                raise ValueError("no save folders found on the PS5")
            write_json(dest / "manifest.json", manifest)
            _saves_job.update(state="done", finished=now(), current="")
            notify("Saves backed up", f"{_saves_job['titles']} titles, {human(_saves_job['bytes'])} on the NAS ({stamp})")
        except Exception as err:
            if dest.is_dir():
                write_json(dest / "manifest.json", {**manifest, "incomplete": str(err)})
            _saves_job.update(state="failed", error=str(err), current="")
    __import__("threading").Thread(target=run, daemon=True).start()
    return _saves_job


def saves_list() -> list[dict]:
    out = []
    if SAVES.is_dir():
        for d in sorted(SAVES.iterdir(), reverse=True):
            m = read_json(d / "manifest.json", None)
            if not isinstance(m, dict):
                continue
            titles = list((m.get("titles") or {}).values())
            out.append({"backup": d.name, "created": m.get("created"), "incomplete": m.get("incomplete"),
                        "titles": sorted(titles, key=lambda t: (t.get("name") or t["title_id"]).lower()),
                        "bytes": sum(t.get("bytes", 0) for t in titles)})
    return out


def saves_backup_dir(backup: str) -> Path:
    if not re.fullmatch(r"[0-9_-]{10,20}", backup) or not (SAVES / backup / "manifest.json").is_file():
        raise ValueError("no such backup")
    return SAVES / backup


def saves_restore(backup: str, key: str) -> dict:
    """Write one title's saves from a backup back to the same place on the PS5
    (same user, same folder). Close the game first."""
    import ftplib
    d = saves_backup_dir(backup)
    t = (read_json(d / "manifest.json", {}) or {}).get("titles", {}).get(key)
    if not t:
        raise ValueError("that title is not in the backup")
    src = d / key
    remote = f"/user/home/{key}"
    files = sorted(p for p in src.rglob("*") if p.is_file())
    f = ps5_ftp_connect()
    try:
        made = set()
        for p in files:
            rel = p.relative_to(src).as_posix()
            parent = f"{remote}/{rel}".rsplit("/", 1)[0]
            if parent not in made:
                ps5_ftp_mkdirs(f, parent)
                made.add(parent)
            with open(p, "rb") as fh:
                f.voidcmd("TYPE I")
                f.storbinary(f"STOR {remote}/{rel}", fh, blocksize=1 << 20)
        got = ps5_remote_sizes(f, remote)
        bad = [p.relative_to(src).as_posix() for p in files if got.get(p.relative_to(src).as_posix()) != p.stat().st_size]
        if bad:
            raise ValueError(f"{len(bad)} file(s) did not arrive whole (e.g. {bad[0]}); try again")
    except ftplib.all_errors as err:
        raise ValueError(f"FTP: {err}")
    finally:
        try:
            f.quit()
        except Exception:
            pass
    ps5_notify(f"NAS: saves of {t.get('name') or t['title_id']} restored")
    return {"restored": key, "files": len(files)}


def saves_zip(h, backup: str) -> None:
    """Send a backup as a .zip download (written straight to the connection)."""
    import zipfile
    d = saves_backup_dir(backup)
    h.send_response(200)
    h.send_header("Content-Type", "application/zip")
    h.send_header("Content-Disposition", f'attachment; filename="ps5-saves-{backup}.zip"')
    h.end_headers()
    h.close_connection = True
    with zipfile.ZipFile(h.wfile, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(d).as_posix())


def metrics_text() -> str:
    """Prometheus metrics (idea from ps5-exporter): the library, packing,
    transfers, downloads by the PS5 and save backups; GET /metrics."""
    out = []

    def m(name, help_, value, labels=""):
        out.append(f"# HELP ps5lz4_{name} {help_}\n# TYPE ps5lz4_{name} gauge\nps5lz4_{name}{labels} {value}")
    reports = [read_json(f, {}) or {} for f in (REPORTS.glob("*.json") if REPORTS.is_dir() else [])]
    m("lz4_games", "LZ4 games packed and verified on the NAS", len([r for r in reports if r.get("finished")]))
    m("saved_bytes", "bytes saved by LZ4 packing", sum(r.get("saved_bytes") or 0 for r in reports))
    m("job_running", "1 while a packing job runs", 1 if job_running()[0] else 0)
    xs = [read_json(f, {}) or {} for f in transfer_files()]
    m("transfer_running", "1 while a transfer to the PS5 runs", 1 if any(x.get("state") == "running" for x in xs) else 0)
    m("transfer_queue", "games waiting to be sent to the PS5", len(transfer_queue()))
    m("transfers_failed", "transfers that ended failed", len([x for x in xs if x.get("state") == "failed"]))
    dl = dl_snapshot()
    m("ps5_downloads_active", "packages or images the PS5 is downloading from the NAS",
      len([d for d in dl if d["status"] == "downloading"]))
    m("ps5_download_rate_bytes", "bytes per second the PS5 downloads from the NAS", sum(d["rate"] for d in dl))
    m("save_backups", "save data backups on the NAS", len([d for d in SAVES.iterdir() if d.is_dir()]) if SAVES.is_dir() else 0)
    return "\n".join(out) + "\n"


def ps5_notify(text: str, wait: bool = False) -> None:
    """A notification on the PS5 (pkg-receiver Glass build 7+, /api/notify);
    best effort, in the background (wait: up to 5 s, for a process about to end)."""
    import urllib.request
    host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
    if not host:
        return

    def send():
        try:
            req = urllib.request.Request(f"http://{host}:{RECV_PORT}/api/notify", data=text[:200].encode(),
                                         method="POST", headers={"Content-Type": "text/plain"})
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:
            pass
    t = __import__("threading").Thread(target=send, daemon=True)
    t.start()
    if wait:
        t.join(5)


def smp(route: str, body: dict | None = None, timeout: float = 30) -> dict:
    """ShadowMountPlus's API (on the PS5 at 127.0.0.1:10101), through
    pkg-receiver's Glass build (7 or newer). Raises ValueError with SMP's error."""
    import urllib.error
    import urllib.request
    host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
    if not host:
        raise ValueError("set the PS5 address first")
    req = urllib.request.Request(f"http://{host}:{RECV_PORT}/api/smp?route={route}",
                                 data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except (urllib.error.URLError, OSError) as err:
        raise ValueError(f"pkg-receiver (Glass build 7 or newer) does not answer on the PS5: {err}")
    try:
        j = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise ValueError("pkg-receiver is too old for ShadowMount (install the newest ELF)")
    if j.get("status"):
        raise ValueError(f"ShadowMountPlus: {j.get('error') or j.get('status')}"
                         + (f" ({j['error_reason']})" if j.get("error_reason") else ""))
    return j


BACKPORT_ROOTS = [f"{d}/{s}" for d in ("/data", "/mnt/ext0", "/mnt/ext1", "/mnt/usb0", "/mnt/usb1")
                  for s in ("homebrew", "etaHEN/games")]


def launch_check(tid: str) -> dict:
    """What would stop an LZ4 game from starting on the PS5 (idea from
    exFAT2AMPR's launch check): ShadowMountPlus's fakelib turned off for it,
    APR-EMU missing from fakelib/, a fakelib2/ without APR-EMU (it replaces
    fakelib/ as a whole), eboot.bin not executable, and a backport whose own
    libSceAmpr ShadowMountPlus lays over the emulator. Read through
    ShadowMountPlus's API and FTP; what can't be read is said, not guessed."""
    import ftplib
    tid = tid.strip().upper()
    if not re.fullmatch(r"(PPSA|CUSA)\d{5}", tid):
        raise ValueError("not a title ID")
    errors, warnings, notes = [], [], []
    root = ""
    try:
        j = smp("/api/v1/games/info", {"title_id": tid}, timeout=30)
        g = j.get("game") if isinstance(j.get("game"), dict) else j
        if str(g.get("fakelib_mode") or "").lower() == "disabled" or g.get("fakelib_effective_enabled") is False:
            errors.append("ShadowMountPlus has fakelib turned off for this game, so APR-EMU never loads: "
                          "turn fakelib on for it in ShadowMountPlus")
        root = str(g.get("runtime_path") or (g.get("path") if g.get("source_type") == "folder" else "") or "")
        if not root:
            notes.append("ShadowMountPlus has the game but not mounted, so its files can't be checked: mount it and check again")
    except ValueError as err:
        notes.append(f"ShadowMountPlus: {err}")
    try:
        f = ps5_ftp_connect()
    except ValueError as err:
        notes.append(str(err))
        return {"title_id": tid, "errors": errors, "warnings": warnings, "notes": notes, "root": root}
    try:
        if root:
            names = ps5_ftp_names(f, root)
            low = {n.lower() for n in names or []}
            if names is None:
                notes.append(f"{root} can't be read over FTP")
            elif not {"ampr_assets.index", "ampr_zstd.index"} & low:
                notes.append("not an AMPR packed game: no LZ4 or zstd index")
            else:
                fl = {n.lower() for n in ps5_ftp_names(f, f"{root}/fakelib") or []}
                if "libsceampr.sprx" not in fl:
                    errors.append("APR-EMU is missing: no fakelib/libSceAmpr.sprx in the game")
                if "fakelib2" in low:
                    fl2 = {n.lower() for n in ps5_ftp_names(f, f"{root}/fakelib2") or []}
                    if "libsceampr.sprx" not in fl2:
                        errors.append("fakelib2/ has no libSceAmpr.sprx: fakelib2 replaces fakelib as a whole, "
                                      "so the game starts without APR-EMU (copy fakelib/libSceAmpr.sprx into it)")
                lines: list[str] = []
                try:
                    f.retrlines(f"LIST {root}", lines.append)
                except ftplib.all_errors:
                    pass
                for line in lines:
                    m = LIST_RE.match(line)
                    if m and m.group(4) == "eboot.bin" and "x" not in line.split()[0]:
                        warnings.append("eboot.bin has no execute permission on the PS5 (FTP shows "
                                        f"{line.split()[0]}); if the game doesn't start, set it to 755")
        for d in BACKPORT_ROOTS:
            bp = f"{d}/backports/{tid}/fakelib"
            for n in ps5_ftp_names(f, bp) or []:
                if n.lower() in ("libsceampr.sprx", "libsceampr.prx"):
                    errors.append(f"the backport {bp}/{n} brings its own AMPR library: ShadowMountPlus lays it "
                                  "over APR-EMU and the LZ4 game can't read its packs (remove that file from the backport)")
    finally:
        try:
            f.quit()
        except Exception:
            pass
    return {"title_id": tid, "errors": errors, "warnings": warnings, "notes": notes, "root": root}


def smp_hide(path: str) -> str:
    """Rename a game source with a leading dot, so ShadowMountPlus's scans skip it."""
    import ftplib
    path = ps5_ftp_path(path)
    if not FTP_DELETE_ROOTS.match(path):
        raise ValueError("only games inside /data, /mnt/usbN or /mnt/extN")
    base, _, name = path.rpartition("/")
    if name.startswith("."):
        return path
    f = ps5_ftp_connect()
    try:
        if "." + name in {i["name"] for i in ps5_ftp_list_conn(f, base)}:
            raise ValueError(f"{base}/.{name} already exists")
        f.rename(path, f"{base}/.{name}")
    except ftplib.all_errors as err:
        raise ValueError(f"FTP: {err}")
    finally:
        try:
            f.quit()
        except Exception:
            pass
    return f"{base}/.{name}"


def untile(tid: str) -> str:
    """Take a deleted game's tile off the PS5 home screen (pkg-receiver's
    Glass build: sceAppInstUtilAppUnInstall), unless another copy with that
    Title ID is still in a game folder (ShadowMountPlus would show it again)."""
    import ftplib
    import urllib.request
    if not re.fullmatch(r"PPSA\d{5}|CUSA\d{5}", tid):
        return "kept (no Title ID)"
    try:
        f = ps5_ftp_connect()
        try:
            mnt = ps5_ftp_names(f, "/mnt") or []
            for drive in ["/data"] + [f"/mnt/{n}" for n in mnt if re.fullmatch(r"(usb|ext)\d+", n)]:
                for sub in GAME_DIRS:
                    try:
                        names = ps5_ftp_names(f, f"{drive}/{sub}") or []
                    except ftplib.all_errors:
                        continue
                    if any(tid in n.upper() for n in names):
                        return f"kept: another copy of {tid} is in {drive}/{sub}"
        finally:
            try:
                f.quit()
            except Exception:
                pass
    except ValueError:
        pass
    try:
        smp("/api/v1/games/uninstall", {"title_id": tid})
        print(f"[{now()}] {tid} taken off the PS5 home screen (ShadowMountPlus)", flush=True)
        return "removed"
    except ValueError:
        pass  # older SMP or receiver: AppInstUtil directly
    host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
    try:
        req = urllib.request.Request(f"http://{host}:{RECV_PORT}/api/uninstall?tid={tid}", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.load(r)
    except Exception:
        return "not removed: start pkg-receiver (Glass build 6 or newer) and delete again, or remove the tile on the PS5"
    if j.get("ok"):
        print(f"[{now()}] {tid} taken off the PS5 home screen", flush=True)
        return "removed"
    return f"not removed: {j.get('error') or j.get('rc')}"


def ftp_open(host: str, port: int, timeout: float = 3) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ps5_pair(pin: str, account_id: str) -> dict:
    """Remote Play pairing like Chiaki (ps5regist.py, AGPL); stores the keys."""
    sys.path.insert(0, str(Path(__file__).parent))
    import ps5regist
    host = get_settings()["ps5_ftp"].partition(":")[0]
    if not host:
        raise ValueError("set the PS5 address first")
    try:
        res = ps5regist.register(host, pin, account_id)
    except ps5regist.RegistError as err:
        raise ValueError(str(err))
    except OSError as err:
        raise ValueError(f"no connection to the PS5 at {host}: {err}")
    stored = read_json(SETTINGS_PATH, {}) or {}
    stored.update(ps5_wake_key=res["regist_key"], ps5_rp_key=res["rp_key"], ps5_mac=res["mac"],
                  ps5_nickname=res["nickname"], ps5_paired=now())
    write_settings(stored)
    return {"nickname": res["nickname"], "mac": res["mac"], "paired": stored["ps5_paired"]}


def cmd_pair(args) -> int:
    try:
        res = ps5_pair(args.pin, args.account_id)
    except ValueError as err:
        raise SystemExit(f"pairing failed: {err}")
    print(f"paired with {res['nickname'] or 'the PS5'} ({res['mac']}); it can now be woken from rest mode")
    return 0


def cmd_wake(_args) -> int:
    cfg = get_settings()
    host = cfg["ps5_ftp"].partition(":")[0]
    if not host or not cfg["ps5_wake_key"]:
        raise SystemExit("set the PS5 address and the Remote Play key first (web page: Send to PS5)")
    print(f"PS5 is {ps5_status(host)}; sending wake-up")
    ps5_wake(host, cfg["ps5_wake_key"])
    return 0


def transfer_files() -> list[Path]:
    return [f for f in TRANSFERS.glob("*.json") if f.name != "queue.json"] if TRANSFERS.is_dir() else []


def transfer_running() -> dict | None:
    for f in transfer_files():
        st = read_json(f, {}) or {}
        if not isinstance(st, dict):
            continue
        if st.get("state") == "running":
            try:
                os.kill(int(st.get("pid", 0)), 0)
                return st
            except (OSError, ValueError):
                st.update(state="failed", error="interrupted (container restarted?); press again to resume")
                write_json(f, st)
    return None


def output_for(game: str) -> Path:
    """Resolve a library id/name or an LZ4 folder name to the LZ4 folder."""
    for name in (game, f"{game}-lz4", f"{safe_name(game)}-lz4", f"{game}-zstd", f"{safe_name(game)}-zstd"):
        cand = output_item(name)
        if cand.is_dir() and is_packed(cand) and cand.parent in output_roots():
            return cand
    for e in scan_library():
        if game in (e.id, e.rel, e.title_id) and e.output.is_dir():
            return e.output
    raise SystemExit(f"no finished LZ4 folder for {game!r} in {OUTPUT}")


# --------------------------------------------------------------------------
# exFAT images: an LZ4 copy as one .exfat file (some games only start from an
# image), checked byte for byte against the LZ4 folder. One at a time; the
# progress is in state/images so the page (another container) can show it.
# Originals in the library are never converted or touched.

IMAGES = STATE / "images"
IMAGES_LOCK = STATE / "images.lock"
IMAGE_STOP = IMAGES / "stop"


class ImageStopped(Exception):
    """Stop pressed on the page."""


def image_state(key: str, **st) -> None:
    IMAGES.mkdir(parents=True, exist_ok=True)
    p = IMAGES / f"{key}.json"
    cur = read_json(p, {}) or {}
    cur.update(st, updated=time.time())
    write_json(p, cur)


def exfat_build(src: Path, final: Path, key: str, tmpdir: Path, state=None) -> int:
    """Pack folder src into the image final (through tmpdir on the same disk),
    then compare every file in the image with src byte for byte. Returns the
    image size. On failure the half-made image stays in tmpdir."""
    from mkpfs.exfat import ExfatReader  # pinned MkPFS 1.1.0
    st = state or (lambda **kw: image_state(key, **kw))
    links = [p for p in src.rglob("*") if p.is_symlink()]
    if links:
        raise SystemExit(f"{src.name} has symlinks ({links[0].relative_to(src)}); exFAT can't hold them")
    files = {str(p.relative_to(src)): p for p in sorted(src.rglob("*")) if p.is_file()}
    total = sum(p.stat().st_size for p in files.values())
    need = int(total * 1.03) + (1 << 30)
    tmpdir.mkdir(parents=True, exist_ok=True)
    if free_bytes(tmpdir) < need:
        raise SystemExit(f"not enough free space for the image: {human(need)} needed, "
                         f"{human(free_bytes(tmpdir))} free")
    tmp = tmpdir / final.name
    st(state="running", phase="building the image", done=0, total=total,
                source=str(src), image=str(final), started=now(), error=None)
    with open(tmpdir / "mkpfs.log", "w") as log:
        proc = subprocess.Popen([MKPFS, "pack", "exfat", "--no-progress", "--overwrite", str(src), str(tmp)],
                                stdout=log, stderr=subprocess.STDOUT)
        while proc.poll() is None:
            time.sleep(3)
            try:
                got = tmp.stat().st_blocks * 512
            except OSError:
                got = 0
            st(done=min(got, total))
            if IMAGE_STOP.exists():
                proc.terminate()
                proc.wait()
                raise ImageStopped()
    if proc.returncode != 0:
        tail = (tmpdir / "mkpfs.log").read_text(errors="replace")[-600:]
        raise SystemExit(f"MkPFS could not build the image: {tail.strip()}")
    # Check: the same files, the same sizes, the same bytes.
    st(phase="checking the image byte for byte", done=0, total=total)
    done = 0
    last = time.time()
    with open(tmp, "rb") as fh:
        reader = ExfatReader(fh)
        inside = {e.rel_path: e for e in reader.iter_files()}
        missing = sorted(set(files) - set(inside))
        extra = sorted(set(inside) - set(files))
        if missing or extra:
            raise SystemExit(f"the image doesn't hold the same files (missing: {missing[:3]}, extra: {extra[:3]})")
        for rel, p in files.items():
            e = inside[rel]
            if e.length != p.stat().st_size:
                raise SystemExit(f"{rel}: {e.length} bytes in the image, {p.stat().st_size} in the folder")
            with open(p, "rb") as f:
                for chunk in reader.read_file(e):
                    if f.read(len(chunk)) != chunk:
                        raise SystemExit(f"{rel} differs between the image and the folder")
                    done += len(chunk)
                    if time.time() - last > 3:
                        last = time.time()
                        st(done=done)
                        if IMAGE_STOP.exists():
                            raise ImageStopped()
                if f.read(1):
                    raise SystemExit(f"{rel} is shorter in the image than in the folder")
    size = tmp.stat().st_size
    os.replace(tmp, final)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return size


# RAR archives in the library (a game as name.part1.rar, name.part2.rar, ...
# or name.rar + name.r00, ...): extracted with unrar (CRC of every file
# checked) into a hidden temp folder in LIBRARY/_extracted, packed into a
# checked .exfat image there, and the temp folder removed. The archives stay
# unless deleted on purpose (DELETE_ORIGINALS=yes).
EXTRACTED = LIBRARY / "_extracted"
EXTRACTS = STATE / "extract"
_RAR_PART = re.compile(r"^(.*)\.part0*(\d+)\.rar$", re.I)
_RAR_OLD = re.compile(r"^(.*)\.r(\d\d)$", re.I)


def rar_sets(d: Path) -> list[dict]:
    """The RAR sets in folder d: base name, first volume, every volume."""
    sets: dict = {}
    files = []
    try:
        for p in d.iterdir():
            try:
                if not p.name.startswith(".") and p.is_file():
                    files.append(p)
            except OSError:
                continue
    except OSError:
        return []
    for p in files:
        m = _RAR_PART.match(p.name)
        if m:
            sets.setdefault(m.group(1), {"vols": []})["vols"].append((int(m.group(2)), p))
            continue
        m = _RAR_OLD.match(p.name)
        if m:
            sets.setdefault(m.group(1), {"vols": []})["vols"].append((int(m.group(2)) + 2, p))
        elif p.suffix.lower() == ".rar":
            sets.setdefault(p.stem, {"vols": []})["vols"].append((1, p))
    out = []
    for base, v in sorted(sets.items()):
        vols = [p for _, p in sorted(v["vols"], key=lambda x: x[0])]
        if vols[0].suffix.lower() != ".rar":
            continue  # .r00 parts without their .rar
        out.append({"base": base, "first": vols[0], "vols": vols})
    return out


def extract_key(first: Path) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(first.relative_to(LIBRARY)))[:150]


def _ver_key(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")) or (-1,)


def _safe(fn, default):
    """Extra page data that must never take the whole page down."""
    try:
        return fn()
    except Exception as err:
        print(f"[{now()}] {fn.__name__}: {err}", flush=True)
        return default


def library_duplicates() -> list[dict]:
    """Games in the library more than once with the same Title ID (another
    version, or a folder and an image of it): each copy with its version and
    size, the newest marked; the page suggests deleting the others."""
    groups: dict = {}
    for e in scan_library():
        if e.title_id:
            groups.setdefault(e.title_id.upper(), []).append(e)
    out = []
    for tid, es in sorted(groups.items()):
        if len(es) < 2:
            continue
        items = []
        for e in es:
            if e.kind == "folder":
                ver = game_version(e.path).get("version", "")
                size = None  # the page takes it from the library list
            else:
                ver = game_version(name=e.path.name).get("version", "") or (image_meta(e.path).get("version") or "")
                size = e.path.stat().st_size
            items.append({"id": e.id, "rel": e.rel, "kind": e.kind, "version": ver, "size": size,
                          "used": not e.duplicate_of,
                          "path": str(Path(HOST_LIBRARY) / e.rel),
                          "lz4": e.output.is_dir() and is_packed(e.output)})
        newest = max(items, key=lambda i: (_ver_key(i["version"]), i["kind"] == "folder"))
        for i in items:
            i["newest"] = i is newest
        out.append({"title_id": tid, "name": next((e.name for e in es if e.name), es[0].rel), "items": items,
                    "chosen": (read_json(PREFERRED, {}) or {}).get(tid)})
    return out


def scan_archives() -> list[dict]:
    out = []
    if not LIBRARY.is_dir():
        return out

    def walk(d: Path, depth: int):
        sets = rar_sets(d)
        for st in sets:
            key = extract_key(st["first"])
            try:
                size = sum(p.stat().st_size for p in st["vols"])
            except OSError:
                size = None
            out.append({"id": str(st["first"].relative_to(LIBRARY)), "dir": str(d.relative_to(LIBRARY)),
                        "name": d.name if d != LIBRARY and len(sets) == 1 else st["base"],
                        "parts": len(st["vols"]), "size": size,
                        "state": (stj := read_json(EXTRACTS / f"{key}.json", None)),
                        "tested": bool(stj and stj.get("image") and tested_ok(safe_name(Path(stj["image"]).stem)))})
        if depth >= 3:
            return
        try:
            kids = sorted(d.iterdir())
        except OSError:
            return
        for p in kids:
            try:
                if p.name.startswith(".") or not p.is_dir() or p == EXTRACTED or (p / "eboot.bin").is_file():
                    continue
            except OSError:  # a folder this container may not read
                continue
            walk(p, depth + 1)
    walk(LIBRARY, 0)
    return out


def rar_set_for(rel: str) -> dict:
    first = (LIBRARY / rel).resolve()
    if not under(first, LIBRARY.resolve()) or not first.is_file():
        raise SystemExit(f"{rel} is not an archive in the library")
    st = next((x for x in rar_sets(first.parent) if x["first"].resolve() == first), None)
    if not st:
        raise SystemExit(f"{rel} is not the first part of a RAR archive")
    return st


def cmd_extract(args) -> int:
    """Extract a RAR archive from the library and make a checked .exfat of the game in it."""
    ensure_dirs()
    st = rar_set_for(args.archive)
    first = st["first"]
    key = extract_key(first)
    state_p = EXTRACTS / f"{key}.json"
    EXTRACTS.mkdir(parents=True, exist_ok=True)

    def state(**kw):
        cur = read_json(state_p, {}) or {}
        cur.update(kw, updated=time.time())
        write_json(state_p, cur)
    lock = open(EXTRACTS / ".lock", "a+")
    tmp = EXTRACTED / f".{key}.partial"
    try:
        if not shutil.which("unrar"):
            raise SystemExit("unrar is missing in this container: update it (./lz4-ps5.sh update)")
        if not EXTRACTED.is_dir() or not os.access(EXTRACTED, os.W_OK):
            raise SystemExit("the _extracted folder in the library is not writable here: run the install "
                             "script again once (it creates and mounts it)")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("another archive is being extracted; wait for it")
        # Size inside the archive: the last line of `unrar l` is the total.
        lst = subprocess.run(["unrar", "l", "-p-", str(first)], capture_output=True, text=True)
        tail = [l for l in lst.stdout.splitlines() if l.strip()]
        m = re.match(r"\s*(\d+)\s", tail[-1]) if tail else None
        total = int(m.group(1)) if m else sum(p.stat().st_size for p in st["vols"])
        need = int(total * 2.05) + (2 << 30)  # the folder and the image, a while both
        if free_bytes(EXTRACTED) < need:
            raise SystemExit(f"not enough free space in {EXTRACTED}: {human(need)} needed "
                             f"(the game and its image), {human(free_bytes(EXTRACTED))} free")
        state(state="running", phase="extracting", done=0, total=total, archive=args.archive,
              started=now(), error=None, image=None)
        tmp.mkdir(parents=True, exist_ok=True)
        log = LOGS / f"extract-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        with open(log, "w") as fh:
            proc = subprocess.Popen(["unrar", "x", "-o+", "-y", "-p-", str(first), str(tmp) + "/"],
                                    stdout=fh, stderr=subprocess.STDOUT)
            while proc.poll() is None:
                time.sleep(3)
                got = sum(p.stat().st_size for p in tmp.rglob("*") if p.is_file())
                state(done=min(got, total))
        if proc.returncode != 0:
            raise SystemExit(f"unrar failed (code {proc.returncode}; CRC or missing part?): "
                             f"{log.read_text(errors='replace')[-400:].strip()}")
        # The game folder inside: the one with sce_sys/param.json (or eboot.bin).
        cands = [p.parent.parent for p in tmp.rglob("sce_sys/param.json")] or [p.parent for p in tmp.rglob("eboot.bin")]
        cands = sorted(set(cands), key=lambda p: len(p.parts))
        if not cands:
            # Already an image (.exfat/.ffpfs/.ffpfsc) or a package (.pkg): move it
            # into _extracted as it is (the library lists it from there).
            keep = [p for p in tmp.rglob("*") if p.is_file() and p.suffix.lower() in (*IMAGE_EXTS, ".pkg")]
            if not keep:
                raise SystemExit("no PS5 game (a folder with sce_sys/param.json, an image or a .pkg) inside the "
                                 f"archive; it was extracted to {tmp.name} in {EXTRACTED} and left there")
            moved = {}
            for p in keep:
                dest = EXTRACTED / p.name
                if p.suffix.lower() in IMAGE_EXTS and BARE_TID_RE.fullmatch(p.stem):
                    # "PPSA12345.exfat" says nothing: name it after the game inside.
                    meta = _safe(lambda: image_meta(p), {}) or {}
                    title = re.sub(r'[\\/:*?"<>|]+', " ", meta.get("title") or "").strip()
                    if title and not BARE_TID_RE.fullmatch(title):
                        tid = meta.get("title_id") or TITLE_RE.search(p.stem).group(0).upper()
                        dest = EXTRACTED / f"{title} [{tid}]{p.suffix}"
                if dest.exists():
                    raise SystemExit(f"{dest.name} already exists in {EXTRACTED}")
                os.replace(p, dest)
                moved[p.relative_to(tmp).as_posix()] = dest.name
            shutil.rmtree(tmp)
            size = sum((EXTRACTED / n).stat().st_size for n in moved.values())
            state(state="done", phase="", done=size, total=size, finished=now(), moved=moved,
                  image=str(Path(HOST_LIBRARY) / "_extracted" / next(iter(moved.values()))))
            print(f"moved {', '.join(moved.values())} from the archive into {EXTRACTED.name} "
                  "(unrar checked every file's CRC); the RAR files are unchanged")
            return 0
        game = cands[0]
        tid, title = ("", "")
        if (game / "sce_sys" / "param.json").is_file():
            tid, title = parse_param_json((game / "sce_sys" / "param.json").read_bytes())
        name = re.sub(r'[\\/:*?"<>|]+', " ", (title or st["base"]).strip()) or st["base"]
        final = EXTRACTED / (f"{name} [{tid.upper()}].exfat" if tid else f"{name}.exfat")
        if final.exists():
            raise SystemExit(f"{final.name} already exists in {EXTRACTED}")
        boot = _safe(lambda: boot_files(game, repair=False), {}) or {}
        if boot.get("needed") or boot.get("notes"):
            state(boot=boot.get("needed", []) + boot.get("notes", []))
        size = exfat_build(game, final, key, EXTRACTED / f".{key}.img", state=lambda **kw: state(
            **({**kw, "phase": "image: " + kw["phase"]} if "phase" in kw else kw)))
        shutil.rmtree(tmp)  # our own temp copy; the archive is untouched
        state(state="done", phase="", done=size, total=size, finished=now(),
              image=str(Path(HOST_LIBRARY) / final.relative_to(LIBRARY)))
        print(f"{final.name}: {human(size)}, extracted with CRC checks and every file checked byte for byte "
              f"in the image; the RAR files are unchanged")
        return 0
    except ImageStopped:
        state(state="stopped", error="stopped; press again to start over")
        return 1
    except (SystemExit, OSError) as err:
        state(state="failed", error=str(err))  # temp data stays for a look
        raise
    finally:
        lock.close()


def rar_listing(first: Path) -> list[dict]:
    """Every file in a RAR set (all volumes): name, size and the whole file's
    CRC32 (from the volume where the file ends), or None when the archive
    records another hash."""
    out = subprocess.run(["unrar", "vt", "-v", "-p-", str(first)], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"unrar could not list the archive: {(out.stdout + out.stderr)[-300:].strip()}")
    files: dict = {}
    cur = None
    for line in out.stdout.splitlines():
        k, _, v = line.strip().partition(": ")
        if k == "Name":
            cur = {"name": v, "type": "", "size": None, "crc": None}
        elif cur is None:
            continue
        elif k == "Type":
            cur["type"] = v
            if v == "File":
                cur = files.setdefault(cur["name"], cur)
        elif k == "Size" and cur.get("type") == "File":
            cur["size"] = int(v)
        elif k == "CRC32" and cur.get("type") == "File":
            cur["crc"] = int(v, 16)  # the last volume's line is the whole file's
    return list(files.values())


def cmd_delete_rars(args) -> int:
    """Delete the volumes of a RAR archive, but only after checking, right
    now, that every file in it is in its .exfat image with the same size and
    content (CRC32 from the archive, or byte for byte through unrar)."""
    import zlib
    from mkpfs.exfat import ExfatReader
    if not DELETE_ORIGINALS:
        raise SystemExit("deleting originals is off: install with DELETE_ORIGINALS=yes to allow it")
    st = rar_set_for(args.archive)
    key = extract_key(st["first"])
    state_p = EXTRACTS / f"{key}.json"
    done = read_json(state_p, {}) or {}
    img = EXTRACTED / Path(done.get("image") or "-").name
    if done.get("moved"):
        img = EXTRACTED / next(iter(done["moved"].values()))
    if done.get("state") != "done" or not img.is_file():
        raise SystemExit("extract it first: the RAR files go only after a checked .exfat exists")
    ent = next((x for x in scan_library() if x.path == img), None)
    if ent is None or not tested_ok(ent.id):
        raise SystemExit(f"test {img.name} on the PS5 first: mark it 'works' (PS5 result in My games), "
                         "then the RAR files can go; nothing was deleted")

    def state(**kw):
        cur = read_json(state_p, {}) or {}
        cur.update(kw, updated=time.time())
        write_json(state_p, cur)
    try:
        files = rar_listing(st["first"])
        if done.get("moved"):
            # Images or packages moved out as they were: compare them with the archive.
            for f in files:
                dest = done["moved"].get(f["name"])
                if dest is None:
                    if (f["size"] or 0) > 1 << 20:
                        raise SystemExit(f"{f['name']} from the archive is not in {EXTRACTED.name}; nothing was deleted")
                    continue
                q = EXTRACTED / dest
                if not q.is_file() or (f["size"] is not None and q.stat().st_size != f["size"]):
                    raise SystemExit(f"{dest} is missing or has another size than in the archive; nothing was deleted")
                if f["crc"] is not None:
                    state(phase=f"checking {dest} against the archive before deleting", done=0, total=q.stat().st_size)
                    crc, n, last = 0, 0, time.time()
                    with open(q, "rb") as fh:
                        for chunk in iter(lambda: fh.read(8 << 20), b""):
                            crc = zlib.crc32(chunk, crc)
                            n += len(chunk)
                            if time.time() - last > 3:
                                last = time.time()
                                state(done=n)
                    if crc != f["crc"]:
                        raise SystemExit(f"{dest} differs from the archive (CRC32); nothing was deleted")
            for p in st["vols"]:
                p.unlink()
            state(phase="", rars_deleted=now())
            print(f"checked {len(done['moved'])} file(s) against the archive, then deleted {len(st['vols'])} RAR files")
            return 0
        # The game folder inside the archive: where sce_sys/param.json is.
        pj = sorted((f["name"] for f in files if f["name"].endswith("sce_sys/param.json")), key=len)
        prefix = pj[0][: -len("sce_sys/param.json")] if pj else ""
        extra = [f for f in files if not f["name"].startswith(prefix)]
        big = [f["name"] for f in extra if (f["size"] or 0) > 1 << 20]
        if big:
            raise SystemExit(f"the archive also holds files outside the game ({big[0]}, …) that are not in the "
                             f"image; they would be lost, so nothing was deleted")
        game = [f for f in files if f["name"].startswith(prefix)]
        total = sum(f["size"] or 0 for f in game)
        state(phase="checking the image against the archive before deleting", done=0, total=total, check_error=None)
        checked = 0
        last = time.time()
        with open(img, "rb") as fh:
            reader = ExfatReader(fh)
            inside = {e.rel_path: e for e in reader.iter_files()}
            for f in game:
                rel = f["name"][len(prefix):]
                e = inside.get(rel)
                if e is None:
                    raise SystemExit(f"{rel} is in the archive but not in the image")
                if f["size"] is not None and e.length != f["size"]:
                    raise SystemExit(f"{rel}: {e.length} bytes in the image, {f['size']} in the archive")
                if f["crc"] is not None:
                    crc = 0
                    for chunk in reader.read_file(e):
                        crc = zlib.crc32(chunk, crc)
                        checked += len(chunk)
                        if time.time() - last > 3:
                            last = time.time()
                            state(done=checked)
                    if crc != f["crc"]:
                        raise SystemExit(f"{rel} differs between the image and the archive (CRC32)")
                else:
                    # No CRC32 recorded: compare with the file unrar prints.
                    proc = subprocess.Popen(["unrar", "p", "-inul", "-p-", str(st["first"]), f["name"]],
                                            stdout=subprocess.PIPE)
                    for chunk in reader.read_file(e):
                        if proc.stdout.read(len(chunk)) != chunk:
                            proc.kill()
                            raise SystemExit(f"{rel} differs between the image and the archive")
                        checked += len(chunk)
                    if proc.stdout.read(1):
                        proc.kill()
                        raise SystemExit(f"{rel} is longer in the archive than in the image")
                    if proc.wait() != 0:
                        raise SystemExit(f"unrar could not read {rel} from the archive")
                    state(done=checked)
        for p in st["vols"]:
            p.unlink()
        state(phase="", rars_deleted=now(), done=total, total=total)
        print(f"checked {len(game)} files of the image against the archive, then deleted {len(st['vols'])} RAR "
              f"files of {st['base']}; the game is in {img.name}")
        return 0
    except (SystemExit, OSError) as err:
        state(phase="", check_error=f"not deleted: {err}")
        raise


def _image_lock():
    IMAGES.mkdir(parents=True, exist_ok=True)
    fh = open(IMAGES_LOCK, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit("an exFAT image is already being made; wait for it or stop it")
    IMAGE_STOP.unlink(missing_ok=True)
    return fh


def lz4_image_path(out: Path) -> Path:
    return out.parent / f"{out.name}.exfat"


def cmd_make_exfat(args) -> int:
    """Make an .exfat image of a finished packed copy, next to it in the output folder."""
    ensure_dirs()
    out = output_for(args.game)
    problem = lz4_format_problem(out)
    if problem:
        raise SystemExit(f"{out.name} is not a complete LZ4 game: {problem}")
    q = read_json(QUEUE_PATH, {}) or {}
    if job_running()[0] and q.get("current") and out.name in (f"{q['current']}-lz4", f"{q['current']}-zstd"):
        raise SystemExit("that game is being packed right now")
    lock = _image_lock()
    key = out.name
    try:
        size = exfat_build(out, lz4_image_path(out), key, (zstd_stage() / f"img-{out.name}" if out.parent != OUTPUT else WORK / f"img-{out.name}"))
    except ImageStopped:
        image_state(key, state="stopped", error="stopped; press again to start over")
        return 1
    except (SystemExit, OSError) as err:
        image_state(key, state="failed", error=str(err))
        raise
    finally:
        lock.close()
    image_state(key, state="done", done=size, total=size, finished=now(), bytes=size,
                image=host_output_path(lz4_image_path(out)))
    print(f"{lz4_image_path(out).name}: {human(size)}, every file checked byte for byte against {out.name}")
    return 0


def cmd_remove_exfat(args) -> int:
    """Delete a generated .exfat image while keeping its packed folder."""
    ensure_dirs()
    name = args.game if args.game.endswith(("-lz4", "-zstd")) else output_for(args.game).name
    img = output_item(f"{name}.exfat")
    if img.parent not in output_roots() or not img.is_file():
        raise SystemExit(f"no image {img.name} in {OUTPUT}")
    img.unlink()
    (IMAGES / f"{name}.json").unlink(missing_ok=True)
    print(f"deleted {img.name}; the packed folder {name} stays")
    return 0


def images_data() -> dict:
    """For the page: image jobs (running ones with no news for 2 minutes were
    interrupted) and the LZ4 images in the output folder."""
    jobs = {}
    if IMAGES.is_dir():
        for f in IMAGES.glob("*.json"):
            st = read_json(f, {}) or {}
            if st.get("state") == "running" and time.time() - st.get("updated", 0) > 120:
                st["state"] = "interrupted"
            jobs[f.stem] = st
    ready = {}
    if any(root.is_dir() for root in output_roots()):
        for f in output_items("*.exfat"):
            if f.name.endswith(("-lz4.exfat", "-zstd.exfat")):
                ready[f.name[: -len(".exfat")]] = f.stat().st_size
    return {"jobs": jobs, "ready": ready}


# --------------------------------------------------------------------------
# PS4 packages (.pkg): listed from the PS4 folder (and the library), sent as
# one file to the PS5's package folder (default the root of /mnt/usb0), where ItemzFlow or
# etaHEN's installer installs them. Nothing is packed or changed.

PS4_LIBRARY = Path(os.environ.get("PS5LZ4_PS4_LIBRARY", "/library-ps4"))
HOST_PS4_LIBRARY = os.environ.get("PS5LZ4_HOST_PS4_LIBRARY", str(PS4_LIBRARY))
# A folder of updates, DLC and backports (default <share>/backport-updates-dlc,
# mounted read-only by install.sh or lz4-ps5.sh update).
PKG_LIBRARY = Path(os.environ.get("PS5LZ4_PKG_LIBRARY", "/library-pkgs"))
HOST_PKG_LIBRARY = os.environ.get("PS5LZ4_HOST_PKG_LIBRARY", "")
PKG_CATEGORY = {"gd": "Game", "gp": "Update", "ac": "DLC", "gde": "Game", "gdk": "Game", "gdc": "App"}
_pkg_cache: dict = {}


def pkg_roots() -> dict:
    return {k: p for k, p in (("ps5", LIBRARY), ("pkgs", PKG_LIBRARY), ("ps4", PS4_LIBRARY)) if p.is_dir()}


def pkg_host(root_key: str) -> str:
    """The NAS path of a package root, as shown on the page."""
    return {"ps4": HOST_PS4_LIBRARY, "ps5": HOST_LIBRARY}.get(root_key) or HOST_PKG_LIBRARY or str(PKG_LIBRARY)


def pkg_folders(pkgs: list[dict]) -> list[dict]:
    """The package roots with their NAS path and how many packages each has."""
    return [{"key": k, "host": pkg_host(k), "count": sum(1 for p in pkgs if p["source"] == k)} for k in pkg_roots()]


def pkg_container(fh) -> tuple[int, dict]:
    """Where the CNT header is (0 for a PS4 package; a PS5 package with the
    \x7fFIH header names its embedded CNT at 0x58) and its readable file
    table: entry id -> (absolute offset, size); encrypted entries left out.
    The PS5 layout follows pkg-sender-synology's metadata reader (MIT)."""
    import struct
    fh.seek(0)
    head = fh.read(0x60)
    base = 0
    if head[:4] == b"\x7fFIH" and len(head) >= 0x60:
        base = struct.unpack("<Q", head[0x58:0x60])[0]
        fh.seek(base)
        head = fh.read(0x30)
    if head[:4] != b"\x7fCNT":
        raise ValueError("not a PS4 or PS5 package")
    count, table = struct.unpack(">I", head[0x10:0x14])[0], struct.unpack(">I", head[0x18:0x1C])[0]
    fh.seek(base + table)
    out = {}
    for _ in range(min(count, 4096)):
        e = fh.read(32)
        if len(e) < 32:
            break
        eid, _name, flags, _f2, off, size = struct.unpack(">IIIIII", e[:24])
        if flags & 0x80000000 or not size:
            continue
        out.setdefault(eid, (base + off, size))
    return base, out


def pkg_entries(fh) -> dict:
    return pkg_container(fh)[1]


def pkg_icon_entry(ents: dict):
    """icon0.png (0x1200), else the first readable icon variant (0x1201-0x1220)."""
    for eid in [0x1200] + list(range(0x1201, 0x1221)):
        if eid in ents:
            return ents[eid]
    return None


def parse_sfo(data: bytes) -> dict:
    import struct
    if data[:4] != b"\x00PSF":
        return {}
    keys, vals, n = struct.unpack("<III", data[8:20])
    out = {}
    for i in range(min(n, 512)):
        ko, fmt, ln, _mx, do = struct.unpack("<HHIII", data[20 + 16 * i: 36 + 16 * i])
        k = data[keys + ko: data.index(b"\0", keys + ko)].decode(errors="replace")
        raw = data[vals + do: vals + do + ln]
        out[k] = struct.unpack("<I", raw[:4])[0] if fmt == 0x0404 else raw.rstrip(b"\0").decode("utf-8", "replace")
    return out


def pkg_is_ps5_game(info: dict) -> bool:
    """A PS5 base game package, readable (not an update, DLC, app or PS4 title)."""
    return (info.get("platform") == "PS5" and info.get("category") == "Game" and not info.get("error")
            and str(info.get("title_id", "")).upper().startswith("PPSA"))


def pkg_info(path: Path) -> dict:
    """Title, title ID, content ID, type and version of a .pkg (cached by size and time)."""
    st = path.stat()
    key = (str(path), st.st_size, int(st.st_mtime))
    if key in _pkg_cache:
        return _pkg_cache[key]
    info = {"size": st.st_size}
    try:
        with open(path, "rb") as fh:
            base, ents = pkg_container(fh)
            fh.seek(base + 0x40)
            info["content_id"] = fh.read(36).rstrip(b"\0").decode(errors="replace")
            if 0x1000 in ents:
                off, size = ents[0x1000]
                fh.seek(off)
                sfo = parse_sfo(fh.read(min(size, 1 << 20)))
                info.update(name=sfo.get("TITLE", ""), title_id=sfo.get("TITLE_ID", ""),
                            category=PKG_CATEGORY.get(str(sfo.get("CATEGORY", "")), str(sfo.get("CATEGORY", ""))),
                            version=sfo.get("APP_VER") or sfo.get("VERSION") or "")
            elif 0x2000 in ents and ents[0x2000][1] <= 2 << 20:
                # PS5: param.json
                off, size = ents[0x2000]
                fh.seek(off)
                raw = fh.read(size)
                tid, name = parse_param_json(raw)
                try:
                    j = json.loads(raw.decode("utf-8-sig", "replace"))
                except ValueError:
                    j = {}
                info.update(name=name, title_id=tid, version=str(j.get("contentVersion") or ""), platform="PS5")
                low = "\n".join((name, info["content_id"], path.name)).lower()
                if any(e in ents for e in (0x0407, 0x0408, 0x1008)) or j.get("targetContentVersion"):
                    info["category"] = "Update"
                elif any(m in low for m in ("dlc", "add-on", "addon", "expansion", "season pass")):
                    info["category"] = "DLC"
                elif j.get("applicationCategoryType") == 0:
                    info["category"] = "Game"
                elif "applicationCategoryType" in j:
                    info["category"] = "App"
            info["icon"] = pkg_icon_entry(ents) is not None
    except (OSError, ValueError) as err:
        info["error"] = str(err)
    if not info.get("title_id"):
        m = re.search(r"(CUSA|PPSA)\d{5}", info.get("content_id", "") + " " + path.name, re.I)
        info["title_id"] = m.group(0).upper() if m else ""
    info.setdefault("name", "")
    info["name"] = info["name"] or re.sub(r"\.pkg$", "", path.name, flags=re.I)
    _pkg_cache[key] = info
    return info


def scan_pkgs() -> list[dict]:
    out = []
    for root_key, root in pkg_roots().items():
        def walk(d: Path, depth: int):
            try:
                kids = sorted(d.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                return
            for p in kids:
                if p.name.startswith("."):
                    continue
                if p.is_dir() and depth < 3:
                    walk(p, depth + 1)
                elif p.is_file() and p.suffix.lower() == ".pkg":
                    rel = str(p.relative_to(root))
                    info = pkg_info(p)
                    # PS4 packages (CUSA, no PS5 param.json) go on the page's PS4 games tab
                    ps4 = info.get("platform") != "PS5" and not str(info.get("title_id", "")).upper().startswith("PPSA")
                    out.append({"id": f"{root_key}/{rel}", "rel": rel, "file": p.name, "source": root_key,
                                "path": str(Path(pkg_host(root_key)) / rel), "ps4": ps4, **info})
        walk(root, 0)
    # The same package under two names (same content ID, version and size):
    # the later ones point at the first.
    seen: dict = {}
    for p in out:
        key = (p.get("content_id"), p.get("version"), p.get("size"))
        if p.get("content_id") and key in seen:
            p["same_as"] = seen[key]
        else:
            seen.setdefault(key, p["path"])
    return out


def pkg_path(pid: str) -> Path:
    """The .pkg file for an id from scan_pkgs (refuses anything outside the roots)."""
    root_key, _, rel = pid.partition("/")
    root = pkg_roots().get(root_key)
    if not root or not rel or ".." in rel.split("/") or rel.startswith("/"):
        raise SystemExit(f"{pid} is not a package in the library")
    p = root / rel
    if not p.is_file() or p.suffix.lower() != ".pkg" or not under(p, root):
        raise SystemExit(f"{pid} is not a package in the library")
    return p


def pkg_icon(pid: str) -> bytes | None:
    try:
        p = pkg_path(pid)
        with open(p, "rb") as fh:
            ent = pkg_icon_entry(pkg_entries(fh))
            if not ent:
                return None
            off, size = ent
            fh.seek(off)
            data = fh.read(min(size, 4 << 20))
        return data if data[:8] == b"\x89PNG\r\n\x1a\n" else None
    except (OSError, ValueError, SystemExit):
        return None


# pkg-receiver (Loopayeh/pkg-sender, MIT): a PS5 payload on port 12800 that
# installs .pkg files with the console's own installer, from a URL (here: the
# NAS serves the file) or from a path on the PS5 (/data/...). This page puts
# it in Payload Manager, starts it and asks it to install.
RECV_PORT = int(os.environ.get("PS5LZ4_RECV_PORT", "12800"))
RECV_REPO = os.environ.get("PS5LZ4_RECV_REPO", "Loopayeh/pkg-sender")
# The same receiver with this page's Glass theme, built from RECV_REPO's source
# by pkg-receiver.yml (release tag RECV_GLASS_TAG); empty PS5LZ4_RECV_GLASS:
# pkg-sender's own build.
RECV_GLASS = os.environ.get("PS5LZ4_RECV_GLASS", ENGINE_REPO)
RECV_GLASS_TAG = "pkg-receiver-glass"
RECV_PATH = "/data/pldmgr/payloads/pkg-receiver/pkg-receiver.elf"
NAS_URL = os.environ.get("PS5LZ4_NAS_URL", "")  # how the PS5 reaches this page, e.g. http://192.168.1.10:5921


def _recv_get(path: str, timeout: float = 3):
    import urllib.request
    host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
    if not host:
        raise ValueError("set the PS5 address first")
    with urllib.request.urlopen(f"http://{host}:{RECV_PORT}{path}", timeout=timeout) as r:
        return json.load(r)


def receiver_status() -> dict:
    out = {"port": RECV_PORT, "repo": RECV_REPO, "path": RECV_PATH, "running": False,
           "auto": receiver_auto_on(), "cached": (ENGINE_DIR / "pkg-receiver.elf").is_file()}
    try:
        out["build"] = _recv_get("/api/version").get("build")
        out["running"] = True
        out["space"] = _recv_get("/api/space")
        out["status"] = _recv_get("/api/status")
    except Exception as err:
        out["error"] = str(err) if out["running"] else None
    return out


def receiver_fetch() -> Path:
    """pkg-receiver.elf: the Glass build from RECV_GLASS, else the newest release
    of RECV_REPO, else RECV_REPO's repository itself (SHA-256 GitHub lists
    checked); cached in state/engine."""
    import hashlib
    import urllib.request
    hdr = {"User-Agent": "ps5-lz4", "Accept": "application/vnd.github+json"}
    url, want = None, ""
    rels = ([f"{RECV_GLASS}/releases/tags/{RECV_GLASS_TAG}"] if RECV_GLASS else []) + [f"{RECV_REPO}/releases/latest"]
    for rel_path in rels:
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{rel_path}", headers=hdr)
            with urllib.request.urlopen(req, timeout=20) as r:
                rel = json.load(r)
            a = next((a for a in rel.get("assets", []) if a.get("name") == "pkg-receiver.elf"), None)
            if a:
                url, want = a["browser_download_url"], str(a.get("digest") or "").removeprefix("sha256:").lower()
                break
        except Exception:
            continue
    url = url or f"https://raw.githubusercontent.com/{RECV_REPO}/HEAD/payload/pkg-receiver.elf"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ps5-lz4"}), timeout=60) as r:
        data = r.read()
    if data[:4] != b"\x7fELF":
        raise ValueError("the downloaded pkg-receiver.elf is not an ELF")
    if want and hashlib.sha256(data).hexdigest() != want:
        raise ValueError("the downloaded pkg-receiver.elf does not match the SHA-256 GitHub lists")
    ENGINE_DIR.mkdir(parents=True, exist_ok=True)
    elf = ENGINE_DIR / "pkg-receiver.elf"
    elf.write_bytes(data)
    return elf


def receiver_install() -> dict:
    """Put pkg-receiver in Payload Manager over FTP and start it."""
    import io
    elf = receiver_fetch()
    f = ps5_ftp_connect()
    try:
        path = pm_path(RECV_PATH, f)
        ps5_ftp_mkdirs(f, path.rsplit("/", 1)[0])
        f.storbinary(f"STOR {path}", io.BytesIO(elf.read_bytes()), blocksize=1 << 20)
    finally:
        try:
            f.quit()
        except Exception:
            pass
    # A newly started receiver replaces the running one, so start it unless
    # that one already is this build.
    m = re.search(rb'\{"build":"([^"]+)"\}', elf.read_bytes())
    st = receiver_status()
    if st["running"] and (not m or st.get("build") == m.group(1).decode()):
        return {"installed": path, "started": "already running"}
    return {"installed": path, **receiver_launch(elf)}


def receiver_launch(elf: Path | None) -> dict:
    """Start the pkg-receiver already in Payload Manager on the PS5, else send
    elf (the cached copy) to an ELF loader."""
    import socket
    import urllib.request
    host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
    if not host:
        raise ValueError("set the PS5 address first")
    try:
        if "Invalid payload name" not in pm_load(host, pm_path(RECV_PATH)):
            return {"started": f"Payload Manager ({PLDMGR_PORT})"}
    except Exception:
        pass
    if elf and elf.is_file():
        for port in ELFLDR_PORTS:
            try:
                with socket.create_connection((host, port), timeout=10) as sk:
                    sk.sendall(elf.read_bytes())
                return {"started": f"ELF loader ({port})"}
            except OSError:
                continue
    return {"started": None,
            "note": "start pkg-receiver from the Payload Manager on the PS5 (or press Install and start)"}


def receiver_start() -> dict:
    """Start pkg-receiver on the PS5 without downloading or copying it again."""
    if receiver_status()["running"]:
        return {"started": "already running"}
    return receiver_launch(ENGINE_DIR / "pkg-receiver.elf")


# Match the reviewed Forge release used by the NAS packer. A console payload
# has its own bundled runtime; it is not the newer NAS runtime in this image.
FORGE_PS5_VERSION = "0.5.5"
FORGE_PS5_SHA256 = "858b8ae2954341a3389e4a9f998c6a57d01bc4e4fb8f01a71c41719001c30be7"
FORGE_PS5_PATH = "/data/pldmgr/payloads/ps5-dump-forge/ps5-dump-forge.elf"


def forge_ps5_elf() -> Path:
    """Cache the official, checksum-verified PS5 release in NAS state."""
    import hashlib
    import urllib.request
    elf = ENGINE_DIR / f"ps5-dump-forge-{FORGE_PS5_VERSION}-ps5.elf"
    if elf.is_file():
        with elf.open("rb") as cached:
            if hashlib.file_digest(cached, "sha256").hexdigest() == FORGE_PS5_SHA256:
                return elf
    url = ("https://github.com/quer3q/ps5-dump-forge/releases/download/"
           f"v{FORGE_PS5_VERSION}/{elf.name}")
    req = urllib.request.Request(url, headers={"User-Agent": "ps5-lz4"})
    with urllib.request.urlopen(req, timeout=120) as response:
        data = response.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024 or data[:4] != b"\x7fELF":
        raise ValueError("the downloaded PS5 Dump Forge payload is not a valid ELF")
    if hashlib.sha256(data).hexdigest() != FORGE_PS5_SHA256:
        raise ValueError("the PS5 Dump Forge payload failed its SHA-256 check")
    ENGINE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = elf.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(elf)
    return elf


def forge_ps5_install() -> dict:
    """Copy Forge into Payload Manager when FTP works; start via PM or elfldr."""
    import io
    import ftplib
    import socket
    host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
    if not host:
        raise ValueError("set the PS5 address under Remote first")
    elf = forge_ps5_elf()
    installed = None
    try:
        f = ps5_ftp_connect()
        try:
            installed = pm_path(FORGE_PS5_PATH, f)
            ps5_ftp_mkdirs(f, installed.rsplit("/", 1)[0])
            f.storbinary(f"STOR {installed}", io.BytesIO(elf.read_bytes()), blocksize=1 << 20)
        finally:
            try:
                f.quit()
            except Exception:
                pass
        answer = pm_load(host, installed)
        if "Invalid payload name" not in answer:
            return {"installed": installed, "started": f"Payload Manager ({PLDMGR_PORT})",
                    "url": f"http://{host}:8095/", "version": FORGE_PS5_VERSION}
    except (OSError, ValueError, *ftplib.all_errors):
        pass  # A PS5 with an ELF loader does not need FTP or Payload Manager.
    for port in ELFLDR_PORTS:
        try:
            with socket.create_connection((host, port), timeout=10) as sk, elf.open("rb") as source:
                while chunk := source.read(1 << 20):
                    sk.sendall(chunk)
            return {"installed": installed, "started": f"ELF loader ({port})",
                    "url": f"http://{host}:8095/", "version": FORGE_PS5_VERSION}
        except OSError:
            continue
    raise ValueError("could not start Forge: run Payload Manager or an ELF loader on the PS5 (port 9021)")


RECV_AUTO = ENGINE_DIR / "receiver-auto.json"  # {"on": bool}: start pkg-receiver when the PS5 is on


def receiver_auto_on() -> bool:
    return bool((read_json(RECV_AUTO, {}) or {}).get("on", True))


def receiver_autostarter() -> None:
    """Start pkg-receiver when the PS5 is on and it doesn't answer (after a
    PS5 restart): checked every 30 s, retried at most every 5 minutes."""
    tried = 0.0
    while True:
        try:
            host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
            if (host and receiver_auto_on() and time.time() - tried > 300
                    and ps5_status(host) == "on" and not receiver_status()["running"]):
                tried = time.time()
                res = receiver_start()
                if res.get("started"):
                    print(f"[{now()}] pkg-receiver started by itself: {res['started']}", flush=True)
        except Exception:
            pass
        time.sleep(30)



# What the PS5 downloads from this page (packages and images), counted by the
# byte ranges sent, as pkg-sender-synology's transfer tracker does (MIT): live
# progress and speed, and a history of downloads and install requests.
PKG_HISTORY = STATE / "pkg_history.json"
_dl: dict = {}
_dl_lock = __import__("threading").Lock()


def pkg_history_add(rec: dict) -> None:
    with _dl_lock:
        hist = read_json(PKG_HISTORY, []) or []
        hist.insert(0, {"at": now(), **rec})
        write_json(PKG_HISTORY, hist[:100])


def dl_note(pid: str, name: str, total: int, start: int, n: int) -> None:
    t = time.time()
    done = None
    with _dl_lock:
        s = _dl.get(pid)
        if not s or s["done"] or t - s["updated"] > 600:
            s = _dl[pid] = {"id": pid, "name": name, "total": total, "iv": [], "got": 0, "started": t,
                            "updated": t, "rate": 0.0, "mark": (t, 0), "done": False, "logged": False}
        a, b = start, start + n
        iv = []
        for x, y in s["iv"]:
            if y < a or x > b:
                iv.append((x, y))
            else:
                a, b = min(a, x), max(b, y)
        iv.append((a, b))
        s["iv"] = sorted(iv)
        s["got"] = sum(y - x for x, y in s["iv"])
        s["updated"] = t
        mt, mg = s["mark"]
        if t - mt >= 2:
            r = (s["got"] - mg) / (t - mt)
            s["rate"] = r if not s["rate"] else 0.6 * s["rate"] + 0.4 * r
            s["mark"] = (t, s["got"])
        if s["got"] >= total and not s["done"]:
            s["done"] = s["logged"] = True
            done = {"kind": "download", "id": pid, "name": name, "size": total, "ok": True,
                    "seconds": round(t - s["started"])}
    if done:
        pkg_history_add(done)


def dl_snapshot() -> list[dict]:
    t = time.time()
    out, stale = [], []
    with _dl_lock:
        for pid, s in list(_dl.items()):
            age = t - s["updated"]
            if s["done"] and age > 600:
                del _dl[pid]
                continue
            if not s["done"] and age > 600:
                del _dl[pid]
                if not s["logged"]:
                    stale.append({"kind": "download", "id": pid, "name": s["name"], "size": s["total"],
                                  "got": s["got"], "ok": False, "error": "stopped"})
                continue
            out.append({"id": pid, "name": s["name"], "total": s["total"], "got": s["got"],
                        "percent": round(100 * s["got"] / s["total"], 1) if s["total"] else 0,
                        "rate": round(s["rate"]) if age < 15 else 0,
                        "status": "done" if s["done"] else "downloading" if age < 30 else "paused"})
    for rec in stale:
        pkg_history_add(rec)
    return sorted(out, key=lambda d: d["status"] != "downloading")


def notify(title: str, text: str, ok: bool = True, url: str | None = None) -> None:
    """A push notification: to an ntfy topic (https://ntfy.sh/<topic> or a
    self-hosted one; title and tags as headers) or any other webhook (JSON
    with title, message, ok), e.g. Home Assistant. Idea from
    game-library-manager-ps5; best effort, never raises."""
    import urllib.request
    url = url or get_settings().get("notify_url") or ""
    if not url:
        return
    try:
        if "ntfy" in url.lower():
            req = urllib.request.Request(url, data=text.encode(), method="POST", headers={
                "Title": title.encode("ascii", "replace").decode(), "Tags": "white_check_mark" if ok else "warning",
                "Priority": "default" if ok else "high"})
        else:
            req = urllib.request.Request(url, data=json.dumps({"title": title, "message": text, "ok": ok}).encode(),
                                         method="POST", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as err:
        print(f"[{now()}] notification failed: {err}", flush=True)


def notifier() -> None:
    """Watch what finishes (packing reports, actions, transfers to the PS5,
    downloads from this NAS) and send a notification for each; the first
    look only remembers what is already there."""
    seen: dict = {}
    first = True
    while True:
        try:
            events = []
            for f in (REPORTS.glob("*.json") if REPORTS.is_dir() else []):
                r = read_json(f, {}) or {}
                key = ("report", f.name, r.get("finished"))
                if r.get("finished") and key not in seen:
                    seen[key] = 1
                    saved = r.get("saved_bytes") or 0
                    events.append(("Packed: " + (r.get("title_name") or r.get("id") or f.stem),
                                   f"LZ4 done and verified on the NAS, {human(saved)} saved ({r.get('saved_percent', 0)} %).", True))
            for f in (REQUESTS.glob("*.done.json") if REQUESTS.is_dir() else []):
                key = ("req", f.name)
                if key in seen:
                    continue
                seen[key] = 1
                r = read_json(f, {}) or {}
                if r.get("action") in ("start", "fix", "check", "check_full", "apr", "make_exfat") or not r.get("ok", True):
                    events.append((f"{'Done' if r.get('ok') else 'Failed'}: {r.get('action', '')} {r.get('game') or ''}".strip(),
                                   "\n".join((r.get("output") or "").splitlines()[-3:]) or "-", bool(r.get("ok"))))
            for f in transfer_files():
                t = read_json(f, {}) or {}
                key = ("xfer", f.name, t.get("state"), t.get("finished"))
                if t.get("state") in ("done", "failed") and key not in seen:
                    seen[key] = 1
                    ok = t["state"] == "done"
                    events.append((("Sent to the PS5: " if ok else "Transfer failed: ") + str(t.get("game") or f.stem),
                                   f"{human(t.get('total') or 0)} to {t.get('dest', '')}" if ok else str(t.get("error") or ""), ok))
            for h in (read_json(PKG_HISTORY, []) or [])[:20]:
                key = ("dl", h.get("at"), h.get("id"), h.get("kind"))
                if h.get("kind") == "download" and key not in seen:
                    seen[key] = 1
                    events.append((("Downloaded by the PS5: " if h.get("ok") else "Download stopped: ") + str(h.get("name")),
                                   f"{human(h.get('size') or 0)} from this NAS" + ("; the PS5 now installs it" if h.get("ok") else ""),
                                   bool(h.get("ok"))))
            if not first:
                for title, text, ok in events[:10]:
                    notify(title, text, ok)
            first = False
        except Exception as err:
            print(f"[{now()}] notifier: {err}", flush=True)
        time.sleep(20)


def serve_pkg(h, pid: str, head: bool = False) -> None:
    """Send a library .pkg on HTTP handler h, with Range support (the PS5's
    installer downloads in pieces)."""
    try:
        p = catalog_file(pid)
    except SystemExit as err:
        b = f"{err}\n".encode()
        h.send_response(404)
        h.send_header("Content-Type", "text/plain; charset=utf-8")
        h.send_header("Content-Length", str(len(b)))
        h.end_headers()
        if not head:
            h.wfile.write(b)
        return
    size = p.stat().st_size
    start, end = 0, size - 1
    m = re.match(r"bytes=(\d*)-(\d*)$", h.headers.get("Range") or "")
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        else:
            start = max(0, size - int(m.group(2)))
        if start > end or start >= size:
            h.send_response(416)
            h.send_header("Content-Range", f"bytes */{size}")
            h.end_headers()
            return
        h.send_response(206)
        h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    else:
        h.send_response(200)
    h.send_header("Content-Type", "application/octet-stream")
    h.send_header("Accept-Ranges", "bytes")
    h.send_header("Access-Control-Allow-Origin", "*")
    h.send_header("Content-Length", str(end - start + 1))
    h.end_headers()
    if head:
        return
    left = end - start + 1
    pos = start
    try:
        name = (image_meta(p).get("title") if pid.startswith("img/") else pkg_info(p).get("name")) or p.name
    except Exception:
        name = p.name
    try:
        with open(p, "rb") as f:
            f.seek(start)
            while left > 0:
                chunk = f.read(min(left, 1 << 20))
                if not chunk:
                    break
                h.wfile.write(chunk)
                dl_note(pid, name, size, pos, len(chunk))
                pos += len(chunk)
                left -= len(chunk)
    except (BrokenPipeError, ConnectionResetError):
        pass


# pkg-receiver's own page on the PS5 (the "pkg remote installer" shortcut)
# shows a PC's catalog from port 9898 and finds the PC from a UDP message to
# the PS5's port 12802. This page acts as that PC: the same catalog of the
# NAS's packages, the files and their icons.
CATALOG_PORT = int(os.environ.get("PS5LZ4_CATALOG_PORT", "9898"))
PC_ANNOUNCE_PORT = 12802


_img_meta: dict = {}


def image_meta(path: Path) -> dict:
    """Title, title ID and cover of a library image (an .exfat is read inside;
    other images go by name), cached by size and time."""
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key in _img_meta:
        return _img_meta[key]
    m = TITLE_RE.search(path.name)
    stem = re.sub(r"-(?:lz4|zstd)$", "", path.stem)
    stem = re.sub(r"\s*\[[^\]]*\]|\s*\([^)]*\)|\s*_[A-Z]{4}\d{5}_\s*", " ", stem).strip()
    info = {"title": stem or path.stem,
            "title_id": m.group(0).upper() if m else "", "icon": None}
    if path.suffix.lower() == ".pkg":
        pi = pkg_info(path)
        info.update(title=pi.get("name") or info["title"], title_id=(pi.get("title_id") or info["title_id"]).upper(),
                    version=pi.get("version") or "")
        try:
            with open(path, "rb") as fh:
                ent = pkg_icon_entry(pkg_entries(fh))
                if ent and ent[1] < 8 << 20:
                    fh.seek(ent[0])
                    data = fh.read(ent[1])
                    info["icon"] = data if data[:8] == b"\x89PNG\r\n\x1a\n" else None
        except (OSError, ValueError):
            pass
        _img_meta[key] = info
        return info
    if path.suffix.lower() in (".exfat", ".ffpfsc", ".ffpfs"):
        fh = None
        try:
            from mkpfs.exfat import ExfatReader  # pinned MkPFS 1.1.0
            if path.suffix.lower() == ".exfat":
                fh = open(path, "rb")
                src = fh
            else:
                # The exFAT inside a .ffpfsc/.ffpfs, read on demand (nothing unpacked).
                from mkpfs.pfs import open_inner_file_view
                opened = open_inner_file_view(path)
                if not opened:
                    raise ValueError("no single inner image")
                src, fh, _name = opened
            reader = ExfatReader(src)
            files = {e.rel_path.lower(): e for e in reader.iter_files()}
            prefix = exfat_game_prefix(files)
            if prefix + "ampr_zstd.index" in files:
                info["pack_codec"] = "zstd"
            elif prefix + "ampr_assets.index" in files:
                info["pack_codec"] = "lz4"
            pj = next((e for k, e in files.items() if k.endswith("sce_sys/param.json")), None)
            if pj:
                raw = b"".join(reader.read_file(pj))
                tid, name = parse_param_json(raw)
                try:
                    info["version"] = str(json.loads(raw.decode("utf-8-sig", "replace")).get("contentVersion") or "")
                except ValueError:
                    pass
                info["title"] = name or info["title"]
                info["title_id"] = (tid or info["title_id"]).upper()
            ic = next((e for k, e in files.items() if k.endswith("sce_sys/icon0.png")), None)
            if ic and ic.length < 8 << 20:
                info["icon"] = b"".join(reader.read_file(ic))
        except Exception:
            pass
        finally:
            if fh:
                fh.close()
    _img_meta[key] = info
    return info


_cat_cache = {"at": 0.0, "list": []}


def catalog_images() -> list[tuple[str, Path, str | None]]:
    """(catalog id, file, game id for the cover) of every PS5 image to offer:
    library images and the LZ4 copies' .exfat images (cached for a minute:
    a download asks for every piece)."""
    if time.time() - _cat_cache["at"] < 60:
        return _cat_cache["list"]
    out = []
    for e in scan_library():
        if e.kind in ("exfat", "ffpfs", "ffpfsc"):
            out.append((f"img/lib/{e.id}", e.path, e.id))
    if any(root.is_dir() for root in output_roots()):
        for f in output_items("*.exfat"):
            if f.name.endswith(("-lz4.exfat", "-zstd.exfat")):
                out.append((f"img/out/{f.name}", f, re.sub(r"-(?:lz4|zstd)\.exfat$", "", f.name)))
    _cat_cache.update(at=time.time(), list=out)
    return out


def catalog_file(cid: str) -> Path:
    """The file behind a catalog id: a package, or a PS5 image."""
    if cid.startswith("img/"):
        for i, p, _g in catalog_images():
            if i == cid:
                return p
        raise SystemExit(f"{cid} is not an image in the library")
    return pkg_path(cid)


def catalog_icon(cid: str) -> bytes | None:
    if not cid.startswith("img/"):
        return pkg_icon(cid)
    for i, p, gid in catalog_images():
        if i == cid:
            return image_meta(p).get("icon") or (nas_icon(gid) if gid else None)
    return None


IMG_VARIANT = {"exfat": "exFAT", "ffpfsc": "FFPFSC", "ffpfs": "FFPFS"}


def pkg_catalog() -> list[dict]:
    role = {"Game": "Game", "Update": "Patch", "DLC": "DLC"}
    out = []
    for cid, p, gid in catalog_images():
        meta = image_meta(p)
        fmt = p.suffix.lower().lstrip(".")
        lz4 = cid.startswith("img/out/")
        size = p.stat().st_size
        out.append({"id": cid, "title": meta["title"] + (" (LZ4)" if lz4 else ""), "titleId": meta["title_id"],
                    "version": "", "size": size, "sizeText": human(size), "role": "Game",
                    "familyKey": "FILE:" + p.name, "platform": "PS5", "format": fmt, "file": p.name,
                    "hasIcon": bool(meta.get("icon") or (gid and nas_icon(gid))),
                    # the Glass page groups a game's images and offers a choice
                    "game": gid or p.name, "variant": "LZ4" if lz4 else IMG_VARIANT.get(fmt, fmt)})
    for p in scan_pkgs():
        tid = p.get("title_id") or ""
        out.append({"id": p["id"], "title": p.get("name") or p["file"], "titleId": tid,
                    "version": p.get("version") or "", "size": p.get("size") or 0, "sizeText": human(p.get("size") or 0),
                    "role": role.get(p.get("category") or "", p.get("category") or "Game"),
                    "familyKey": tid or "FILE:" + p["file"],
                    "platform": p.get("platform") or ("PS5" if tid.upper().startswith("PPSA") else "PS4"),
                    "format": "pkg", "file": p["file"], "hasIcon": bool(p.get("icon"))})
    return out


FPKGI_REGION = {"UP": "USA", "EP": "EUR", "JP": "JAP", "HP": "ASIA", "KP": "ASIA", "IP": "ASIA"}


def fpkgi_feed(kind: str, host: str) -> dict:
    """The package library as an FPKGi feed (the PS5 store app that reads
    {"DATA": {url: {name, size, region, version, release, min_fw, cover_url}}}
    lists, idea from FPKGi / fpkgi-server): GAMES, UPDATES or DLC, with
    download and cover links on this catalog port."""
    import urllib.parse
    want = {"GAMES": ("Game", "App"), "UPDATES": ("Update",), "DLC": ("DLC",)}.get(kind.upper(), ())
    data = {}
    for p in scan_pkgs():
        if (p.get("category") or "Game") not in want:
            continue
        q = urllib.parse.quote(p["id"])
        cid = p.get("content_id") or ""
        data[f"http://{host}/pkg/{q}"] = {
            "name": p.get("name") or p["file"], "size": p.get("size") or 0,
            "title_id": p.get("title_id") or "", "region": FPKGI_REGION.get(cid[:2].upper(), ""),
            "version": p.get("version") or "", "release": None, "min_fw": None,
            "cover_url": f"http://{host}/icon/{q}" if p.get("icon") else None}
    return {"DATA": data}


def catalog_server() -> None:
    """Web page container: the pkg-sender style catalog on CATALOG_PORT."""
    import http.server
    from urllib.parse import unquote

    class C(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_HEAD(self):
            path = self.path.split("?")[0]
            if path.startswith("/pkg/"):
                return serve_pkg(self, unquote(path[5:]), head=True)
            self.send_response(404)
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/catalog":
                return self._json(pkg_catalog())
            m = re.fullmatch(r"/fpkgi/(GAMES|UPDATES|DLC)\.json", path, re.I)
            if m:
                return self._json(fpkgi_feed(m.group(1), self.headers.get("Host") or f"127.0.0.1:{CATALOG_PORT}"))
            if path.startswith("/pkg/"):
                return serve_pkg(self, unquote(path[5:]))
            if path.startswith("/icon/"):
                data = catalog_icon(unquote(path[6:]))
                if not data:
                    return self._json({"error": "no icon"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            return self._json({"error": "unknown"}, 404)

    try:
        srv = http.server.ThreadingHTTPServer(("0.0.0.0", CATALOG_PORT), C)
    except OSError as err:
        print(f"[{now()}] catalog for the PS5: port {CATALOG_PORT}: {err}", flush=True)
        return
    print(f"[{now()}] catalog for pkg-receiver on port {CATALOG_PORT}", flush=True)
    srv.serve_forever()


def catalog_announcer() -> None:
    """Tell pkg-receiver on the PS5 where the catalog is: it takes the
    sender's address of this message (the NAS) and uses port 9898."""
    import socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        try:
            host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
            if host:  # also with no packages: the catalog lists images too
                sk.sendto(f"PKGSENDER-PC 0.0.0.0:{CATALOG_PORT}".encode(), (host, PC_ANNOUNCE_PORT))
        except Exception:
            pass
        time.sleep(3)


def pkg_install(pid: str, via: str, page_host: str) -> dict:
    """pkg_install_now, noted in the package history (with Retry on the page)."""
    try:
        name = pkg_info(pkg_path(pid)).get("name") or pid
    except (SystemExit, OSError):
        name = pid
    try:
        res = pkg_install_now(pid, via, page_host)
    except (ValueError, SystemExit) as err:
        pkg_history_add({"kind": "install", "id": pid, "name": name, "via": via, "ok": False, "error": str(err)})
        raise
    pkg_history_add({"kind": "install", "id": pid, "name": name, "via": via, "ok": True})
    ps5_notify(f"NAS: installing {name}" + (" (downloading from the NAS)" if via != "local" else ""))
    return res


def ver_key(v: str) -> tuple:
    """"01.004.000" / "01.06" as numbers, for comparing versions."""
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))) or (0,)


def ps5_installed() -> dict:
    """What is already on the PS5, from every source that answers: the apps
    in /user/app with their version (pkg-receiver's /api/installed), games
    ShadowMountPlus has mounted, and over FTP the apps the PS5 has registered
    (/system_data/priv/appmeta, /user/app) and the DLC folders in
    /user/addcont/<title ID> (dlc None: FTP didn't answer, unknown)."""
    import ftplib
    import urllib.error
    import urllib.request
    host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
    if not host:
        raise ValueError("set the PS5 address on the Remote tab first")
    try:
        with urllib.request.urlopen(f"http://{host}:{RECV_PORT}/api/installed", timeout=15) as r:
            j = json.load(r)
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise ValueError(f"pkg-receiver (Glass build) does not answer on the PS5 (port {RECV_PORT}): "
                         f"start it on the Remote tab ({err})")
    apps = {str(a.get("id", "")).upper(): a for a in j.get("apps") or []}
    sources = ["pkg-receiver"]
    try:
        for g in smp("/api/v1/games", {"include_size": False}, timeout=15).get("games") or []:
            tid = str(g.get("title_id") or "").upper()
            if tid and tid not in apps:
                apps[tid] = {"id": tid, "ver": str(g.get("version") or ""), "from": "ShadowMount"}
        sources.append("ShadowMount")
    except ValueError:
        pass
    dlc = None
    try:
        f = ps5_ftp_connect()
        try:
            for d in ("/system_data/priv/appmeta", "/user/app"):
                try:
                    for i in ps5_ftp_list_conn(f, d):
                        tid = i["name"].upper()
                        if i["dir"] and re.fullmatch(r"(PPSA|CUSA)\d{5}", tid) and tid not in apps:
                            apps[tid] = {"id": tid, "ver": "", "from": d}
                except ftplib.all_errors:
                    pass
            sources.append("FTP")
            dlc = {}
            try:
                for i in ps5_ftp_list_conn(f, "/user/addcont"):
                    if i["dir"]:
                        try:
                            dlc[i["name"].upper()] = {x["name"].upper() for x in ps5_ftp_list_conn(f, f"/user/addcont/{i['name']}")}
                        except ftplib.all_errors:
                            dlc[i["name"].upper()] = set()
            except ftplib.error_perm:
                pass  # no /user/addcont: no DLC installed
        finally:
            try:
                f.quit()
            except Exception:
                pass
    except (ValueError, OSError, *ftplib.all_errors):
        dlc = None
    return {"apps": apps, "dlc": dlc, "sources": sources}


def pkg_on_ps5(p: dict, inst: dict) -> tuple[str, str]:
    """Whether a package is on the PS5: ("installed"|"missing"|"no_game"|
    "unknown", what the page shows)."""
    cat, tid = p.get("category") or "Game", (p.get("title_id") or "").upper()
    a = inst["apps"].get(tid)
    ver = f" v{a['ver']}" if a and a.get("ver") else ""
    if cat in ("Game", "App"):
        return ("installed", f"installed{ver}") if a else ("missing", "not installed")
    if not a:
        return "no_game", "the game isn't installed"
    if cat == "Update":
        if not a.get("ver"):
            return "unknown", "game installed, its version unknown"
        if ver_key(a["ver"]) >= ver_key(p.get("version")):
            return "installed", f"installed (game is{ver})"
        return "missing", f"not installed (game is{ver})"
    if cat == "DLC":
        if inst["dlc"] is None:
            return "unknown", "game installed; DLC unknown (no FTP)"
        label = (p.get("content_id") or "").rpartition("-")[2].upper()
        if label and any(label in n for n in inst["dlc"].get(tid, ())):
            return "installed", "installed"
        return "missing", "not installed"
    return "unknown", ""


def pkg_ps5_states() -> dict:
    """pkg_on_ps5 for every package, for the page's PS5 column."""
    inst = ps5_installed()
    return {"states": {p["id"]: dict(zip(("state", "text"), pkg_on_ps5(p, inst))) for p in scan_pkgs()},
            "sources": inst.get("sources", []), "checked": now()}


def pkg_install_plan(ids: list[str] | None, inst: dict) -> list[dict]:
    """Install all: the packages (all, or these ids) in the order the PS5
    needs them (games, then updates, then DLC), each with skip set when it is
    already on the PS5 or can't be installed. A second name of the same
    package and an older update of the same game are left out."""
    pkgs = [p for p in scan_pkgs() if not p.get("same_as") and (ids is None or p["id"] in ids)]
    order = {"Game": 0, "App": 0, "Update": 1, "DLC": 2}
    pkgs.sort(key=lambda p: (order.get(p.get("category") or "Game", 0), p.get("name") or ""))
    newest: dict = {}
    for p in pkgs:
        if p.get("category") == "Update" and p.get("title_id"):
            t = p["title_id"].upper()
            if t not in newest or ver_key(p.get("version")) > ver_key(newest[t].get("version")):
                newest[t] = p
    games = {(p.get("title_id") or "").upper() for p in pkgs if (p.get("category") or "Game") in ("Game", "App")}
    plan = []
    for p in pkgs:
        cat, tid = p.get("category") or "Game", (p.get("title_id") or "").upper()
        state, text = pkg_on_ps5(p, inst)
        skip = text if state == "installed" else ""
        if cat == "Update" and newest.get(tid) is not p:
            skip = f"a newer update (v{newest[tid].get('version')}) is in the list"
        elif state == "no_game" and tid not in games:
            skip = "the game isn't on the PS5"
        plan.append({"id": p["id"], "name": p.get("name") or p["file"], "category": cat,
                     "version": p.get("version") or "", "skip": skip})
    return plan


def pkg_install_all(ids: list[str] | None, page_host: str, dry: bool) -> dict:
    """Install every package not on the PS5 yet (dry: only say which)."""
    inst = ps5_installed()
    plan = pkg_install_plan(ids, inst)
    out = {"plan": plan, "dlc_checked": inst["dlc"] is not None, "sources": inst.get("sources", []),
           "started": [], "failed": []}
    if dry:
        return out
    for e in plan:
        if e["skip"]:
            continue
        try:
            pkg_install_now(e["id"], "url", page_host)
            pkg_history_add({"kind": "install", "id": e["id"], "name": e["name"], "via": "url", "ok": True})
            out["started"].append(e["name"])
        except (ValueError, SystemExit) as err:
            pkg_history_add({"kind": "install", "id": e["id"], "name": e["name"], "via": "url", "ok": False, "error": str(err)})
            out["failed"].append({"name": e["name"], "error": str(err)})
        time.sleep(0.5)
    if out["started"]:
        ps5_notify(f"NAS: installing {len(out['started'])} package(s), downloading from the NAS")
    return out


def pkg_install_now(pid: str, via: str, page_host: str) -> dict:
    """Ask pkg-receiver to install a package: from this page over HTTP ("url"),
    or from the copy sent to the PS5's package folder ("local")."""
    import urllib.error
    import urllib.parse
    import urllib.request
    p = pkg_path(pid)
    info = pkg_info(p)
    base = (NAS_URL or f"http://{page_host}").rstrip("/")
    if via == "local":
        src = f"{get_settings()['ps4_dest'].rstrip('/')}/{p.name}"
    else:
        if not page_host and not NAS_URL:
            raise ValueError("unknown address of this page; set PS5LZ4_NAS_URL")
        src = f"{base}/pkgfile/{urllib.parse.quote(pid)}"
    body = {"type": "direct", "packages": [src], "name": info.get("name") or p.name}
    if info.get("icon") and via != "local":
        body["icon_url"] = f"{base}/api/pkg/icon?id={urllib.parse.quote(pid)}"
    host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
    req = urllib.request.Request(f"http://{host}:{RECV_PORT}/api/install", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.load(r)
    except (urllib.error.URLError, OSError) as err:
        raise ValueError(f"pkg-receiver does not answer on the PS5 (port {RECV_PORT}): install and start it on "
                         f"the Remote tab ({err})")
    if res.get("status") != "success":
        raise ValueError(f"pkg-receiver: {res.get('error') or res}")
    print(f"[{now()}] install of {p.name} queued on the PS5 ({src})", flush=True)
    return {"queued": True, "source": src}


class TransferStopped(Exception):
    """Stop pressed: not retried like a network error."""


TRANSFER_QUEUE = TRANSFERS / "queue.json"


def transfer_queue() -> list[str]:
    q = read_json(TRANSFER_QUEUE, []) or []
    return [x for x in q if isinstance(x, str)]


def transfer_queue_set(q: list[str]) -> None:
    TRANSFERS.mkdir(parents=True, exist_ok=True)
    write_json(TRANSFER_QUEUE, q)


def cmd_push(args) -> int:
    """Copy a finished LZ4 game to the PS5 over FTP and check it, then the
    games queued after it (state/transfers/queue.json), one at a time."""
    ensure_dirs()
    TRANSFERS.mkdir(exist_ok=True)
    if not get_settings()["ps5_ftp"]:
        raise SystemExit("set the PS5 FTP address first (web page: Remote tab, or PS5LZ4_PS5_FTP)")
    if transfer_running():
        raise SystemExit("a transfer is already running")
    try:
        return push_queue(args.game, args.force)
    finally:
        (TRANSFERS / ".starting").unlink(missing_ok=True)


def push_queue(game: str, force: bool) -> int:
    rc = 0
    while game:
        q = [x for x in transfer_queue() if x != game]
        transfer_queue_set(q)
        try:
            rc = push_one(game, force) or rc
        except TransferStopped:
            return 1  # the queue waits until it is started again
        except SystemExit as err:
            print(f"{game}: {err}", file=sys.stderr)
            rc = 1
        q = transfer_queue()
        game = q[0] if q else None
    return rc


def push_one(game: str, force: bool = False) -> int:
    import ftplib
    cfg = get_settings()
    # "src:<id>" sends the original from the library as it is (a game folder,
    # or an .exfat/.ffpfs/.ffpfsc image as one file); anything else is an LZ4 copy.
    entry = None
    image = game.startswith("img:")
    pkg = game.startswith("pkg:")
    if pkg:
        out = pkg_path(game[4:])  # a PS4 package, as one file
    elif image:
        # A generated packed-game .exfat image from the output folder, as one file.
        out = output_item(game[4:])
        if "/" in game[4:] or not out.name.endswith(("-lz4.exfat", "-zstd.exfat")) or not out.is_file():
            raise SystemExit(f"{game[4:]} is not a packed-game image in the output folder")
    elif game.startswith("src:"):
        entry = next((x for x in scan_library() if x.id == game[4:]), None)
        if entry is None:
            raise SystemExit(f"{game[4:]} is not in the library")
        out = entry.path
    else:
        out = output_for(game)
        problem = lz4_format_problem(out)
        if problem:
            raise SystemExit(f"{out.name} is not a complete LZ4 game: {problem}")
    single = out.is_file()
    host, _, port = cfg["ps5_ftp"].partition(":")
    port = int(port or 2121)
    dest_root = cfg["ps4_dest"] if pkg else cfg["ps5_dest"]
    dest = dest_root if single else f"{dest_root}/{out.name}"
    root = out.parent if single else out
    files = [out] if single else sorted(p for p in out.rglob("*") if p.is_file())
    total = sum(p.stat().st_size for p in files)
    st_path = TRANSFERS / f"{out.name}.json"
    st = {"game": out.name, "dest": f"{cfg['ps5_ftp']}{dest_root}/{out.name}", "state": "running",
          "pid": os.getpid(), "source": "original" if entry else "lz4 image" if image else "ps4 package" if pkg else "lz4", "request": game,
          "bytes": 0, "total": total, "files": len(files), "files_done": 0, "skipped": 0,
          "current": "", "started": now(), "error": None, "verified": 0}
    write_json(st_path, st)
    (TRANSFERS / ".starting").unlink(missing_ok=True)
    last = [0.0]

    def stop(_sig, _frm):
        raise TransferStopped("stopped; press Send to PS5 again to resume (finished files are kept)")
    signal.signal(signal.SIGTERM, stop)

    rate = __import__("collections").deque()  # (time, bytes) of the last 30 seconds

    def save(force=False):
        if force or time.time() - last[0] > 1:
            t = time.time()
            while rate and t - rate[0][0] > 30:
                rate.popleft()
            if len(rate) > 1 and t - rate[0][0] > 2:
                st["speed"] = int(sum(n for _, n in rate) / (t - rate[0][0]))
                st["eta"] = int((st["total"] - st["bytes"]) / st["speed"]) if st["speed"] else None
            write_json(st_path, st)
            last[0] = t

    def connect():
        f = ftplib.FTP()
        f.connect(host, port, timeout=60)
        f.login()
        f.voidcmd("TYPE I")
        try:
            # ftpsrv decrypts SELF files on download and reports their
            # decrypted size; SELF turns that off for this connection.
            f.sendcmd("SELF")
        except ftplib.all_errors:
            pass
        return f

    def rsize(f, path):
        try:
            f.voidcmd("TYPE I")  # listings switch the connection to ASCII
            return f.size(path)
        except ftplib.all_errors:
            return None

    wakes = [0]

    def ensure_ftp():
        """Wait for ftpsrv, waking the PS5 from rest mode when it went to sleep."""
        if ftp_open(host, port):
            return
        state = ps5_status(host)
        if state == "on":
            # Awake but nothing on this port: give ftpsrv a moment, then say why.
            for _ in range(5):
                time.sleep(2)
                if ftp_open(host, port):
                    return
            hint = " (ftpsrv uses port 2121; change it on the Remote tab)" if port != 2121 else ""
            raise RuntimeError(f"the PS5 is on but nothing answers on {host}:{port}{hint}; "
                               "is ftpsrv running? Then press Send to PS5 again to resume")
        if not cfg["ps5_wake_key"]:
            raise RuntimeError(f"no FTP server at {host}:{port}: is the PS5 on with ftpsrv running? "
                               "(add the Remote Play key to wake it from rest mode)")
        wakes[0] += 1
        if wakes[0] > 5:
            raise RuntimeError("the PS5 kept going to rest mode; set Settings > System > Power Saving > "
                               "Set Time Until PS5 Enters Rest Mode to Don't Put in Rest Mode")
        was, cur = st.get("current", ""), f"waking the PS5 (it was {state})"
        st["current"] = cur
        save(True)
        ps5_wake(host, cfg["ps5_wake_key"])
        deadline = time.time() + 240
        while not ftp_open(host, port):
            if time.time() > deadline:
                raise RuntimeError("woke the PS5 but its FTP server did not answer within 4 minutes "
                                   "(is ftpsrv loaded after rest mode?)")
            if int(time.time()) % 30 == 0:
                ps5_wake(host, cfg["ps5_wake_key"])
            time.sleep(3)
        time.sleep(5)  # give ftpsrv a moment after resume
        st["current"] = was
        st["woken"] = st.get("woken", 0) + 1
        rest_set(woke_at=time.time())  # this page woke it: rest again when done
        save(True)

    # Ask pkg-receiver's Glass build (port 12800) and the LZ4 Compression
    # engine (port 5920), whichever runs, to hold off rest mode while this
    # transfer runs; renewed every minute.
    awake_stop = __import__("threading").Event()
    awake_urls = (f"http://{host}:{RECV_PORT}/api/keep-awake?seconds=",)

    def keep_awake():
        import urllib.request
        while not awake_stop.is_set():
            for u in awake_urls:
                try:
                    with urllib.request.urlopen(u + "180", timeout=4) as r:
                        if r.status == 200 and not st.get("kept_awake"):
                            st["kept_awake"] = True
                except Exception:
                    pass
            awake_stop.wait(60)
        for u in awake_urls:
            try:
                urllib.request.urlopen(u + "0", timeout=4).close()
            except Exception:
                pass
    __import__("threading").Thread(target=keep_awake, daemon=True).start()

    ps5_notify(f"NAS: sending {out.name} ({human(total)})")
    try:
        ensure_ftp()
        ftp = connect()
        # Two copies of one title confuse ShadowMountPlus.
        tid = ""
        pj = out / "sce_sys" / "param.json"
        if not single and pj.is_file():
            tid = parse_param_json(pj.read_bytes())[0].upper()
        if not tid and entry and entry.title_id:
            tid = entry.title_id.upper()
        if not tid:
            m = TITLE_RE.search(out.name)
            tid = m.group(0).upper() if m else ""
        names = ps5_ftp_names(ftp, dest_root)
        if names is None:  # the folder isn't there yet
            names = []
            ps5_ftp_mkdirs(ftp, dest_root)
            ftp.voidcmd("TYPE I")
        # (PS4 packages are installed from there, not mounted: no such limit.)
        dupes = [n for n in names if tid and tid in n.upper() and n != out.name] if not pkg else []
        if dupes and not force:
            raise RuntimeError(f"{dest_root} on the PS5 already has {tid}: {', '.join(dupes)}. "
                               "Delete or move it first (ShadowMountPlus mounts one copy per title)")
        # Room on the drive (idea from ps5upload): refuse a new transfer that
        # can't fit; a resumed one (already partly there) is left to go on.
        if out.name not in names and not force:
            drive = re.match(r"^(/data|/mnt/[^/]+|/user)", dest_root)
            room = drive_space(drive.group(1)) if drive else {}
            if room.get("live_free") is not None and room["live_free"] < total + (1 << 30):
                raise RuntimeError(f"not enough room on the PS5: {human(total)} to send, {human(room['live_free'])} free "
                                   f"on {drive.group(1)} (1 GB kept free). Free some space or pick another drive")
        made = set()

        def mkdirs(path):
            parts, cur = path.strip("/").split("/"), ""
            for part in parts:
                cur += "/" + part
                if cur not in made:
                    try:
                        ftp.mkd(cur)
                    except ftplib.error_perm:
                        pass
                    made.add(cur)

        boot = {"changed": [], "needed": [], "notes": []} if single else boot_files(out, repair=False)
        if any(n.startswith("runtime folder") for n in boot["needed"]):
            raise RuntimeError("the game's runtime folder has the wrong case for the PS5 "
                               "(e.g. PPSA11386): press Check all, then Repair, and send again")
        mkdirs(dest)
        for d in ([] if single else sorted(q for q in out.rglob("*") if q.is_dir())):
            mkdirs(f"{dest}/{d.relative_to(out).as_posix()}")  # empty folders too
        programs = []
        for p in files:
            rel = p.relative_to(root).as_posix()
            remote = f"{dest}/{rel}"
            size = p.stat().st_size
            st["current"] = rel
            with open(p, "rb") as fh:
                if fh.read(4) in PROGRAM_MAGICS:
                    programs.append((p, remote))
            for attempt in range(6):
                try:
                    have = rsize(ftp, remote)
                    if have == size:
                        st["skipped"] += 1
                        break
                    mkdirs(remote.rsplit("/", 1)[0])
                    start = st["bytes"]
                    # A partial file continues where it stopped (ftpsrv honours
                    # REST on STOR); the last MiB is sent again to be safe.
                    offset = max(0, have - (1 << 20)) if have and have < size else 0
                    st["bytes"] += offset

                    def cb(chunk):
                        st["bytes"] += len(chunk)
                        rate.append((time.time(), len(chunk)))
                        save()
                    with open(p, "rb") as fh:
                        fh.seek(offset)
                        ftp.storbinary(f"STOR {remote}", fh, blocksize=1 << 20, callback=cb,
                                       rest=offset or None)
                    got = rsize(ftp, remote)
                    if got is not None and got != size:
                        st["bytes"] = start
                        raise RuntimeError(f"{rel}: PS5 has {got} bytes, expected {size}")
                    if offset and size <= 1 << 30 and (p, remote) not in programs:
                        programs.append((p, remote))  # a joined file is compared byte for byte below
                    if size >= SAMPLE_MIN and (p, remote) not in programs:
                        st["current"] = "spot check " + rel
                        bad = spot_check(ftp, p, remote)
                        if bad:
                            st["bytes"] = start
                            st["spot_failed"] = st.get("spot_failed", 0) + 1
                            try:
                                ftp.sendcmd(f"DELE {remote}")  # ftpsrv answers 226; sent whole again below
                            except ftplib.all_errors:
                                pass
                            raise RuntimeError(f"{rel}: {bad} on the PS5; sending it again")
                        st["spot_checked"] = st.get("spot_checked", 0) + 1
                    break
                except (*ftplib.all_errors, OSError, RuntimeError) as err:
                    if "No space" in str(err) or attempt == 5:
                        raise RuntimeError(f"{rel}: {err}")
                    st["bytes"] = sum(q.stat().st_size for q in files[: st["files_done"]])
                    try:
                        ftp.close()
                    except Exception:
                        pass
                    time.sleep(3)
                    ensure_ftp()  # the PS5 may have gone to rest mode
                    ftp = connect()
            else:
                pass
            st["files_done"] += 1
            st["bytes"] = sum(q.stat().st_size for q in files[: st["files_done"]])
            save()
        # A game that imports libScePlayGo stops at boot without a PlayGo
        # emulator in fakelib/. The LZ4 folder is read-only here, so it goes
        # to the PS5 copy only, taken from the NAS or from the console itself.
        if any("PlayGo" in n for n in boot["needed"]):
            st["current"] = "PlayGo emulator"
            save(True)
            emu = find_playgo_emu(out) or fetch_playgo_emu(ftp, rsize, dest)
            if emu:
                fl = entry_nocase(out, "fakelib") or "fakelib"
                mkdirs(f"{dest}/{fl}")
                with open(emu, "rb") as fh:
                    ftp.storbinary(f"STOR {dest}/{fl}/{PLAYGO_LIB}", fh)
                st["playgo"] = f"PlayGo emulator added to fakelib (from {emu})"
            else:
                st["note"] = (f"the game needs a PlayGo emulator ({PLAYGO_LIB}) and none was found on the NAS "
                              f"or the PS5; put one in {Path(HOST_STATE) / 'playgo'} and send again")
        # Byte check of the program files (the ones ftpsrv would decrypt).
        for p, remote in programs:
            st["current"] = "checking " + p.relative_to(root).as_posix()
            save(True)
            want = hashlib.sha256(p.read_bytes()).hexdigest()
            for attempt in range(2):
                h = hashlib.sha256()
                ftp.retrbinary(f"RETR {remote}", h.update, blocksize=1 << 20)
                if h.hexdigest() == want:
                    break
                if attempt:
                    raise RuntimeError(f"{p.relative_to(root)} differs on the PS5 (SHA-256) after a second upload")
                with open(p, "rb") as fh:  # same size, other bytes: upload it again
                    ftp.storbinary(f"STOR {remote}", fh, blocksize=1 << 20)
            st["verified"] += 1
        # Last look: every file of the game is on the PS5 with its size, from
        # a fresh listing (no file reads), so nothing can have been dropped.
        if not single:
            st["current"] = "checking that every file is there"
            save(True)
            there = ps5_remote_sizes(ftp, dest)
            lost = [p.relative_to(root).as_posix() for p in files
                    if there.get(p.relative_to(root).as_posix(), -1) != p.stat().st_size]
            if lost:
                raise RuntimeError(f"{len(lost)} file(s) missing or the wrong size on the PS5 "
                                   f"(e.g. {lost[0]}); press Send again to fill them in")
            st["complete"] = len(files)
        ftp.quit()
        awake_stop.set()
        st.update(state="done", current="", finished=now())
        save(True)
        ps5_notify(f"NAS: {out.name} is on the PS5 and checked", wait=True)
        print(f"done: {out.name} -> {st['dest']} ({human(total)}, {st['verified']} program files "
              f"checked byte for byte, {st['skipped']} already there)")
        for k in ("playgo", "note"):
            if st.get(k):
                print(st[k])
        return 0
    except Exception as err:
        awake_stop.set()
        st.update(state="failed", error=str(err)[:500], finished=now())
        ps5_notify(f"NAS: sending {out.name} stopped: {str(err)[:120]}", wait=True)
        save(True)
        print(f"FAILED: {err}", file=sys.stderr)
        return 1


REQUESTS = STATE / "requests"
STEPS = ["source", "check", "pack", "verify", "restore", "publish"]
UI_ACTIONS = {  # action -> ps5lz4 arguments (game and result are checked separately)
    "fix": ["lz4", "--fix"],
    "check": ["apr"],
    "check_full": ["apr", "--full"],
    "apr": ["apr", "--fix"],
    "stop": ["stop"],
    "resume": ["start", "--resume"],
    "start": ["start"],
    "community": ["community"],
    "remove": ["remove"],
    "delete_original": ["delete-original"],
    "make_exfat": ["make-exfat"],
    "remove_exfat": ["remove-exfat"],
    "extract": ["extract"],
    "verify_lz4": ["verify-lz4"],
    "delete_rars": ["delete-rars"],
}


def job_running() -> tuple[bool, str]:
    running = False
    try:
        with open(LOCK_PATH, "a+") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                running = True
    except OSError:
        pass
    text = LOCK_PATH.read_text().strip() if LOCK_PATH.exists() else ""
    return running, text


# What a step's progress line measures, by the .err file it is in.
PROGRESS_PHASE = {"pack": "packing", "verify": "checking every chunk", "restore": "unpacking",
                  "restore-compare": "comparing with the original"}


def work_progress(w: Path) -> tuple[int, int, str] | None:
    best = None
    for errf in sorted(w.glob("*.err"), key=lambda f: f.stat().st_mtime):
        try:
            with open(errf, "rb") as f:
                f.seek(max(0, f.seek(0, 2) - 4096))
                tail = f.read().decode(errors="replace")
        except OSError:
            continue
        m = re.findall(r"\[progress\] (\d+) / (\d+)", tail)
        if m:
            best = (int(m[-1][0]), int(m[-1][1]), PROGRESS_PHASE.get(errf.stem, ""))
    st = read_json(w / "state.json", {}) or {}
    if st.get("runtime") == "ng":
        phase = str(st.get("step", "")).split(" ")[0]
        path = w / f"{phase}.out"
        try:
            with path.open("rb") as f:
                f.seek(max(0, f.seek(0, 2) - 16384))
                for line in reversed(f.read().decode(errors="replace").splitlines()):
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("kind") == "progress":
                        best = (int(event.get("done", 0)), int(event.get("total", 0)),
                                f"{st.get('codec', 'lz4')} {event.get('stage', phase)}")
                        break
        except OSError:
            pass
    exp = st.get("expect")
    if best is None and exp and str(st.get("step", "")).startswith("source"):
        # Unpacking an image: how much of the expected size is on disk so far.
        _files, got = tree_bytes(w / exp["folder"]) if (w / exp["folder"]).is_dir() else (0, 0)
        best = (min(got, exp["total"]), exp["total"], exp["phase"])
    return best


# Time left for the packing job, worked out where the page is served so it is
# there as soon as the page opens: the rate over the last minutes (or since the
# step started), and for the steps still to come the rate earlier games had.
PROG_SEEN: dict = {}
RATES_PATH = STATE / "rates.json"
LATER_PHASES = {"pack": ["checking every chunk", "unpacking", "comparing with the original"],
                "verify": ["unpacking", "comparing with the original"], "restore": []}


def job_eta(current: str, st: dict, prog, restore_test: bool = True) -> dict | None:
    if not prog or not prog[1]:
        return None
    done, total, phase = prog
    t = time.time()
    h = PROG_SEEN.setdefault((current, phase), [])
    if h and done < h[-1][1]:
        h.clear()
    if not h or h[-1][1] != done:
        h.append((t, done))
    while len(h) > 2 and t - h[1][0] > 600:
        h.pop(0)
    rate = None
    if len(h) > 1 and h[-1][0] - h[0][0] >= 30:
        rate = (h[-1][1] - h[0][1]) / (h[-1][0] - h[0][0])
    if not rate and st.get("step_at") and t - st["step_at"] > 30 and done:
        rate = done / (t - st["step_at"])
    rates = read_json(RATES_PATH, {}) or {}
    if rate and done >= total and len(h) > 1 and h[-1][0] - h[0][0] >= 60:
        rates[phase] = round(rate if phase not in rates else 0.5 * rates[phase] + 0.5 * rate)
        write_json(RATES_PATH, rates)
    if not rate and rates.get(phase):
        rate = rates[phase]
    out = {"rate": rate, "step_left": (total - done) / rate if rate else None}
    # The steps after this one each go through about the game's size again.
    step = str(st.get("step", "")).split(" ")[0]
    size = st.get("source_bytes") or (total if phase == "packing" else None)
    later = LATER_PHASES.get(step)
    if later is not None and step == "restore" and phase == "unpacking":
        later = ["comparing with the original"]
    if later is not None and (not restore_test or (size and RESTORE_TEST_MAX and size > RESTORE_TEST_MAX)):
        later = [p for p in later if p == "checking every chunk"]
    if out["step_left"] is not None and later is not None and size:
        rest = [size / rates[p] for p in later if rates.get(p)]
        out["job_left"] = out["step_left"] + sum(rest) if len(rest) == len(later) else None
        out["later"] = len(later)
    return out


def lz4_folder_info(out: Path, cache: dict | None = None) -> dict:
    """Size, file count and pack volumes of a packed game folder (cached by mtime)."""
    try:
        sig = f"{int(out.stat().st_mtime)}:{int(packed_index(out).stat().st_mtime)}"
    except OSError:
        sig = None
    key = "out:" + str(out)
    hit = (cache or {}).get(key)
    # Older cached folder summaries did not store the pack codec.
    if hit and sig and hit.get("sig") == sig and "pack_codec" in hit["info"]:
        return hit["info"]
    files, total = tree_bytes(out)
    info = {"path": host_output_path(out), "files": files, "bytes": total,
            "pack_codec": packed_codec(out), "paks": len(list(out.glob("ampr_zstd-*.pak" if packed_codec(out) == "zstd" else "ampr_assets-*.pak"))), "problem": lz4_format_problem(out)}
    pj = out / "sce_sys" / "param.json"
    if pj.is_file():
        try:
            info["title_id"], info["name"] = parse_param_json(pj.read_bytes())
        except Exception:
            pass
    if cache is not None and sig:
        cache[key] = {"sig": sig, "info": info}
    return info


def dashboard_data() -> dict:
    ensure_dirs()
    running, lock_text = job_running()
    queue = read_json(QUEUE_PATH, {}) or {}
    cache = CheckDB()
    games = ng_reports()
    rows, totals = [], {"lz4": 0, "source": 0, "output": 0}
    source_copies = []
    entries = scan_library()
    current = queue.get("current") if running else None
    for e in entries:
        if e.kind == "folder":
            source_codec = packed_codec(e.path) if is_packed(e.path) else None
        else:
            source_codec = _safe(lambda: image_meta(e.path).get("pack_codec"), None)
        res = result_for(e)
        if e.duplicate_of and res["status"] != "done" and not source_codec:
            continue
        if source_codec:
            verdict, why, can = ("Zstd" if source_codec == "zstd" else "LZ4"), "already packed", False
        else:
            verdict, why, can = classify(e, res, cache)
        skey = "size:" + str(e.path)
        try:
            ssig = f"{int(e.path.stat().st_mtime)}"
            hit = cache.get(skey)
            if hit and hit.get("sig") == ssig:
                src_size = hit["bytes"]
            else:
                src_size = e.size()
                cache[skey] = {"sig": ssig, "bytes": src_size}
        except OSError:
            src_size = None
        rep = read_json(REPORTS / f"{e.id}.json") or {}
        g = games.get((e.title_id or "").upper()) or {}
        row = {"id": e.id, "rel": e.rel, "source_path": str(Path(HOST_LIBRARY) / e.rel), "kind": e.kind,
               "source_codec": source_codec,
               "not_in_use": bool(e.duplicate_of),
               "source_size": src_size, "title_id": e.title_id,
               "name": rep.get("title_name") or e.name or nice_folder_name(e, games),
               "verdict": verdict, "why": why,
               "can_queue": can, "running": e.id == current,
               "queued": e.id in (queue.get("remaining") or []) and running,
               "source_bytes": rep.get("source_bytes"), "output_bytes": rep.get("output_bytes"),
               "pack_codec": rep.get("pack_codec", "lz4"), "pack_runtime": rep.get("pack_runtime", "legacy"),
               "saved_percent": rep.get("saved_percent"), "ps5": ps5_result(e.id), "finished": rep.get("finished"),
               "output": host_output_path(e.output) if e.output.is_dir() else None}
        if source_codec:
            runtime = None
            if e.kind == "folder":
                sha = _safe(lambda: runtime_sha(e.path), "")
                if sha:
                    runtime = "ng" if sha in (NG_SHA256, NG_UPSTREAM_SHA256) else "legacy"
            source_copies.append({"id": f"src:{e.id}", "game": e.id, "codec": source_codec,
                                  "runtime": runtime, "name": row["name"], "title_id": e.title_id,
                                  "path": row["source_path"], "bytes": src_size, "ps5": row["ps5"],
                                  "kind": e.kind, "transfer_name": e.path.name,
                                  "busy": row["running"]})
        elif verdict == "LZ4" and rep:
            totals["lz4"] += 1
            totals["source"] += rep.get("source_bytes", 0)
            totals["output"] += rep.get("output_bytes", 0)
        rows.append(row)
    # LZ4 games in the output folder without a source in the library
    # (original removed, or packed somewhere else).
    known = {e.output.name for e in entries}
    for out in output_items():
        if out.name.startswith(".") or out.name in known or not out.is_dir() \
                or not is_packed(out):
            continue
        info = lz4_folder_info(out, cache)
        rep = {}
        for f in REPORTS.glob("*.json"):
            if f.name == re.sub(r"-(lz4|zstd)$", "", out.name) + ".json":
                rep = read_json(f, {}) or {}
        tid = (info.get("title_id") or rep.get("title_id") or "").upper()
        if not tid:
            m = TITLE_RE.search(out.name)
            tid = m.group(0).upper() if m else ""
        g = games.get(tid) or {}
        problem = info["problem"]
        rows.append({"id": out.name, "rel": out.name, "kind": "lz4", "title_id": tid,
                     "name": rep.get("title_name") or info.get("name") or out.name,
                     "verdict": "LZ4" if not problem else "error",
                     "why": "only in the LZ4 folder (the original is not in the library)" if not problem else problem,
                     "can_queue": False, "running": False, "queued": False, "output_only": True,
                     "pack_codec": packed_codec(out), "pack_runtime": "ng" if runtime_sha(out) == NG_SHA256 else "legacy",
                     "source_bytes": rep.get("source_bytes"), "output_bytes": rep.get("output_bytes") or info["bytes"],
                     "saved_percent": rep.get("saved_percent"), "ps5": rep.get("ps5_result"),
                     "output": info["path"]})
    # Every packed copy (LZ4 and Zstd) on its own, for the page's LZ4 and Zstd
    # tabs: a game can have both, and its report only describes the last pack.
    by_id = {e.id: e for e in entries}
    sizes = {r["id"]: r.get("source_size") for r in rows}
    copies = []
    for out in output_items():
        if out.name.startswith(".") or not out.is_dir() or out.is_symlink() or not is_packed(out):
            continue
        info = lz4_folder_info(out, cache)
        codec = info["pack_codec"]
        gid = re.sub(r"-(lz4|zstd)$", "", out.name)
        e = by_id.get(gid)
        rep = read_json(REPORTS / f"{gid}.json") or {}
        same = rep.get("pack_codec", "lz4") == codec and rep.get("output") == info["path"]
        src = rep.get("source_bytes") if same else sizes.get(e.id) if e else None
        copies.append({"id": out.name, "game": e.id if e else None, "codec": codec,
                       "runtime": "ng" if runtime_sha(out) == NG_SHA256 else "legacy",
                       "name": (rep.get("title_name") if same else None) or info.get("name") or (e.name if e else out.name),
                       "title_id": (info.get("title_id") or (e.title_id if e else "") or "").upper(),
                       "path": info["path"], "bytes": info["bytes"], "source_bytes": src,
                       "saved_percent": round(100.0 * (src - info["bytes"]) / src, 1) if src else None,
                       "ps5": ps5_result(e.id) if e and same else None,
                       "finished": rep.get("finished") if same else None, "problem": info["problem"],
                       "busy": bool(running and current and out.name in (f"{current}-lz4", f"{current}-zstd"))})
    managed_paths = {c["path"] for c in copies}
    copies.extend(c for c in source_copies if c["path"] not in managed_paths)
    cache.close()
    job = None
    if running and current:
        st = read_json(WORK / current / "state.json", {}) or {}
        step = str(st.get("step", "")).split(" ")[0]
        job = {"id": current, "step": step, "done": st.get("done", []), "steps": STEPS,
               "progress": work_progress(WORK / current), "since": lock_text}
        try:
            job["eta"] = job_eta(current, st, job["progress"],
                                 not (queue.get("options") or {}).get("no_restore_test"))
        except Exception:
            job["eta"] = None
    failed = []
    if WORK.is_dir():
        for w in sorted(WORK.iterdir()):
            st = read_json(w / "state.json", {}) or {}
            if st.get("error") and w.name != current:
                failed.append({"id": w.name, "step": st.get("step"), "error": st["error"]})
    done_req = []
    if REQUESTS.is_dir():
        for f in sorted(REQUESTS.glob("*.done.json"), key=lambda f: f.stat().st_mtime)[-5:]:
            done_req.append(read_json(f, {}))
    pending_list = [{**(read_json(f, {}) or {}), "file": f.name}
                    for f in sorted(REQUESTS.glob("*.req.json"))] if REQUESTS.is_dir() else []
    pending = len(pending_list)
    try:
        agent_age = int(time.time() - (REQUESTS / ".agent-alive").stat().st_mtime)
    except OSError:
        agent_age = None
    return {"running": running, "job": job, "queue": queue.get("remaining") or [],
            "interrupted": (not running) and bool(queue.get("remaining")),
            "free_bytes": free_bytes(OUTPUT), "games": rows, "copies": copies, "totals": totals, "failed": failed,
            "zstd_output_host": host_output_path(zstd_output()),
            "delete_originals": DELETE_ORIGINALS,
            "archives": _safe(scan_archives, []),
            "unreadable": sorted(UNREADABLE), "uid": os.getuid(), "library_host": HOST_LIBRARY,
            "duplicates": _safe(library_duplicates, []),
            "verifies": _safe(verify_states, {}),
            "send_after": list(read_json(SEND_AFTER, {}) or {}),
            "images": images_data(),
            "pkgs": (pkgs := scan_pkgs()), "pkg_folders": pkg_folders(pkgs),
            "level": int(os.environ.get("PS5LZ4_ZSTD_LEVEL", "5")), "runtime": NG_NAME,
            "compat_updated": None,
            "requests": {"pending": pending, "pending_list": pending_list, "recent": done_req[::-1],
                         "agent_age": agent_age}, "version": VERSION,
            "settings": {**get_settings(), "ps5_wake_key": "set" if get_settings()["ps5_wake_key"] else "",
                         "paired": {k: (read_json(SETTINGS_PATH, {}) or {}).get(k) for k in ("ps5_nickname", "ps5_paired")},
            "github_token": "set" if github_token() else ""},
            "transfer": transfer_running(),
            "transfers": {f.stem: read_json(f, {}) for f in transfer_files()},
            "transfer_queue": transfer_queue()}


# The community's .ffpfsc compatibility list (a Google Sheet), fetched as CSV
# where the page runs and shown in a game's sheet with the sheet's own column
# names. PS5LZ4_FFPFSC_SHEET is the sheet's CSV export URL ("" turns it off).
FFPFSC_SHEET = os.environ.get(
    "PS5LZ4_FFPFSC_SHEET",
    "https://docs.google.com/spreadsheets/d/1dgu0p7U2yB_mhcUELz-Wkc7Yhs-avoWLY1Gcm0n5XJw/export?format=csv&gid=357033774")
FFPFSC_PAGE = re.sub(r"/export\?format=csv&gid=(\d+)$", r"/edit#gid=\1", FFPFSC_SHEET)
FFPFSC_PATH = STATE / "ffpfsc_sheet.json"
FFPFSC_EVERY = 6 * 3600


def ffpfsc_refresh() -> dict:
    import csv
    import io
    import urllib.request
    req = urllib.request.Request(FFPFSC_SHEET, headers={"User-Agent": "ps5-lz4"})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read(20 << 20).decode("utf-8-sig", errors="replace")
    rows = [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]
    rows = [r for r in rows if any(r)]
    if not rows:
        raise ValueError("the sheet is empty")
    # The header is the first row with several filled cells before the first
    # row that holds a title ID (sheets often start with a title or notes).
    first_data = next((i for i, r in enumerate(rows) if any(TITLE_RE.search(c) for c in r)), len(rows))
    head_i = max((i for i in range(first_data) if sum(1 for c in rows[i] if c) >= 2), default=None)
    if head_i is None:
        head_i, headers = -1, [f"Column {i + 1}" for i in range(max(len(r) for r in rows))]
    else:
        headers = [c or f"Column {i + 1}" for i, c in enumerate(rows[head_i])]
    data = []
    for r in rows[head_i + 1:]:
        cells = {headers[i] if i < len(headers) else f"Column {i + 1}": c for i, c in enumerate(r) if c}
        if len(cells) >= 2:
            data.append(cells)
    out = {"at": time.time(), "url": FFPFSC_PAGE, "headers": headers, "rows": data}
    write_json(FFPFSC_PATH, out)
    return out


def ffpfsc_sheet() -> dict:
    return read_json(FFPFSC_PATH, {}) or {}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower().replace("&", "and"))


def ffpfsc_lookup(title_id: str, name: str) -> list[dict]:
    """Rows of the sheet for this game: by title ID in any cell, else by name."""
    rows = ffpfsc_sheet().get("rows") or []
    tid = (title_id or "").upper()
    hits = [r for r in rows if tid and any(tid in c.upper() for c in r.values())]
    if not hits and name:
        n = _norm(re.sub(r"\[[^\]]*\]|\([^)]*\)", "", name))
        if len(n) >= 4:
            hits = [r for r in rows if any(_norm(c) == n for c in r.values())]
    return hits[:5]


def ffpfsc_refresher() -> None:
    """Web page container: keep the sheet fresh."""
    while True:
        try:
            if time.time() - ffpfsc_sheet().get("at", 0) > FFPFSC_EVERY - 60:
                n = len(ffpfsc_refresh()["rows"])
                print(f"[{now()}] ffpfsc sheet: {n} rows", flush=True)
        except Exception as err:
            print(f"[{now()}] ffpfsc sheet: {err}", flush=True)
        time.sleep(1800)


def game_detail(game_id: str) -> dict:
    """Everything known about one game, for the page's detail view."""
    out = None
    rep = read_json(REPORTS / f"{game_id}.json") or {}
    for e in scan_library():
        if e.id == game_id:
            out = e.output
            break
    if out is None and output_item(game_id).is_dir():
        out = output_item(game_id)
        rep = rep or read_json(REPORTS / f"{game_id.rsplit('-', 1)[0]}.json") or {}
    cache = CheckDB()
    folder = lz4_folder_info(out, cache) if out and out.is_dir() else None
    cache.close()
    work = read_json(WORK / game_id / "state.json") or None
    skipped = read_json(REPORTS / f"{game_id}.skipped.json") or None
    tid = ((rep or {}).get("title_id") or (folder or {}).get("title_id") or "").upper()
    if not tid:
        m = TITLE_RE.search(game_id)
        tid = m.group(0).upper() if m else ""
    apr = None
    if out and out.is_dir():
        rt = find_runtime(out)
        if rt:
            sha = hashlib.sha256(rt.read_bytes()).hexdigest()
            apr = {"path": host_output_path(rt), "ok": runtime_ok(out, sha), "build": runtime_name(sha)}
        else:
            apr = {"path": None, "ok": False, "build": "missing"}
    src = next((e for e in scan_library() if e.id == game_id), None)
    if not tid and src and src.title_id:
        tid = src.title_id.upper()  # an original with no pack yet: its own param.json
    version = game_version(*(x for x in (out, src.path if src and src.kind == "folder" else None) if x),
                           name=(src.rel if src else "") or (out.name if out else game_id))
    return {"id": game_id, "report": rep or None, "folder": folder, "work": work, "skipped": skipped,
            "title_id": tid, "ng_submitted": (read_json(NG_SUBMITTED, {}) or {}).get(game_id) or [],
            "ng_reports": ng_reports().get(tid), "ng_reports_web": NG_REPORT_WEB,
            "ng_reports_at": (read_json(NG_REPORTS, {}) or {}).get("updated") if NG_REPORTS_ON else None,
            "apr": apr,
            "unity": UNITY_WHY if (out and out.is_dir() and unity_folder(out)) or
                     (src and src.kind == "folder" and unity_folder(src.path)) else None,
            "version": version,
            "ffpfsc": {"rows": ffpfsc_lookup(tid, (src.name or Path(src.rel).name.removesuffix(src.path.suffix if src.kind != "folder" else ""))
                                             if src else game_id.removesuffix("-lz4")),
                       "url": FFPFSC_PAGE, "at": ffpfsc_sheet().get("at")} if FFPFSC_SHEET else None}


def cmd_dashboard(_args) -> int:
    print(json.dumps(dashboard_data(), ensure_ascii=False, indent=1))
    return 0


def queued_request(req: dict) -> dict:
    # Keep compression options across the UI-container -> worker-container queue.
    return {k: req[k] for k in ("action", "game", "result", "codec", "runtime", "level", "profile") if k in req}


def run_request(req: dict) -> dict:
    action = req.get("action")
    if action not in UI_ACTIONS:
        return {"ok": False, "output": f"unknown action {action!r}"}
    argv = list(UI_ACTIONS[action])
    if action in ("start", "community", "remove", "delete_original", "make_exfat", "remove_exfat", "extract", "delete_rars",
                  "verify_lz4"):
        game = str(req.get("game") or "")
        if not game or game.startswith("-") or len(game) > 300:
            return {"ok": False, "output": "no game given"}
        argv.append(game)
    if action == "start" or (action == "fix" and "codec" in req):  # Compress all without a format: as before
        codec, runtime = req.get("codec", "zstd"), req.get("runtime", "ng")
        level = req.get("level", 5)
        if codec != "zstd" or runtime != "ng":
            return {"ok": False, "output": "only Zstd is packed now"}
        if type(level) is not int or not 1 <= level <= (22 if codec == "zstd" else 12):
            return {"ok": False, "output": "invalid compression level"}
        argv += ["--codec", codec, "--runtime", runtime, "--level", str(level)]
        if req.get("profile") is False:
            argv.append("--no-profile")
    if action == "community":
        result = req.get("result")
        if result not in PLAY_STATES:
            return {"ok": False, "output": f"unknown result {result!r}"}
        argv.append(result)
    me = [sys.executable, os.path.abspath(__file__)]
    if action in ("make_exfat", "extract", "delete_rars", "verify_lz4"):
        # Long jobs: they run on their own; the page follows state/images (state/extract).
        log = LOGS / f"{'exfat' if action == 'make_exfat' else 'extract-run'}-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        with open(log, "a") as fh:
            subprocess.Popen(["nohup"] + me + argv, stdout=fh, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        return {"ok": True, "output": f"started; log: {log.name}"}
    if action in ("check", "check_full"):
        # "Check all": read-only. Format and APR-EMU of every LZ4 game, and
        # which games can still become LZ4. Nothing is changed.
        rep = subprocess.run(me + argv, capture_output=True, text=True, timeout=6 * 3600)
        lst = subprocess.run(me + ["lz4"] + (["--full"] if action == "check_full" else []),
                             capture_output=True, text=True, timeout=3600)
        text = ("LZ4 games:\n" + (rep.stdout + rep.stderr).strip() +
                "\n\nLibrary:\n" + (lst.stdout + lst.stderr).strip())
        return {"ok": rep.returncode == 0, "output": text[-3000:]}
    out = subprocess.run(me + argv, capture_output=True, text=True, timeout=6 * 3600)
    text = (out.stdout + out.stderr).strip()
    return {"ok": out.returncode == 0, "output": text[-3000:]}


def log_action(res: dict) -> None:
    """Append one line per page action to state/actions.log. The page keeps only
    the last 20 results; this file keeps them all, to trace what was done when."""
    try:
        line = {k: res.get(k) for k in ("finished", "action", "game", "result", "ok")}
        line["output"] = (res.get("output") or "")[-600:]
        with open(STATE / "actions.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


def cmd_agent(_args) -> int:
    """Runs in the ps5-lz4 container: carries out requests from the web page."""
    ensure_dirs()
    REQUESTS.mkdir(exist_ok=True)
    print(f"[{now()}] agent: watching {REQUESTS}", flush=True)
    alive = REQUESTS / ".agent-alive"
    while True:
        alive.touch()  # the page tells "not picked up" from "waiting for a job"
        for f in sorted(REQUESTS.glob("*.req.json")):
            req = read_json(f, {}) or {}
            if req.get("action") in ("start", "fix", "resume") and job_running()[0]:
                continue  # waits for the running job; picked up when it is done
            f.unlink(missing_ok=True)
            print(f"[{now()}] agent: {req.get('action')} {req.get('game') or ''}", flush=True)
            try:
                res = run_request(req)
            except Exception as err:
                res = {"ok": False, "output": str(err)}
            res.update(action=req.get("action"), game=req.get("game"), result=req.get("result"),
                       asked=req.get("asked"), finished=now())
            write_json(REQUESTS / (f.name[: -len(".req.json")] + ".done.json"), res)
            log_action(res)
        olds = sorted(REQUESTS.glob("*.done.json"), key=lambda f: f.stat().st_mtime)
        for f in olds[:-20]:
            f.unlink(missing_ok=True)
        time.sleep(2)


_push_lock = __import__("threading").Lock()


def start_push(game: str, force: bool = False) -> dict:
    """Start sending a game to the PS5, or queue it behind the running transfer."""
    with _push_lock:
        q = transfer_queue()
        starting = TRANSFERS / ".starting"
        just_started = starting.exists() and time.time() - starting.stat().st_mtime < 20
        if transfer_running() or just_started:  # after the current one, in order
            if game not in q:
                transfer_queue_set(q + [game])
            return {"queued": game, "position": transfer_queue().index(game) + 1}
        argv = [sys.executable, os.path.abspath(__file__), "push", game] + (["--force"] if force else [])
        TRANSFERS.mkdir(exist_ok=True)
        starting.touch()  # until the new process has written its state
        with open(os.devnull, "w") as devnull:
            subprocess.Popen(argv, stdout=devnull, stderr=devnull, stdin=subprocess.DEVNULL,
                             start_new_session=True)
        return {"started": True}


def transfer_queue_watcher() -> None:
    """Web page container: games waiting in the transfer queue start by
    themselves as soon as nothing is being sent (after a game is done, after
    Stop, or after the container restarted), so no Start button is needed."""
    while True:
        try:
            q = transfer_queue()
            starting = TRANSFERS / ".starting"
            busy = starting.exists() and time.time() - starting.stat().st_mtime < 20
            if q and not busy and not transfer_running() and get_settings()["ps5_ftp"]:
                time.sleep(5)  # let a process that just finished hand over itself
                q = transfer_queue()
                if q and not transfer_running():
                    print(f"[{now()}] transfer queue: starting {q[0]}", flush=True)
                    start_push(q[0])
        except Exception as err:
            print(f"[{now()}] transfer queue: {err}", flush=True)
        time.sleep(10)


SEND_AFTER = STATE / "send_after.json"  # games to send to the PS5 once they are packed


def send_after_watcher() -> None:
    """Web page container: when a game marked 'Compress and send' is packed,
    send it (or queue it). A game that fails or is skipped is dropped."""
    while True:
        try:
            lst = read_json(SEND_AFTER, {}) or {}
            lst = lst if isinstance(lst, dict) else {}
            if lst:
                keep = {}
                entries = {e.id: e for e in scan_library()}
                for gid, v in lst.items():
                    e = entries.get(gid)
                    res = result_for(e) if e else {"status": "gone"}
                    at = v["at"] if isinstance(v, dict) else v
                    if res["status"] == "done" and e.output.is_dir() and isinstance(v, dict) and v.get("image"):
                        # Compress, make exFAT and send: the image of the LZ4 copy goes.
                        img = lz4_image_path(e.output)
                        job = read_json(IMAGES / f"{e.output.name}.json", {}) or {}
                        stale = job.get("state") == "running" and time.time() - job.get("updated", 0) > 120
                        if img.is_file() and job.get("state") in (None, "done"):
                            if get_settings()["ps5_ftp"]:
                                start_push("img:" + img.name)
                            print(f"[{now()}] image made, sending to the PS5: {img.name}", flush=True)
                        elif v.get("asked") and (job.get("state") in ("failed", "stopped") or stale
                                                 or (not job and time.time() - v["asked"] > 600)):
                            print(f"[{now()}] not sending {gid}: the exFAT image was not made", flush=True)
                        else:
                            if not v.get("asked"):
                                req = {"action": "make_exfat", "game": e.output.name, "result": None, "asked": now()}
                                write_json(REQUESTS / f"{int(time.time() * 1000)}-{os.getpid()}.req.json", req)
                                v = {**v, "asked": time.time()}
                            keep[gid] = v
                    elif res["status"] == "done" and e.output.is_dir():
                        if get_settings()["ps5_ftp"]:
                            start_push(e.output.name)
                        print(f"[{now()}] packed, sending to the PS5: {e.output.name}", flush=True)
                    elif res["status"] in ("skipped", "exists", "gone"):
                        print(f"[{now()}] not sending {gid}: {res['status']}", flush=True)
                    elif res["status"] == "failed" and not job_running()[0] and time.time() - at > 180:
                        print(f"[{now()}] not sending {gid}: packing failed", flush=True)
                    else:
                        keep[gid] = v
                if keep != lst:
                    write_json(SEND_AFTER, keep)
        except Exception as err:
            print(f"[{now()}] send-after: {err}", flush=True)
        time.sleep(20)


# Rest mode when the work is done: if this page woke the PS5 to send games,
# it is put back in rest mode (through the engine's /api/lzc/rest) once
# nothing is being sent or waits to be sent and a few minutes have passed.
# A PS5 that was already on (someone may be playing) is left alone.
REST_PATH = STATE / "rest.json"
REST_IDLE = int(os.environ.get("PS5LZ4_REST_IDLE", "180"))


def rest_info() -> dict:
    r = read_json(REST_PATH, {}) or {}
    r.setdefault("on", False)  # needs the LZ4 engine on the PS5; pkg-receiver can't
    return r


def rest_set(**kw) -> dict:
    r = rest_info()
    r.update(kw)
    write_json(REST_PATH, r)
    return r


def ps5_rest() -> dict:
    """Rest mode needs a payload on the PS5 that offers it; pkg-receiver doesn't."""
    raise ValueError("rest mode is not available: nothing on the PS5 offers it any more")


def rest_watcher() -> None:
    """Web page container: rest the PS5 when the work this page woke it for is done."""
    idle_since = None
    while True:
        try:
            r = rest_info()
            starting = TRANSFERS / ".starting"
            busy = (transfer_running() or transfer_queue() or (read_json(SEND_AFTER, {}) or {})
                    or (starting.exists() and time.time() - starting.stat().st_mtime < 60))
            if not (r["on"] and r.get("woke_at")) or busy:
                idle_since = None
            else:
                idle_since = idle_since or time.time()
                if time.time() - idle_since >= REST_IDLE:
                    try:
                        ps5_rest()
                        rest_set(woke_at=None, last=now(), error=None)
                    except ValueError as err:
                        if "busy" not in str(err):
                            rest_set(woke_at=None, error=str(err))
                            print(f"[{now()}] rest mode: {err}", flush=True)
                    idle_since = None
        except Exception as err:
            print(f"[{now()}] rest watcher: {err}", flush=True)
        time.sleep(30)


def cmd_ui(args) -> int:
    """Serves the web page. Reads state, writes only request files."""
    import http.server
    ensure_dirs()
    REQUESTS.mkdir(exist_ok=True)
    cache = {"at": 0.0, "body": b""}
    lock = __import__("threading").Lock()

    def refresh_dashboard() -> None:
        """Rebuild the page's data; one rebuild at a time, the others return."""
        if not lock.acquire(blocking=not cache["body"]):
            return
        try:
            if cache["body"] and time.time() - cache["at"] <= 4:
                return
            try:
                cache["body"] = json.dumps(dashboard_data(), ensure_ascii=False).encode()
            except Exception as err:
                cache["body"] = json.dumps({"error": str(err)}).encode()
            cache["at"] = time.time()
        finally:
            lock.release()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self.send(200, UI_HTML.encode(), "text/html")
            if self.path.startswith("/api/estimate?"):
                from urllib.parse import parse_qs, urlparse
                try:
                    return self.send(200, json.dumps(estimate_game((parse_qs(urlparse(self.path).query).get("id") or [""])[0])).encode())
                except (ValueError, OSError, subprocess.SubprocessError) as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path in ("/store", "/store/"):
                return self.send(200, STORE_HTML.encode(), "text/html")
            if self.path.startswith("/api/game?"):
                from urllib.parse import parse_qs, urlparse
                gid = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
                if not gid or "/" in gid or gid.startswith("."):
                    return self.send(400, b'{"error":"bad id"}')
                try:
                    body = game_detail(gid)
                except Exception as err:
                    body = {"error": str(err)}
                return self.send(200, json.dumps(body, ensure_ascii=False).encode())
            if self.path.startswith("/api/ftp/list?"):
                from urllib.parse import parse_qs, urlparse
                path = (parse_qs(urlparse(self.path).query).get("path") or ["/"])[0]
                try:
                    return self.send(200, json.dumps(ps5_ftp_list(path), ensure_ascii=False).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path.startswith("/api/ftp/icon?") or self.path.startswith("/api/icon?"):
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                try:
                    if self.path.startswith("/api/icon?"):
                        gid = (q.get("id") or [""])[0]
                        png = None if not gid or "/" in gid or gid.startswith(".") else nas_icon(gid)
                    else:
                        png = ps5_ftp_icon((q.get("path") or [""])[0])
                except Exception:
                    png = None
                if not png:
                    return self.send(404, b'{"error":"no icon"}')
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "max-age=86400")
                self.send_header("Content-Length", str(len(png)))
                self.end_headers()
                self.wfile.write(png)
                return
            if self.path.startswith("/pkgfile/"):
                return self.send_pkgfile()
            if self.path == "/api/ps5/find":
                try:
                    return self.send(200, json.dumps({"found": ps5_find(self.headers.get("Host") or "")}).encode())
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path.startswith("/api/ps5/verify?"):
                from urllib.parse import parse_qs, urlparse
                try:
                    key = ps5_ftp_path((parse_qs(urlparse(self.path).query).get("path") or [""])[0])
                except ValueError:
                    key = ""
                return self.send(200, json.dumps(_verify.get(key) or {"state": "none"}).encode())
            if self.path == "/metrics":
                return self.send(200, metrics_text().encode(), "text/plain; version=0.0.4")
            if self.path == "/api/pkg/onps5":
                try:
                    return self.send(200, json.dumps(pkg_ps5_states()).encode())
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path.startswith("/api/ps5/launchcheck?"):
                from urllib.parse import parse_qs, urlparse
                try:
                    return self.send(200, json.dumps(launch_check((parse_qs(urlparse(self.path).query).get("tid") or [""])[0])).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path.startswith("/api/ps5/amprlog?"):
                from urllib.parse import parse_qs, urlparse
                try:
                    return self.send(200, json.dumps(ampr_log((parse_qs(urlparse(self.path).query).get("path") or [""])[0])).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path == "/api/saves":
                return self.send(200, json.dumps({"job": _saves_job, "backups": saves_list()}).encode())
            if self.path.startswith("/api/saves/zip?"):
                from urllib.parse import parse_qs, urlparse
                try:
                    return saves_zip(self, (parse_qs(urlparse(self.path).query).get("b") or [""])[0])
                except ValueError as err:
                    return self.send(404, json.dumps({"error": str(err)}).encode())
            if self.path == "/api/smp/games":
                try:
                    return self.send(200, json.dumps({**smp("/api/v1/games", {"include_size": False}),
                                                      "version": smp("/api/v1/version").get("shadowmount_version")}).encode())
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path in ("/api/smp/storage", "/api/smp/job"):
                try:
                    res = smp("/api/v1/storage") if self.path.endswith("storage") else smp("/api/v1/games/storage/status", {})
                    return self.send(200, json.dumps(res).encode())
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path.startswith("/api/smp/icon?"):
                import urllib.request
                from urllib.parse import parse_qs, urlparse
                tid = (parse_qs(urlparse(self.path).query).get("tid") or [""])[0].upper()
                png = None
                if re.fullmatch(r"(CUSA|PPSA|LAPY|FAKE)\d{5}", tid):
                    cached = ICON_CACHE / f"smp-{tid}.png"
                    if cached.is_file() and time.time() - cached.stat().st_mtime < 86400:
                        png = cached.read_bytes()
                    else:
                        try:
                            host = (get_settings().get("ps5_ftp") or "").partition(":")[0]
                            with urllib.request.urlopen(f"http://{host}:{RECV_PORT}/api/smp-icon?title_id={tid}", timeout=10) as r:
                                data = r.read()
                            if data[:4] == b"\x89PNG":
                                png = data
                                ICON_CACHE.mkdir(parents=True, exist_ok=True)
                                cached.write_bytes(png)
                        except Exception:
                            pass
                if not png:
                    return self.send(404, b'{"error":"no icon"}')
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "max-age=3600")
                self.send_header("Content-Length", str(len(png)))
                self.end_headers()
                self.wfile.write(png)
                return
            if self.path == "/api/pkg/activity":
                return self.send(200, json.dumps({"downloads": dl_snapshot(),
                                                  "history": read_json(PKG_HISTORY, []) or []}).encode())
            if self.path == "/api/receiver":
                return self.send(200, json.dumps(receiver_status()).encode())
            if self.path.startswith("/api/pkg/icon?"):
                from urllib.parse import parse_qs, urlparse
                data = pkg_icon((parse_qs(urlparse(self.path).query).get("id") or [""])[0])
                if not data:
                    return self.send(404, b'{"error":"no icon"}')
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                return self.wfile.write(data)
            if self.path == "/api/ps5/games":
                try:
                    return self.send(200, json.dumps(ps5_games(), ensure_ascii=False).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path.startswith("/api/ftp/du?") or self.path == "/api/ps5/drives":
                from urllib.parse import parse_qs, urlparse
                try:
                    if self.path == "/api/ps5/drives":
                        body = ps5_drives()
                    else:
                        body = ps5_ftp_du((parse_qs(urlparse(self.path).query).get("path") or ["/"])[0])
                    return self.send(200, json.dumps(body).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path.startswith("/api/ftp/apr?"):
                from urllib.parse import parse_qs, urlparse
                path = (parse_qs(urlparse(self.path).query).get("path") or ["/"])[0]
                try:
                    return self.send(200, json.dumps(ps5_ftp_apr(path)).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path.startswith("/api/ftp/zip?"):
                from urllib.parse import parse_qs, urlparse, quote
                try:
                    path = ps5_ftp_path((parse_qs(urlparse(self.path).query).get("path") or [""])[0])
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
                name = (path.rsplit("/", 1)[-1] or "ps5") + ".zip"
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True

                class Sink:  # zipfile wants tell() on a stream it can't seek
                    def __init__(self, w):
                        self.w, self.pos = w, 0

                    def write(self, b):
                        self.w.write(b)
                        self.pos += len(b)
                        return len(b)

                    def tell(self):
                        return self.pos

                    def flush(self):
                        self.w.flush()
                try:
                    ps5_ftp_zip(path, Sink(self.wfile))
                except Exception:
                    pass  # the download ends short; the browser reports it
                return
            if self.path.startswith("/api/ftp/get?"):
                import ftplib
                from urllib.parse import parse_qs, urlparse, quote
                try:
                    path = ps5_ftp_path((parse_qs(urlparse(self.path).query).get("path") or [""])[0])
                    f = ps5_ftp_connect()
                    size = f.size(path)
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
                name = path.rsplit("/", 1)[-1]
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
                if size is not None:
                    self.send_header("Content-Length", str(size))
                self.end_headers()
                try:
                    f.retrbinary(f"RETR {path}", self.wfile.write, blocksize=1 << 20)
                    f.quit()
                except (*ftplib.all_errors, OSError):
                    f.close()
                return
            if self.path == "/api/ps5":
                host = get_settings()["ps5_ftp"].partition(":")[0]
                return self.send(200, json.dumps({"status": ps5_status(host) if host else "unset"}).encode())
            if self.path.startswith("/api/ng-reports"):
                err = None
                if NG_REPORTS_ON and "refresh=1" in self.path and time.time() - refreshed[0] > 60:
                    refreshed[0] = time.time()
                    try:
                        ng_reports_refresh()
                    except Exception as e:
                        err = str(e)
                saved = (read_json(NG_REPORTS, {}) or {}) if NG_REPORTS_ON else {}
                return self.send(200, json.dumps({"repo": NG_REPORT_REPO, "web": NG_REPORT_WEB, "updated": saved.get("updated"),
                                                  "games": saved.get("games") or {}, "refresh_error": err},
                                                 ensure_ascii=False).encode())
            if self.path == "/api/dashboard":
                # Served from the last result at once; a stale one is rebuilt in the
                # background, so a slow disk (a game packing) never stalls the page.
                if not cache["body"]:
                    refresh_dashboard()
                elif time.time() - cache["at"] > 4:
                    __import__("threading").Thread(target=refresh_dashboard, daemon=True).start()
                return self.send(200, cache["body"])
            self.send(404, b'{"error":"not found"}')

        def do_HEAD(self):
            if self.path.startswith("/pkgfile/"):
                return self.send_pkgfile(head=True)
            self.send_response(405)
            self.end_headers()

        def send_pkgfile(self, head: bool = False):
            """A library .pkg for pkg-receiver on the PS5 to download (Range supported)."""
            from urllib.parse import unquote
            return serve_pkg(self, unquote(self.path[len("/pkgfile/"):].split("?")[0]), head)

        def do_POST(self):
            if self.path.startswith("/api/ftp/put?"):
                from urllib.parse import parse_qs, urlparse
                path = (parse_qs(urlparse(self.path).query).get("path") or [""])[0]
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    return self.send(200, json.dumps(ps5_ftp_put(path, self.rfile, n)).encode())
                except Exception as err:
                    self.close_connection = True  # the body may be unread
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if self.path != "/api/action":
                return self.send(404, b'{"error":"not found"}')
            try:
                n = int(self.headers.get("Content-Length") or 0)
                # 1 MB: Install all sends the id of every listed package
                req = json.loads(self.rfile.read(min(n, 1 << 20)) or b"{}")
            except ValueError:
                return self.send(400, b'{"error":"bad request"}')
            if req.get("action") == "pair":
                try:
                    if req.get("ps5_ftp"):  # the address typed on the page, saved or not
                        save_settings({k: req[k] for k in ("ps5_ftp", "ps5_dest") if req.get(k)})
                    res = ps5_pair(str(req.get("pin") or ""), str(req.get("account_id") or ""))
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
                cache["at"] = 0
                return self.send(200, json.dumps(res).encode())
            if req.get("action") == "ps5_verify":
                try:
                    return self.send(200, json.dumps(ps5_verify_start(str(req.get("path") or ""))).encode())
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "ps5_fix":
                try:
                    return self.send(200, json.dumps(ps5_fix(str(req.get("path") or ""), str(req.get("code") or ""))).encode())
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "notify_test":
                url = str(req.get("url") or get_settings().get("notify_url") or "")
                if not url:
                    return self.send(400, json.dumps({"error": "enter a notification address first"}).encode())
                notify("ps5-lz4 test", "Notifications from ps5-lz4 arrive here.", True, url)
                return self.send(200, b'{"sent":true}')
            if req.get("action") in ("receiver_start", "receiver_auto"):
                try:
                    if req["action"] == "receiver_auto":
                        ENGINE_DIR.mkdir(parents=True, exist_ok=True)
                        write_json(RECV_AUTO, {"on": bool(req.get("on"))})
                        return self.send(200, json.dumps({"auto": receiver_auto_on()}).encode())
                    return self.send(200, json.dumps(receiver_start()).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "receiver_install":
                try:
                    return self.send(200, json.dumps(receiver_install()).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "forge_ps5_install":
                try:
                    return self.send(200, json.dumps(forge_ps5_install()).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "pkg_install":
                try:
                    res = pkg_install(str(req.get("game") or ""), str(req.get("via") or "url"),
                                      self.headers.get("Host") or "")
                    return self.send(200, json.dumps(res).encode())
                except (ValueError, SystemExit) as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "pkg_install_all":
                ids = req.get("ids")
                try:
                    res = pkg_install_all([str(i) for i in ids] if isinstance(ids, list) else None,
                                          self.headers.get("Host") or "", bool(req.get("dry")))
                    return self.send(200, json.dumps(res).encode())
                except (ValueError, SystemExit) as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "drive_size":
                try:
                    path = str(req.get("path") or "")
                    if not DRIVE_ROOT.match(path):
                        raise ValueError("not a PS5 drive")
                    info = read_json(DRIVES_PATH, {}) or {}
                    if str(req.get("size") or "").strip():
                        info.setdefault(path, {})["capacity"] = parse_size(req["size"])
                    else:
                        info.setdefault(path, {}).pop("capacity", None)
                    write_json(DRIVES_PATH, info)
                    return self.send(200, json.dumps(info[path]).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "ftp_mkdir":
                try:
                    path = ps5_ftp_path(str(req.get("path") or ""))
                    if not FTP_WRITE_ROOTS.match(path):
                        raise ValueError("new folders go inside /data, /mnt/usbN or /mnt/extN")
                    f = ps5_ftp_connect()
                    try:
                        ps5_ftp_mkdirs(f, path)
                    finally:
                        f.quit()
                    return self.send(200, json.dumps({"made": path}).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") in ("saves_backup", "saves_restore", "saves_delete"):
                try:
                    if req["action"] == "saves_backup":
                        return self.send(200, json.dumps(saves_backup_start(str(req.get("tid") or ""))).encode())
                    if req["action"] == "saves_restore":
                        return self.send(200, json.dumps(saves_restore(str(req.get("backup") or ""), str(req.get("key") or ""))).encode())
                    d = saves_backup_dir(str(req.get("backup") or ""))
                    shutil.rmtree(d)
                    return self.send(200, json.dumps({"deleted": d.name}).encode())
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if str(req.get("action") or "").startswith("smp_"):
                a, tid = req["action"], str(req.get("tid") or "").upper()
                try:
                    if a == "smp_scan":
                        res = smp("/api/v1/scan", {"reset_attempts": False})
                    elif a == "smp_cancel":
                        res = smp("/api/v1/games/storage/cancel", {"job_id": int(req.get("job_id") or 0)})
                    elif a in ("smp_log", "smp_klog"):
                        res = smp("/api/v1/debug-log" if a == "smp_log" else "/api/v1/kernel-log", {})
                    elif not re.fullmatch(r"(CUSA|PPSA|LAPY|FAKE)\d{5}", tid):
                        raise ValueError("bad Title ID")
                    elif a == "smp_move":
                        dest = str(req.get("dest") or "")
                        if not dest.startswith("/") or ".." in dest.split("/"):
                            raise ValueError("pick a destination folder")
                        res = smp("/api/v1/games/move", {"title_id": tid, "destination_dir": dest})
                    elif a == "smp_unmount":
                        res = smp("/api/v1/games/unmount", {"title_id": tid})
                    elif a == "smp_delete":
                        # Off the home screen, unmounted, then its files deleted on the PS5.
                        path = str(req.get("path") or "")
                        if not path:
                            raise ValueError("no path for this game")
                        res = {}
                        for step, route in (("unmount", "/api/v1/games/unmount"), ("uninstall", "/api/v1/games/uninstall")):
                            try:
                                res[step] = smp(route, {"title_id": tid})
                            except ValueError as err:
                                res[step] = {"error": str(err)}
                        try:
                            res["deleted"] = ps5_ftp_delete(path)
                        except Exception as err:
                            raise ValueError(f"taken off the home screen, but its files were not deleted: {err}")
                    elif a in ("smp_uninstall", "smp_hide"):
                        res = smp("/api/v1/games/uninstall", {"title_id": tid})
                        if a == "smp_hide":
                            res["hidden"] = smp_hide(str(req.get("path") or ""))
                    else:
                        raise ValueError("unknown action")
                    return self.send(200, json.dumps(res).encode())
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "ps5_uninstall":
                try:
                    return self.send(200, json.dumps({"result": ps5_uninstall(str(req.get("tid") or ""))}).encode())
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "ftp_delete":
                try:
                    return self.send(200, json.dumps(ps5_ftp_delete(str(req.get("path") or ""))).encode())
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "ps5_rest":
                try:
                    return self.send(200, json.dumps(ps5_rest()).encode())
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
            if req.get("action") == "rest_auto":
                return self.send(200, json.dumps(rest_set(on=bool(req.get("on")))).encode())
            if req.get("action") == "wake":
                cfg = get_settings()
                host = cfg["ps5_ftp"].partition(":")[0]
                if not host or not cfg["ps5_wake_key"]:
                    return self.send(400, json.dumps({"error": "PS5 address or Remote Play key missing"}).encode())
                before = ps5_status(host)
                ps5_wake(host, cfg["ps5_wake_key"])
                return self.send(200, json.dumps({"sent": True, "before": before}).encode())
            if req.get("action") == "github_token":
                try:
                    res = set_github_token(str(req.get("token") or ""))
                except (ValueError, OSError) as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
                cache["at"] = 0
                return self.send(200, json.dumps(res).encode())
            if req.get("action") == "ng_report":
                try:
                    res = ng_report_submit(str(req.get("game") or ""), req.get("fields") or {}, bool(req.get("dry")))
                except (ValueError, OSError) as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
                return self.send(200, json.dumps(res).encode())
            if req.get("action") == "settings":
                if req.get("ps5_wake_key") == "set":
                    req.pop("ps5_wake_key")  # unchanged (the page only sees that one is stored)
                try:
                    s = save_settings(req)
                except ValueError as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
                cache["at"] = 0
                return self.send(200, json.dumps({**s, "ps5_wake_key": "set" if s["ps5_wake_key"] else ""}).encode())
            if req.get("action") == "push_stop":
                st = transfer_running()
                if not st:
                    return self.send(409, b'{"error":"no transfer is running"}')
                try:
                    os.kill(int(st["pid"]), signal.SIGTERM)
                except (OSError, ValueError, KeyError) as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
                return self.send(200, b'{"stopping":true}')
            if req.get("action") == "transfer_delete":
                # Stop it if it runs, delete what reached the PS5, forget it.
                key = str(req.get("game") or "")
                rec = TRANSFERS / f"{key}.json"
                if not key or "/" in key or key.startswith(".") or not rec.is_file():
                    return self.send(400, b'{"error":"no such transfer"}')
                st = read_json(rec, {}) or {}
                path = "/" + str(st.get("dest") or "").partition("/")[2]
                try:
                    res = ps5_ftp_delete(path)
                except ValueError as err:
                    if "is not on the PS5" not in str(err):
                        return self.send(400, json.dumps({"error": str(err)}).encode())
                    res = {"deleted": None}
                except Exception as err:
                    return self.send(400, json.dumps({"error": str(err)}).encode())
                rec.unlink(missing_ok=True)
                transfer_queue_set([g for g in transfer_queue() if g not in (key, st.get("request"))])
                cache["at"] = 0
                return self.send(200, json.dumps(res).encode())
            if req.get("action") == "dup_use":
                # "Use this one": this copy is listed and packed, the others with
                # its Title ID are left out (nothing is deleted).
                import unicodedata
                nfc = lambda x: unicodedata.normalize("NFC", x)
                tid, rel = str(req.get("tid") or "").upper(), nfc(str(req.get("rel") or ""))
                copies = [e for e in scan_library() if (e.title_id or "").upper() == tid]
                hit = next((e for e in copies if nfc(e.rel) == rel), None)
                if not re.fullmatch(r"[A-Z]{4}\d{5}", tid) or hit is None:
                    return self.send(400, json.dumps({"error": f"that copy is not in the library ({len(copies)} "
                                                      f"copies of {tid} found)"}).encode())
                running, _ = job_running()
                current = (read_json(QUEUE_PATH, {}) or {}).get("current") if running else None
                busy = next((e.rel for e in copies if e.id == current and e.rel != hit.rel), None)
                prefs = read_json(PREFERRED, {}) or {}
                prefs[tid] = hit.rel
                try:
                    write_json(PREFERRED, prefs)
                except OSError as err:
                    return self.send(500, json.dumps({"error": f"could not save the choice: {err}"}).encode())
                cache["at"] = 0
                return self.send(200, json.dumps({"used": hit.rel, "busy": busy}).encode())
            if req.get("action") == "queue_remove":
                # A game waiting in the packing queue (not the one being packed),
                # or a Compress request not picked up yet.
                game, name = str(req.get("game") or ""), str(req.get("file") or "")
                if name:
                    f = REQUESTS / name
                    if not re.fullmatch(r"[\w.-]+\.req\.json", name) or f.parent != REQUESTS:
                        return self.send(400, b'{"error":"bad request file"}')
                    f.unlink(missing_ok=True)
                elif game:
                    q = read_json(QUEUE_PATH, {}) or {}
                    if q.get("current") == game:
                        return self.send(409, b'{"error":"that game is being packed now: use Stop"}')
                    q["remaining"] = [x for x in q.get("remaining", []) if x != game]
                    write_json(QUEUE_PATH, q)
                    sa = read_json(SEND_AFTER, {}) or {}
                    if game in sa:
                        sa.pop(game)
                        write_json(SEND_AFTER, sa)
                cache["at"] = 0
                return self.send(200, b'{"removed":true}')
            if req.get("action") in ("push_queue_remove", "push_queue_up"):
                game, q = str(req.get("game") or ""), transfer_queue()
                if game in q:
                    i = q.index(game)
                    q.pop(i)
                    if req["action"] == "push_queue_up":
                        q.insert(max(0, i - 1), game)
                    transfer_queue_set(q)
                cache["at"] = 0
                return self.send(200, json.dumps({"queue": q}).encode())
            if req.get("action") == "push_queue_start":
                q = transfer_queue()
                if not q:
                    return self.send(409, b'{"error":"the transfer queue is empty"}')
                if transfer_running():
                    return self.send(409, b'{"error":"a transfer is already running"}')
                req = {"action": "push", "game": q[0]}
            if req.get("action") == "push":
                game = str(req.get("game") or "")
                if not game or game.startswith("-") or ("/" in game and not game.startswith("pkg:")):
                    return self.send(400, b'{"error":"no game"}')
                if game.startswith("pkg:"):
                    try:
                        pkg_path(game[4:])
                    except SystemExit as err:
                        return self.send(400, json.dumps({"error": str(err)}).encode())
                if not get_settings()["ps5_ftp"]:
                    return self.send(400, json.dumps({"error": "PS5 FTP address missing"}).encode())
                res = start_push(game, bool(req.get("force")))
                cache["at"] = 0
                return self.send(200, json.dumps(res).encode())
            if req.get("action") == "image_stop":
                IMAGES.mkdir(parents=True, exist_ok=True)
                IMAGE_STOP.touch()
                cache["at"] = 0
                return self.send(200, b'{"stopping":true}')
            if req.get("action") == "send_after_remove":
                lst = read_json(SEND_AFTER, {}) or {}
                lst = lst if isinstance(lst, dict) else {}
                lst.pop(str(req.get("game") or ""), None)
                write_json(SEND_AFTER, lst)
                cache["at"] = 0
                return self.send(200, b'{"send_after":false}')
            if req.get("action") == "send_after":
                game = str(req.get("game") or "")
                if not game or "/" in game:
                    return self.send(400, b'{"error":"no game"}')
                lst = read_json(SEND_AFTER, {}) or {}
                lst = lst if isinstance(lst, dict) else {}
                lst[game] = {"at": time.time(), "image": True} if req.get("image") else lst.get(game, time.time())
                write_json(SEND_AFTER, lst)
                cache["at"] = 0
                return self.send(200, b'{"send_after":true}')
            if req.get("action") not in UI_ACTIONS:
                return self.send(400, b'{"error":"unknown action"}')
            req = queued_request(req)
            req["asked"] = now()
            name = f"{int(time.time() * 1000)}-{os.getpid()}"
            write_json(REQUESTS / f"{name}.req.json", req)
            cache["at"] = 0
            self.send(200, json.dumps({"queued": name}).encode())

    refreshed = [0.0]
    if NG_REPORTS_ON:
        __import__("threading").Thread(target=ng_reports_refresher, daemon=True).start()
    __import__("threading").Thread(target=send_after_watcher, daemon=True).start()
    __import__("threading").Thread(target=transfer_queue_watcher, daemon=True).start()
    __import__("threading").Thread(target=rest_watcher, daemon=True).start()
    __import__("threading").Thread(target=receiver_autostarter, daemon=True).start()
    # PS4 packages now go to the root of the USB drive (was /data/pkg).
    stored = read_json(SETTINGS_PATH, {}) or {}
    if stored.get("ps4_dest") == "/data/pkg":
        stored["ps4_dest"] = "/mnt/usb0"
        write_settings(stored)
        print(f"[{now()}] PS4 package folder moved from /data/pkg to /mnt/usb0", flush=True)
    __import__("threading").Thread(target=notifier, daemon=True).start()
    if CATALOG_PORT > 0:
        __import__("threading").Thread(target=catalog_server, daemon=True).start()
        __import__("threading").Thread(target=catalog_announcer, daemon=True).start()
    if FFPFSC_SHEET:
        __import__("threading").Thread(target=ffpfsc_refresher, daemon=True).start()
    srv = http.server.ThreadingHTTPServer((os.environ.get("PS5LZ4_UI_BIND", "127.0.0.1"), args.port), H)
    print(f"[{now()}] ui on port {args.port}", flush=True)
    srv.serve_forever()
    return 0


STORE_HTML = (Path(__file__).with_name("store.html").read_text()
              if Path(__file__).with_name("store.html").is_file() else "<p>store.html missing</p>")
UI_HTML = (Path(__file__).with_name("ui.html").read_text()
           if Path(__file__).with_name("ui.html").is_file() else "<p>ui.html missing</p>")


def main() -> int:
    p = argparse.ArgumentParser(prog="ps5lz4", description="Zstd packing of PS5 games for ampr-emu-ng (PS5 Dump Forge), on the NAS.")
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    def job_opts(sp):
        sp.add_argument("--codec", choices=("zstd",), default="zstd", help="only Zstd is packed")
        sp.add_argument("--runtime", choices=("ng",), default="ng",
                        help="ng installs ampr-emu-ng; required for zstd")
        sp.add_argument("--level", type=int, default=int(os.environ.get("PS5LZ4_ZSTD_LEVEL", "5")),
                        help="zstd level 1-22 (default 5)")
        sp.add_argument("--no-restore-test", action="store_true",
                        help="skip the full unpack-and-compare step (not recommended)")
        sp.add_argument("--require-vhash", action="store_true",
                        help="skip .ffpfsc images without a .vhash sidecar")
        sp.add_argument("--force-image", action="store_true",
                        help="pack an image even when a folder of the same game exists")
        sp.add_argument("--no-profile", action="store_true",
                        help="ignored: there are no TOML profiles any more")

    sp = sub.add_parser("doctor", help="check the installation")
    sp.set_defaults(func=cmd_doctor)
    sp = sub.add_parser("scan", help="list the library and each game's state")
    sp.add_argument("--check", action="store_true", help="also check AMPR compatibility (reads eboot)")
    sp.set_defaults(func=cmd_scan)
    sp = sub.add_parser("run", help="pack games now, in the foreground")
    sp.add_argument("targets", nargs="*", help="# from scan, folder/image name, or title ID")
    sp.add_argument("--all", action="store_true", help="every game not done yet")
    sp.add_argument("--from-queue", action="store_true", help=argparse.SUPPRESS)
    job_opts(sp)
    sp.set_defaults(func=cmd_run)
    sp = sub.add_parser("start", help="queue games and run them in the background (nohup)")
    sp.add_argument("targets", nargs="*")
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--resume", action="store_true", help="continue the unfinished queue")
    job_opts(sp)
    sp.set_defaults(func=cmd_start)
    sp = sub.add_parser("lz4", help="is each game LZ4? --fix packs every game that can be")
    sp.add_argument("--fix", action="store_true", help="queue every game that can become LZ4")
    sp.add_argument("--full", action="store_true", help="scan every source again, ignoring saved results")
    sp.add_argument("--include-compressed", action="store_true",
                    help="with --fix, also pack .ffpfsc images (already compressed; usually no space saved)")
    job_opts(sp)
    sp.set_defaults(func=cmd_lz4)
    sp = sub.add_parser("status", help="show the running job and the work area")
    sp.set_defaults(func=cmd_status)
    sp = sub.add_parser("stop", help="stop the running job (resumable)")
    sp.set_defaults(func=cmd_stop)
    sp = sub.add_parser("report", help="sizes and savings of finished packed games")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_report)
    sp = sub.add_parser("verify", help="re-verify a finished output folder")
    sp.add_argument("output", help="output folder name, e.g. MyGame-lz4")
    sp.add_argument("source", nargs="?", help="optional original folder to compare against")
    sp.set_defaults(func=cmd_verify)
    sp = sub.add_parser("apr", help="check every LZ4 game (APR-EMU, on-disk files); --fix repairs")
    sp.add_argument("--fix", action="store_true")
    sp.add_argument("--full", action="store_true", help="check every game again, not only changed ones")
    sp.set_defaults(func=cmd_apr)
    sp = sub.add_parser("community", help="community reports per game; record and share your PS5 result")
    sp.add_argument("game", nargs="?", help="# from scan, name or title ID")
    sp.add_argument("result", nargs="?", help="works | issues | nostart | crash")
    sp.set_defaults(func=cmd_community)
    sp = sub.add_parser("push", help="copy a finished LZ4 game to the PS5 over FTP (runs in ps5-lz4-ui)")
    sp.add_argument("game", help="LZ4 folder name, library name or title ID")
    sp.add_argument("--force", action="store_true", help="copy even if the PS5 has another copy of the title")
    sp.set_defaults(func=cmd_push)
    sp = sub.add_parser("pair", help="pair with the PS5 for Remote Play wake-up, like Chiaki (PIN from the PS5)")
    sp.add_argument("pin", help="8-digit PIN: PS5 Settings > System > Remote Play > Link Device")
    sp.add_argument("account_id", help="PSN account ID: base64 like Chiaki, decimal, or 0x-hex")
    sp.set_defaults(func=cmd_pair)
    sp = sub.add_parser("wake", help="wake the PS5 from rest mode (Remote Play key, like Chiaki)")
    sp.set_defaults(func=cmd_wake)
    sp = sub.add_parser("dashboard", help="everything the web page shows, as JSON")
    sp.set_defaults(func=cmd_dashboard)
    sp = sub.add_parser("agent", help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_agent)
    sp = sub.add_parser("ui", help="serve the web page (own container, see install.sh)")
    sp.add_argument("--port", type=int, default=int(os.environ.get("PS5LZ4_UI_PORT", "5921")))
    sp.set_defaults(func=cmd_ui)
    sp = sub.add_parser("make-exfat", help="make a checked .exfat image of a finished LZ4 copy")
    sp.add_argument("game")
    sp.set_defaults(func=cmd_make_exfat)
    sp = sub.add_parser("verify-lz4", help="verify an LZ4 copy (every block decoded and CRC-checked) for the page")
    sp.add_argument("game")
    sp.set_defaults(func=cmd_verify_lz4)
    sp = sub.add_parser("extract", help="extract a RAR archive in the library into a checked .exfat image")
    sp.add_argument("archive", help="the first part, relative to the library")
    sp.set_defaults(func=cmd_extract)
    sp = sub.add_parser("delete-rars", help="delete an extracted RAR archive (needs DELETE_ORIGINALS=yes)")
    sp.add_argument("archive")
    sp.set_defaults(func=cmd_delete_rars)
    sp = sub.add_parser("remove-exfat", help="delete the .exfat image of an LZ4 copy")
    sp.add_argument("game")
    sp.set_defaults(func=cmd_remove_exfat)
    sp = sub.add_parser("delete-original", help="delete an original game from the library (needs DELETE_ORIGINALS=yes)")
    sp.add_argument("game")
    sp.set_defaults(func=cmd_delete_original)
    sp = sub.add_parser("remove", help="delete a finished LZ4 copy from the output folder (not the original)")
    sp.add_argument("game")
    sp.set_defaults(func=cmd_remove)
    sp = sub.add_parser("clean", help="delete the work folder of a failed game")
    sp.add_argument("ids", nargs="+")
    sp.set_defaults(func=cmd_clean)
    args = p.parse_args()
    # `ps5lz4 status | head` should just stop, not print a traceback.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
