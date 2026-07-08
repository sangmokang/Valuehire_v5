# Project Claude Skills

This repository vendors Claude Code project-local skills under `.claude/skills/`.

On another PC, `git pull` is enough for Claude Code to see these skills when it is opened from this repository root. No copy into `~/.claude/skills` is required for repo work.

Use this check after pulling:

```bash
make claude-skills-check
```

Machine-local Claude files such as `.claude/settings.local.json`, scheduled-task locks, and `.omc/` runtime state must stay untracked.
