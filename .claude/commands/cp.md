---
description: Draft a commit message, commit staged changes, and push
argument-hint: [optional extra instructions]
allowed-tools: Bash(git add:*), Bash(git status:*), Bash(git diff:*), Bash(git commit:*), Bash(git push:*), Bash(git rev-parse:*), Bash(git branch:*)
---

Commit the current changes and push them. Steps:

1. Run the /draft skill to generate a concise commit message for the changes. If nothing is staged, stage all changes first, including new untracked files (`git add -A`).
2. Commit the staged files using that message. Take any extra guidance from: $ARGUMENTS
3. Push to the current branch's upstream. If the branch has no upstream yet, push with `-u` to set it.

Report the final commit hash and the push result.
