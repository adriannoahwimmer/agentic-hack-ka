---
description: Implement an approved plan from docs/plans/ phase by phase with verification
argument-hint: [path to plan in docs/plans/]
---

# Implement Plan

Implement an approved technical plan from `docs/plans/`. Plans contain phases with specific changes and success criteria.

## Getting started
Given a plan path (`$ARGUMENTS`):
- Read the plan completely and note existing checkmarks (`- [x]`).
- Read the original ticket/research and every file the plan mentions, fully (no limit/offset).
- Create a todo list and start implementing once you understand what needs to be done.

If no plan path was provided, list `docs/plans/` (newest first) and ask which one to use.

## Philosophy
Follow the plan's intent while adapting to what you find. Finish each phase before starting the next, and update the plan's checkboxes as you go.

If reality doesn't match the plan, stop and present the mismatch:
```
Issue in Phase [N]:
Expected: [what the plan says]
Found: [actual situation]
Why this matters: [explanation]

How should I proceed?
```

## Verification
After each phase:
- Run the automated success criteria (the project's check command from CLAUDE.md, e.g. `scripts/check.ps1`).
- Fix failures before moving on, then check off the completed items in the plan file.
- Pause for human verification:
  ```
  Phase [N] Complete - Ready for Manual Verification

  Automated verification passed:
  - [checks that passed]

  Please perform the manual verification steps from the plan:
  - [manual items]

  Tell me when manual testing is done so I can continue with Phase [N+1].
  ```
If told to run several phases in a row, pause only after the last one. Never check off manual items until the user confirms them.

## If you get stuck
Make sure you've read all relevant code, consider whether the code changed since the plan was written, and present the mismatch clearly. Use sub-agents sparingly, for targeted debugging or unfamiliar territory: Agent tool, `subagent_type: "general-purpose"`, `model: "sonnet"`, read-only brief.

## Resuming
If the plan has checkmarks, trust completed work and continue from the first unchecked item. Re-verify earlier work only if something seems off.
