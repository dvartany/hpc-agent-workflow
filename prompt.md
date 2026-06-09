# Resume Prompt

Resume HPC dashboard work at /Users/davidvartanyan/Documents/Codex/2026-06-03/i-d-like-to-have-an/outputs/hpc-agent-workflow/

Start the dashboard:
```bash
python3 hpc_dashboard.py
```
Open http://127.0.0.1:8765

## Current pipeline order and button layout

Start Monitor → Stop | Pre-process → Submit → Analyze → Stop Analysis | Sync → Queue
(8 buttons in a 2x4 grid)

| Button | Action |
|--------|--------|
| Start Monitor | Runs `hpc_agent.py run` — iterates over all job scripts, for each: preprocess → submit → poll → analyze → sync in its own subdir. Phase indicators light up via `.hpc_agent_phase`. Wrapped in try/finally. |
| Stop | Cancels Slurm job(s) via `scancel`, then kills MONITOR subprocess (SIGTERM → wait 5s → SIGKILL). Output includes cancel result. |
| Pre-process | Runs `hpc_agent.py preprocess` as managed background process. |
| Submit | Runs `hpc_agent.py submit` — submits all job scripts via sbatch, returns comma-separated job IDs. |
| Analyze | Runs `hpc_agent.py analyze` as managed background process (all modes, not just submit). |
| Stop Analysis | Cancels analysis Slurm job via `scancel --analysis`, then kills ANALYSIS subprocess. Output includes cancel result. |
| Sync | Runs `hpc_agent.py sync` — iterates over all job scripts, each in its subdir. |
| Queue | Runs `hpc_agent.py status` — squeue for configured user. |

## Config UI layout

**Left column:**
- Operations: pipeline indicators, Job ID input, 2x4 button grid, command output `<pre>`
- Config grid (2x2): Pre-process (mode + conditional fields), Job (script, poll seconds), Analysis (mode + conditional fields), Results (remote/local paths)

**Right column (flex column, gap: 0):**
- Cluster: HPC preset dropdown, host, user, remote workdir
- Job scripts: dynamic add/remove, stored as `jobs.script_N`
- Compact logs: Status Log + Run Log (fixed max-height: 175px on pre)

## Key files

| File | Role |
|------|------|
| `hpc_agent.py` | Backend — `run_preprocess` auto-skips when no mode-specific script configured; `_run_phase` for python mode parses stdout for "Submitted batch job X" and saves job ID via `save_job_id`; `_run_phase` for submit mode saves job ID after sbatch; CD into script's directory component for both python and submit modes |
| `hpc_dashboard.py` | HTTP server — `free_port()` kills existing listener on port 8765 before binding; all analyze/preprocess modes use ManagedProcess; stop-analysis captures cancel output like stop-monitor; `handle_action` dispatches actions |
| `dashboard/app.js` | Frontend — command output streams last 10 run log lines while monitor or analysis is running via `renderUI`; buttons dispatch to `action()` |
| `dashboard/index.html` | UI HTML — inline styled right column |
| `dashboard/styles.css` | Styling — `.workspace` grid, phase/button indicators |
| `config.toml` | Active config — cluster (frontera), job (batch.sub), preprocess (python, parfile_restart.py), analysis (python, opencode_automation/job_config.py), sync, reporting (poll 900s) |

## API endpoints

- **GET `/api/state`** — full state: config, jobId, latestStatus, queue, statusLog (120 lines), runLog (60 lines), process states, currentPhase
- **POST `/api/config`** — save config, returns updated state
- **POST `/api/action`** — action dispatch, returns `{ok, message, stdout, stderr, state}`

## Multi-script behavior

When `[jobs]` has entries, each script runs in `<remote_workdir>/<script_stem>/`. `poll()` handles comma-separated IDs. Falls back to single `job.script` with no subdir when `[jobs]` is empty.

## Session closeout

When concluding, update README.md, log.md, prompt.md, then commit and push. Use `git -c http.postBuffer=524288000 push` if HTTP 400 occurs (large PNGs in history). Remote is `https://github.com/dvartany/hpc-agent-workflow.git`.

## Known issues / blockers

- **No CSS fix for log alignment** — user reverted both flex-grow and grid-row approaches; logs remain in right column below job scripts with fixed max-height
- **SSH dependency** — dashboard talks to Frontera; sleep/reboot kills subprocesses
- **Phase file on SIGKILL** — `.hpc_agent_phase` not cleaned up on hard kill

## Task paused

User requested a Google Slide deck (motivate problem, summarize AI approach, pitfalls to avoid). Screenshot taken at `/tmp/dashboard_screenshot.png`. Python-pptx was installed but slide creation was not completed. To resume: write a Python script using python-pptx to generate the presentation, include the screenshot image, and add capability indicator bubbles.
