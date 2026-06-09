Resume HPC dashboard work at /Users/davidvartanyan/Documents/Codex/2026-06-03/i-d-like-to-have-an/outputs/hpc-agent-workflow/

Start the dashboard:
```bash
python3 hpc_dashboard.py
```
Open http://127.0.0.1:8765

## Current pipeline order
Pre-process → Submit → Analyze → Sync

## Button layout
Start Monitor, Stop, Submit, Queue, Pre-process, Analyze, Stop Analysis, Sync

## Config fieldsets (left panel, 2-col grid)
- Cluster (col 1): HPC preset dropdown + host/user/ssh_key/remote_workdir/remote_script_path
- Job (col 2): Script filename, Poll seconds
- Pre-processing (col 1): enabled toggle, mode select (local/submit/python), command/slurm_script/python_script
- Analysis (col 2): enabled toggle, mode select, command/slurm_script/python_script
- Results (col 2, below Analysis): enabled toggle, remote results, local results

## What "Start Monitor" does
1. run_preprocess(config) — runs pre-processing step
2. submit(config) — submits main job via sbatch
3. poll(config, job_id) — polls slurm every N seconds until done
4. run_analysis(config) — runs analysis step
5. sync_results(config) — rsyncs results back

## Key files
- `hpc_agent.py` — backend logic (submit, poll, preprocess, analyze, sync)
- `hpc_dashboard.py` — HTTP server with API and static file serving
- `dashboard/index.html` — UI layout
- `dashboard/app.js` — frontend logic (form, state rendering, actions)
- `dashboard/styles.css` — styling
- `config.toml` — active configuration
- `.hpc_agent_job_id` — stores last Slurm job ID

## API endpoints
- GET `/api/state` — full dashboard state (config, jobId, queue, logs, process states)
- POST `/api/config` — save config from form
- POST `/api/action` — run an action (submit, start-monitor, stop-monitor, sync, analyze, preprocess, status, stop-analysis)

## Status tracking
- Pipeline phases highlighted green when their subprocess is running
- Monitor process (`state.process.running`) highlights "Submit" phase
- Pre-process process (`state.preprocessProcess.running`) highlights "Pre-process" phase
- Analysis process (`state.analysisProcess.running`) highlights "Analyze" phase
- Buttons with `data-active` attribute show green background

## HPC presets
- NERSC: perlmutter-p1.nersc.gov, /global/homes/u/
- Polaris: polaris.alcf.anl.gov, /home/
- TACC: frontera.tacc.utexas.edu, /home1/
