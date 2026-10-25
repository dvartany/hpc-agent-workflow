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
  * preserves existing inline comments instead of appending the old value on
    every auto-restart iteration,
  * writes ``flash.par`` atomically after making ``flash.par.bak``,
  * exits nonzero on failure so the dashboard stops the pipeline.
"""

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


KEY_RE = re.compile(r"^(\s*)([A-Za-z0-9_]+)(\s*=\s*)(.*)$")
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


def replace_value(line, new_value):
    # type: (str, str) -> str
    """Replace the value in a ``key = value`` line, keeping spacing + comment."""
    match = KEY_RE.match(line)
    if not match:
        return line
    lead, key, eq, rest = match.groups()
    newline = "\n" if line.endswith("\n") else ""
    value_part, comment = split_value_comment(rest.rstrip("\n"))
    leading_ws = value_part[: len(value_part) - len(value_part.lstrip())]
    trailing_ws = value_part[len(value_part.rstrip()) :]
    updated = "{}{}{}{}{}{}".format(lead, key, eq, leading_ws, new_value, trailing_ws)
    if comment:
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
    pattern = "{}hdf5_{}_*".format(basenm, kind)
    numbers = []  # type: List[int]
    for path in directory.glob(pattern):
        match = re.search(r"_(\d+)$", path.name)
        if match:
            numbers.append(int(match.group(1)))
    if not numbers:
        raise FileNotFoundError("No {} files found in {}.".format(pattern, directory))
    return max(numbers)


def format_number(value):
    # type: (float) -> str
    return "{:.15g}".format(value)


def rewrite_params(lines, params, shock, workdir):
    # type: (List[str], Dict[str, str], Dict[str, Any], Path) -> List[str]
    required = ["basenm", "output_directory", "iprocs", "xmin"]
    missing = [key for key in required if key not in params]
    if missing:
        raise RuntimeError("flash.par is missing required key(s): " + ", ".join(missing))

    basenm = params["basenm"]
    outdir = Path(params["output_directory"])
    if not outdir.is_absolute():
        outdir = workdir / outdir
    prev_iprocs = int(params["iprocs"])
    old_xmin = float(params["xmin"])

    prev_chk = latest_file_number(outdir, basenm, "chk")
    prev_plt = latest_file_number(outdir, basenm, "plt")

    skip_num = shock["skip_num"]
    if skip_num < 0:
        raise RuntimeError("Invalid skip_num: {}".format(skip_num))
    if skip_num > prev_iprocs:
        raise RuntimeError(
            "skip_num ({}) exceeds previous iProcs ({}).".format(skip_num, prev_iprocs)
        )

    xmin = shock["xmin_cm"]
    if skip_num > 0:
        if xmin is None:
            raise RuntimeError("skip_num > 0 but no new xmin is available.")
        if xmin <= 0:
            raise RuntimeError("Invalid new xmin: {}".format(xmin))
    elif xmin is None:
        xmin = old_xmin

    if old_xmin == 0:
        raise RuntimeError("flash.par xmin is zero; cannot rescale intervals.")
    interval_scale = (float(xmin) / old_xmin) * 1.3

    new_values = {
        "restart": ".true.",
        "checkpointfilenumber": str(prev_chk),
        "plotfilenumber": str(prev_plt + 1),
        "point_mass": format_number(shock["point_mass"]),
        "iprocs": str(prev_iprocs - skip_num),
        "do_move": ".true." if skip_num > 0 else ".false.",
        "skip_num": str(skip_num),
    }  # type: Dict[str, str]
    if skip_num > 0:
        new_values["xmin"] = format_number(float(xmin))

    for key in ("checkpointfileintervaltime", "plotfileintervaltime"):
        prev = float(params.get(key, "0") or 0)
        if prev != 0:
            new_values[key] = format_number(prev * interval_scale)

    for key in ("checkpointfileintervalstep", "plotfileintervalstep"):
        prev = int(float(params.get(key, "0") or 0))
        if prev != 0:
            new_values[key] = str(round(prev * interval_scale))

    updated = []  # type: List[str]
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            updated.append(line)
            continue
        match = KEY_RE.match(line)
        if not match:
            updated.append(line)
            continue
        key = match.group(2).lower()
        if key in new_values:
            updated.append(replace_value(line, new_values[key]))
        else:
            updated.append(line)
    return updated


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

    params, lines = read_param_lines(param_path)
    updated_lines = rewrite_params(lines, params, shock, workdir)

    changed = sum(1 for a, b in zip(lines, updated_lines) if a != b)
    print(
        "skip_num={} xmin={} point_mass={:.6e} iprocs={}".format(
            shock["skip_num"],
            "{:.6e}".format(shock["xmin_cm"])
            if shock["xmin_cm"] is not None
            else "n/a",
            shock["point_mass"],
            int(params["iprocs"]) - shock["skip_num"],
        )
    )

    if args.dry_run:
        print("dry run: {} line(s) would change; {} not modified.".format(changed, param_path))
        return 0

    if not args.no_backup:
        backup_path = param_path.with_name(param_path.name + ".bak")
        shutil.copy2(param_path, backup_path)
        print("backup: {}".format(backup_path))

    tmp_path = param_path.with_name(param_path.name + ".tmp")
    tmp_path.write_text("".join(updated_lines), encoding="utf-8")
    os.replace(tmp_path, param_path)
    print("updated: {} ({} line(s) changed)".format(param_path, changed))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("error: {}".format(exc), file=sys.stderr)
        raise SystemExit(1)
