#!/usr/bin/env python3
"""Builds compat/compat.json from the "Game report" issues (label: compat).

Usage: compat_aggregate.py <issues.json> <out.json>
issues.json is `gh issue list --label compat --state all --limit 5000
--json number,title,body,createdAt,updatedAt,author,labels,state`.

One vote per GitHub user per game: a user's newest report replaces their
older ones. Issues labelled invalid, duplicate or spam are ignored.
"""
import json
import re
import sys
from datetime import datetime, timezone

STATUS = {
    "works": "works",
    "works with issues": "issues",
    "won't start (black screen or crash on launch)": "noStart",
    "crashes in game": "crash",
}
FIELDS = {
    "title id": "titleId",
    "game": "game",
    "how does it run?": "status",
    "game version": "gameVersion",
    "lz4 level": "level",
    "packed from": "source",
    "firmware": "firmware",
    "lz4 compression version": "appVersion",
    "notes": "notes",
}
IGNORED_LABELS = {"invalid", "duplicate", "spam"}
TITLE_ID = re.compile(r"^[A-Z]{4}\d{5}$")


def parse_body(body):
    """Issue forms render as '### Label' followed by the answer."""
    out = {}
    parts = re.split(r"(?m)^### +(.+?)\s*$", body or "")
    for i in range(1, len(parts) - 1, 2):
        key = FIELDS.get(parts[i].strip().lower())
        value = parts[i + 1].strip()
        if not key or value in ("", "_No response_", "None"):
            continue
        out[key] = value
    return out


def clean(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def main(src, dst):
    issues = json.load(open(src, encoding="utf-8"))
    latest = {}
    for issue in issues:
        labels = {label.get("name", "").lower() for label in issue.get("labels") or []}
        if labels & IGNORED_LABELS:
            continue
        fields = parse_body(issue.get("body"))
        title_id = clean(fields.get("titleId"), 16).upper()
        status = STATUS.get(clean(fields.get("status"), 80).lower())
        if not TITLE_ID.match(title_id) or not status:
            continue
        author = (issue.get("author") or {}).get("login") or f"#{issue.get('number')}"
        report = {
            "status": status,
            "game": clean(fields.get("game"), 80),
            "gameVersion": clean(fields.get("gameVersion"), 20),
            "level": clean(fields.get("level"), 4),
            "source": clean(fields.get("source"), 40),
            "firmware": clean(fields.get("firmware"), 12),
            "appVersion": clean(fields.get("appVersion"), 12),
            "date": issue.get("createdAt") or "",
            "issue": issue.get("number"),
        }
        key = (title_id, author.lower())
        if key not in latest or report["date"] >= latest[key][1]["date"]:
            latest[key] = (title_id, report)

    games = {}
    for title_id, report in latest.values():
        game = games.setdefault(title_id, {
            "name": "", "works": 0, "issues": 0, "noStart": 0, "crash": 0,
            "reports": 0, "lastReport": None,
        })
        game[report["status"]] += 1
        game["reports"] += 1
        if report["game"] and not game["name"]:
            game["name"] = report["game"]
        if not game["lastReport"] or report["date"] > game["lastReport"]["date"]:
            game["lastReport"] = report

    out = {
        "version": 1,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "games": dict(sorted(games.items())),
    }
    with open(dst, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=1, ensure_ascii=False)
        handle.write("\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
