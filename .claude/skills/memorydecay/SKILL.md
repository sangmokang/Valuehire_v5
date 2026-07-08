---
name: memorydecay
description: Human-like memory with decay for Claude Code
---

# Memory System (memorydecay)

You have access to a human-like memory system that decays naturally over time. Important memories persist longer; trivial ones fade away.

## Session Start

At the start of each session, the memory system is automatically available. No action needed - the server starts on first use.

## Commands

```bash
# Search for relevant memories
memorydecay search "your query here" [--top-k 5]

# Store a memory (see Category Guide below for correct flags)
memorydecay store "memory content" --importance 0.8 --category decision --mtype fact

# Apply time-based decay (called automatically by hooks)
memorydecay tick

# Check server status
memorydecay server status

# Migrate existing memories from files
memorydecay migrate [--from ~/.claude/memory]
```

## Category Guide — ALWAYS match the right category

Every memory MUST use the correct `--category` flag. Do NOT default everything to `fact`.

| Category | `--category` | `--mtype` | Importance | When to use |
|----------|-------------|-----------|------------|-------------|
| **preference** | `preference` | `fact` | 0.8-1.0 | User's likes/dislikes, communication style, workflow habits, tool preferences |
| **decision** | `decision` | `fact` | 0.7-0.9 | Why something was done a certain way, tradeoffs, rejected alternatives |
| **fact** | `fact` | `fact` | 0.6-0.9 | Technical facts, API behaviors, architecture patterns, domain knowledge |
| **episode** | `episode` | `episode` | 0.3-0.6 | What was worked on, session summaries, transient context |

### Importance calibration

Importance directly controls how fast a memory decays. **Use the full range — not everything is 0.8.**

| Importance | Decay behavior | Examples |
|-----------|----------------|----------|
| **0.9-1.0** | Persists for hundreds of ticks | User's core identity/role, critical production constraints, "never do X" rules |
| **0.7-0.8** | Persists for ~100 ticks | Architectural decisions, API conventions, project-level patterns |
| **0.5-0.6** | Moderate lifespan | What was built this week, intermediate findings, session context |
| **0.3-0.4** | Fades quickly | Minor observations, temporary workarounds, one-off events |

**Rule of thumb:** If you'd want to recall this in 2 weeks, use 0.8+. If it's only relevant for a few sessions, use 0.5. If it's truly transient, use 0.3.

Store BEFORE context gets too long — don't wait until compaction.

## When to Search Memories

Always search before:
- Answering questions that might have been discussed before
- Making decisions that might have prior context
- Starting work on a topic that might have history

## Freshness Indicators

Search results include freshness:
- **FRESH** (>0.7): Recently recalled or high importance - reliable
- **NORMAL** (0.3-0.7): Moderate decay - probably accurate but verify if critical
- **STALE** (<0.3): Heavily decayed - may be outdated, use with caution

## Automatic Decay

Memories naturally fade over time based on:
- **Importance**: Higher = slower decay
- **Recalls**: Each recall strengthens the memory (testing effect)
- **Time**: Decay applies automatically via hooks on PreCompact and SessionEnd

You don't need to manually manage decay - the system handles it.

## Migration (One-Time)

If you have existing memories in `~/.claude/memory/` or `MEMORY.md`:

```bash
memorydecay migrate --from ~/.claude/memory
```

This imports them with appropriate importance levels based on file type.

## Proactive Storing Triggers

Do NOT wait to be asked. Store a memory when ANY of these happen:

- **User context** (preference, 0.8-1.0): User reveals role, expertise, preferences, corrects your approach, or communication style becomes clear
- **Decisions** (decision, 0.7-0.9): A technical choice is made with tradeoffs, an alternative is rejected with reasoning, a convention is established
- **Facts** (fact, 0.6-0.9): Non-obvious API behavior discovered, architecture details discussed, bug root cause identified
- **Episodes** (episode, 0.3-0.6): Feature/fix completed, debugging session concluded, session ends with meaningful work

**If you think "this would be useful to know next time" — store it NOW with the right category and importance.**

## Best Practices

1. **Search first, then decide**: Always check if relevant context exists
2. **Store proactively**: Don't wait to be asked — if something seems worth remembering, store it
3. **Calibrate importance honestly**: Use the full 0.3-1.0 range. Not everything is 0.8.
4. **Pick the right category**: Preference ≠ fact ≠ episode. Category affects decay rate.
5. **Respect freshness**: Stale memories might be outdated — verify before relying on them

## Troubleshooting

If `memorydecay` commands fail:
1. Check server status: `memorydecay server status`
2. Start manually if needed: `memorydecay server start`
3. Check memory-decay is installed: `pip show memory-decay`
