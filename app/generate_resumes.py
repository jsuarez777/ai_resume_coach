#!/usr/bin/env python3
"""Generate resumes for existing job descriptions at controlled fit levels.

Interactive flow:
  1. Pick a generated jobs_*.jsonl file under data/job_description/ (default: most
     recent; each option shows its job count).
  2. Choose which jobs to use: all (default), a CSV/range like "1,3,5-9", or "NR"
     (e.g. "20R") to randomly pick N jobs.
  3. Resumes per job (default and minimum: 5).
  4. Pick which style templates to use (default all; CSV/range accepted).
  5. Pick which fit levels to use (default all; CSV/range accepted).

For each job, resumes are produced by rotating fit levels and styles in lockstep
(resume i uses fits[i % nfits] and styles[i % nstyles]) until the per-job count is
reached. Each resume is validated into the Resume model (with the same correction
loop + 429 backoff as the job generator) and written to one timestamped JSONL under
data/resume/<version>/, tagged with its source job's trace_id.

Run from the project root:

    export OPENAI_API_KEY='sk-...'
    python app/generate_resumes.py                 # interactive
    python app/generate_resumes.py --dry-run        # plan + sample prompt, no API
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app.generate_job_descriptions as gjd  # noqa: E402 - reuse generic helpers
from model.resume import Resume  # noqa: E402

DEFAULT_VERSION = "v1"
DEFAULT_RESUMES_PER_JOB = 5  # also the minimum
PROMPTS_DIR = PROJECT_ROOT / "prompts" / "resume"
JOBS_DIR = PROJECT_ROOT / "data" / "job_description"
OUTPUT_BASE = PROJECT_ROOT / "data" / "resume"
LOGS_DIR = PROJECT_ROOT / "logs"

# style template slug -> WritingStyle enum value
WRITING_STYLE_MAP = {
    "formal": "Formal",
    "casual": "Casual",
    "technical": "Technical",
    "achievement": "Achievement",
    "career-changer": "Career-changer",
}

log = logging.getLogger(__name__)


def _setup_logging(to_file: bool) -> Path | None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_file = None
    if to_file:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOGS_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_generate_resumes.log"
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=handlers)
    if os.getenv("LOG_HTTP") != "1":
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
    return log_file


# --------------------------------------------------------------------------- selection helpers


def _count_lines(path: Path) -> int:
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def _find_jobs_files() -> list[Path]:
    """All jobs_*.jsonl under data/job_description/, newest first."""
    return sorted(JOBS_DIR.glob("**/jobs_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def _parse_selection(raw: str, n: int) -> list[int]:
    """Parse '' (all), 'NR' (random N), or CSV of numbers/ranges (1-based) -> 0-based indices."""
    raw = raw.strip()
    if not raw:
        return list(range(n))
    m = re.fullmatch(r"(\d+)\s*[rR]", raw)
    if m:
        return sorted(random.sample(range(n), min(int(m.group(1)), n)))
    chosen: set[int] = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if "-" in tok:
            a, _, b = tok.partition("-")
            if a.strip().isdigit() and b.strip().isdigit():
                for v in range(int(a), int(b) + 1):
                    if 1 <= v <= n:
                        chosen.add(v - 1)
        elif tok.isdigit() and 1 <= int(tok) <= n:
            chosen.add(int(tok) - 1)
    return sorted(chosen) if chosen else list(range(n))


def _pick_index(title: str, labels: list[str], default_index: int) -> int:
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


def _pick_multi(title: str, items: list[str]) -> list[str]:
    print(f"\n{title}")
    for i, it in enumerate(items, 1):
        print(f"  {i}. {it}")
    raw = input(f"Select (CSV/range 1-{len(items)}) [default: all]: ").strip()
    return [items[i] for i in _parse_selection(raw, len(items))]


def _discover_resume_styles(version_dir: Path) -> list[str]:
    prefix, suffix = "gen_resume_", ".template"
    return sorted(
        p.name[len(prefix) : -len(suffix)] for p in version_dir.glob(f"{prefix}*{suffix}")
    )


def _load_fit_levels(version_dir: Path) -> dict[str, str]:
    data = yaml.safe_load(gjd._read(version_dir / "fit_levels.yml"))
    return data["fit_levels"]


# --------------------------------------------------------------------------- generation


def assemble_resume_prompt(
    version_dir: Path, style: str, fit_name: str, fit_prompt: str, job: dict
) -> str:
    """template (filled with target-job context) -> fit-level guidance -> prerequisite -> suffix."""
    template = gjd._read(version_dir / f"gen_resume_{style}.template")
    prerequisite = gjd._read(version_dir / "gen_resume_prerequisite.prompt")
    suffix = gjd._read(version_dir / "gen_resume_output_format_suffix.prompt")
    req = job.get("requirements", {})
    ctx = {
        "target_summary": job.get("summary", ""),
        "target_industry": job.get("company", {}).get("industry", ""),
        "target_experience_level": req.get("experience_level", ""),
        "required_skills": ", ".join(req.get("required_skills", [])),
        "fit_level": fit_name,
    }
    try:
        filled = template.format_map(ctx)
    except KeyError as exc:
        raise KeyError(f"Template placeholder {exc} not available in job context") from exc
    return f"{filled}\nFit level guidance:\n{fit_prompt}\n{prerequisite}\n{suffix}"


def stamp_resume_metadata(data: dict, style: str, fit_name: str, version: str) -> dict:
    """The pipeline owns all resume metadata (it encodes how we asked it to generate)."""
    meta = data.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        data["metadata"] = meta
    meta["trace_id"] = str(uuid.uuid4())
    meta["generated_at"] = datetime.now(timezone.utc).isoformat()
    meta["prompt_template"] = f"{version}/gen_resume_{style}"
    meta["fit_level"] = fit_name
    meta["writing_style"] = WRITING_STYLE_MAP.get(style, style.capitalize())
    return data


def _generate_one_resume(
    client, version_dir: Path, version: str, style: str, fit: tuple[str, str], job: dict
) -> tuple[str, str, str | None, str | None, str | None, int]:
    """Worker: assemble -> query -> parse -> validate (Resume) with correction loop.

    Returns (style, fit_name, job_trace_id, record_json_or_None, error_or_None, corrections).
    """
    fit_name, fit_prompt = fit
    job_tid = job.get("metadata", {}).get("trace_id")
    base_prompt = assemble_resume_prompt(version_dir, style, fit_name, fit_prompt, job)
    label = f"{style}/{fit_name} <- job {(job_tid or '?')[:8]}"
    prompt_input: object = base_prompt
    last_error: str | None = None

    for attempt in range(gjd.MAX_CORRECTIONS + 1):
        try:
            raw = gjd._query_with_backoff(client, prompt_input, label)
        except Exception as exc:  # noqa: BLE001 - API error: not correctable
            return style, fit_name, job_tid, None, f"{type(exc).__name__}: {exc}", attempt
        try:
            data = stamp_resume_metadata(gjd.extract_json(raw), style, fit_name, version)
            resume = Resume.model_validate(data)
            out = resume.model_dump(mode="json")
            out["source_job_trace_id"] = job_tid
            if attempt:
                log.info(f"  [corrected] {label}: valid after {attempt} correction attempt(s)")
            return style, fit_name, job_tid, json.dumps(out), None, attempt
        except (ValidationError, ValueError) as exc:
            last_error = gjd._format_validation_error(exc)
            if attempt == gjd.MAX_CORRECTIONS:
                log.warning(
                    f"  [give up] {label}: still invalid after {gjd.MAX_CORRECTIONS} -> {last_error}"
                )
                return style, fit_name, job_tid, None, last_error, attempt
            log.warning(
                f"  [validation] {label}: attempt {attempt + 1} invalid -> {last_error}; "
                f"requesting correction {attempt + 1}/{gjd.MAX_CORRECTIONS}"
            )
            prompt_input = gjd._build_correction_prompt(base_prompt, raw, last_error)
    return style, fit_name, job_tid, None, last_error, gjd.MAX_CORRECTIONS


def build_tasks(
    jobs: list[dict], per_job: int, styles: list[str], fits: list[tuple[str, str]]
) -> list[tuple[dict, str, tuple[str, str]]]:
    """For each job, rotate fit levels and styles in lockstep until per_job is reached."""
    tasks = []
    for job in jobs:
        for i in range(per_job):
            tasks.append((job, styles[i % len(styles)], fits[i % len(fits)]))
    return tasks


# --------------------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION, help="Prompt version (default: v1)")
    parser.add_argument(
        "--per-job", type=int, default=None, help="Resumes per job (min/default: 5)"
    )
    parser.add_argument(
        "--limit-jobs",
        type=int,
        default=None,
        help="Use only the first N jobs from the file (skips the job-selection prompt)",
    )
    parser.add_argument("--model", default=None, help=f"Model (default: {gjd.DEFAULT_MODEL})")
    parser.add_argument("--temperature", type=float, default=None, help="Sampling temperature")
    parser.add_argument(
        "--parallel", type=int, default=gjd.DEFAULT_PARALLEL, help="Max parallel API calls"
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan + sample prompt only, no API")
    args = parser.parse_args()

    _setup_logging(to_file=not args.dry_run)
    interactive = gjd._interactive()

    version_dir = PROMPTS_DIR / args.version
    if not version_dir.is_dir():
        sys.exit(f"No resume prompts found at {version_dir}")

    # 1. jobs file
    files = _find_jobs_files()
    if not files:
        sys.exit(f"No jobs_*.jsonl files under {JOBS_DIR}. Generate job descriptions first.")
    if interactive:
        labels = [f"{p.parent.name}/{p.name}  ({_count_lines(p)} jobs)" for p in files]
        jobs_file = files[_pick_index("Job-descriptions file:", labels, 0)]
    else:
        jobs_file = files[0]
    jobs = [json.loads(line) for line in jobs_file.read_text().splitlines() if line.strip()]

    # 2. which jobs
    if args.limit_jobs is not None:
        jobs = jobs[: args.limit_jobs]
    elif interactive:
        raw = input(
            f"Jobs to use of {len(jobs)} (CSV, range like 1-10, or N+R for random N) [default: all]: "
        )
        jobs = [jobs[i] for i in _parse_selection(raw, len(jobs))]

    # 3. resumes per job (min 5)
    if args.per_job is not None:
        per_job = max(DEFAULT_RESUMES_PER_JOB, args.per_job)
    elif interactive:
        per_job = gjd._ask_int(
            "Resumes per job", DEFAULT_RESUMES_PER_JOB, minimum=DEFAULT_RESUMES_PER_JOB
        )
    else:
        per_job = DEFAULT_RESUMES_PER_JOB

    # 4. styles
    styles = _discover_resume_styles(version_dir)
    if not styles:
        sys.exit(f"No gen_resume_*.template files in {version_dir}")
    styles = _pick_multi("Style templates:", styles) if interactive else styles

    # 5. fit levels
    fit_map = _load_fit_levels(version_dir)
    fit_names = list(fit_map)
    if interactive:
        fit_names = _pick_multi("Fit levels:", fit_names)
    fits = [(name, fit_map[name]) for name in fit_names]

    model = args.model or (
        gjd._pick_model(gjd.PRICES, gjd.DEFAULT_MODEL) if interactive else gjd.DEFAULT_MODEL
    )

    tasks = build_tasks(jobs, per_job, styles, fits)
    temp_label = "unset" if args.temperature is None else args.temperature
    log.info(
        f"\nVersion: {args.version} | jobs: {len(jobs)} | per-job: {per_job} | "
        f"styles: {len(styles)} | fits: {len(fits)} | model: {model} | temp: {temp_label}"
    )
    log.info(f"Total resumes to generate: {len(tasks)}")

    if args.dry_run:
        job0, style0, fit0 = tasks[0]
        sample = assemble_resume_prompt(version_dir, style0, fit0[0], fit0[1], job0)
        log.info(f"\n----- sample prompt: {style0} / {fit0[0]} ({len(sample)} chars) -----")
        log.info(sample)
        return

    client = gjd.MyOpenAIClient(model=model, temperature=args.temperature)
    client.validate_api_key()
    client.get_client()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_BASE / args.version
    out_dir.mkdir(parents=True, exist_ok=True)
    valid_path = out_dir / f"resumes_{timestamp}.jsonl"
    invalid_path = out_dir / f"invalid_{timestamp}.jsonl"

    workers = max(1, min(args.parallel, len(tasks)))
    log.info(f"\nGenerating {len(tasks)} resume(s) with up to {workers} parallel worker(s)...")
    n_valid = n_invalid = n_corrected = 0
    started = time.perf_counter()
    with (
        valid_path.open("w") as vf,
        invalid_path.open("w") as inf,
        ThreadPoolExecutor(max_workers=workers) as executor,
    ):
        futures = [
            executor.submit(
                _generate_one_resume, client, version_dir, args.version, style, fit, job
            )
            for job, style, fit in tasks
        ]
        for i, future in enumerate(as_completed(futures), 1):
            style, fit_name, job_tid, record, error, corrections = future.result()
            label = f"{style}/{fit_name} <- job {(job_tid or '?')[:8]}"
            if record is not None:
                vf.write(record + "\n")
                n_valid += 1
                if corrections:
                    n_corrected += 1
                tag = f"OK (corrected x{corrections})" if corrections else "OK"
                log.info(f"[{i}/{len(tasks)}] {tag}    {label}")
            else:
                inf.write(
                    json.dumps(
                        {"style": style, "fit_level": fit_name, "job": job_tid, "error": error}
                    )
                    + "\n"
                )
                n_invalid += 1
                log.warning(f"[{i}/{len(tasks)}] FAIL  {label} -> {error}")

    elapsed = time.perf_counter() - started
    per = elapsed / len(tasks) if tasks else 0.0
    rate = len(tasks) / elapsed if elapsed > 0 else 0.0
    log.info(
        f"\nDone in {elapsed:.1f}s  ({len(tasks)} resumes, {per:.2f}s/ea, {rate:.1f}/s)  "
        f"—  valid {n_valid} ({n_corrected} via correction), invalid {n_invalid}"
    )
    log.info(f"Valid:   {n_valid} -> {valid_path}")
    log.info(f"Invalid: {n_invalid} -> {invalid_path}")


if __name__ == "__main__":
    main()
