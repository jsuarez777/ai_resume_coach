Commit the following files using the /draft commit message immediately above.  If there is no /draft output immediately above, draft a concise commit message that describes the changes in these files.

$BASH(if [ -n "$(git diff --cached --name-only 2>/dev/null)" ]; then git diff --cached; else git diff; fi)
