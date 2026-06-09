# HPC Agent Dashboard

Slurm workflow manager with a local web UI and CLI backend. Submit jobs, poll status, run preprocess/analysis pipelines, and sync results via SSH to Frontera (TACC).

By [David Vartanyan](https://github.com/dvartany)

```bash
python3 hpc_dashboard.py      # start dashboard at http://127.0.0.1:8765
python3 hpc_agent.py <cmd>    # run from CLI: submit, status, cancel, poll, sync, analyze, preprocess, run
```

## Key Files

| File | Purpose |
|------|---------|
| `hpc_agent.py` | Backend: submit, poll, cancel, preprocess, analyze, sync, CLI entry point |
| `hpc_dashboard.py` | HTTP server: API endpoints, ManagedProcess, static file serving |
| `dashboard/app.js` | Frontend: form read/write, HPC presets, job scripts, state polling, phase indicators, button dispatch |
| `dashboard/index.html` | UI layout — left (operations + 2x2 grid) + right (cluster, job scripts, logs) |
| `dashboard/styles.css` | Dashboard styling — CSS grid layout, dark mode, phase/button indicators |
| `config.toml` | Active config: cluster, job, sync, analysis, preprocess, reporting, jobs sections |

## Layout

- **Left column:** Operations (pipeline phases, 2x4 action buttons, command output) + 2x2 config grid (Pre-process, Job, Analysis, Results)
- **Right column:** Cluster settings + Job scripts list (dynamic add/remove) + Status Log / Run Log panels

## API Endpoints

- `GET /api/state` — full dashboard state (config, jobId, queue, logs, process states, currentPhase)
- `POST /api/config` — save config from form
- `POST /api/action` — run an action (body: `{"action": "<name>", "jobId": "<optional>"}`)

## Per-Script Subdirectory Mode

When `[jobs]` has entries (via the Job scripts list), each script runs its full pipeline in `<remote_workdir>/<script_stem>/`. Falls back to `job.script` with no subdir when `[jobs]` is empty.

## Recent Changes

- Preprocess auto-skips when no mode-specific script/command is configured
- Dashboard auto-frees port 8765 on startup (kills existing listener)
- Stop Analysis scancels the analysis job ID (saved on sbatch or parsed from Python script stdout)
- Remote Python scripts CD into `<remote_workdir>/<script_dir>` before execution
- All analysis/preprocess modes use managed background processes (not just submit)
- Command output streams latest run log lines while monitor/analysis is running
