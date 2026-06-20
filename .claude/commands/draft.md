Suggest a concise git commit message based on the following changes. Output only the commit message and nothing else, wrapped in a fenced code block (triple backticks) so it renders as a copy-pasteable monospace block.

$BASH(if [ -n "$(git diff --cached --name-only 2>/dev/null)" ]; then git diff --cached; else git diff; fi)
