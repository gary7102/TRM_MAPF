#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 3: run pypibt on prepared instances and collect P_raw (wait/collision heatmaps).

Assumed project layout (defaults can be overridden by CLI args):
- external/pypibt/app.py
- data/maps/<map_name>.map
- data/instances/<map_name>.map/instance_XXXXX.scen
- data/instances_manifest.jsonl
Outputs:
- runs/pypibt/<instance_id>/output.txt (+ stdout/stderr logs)
- data/p_raw/<map_name>.map/instance_XXXXX.npz (+ meta.json)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

# local imports
# (When running from project root, "src" should be importable. We also add it defensively.)
_THIS = Path(__file__).resolve()
_PROJ = _THIS.parents[1]
sys.path.insert(0, str(_PROJ / "src"))

from praw.parse_paths import parse_output_txt  # noqa: E402
from praw.stats_wait_collision import (
    read_movingai_map,
    compute_wait_collision_heatmaps,
    summarize_run_metrics,
)  # noqa: E402


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _to_proj_abs(p: Path) -> Path:
    return p if p.is_absolute() else (_PROJ / p).resolve()

def _run_cmd(
    cmd: List[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_s: Optional[int],
    env: Optional[Dict[str, str]] = None,
) -> int:
    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        proc = subprocess.run(cmd, cwd=str(cwd), stdout=out, stderr=err, timeout=timeout_s, env=env)
    return int(proc.returncode)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=str, default="data/instances/trap-32-32.map/instances_manifest.jsonl")
    ap.add_argument("--maps_root", type=str, default="data/maps")
    ap.add_argument("--pypibt_app", type=str, default="external/pypibt/app.py")
    ap.add_argument("--python", type=str, default=sys.executable, help="Python executable to run pypibt (default: current).")
    ap.add_argument("--runs_dir", type=str, default="runs/pypibt/trap-32-32.map")
    ap.add_argument("--out_dir", type=str, default="data/p_raw")
    ap.add_argument("--timeout", type=int, default=120, help="Per-instance solver timeout (seconds).")
    ap.add_argument("--max_instances", type=int, default=0, help="0 means no limit.")
    ap.add_argument("--only_ids", type=str, default="", help="Comma-separated instance_ids to run, e.g. '0,1,2'.")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs.")
    ap.add_argument("--dry_run", action="store_true")
    ap.add_argument("--use_uv", action="store_true", help="Run pypibt using 'uv run' in its directory.")
    args = ap.parse_args()

    manifest_path = _to_proj_abs(Path(args.manifest))
    maps_root = _to_proj_abs(Path(args.maps_root))
    pypibt_app = _to_proj_abs(Path(args.pypibt_app))
    runs_dir = _to_proj_abs(Path(args.runs_dir))
    out_dir = _to_proj_abs(Path(args.out_dir))


    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    if not pypibt_app.exists():
        raise FileNotFoundError(f"pypibt app not found: {pypibt_app}")
    _ensure_dir(runs_dir)
    _ensure_dir(out_dir)

    only_ids: Optional[set[int]] = None
    if args.only_ids.strip():
        only_ids = {int(x) for x in args.only_ids.split(",") if x.strip()}

    n_done = 0
    for entry in _read_jsonl(manifest_path):
        instance_id = int(entry["instance_id"])
        if only_ids is not None and instance_id not in only_ids:
            continue

        instance_file = Path(entry["instance_file"])
        map_name = entry.get("map_filter") or Path(entry.get("map_file", "")).name
        if not map_name:
            # fallback: infer from instance_file path .../<map_name>/instance_xxx.scen
            map_name = instance_file.parent.name

        num_agents = int(entry["num_agents"])
        starts = entry.get("starts")
        goals = entry.get("goals")
        if goals is None:
            raise ValueError(f"manifest entry missing goals for instance_id={instance_id}")

        map_path = maps_root / map_name
        if not map_path.exists():
            raise FileNotFoundError(f"map file not found: {map_path}")

        run_dir = runs_dir / f"{instance_id:05d}"
        _ensure_dir(run_dir)
        out_txt = run_dir / "output.txt"
        stdout_log = run_dir / "stdout.log"
        stderr_log = run_dir / "stderr.log"

        out_npz_dir = out_dir / map_name
        _ensure_dir(out_npz_dir)
        out_npz = out_npz_dir / f"instance_{instance_id:05d}.npz"
        out_meta = out_npz_dir / f"instance_{instance_id:05d}.meta.json"

        if out_npz.exists() and out_meta.exists() and not args.overwrite:
            print(f"[skip] instance {instance_id:05d} already has outputs")
            n_done += 1
            if args.max_instances and n_done >= args.max_instances:
                break
            continue

        instance_file = _to_proj_abs(Path(entry["instance_file"]))
        map_path = maps_root / map_name
        pypibt_app_abs = pypibt_app
        map_path_abs = map_path.resolve()
        instance_file_abs = instance_file.resolve()

        env = None
        if args.use_uv:
            # Run inside the pypibt directory so uv picks up the environment
            run_cwd = pypibt_app_abs.parent
            cmd = [
                "uv", "run", "python", pypibt_app_abs.name,
                "-m", str(map_path_abs),
                "-i", str(instance_file_abs),
                "-N", str(num_agents),
                "-o", str(out_txt.resolve()),
            ]
            env = os.environ.copy()
            env.pop("VIRTUAL_ENV", None)
        else:
            run_cwd = run_dir
            cmd = [
                args.python,
                str(pypibt_app_abs),
                "-m", str(map_path_abs),
                "-i", str(instance_file_abs),
                "-N", str(num_agents),
                "-o", "output.txt",
            ]

        print(f"[run] {instance_id:05d} cmd={' '.join(cmd)}")
        if args.dry_run:
            continue

        if args.overwrite:
            if out_txt.exists():
                out_txt.unlink()

        t0 = time.time()
        try:
            rc = _run_cmd(cmd, cwd=run_cwd, stdout_path=stdout_log, stderr_path=stderr_log, timeout_s=args.timeout, env=env)
        except subprocess.TimeoutExpired:
            rc = 124
        t1 = time.time()
        runtime_s = float(t1 - t0)

        if rc != 0:
            print(f"[warn] instance {instance_id:05d} solver returned rc={rc}. still try to parse if output exists.")

        if not out_txt.exists():
            # Some versions may write to cwd/output.txt; we already ran in run_dir, so expect here.
            raise RuntimeError(
                f"pypibt did not produce output.txt at {out_txt}. "
                f"Check logs: {stdout_log} / {stderr_log}"
            )

        # Parse solution paths from output.txt
        try:
            parsed = parse_output_txt(out_txt, expected_num_agents=num_agents)
        except ValueError as e:
            print(f"[error] Failed to parse output.txt: {e}")
            if stdout_log.exists():
                print(f"--- stdout.log ---\n{stdout_log.read_text(errors='replace')}\n------------------")
            if stderr_log.exists():
                print(f"--- stderr.log ---\n{stderr_log.read_text(errors='replace')}\n------------------")
            raise

        # Read map to get H/W and obstacle mask (useful for sanity checks / later visualization)
        grid, H, W, obstacles = read_movingai_map(map_path)

        # Compute heatmaps (wait_map includes goal-camping exclusion)
        # stats_wait_collision expects time-major paths: paths[t][agent] == (x,y)
        wait_map, collision_map, occupancy_map, details = compute_wait_collision_heatmaps(
            paths=parsed["positions_by_t"],
            goals=[tuple(g) for g in goals],
            H=H,
            W=W,
            obstacles=obstacles,
        )

        # Summarize and determine solved flag
        metrics = summarize_run_metrics(
            # paths=parsed["paths"],
            paths=parsed["positions_by_t"],
            goals=[tuple(g) for g in goals],
            wait_map=wait_map,
            collision_map=collision_map,
            runtime_s=runtime_s,
            solver_rc=rc,
        )
        meta = {
            "instance_id": instance_id,
            "instance_file": str(instance_file),
            "map_name": map_name,
            "map_path": str(map_path),
            "num_agents": num_agents,
            "seed": entry.get("seed", None),
            "solver": "pypibt",
            "pypibt_app": str(pypibt_app),
            "python": args.python,
            "runtime_s": runtime_s,
            "solver_rc": rc,
            "metrics": metrics,
            "notes": {
                "wait_map_rule": "count stay steps before the agent reaches its goal (goal-camping excluded)",
                "collision_map_rule": "blocking pressure: if agent (pre-goal) intends shortest-step (BFS) but stays, add 1 to intended cell",
            },
        }

        np.savez_compressed(
            out_npz,
            wait_map=wait_map.astype(np.int32),
            collision_map=collision_map.astype(np.int32),
            occupancy_map=occupancy_map.astype(np.int32),
            obstacles=obstacles.astype(np.uint8),
            H=np.int32(H),
            W=np.int32(W),
            makespan=np.int32(metrics["makespan"]),
        )
        out_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"[ok] wrote {out_npz} and {out_meta}")

        n_done += 1
        if args.max_instances and n_done >= args.max_instances:
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
