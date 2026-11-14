---
description: Update an existing plan in docs/plans/ based on feedback, grounded in the code
argument-hint: [plan path] [requested changes]
---

# Iterate Implementation Plan

Update an existing implementation plan based on user feedback. Be skeptical and keep every change grounded in the actual code.

## Start
Parse `$ARGUMENTS` for a plan path (in `docs/plans/`) and the requested changes.
- **No plan path**: list `docs/plans/` (newest first) and ask which plan to update.
- **Plan but no feedback**: ask what to change (e.g. "add a phase for X", "split phase 2", "tighten the success criteria").
- **Both given**: go straight to step 1.

## Step 1: Understand
Read the plan completely (no limit/offset). Work out what the user wants added, changed or removed, and whether that needs code research.

## Step 2: Research (only if needed)
Only when the change needs new technical understanding: spawn research sub-agents with the Agent tool (formerly Task), using `subagent_type: "general-purpose"` and `model: "sonnet"`, in parallel. Use the roles **Locator** (where), **Analyzer** (how, with `file:line`) and **Pattern finder** (similar examples). Give each exact directories, a read-only instruction, and ask for `file:line` refs. Read the files they identify fully, then wait for all of them.

## Step 3: Confirm
Before editing, present:
```
Based on your feedback, I understand you want to:
- [change 1]
- [change 2]

My research found:
- [relevant constraint or pattern, with file:line]

I plan to update the plan by:
1. [modification]
2. [modification]

Does this match your intent?
```
Wait for confirmation.

## Step 4: Edit
- Make surgical edits with the Edit tool. Keep the structure unless asked to change it.
- Keep `file:line` refs accurate and success criteria measurable.
- Keep the split between **Automated Verification** (commands from the project's CLAUDE.md) and **Manual Verification**.
- When you change scope, update "What We're NOT Doing". When you change the approach, update "Implementation Approach".

## Step 5: Report
List the changes made and the plan path, then ask whether further adjustments are needed.

## Guidelines
- Question requests that conflict with existing phases or seem infeasible.
- Don't over-engineer: research only what the change needs.
- No unresolved questions in the plan. Ask first, then edit.
