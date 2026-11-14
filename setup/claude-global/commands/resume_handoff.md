---
description: Resume work from a handoff in docs/handoffs/ after verifying the current state
argument-hint: [path to handoff, or empty for the latest]
---

# Resume Handoff

Resume work from a handoff document through an interactive process. Handoffs carry context, learnings and next steps from a previous session.

## Start
- **Path given** (`$ARGUMENTS`): read the handoff fully, then read every plan/research document it links (`docs/plans/`, `docs/research/`) yourself. Don't delegate these critical reads.
- **No path**: list `docs/handoffs/` and take the newest file (the filenames start with `YYYY-MM-DD_HH-MM-SS`). Tell the user which handoff you picked. If the directory is empty or missing, ask for a path.

## Step 1: Analyze
1. Extract the tasks and their statuses, recent changes, learnings, artifacts, action items and notes.
2. Verify the current state with research sub-agents: Agent tool (formerly Task), `subagent_type: "general-purpose"`, `model: "sonnet"`, in parallel, with read-only briefs. Example: "Check whether these changes still exist: [list with file:line]. Report present / missing / modified."
3. Wait for all of them, then read the key files from "Learnings" and "Recent Changes" yourself.

## Step 2: Present
```
I've analyzed the handoff from [date]. Current situation:

**Tasks:**
- [task]: [status in handoff] -> [verified status now]

**Learnings still valid?**
- [learning with file:line] - [still valid / changed]

**Recent changes:**
- [change] - [present / missing / modified]

**Recommended next actions:**
1. [most logical next step]
2. [next]

**Potential issues:**
- [conflicts, regressions, missing dependencies]

Shall I proceed with [action 1], or do you want to adjust?
```
Get confirmation before acting.

## Step 3: Plan and execute
Turn the action items into a todo list (add anything newly discovered, ordered by dependency), then start with the first approved task. Apply the handoff's learnings, and when done consider `/create_handoff` for the next session.

## Guidelines
- Never assume the handoff state matches the current code. Verify file references and look for changes since the handoff's commit (`git log <commit>..HEAD --oneline`).
- If the code has diverged or the handoff is stale, re-evaluate the strategy with the user instead of following it blindly.
- If a task was in progress, finish it before starting new work.
