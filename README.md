# ASTRA — Automated Scheduling & Tracking for Research Applications

HPC job lifecycle management dashboard. Slurm workflow manager with a local web UI and CLI backend. Submit jobs, poll status, run preprocess/analysis pipelines, sync results, and auto-restart the pipeline — all via SSH to Frontera (TACC).

```bash
python3 hpc_dashboard.py          # start dashboard at http://127.0.0.1:8765
python3 hpc_agent.py <command>    # CLI: submit, status, cancel, poll, sync, analyze, run
```

## Key Files

| File | Purpose |
|------|---------|
| `hpc_agent.py` | Backend engine: submit, poll, cancel, preprocess, analyze, sync, run (with `--restart`) |
| `hpc_dashboard.py` | HTTP server: `/api/state`, `/api/config`, `/api/action` endpoints, ManagedProcess wrapper |
| `dashboard/app.js` | Frontend: form read/write, HPC presets, job scripts, state polling, phase indicators |
| `dashboard/index.html` | UI layout — left (operations + 2x2 config) + right (cluster, job scripts, logs) |
| `dashboard/styles.css` | Styling — grid layout, dark mode, phase/button indicators, restart toggle |
| `config.toml` | Active config — `restart`, cluster, job, sync, analysis, preprocess, reporting |
| `create_slides.py` | Generates single-slide PPTX with screenshot + motivation/process/challenges |

## Layout

- **Left column:** Pipeline phase chain (Pre-process → Submit → Analyze → Sync) with Restart checkbox, 2×4 action buttons, command output, config grid (2×2)
- **Right column:** Cluster settings, dynamic job scripts list, Status Log + Run Log panels

## API Endpoints

- `GET /api/state` — full dashboard state
- `POST /api/config` — save config from form
- `POST /api/action` — dispatch action (body: `{"action": "<name>", "jobId": "<optional>"}`)

## Auto-Restart

When the Restart checkbox is checked, `hpc_agent.py run --restart` loops the pipeline indefinitely: preprocess → submit → poll → analyze → sync → [restart]. Hit Stop to break the loop.
