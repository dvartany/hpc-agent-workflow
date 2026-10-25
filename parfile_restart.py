#!/usr/bin/env python3
"""Rewrite FLASH restart parameters for an automated pipeline run.

This is a dashboard-friendly rewrite of ``parfile_restart.py``. It is meant to
be run on the HPC login node by the ASTRA pre-processing step:

    cd <remote_workdir> && python3 parfile_restart.py

It has no hardcoded cluster paths. The simulation directory is taken from
``--workdir``, ``$HPC_WORKDIR`` / ``$HPC_REMOTE_WORKDIR``, or the current
directory (walking up one level if run from a subdirectory such as
``opencode_automation/``).

It expects the usual FLASH restart inputs in that directory:
  * ``flash.par``
  * ``dvolume_3d_angles.npy``
  * ``ccsn3d.dat``
  * a ``shock_finder_v4.py`` (in the workdir, its parent, or ``F2F_shared/``)
  * the latest checkpoint/plot files under ``output_directory``

The script itself only needs the Python standard library, so it runs with the
login node's system ``python3``. The shock finder needs ``h5py`` and ``scipy``;
if the current interpreter lacks them, the finder is launched under a
module-loaded Python (default ``python/3.12-26.1.0``, override with
``--shock-module`` or ``$SHOCK_PYTHON_MODULE``).

Unlike the original, this version:
  * parses the shock-finder output actually produced on Perlmutter,
  * recomputes iProcs and interval values from the checkpoint's runtime
    parameters, so repeated pre-process runs are idempotent,
  * appends the replaced value inline as a ``#<old>`` comment instead of
    creating extra history lines, and preserves existing inline comments,
  * removes legacy ``# old:`` lines left by earlier versions,
  * writes ``flash.par`` atomically after making ``flash.par.bak``,
  * exits nonzero on failure so the dashboard stops the pipeline.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


KEY_RE = re.compile(r"^(\s*)([A-Za-z0-9_]+)(\s*=\s*)(.*)$")
LEGACY_OLD_RE = re.compile(r"^\s*# old: ")
DEFAULT_SHOCK_MODULE = "python/3.12-26.1.0"
MASS_CONSERVATION_RTOL = 1.0e-6


def split_value_comment(rest):
    # type: (str) -> Tuple[str, str]
    """Split a value from its inline comment, respecting single/double quotes."""
    quote = ""
    for i, ch in enumerate(rest):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#":
            return rest[:i], rest[i:]
    return rest, ""


def parse_value(raw):
    # type: (str) -> str
    value, _ = split_value_comment(raw)
    return value.strip().strip("'\"")


def replace_value(line, new_value, old_value=None):
    # type: (str, str, Optional[str]) -> str
    """Replace the value in a ``key = value`` line, keeping spacing + comment.

    When ``old_value`` is given, it is appended to the same line as a trailing
    comment (for example ``iProcs =  123 #126``).
    """
    match = KEY_RE.match(line)
    if not match:
        return line
    lead, key, eq, rest = match.groups()
    newline = "\n" if line.endswith("\n") else ""
    value_part, comment = split_value_comment(rest.rstrip("\n"))
    leading_ws = value_part[: len(value_part) - len(value_part.lstrip())]
    trailing_ws = value_part[len(value_part.rstrip()) :]
    updated = "{}{}{}{}{}{}".format(lead, key, eq, leading_ws, new_value, trailing_ws)
    if old_value is not None:
        if not trailing_ws:
            updated += " "
        updated += "#" + old_value
        if comment:
            updated += " " + comment
    elif comment:
        if not trailing_ws:
            updated += " "
        updated += comment
    return updated + newline


def find_workdir(explicit):
    # type: (Optional[str]) -> Path
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("HPC_WORKDIR") or os.environ.get("HPC_REMOTE_WORKDIR")
    if env:
        return Path(env).expanduser().resolve()
    cwd = Path.cwd()
    if (cwd / "flash.par").is_file():
        return cwd
    if (cwd.parent / "flash.par").is_file():
        return cwd.parent
    return cwd


def find_shock_finder(workdir, override):
    # type: (Path, Optional[str]) -> Path
    candidates = []  # type: List[Path]
    if override:
        candidates.append(Path(override).expanduser())
    env = os.environ.get("SHOCK_FINDER")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.extend(
        [
            workdir / "shock_finder_v4.py",
            workdir / "opencode_automation" / "shock_finder_v4.py",
            workdir / "F2F_shared" / "shock_finder_v4.py",
            workdir.parent / "shock_finder_v4.py",
            workdir.parent / "F2F_shared" / "shock_finder_v4.py",
            Path.home() / "F2F_shared" / "shock_finder_v4.py",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    tried = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError("Could not find shock_finder_v4.py. Tried:\n  " + tried)


def can_import(python, modules, workdir):
    # type: (str, List[str], Path) -> bool
    code = "import " + ", ".join(modules)
    try:
        result = subprocess.run(
            [python, "-c", code],
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=60,
        )
    except Exception:
        return False
    return result.returncode == 0


def build_shock_command(script, workdir, args):
    # type: (Path, Path, argparse.Namespace) -> List[str]
    explicit = args.shock_python or os.environ.get("SHOCK_PYTHON")
    if explicit:
        return [explicit, str(script)]

    if can_import(sys.executable, ["h5py", "scipy"], workdir):
        return [sys.executable, str(script)]

    module = (
        args.shock_module
        or os.environ.get("SHOCK_PYTHON_MODULE")
        or DEFAULT_SHOCK_MODULE
    )
    probe = [
        "bash",
        "-lc",
        "module load {} && python3 -c 'import h5py, scipy'".format(module),
    ]
    probe_result = subprocess.run(
        probe,
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=120,
    )
    if probe_result.returncode != 0:
        detail = (probe_result.stderr or probe_result.stdout).strip()
        raise RuntimeError(
            "shock_finder_v4.py needs h5py and scipy, which are missing from "
            "'{}', and 'module load {}' did not provide them. "
            "Set --shock-python or $SHOCK_PYTHON_MODULE. Details: {}".format(
                sys.executable, module, detail
            )
        )

    shell_cmd = "cd {workdir} && module load {module} && exec python3 {script}".format(
        workdir=shlex.quote(str(workdir)),
        module=module,
        script=shlex.quote(str(script)),
    )
    return ["bash", "-lc", shell_cmd]


def build_python_code_command(code, workdir, args, modules, argument):
    # type: (str, Path, argparse.Namespace, List[str], str) -> List[str]
    explicit = args.shock_python or os.environ.get("SHOCK_PYTHON")
    if explicit:
        return [explicit, "-c", code, argument]
    if can_import(sys.executable, modules, workdir):
        return [sys.executable, "-c", code, argument]

    module = (
        args.shock_module
        or os.environ.get("SHOCK_PYTHON_MODULE")
        or DEFAULT_SHOCK_MODULE
    )
    shell_cmd = (
        "cd {workdir} && module load {module} && "
        "exec python3 -c {code} {argument}".format(
            workdir=shlex.quote(str(workdir)),
            module=module,
            code=shlex.quote(code),
            argument=shlex.quote(argument),
        )
    )
    return ["bash", "-lc", shell_cmd]


def checkpoint_params(path, workdir, args):
    # type: (Path, Path, argparse.Namespace) -> Optional[Dict[str, Any]]
    """Read FLASH runtime parameters that were used to write the checkpoint."""
    names = [
        "iprocs",
        "xmin",
        "checkpointfileintervaltime",
        "plotfileintervaltime",
        "checkpointfileintervalstep",
        "plotfileintervalstep",
    ]
    h5dump = shutil.which("h5dump")
    if h5dump:
        try:
            result = subprocess.run(
                [
                    h5dump,
                    "-d",
                    "integer runtime parameters",
                    "-d",
                    "real runtime parameters",
                    str(path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=300,
            )
        except Exception:
            result = None
        if result is not None and result.returncode == 0:
            values = {}  # type: Dict[str, str]
            for match in re.finditer(r'"([^"]+)"\s*,\s*([-+0-9.eE]+)', result.stdout):
                name = match.group(1).strip().lower()
                if name in names:
                    values[name] = match.group(2)
            if "iprocs" in values and "xmin" in values:
                return {
                    "iprocs": int(float(values["iprocs"])),
                    "xmin": float(values["xmin"]),
                    "checkpointfileintervaltime": float(
                        values.get("checkpointfileintervaltime", "0") or 0
                    ),
                    "plotfileintervaltime": float(
                        values.get("plotfileintervaltime", "0") or 0
                    ),
                    "checkpointfileintervalstep": int(
                        float(values.get("checkpointfileintervalstep", "0") or 0)
                    ),
                    "plotfileintervalstep": int(
                        float(values.get("plotfileintervalstep", "0") or 0)
                    ),
                }

    code = (
        "import json, sys\n"
        "import h5py\n"
        "names = set({!r})\n"
        "result = {{}}\n"
        "with h5py.File(sys.argv[1], 'r') as handle:\n"
        "    for dataset in ('integer runtime parameters', 'real runtime parameters'):\n"
        "        for row in handle[dataset][:]:\n"
        "            name = row['name']\n"
        "            if isinstance(name, bytes):\n"
        "                name = name.decode('ascii', 'ignore')\n"
        "            name = name.strip().lower()\n"
        "            if name in names:\n"
        "                value = row['value']\n"
        "                result[name] = value.item() if hasattr(value, 'item') else value\n"
        "print(json.dumps(result))\n"
    ).format(names)
    cmd = build_python_code_command(code, workdir, args, ["h5py"], str(path))
    try:
        result = subprocess.run(
            cmd,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=300,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"\{.*\}", result.stdout, re.DOTALL)
    if not match:
        return None
    try:
        values = json.loads(match.group(0))
    except ValueError:
        return None
    if "iprocs" not in values or "xmin" not in values:
        return None
    return {
        "iprocs": int(float(values["iprocs"])),
        "xmin": float(values["xmin"]),
        "checkpointfileintervaltime": float(
            values.get("checkpointfileintervaltime", 0) or 0
        ),
        "plotfileintervaltime": float(values.get("plotfileintervaltime", 0) or 0),
        "checkpointfileintervalstep": int(
            float(values.get("checkpointfileintervalstep", 0) or 0)
        ),
        "plotfileintervalstep": int(
            float(values.get("plotfileintervalstep", 0) or 0)
        ),
    }


def run_shock_finder(script, workdir, args):
    # type: (Path, Path, argparse.Namespace) -> str
    cmd = build_shock_command(script, workdir, args)
    result = subprocess.run(
        cmd,
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError("shock_finder_v4.py failed: {}".format(detail))
    if not result.stdout.strip():
        raise RuntimeError("shock_finder_v4.py produced no output.")
    return result.stdout


def parse_shock_output(text):
    # type: (str) -> Dict[str, Any]
    """Parse the values printed by the Perlmutter shock_finder_v4.py.

    Relevant line:
      excise point cell, mass, point mass, total mass: <skip> <excised> <point> <total>

    The new xmin is printed by the edge loop as ``<index> <edge_km>``.
    """
    skip_num = None  # type: Optional[int]
    point_mass = None  # type: Optional[float]
    total_mass = None  # type: Optional[float]
    excised_mass = None  # type: Optional[float]
    xmin_km = None  # type: Optional[float]

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if "excise point cell" in line and ":" in line:
            tail = line.split(":", 1)[1].split()
            if len(tail) >= 4:
                skip_num = int(float(tail[0]))
                excised_mass = float(tail[1])
                point_mass = float(tail[2])
                total_mass = float(tail[3])

        # Edge loop print: "<i> <edge in km>"
        if xmin_km is None:
            match = re.fullmatch(r"(\d+)\s+([0-9.eE+\-]+)", line)
            if match:
                xmin_km = float(match.group(2))

    # Current Perlmutter format prints both labels before the values:
    #   Prev Total Mass, New Total Mass   :  <prev> <new>
    prev_total = None  # type: Optional[float]
    new_total = None  # type: Optional[float]
    match = re.search(
        r"prev\w*\s+total\s+mass\s*,\s*new\s+total\s+mass\s*:\s*"
        r"([0-9.eE+\-]+)\s+([0-9.eE+\-]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        # Older/Frontera shock-finder variants print the previous and new totals.
        match = re.search(
            r"prev\w*\s+total\s+mass.*?([0-9.eE+\-]+).*?new\s+total\s+mass.*?([0-9.eE+\-]+)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
    if match:
        prev_total, new_total = float(match.group(1)), float(match.group(2))

    if skip_num is None:
        raise RuntimeError(
            "Could not parse 'excise point cell ...' from shock finder output."
        )
    if point_mass is None:
        raise RuntimeError("Could not parse point_mass from shock finder output.")
    if skip_num > 0 and xmin_km is None:
        raise RuntimeError(
            "Shock finder did not report a new xmin (edge loop printed nothing)."
        )

    return {
        "skip_num": skip_num,
        "xmin_cm": xmin_km * 1.0e5 if xmin_km is not None else None,
        "point_mass": point_mass,
        "excised_mass": excised_mass,
        "total_mass": total_mass,
        "prev_total": prev_total,
        "new_total": new_total,
        "raw": text,
    }


def read_param_lines(path):
    # type: (Path) -> Tuple[Dict[str, str], List[str]]
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    params = {}  # type: Dict[str, str]
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = KEY_RE.match(line)
        if not match:
            continue
        key = match.group(2).lower()
        params[key] = parse_value(match.group(4))
    return params, lines


def latest_file_number(directory, basenm, kind):
    # type: (Path, str, str) -> int
    return latest_file_info(directory, basenm, kind)["number"]


def latest_file_info(directory, basenm, kind):
    # type: (Path, str, str) -> Dict[str, Any]
    pattern = "{}hdf5_{}_*".format(basenm, kind)
    candidates = []  # type: List[Tuple[int, Path]]
    for path in directory.glob(pattern):
        match = re.search(r"_(\d+)$", path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    if not candidates:
        raise FileNotFoundError("No {} files found in {}.".format(pattern, directory))
    number, path = max(candidates, key=lambda item: item[0])
    stat = path.stat()
    return {
        "number": number,
        "path": path,
        "name": path.name,
        "mtime": stat.st_mtime,
        "size": stat.st_size,
    }


def format_number(value):
    # type: (float) -> str
    return "{:.15g}".format(value)


def rewrite_params(
    lines, params, shock, workdir, prev_chk=None, prev_plt=None, chk_params=None
):
    # type: (List[str], Dict[str, str], Dict[str, Any], Path, Optional[int], Optional[int], Optional[Dict[str, Any]]) -> Dict[str, Any]
    required = ["basenm", "output_directory", "iprocs", "xmin"]
    missing = [key for key in required if key not in params]
    if missing:
        raise RuntimeError("flash.par is missing required key(s): " + ", ".join(missing))

    basenm = params["basenm"]
    outdir = Path(params["output_directory"])
    if not outdir.is_absolute():
        outdir = workdir / outdir
    if chk_params is None:
        raise RuntimeError(
            "Checkpoint runtime parameters are required to compute the new "
            "values; refusing to use flash.par."
        )
    removed_old_lines = sum(1 for line in lines if LEGACY_OLD_RE.match(line))
    if removed_old_lines:
        lines = [line for line in lines if not LEGACY_OLD_RE.match(line)]
    chk_iprocs = int(chk_params["iprocs"])
    chk_xmin = float(chk_params["xmin"])
    chk_chk_interval = float(chk_params.get("checkpointfileintervaltime", 0) or 0)
    chk_plt_interval = float(chk_params.get("plotfileintervaltime", 0) or 0)
    chk_chk_step = int(chk_params.get("checkpointfileintervalstep", 0) or 0)
    chk_plt_step = int(chk_params.get("plotfileintervalstep", 0) or 0)

    if prev_chk is None:
        prev_chk = latest_file_number(outdir, basenm, "chk")
    if prev_plt is None:
        prev_plt = latest_file_number(outdir, basenm, "plt")

    skip_num = shock["skip_num"]
    if skip_num < 0:
        raise RuntimeError("Invalid skip_num: {}".format(skip_num))
    if skip_num > chk_iprocs:
        raise RuntimeError(
            "skip_num ({}) exceeds checkpoint iProcs ({}).".format(
                skip_num, chk_iprocs
            )
        )

    xmin = shock["xmin_cm"]
    if skip_num > 0:
        if xmin is None:
            raise RuntimeError("skip_num > 0 but no new xmin is available.")
        if xmin <= 0:
            raise RuntimeError("Invalid new xmin: {}".format(xmin))
    elif xmin is None:
        xmin = chk_xmin

    if chk_xmin == 0:
        raise RuntimeError("checkpoint xmin is zero; cannot rescale intervals.")
    interval_scale = (float(xmin) / chk_xmin) * 1.3

    new_values = {
        "restart": ".true.",
        "checkpointfilenumber": str(prev_chk),
        "plotfilenumber": str(prev_plt + 1),
        "point_mass": format_number(shock["point_mass"]),
        "iprocs": str(chk_iprocs - skip_num),
        "do_move": ".true." if skip_num > 0 else ".false.",
        "skip_num": str(skip_num),
        "xmin": format_number(float(xmin)),
    }  # type: Dict[str, str]

    if chk_chk_interval != 0:
        new_values["checkpointfileintervaltime"] = format_number(
            chk_chk_interval * interval_scale
        )
    if chk_plt_interval != 0:
        new_values["plotfileintervaltime"] = format_number(
            chk_plt_interval * interval_scale
        )
    if chk_chk_step != 0:
        new_values["checkpointfileintervalstep"] = str(
            round(chk_chk_step * interval_scale)
        )
    if chk_plt_step != 0:
        new_values["plotfileintervalstep"] = str(
            round(chk_plt_step * interval_scale)
        )

    updated = []  # type: List[str]
    changes = []  # type: List[Dict[str, str]]
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            updated.append(line)
            continue
        match = KEY_RE.match(line)
        if not match:
            updated.append(line)
            continue
        key = match.group(2).lower()
        if key not in new_values:
            updated.append(line)
            continue
        old_value = params.get(key, parse_value(match.group(4)))
        new_value = new_values[key]
        if old_value == new_value:
            updated.append(line)
            continue
        updated.append(replace_value(line, new_value, old_value))
        changes.append(
            {
                "key": key,
                "name": match.group(2),
                "old": old_value,
                "new": new_value,
            }
        )
    return {
        "lines": updated,
        "changes": changes,
        "new_values": new_values,
        "prev_chk": prev_chk,
        "prev_plt": prev_plt,
        "chk_params": chk_params,
        "removed_old_lines": removed_old_lines,
        "interval_scale": interval_scale,
    }


def main():
    # type: () -> int
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workdir", help="Simulation directory (default: cwd).")
    parser.add_argument("--param-file", default="flash.par", help="FLASH parameter file.")
    parser.add_argument("--shock-finder", help="Path to shock_finder_v4.py.")
    parser.add_argument(
        "--shock-python", help="Python interpreter to run shock_finder_v4.py."
    )
    parser.add_argument(
        "--shock-module",
        help="Module to load for the shock finder (default: {}).".format(
            DEFAULT_SHOCK_MODULE
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print changes without writing."
    )
    parser.add_argument(
        "--no-backup", action="store_true", help="Do not create flash.par.bak."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Retained for compatibility; the rewrite is now idempotent, so "
            "this flag is not needed."
        ),
    )
    args = parser.parse_args()

    workdir = find_workdir(args.workdir)
    param_path = Path(args.param_file)
    if not param_path.is_absolute():
        param_path = workdir / param_path

    print("workdir: {}".format(workdir))
    if not param_path.is_file():
        raise FileNotFoundError("Parameter file not found: {}".format(param_path))

    required_files = ["dvolume_3d_angles.npy", "ccsn3d.dat"]
    missing_files = [name for name in required_files if not (workdir / name).is_file()]
    if missing_files:
        raise FileNotFoundError(
            "Missing required input file(s) in {}: {}".format(
                workdir, ", ".join(missing_files)
            )
        )

    params, lines = read_param_lines(param_path)
    required_keys = ["basenm", "output_directory", "iprocs", "xmin"]
    missing_keys = [key for key in required_keys if key not in params]
    if missing_keys:
        raise RuntimeError(
            "flash.par is missing required key(s): " + ", ".join(missing_keys)
        )

    basenm = params["basenm"]
    outdir = Path(params["output_directory"])
    if not outdir.is_absolute():
        outdir = workdir / outdir
    latest_chk = latest_file_info(outdir, basenm, "chk")
    latest_plt = latest_file_info(outdir, basenm, "plt")
    current_chk = None
    current_chk_raw = params.get("checkpointfilenumber")
    if current_chk_raw is not None:
        try:
            current_chk = int(float(current_chk_raw))
        except ValueError:
            current_chk = None

    print("parameter file: {}".format(param_path))
    print(
        "latest checkpoint: {} (#{}, mtime {})".format(
            latest_chk["name"],
            latest_chk["number"],
            time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(latest_chk["mtime"])),
        )
    )
    print(
        "latest plot: {} (#{}, mtime {})".format(
            latest_plt["name"],
            latest_plt["number"],
            time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(latest_plt["mtime"])),
        )
    )
    print(
        "flash.par checkpointFileNumber: {}".format(
            current_chk if current_chk is not None else "not set"
        )
    )

    skip = current_chk is not None and current_chk == latest_chk["number"]
    if skip:
        print(
            "flash.par checkpointFileNumber already matches the latest "
            "checkpoint; recomputing the deterministic target values."
        )

    chk_params = checkpoint_params(latest_chk["path"], workdir, args)
    if chk_params is None:
        raise RuntimeError(
            "Could not read runtime parameters from checkpoint {}. Refusing "
            "to update flash.par; set --shock-python to a Python with h5py or "
            "ensure h5dump is available.".format(latest_chk["name"])
        )
    print(
        "checkpoint params: iProcs={} xmin={:.6e} "
        "checkpointFileIntervalTime={} plotFileIntervalTime={}".format(
            chk_params["iprocs"],
            chk_params["xmin"],
            chk_params["checkpointfileintervaltime"],
            chk_params["plotfileintervaltime"],
        )
    )

    shock_script = find_shock_finder(workdir, args.shock_finder)
    print("shock finder: {}".format(shock_script))
    shock_output = run_shock_finder(shock_script, workdir, args)
    shock = parse_shock_output(shock_output)

    if shock["prev_total"] is not None and shock["new_total"] is not None:
        prev_total = float(shock["prev_total"])
        new_total = float(shock["new_total"])
        rel_err = abs(prev_total - new_total) / abs(prev_total) if prev_total else 0.0
        if rel_err > MASS_CONSERVATION_RTOL:
            raise RuntimeError(
                "Total mass not conserved: prev={:.6e} new={:.6e} rel_err={:.2e}".format(
                    prev_total, new_total, rel_err
                )
            )
        if rel_err > 1.0e-10:
            print(
                "mass conservation: OK ({:.6e}, rel err {:.2e})".format(
                    new_total, rel_err
                )
            )
        else:
            print("mass conservation: OK ({:.6e})".format(new_total))
    elif shock["total_mass"] is not None:
        print(
            "mass conservation: not reported by shock finder "
            "(new total {:.6e})".format(shock["total_mass"])
        )

    result = rewrite_params(
        lines,
        params,
        shock,
        workdir,
        prev_chk=latest_chk["number"],
        prev_plt=latest_plt["number"],
        chk_params=chk_params,
    )
    updated_lines = result["lines"]
    changes = result["changes"]
    removed_old_lines = result["removed_old_lines"]
    changed_lines = len(changes) + removed_old_lines

    print(
        "iProcs: checkpoint {} - skip_num {} = {}".format(
            chk_params["iprocs"],
            shock["skip_num"],
            chk_params["iprocs"] - shock["skip_num"],
        )
    )
    print("interval scale: {:.6f}".format(result["interval_scale"]))

    print(
        "shock result: skip_num={} xmin={} point_mass={:.6e} iprocs={}".format(
            shock["skip_num"],
            "{:.6e}".format(shock["xmin_cm"])
            if shock["xmin_cm"] is not None
            else "n/a",
            shock["point_mass"],
            result["new_values"]["iprocs"],
        )
    )
    if changes:
        print("changes (old value appended in-line as '#old'):")
        for change in changes:
            print(
                "  {}: {} -> {}".format(
                    change["name"], change["old"], change["new"]
                )
            )
    else:
        print("no parameter values changed.")
    if removed_old_lines:
        print("removed {} legacy '# old:' line(s).".format(removed_old_lines))

    if args.dry_run:
        print(
            "dry run: {} parameter(s), {} line(s) would change; "
            "{} not modified.".format(len(changes), changed_lines, param_path)
        )
        return 0

    if not changes and not removed_old_lines:
        print("no updates needed; {} unchanged.".format(param_path))
        return 0

    if not args.no_backup:
        backup_path = param_path.with_name(param_path.name + ".bak")
        shutil.copy2(param_path, backup_path)
        print("backup: {}".format(backup_path))

    tmp_path = param_path.with_name(param_path.name + ".tmp")
    tmp_path.write_text("".join(updated_lines), encoding="utf-8")
    os.replace(tmp_path, param_path)
    print(
        "updated: {} ({} parameter(s), {} line(s) added/updated)".format(
            param_path, len(changes), changed_lines
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("error: {}".format(exc), file=sys.stderr)
        raise SystemExit(1)
