#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import datetime as dt
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


# -- Constants -------------------------------------------

DONE_STATES = {
    "BOOT_FAIL", "CANCELLED", "COMPLETED", "DEADLINE",
    "FAILED", "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED", "TIMEOUT",
}
SUCCESS_STATES = {"COMPLETED"}
PHASE_FILE = Path(os.path.dirname(os.path.abspath(__file__))) / ".hpc_agent_phase"


def _sigterm_handler(signum: int, frame: object) -> None:
    clear_phase()
    sys.exit(0)


signal.signal(signal.SIGTERM, _sigterm_handler)


def set_phase(name: str) -> None:
    try:
        PHASE_FILE.write_text(name)
    except Exception:
        pass


def clear_phase() -> None:
    try:
        PHASE_FILE.unlink()
    except Exception:
        pass


# -- Config ----------------------------------------------

def load_config(path: Path) -> dict[str, Any]:
    config: dict[str, Any] = {}
    section: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = config.setdefault(line[1:-1].strip(), {})
            continue
        if "=" not in line:
            raise ValueError(f"Invalid config line: {raw_line}")
        key, val = (p.strip() for p in line.split("=", 1))
        if section is None:
            config[key] = parse_scalar(val)
        else:
            section[key] = parse_scalar(val)
    return config


def parse_scalar(value: str) -> Any:
    v = value.lower()
    if v == "true":
        return True
    if v == "false":
        return False
    if len(value) > 1 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


# -- Logging ---------------------------------------------

def timestamp() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log(config: dict[str, Any], message: str) -> None:
    line = f"[{timestamp()}] {message}"
    print(line, flush=True)
    log_path = config.get("reporting", {}).get("status_log")
    if log_path:
        Path(log_path).open("a", encoding="utf-8").write(line + "\n")


# -- SSH helpers -----------------------------------------

def ssh_target(config: dict[str, Any]) -> str:
    cluster = config["cluster"]
    user = cluster.get("user", "")
    host = cluster["host"]
    return f"{user}@{host}" if user else host


def ssh_base(config: dict[str, Any]) -> list[str]:
    cmd = ["ssh", "-o", "BatchMode=yes"]
    key = config["cluster"].get("ssh_key")
    if key:
        cmd.extend(["-i", os.path.expanduser(key)])
    cmd.append(ssh_target(config))
    return cmd


def run_local(cmd: list[str] | str, shell: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, shell=shell, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_remote(config: dict[str, Any], remote_cmd: str) -> subprocess.CompletedProcess[str]:
    return run_local(ssh_base(config) + [remote_cmd])


def remote_cd(config: dict[str, Any], command: str) -> str:
    return f"cd {shlex.quote(config['cluster']['remote_workdir'])} && {command}"


def script_path(config: dict[str, Any], name: str) -> str:
    base = config.get("cluster", {}).get("remote_script_path", "")
    return f"{base}/{name}".lstrip("/") if base else name


# -- Job ID helpers --------------------------------------

def job_id_path(config: dict[str, Any], section: str = "job", key: str = "job_id_file", default: str = ".hpc_agent_job_id") -> Path:
    return Path(config.get(section, {}).get(key, default))


def save_job_id(config: dict[str, Any], job_id: str, section: str = "job", key: str = "job_id_file", default: str = ".hpc_agent_job_id") -> None:
    job_id_path(config, section, key, default).write_text(job_id + "\n", encoding="utf-8")


def read_job_id(config: dict[str, Any], explicit: str | None = None, section: str = "job", key: str = "job_id_file", default: str = ".hpc_agent_job_id") -> str:
    if explicit:
        return explicit
    path = job_id_path(config, section, key, default)
    if not path.exists():
        raise RuntimeError(f"No job id supplied and {path} does not exist.")
    return path.read_text(encoding="utf-8").strip()


def parse_job_id(output: str) -> str:
    m = re.search(r"Submitted batch job\s+(\d+)", output)
    if not m:
        raise RuntimeError(f"Could not parse Slurm job id from sbatch output: {output!r}")
    return m.group(1)


# -- Slurm operations ------------------------------------

def get_job_scripts(config: dict[str, Any]) -> list[str]:
    cfg = config.get("jobs", {})
    scripts = [v for _, v in sorted(cfg.items()) if v]
    if scripts:
        return scripts
    single = config.get("job", {}).get("script")
    return [single] if single else []


def _script_subdir(script: str) -> str:
    return os.path.splitext(os.path.basename(script))[0]


def _with_subdir(config: dict[str, Any], subdir: str) -> dict[str, Any]:
    c = copy.deepcopy(config)
    base = c.get("cluster", {}).get("remote_workdir", "")
    c["cluster"]["remote_workdir"] = str(Path(base) / subdir)
    sync = c.get("sync", {})
    if sync.get("local_results_path"):
        sync["local_results_path"] = str(Path(sync["local_results_path"]) / subdir)
    return c


def submit(config: dict[str, Any], script: str | None = None) -> str:
    if script:
        scripts = [script]
    else:
        scripts = get_job_scripts(config)
    if not scripts:
        raise RuntimeError("No job scripts configured.")
    use_subdirs = bool(config.get("jobs", {}))
    job_ids: list[str] = []
    for s in scripts:
        if use_subdirs:
            subdir = _script_subdir(s)
            sc = _with_subdir(config, subdir)
        else:
            sc = config
            subdir = ""
        quoted = shlex.quote(script_path(sc, s))
        result = run_remote(sc, remote_cd(sc, f"sbatch {quoted}"))
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        jid = parse_job_id(result.stdout)
        job_ids.append(jid)
        log(config, f"Submitted {s}" + (f" (in {subdir}/)" if subdir else "") + f" -> job {jid}.")
    all_ids = ",".join(job_ids)
    save_job_id(config, all_ids)
    return all_ids


def submit_analysis(config: dict[str, Any]) -> str:
    script = config.get("analysis", {}).get("slurm_script")
    if not script:
        raise RuntimeError("analysis.slurm_script is empty.")
    result = run_remote(config, remote_cd(config, f"sbatch {shlex.quote(script_path(config, script))}"))
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    job_id = parse_job_id(result.stdout)
    save_job_id(config, job_id, section="analysis", key="job_id_file", default=".hpc_agent_analysis_job_id")
    log(config, f"Submitted analysis job {job_id}.")
    return job_id


def query_status(config: dict[str, Any], job_id: str) -> str:
    squeue_cmd = f"squeue -j {shlex.quote(job_id)} -h -o %T"
    result = run_remote(config, squeue_cmd)
    if result.returncode == 0:
        states = result.stdout.strip().splitlines()
        if states:
            return states[0].strip()
    sacct_cmd = f"sacct -j {shlex.quote(job_id)} --format=State --noheader --parsable2 | head -n 1"
    result = run_remote(config, sacct_cmd)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    states = result.stdout.strip().splitlines()
    return states[0].split("|")[0].strip() if states else "UNKNOWN"


def query_user_queue(config: dict[str, Any], username: str | None = None) -> str:
    user = username or config.get("cluster", {}).get("user")
    if not user:
        raise RuntimeError("No Slurm username supplied and cluster.user is empty.")
    result = run_remote(config, f"squeue -u {shlex.quote(user)}")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def queue_summary(config: dict[str, Any]) -> dict[str, int]:
    user = config.get("cluster", {}).get("user", "")
    if not user:
        return {}
    result = run_remote(config, f"squeue -u {shlex.quote(user)} -h -o %T")
    if result.returncode != 0:
        return {}
    counts: dict[str, int] = {}
    for line in result.stdout.strip().splitlines():
        state = line.strip()
        if state:
            counts[state] = counts.get(state, 0) + 1
    return counts


def cancel_job(config: dict[str, Any], job_ids_str: str) -> None:
    ids = [j.strip() for j in job_ids_str.replace(",", "\n").splitlines() if j.strip()]
    for jid in ids:
        result = run_remote(config, f"scancel {shlex.quote(jid)}")
        if result.returncode != 0:
            log(config, f"scancel {jid} failed: {result.stderr.strip()}")
        else:
            log(config, f"Cancelled job {jid}.")


def poll(config: dict[str, Any], job_ids_str: str, label: str = "Job") -> str:
    ids = [j.strip() for j in job_ids_str.replace(",", "\n").splitlines() if j.strip()]
    if not ids:
        raise RuntimeError("No job IDs to poll.")
    interval = int(config.get("reporting", {}).get("poll_interval_seconds", 900))
    remaining: set[str] = set(ids)
    last_states: dict[str, str | None] = {}
    final_states: dict[str, str] = {}
    while remaining:
        for jid in list(remaining):
            state = query_status(config, jid)
            if state != last_states.get(jid):
                log(config, f"{label} {jid} status: {state}.")
            else:
                log(config, f"{label} {jid} still {state}.")
            last_states[jid] = state
            if state in DONE_STATES:
                remaining.discard(jid)
                final_states[jid] = state
        if remaining:
            time.sleep(interval)
    if len(ids) == 1:
        return final_states[ids[0]]
    non_success = [s for s in final_states.values() if s not in SUCCESS_STATES]
    return non_success[0] if non_success else "COMPLETED"


# -- Results sync ----------------------------------------

def sync_results(config: dict[str, Any]) -> None:
    sync = config.get("sync", {})
    local_path = Path(sync["local_results_path"])
    local_path.mkdir(parents=True, exist_ok=True)
    remote_path = sync["remote_results_path"]
    workdir = config.get("cluster", {}).get("remote_workdir", "")
    if remote_path and not remote_path.startswith("/"):
        remote_path = f"{workdir}/{remote_path}"
    remote = f"{ssh_target(config)}:{remote_path}"
    cmd = ["rsync", "-az", "--progress"]
    key = config["cluster"].get("ssh_key")
    if key:
        cmd.extend(["-e", f"ssh -i {os.path.expanduser(key)} -o BatchMode=yes"])
    cmd.extend([remote, str(local_path)])
    result = run_local(cmd)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    log(config, f"Synced results to {local_path}.")


# -- Pipeline phases (preprocess / analysis) -------------

def _run_phase(config: dict[str, Any], section: str, label: str) -> None:
    """Run a pipeline phase dispatching by mode: local, python, or submit."""
    cfg = config.get(section, {})
    mode = cfg.get("mode", "local")

    if mode == "python":
        script = cfg.get("python_script")
        if script:
            script_dir = os.path.dirname(script)
            script_name = os.path.basename(script)
            workdir = config["cluster"]["remote_workdir"]
            if script_dir:
                full_dir = str(Path(workdir) / script_dir)
            else:
                full_dir = workdir
            remote_cmd = f"cd {shlex.quote(full_dir)} && python3 {shlex.quote(script_name)}"
        else:
            remote_cmd = cfg.get("command")
            if remote_cmd:
                remote_cmd = remote_cd(config, remote_cmd)
        if not remote_cmd:
            raise RuntimeError(f"{section}.python_script (or fallback command) is empty.")
        log(config, f"Running remote Python {label.lower()}: {remote_cmd}")
        result = run_remote(config, remote_cmd)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        if result.stdout:
            print(result.stdout, end="")
            m = re.search(r"Submitted batch job\s+(\d+)", result.stdout)
            if m:
                save_job_id(config, m.group(1), section=section, key="job_id_file")
        log(config, f"Remote Python {label.lower()} completed.")
        return

    if mode == "submit":
        script = cfg.get("slurm_script")
        if not script:
            raise RuntimeError(f"{section}.slurm_script is empty.")
        script_dir = os.path.dirname(script)
        script_name = os.path.basename(script)
        workdir = config["cluster"]["remote_workdir"]
        full_dir = str(Path(workdir) / script_dir) if script_dir else workdir
        remote_cmd = f"cd {shlex.quote(full_dir)} && sbatch {shlex.quote(script_name)}"
        result = run_remote(config, remote_cmd)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        job_id = parse_job_id(result.stdout)
        log(config, f"Submitted {label.lower()} job {job_id}.")
        save_job_id(config, job_id, section=section, key="job_id_file")
        state = poll(config, job_id, label=label)
        if state not in SUCCESS_STATES:
            raise RuntimeError(f"{label} job {job_id} ended with state {state}.")
        log(config, f"{label} job {job_id} completed.")
        return

    if mode != "local":
        raise RuntimeError(f"Unknown {section}.mode: {mode}")

    command = cfg["command"]
    result = run_local(command, shell=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    log(config, f"{label} completed.")


def run_preprocess(config: dict[str, Any]) -> None:
    cfg = config.get("preprocess", {})
    mode = cfg.get("mode", "local")
    has_content = bool(
        cfg.get("python_script") or cfg.get("command") or cfg.get("slurm_script")
    )
    if not has_content:
        log(config, "Pre-processing disabled (no script configured).")
        return
    _run_phase(config, "preprocess", "Pre-processing")


def run_analysis(config: dict[str, Any]) -> None:
    _run_phase(config, "analysis", "Analysis")


# -- CLI -------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Submit, monitor, sync, and analyze an HPC Slurm job.")
    parser.add_argument("--config", default="config.toml", help="Path to TOML config.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("submit")
    c = sub.add_parser("cancel")
    c.add_argument("--job-id")
    c.add_argument("--analysis", action="store_true", help="Cancel analysis job instead of main job.")
    sp = sub.add_parser("status")
    sp.add_argument("--job-id")
    sp.add_argument("--user", help="Show squeue for this Slurm user. Defaults to cluster.user.")
    pp = sub.add_parser("poll")
    pp.add_argument("--job-id")
    ap = sub.add_parser("poll-analysis")
    ap.add_argument("--job-id")
    r = sub.add_parser("run")
    r.add_argument("--restart", action="store_true", help="Auto-restart pipeline on completion")
    sub.add_parser("sync")
    sub.add_parser("analyze")
    sub.add_parser("preprocess")
    sub.add_parser("submit-analysis")

    args = parser.parse_args()
    config = load_config(Path(args.config))

    try:
        if args.command == "submit":
            submit(config)
        elif args.command == "cancel":
            try:
                if args.analysis:
                    job_id = read_job_id(config, section="analysis", key="job_id_file", default=".hpc_agent_analysis_job_id")
                else:
                    job_id = read_job_id(config, args.job_id)
                cancel_job(config, job_id)
            except RuntimeError as exc:
                log(config, f"Cancel skipped ({exc}).")
        elif args.command == "status":
            if args.job_id:
                print(query_status(config, args.job_id))
            else:
                print(query_user_queue(config, args.user), end="")
        elif args.command == "poll":
            job_id = read_job_id(config, args.job_id)
            state = poll(config, job_id)
            if state in SUCCESS_STATES:
                run_analysis(config)
                sync_results(config)
            else:
                log(config, f"Job {job_id} ended with state {state}; skipping analysis.")
                return 1
        elif args.command == "poll-analysis":
            job_id = read_job_id(config, args.job_id, section="analysis", key="job_id_file", default=".hpc_agent_analysis_job_id")
            state = poll(config, job_id, label="Analysis job")
            if state not in SUCCESS_STATES:
                log(config, f"Analysis job {job_id} ended with state {state}.")
                return 1
            log(config, f"Analysis job {job_id} completed.")
        elif args.command == "run":
            scripts = get_job_scripts(config)
            if not scripts:
                log(config, "No job scripts configured.")
                return 1
            use_subdirs = bool(config.get("jobs", {}))
            restart = getattr(args, "restart", False)
            overall_ok = True
            try:
                while True:
                    for script in scripts:
                        try:
                            if use_subdirs:
                                subdir = _script_subdir(script)
                                sc = _with_subdir(config, subdir)
                                log(config, f"--- Running pipeline for {script} in {subdir}/ ---")
                            else:
                                sc = config
                                log(config, f"--- Running pipeline for {script} ---")
                            set_phase("preprocess")
                            run_preprocess(sc)
                            set_phase("submit")
                            job_id = submit(sc, script=script)
                            set_phase("monitor")
                            state = poll(sc, job_id)
                            if state in SUCCESS_STATES:
                                set_phase("analysis")
                                run_analysis(sc)
                                set_phase("sync")
                                sync_results(sc)
                                log(config, f"Pipeline completed for {script}.")
                            else:
                                log(config, f"Job for {script} ended with {state}; skipping analysis/sync.")
                                overall_ok = False
                        except Exception as exc:
                            log(config, f"Pipeline failed for {script}: {exc}")
                            overall_ok = False
                    if not restart:
                        break
                    log(config, "--- Auto-restart enabled; restarting pipeline ---")
            finally:
                clear_phase()
            return 0 if overall_ok else 1
        elif args.command == "sync":
            scripts = get_job_scripts(config)
            if not scripts:
                log(config, "No job scripts configured.")
                return 1
            use_subdirs = bool(config.get("jobs", {}))
            for script in scripts:
                subdir = _script_subdir(script) if use_subdirs else ""
                sc = _with_subdir(config, subdir) if use_subdirs else config
                log(config, f"Syncing results for {script}" + (f" (in {subdir}/)" if subdir else "") + ".")
                sync_results(sc)
        elif args.command == "analyze":
            scripts = get_job_scripts(config)
            if not scripts:
                log(config, "No job scripts configured.")
                return 1
            use_subdirs = bool(config.get("jobs", {}))
            for script in scripts:
                subdir = _script_subdir(script) if use_subdirs else ""
                sc = _with_subdir(config, subdir) if use_subdirs else config
                log(config, f"Analyzing for {script}" + (f" (in {subdir}/)" if subdir else "") + ".")
                run_analysis(sc)
        elif args.command == "preprocess":
            scripts = get_job_scripts(config)
            if not scripts:
                log(config, "No job scripts configured.")
                return 1
            use_subdirs = bool(config.get("jobs", {}))
            for script in scripts:
                subdir = _script_subdir(script) if use_subdirs else ""
                sc = _with_subdir(config, subdir) if use_subdirs else config
                log(config, f"Pre-processing for {script}" + (f" (in {subdir}/)" if subdir else "") + ".")
                run_preprocess(sc)
        elif args.command == "submit-analysis":
            submit_analysis(config)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
