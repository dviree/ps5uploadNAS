#!/usr/bin/env python3
"""Follow quer3q/ampr-emu-ng (main) and quer3q/ps5-dump-forge (releases), and
James St-Pierre's ampr-emu-ng branches (jamesst20/ampr-emu-ng).

  python3 tools/quer3q_update.py            # say what is new, change nothing
  python3 tools/quer3q_update.py --apply    # also move the pins in the repo

--apply moves ampr-emu-ng to the newest main commit (built as it is, no patch)
and Forge to its newest release
(after checking the release archives and the vendored runtime against
upstream's own SHA256SUMS). With --trail it adds Trail-Code's blast radius of
upstream's change. The report goes to --report (Markdown) for the pull request;
nothing is merged here. Exit 0 always unless something failed; the output
lines "changed=true|false" (anything new) and "pins=true|false" (a pin moved,
so the image must be rebuilt) say what happened.

James's branches are work in progress that quer3q merges by pull request, so
they are reported, not pinned: each new or moved branch with the commits that
are not in quer3q's main yet and, with --trail, its blast radius. --apply
records the heads seen in tools/james-branches.json.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "nas-lz4" / "Dockerfile"
FORGE_PY = ROOT / "nas-lz4" / "install-forge.py"
DOCS = [ROOT / "nas-lz4" / "README.md", ROOT / "THIRD_PARTY_NOTICES.md"]
NG_REPO = "https://github.com/quer3q/ampr-emu-ng"
FORGE_REPO = "https://github.com/quer3q/ps5-dump-forge"
JAMES_REPO = "https://github.com/jamesst20/ampr-emu-ng"
JAMES_STATE = ROOT / "tools" / "james-branches.json"


def run(argv, **kw):
    return subprocess.run(argv, check=True, capture_output=True, text=True, **kw).stdout


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "PS5-LZ4-NAS-quer3q-update"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def read_seen() -> dict:
    try:
        return json.loads(JAMES_STATE.read_text())
    except (OSError, ValueError):
        return {}


def current() -> dict:
    d, f = DOCKERFILE.read_text(), FORGE_PY.read_text()
    return {"ng": re.search(r"^ARG NG_COMMIT=([0-9a-f]{40})$", d, re.M).group(1),
            "forge": re.search(r"^VERSION = '([\d.]+)'$", f, re.M).group(1)}


def newest() -> dict:
    head = run(["git", "ls-remote", NG_REPO, "refs/heads/main"]).split()[0]
    tags = [line.rsplit("/", 1)[-1] for line in run(["git", "ls-remote", "--tags", "--refs", FORGE_REPO]).splitlines()]
    vers = sorted((t[1:] for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+", t)), key=lambda v: tuple(map(int, v.split("."))))
    return {"ng": head, "forge": vers[-1]}


def shallow(repo: str, ref: str, dest: Path, depth: int = 1) -> Path:
    run(["git", "init", "-q", str(dest)])
    run(["git", "-C", str(dest), "fetch", "-q", f"--depth={depth}", repo, ref])
    run(["git", "-C", str(dest), "checkout", "-q", "FETCH_HEAD"])
    return dest


def trail_in(src: Path, base: str) -> str:
    """Trail-Code's blast radius of the checked-out tree against base."""
    env = {**os.environ, "DO_NOT_TRACK": "1", "TRAIL_NO_LOOK_BACK": "1", "GRAFT_NO_GITIGNORE": "1"}
    subprocess.run(["trail", "build", "."], cwd=src, env=env, capture_output=True, text=True, timeout=1800)
    out = subprocess.run(["trail", "blast", "--base", base], cwd=src, env=env, capture_output=True, text=True, timeout=600)
    return (out.stdout or out.stderr).strip()[:6000]


def james_heads() -> dict:
    return {line.split()[1].removeprefix("refs/heads/"): line.split()[0]
            for line in run(["git", "ls-remote", "--heads", JAMES_REPO]).splitlines()}


def james_report(seen: dict, heads: dict, ng_main: str, tmp: Path, trail: bool) -> str:
    """The James branches that are new or moved since seen, against quer3q's main."""
    src = tmp / "james"
    run(["git", "clone", "-q", "--filter=blob:none", JAMES_REPO, str(src)])
    run(["git", "-C", str(src), "fetch", "-q", NG_REPO, f"+{ng_main}:refs/remotes/quer3q/main"])
    def merged(sha):
        return subprocess.run(["git", "-C", str(src), "merge-base", "--is-ancestor", sha, "quer3q/main"]).returncode == 0
    out = ["## James St-Pierre's ampr-emu-ng branches\n"]
    for name, sha in sorted(heads.items()):
        if seen.get(name) == sha or name == "main":
            continue
        if merged(sha):
            out.append(f"### `{name}` → `{sha[:7]}`: merged into quer3q's main (comes with the next main update)\n")
            continue
        log = run(["git", "-C", str(src), "log", "--format=%h %cs %s", f"quer3q/main..{sha}"]).strip()
        out.append(f"### `{name}` → `{sha[:7]}`: not in quer3q's main yet\n```\n{log[:3000]}\n```\n")
        if trail:
            run(["git", "-C", str(src), "checkout", "-q", sha])
            out.append(f"Trail-Code blast radius against quer3q's main:\n```\n{trail_in(src, 'quer3q/main')}\n```\n")
    for name in sorted(set(seen) - set(heads)):
        out.append(f"### `{name}`: deleted\n")
    return "\n".join(out)


def trail_blast(repo: str, old: str, new: str, tmp: Path) -> str:
    """Trail-Code's view of upstream's change: blast radius from old to new."""
    src = tmp / ("trail-" + repo.rsplit("/", 1)[-1])
    run(["git", "clone", "-q", "--filter=blob:none", repo, str(src)])
    run(["git", "-C", str(src), "checkout", "-q", new])
    env = {**os.environ, "DO_NOT_TRACK": "1", "TRAIL_NO_LOOK_BACK": "1", "GRAFT_NO_GITIGNORE": "1"}
    subprocess.run(["trail", "build", "."], cwd=src, env=env, capture_output=True, text=True, timeout=1800)
    out = subprocess.run(["trail", "blast", "--base", old], cwd=src, env=env, capture_output=True, text=True, timeout=600)
    log = run(["git", "-C", str(src), "log", "--oneline", "--no-merges", f"{old}..{new}"])
    return f"Commits:\n```\n{log.strip()[:4000]}\n```\nTrail-Code blast radius (`trail blast --base {old[:7]}`):\n```\n{(out.stdout or out.stderr).strip()[:6000]}\n```\n"


def apply_ng(old: str, new: str, tmp: Path) -> str:
    src = shallow(NG_REPO, new, tmp / "ng")
    version = (re.search(r'^version = "([^"]+)"', (src / "crates" / "ampr-sys" / "Cargo.toml").read_text(), re.M) or [None, "?"])[1]
    d = DOCKERFILE.read_text()
    d = d.replace(old, new).replace(f"ampr-emu-ng-{old[:7]}", f"ampr-emu-ng-{new[:7]}")
    d = re.sub(r"AMPR_GIT_REV=[0-9a-f]{7}\b", f"AMPR_GIT_REV={new[:7]}", d)
    d = re.sub(r"ampr-emu-ng main \(quer3q, v[\d.]+", f"ampr-emu-ng main (quer3q, v{version}", d)
    d = re.sub(r'"name":"ampr-emu-ng [0-9a-f]{7} \(v[^)]*\)', f'"name":"ampr-emu-ng {new[:7]} (v{version})', d)
    DOCKERFILE.write_text(d)
    for doc in DOCS:
        doc.write_text(doc.read_text().replace(old, new).replace(f"ampr-emu-ng-{old[:7]}", f"ampr-emu-ng-{new[:7]}"))
    return f"**ampr-emu-ng** `{old[:7]}` → `{new[:7]}` (v{version}); upstream's own commit, no patch.\n"


def apply_forge(old: str, new: str, tmp: Path) -> str:
    base = f"{FORGE_REPO}/releases/download/v{new}"
    sums = {line.split()[1].lstrip("*"): line.split()[0] for line in fetch(base + "/SHA256SUMS").decode().splitlines() if line.strip()}
    arch = {}
    for machine, name in (("x86_64", "x86-64"), ("aarch64", "arm64")):
        asset = f"ps5-dump-forge-{new}-linux-{name}.tar.gz"
        digest = hashlib.sha256(fetch(f"{base}/{asset}")).hexdigest()
        if sums.get(asset) != digest:
            raise SystemExit(f"{asset}: SHA-256 {digest} is not what upstream's SHA256SUMS lists")
        arch[machine] = (name, digest)
    src = shallow(FORGE_REPO, f"refs/tags/v{new}", tmp / "forge")
    ref = run(["git", "-C", str(src), "rev-parse", "HEAD"]).strip()
    vendor = src / "vendor" / "ampr-emu-ng"
    vsums = {line.split()[1]: line.split()[0] for line in (vendor / "SHA256SUMS").read_text().splitlines() if line.strip()}
    ng_sha = hashlib.sha256((vendor / "libSceAmpr.sprx").read_bytes()).hexdigest()
    if vsums.get("libSceAmpr.sprx") != ng_sha:
        raise SystemExit("Forge's vendored libSceAmpr.sprx does not match its SHA256SUMS")
    tars = sorted(vendor.glob("ampr-emu-ng-*-src.tar.gz"))
    if len(tars) != 1:
        raise SystemExit("expected one ampr-emu-ng source archive in Forge's vendor folder")
    src_sha = hashlib.sha256(tars[0].read_bytes()).hexdigest()
    f = FORGE_PY.read_text()
    f = re.sub(r"^VERSION = '[\d.]+'$", f"VERSION = '{new}'", f, flags=re.M)
    f = re.sub(r"^REF = '[0-9a-f]{40}'$", f"REF = '{ref}'", f, flags=re.M)
    for machine, (name, digest) in arch.items():
        f = re.sub(rf"'{machine}': \('{name}', '[0-9a-f]{{64}}'\)", f"'{machine}': ('{name}', '{digest}')", f)
    f = re.sub(r"^NG_SHA = '[0-9a-f]{64}'$", f"NG_SHA = '{ng_sha}'", f, flags=re.M)
    f = re.sub(r"^SOURCE_SHA = '[0-9a-f]{64}'$", f"SOURCE_SHA = '{src_sha}'", f, flags=re.M)
    f = re.sub(r"ampr-emu-ng-[\d.]+-src\.tar\.gz", tars[0].name, f)
    FORGE_PY.write_text(f)
    return f"**PS5 Dump Forge** v{old} → v{new} (`{ref[:7]}`); archives and the vendored runtime match upstream's SHA256SUMS.\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--trail", action="store_true", help="add Trail-Code's blast radius of upstream's change")
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()
    cur, new = current(), newest()
    report, changed = [], False
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for key, repo, label in (("ng", NG_REPO, "ampr-emu-ng main"), ("forge", FORGE_REPO, "Forge release")):
            if cur[key] == new[key]:
                print(f"{label}: up to date ({cur[key][:12]})")
                continue
            print(f"{label}: {cur[key][:12]} -> {new[key][:12]}")
            if not a.apply:
                continue
            try:
                report.append(apply_ng(cur[key], new[key], tmp) if key == "ng" else apply_forge(cur[key], new[key], tmp))
            except urllib.error.HTTPError as err:
                if key != "forge" or err.code != 404:
                    raise
                # Tagged, but the release files are not uploaded yet: nothing to verify against.
                print(f"{label}: v{new[key]} has no release files yet (404); staying on {cur[key]}")
                report.append(f"**Forge** v{new[key]} is tagged but has no release files yet; still on {cur[key]}.\n")
                continue
            changed = True
            if a.trail:
                old, nw = (cur[key], new[key]) if key == "ng" else (f"v{cur[key]}", f"v{new[key]}")
                report.append(trail_blast(repo, old, nw, tmp))
        pins = changed
        seen, heads = read_seen(), james_heads()
        if heads != seen:
            print(f"James's branches: {len(set(heads.items()) - set(seen.items()))} new or moved")
            report.append(james_report(seen, heads, new["ng"], tmp, a.trail))
            changed = True
            if a.apply:
                JAMES_STATE.write_text(json.dumps(heads, indent=1, sort_keys=True) + "\n")
        else:
            print("James's branches: nothing new")
    if a.report:
        a.report.write_text("\n".join(report) or "Nothing new from quer3q or James.\n")
    print(f"changed={'true' if changed else 'false'}")
    print(f"pins={'true' if pins else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
