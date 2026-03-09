# Session Reflection — [DATE] — [BRIEF TOPIC]

## What Was Done
<!-- 3-5 bullet points. Factual: what tasks were completed. -->

- ...

## Critical Path
<!-- The minimum sequence of operations that actually mattered. If the real session took detours, note both: what was done vs what would have been sufficient. -->

1. ...

## Friction Log
<!-- Objective record of what went wrong or took extra effort. Focus on WHAT HAPPENED, not why or what should be done differently. Let the facts speak for themselves.

Each entry should include:
- What was attempted (the actual API call or action)
- What happened (error message, unexpected return value, crash)
- How many round-trips it cost
-->

| What was attempted | What happened | Cost |
|---|---|---|
| e.g., `parm("source").eval()` on OpenCL node | KeyError — parm doesn't exist, actual name is `kernelcode` | 1 round-trip |
| e.g., batch-created 12 HDA nodes in one script | Houdini crashed — NAS dependency loading overwhelmed main thread | Lost entire session |

## Observations
<!-- Factual things learned about Houdini, the API, or the codebase. No recommendations — just "X works like Y" or "X does not work as expected". These are candidates for migration to context/ docs. -->

- ...
