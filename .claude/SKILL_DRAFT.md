# `/draft` Skill - Commit Message Suggestion Helper

## Overview
The `/draft` command analyzes your staged or changed files and provides detailed information to help you write a meaningful commit message.

## How It Works

### Staged vs. All Changes
- **If you have staged files** (via `git add`), `/draft` analyzes only those changes
- **If no staged files exist**, it analyzes all modified/added files in your working directory

### Output Provided
1. **📋 File List** - Shows which files are staged or changed
2. **📊 Summary Statistics** - Counts files, added lines, and removed lines
3. **🔍 Key Changes** - Detects new/removed functions and classes
4. **📂 File Types** - Shows distribution of file types changed
5. **💡 Diff Preview** - First 100 lines of the diff for context

## Usage Example

```bash
# Stage your changes
git add .

# Run the draft command to analyze
/draft

# Based on the output, Claude can suggest a commit message
# For example, if you see:
#   - 61 new tests added
#   - model/resume.py and model/job_description.py modified
#   - Key changes: test functions for edge cases
#
# A good commit message would be:
# "Add comprehensive corner case tests for Resume and JobDescription models"
```

## Workflow

1. Make your changes
2. Stage the files: `git add <files>`
3. Run `/draft` to see what changed
4. Based on the output, decide on your commit message
5. Create the commit: `git commit -m "Your message"`

## Tips

- Run `/draft` before writing your commit message to ensure you haven't missed anything
- Use the "Key changes" section to understand the high-level impact
- The file types summary helps identify if changes span multiple components
- If the diff is large (>100 lines), you'll see a summary; review with `git diff --cached` if needed

## Notes

- The skill only shows analysis; it doesn't create commits automatically
- Diff preview is limited to 100 lines to keep output manageable
- .pyc and cache files are included in the analysis but can usually be ignored
