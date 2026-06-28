#!/usr/bin/env python3
"""Pretty-print generated job descriptions from data/.

Flow (menus shown only when the matching flag is omitted and on a TTY):
  1. Pick a version subdir under data/job_description/  (default: the latest one containing job files).
  2. Pick a dated jobs_*.jsonl file   (default: the latest file).
  3. Pretty-print every job record in that file.

Run from the project root (or anywhere):

    python app/show_jobs.py
    python app/show_jobs.py --version v1 --file jobs_20260627_205222.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = PROJECT_ROOT / "data" / "job_description"


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _jobs_files(version_dir: Path) -> list[Path]:
    """Dated jobs files, latest first (filenames sort chronologically)."""
    return sorted(version_dir.glob("jobs_*.jsonl"), reverse=True)


def _version_dirs() -> list[Path]:
    return sorted(p for p in JOBS_DIR.iterdir() if p.is_dir())


def _default_version(versions: list[Path]) -> Path | None:
    """The version dir whose newest jobs file is most recent; else the first dir."""
    best, best_mtime = None, -1.0
    for v in versions:
        files = _jobs_files(v)
        if files:
            m = max(f.stat().st_mtime for f in files)
            if m > best_mtime:
                best, best_mtime = v, m
    return best or (versions[0] if versions else None)


def _pick(title: str, labels: list[str], default_index: int) -> int:
    """Numbered menu returning the chosen index. Empty input picks the default."""
    print(f"\n{title}")
    for i, label in enumerate(labels, 1):
        print(f"  {i}. {label}{'  (default)' if i - 1 == default_index else ''}")
    while True:
        raw = input(f"Select 1-{len(labels)} [default: {default_index + 1}]: ").strip()
        if not raw:
            return default_index
        if raw.isdigit() and 1 <= int(raw) <= len(labels):
            return int(raw) - 1
        print("  Invalid choice, try again.")


def _fmt_job(idx: int, rec: dict) -> str:
    company = rec.get("company", {})
    req = rec.get("requirements", {})
    meta = rec.get("metadata", {})

    name = company.get("name", "?")
    header_bits = [name, company.get("industry"), company.get("size"), company.get("location")]
    header = "  ·  ".join(b for b in header_bits if b)

    niche = "yes" if meta.get("is_niche_role") else "no"
    style = meta.get("writing_style") or "—"
    seniority = f"{req.get('experience_level', '?')} ({req.get('experience_years', '?')} yrs)"
    trace = (meta.get("trace_id") or "")[:8]
    generated = meta.get("generated_at") or ""

    details = rec.get("description", {})
    overview = details.get("overview", "")
    responsibilities = details.get("responsibilities", [])

    lines = [
        "─" * 78,
        f"[{idx}] {header}",
        f"    Seniority : {seniority}        Niche: {niche}        Style: {style}",
    ]
    if rec.get("summary"):
        lines.append(f"    Summary   : {rec['summary']}")
    if overview:
        lines.append(f"    Overview  : {overview}")
    if responsibilities:
        lines.append("    Responsibilities:")
        lines.extend(f"      • {r}" for r in responsibilities)
    lines.append(f"    Education : {req.get('education', '?')}")
    required = req.get("required_skills", [])
    preferred = req.get("preferred_skills", [])
    lines.append("    Required  :" if required else "    Required  : —")
    lines.extend(f"      • {s}" for s in required)
    lines.append("    Preferred :" if preferred else "    Preferred : —")
    lines.extend(f"      • {s}" for s in preferred)
    lines.append(f"    trace_id  : {trace}…  ·  generated {generated}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default=None,
        help="version subdir under data/job_description/ (menu if omitted)",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="jobs_*.jsonl filename within the version dir (menu if omitted)",
    )
    args = parser.parse_args()

    if not JOBS_DIR.is_dir():
        sys.exit(f"No job-description data directory found at {JOBS_DIR}")

    versions = _version_dirs()
    if not versions:
        sys.exit(f"No version subdirectories under {JOBS_DIR}")

    # --- pick version dir ---
    if args.version:
        version_dir = JOBS_DIR / args.version
        if not version_dir.is_dir():
            sys.exit(f"Version dir not found: {version_dir}")
    else:
        default_dir = _default_version(versions)
        default_idx = versions.index(default_dir) if default_dir in versions else 0
        if _interactive() and len(versions) > 1:
            labels = [f"{v.name}  ({len(_jobs_files(v))} files)" for v in versions]
            version_dir = versions[_pick("Version:", labels, default_idx)]
        else:
            version_dir = versions[default_idx]

    # --- pick file ---
    files = _jobs_files(version_dir)
    if not files:
        sys.exit(f"No jobs_*.jsonl files in {version_dir}")
    if args.file:
        chosen = version_dir / args.file
        if not chosen.is_file():
            sys.exit(f"File not found: {chosen}")
    elif _interactive() and len(files) > 1:
        chosen = files[_pick("Jobs file:", [f.name for f in files], 0)]
    else:
        chosen = files[0]  # latest

    # --- print ---
    records = [json.loads(line) for line in chosen.read_text().splitlines() if line.strip()]
    print(f"\n{chosen.relative_to(PROJECT_ROOT)}  —  {len(records)} job(s)")
    for i, rec in enumerate(records, 1):
        print(_fmt_job(i, rec))
    print("─" * 78)


if __name__ == "__main__":
    main()
