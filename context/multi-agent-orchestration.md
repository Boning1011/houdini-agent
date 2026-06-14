<!-- houdini_version: 21.0 -->
# Multi-Agent Orchestration

Running several subagents in parallel against Houdini. Keep it thin — no harness, just the rule.

## The one rule

**One Houdini instance = one writer.** Never point multiple subagents at the same instance (same port).

The bridge serializes requests onto the main thread, so it won't crash — but all `/exec` calls share one global namespace and one undo stack, and the subagents fight over the same scene. You get silent variable clobbering and logical conflicts, not errors.

## The pattern that works

Give each subagent **its own headless instance on its own port**, then merge via files.

```
coordinator (you)
  ├─ start N headless instances: hython scripts/serve_headless.py --port 879x
  ├─ fan out N subagents in one message — each pinned to one port, each producing a file
  │     (HDA → .hda,  geometry → .bgeo,  staged scene → .hip)
  ├─ join: install/import each file into the main-scene instance, save the merged .hip
  └─ kill the instances you started (free licenses); never touch instances you didn't start
```

Parallelize work that exports to a file (HDAs, asset geometry, isolated subnets). Edits to one **live** scene stay serial — split into per-agent subnets, then merge.

## Two things that will bite you

- **Always pass `port=N` explicitly** to `HoudiniClient` in subagents. Auto-discovery only sees instances that registered, and may not see GUI Houdinis the user already has open — a subagent could grab the wrong one and edit a real project. Tell each subagent its port *and* that other ports are off-limits.
- Subagents inherit `context/` — point HDA-building agents at `hda-development.md`; they consume it the same way you do. **Name the one doc each subagent needs** (or say "no Houdini knowledge needed, skip context") — every doc a subagent reads is paid again in its own context, so a vague prompt that triggers a scan-all multiplies cost by the number of agents.
- **Model per subagent:** the `Agent` tool's `model` arg is set per call (defaults to inheriting the parent). Downgrade clear, mechanical work to a cheaper model; keep Opus for tasks that need real debugging/iteration — a weak model that thrashes can cost *more* total tokens than a strong one that gets it first try.
