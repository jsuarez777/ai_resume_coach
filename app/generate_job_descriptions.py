#!/usr/bin/env python3
"""Generate a batch of job descriptions across styles and roles into one JSONL.

Each job is one LLM call: assemble `template -> prerequisite -> output-format
suffix`, validate into the `JobDescription` model, and append to a single
timestamped jobs_<ts>.jsonl under data/job_description/<version>/.

Generation modes (which (style, role) pairs to produce):
  even   - N jobs split as evenly as possible across all styles and roles
  random - N jobs, each a random (style, role) pick
  custom - per-style counts entered by hand, then allowed roles per style
  single - one job per selected role for a single style (the classic flow)

Run from the project root (or anywhere; the project root is added to sys.path):

    export OPENAI_API_KEY='sk-...'
    python app/generate_job_descriptions.py                       # interactive menus
    python app/generate_job_descriptions.py --mode even --count 50
    python app/generate_job_descriptions.py --mode random --count 30 --seed 7
    python app/generate_job_descriptions.py --mode single --style formal-corporate --limit 3
    python app/generate_job_descriptions.py --mode even --count 50 --dry-run   # plan only, no API

Any selection passed as a flag skips its menu; omitted selections prompt a menu
when run on a TTY, and fall back to defaults when piped/non-interactive.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from model.job_description import JobDescription  # noqa: E402
from openai_client import MyOpenAIClient, PRICES  # noqa: E402

DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_VERSION = "v1"
DEFAULT_STYLE = "formal-corporate"
DEFAULT_COUNT = 50
MODES = ["even", "random", "custom", "single"]
PROMPTS_DIR = PROJECT_ROOT / "prompts" / "job_description"
OUTPUT_BASE = PROJECT_ROOT / "data" / "job_description"


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Required prompt file not found: {path}")
    return path.read_text()


def assemble_prompt(version_dir: Path, style: str, role: dict) -> str:
    """Compose template -> prerequisite -> output-format suffix for one role."""
    template = _read(version_dir / f"gen_job_{style}.template")
    prerequisite = _read(version_dir / "gen_job_prerequisite.prompt")
    suffix = _read(version_dir / "gen_job_description_output_format_suffix.prompt")
    try:
        filled = template.format_map(role)
    except KeyError as exc:
        raise KeyError(
            f"Template placeholder {exc} missing from categories.yml entry: {role}"
        ) from exc
    return f"{filled}\n{prerequisite}\n{suffix}"


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response (tolerates fences/prose)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model response")
    return json.loads(text[start : end + 1])


def stamp_metadata(data: dict, role: dict, style: str) -> dict:
    """The pipeline owns trace_id/generated_at/writing_style; is_niche_role from input."""
    meta = data.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        data["metadata"] = meta
    meta["trace_id"] = str(uuid.uuid4())
    meta["generated_at"] = datetime.now(timezone.utc).isoformat()
    meta["is_niche_role"] = bool(role.get("is_niche_role", False))
    meta["writing_style"] = style
    return data


def _discover_versions() -> list[str]:
    return sorted(p.name for p in PROMPTS_DIR.iterdir() if p.is_dir() and p.name.startswith("v"))


def _discover_styles(version_dir: Path) -> list[str]:
    prefix, suffix = "gen_job_", ".template"
    return sorted(p.name[len(prefix):-len(suffix)] for p in version_dir.glob(f"{prefix}*{suffix}"))


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _pick_one(title: str, options: list[str], default: str) -> str:
    """Numbered single-choice menu. Empty input picks the default."""
    print(f"\n{title}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}{'  (default)' if opt == default else ''}")
    while True:
        raw = input(f"Select 1-{len(options)} [default: {default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        print("  Invalid choice, try again.")


def _fmt_price(p: dict) -> str:
    return f"[ {p['input']:.2f} / {p['output']:.2f} ]"


def _pick_model(prices: dict, default: str) -> str:
    """Numbered model menu listing prices. Empty input picks the default."""
    models = list(prices)
    width = max(len(m) for m in models)
    print("\nModel (cost [ in / out per 1MM tok]:")
    for i, m in enumerate(models, 1):
        print(f"  {i}. {m:<{width}}  {_fmt_price(prices[m])}{'  (default)' if m == default else ''}")
    while True:
        raw = input(f"Select 1-{len(models)} [default: {default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(models):
            return models[int(raw) - 1]
        if raw in prices:
            return raw
        print("  Invalid choice, try again.")


def _pick_roles(roles: list[dict]) -> list[dict]:
    """Multi-choice menu over categories.yml roles. Empty selects role 1; 'all' selects everything."""
    print("\nRoles:")
    for i, r in enumerate(roles, 1):
        print(f"  {i}. {r.get('role')}{'  [niche]' if r.get('is_niche_role') else ''}")
    raw = input(f"Select roles (comma-separated 1-{len(roles)}, or 'all') [default: 1]: ").strip()
    if not raw:
        return [roles[0]]
    if raw.lower() == "all":
        return roles
    chosen = [roles[int(t) - 1] for t in raw.split(",") if t.strip().isdigit() and 1 <= int(t) <= len(roles)]
    return chosen or [roles[0]]


def _ask_int(prompt: str, default: int, minimum: int = 0) -> int:
    while True:
        raw = input(f"{prompt} [default: {default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and int(raw) >= minimum:
            return int(raw)
        print(f"  Enter a whole number >= {minimum}.")


def _pick_roles_allow(roles: list[dict], style: str) -> list[dict]:
    """Multi-choice role allowlist for a style. Empty / 'all' selects everything."""
    print(f"\nRoles to allow for '{style}':")
    for i, r in enumerate(roles, 1):
        print(f"  {i}. {r.get('role')}{'  [niche]' if r.get('is_niche_role') else ''}")
    raw = input(f"Select roles (comma-separated 1-{len(roles)}, or 'all') [default: all]: ").strip()
    if not raw or raw.lower() == "all":
        return roles
    chosen = [roles[int(t) - 1] for t in raw.split(",") if t.strip().isdigit() and 1 <= int(t) <= len(roles)]
    return chosen or roles


def _even_counts(total: int, n: int) -> list[int]:
    """Split `total` into `n` buckets differing by at most 1."""
    if n <= 0:
        return []
    base, rem = divmod(total, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def build_plan_even(styles: list[str], roles: list[dict], total: int) -> list[tuple[str, dict]]:
    """Distribute `total` jobs evenly across styles, and within each style across roles."""
    plan: list[tuple[str, dict]] = []
    for style, scount in zip(styles, _even_counts(total, len(styles))):
        for role, rcount in zip(roles, _even_counts(scount, len(roles))):
            plan.extend([(style, role)] * rcount)
    return plan


def build_plan_random(styles: list[str], roles: list[dict], total: int, rng: random.Random) -> list[tuple[str, dict]]:
    return [(rng.choice(styles), rng.choice(roles)) for _ in range(total)]


def build_plan_custom(styles: list[str], roles: list[dict]) -> list[tuple[str, dict]]:
    """Ask a count per style, then the allowed roles for each style that will generate."""
    plan: list[tuple[str, dict]] = []
    print("\nCustom mode: enter how many jobs to generate for each style.")
    for style in styles:
        count = _ask_int(f"  {style}", default=0)
        if count <= 0:
            continue
        allowed = _pick_roles_allow(roles, style)
        for role, rcount in zip(allowed, _even_counts(count, len(allowed))):
            plan.extend([(style, role)] * rcount)
    return plan


def resolve_version(args: argparse.Namespace) -> str:
    versions = _discover_versions()
    if args.version:
        return args.version
    if _interactive() and len(versions) > 1:
        return _pick_one("Prompt version:", versions, DEFAULT_VERSION if DEFAULT_VERSION in versions else versions[0])
    return DEFAULT_VERSION if DEFAULT_VERSION in versions else (versions[0] if versions else DEFAULT_VERSION)


def resolve_model(args: argparse.Namespace) -> str:
    if args.model:
        return args.model
    if _interactive():
        return _pick_model(PRICES, DEFAULT_MODEL if DEFAULT_MODEL in PRICES else list(PRICES)[0])
    return DEFAULT_MODEL


def resolve_plan(args: argparse.Namespace, styles: list[str], roles: list[dict]) -> tuple[str, list[tuple[str, dict]]]:
    """Resolve the generation mode and build the (style, role) plan."""
    interactive = _interactive()

    mode = args.mode
    if not mode:
        mode = _pick_one("Generation mode:", MODES, "even") if interactive else ("single" if args.style else "even")

    if mode == "single":
        if args.style:
            style = args.style
        elif interactive:
            style = _pick_one("Template style:", styles, styles[0])
        else:
            style = styles[0] if styles else DEFAULT_STYLE
        if args.limit is not None:
            sel = roles[: args.limit]
        elif interactive:
            sel = _pick_roles(roles)
        else:
            sel = roles
        return mode, [(style, r) for r in sel]

    if mode == "custom":
        if not interactive:
            sys.exit("custom mode requires an interactive terminal (use --mode even/random with --count for scripting).")
        return mode, build_plan_custom(styles, roles)

    # even / random need a total count
    total = args.count if args.count is not None else (_ask_int("How many jobs?", DEFAULT_COUNT, minimum=1) if interactive else DEFAULT_COUNT)
    if mode == "even":
        return mode, build_plan_even(styles, roles, total)
    if mode == "random":
        return mode, build_plan_random(styles, roles, total, random.Random(args.seed))
    sys.exit(f"Unknown mode: {mode}")


def summarize_plan(plan: list[tuple[str, dict]]) -> None:
    by_style = Counter(style for style, _ in plan)
    print(f"\nPlan: {len(plan)} job(s) across {len(by_style)} style(s)")
    for style in sorted(by_style):
        roles_for_style = Counter(r.get("role") for s, r in plan if s == style)
        detail = ", ".join(f"{role}×{n}" for role, n in sorted(roles_for_style.items()))
        print(f"  {style:<20} {by_style[style]:>3}   ({detail})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=None, help="Prompt version folder (menu if omitted; default: v1)")
    parser.add_argument("--mode", default=None, choices=MODES, help="Generation mode (menu if omitted)")
    parser.add_argument("--count", type=int, default=None, help="Total jobs for even/random mode (default: 50)")
    parser.add_argument("--style", default=None, help="Template style for single mode (menu if omitted)")
    parser.add_argument("--limit", type=int, default=None, help="single mode: max roles (skips the role menu)")
    parser.add_argument("--seed", type=int, default=None, help="random mode: RNG seed for reproducibility")
    parser.add_argument("--model", default=None, help=f"Model (menu if omitted; default: {DEFAULT_MODEL})")
    parser.add_argument("--dry-run", action="store_true", help="Build the plan only; no API calls or files written")
    args = parser.parse_args()

    version = resolve_version(args)
    version_dir = PROMPTS_DIR / version
    styles = _discover_styles(version_dir)
    roles = yaml.safe_load(_read(version_dir / "categories.yml"))["roles"]
    if not styles:
        sys.exit(f"No style templates found in {version_dir}")

    model = resolve_model(args)
    mode, plan = resolve_plan(args, styles, roles)

    if not plan:
        sys.exit("Empty plan: nothing to generate.")

    print(f"\nVersion: {version} | mode: {mode} | model: {model}")
    summarize_plan(plan)

    if args.dry_run:
        s0, r0 = plan[0]
        sample = assemble_prompt(version_dir, s0, r0)
        print(f"\n----- sample prompt: {s0} / {r0.get('role')} ({len(sample)} chars) -----")
        print(sample)
        return

    client = MyOpenAIClient(model=model)
    client.validate_api_key()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_BASE / version
    out_dir.mkdir(parents=True, exist_ok=True)
    valid_path = out_dir / f"jobs_{timestamp}.jsonl"
    invalid_path = out_dir / f"invalid_{timestamp}.jsonl"

    n_valid = n_invalid = 0
    with valid_path.open("w") as vf, invalid_path.open("w") as inf:
        for i, (style, role) in enumerate(plan, 1):
            label = f"{style}/{role.get('role', f'role_{i}')}"
            try:
                prompt = assemble_prompt(version_dir, style, role)
                response = client.query(input=prompt)
                raw = getattr(response, "output_text", None) or str(response)
                data = stamp_metadata(extract_json(raw), role, style)
                job = JobDescription.model_validate(data)
                vf.write(job.model_dump_json() + "\n")
                n_valid += 1
                print(f"[{i}/{len(plan)}] OK    {label}")
            except Exception as exc:  # noqa: BLE001 - record and continue
                inf.write(json.dumps({"style": style, "role": role, "error": f"{type(exc).__name__}: {exc}"}) + "\n")
                n_invalid += 1
                print(f"[{i}/{len(plan)}] FAIL  {label} -> {type(exc).__name__}: {exc}")

    print(f"\nValid:   {n_valid} -> {valid_path}")
    print(f"Invalid: {n_invalid} -> {invalid_path}")


if __name__ == "__main__":
    main()
