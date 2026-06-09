# Session Closeout

When the user indicates the current task is complete or the session is ending, update these three files before stopping:

## 1. README.md

Overwrite with a concise project README covering:
- What the project does (1-2 sentences)
- How to set up and run (dashboard, CLI)
- Key files and their purpose
- Any recent additions or structural changes

## 2. log.md

Append a new entry at the bottom:

```markdown
## 2026-06-08

<bullet-point summary of what was accomplished this session>
```

Keep each entry brief (3-8 bullets). Do not rewrite history.

## 3. prompt.md

Overwrite with a comprehensive resume prompt for a new opencode session. Include:
- Project path and how to start the dashboard
- Current pipeline order and button layout
- Summary of the config UI layout (fieldsets, columns)
- What each action button does
- Key files with their roles
- API endpoints
- Recent decisions or in-progress work
- Any known issues or blockers

This is the single file someone opening a fresh opencode window should read first to continue work without asking questions.

## 4. Push to GitHub

After updating all three files, commit and push:

```bash
git add -A && git commit -m "chore: update session closeout files" && git push
```

If the push fails with HTTP 400, increase the git buffer:

```bash
git -c http.postBuffer=524288000 push
```

The remote URL is `https://github.com/dvartany/hpc-agent-workflow.git` (no embedded token).

---

If the user didn't do anything meaningful (just browsed, asked questions, etc.), skip updating all three files and the git push.
