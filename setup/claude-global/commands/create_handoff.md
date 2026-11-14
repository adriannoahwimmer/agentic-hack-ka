---
description: Write a concise handoff document to docs/handoffs/ for a fresh session
argument-hint: [short description]
---

# Create Handoff

Write a handoff document so that another agent in a new session can continue your work. Be thorough but concise: compact your context without losing any key details.

## 1. Path and metadata
- Path: `docs/handoffs/YYYY-MM-DD_HH-MM-SS_<kebab-description>.md` (24-hour time; create the directory if missing).
- Metadata (no placeholders): timestamp via `date -Iseconds` (PowerShell: `Get-Date -Format o`), `git rev-parse --short HEAD`, `git branch --show-current`, `git config user.name`, and the repo from `git remote get-url origin` or the folder name.

## 2. Write the document
````markdown
---
date: <ISO timestamp>
author: <git user.name>
git_commit: <short hash>
branch: <branch>
repository: <repo>
topic: "<task> handoff"
tags: [handoff, <component-names>]
status: complete
type: handoff
---

# Handoff: <very concise description>

## Task(s)
<each task with status: completed / in progress / planned. Name the current phase if you are working from a plan, and reference the plan or research docs (docs/plans/, docs/research/).>

## Critical References
<2-3 most important spec/design/plan file paths, or blank>

## Recent Changes
<changes you made, as path/file.ext:line references>

## Learnings
<patterns, root causes, gotchas the next agent must know, with file paths>

## Artifacts
<exhaustive list of files you created or updated (plans, research, code) as paths or file:line>

## Action Items & Next Steps
<ordered list for the next agent>

## Other Notes
<anything else useful: where relevant code lives, open questions>
````

## 3. Respond
Reply with:
```
Handoff created. Resume it in a new session with:

/resume_handoff docs/handoffs/<file>.md
```

## Notes
- More information, not less. The template is the minimum.
- Avoid large code blocks or diffs. Prefer `path/file.ext:12-24` references, except for a short snippet that is essential (e.g. an error being debugged).
- Don't commit the handoff unless the user asks.
