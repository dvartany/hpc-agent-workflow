# ASTRA — Automated Scheduling & Tracking for Research Applications

HPC job lifecycle management dashboard. Slurm workflow manager with a local web UI and CLI backend. Submit jobs, poll status, run preprocess/analysis pipelines, sync results, and auto-restart the pipeline — all via SSH to Frontera (TACC) or Perlmutter (NERSC) interchangeably.

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
| `parfile_restart.py` | Dashboard-friendly FLASH restart prep: runs `shock_finder_v4.py`, updates `flash.par` (backup + atomic write) |
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

## Clusters

The backend is host-agnostic (plain `ssh` + Slurm), so both clusters work with the same pipeline. Use the **HPC preset** dropdown to switch:

| Preset | Host | User | Remote workdir |
|--------|------|------|----------------|
| NERSC (Perlmutter) | `perlmutter-p1.nersc.gov` | `vartan` | `/pscratch/sd/v/vartan/2023/F2F/9-3D-new` |
| TACC (Frontera) | `frontera.tacc.utexas.edu` | `tg848932` | `/scratch2/05594/tg848932/2023/F2F/s17_new_mpi_decay` |

The active `config.toml` cluster is currently Perlmutter.

## Result save path

`sync.local_results_path` supports `{hpc}` and `{project}` placeholders. The default is
`results/{hpc}/{project}`, which expands to e.g. `results/perlmutter/9-3D-new` (or
`results/frontera/s17_new_mpi_decay`). `{hpc}` is derived from the host, `{project}` from the
basename of `cluster.remote_workdir`. With multiple job scripts, each script adds its stem as a
subdirectory (`results/perlmutter/9-3D-new/<script_stem>/`).

## Pre-processing (`parfile_restart.py`)

Runs on the login node as the first pipeline phase. From the remote workdir it:

1. Runs `shock_finder_v4.py` (auto-finds it; uses a module-loaded Python with `h5py`/`scipy` when the system `python3` lacks them).
2. Checks the `Prev Total Mass, New Total Mass` conservation line (relative tolerance `1e-6`, residual printed).
3. Updates `flash.par`: `restart`, latest checkpoint/plot numbers, `xmin`, `point_mass`, `iProcs`, `skip_num`, `do_move`, and interval scaling.
4. Backs up `flash.par.bak` and writes atomically. Exits nonzero on failure so the pipeline stops.

Useful flags: `--dry-run` (no write), `--shock-module`, `--shock-python`, `--shock-finder`. By default it auto-detects `shock_finder_v4.py` in the workdir; pass `--shock-finder` only to override. `parfile_restart.py` is deployed to the Perlmutter workdir and enabled in `config.toml`.
