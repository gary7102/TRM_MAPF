#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Step 2 - Prepare MAPF instances (.scen slicing)

Reads a MovingAI .scen file, samples K instances, each instance contains N tasks (agents),
with UNIQUE START positions to avoid start conflicts.

Scenario format reference (MovingAI):
- First line: "version x.x"
- Each subsequent line has 9 fields:
  bucket, map, map_width, map_height, start_x, start_y, goal_x, goal_y, optimal_length
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


# ----------------------------
# Data model
# ----------------------------

@dataclass(frozen=True)
class ScenRecord:
    bucket: int
    map_name: str
    map_w: int
    map_h: int
    sx: int
    sy: int
    gx: int
    gy: int
    opt_len: float
    src_line_no: int  # for reproducibility / manifest


# ----------------------------
# IO: read / write .scen
# ----------------------------

def read_scen(path: Path) -> Tuple[str, List[ScenRecord]]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        raise ValueError(f"Empty scen file: {path}")

    header = lines[0].strip()
    if not header.lower().startswith("version"):
        raise ValueError(f"Invalid scen header (expect 'version x.x'): {header}")

    records: List[ScenRecord] = []
    for idx, line in enumerate(lines[1:], start=2):  # 1-based line number
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 9:
            raise ValueError(f"Invalid scen line (expect 9 fields) at line {idx}: {line}")

        bucket = int(parts[0])
        map_name = parts[1]
        map_w = int(parts[2])
        map_h = int(parts[3])
        sx = int(parts[4])
        sy = int(parts[5])
        gx = int(parts[6])
        gy = int(parts[7])
        opt_len = float(parts[8])

        records.append(
            ScenRecord(
                bucket=bucket,
                map_name=map_name,
                map_w=map_w,
                map_h=map_h,
                sx=sx,
                sy=sy,
                gx=gx,
                gy=gy,
                opt_len=opt_len,
                src_line_no=idx,
            )
        )
    return header, records


def write_scen(path: Path, header: str, records: Iterable[ScenRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out_lines = [header]
    for r in records:
        out_lines.append(
            f"{r.bucket} {r.map_name} {r.map_w} {r.map_h} "
            f"{r.sx} {r.sy} {r.gx} {r.gy} {r.opt_len:g}"
        )
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


# ----------------------------
# Sampling logic (Unique Start)
# ----------------------------

def filter_by_map(records: List[ScenRecord], map_name_contains: Optional[str]) -> List[ScenRecord]:
    if not map_name_contains:
        return records
    key = map_name_contains
    return [r for r in records if key in r.map_name]


def sample_one_instance(
    records: List[ScenRecord],
    n_agents: int,
    rng: random.Random,
    unique_goal: bool,
    unique_pair: bool,
    max_trials: int = 20000,
) -> List[ScenRecord]:
    """
    Greedy sampling with constraints:
    - Unique starts always enforced
    - Optional: unique goals
    - Optional: unique (start, goal) pair
    """
    if len(records) < n_agents:
        raise ValueError(f"Not enough records ({len(records)}) to sample {n_agents} agents.")

    chosen: List[ScenRecord] = []
    used_starts = set()
    used_goals = set()
    used_pairs = set()

    # Shuffle a copy for sampling
    pool = records[:]
    rng.shuffle(pool)

    trials = 0
    i = 0
    while len(chosen) < n_agents and trials < max_trials:
        if i >= len(pool):
            # reshuffle and retry
            rng.shuffle(pool)
            i = 0
        r = pool[i]
        i += 1
        trials += 1

        start = (r.sx, r.sy)
        goal = (r.gx, r.gy)
        pair = (start, goal)

        if start in used_starts:
            continue
        if unique_goal and goal in used_goals:
            continue
        if unique_pair and pair in used_pairs:
            continue

        # accept
        chosen.append(r)
        used_starts.add(start)
        if unique_goal:
            used_goals.add(goal)
        if unique_pair:
            used_pairs.add(pair)

    if len(chosen) < n_agents:
        raise RuntimeError(
            f"Failed to sample {n_agents} tasks with constraints "
            f"(unique_goal={unique_goal}, unique_pair={unique_pair}). "
            f"Try lowering constraints or increasing scen size."
        )
    return chosen


# ----------------------------
# Manifest
# ----------------------------

def append_manifest(manifest_path: Path, payload: dict) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scen", type=str, required=True, help="Path to source .scen")
    ap.add_argument("--out_dir", type=str, required=True, help="Output directory for instances")
    ap.add_argument("--map_filter", type=str, default=None,
                    help="Only use scen lines whose map field contains this substring (e.g., 'random-32-32-10')")
    ap.add_argument("--num_instances", type=int, required=True, help="K: number of instances to generate")
    ap.add_argument("--num_agents", type=int, required=True, help="N: number of agents per instance")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--unique_goal", action="store_true", help="Enforce unique goals within an instance")
    ap.add_argument("--unique_pair", action="store_true", help="Enforce unique (start, goal) pairs within an instance")
    args = ap.parse_args()

    src_path = Path(args.scen)
    out_dir = Path(args.out_dir)
    header, records = read_scen(src_path)

    records = filter_by_map(records, args.map_filter)
    if not records:
        raise ValueError(f"No records after filtering. map_filter={args.map_filter}")

    rng = random.Random(args.seed)

    # Create output structure
    map_tag = args.map_filter if args.map_filter else "all_maps"
    target_dir = out_dir / map_tag
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = target_dir / "instances_manifest.jsonl"

    for k in range(args.num_instances):
        inst_records = sample_one_instance(
            records=records,
            n_agents=args.num_agents,
            rng=rng,
            unique_goal=args.unique_goal,
            unique_pair=args.unique_pair,
        )
        inst_name = f"instance_{k:05d}.scen"
        inst_path = target_dir / inst_name
        write_scen(inst_path, header, inst_records)

        append_manifest(manifest_path, {
            "instance_id": k,
            "instance_file": str(inst_path),
            "src_scen": str(src_path),
            "map_filter": args.map_filter,
            "num_agents": args.num_agents,
            "seed": args.seed,
            "unique_goal": args.unique_goal,
            "unique_pair": args.unique_pair,
            "src_line_nos": [r.src_line_no for r in inst_records],
            "starts": [[r.sx, r.sy] for r in inst_records],
            "goals": [[r.gx, r.gy] for r in inst_records],
        })

    print(f"[OK] Generated {args.num_instances} instances under: {target_dir}")
    print(f"[OK] Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
