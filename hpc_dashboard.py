#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from hpc_agent import load_config, queue_summary, PHASE_FILE


# -- Paths -------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.toml"
EXAMPLE_CONFIG_PATH = BASE_DIR / "config.example.toml"
STATIC_DIR = BASE_DIR / "dashboard"
RUN_LOG_PATH = BASE_DIR / "dashboard-run.log"


# -- Managed subprocess wrapper --------------------------

class ManagedProcess:
    """Encapsulates a long-running subprocess with state, start, and stop."""

    def __init__(self, label: str):
        self.label = label
        self._proc: subprocess.Popen[str] | None = None

    @property
    def state(self) -> dict[str, Any]:
        if self._proc is None:
            return {"running": False, "returncode": None}
        rc = self._proc.poll()
        return {"running": rc is None, "returncode": rc, "pid": self._proc.pid}

    def start(self, cmd: list[str]) -> dict[str, Any]:
        if self._proc is not None and self._proc.poll() is None:
            return {"ok": False, "message": f"{self.label} already running."}
        log_fh = RUN_LOG_PATH.open("a", encoding="utf-8")
        log_fh.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting {self.label}: {' '.join(cmd)}\n")
        log_fh.flush()
        self._proc = subprocess.Popen(cmd, cwd=BASE_DIR, text=True, stdout=log_fh, stderr=subprocess.STDOUT)
        return {"ok": True, "message": f"{self.label} started."}

    def stop(self) -> dict[str, Any]:
        if self._proc is None or self._proc.poll() is not None:
            return {"ok": True, "message": f"No {self.label} running."}
        self._proc.send_signal(signal.SIGTERM)
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        return {"ok": True, "message": f"{self.label} stopped."}


MONITOR = ManagedProcess("monitor")
ANALYSIS = ManagedProcess("analysis")
PREPROCESS = ManagedProcess("pre-process")


def log_to_status(msg: str) -> None:
    try:
        log_path = status_log_file(config_snapshot())
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] {msg}\n")
    except Exception:
        pass


def agent_cmd(*args: str) -> list[str]:
    return [sys.executable, str(BASE_DIR / "hpc_agent.py"), "--config", str(CONFIG_PATH), *args]


# -- File helpers ----------------------------------------

def ensure_config() -> None:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default


def tail_lines(path: Path, count: int = 80) -> list[str]:
    return read_text(path).splitlines()[-count:]


# -- Config read / write ---------------------------------

def write_config(data: dict[str, Any]) -> None:
    """Serialize config dict back to TOML-ish config.toml."""
    sections = ["cluster", "job", "sync", "analysis", "reporting", "preprocess", "jobs"]
    lines: list[str] = []
    # Top-level restart flag
    restart = data.get("restart", False)
    lines.append(f"restart = {'true' if restart else 'false'}")
    lines.append("")
    for section in sections:
        lines.append(f"[{section}]")
        for key, value in data.get(section, {}).items():
            if value == "" or value is None:
                continue
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, int):
                rendered = str(value)
            else:
                rendered = json.dumps(str(value))
            lines.append(f"{key} = {rendered}")
        lines.append("")
    CONFIG_PATH.write_text("\n".join(lines), encoding="utf-8")


def config_snapshot() -> dict[str, Any]:
    """Return a safe snapshot of config.toml with defaults for missing keys."""
    ensure_config()
    config = load_config(CONFIG_PATH)
    config.setdefault("cluster", {}).setdefault("remote_script_path", "")
    config.setdefault("job", {}).setdefault("script", "job.sh")
    config["job"].setdefault("job_id_file", ".hpc_agent_job_id")
    config.setdefault("analysis", {})
    config["analysis"].setdefault("mode", "local")
    config["analysis"].setdefault("slurm_script", "analysis_job.sh")
    config["analysis"].setdefault("python_script", "parfile_restart.py")
    config["analysis"].setdefault("job_id_file", ".hpc_agent_analysis_job_id")
    return {
        "cluster": config.get("cluster", {}),
        "job": config.get("job", {}),
        "sync": config.get("sync", {}),
        "analysis": config.get("analysis", {}),
        "reporting": config.get("reporting", {}),
        "preprocess": config.get("preprocess", {}),
        "jobs": config.get("jobs", {}),
        "restart": config.get("restart", False),
    }


def job_id_file(config: dict[str, Any]) -> Path:
    val = config.get("job", {}).get("job_id_file") or ".hpc_agent_job_id"
    return BASE_DIR / val


def status_log_file(config: dict[str, Any]) -> Path:
    val = config.get("reporting", {}).get("status_log") or "./hpc-agent-status.log"
    return BASE_DIR / val


# -- Dashboard state -------------------------------------

def app_state() -> dict[str, Any]:
    """Assemble the full state object returned to the frontend."""
    config = config_snapshot()
    status_file = status_log_file(config)
    job_id = read_text(job_id_file(config)).strip()
    all_lines = tail_lines(status_file, 120)
    latest_status = next((l for l in reversed(all_lines) if l.strip()), "")
    queue = {}
    try:
        queue = queue_summary(config)
    except Exception:
        pass
    current_phase = ""
    try:
        current_phase = PHASE_FILE.read_text().strip()
    except Exception:
        pass
    return {
        "config": config,
        "jobId": job_id,
        "latestStatus": latest_status,
        "queue": queue,
        "statusLog": tail_lines(status_file),
        "runLog": tail_lines(RUN_LOG_PATH, 60),
        "process": MONITOR.state,
        "analysisProcess": ANALYSIS.state,
        "preprocessProcess": PREPROCESS.state,
        "currentPhase": current_phase,
        "paths": {
            "config": str(CONFIG_PATH),
            "statusLog": str(status_file),
            "runLog": str(RUN_LOG_PATH),
        },
    }


# -- Agent actions ---------------------------------------

def run_agent(args: list[str], timeout: int = 60) -> dict[str, Any]:
    """Run hpc_agent.py synchronously and return the result."""
    result = subprocess.run(
        agent_cmd(*args),
        cwd=BASE_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# -- HTTP handler ----------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    """Serves the dashboard UI and JSON API endpoints."""

    MIME = {"css": "text/css; charset=utf-8", "js": "application/javascript; charset=utf-8"}

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/state":
            return self.send_json(app_state())
        if parsed.path == "/":
            return self.send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")

        path = (STATIC_DIR / parsed.path.lstrip("/")).resolve()
        if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.exists():
            return self.send_error(404)

        self.send_file(path, self.MIME.get(path.suffix[1:], "text/plain"))

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/api/config":
                write_config(payload)
                return self.send_json({"ok": True, "state": app_state()})
            if parsed.path == "/api/action":
                return self.handle_action(payload)
            self.send_error(404)
        except subprocess.TimeoutExpired:
            self.send_json({"ok": False, "message": "Command timed out."}, status=504)
        except Exception as exc:
            self.send_json({"ok": False, "message": str(exc)}, status=500)

    def handle_action(self, payload: dict[str, Any]) -> None:
        action = payload.get("action", "")
        job_id = str(payload.get("jobId") or "").strip() or None

        if action == "submit":
            result = run_agent(["submit"])
        elif action == "status":
            args = ["status"] + (["--job-id", job_id] if job_id else [])
            result = run_agent(args)
        elif action == "sync":
            result = run_agent(["sync"], timeout=300)
        elif action == "analyze":
            result = ANALYSIS.start(agent_cmd("analyze"))
        elif action == "preprocess":
            result = PREPROCESS.start(agent_cmd("preprocess"))
        elif action == "submit-analysis":
            result = run_agent(["submit-analysis"])
        elif action == "stop-analysis":
            try:
                r = run_agent(["cancel", "--analysis"])
                out = (r.get("stdout", "") or r.get("stderr", "")).strip()
            except Exception:
                out = ""
            result = ANALYSIS.stop()
            if out:
                result["message"] = out + "\n" + result.get("message", "")
            log_to_status("Analysis stopped.")
        elif action == "start-monitor":
            cmd = agent_cmd("run", *(["--job-id", job_id] if job_id else []))
            config_data = config_snapshot()
            if config_data.get("restart"):
                cmd.append("--restart")
            result = MONITOR.start(cmd)
        elif action == "stop-monitor":
            try:
                r = run_agent(["cancel"])
                out = (r.get("stdout", "") or r.get("stderr", "")).strip()
            except Exception:
                out = ""
            result = MONITOR.stop()
            if out:
                result["message"] = out + "\n" + result.get("message", "")
            log_to_status("Monitor stopped.")
            try:
                PHASE_FILE.unlink()
            except Exception:
                pass
        else:
            result = {"ok": False, "message": f"Unknown action: {action}"}

        result["state"] = app_state()
        self.send_json(result, status=200 if result.get("ok") else 400)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def free_port(port: int) -> None:
    """Kill any process listening on the given port (macOS/Linux)."""
    import shlex
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip():
            pids = result.stdout.strip().splitlines()
            subprocess.run(["kill", "-9", *pids], capture_output=True, timeout=5)
            time.sleep(0.5)
    except Exception:
        pass


def main() -> int:
    ensure_config()
    MONITOR.stop()
    ANALYSIS.stop()
    PREPROCESS.stop()
    port = int(os.environ.get("HPC_DASHBOARD_PORT", "8765"))
    free_port(port)
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"HPC dashboard running at {url}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        MONITOR.stop()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
