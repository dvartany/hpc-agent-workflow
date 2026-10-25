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

## 2026-06-09

- Fixed git push failure (HTTP 400) by setting `http.postBuffer=524288000` for large PNG history
- Added step 4 to AGENTS.md: commit and push to GitHub on session closeout

## 2026-06-10

- Created `create_slides.py` — generates single-slide PPTX with dashboard screenshot
- Iterated slide design through multiple rounds: screenshot on left, right column with motivation/process/challenges
- Settled on ASTRA acronym (Automated Scheduling & Tracking for Research Applications)
- Took fresh dashboard screenshot via Playwright headless Chromium (also used Desktop screenshot)
- Text format: 1-sentence summary per section + short bullet list, non-technical language
- Added "Stop babysitting individual batch jobs" closing line
- Added detailed dashboard caption below screenshot describing left/right panels
- Added Auto-restart feature: checkbox next to phase chain, `--restart` flag on `hpc_agent.py run`, top-level `restart = true/false` in config.toml, infinite pipeline loop until Stop

## 2026-10-25

- Adapted workflow to target Perlmutter (NERSC) in addition to Frontera (TACC)
- Set NERSC preset defaults: user `vartan`, workdir `/pscratch/sd/v/vartan/2023/F2F/9-3D-new`
- Switched active `config.toml` cluster to `perlmutter-p1.nersc.gov` / `vartan`
- Documented both cluster presets in README, prompt.md, RESUME.md
- Confirmed backend is host-agnostic (plain `ssh` + Slurm), so no code changes needed beyond preset/config
- Added `{hpc}`/`{project}` placeholders to `sync.local_results_path`; expanded by `local_results_path()` in `hpc_agent.py`
- Active save path now `results/{hpc}/{project}` → `results/perlmutter/9-3D-new`
- HPC preset dropdown now auto-selects from cluster host on load (Perlmutter → NERSC preset)
- Standalone Sync now sets `.hpc_agent_phase=sync`; UI lights the Sync phase and button immediately (optimistic) since sync can finish inside the 10s poll
- Verified real sync: `results/perlmutter/9-3D-new/entr_plotter` populated
- Rewrote `parfile_restart.py` for the dashboard: no hardcoded paths, cwd/workdir detection, parses Perlmutter shock-finder output, pure-stdlib (works on login-node Python 3.6), module fallback (`python/3.12-26.1.0`) for h5py/scipy, backup + atomic write, nonzero exit on failure
- Integration-tested on Perlmutter with a fake shock finder (Python 3.6 + module fallback + dry-run passed)
- Deployed to `/pscratch/sd/v/vartan/2023/F2F/9-3D-new/parfile_restart.py`; `preprocess.enabled = true`
- Added explicit `preprocess.shock_finder` path (UI field + config + agent `--shock-finder` wiring)
- NERSC preset is now the initially selected dropdown option (no Custom flash on load)
- Restored `config.toml` after a stale dashboard form wiped it to empty defaults
- Empty config now fills the NERSC preset in the form instead of showing Custom
- `write_config()` guard rejects an entirely empty cluster block when a host already exists (stops stale-tab wipes)
- Real Perlmutter preprocess succeeded: shock finder parsed, `flash.par.bak` written, 8 lines changed in `flash.par`
- Checked updated NERSC `shock_finder_v4.py` conservation output; fixed its undefined `maindir` (backup: `shock_finder_v4.py.bak.conservation`)
- Parser now reads `Prev Total Mass, New Total Mass`; conservation tolerance `1e-6` (observed `1.40e-07`), dry-run passes
- Dashboard main window now prints "Pre-process complete." (or failure) when the preprocess process finishes
- Removed the explicit `preprocess.shock_finder` field/config/wiring; `parfile_restart.py` auto-detects the script again
- `parfile_restart.py` is now idempotent: skips when `flash.par checkpointFileNumber` equals the latest checkpoint, so `iProcs`/interval scaling are not reapplied without a new simulation; `--force` overrides
- Changed values are logged (`old -> new`) and the prior line is kept as `# old: <line>`; dry-run reports parameter/line counts and latest checkpoint/plot mtimes
- Local fake-shock tests covered skip, force dry-run, force write, and re-run; real Perlmutter `--dry-run` (skip) and `--dry-run --force` (3 expected changes) passed; deployed to Perlmutter
- `iProcs` now read from the checkpoint's `integer runtime parameters` (via `h5dump`, h5py fallback) and written as `checkpoint iProcs - skip_num`; no fallback to the possibly-decremented `flash.par` value
- Verified on Perlmutter checkpoint 154: `iProcs 126 - skip_num 3 = 123`; local synthetic-HDF5 test also corrected `flash.par iProcs 120` to 123
- Dashboard restarted on http://127.0.0.1:8765 with Perlmutter config
