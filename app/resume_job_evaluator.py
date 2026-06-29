#!/usr/bin/env python3
"""Evaluate resume-job pairs against the 6 rule-based failure metrics.

Reads a pairs_<ts>.jsonl under data/resume/<version>/ (default: latest; menu when
more than one), rehydrates each pair's resume (from the sibling resumes_<ts>.jsonl)
and job (indexed from data/job_description/**/jobs_*.jsonl by trace_id), and scores
each pair on:

  1. Skills Overlap     - token-set Jaccard of resume vs job required skills (float 0-1)
  2. Experience Mismatch- candidate years < 50% of required                  (flag)
  3. Seniority Mismatch - |level(job) - level(resume)| > 1 on a 0-4 scale     (flag)
  4. Missing Core Skills- any of the top-3 required skills absent             (flag)
  5. Hallucinated Skills- e.g. >=20 "Expert" skills, or impossible skill years(flag)
  6. Awkward Language   - buzzword density above threshold                    (flag)

Results are written to failure_labels_<ts>.jsonl alongside the pairs file, plus a
printed summary. Pure computation - no API calls.

Run from the project root:

    python app/resume_job_evaluator.py
    python app/resume_job_evaluator.py --pairs data/resume/v1/pairs_20260628_215844.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESUMES_DIR = PROJECT_ROOT / "data" / "resume"
JOBS_DIR = PROJECT_ROOT / "data" / "job_description"

# --------------------------------------------------------------------------- tunable constants

CORE_SKILLS_TOP_N = 3
EXPERIENCE_MISMATCH_RATIO = 0.5  # flag if candidate years < this fraction of required
SENIORITY_GAP = 1  # flag if |level difference| > this
CORE_SKILL_COVER = 0.5  # a core skill is "present" if >= this fraction of its tokens match
BUZZWORD_DENSITY = 5  # flag if buzzword count exceeds this
EXPERT_HALLUCINATION = 20  # flag if >= this many "Expert" skills
ENTRY_YEARS = 2  # "entry level" if total experience under this many years
ENTRY_EXPERT_LIMIT = 10  # flag if entry-level claims >= this many "Expert" skills

# Skill normalization
STOPWORDS = {
    "a",
    "an",
    "and",
    "or",
    "the",
    "of",
    "in",
    "to",
    "for",
    "with",
    "on",
    "at",
    "by",
    "as",
    "using",
    "use",
    "experience",
    "experienced",
    "proficiency",
    "proficient",
    "knowledge",
    "knowledgeable",
    "ability",
    "able",
    "strong",
    "basic",
    "advanced",
    "expert",
    "familiarity",
    "familiar",
    "understanding",
    "skills",
    "skill",
    "working",
    "work",
    "hands-on",
    "including",
    "various",
    "modern",
    "etc",
}
SKILL_SUFFIXES = (".js", " developer", " engineer")

# Awkward-language buzzwords (multi-word phrases checked as substrings)
BUZZWORDS = [
    "synergy",
    "synergize",
    "leverage",
    "move the needle",
    "thinking outside the box",
    "think outside the box",
    "rockstar",
    "rock star",
    "ninja",
    "guru",
    "self-starter",
    "go-getter",
    "results-driven",
    "results-oriented",
    "detail-oriented",
    "team player",
    "hard worker",
    "dynamic",
    "fast-paced",
    "best-in-class",
    "world-class",
    "cutting-edge",
    "value-add",
    "low-hanging fruit",
    "hit the ground running",
    "wear many hats",
    "passionate",
    "proactive",
    "game-changer",
    "paradigm",
    "disrupt",
    "holistic",
    "mission-driven",
    "win-win",
    "10x",
]

# Seniority keyword -> level (checked most-senior first)
_SENIORITY_KEYWORDS = [
    (
        4,
        (
            "chief",
            "ceo",
            "cto",
            "cfo",
            "coo",
            "vp",
            "vice president",
            "president",
            "director",
            "head of",
        ),
    ),
    (3, ("principal", "staff", "lead", "manager")),
    (2, ("senior", "sr")),
    (0, ("intern", "trainee", "apprentice", "junior", "jr", "assistant", "entry")),
]
_JOB_LEVEL = {
    "Entry": 0,
    "Junior": 0,
    "Mid": 1,
    "Intermediate": 1,
    "Senior": 2,
    "Lead": 3,
    "Principal": 3,
    "Executive": 4,
    "Director": 4,
    "VP": 4,
}


# --------------------------------------------------------------------------- skill normalization


def normalize_skill_tokens(text: str) -> set[str]:
    """Lowercase a skill string, strip versions/suffixes/punctuation, drop stopwords -> token set."""
    s = text.lower()
    for suf in SKILL_SUFFIXES:
        s = s.replace(suf, " ")
    s = re.sub(r"\b\d+(\.\d+)*\b", " ", s)  # version numbers
    s = re.sub(r"[^a-z0-9+#]+", " ", s)  # punctuation -> space (keep c++/c#)
    return {tok for tok in s.split() if tok and tok not in STOPWORDS}


def skill_token_set(skills: list[str]) -> set[str]:
    tokens: set[str] = set()
    for sk in skills:
        tokens |= normalize_skill_tokens(sk)
    return tokens


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------- field extraction


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def total_experience_years(resume: dict) -> float:
    """Sum experience durations (open-ended roles run to today)."""
    total = 0.0
    for exp in resume.get("experience", []):
        start = _parse_date(exp.get("start_date"))
        if not start:
            continue
        end = _parse_date(exp.get("end_date")) or date.today()
        total += max(0.0, (end - start).days / 365.25)
    return total


def _title_level(title: str) -> int:
    t = title.lower()
    for level, keywords in _SENIORITY_KEYWORDS:
        if any(k in t for k in keywords):
            return level
    return 1  # default: mid


def resume_seniority_level(resume: dict) -> int:
    """Most senior title among the 2 most recent jobs (by start_date)."""
    exp = sorted(
        resume.get("experience", []),
        key=lambda e: _parse_date(e.get("start_date")) or date.min,
        reverse=True,
    )
    recent = exp[:2]
    if not recent:
        return 1
    return max(_title_level(e.get("title", "")) for e in recent)


def job_seniority_level(job: dict) -> int:
    return _JOB_LEVEL.get(job.get("requirements", {}).get("experience_level", ""), 1)


# --------------------------------------------------------------------------- the 6 metrics


def detect_hallucinated_skills(resume: dict, total_years: float) -> tuple[bool, list[str]]:
    skills = resume.get("skills", [])
    experts = [s for s in skills if s.get("proficiency_level") == "Expert"]
    reasons = []
    if len(experts) >= EXPERT_HALLUCINATION:
        reasons.append(f">={EXPERT_HALLUCINATION} Expert skills ({len(experts)})")
    if total_years < ENTRY_YEARS and len(experts) >= ENTRY_EXPERT_LIMIT:
        reasons.append(f"entry-level ({total_years:.1f}y) with {len(experts)} Expert skills")
    for s in skills:
        yrs = s.get("years")
        if yrs is not None and yrs > total_years + 1:
            reasons.append(f"'{s.get('name')}' claims {yrs}y > {total_years:.1f}y total")
            break
    return bool(reasons), reasons


def detect_awkward_language(resume: dict) -> tuple[bool, int]:
    parts = []
    for exp in resume.get("experience", []):
        parts.extend(exp.get("responsibilities", []))
        parts.extend(exp.get("achievements", []))
    text = " ".join(parts).lower()
    count = sum(text.count(bw) for bw in BUZZWORDS)
    return count > BUZZWORD_DENSITY, count


def missing_core_skills(resume_tokens: set[str], required: list[str]) -> tuple[bool, list[str]]:
    missing = []
    for core in required[:CORE_SKILLS_TOP_N]:
        ctoks = normalize_skill_tokens(core)
        if not ctoks:
            continue
        covered = len(ctoks & resume_tokens) / len(ctoks)
        if covered < CORE_SKILL_COVER:
            missing.append(core)
    return bool(missing), missing


def analyze_pair(resume: dict, job: dict) -> dict:
    """Compute the 6 rule-based metrics for one resume against one job."""
    req = job.get("requirements", {})
    resume_tokens = skill_token_set([s.get("name", "") for s in resume.get("skills", [])])
    job_tokens = skill_token_set(req.get("required_skills", []))

    total_years = total_experience_years(resume)
    required_years = req.get("experience_years", 0) or 0
    r_level = resume_seniority_level(resume)
    j_level = job_seniority_level(job)

    halluc, halluc_reasons = detect_hallucinated_skills(resume, total_years)
    awkward, buzz_count = detect_awkward_language(resume)
    miss, miss_list = missing_core_skills(resume_tokens, req.get("required_skills", []))

    return {
        "skills_overlap_jaccard": round(jaccard(resume_tokens, job_tokens), 4),
        "experience_mismatch": required_years > 0
        and total_years < EXPERIENCE_MISMATCH_RATIO * required_years,
        "seniority_mismatch": abs(j_level - r_level) > SENIORITY_GAP,
        "missing_core_skills": miss,
        "hallucinated_skills": halluc,
        "awkward_language": awkward,
        "_detail": {
            "candidate_years": round(total_years, 1),
            "required_years": required_years,
            "resume_level": r_level,
            "job_level": j_level,
            "missing_skills": miss_list,
            "hallucination_reasons": halluc_reasons,
            "buzzword_count": buzz_count,
        },
    }


# --------------------------------------------------------------------------- loading / pairing


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _find_pairs_files() -> list[Path]:
    return sorted(
        RESUMES_DIR.glob("**/pairs_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )


def _pick(title: str, labels: list[str], default_index: int) -> int:
    print(f"\n{title}")
    for i, lab in enumerate(labels, 1):
        print(f"  {i}. {lab}{'  (default)' if i - 1 == default_index else ''}")
    while True:
        raw = input(f"Select 1-{len(labels)} [default: {default_index + 1}]: ").strip()
        if not raw:
            return default_index
        if raw.isdigit() and 1 <= int(raw) <= len(labels):
            return int(raw) - 1
        print("  Invalid choice, try again.")


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _index_by_trace(records: list[dict]) -> dict[str, dict]:
    return {r.get("metadata", {}).get("trace_id"): r for r in records}


def _build_job_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for f in JOBS_DIR.glob("**/jobs_*.jsonl"):
        index.update(_index_by_trace(_load_jsonl(f)))
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default=None, help="Path to a pairs_*.jsonl (menu if omitted)")
    args = parser.parse_args()

    if args.pairs:
        pairs_file = Path(args.pairs)
        if not pairs_file.is_file():
            sys.exit(f"Pairs file not found: {pairs_file}")
    else:
        files = _find_pairs_files()
        if not files:
            sys.exit(f"No pairs_*.jsonl under {RESUMES_DIR}. Generate resumes first.")
        if _interactive() and len(files) > 1:
            labels = [f"{p.parent.name}/{p.name}  ({_count(p)} pairs)" for p in files]
            pairs_file = files[_pick("Pairs file:", labels, 0)]
        else:
            pairs_file = files[0]

    resumes_file = pairs_file.with_name(pairs_file.name.replace("pairs_", "resumes_", 1))
    if not resumes_file.is_file():
        sys.exit(f"Sibling resumes file not found: {resumes_file}")

    pairs = _load_jsonl(pairs_file)
    resumes = _index_by_trace(_load_jsonl(resumes_file))
    jobs = _build_job_index()

    labels_path = pairs_file.with_name(pairs_file.name.replace("pairs_", "failure_labels_", 1))
    flag_keys = [
        "experience_mismatch",
        "seniority_mismatch",
        "missing_core_skills",
        "hallucinated_skills",
        "awkward_language",
    ]
    flag_counts = dict.fromkeys(flag_keys, 0)
    jaccard_sum = 0.0
    n = skipped = 0

    print(f"\n{pairs_file.relative_to(PROJECT_ROOT)}  —  {len(pairs)} pair(s)")
    with labels_path.open("w") as out:
        for p in pairs:
            resume = resumes.get(p.get("resume_trace_id"))
            job = jobs.get(p.get("job_trace_id"))
            if resume is None or job is None:
                skipped += 1
                continue
            metrics = analyze_pair(resume, job)
            row = {
                "pair_id": p.get("pair_id"),
                "job_trace_id": p.get("job_trace_id"),
                "resume_trace_id": p.get("resume_trace_id"),
                "fit_level": p.get("fit_level"),
                "writing_style": p.get("writing_style"),
                **metrics,
            }
            out.write(json.dumps(row) + "\n")
            n += 1
            jaccard_sum += metrics["skills_overlap_jaccard"]
            for k in flag_keys:
                flag_counts[k] += int(bool(metrics[k]))
            flags = ",".join(k for k in flag_keys if metrics[k]) or "none"
            print(
                f"  {p.get('fit_level', '?'):<9} jaccard={metrics['skills_overlap_jaccard']:.2f}  "
                f"flags=[{flags}]"
            )

    print(
        f"\nLabeled {n} pair(s)" + (f" ({skipped} skipped: missing resume/job)" if skipped else "")
    )
    if n:
        print(f"  avg skills_overlap (Jaccard): {jaccard_sum / n:.3f}")
        for k in flag_keys:
            print(f"  {k:<22}: {flag_counts[k]}/{n} ({flag_counts[k] / n * 100:.0f}%)")
    print(f"\nLabels -> {labels_path}")


def _count(path: Path) -> int:
    return sum(1 for line in path.read_text().splitlines() if line.strip())


if __name__ == "__main__":
    main()
