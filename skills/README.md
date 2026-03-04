# Skills — Authoring Guide

## What is a Skill?

A skill is a reusable solution to a specific Houdini task. When you solve a problem through the bridge, you can package it as a skill so it's instantly reusable next time.

## Structure

Each skill is a directory under `skills/`:

```
skills/
└── my_skill/
    ├── skill.md       # Description, when to use, what it does
    └── run.py         # Implementation (one or more .py files)
```

## skill.md Format

```markdown
# Skill Name

## When to Use
Describe the trigger conditions — when should the agent reach for this skill?

## What It Does
Brief description of the steps/operations performed.

## Parameters
List any inputs the skill needs (node paths, values, etc.)

## Example
Show a typical usage scenario.
```

## run.py Conventions

```python
"""
Skill: My Skill Name
"""
from bridge.client import HoudiniClient


def run(h: HoudiniClient, **kwargs):
    """Entry point for the skill.

    Args:
        h: Connected HoudiniClient instance
        **kwargs: Skill-specific parameters
    """
    # 1. Observe — read current state
    # 2. Reason — decide what to do
    # 3. Act — make changes
    pass
```

## Guidelines

- **Self-contained**: A skill should work without manual setup beyond having the bridge running.
- **Composable**: Skills can call other skills or use the client directly.
- **Defensive**: Check node existence, validate inputs, handle errors gracefully.
- **Documented**: The skill.md should be clear enough that the agent knows when to use it without reading the code.
