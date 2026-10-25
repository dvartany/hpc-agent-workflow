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
| `parfile_restart.py` | Dashboard-friendly FLASH restart prep: parses `shock_finder_v4.py`, rewrites `flash.par` (backup + atomic), pure-stdlib so it runs on login-node `python3` 3.6 |
| `config.toml` | Active config — `restart = true` at top, then sections |
| `create_slides.py` | Generates single-slide PPTX with screenshot left + motivation/process/challenges right |

## Slide deck

The generated `HPC_Agent_Slide_Deck.pptx` is a single slide:
- **Left:** dashboard screenshot (clean, no overlays)
- **Right:** 3 numbered sections — Motivation (manual HPC steps → human error), Process (one dashboard pipeline), Key Challenges (reproducibility, scalability, transparency, safety)
- **Header:** ASTRA (Automated Scheduling & Tracking for Research Applications)
- **Bottom:** GitHub URL
- Closing line: "Stop babysitting individual batch jobs — automate the pipeline and focus on interpreting results."

## UI behaviors

- On load, the **HPC preset** dropdown starts on NERSC (the `<option>` is `selected`). If `cluster.host` is set, `writeForm()` maps it (perlmutter→nersc, frontera→tacc, polaris→polaris, otherwise Custom); if the config is empty, it fills the NERSC preset instead of leaving Custom.
- Actions POST the current form to `/api/config` first. `write_config()` now refuses to overwrite an existing host with an entirely empty `cluster` block (500 + "Refresh the dashboard…"), so a stale tab can no longer wipe the config. Reload the page after the server restarts.
- Polling is every 10s, so short actions can finish between polls. The Sync action optimistically lights the Sync phase/button immediately; the standalone `sync` CLI also writes `.hpc_agent_phase=sync` for the duration.

## Pre-processing script

`parfile_restart.py` replaces the old hardcoded version. It runs from `cluster.remote_workdir` (or its parent if placed in a subdir), finds `shock_finder_v4.py` automatically, and parses the Perlmutter output:

- `excise point cell, mass, point mass, total mass: <skip> <excised> <point> <total>`
- edge loop line `<index> <edge_km>` → new `xmin` in cm (`edge_km * 1e5`)

It rewrites `restart`, `checkpointFileNumber`, `plotFileNumber`, `xmin`, `point_mass`, `iProcs`, `do_move`, `skip_num`, and scales interval time/step by `(xmin/old_xmin)*1.3`. Existing inline comments are preserved; `flash.par.bak` is written and `flash.par` is replaced atomically. It exits nonzero on failure.

The login-node `python3` is 3.6 and lacks `h5py`/`scipy`; the script is 3.6-compatible and launches the shock finder via `module load python/3.12-26.1.0` when needed. Flags: `--dry-run`, `--workdir`, `--param-file`, `--shock-finder`, `--shock-python`, `--shock-module`. The dashboard does **not** pass a path: `parfile_restart.py` auto-detects `shock_finder_v4.py` in the workdir (`--shock-finder` is a manual CLI override). Deployed at the same workdir; `preprocess.enabled = true`.

## API endpoints

- **GET `/api/state`** — full state: config, jobId, latestStatus, queue, statusLog (120 lines), runLog (60 lines), process states, currentPhase
- **POST `/api/config`** — save config, returns updated state
- **POST `/api/action`** — action dispatch, returns `{ok, message, stdout, stderr, state}`

## Multi-script behavior

When `[jobs]` has entries, each script runs in `<remote_workdir>/<script_stem>/`. `poll()` handles comma-separated IDs. Falls back to single `job.script` with no subdir when `[jobs]` is empty.

## Known issues / blockers

- **SSH dependency** — dashboard talks to Frontera or Perlmutter; sleep/reboot kills subprocesses
- **2FA** — NERSC (Perlmutter) may require an SSH key + OTP; `BatchMode=yes` in `ssh_base()` fails without a working key
- **Phase file on SIGKILL** — `.hpc_agent_phase` not cleaned up on hard kill
- **Stale config writes** — mitigated by the empty-cluster guard; if `config.toml` is ever wiped, restore with `git checkout HEAD -- config.toml`
- **config.toml custom parser** — hand-rolled TOML parser does not support quoted strings with `#` or inline tables; use simple key = value only

## Recent success

- Real `parfile_restart.py` run on Perlmutter (2026-10-25) completed returncode 0: shock finder parsed `skip_num=3 xmin=8.392478e+07 point_mass=2.565207e+33 iprocs=123`, wrote `flash.par.bak`, and changed 8 lines in `flash.par`.

## Cluster targets

The backend is host-agnostic (`ssh` + `sbatch`/`squeue`/`scancel`), so switching clusters only changes the Cluster preset/fields.

| Preset | Host | User | Remote workdir |
|--------|------|------|----------------|
| NERSC (Perlmutter) | `perlmutter-p1.nersc.gov` | `vartan` | `/pscratch/sd/v/vartan/2023/F2F/9-3D-new` |
| TACC (Frontera) | `frontera.tacc.utexas.edu` | `tg848932` | `/scratch2/05594/tg848932/2023/F2F/s17_new_mpi_decay` |

Preset defaults live in `dashboard/app.js` (`HPC_PRESETS`). The active `config.toml` cluster is currently Perlmutter (`vartan@perlmutter-p1.nersc.gov`).

## Local results save path

`sync.local_results_path` is a template supporting `{hpc}` (derived from the host: perlmutter /
frontera / polaris) and `{project}` (basename of `cluster.remote_workdir`). Active value:
`results/{hpc}/{project}` → `results/perlmutter/9-3D-new` for the current config. Multi-script
runs append the script stem as a subdir via `_with_subdir()`; `local_results_path()` in
`hpc_agent.py` performs the expansion.

## Session closeout

When concluding, update README.md, log.md, prompt.md, then commit and push. Use `git -c http.postBuffer=524288000 push` if HTTP 400 occurs (large PPTX/PNG in history). Remote is `https://github.com/dvartany/hpc-agent-workflow.git`.
