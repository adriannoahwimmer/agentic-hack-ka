---
description: Create a phased implementation plan in docs/plans/ through interactive research
argument-hint: [task description or path to ticket/research doc]
---

# Create Implementation Plan

Create a detailed implementation plan through an interactive, iterative process. Be skeptical, thorough, and work collaboratively with the user.

## Start
If a task or file was passed (`$ARGUMENTS`), read any referenced files FULLY and begin research. Otherwise reply:
```
I'll help you create an implementation plan. Please provide:
1. The task description (or a path to a ticket / research document)
2. Relevant context, constraints or requirements
3. Links to related research or previous implementations
```
and wait.

## Step 1: Context gathering
1. **Read all mentioned files fully** (tickets, `docs/research/*`, related plans) yourself before spawning any sub-agent.
2. **Spawn research sub-agents** (see "Sub-agents") to find the relevant files and explain how the current implementation works.
3. **Read every file the sub-agents identify as relevant**, fully, in the main context.
4. **Cross-check** the requirements against the actual code: note discrepancies, assumptions and true scope.
5. **Present your understanding** with `file:line` references, and ask only questions the code cannot answer.

## Step 2: Research and design options
1. If the user corrects you, verify the correction in the code. Don't just accept it.
2. Track open research in your todo list and spawn more sub-agents as needed. Wait for all of them.
3. Present the current state, 2-3 design options with pros and cons, and open questions. Ask which approach fits.

## Step 3: Structure
Propose an outline (overview plus phase names with one line each) and get feedback before writing details.

## Step 4: Write the plan
Write `docs/plans/YYYY-MM-DD-<kebab-description>.md` (create the directory if missing):

````markdown
# <Feature/Task> Implementation Plan

## Overview
<what and why>

## Current State Analysis
<what exists, what's missing, constraints, with file:line refs>

## Desired End State
<specification of the result and how to verify it>

## What We're NOT Doing
<explicit out-of-scope list>

## Implementation Approach
<strategy and reasoning>

## Phase 1: <Name>
### Overview
### Changes Required
#### 1. <Component / file group>
**File**: `path/to/file.ext`
**Changes**: <summary; short code only where it removes ambiguity>

### Success Criteria
#### Automated Verification
- [ ] <project check command from CLAUDE.md, e.g. scripts/check.ps1>
- [ ] <specific test, lint or type check>
#### Manual Verification
- [ ] <behaviour a human must confirm>

**Implementation note**: after automated verification passes, pause for human confirmation of the manual steps before the next phase.

---

## Phase 2: <Name>
...

## Testing Strategy
<unit tests, integration tests, manual steps, edge cases>

## References
- Research: `docs/research/<file>.md`
- Similar implementation: `path/file.ext:line`
````

## Step 5: Review
Share the plan path, ask whether phases, scope and success criteria are right, and iterate until the user is satisfied.

## Sub-agents
Spawn them with the Agent tool (formerly Task) using `subagent_type: "general-purpose"` and `model: "sonnet"`, independent agents in one message so they run in parallel. Roles:
- **Locator**: WHERE do files/components for X live (paths grouped by purpose).
- **Analyzer**: HOW does X work (data flow, `file:line` refs, no critique).
- **Pattern finder**: existing examples similar to X that the plan can follow.

Each brief names the exact directories, says "read-only: do not modify files", and asks for `file:line` references. If a result looks wrong, verify it or spawn a follow-up.

## Guidelines
- **Skeptical**: question vague requirements and verify assumptions in code.
- **Interactive**: don't write the whole plan in one shot; get buy-in at each step.
- **Concrete**: file paths, line numbers, measurable success criteria. Automated checks use the commands documented in the project's CLAUDE.md.
- **Practical**: incremental, testable phases. Always fill in "What We're NOT Doing".
- **No open questions in the final plan.** If something is unresolved, stop and research or ask.
