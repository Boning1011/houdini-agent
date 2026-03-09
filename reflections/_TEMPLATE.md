# Session Reflection — [DATE] — [BRIEF TOPIC]

## What Was Done
<!-- 3-5 bullet points, each one sentence. What were the actual tasks accomplished? -->

- ...

## Critical Path
<!-- Which operations actually mattered? Strip away all the exploration and dead ends — what's the minimum sequence of actions that would have achieved the same result? -->

1. ...

## Waste Analysis
<!-- What consumed context window / round-trips without contributing to the outcome? Be specific: name the API calls, the patterns, the detours. -->

| Pattern | Estimated Waste | Why It Happened |
|---------|----------------|-----------------|
| e.g., "Called scene_snapshot 4x after each small edit" | ~3 round-trips | Should have used verify= instead |
| e.g., "Read context/hda-development.md twice" | ~context | Already had the info from first read |

## Toolkit Improvement Opportunities
<!-- The key section. What changes to the bridge API, client, AGENTS.md, context docs, or skills would have made this session more efficient? Be concrete. -->

- **API**: ...
- **Docs/AGENTS.md**: ...
- **New skill candidate**: ...
- **Context doc gap**: ...

## Patterns Worth Remembering
<!-- Any reusable techniques, Houdini gotchas, or workflow patterns discovered. If significant enough, these should migrate to context/ docs. -->

- ...
