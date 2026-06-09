# Session Log

## 2026-06-08

- Created `opencode.json` + `AGENTS.md` for persistent session instructions
- Set up automatic README.md, log.md, prompt.md update on session closeout
- Fixed job scripts disappearing on Queue action (save config before action)
- Wrapped Cluster + Job scripts in flex column (`gap: 0`) to remove gap
- Removed `margin-top` from `#jobsFieldset`
- Initialized `log.md` and `prompt.md` with current project state

## 2026-06-08

- Fixed action buttons: moved config save inside try/catch so errors display in output box instead of silent failure
- Added zombie process cleanup on dashboard start (MONITOR/ANALYSIS/PREPROCESS.stop() in main())
- Removed `enabled` gate from `_run_phase` and `sync_results` — preprocess/analysis/sync buttons always execute
- Added phase tracking via `.hpc_agent_phase` file: `set_phase`/`clear_phase` in agent, `currentPhase` in app_state, pipeline indicators light up during `run` command
- Updated HPC presets with TACC defaults (host, user tg848932, workdir), added custom preset
- Moved Status Log and Run Log from bottom section into compact panels in the right column
- Replaced box-drawing Unicode chars in comments with ASCII for Python 2 compatibility
- Discussed tmux on Frontera vs autossh vs pmset for SSH persistence across sleep/reboot

## 2026-06-09

- Wired up "Job scripts" UI — each script now submits via `sbatch`, `poll()` waits for all to complete
- Each job script runs in its own subdir (`<remote_workdir>/<script_stem>/`) for all pipeline phases
- Pre-process, Analyze, Sync buttons iterate per-script with subdir scoping (consistent with Start Monitor)
- Added `cancel_job()` — scancel on Stop / Stop Analysis before killing local process; `cancel` CLI command
- Fixed phase file cleanup: wrapped `run` loop in `try/finally` so `clear_phase()` always fires
- `_with_subdir()` also adjusts `sync.local_results_path` per script

## 2026-06-09 (afternoon)

- Fixed preprocess blocking pipeline: `run_preprocess` now auto-skips when no mode-specific script/command is configured
- Added `free_port()` to hpc_dashboard.py — kills existing listener on port 8765 before binding to prevent "address in use"
- Save analysis job ID in `_run_phase` submit mode so Stop Analysis can scancel it
- Python mode `_run_phase` parses stdout for "Submitted batch job X" and saves the job ID to analysis job ID file
- Remote Python scripts now CD into `<remote_workdir>/<script_dir>` (e.g., `python_script = "subdir/script.py"` → `cd <workdir>/subdir && python3 script.py`)
- Same CD treatment applied to submit mode's slurm_script path
- All analysis/preprocess modes now use managed background processes (not just submit), enabling Stop buttons during execution
- Command output window streams latest 10 run log lines every 10s while monitor or analysis is running
- Stop Analysis now captures and displays cancel command output in response (mirrors stop-monitor pattern)
- Reverted two CSS layout attempts for log positioning (user kept original inline flex column layout)
- Took dashboard screenshot for slide deck (task paused before completion)
