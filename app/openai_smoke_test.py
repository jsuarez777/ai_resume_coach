#!/usr/bin/env python3
"""Minimal example: load the openai_client package and run a single query.

Run from the project root so the `openai_client` package is importable:

    export OPENAI_API_KEY='sk-...'
    python app/openai_smoke_test.py
"""

import sys
from pathlib import Path

# Allow running from anywhere by putting the project root on sys.path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from openai_client import MyOpenAIClient, cost_summary  # noqa: E402

MODEL = "gpt-5-nano"


def main() -> None:
    client = MyOpenAIClient(model=MODEL)
    client.validate_api_key()

    response = client.query(input="How many G's are in the word 'Hugging Face'?")

    # Print the model's text output (responses API exposes output_text).
    text = getattr(response, "output_text", None) or response
    print(text)

    usage = getattr(response, "usage", None)
    if usage is not None:
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        print()
        print(cost_summary(MODEL, input_tokens, output_tokens))


if __name__ == "__main__":
    main()
