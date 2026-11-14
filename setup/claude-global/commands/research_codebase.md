---
description: Research the codebase and document it as-is in docs/research/
argument-hint: [research question]
---

# Research Codebase

Answer the user's research question by spawning parallel research sub-agents and synthesizing their findings into a research document.

## Your only job: document the codebase as it exists today
- Describe what exists, where it lives, how it works, and how components interact.
- No suggestions, critique, root-cause analysis, refactoring ideas or future enhancements unless the user explicitly asks for them.
- You and every sub-agent are documentarians, not evaluators.

## Start
If a question was passed (`$ARGUMENTS`), begin immediately. Otherwise reply
"I'm ready to research the codebase. What's your research question?" and wait.

## Steps
1. **Read mentioned files first**: fully (no limit/offset), yourself, in the main context, before spawning any sub-agent.
2. **Decompose the question** into research areas and track them in your todo list.
3. **Spawn sub-agents** as described under "Sub-agents". Start with locators, then send analyzers at the most promising findings.
4. **Wait for all sub-agents**, then synthesize. Live code is the source of truth: verify surprising claims yourself. Use `file:line` references.
5. **Gather metadata** (never write placeholders):
   - timestamp: `date -Iseconds` (PowerShell: `Get-Date -Format o`)
   - `git rev-parse --short HEAD`, `git branch --show-current`, `git config user.name`
   - repository: `git remote get-url origin`, else the folder name
6. **Write** `docs/research/YYYY-MM-DD-<kebab-topic>.md` (create the directory if missing) using the template below.
7. **Permalinks (optional)**: if the commit is pushed to GitHub, turn local refs into
   `https://github.com/{owner}/{repo}/blob/{commit}/{file}#L{line}` (`gh repo view --json owner,name`).
8. **Present** a short summary with the key file references and the document path. Ask for follow-ups.
9. **Follow-ups**: append `## Follow-up Research <timestamp>` to the same document and update `last_updated`.

## Template
````markdown
---
date: <ISO timestamp>
author: <git user.name>
git_commit: <short hash>
branch: <branch>
repository: <repo>
topic: "<research question>"
tags: [research, <component-names>]
status: complete
last_updated: <YYYY-MM-DD>
---

# Research: <research question>

## Research Question
<original query>

## Summary
<high-level answer, describing what exists>

## Detailed Findings
### <Component / Area>
- What exists (`path/file.ext:line`) and how it connects to other parts

## Code References
- `path/to/file.py:123` - what is there

## Architecture Notes
<patterns, conventions and design decisions as implemented>

## Related Research
<other documents in docs/research/>

## Open Questions
<areas that need further investigation>
````

## Sub-agents
Spawn them with the Agent tool (formerly Task) using `subagent_type: "general-purpose"` and `model: "sonnet"`.
Send independent agents in one message so they run in parallel. Give each a narrow, read-only brief in one role:
- **Locator**: find WHERE the files/components for X live. Return paths grouped by purpose, no analysis.
- **Analyzer**: explain HOW X works. Trace data flow with `file:line` references. Describe, don't critique.
- **Pattern finder**: find existing examples similar to X. Return `file:line` plus short excerpts.
- **Web researcher** (only if the user asks for external docs): return findings with source links, and keep those links in the final document.

Every brief states the question, the directories to focus on, "read-only: do not modify files", and "return file:line references".

## Rules
- Keep the main context for synthesis; sub-agents do the deep reading.
- Always run fresh research. Existing documents in `docs/research/` are context, not truth.
- Follow the step order: read files -> spawn -> wait -> metadata -> write.
