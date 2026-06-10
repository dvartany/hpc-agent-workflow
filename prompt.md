# Resume Prompt

Resume HPC dashboard work at `/Users/davidvartanyan/Documents/Codex/2026-06-03/i-d-like-to-have-an/outputs/hpc-agent-workflow/`.

Start the dashboard:
```bash
python3 hpc_dashboard.py
```
Open http://127.0.0.1:8765

## Pipeline and button layout

| Button | Action |
|--------|--------|
| Start Monitor | Runs `hpc_agent.py run` (with `--restart` if checkbox checked) — iterates over all job scripts, for each: preprocess → submit → poll → analyze → sync in its own subdir. Wrapped in try/finally. |
| Stop | Cancels Slurm job(s) via `scancel`, then kills MONITOR subprocess (SIGTERM → wait 5s → SIGKILL). |
| Pre-process | Runs `hpc_agent.py preprocess` as managed background process. |
| Submit | Runs `hpc_agent.py submit` — submits all job scripts via sbatch, returns comma-separated job IDs. |
| Analyze | Runs `hpc_agent.py analyze` as managed background process (all modes). |
| Stop Analysis | Cancels analysis Slurm job via `scancel --analysis`, then kills ANALYSIS subprocess. |
| Sync | Runs `hpc_agent.py sync` — iterates over all job scripts, each in its subdir. |
| Queue | Runs `hpc_agent.py status` — squeue for configured user. |

## Config UI layout

**Left column:**
- Operations: phase chain (Pre-process → Submit → Analyze → Sync), **Restart checkbox** (inline, right-aligned), Job ID input, 2×4 button grid, command output `<pre>`
- Config grid (2×2): Pre-process (mode + conditional fields), Job (script, poll seconds), Analysis (mode + conditional fields), Results (remote/local paths)

**Right column (flex column, gap: 0):**
- Cluster: HPC preset dropdown, host, user, remote workdir
- Job scripts: dynamic add/remove, stored as `jobs.script_N`
- Compact logs: Status Log + Run Log (fixed max-height: 175px on pre)

## Auto-Restart

Checkbox "Restart" sits next to the Pre-process → Submit → Analyze → Sync phase chain. When checked and Start Monitor runs, `--restart` is passed to `hpc_agent.py run`. The pipeline loops: after all scripts complete analysis+sync, it logs "Auto-restart enabled; restarting pipeline" and loops back to preprocess indefinitely. Hit Stop to break the loop.

Config storage: `restart = true/false` is a top-level key in `config.toml`. The custom parser in `hpc_agent.py:load_config` now accepts top-level keys (keys before any `[section]` header). `write_config` in `hpc_dashboard.py` writes `restart` first, before the sections.

## Key files

| File | Role |
|------|------|
| `hpc_agent.py` | Backend — `run` subparser has `--restart` flag; `load_config` accepts top-level keys; pipeline wraps in `while True` when restart enabled |
| `hpc_dashboard.py` | HTTP server — `config_snapshot()` includes `restart`; `start-monitor` action appends `--restart` flag |
| `dashboard/app.js` | Frontend — `restart` in fields array, read/written as checkbox via `general` → now top-level |
| `dashboard/index.html` | UI — Restart checkbox in `.pipeline-status` div, right-aligned inline |
| `dashboard/styles.css` | Styling — `.restart-toggle` class: flex row, auto margin-left, compact checkbox |
| `config.toml` | Active config — `restart = false` at top, then sections |
| `create_slides.py` | Generates single-slide PPTX with screenshot left + motivation/process/challenges right |

## Slide deck

The generated `HPC_Agent_Slide_Deck.pptx` is a single slide:
- **Left:** dashboard screenshot (clean, no overlays)
- **Right:** 3 numbered sections — Motivation (manual HPC steps → human error), Process (one dashboard pipeline), Key Challenges (reproducibility, scalability, transparency, safety)
- **Header:** ASTRA (Automated Scheduling & Tracking for Research Applications)
- **Bottom:** GitHub URL
- Closing line: "Stop babysitting individual batch jobs — automate the pipeline and focus on interpreting results."

## API endpoints

- **GET `/api/state`** — full state: config, jobId, latestStatus, queue, statusLog (120 lines), runLog (60 lines), process states, currentPhase
- **POST `/api/config`** — save config, returns updated state
- **POST `/api/action`** — action dispatch, returns `{ok, message, stdout, stderr, state}`

## Multi-script behavior

When `[jobs]` has entries, each script runs in `<remote_workdir>/<script_stem>/`. `poll()` handles comma-separated IDs. Falls back to single `job.script` with no subdir when `[jobs]` is empty.

## Known issues / blockers

- **SSH dependency** — dashboard talks to Frontera; sleep/reboot kills subprocesses
- **Phase file on SIGKILL** — `.hpc_agent_phase` not cleaned up on hard kill
- **config.toml custom parser** — hand-rolled TOML parser does not support quoted strings with `#` or inline tables; use simple key = value only

## Session closeout

When concluding, update README.md, log.md, prompt.md, then commit and push. Use `git -c http.postBuffer=524288000 push` if HTTP 400 occurs (large PPTX/PNG in history). Remote is `https://github.com/dvartany/hpc-agent-workflow.git`.
