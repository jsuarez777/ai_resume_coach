#!/usr/bin/env python3
"""Generate job descriptions one at a time from the prompt templates.

For each role in a version's `categories.yml`, this assembles
`template -> prerequisite -> output-format suffix`, asks the LLM for a single
job description, validates it against the `JobDescription` Pydantic model, and
writes valid/invalid records to JSONL.

Run from the project root (or anywhere; the project root is added to sys.path):

    export OPENAI_API_KEY='sk-...'
    python app/generate_job_descriptions.py                   # interactive menu (style/version/model/roles)
    python app/generate_job_descriptions.py --style formal-corporate --limit 3
    python app/generate_job_descriptions.py --dry-run         # assemble only, no API calls

Any selection passed as a flag skips its menu; omitted selections prompt a menu
when run on a TTY, and fall back to defaults when piped/non-interactive.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
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


def stamp_metadata(data: dict, role: dict) -> dict:
    """The pipeline owns trace_id/generated_at; is_niche_role comes from the input."""
    meta = data.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        data["metadata"] = meta
    meta["trace_id"] = str(uuid.uuid4())
    meta["generated_at"] = datetime.now(timezone.utc).isoformat()
    meta["is_niche_role"] = bool(role.get("is_niche_role", False))
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


def resolve_selections(args: argparse.Namespace) -> tuple[str, str, str, list[dict]]:
    """Resolve version/style/model/roles from flags, falling back to an interactive
    menu when a flag is omitted and we're on a TTY, else to the defaults."""
    interactive = _interactive()

    versions = _discover_versions()
    if args.version:
        version = args.version
    elif interactive and len(versions) > 1:
        version = _pick_one("Prompt version:", versions, DEFAULT_VERSION if DEFAULT_VERSION in versions else versions[0])
    else:
        version = DEFAULT_VERSION if DEFAULT_VERSION in versions else (versions[0] if versions else DEFAULT_VERSION)
    version_dir = PROMPTS_DIR / version

    styles = _discover_styles(version_dir)
    if args.style:
        style = args.style
    elif interactive and styles:
        style = _pick_one("Template style:", styles, styles[0])
    else:
        style = styles[0] if styles else DEFAULT_STYLE

    if args.model:
        model = args.model
    elif interactive:
        model = _pick_model(PRICES, DEFAULT_MODEL if DEFAULT_MODEL in PRICES else list(PRICES)[0])
    else:
        model = DEFAULT_MODEL

    roles = yaml.safe_load(_read(version_dir / "categories.yml"))["roles"]
    if args.limit is not None:
        roles = roles[: args.limit]
    elif interactive:
        roles = _pick_roles(roles)

    return version, style, model, roles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=None, help="Prompt version folder (menu if omitted; default: v1)")
    parser.add_argument("--style", default=None, help="Template style, e.g. formal-corporate, casual-startup (menu if omitted)")
    parser.add_argument("--model", default=None, help=f"Model (menu if omitted; default: {DEFAULT_MODEL})")
    parser.add_argument("--limit", type=int, default=None, help="Max number of roles to generate (skips the role menu)")
    parser.add_argument("--dry-run", action="store_true", help="Assemble prompts only; no API calls or files written")
    args = parser.parse_args()

    version, style, model, roles = resolve_selections(args)
    version_dir = PROMPTS_DIR / version

    print(f"\nVersion: {version} | style: {style} | model: {model} | roles: {len(roles)}")

    if args.dry_run:
        for role in roles:
            prompt = assemble_prompt(version_dir, style, role)
            print(f"\n===== {role.get('role')} ({len(prompt)} chars) =====")
            print(prompt)
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
        for i, role in enumerate(roles, 1):
            label = role.get("role", f"role_{i}")
            try:
                prompt = assemble_prompt(version_dir, style, role)
                response = client.query(input=prompt)
                raw = getattr(response, "output_text", None) or str(response)
                data = stamp_metadata(extract_json(raw), role)
                job = JobDescription.model_validate(data)
                vf.write(job.model_dump_json() + "\n")
                n_valid += 1
                print(f"[{i}/{len(roles)}] OK    {label}")
            except Exception as exc:  # noqa: BLE001 - record and continue
                inf.write(json.dumps({"role": role, "error": f"{type(exc).__name__}: {exc}"}) + "\n")
                n_invalid += 1
                print(f"[{i}/{len(roles)}] FAIL  {label} -> {type(exc).__name__}: {exc}")

    print(f"\nValid:   {n_valid} -> {valid_path}")
    print(f"Invalid: {n_invalid} -> {invalid_path}")


if __name__ == "__main__":
    main()
