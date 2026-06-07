# Portable Hermes skill: search

This directory is a repository copy of the local Hermes `search` skill used for Valuehire AI Search work.

To install it on another computer:

```bash
mkdir -p ~/.hermes/skills/productivity/search
cp -R skills/search/* ~/.hermes/skills/productivity/search/
```

Then start Hermes and load the skill as `search`.

Notes:
- Secrets are not included. Create `.env.local` separately on the target computer.
- The local `.env.local` is intentionally ignored by Git.
