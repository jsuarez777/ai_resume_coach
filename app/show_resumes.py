#!/usr/bin/env python3
"""Pretty-print generated resumes from data/.

Flow (menus shown only when the matching flag is omitted and on a TTY):
  1. Pick a version subdir under data/resume/  (default: the latest one containing resume files).
  2. Pick a dated resumes_*.jsonl file   (default: the latest file).
  3. Pretty-print every resume record in that file.

Run from the project root (or anywhere):

    python app/show_resumes.py
    python app/show_resumes.py --version v1 --file resumes_20260628_214819.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESUMES_DIR = PROJECT_ROOT / "data" / "resume"


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _resume_files(version_dir: Path) -> list[Path]:
    """Dated resume files, latest first (filenames sort chronologically)."""
    return sorted(version_dir.glob("resumes_*.jsonl"), reverse=True)


def _version_dirs() -> list[Path]:
    return sorted(p for p in RESUMES_DIR.iterdir() if p.is_dir())


def _default_version(versions: list[Path]) -> Path | None:
    """The version dir whose newest resume file is most recent; else the first dir."""
    best, best_mtime = None, -1.0
    for v in versions:
        files = _resume_files(v)
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


def _fmt_resume(idx: int, rec: dict) -> str:
    contact = rec.get("contact_info", {})
    meta = rec.get("metadata", {})

    header_bits = [contact.get("name", "?"), contact.get("location"), contact.get("email")]
    header = "  ·  ".join(b for b in header_bits if b)

    fit = meta.get("fit_level") or "—"
    style = meta.get("writing_style") or "—"
    src = (rec.get("source_job_trace_id") or "")[:8]
    trace = (meta.get("trace_id") or "")[:8]
    generated = meta.get("generated_at") or ""

    lines = [
        "─" * 78,
        f"[{idx}] {header}",
        f"    Fit: {fit:<10} Style: {style:<14} {'← job ' + src if src else ''}",
    ]

    links = [contact.get("linkedin"), contact.get("portfolio")]
    links = [str(line_value) for line_value in links if line_value]
    if links:
        lines.append(f"    Links     : {'  ·  '.join(links)}")

    education = rec.get("education", [])
    if education:
        lines.append("    Education :")
        for e in education:
            gpa = f"  · GPA {e['gpa']}" if e.get("gpa") is not None else ""
            lines.append(
                f"      • {e.get('degree', '?')} — {e.get('institution', '?')} "
                f"({e.get('graduation_date', '?')}){gpa}"
            )

    experience = rec.get("experience", [])
    if experience:
        lines.append("    Experience:")
        for x in experience:
            end = x.get("end_date") or "present"
            lines.append(
                f"      • {x.get('title', '?')} @ {x.get('company', '?')} "
                f"({x.get('start_date', '?')} – {end})"
            )
            lines.extend(f"          - {r}" for r in x.get("responsibilities", []))
            lines.extend(f"          ★ {a}" for a in x.get("achievements", []))

    skills = rec.get("skills", [])
    if skills:
        lines.append("    Skills    :")
        for s in skills:
            yrs = f", {s['years']}y" if s.get("years") is not None else ""
            lines.append(f"      • {s.get('name', '?')} ({s.get('proficiency_level', '?')}{yrs})")

    lines.append(f"    trace_id  : {trace}…  ·  generated {generated}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default=None,
        help="version subdir under data/resume/ (menu if omitted)",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="resumes_*.jsonl filename within the version dir (menu if omitted)",
    )
    args = parser.parse_args()

    if not RESUMES_DIR.is_dir():
        sys.exit(f"No resume data directory found at {RESUMES_DIR}")

    versions = _version_dirs()
    if not versions:
        sys.exit(f"No version subdirectories under {RESUMES_DIR}")

    # --- pick version dir ---
    if args.version:
        version_dir = RESUMES_DIR / args.version
        if not version_dir.is_dir():
            sys.exit(f"Version dir not found: {version_dir}")
    else:
        default_dir = _default_version(versions)
        default_idx = versions.index(default_dir) if default_dir in versions else 0
        if _interactive() and len(versions) > 1:
            labels = [f"{v.name}  ({len(_resume_files(v))} files)" for v in versions]
            version_dir = versions[_pick("Version:", labels, default_idx)]
        else:
            version_dir = versions[default_idx]

    # --- pick file ---
    files = _resume_files(version_dir)
    if not files:
        sys.exit(f"No resumes_*.jsonl files in {version_dir}")
    if args.file:
        chosen = version_dir / args.file
        if not chosen.is_file():
            sys.exit(f"File not found: {chosen}")
    elif _interactive() and len(files) > 1:
        chosen = files[_pick("Resumes file:", [f.name for f in files], 0)]
    else:
        chosen = files[0]  # latest

    # --- print ---
    records = [json.loads(line) for line in chosen.read_text().splitlines() if line.strip()]
    print(f"\n{chosen.relative_to(PROJECT_ROOT)}  —  {len(records)} resume(s)")
    for i, rec in enumerate(records, 1):
        print(_fmt_resume(i, rec))
    print("─" * 78)


if __name__ == "__main__":
    main()
