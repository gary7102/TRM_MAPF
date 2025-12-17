#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import json
import re
from pathlib import Path

PAIR_RE = re.compile(r"\((\-?\d+),\s*(\-?\d+)\)")

def parse_instance_goals(instance_path: Path):
    """
    MovingAI .scen instance:
      line0: "version 1"
      then each line: <bucket> <map> <w> <h> <sx> <sy> <gx> <gy> <opt>
    We return goals: list[(x,y)]
    """
    goals = []
    with instance_path.open("r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f.readlines() if ln.strip()]
    assert lines[0].startswith("version"), f"bad scen header: {instance_path}"
    for ln in lines[1:]:
        parts = ln.split()
        if len(parts) < 8:
            continue
        sx, sy, gx, gy = map(int, parts[4:8])
        goals.append((gx, gy))
    return goals

def parse_output_txt(output_path: Path):
    """
    output.txt format:
      t:(x,y),(x,y),...,
    Return:
      paths[t][agent_i] = (x,y)
    """
    paths = []
    with output_path.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            # split "t:...."
            if ":" not in ln:
                continue
            _, rest = ln.split(":", 1)
            pairs = PAIR_RE.findall(rest)
            if not pairs:
                continue
            step = [(int(x), int(y)) for x, y in pairs]
            paths.append(step)
    return paths

def compute_metrics(paths, goals):
    """
    Metrics for qualitative check:
      - num_agents
      - makespan_index (last timestep index)
      - num_steps (len(paths))
      - reached_agents (at final step)
      - solved (reached_agents == num_agents)
      - total_wait_excluding_after_goal:
          count stay steps only while agent not yet reached goal
    """
    num_steps = len(paths)
    if num_steps == 0:
        return None

    num_agents = len(paths[0])
    goals = goals[:num_agents]  # safety
    last = paths[-1]
    reached = sum(1 for i in range(num_agents) if last[i] == goals[i])
    solved = 1 if reached == num_agents else 0

    # total_wait excluding after goal
    reached_time = [None] * num_agents
    # find first time agent reaches goal
    for t in range(num_steps):
        for i in range(num_agents):
            if reached_time[i] is None and paths[t][i] == goals[i]:
                reached_time[i] = t

    total_wait = 0
    for t in range(num_steps - 1):
        for i in range(num_agents):
            rt = reached_time[i]
            # if already reached at/before t, exclude future waiting
            if rt is not None and t >= rt:
                continue
            if paths[t+1][i] == paths[t][i]:
                total_wait += 1

    return {
        "num_agents": num_agents,
        "makespan": num_steps - 1,   # last timestep index
        "num_steps": num_steps,
        "reached_agents": reached,
        "solved": solved,
        "total_wait": total_wait,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map_name", required=True)
    ap.add_argument("--instance_ids", required=True,
                    help="comma-separated, e.g., 12,29,0")
    ap.add_argument("--qual_dir", required=True,
                    help="e.g., outputs/qual_phase2/random-32-32-10.map")
    ap.add_argument("--instances_dir", default="data/instances",
                    help="root of instances folder")
    ap.add_argument("--out_prefix", default="phase2",
                    help="output prefix name")
    args = ap.parse_args()

    map_name = args.map_name
    instance_ids = [int(x) for x in args.instance_ids.split(",") if x.strip()]
    qual_dir = Path(args.qual_dir)
    instances_root = Path(args.instances_dir)

    variants = ["base", "A", "B", "C"]

    rows = []
    for iid in instance_ids:
        instance_file = instances_root / map_name / f"instance_{iid:05d}.scen"
        if not instance_file.exists():
            raise FileNotFoundError(f"missing instance scen: {instance_file}")
        goals = parse_instance_goals(instance_file)

        for v in variants:
            out_file = qual_dir / f"instance_{iid:05d}_{v}.txt"
            if v == "base":
                out_file = qual_dir / f"instance_{iid:05d}_base.txt"
            if not out_file.exists():
                raise FileNotFoundError(f"missing output: {out_file}")

            paths = parse_output_txt(out_file)
            m = compute_metrics(paths, goals)
            if m is None:
                raise RuntimeError(f"cannot parse paths: {out_file}")

            row = {
                "map_name": map_name,
                "instance_id": iid,
                "variant": v,
                **m,
                "output_file": str(out_file),
            }
            rows.append(row)

    # write long csv
    out_long = qual_dir / f"{args.out_prefix}_long.csv"
    with out_long.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # pivot-like csv (makespan/solved/reached/total_wait)
    # rows by instance, columns by variant
    metrics_cols = ["solved", "reached_agents", "makespan", "total_wait"]
    pivot = []
    for iid in instance_ids:
        base = next(r for r in rows if r["instance_id"] == iid and r["variant"] == "base")
        rec = {"map_name": map_name, "instance_id": iid}
        for v in variants:
            r = next(x for x in rows if x["instance_id"] == iid and x["variant"] == v)
            for c in metrics_cols:
                rec[f"{v}_{c}"] = r[c]
        # deltas vs base
        for v in ["A", "B", "C"]:
            rec[f"{v}_delta_makespan_vs_base"] = rec[f"{v}_makespan"] - rec["base_makespan"]
            rec[f"{v}_delta_wait_vs_base"] = rec[f"{v}_total_wait"] - rec["base_total_wait"]
            rec[f"{v}_delta_reached_vs_base"] = rec[f"{v}_reached_agents"] - rec["base_reached_agents"]
        pivot.append(rec)

    out_pivot = qual_dir / f"{args.out_prefix}_pivot.csv"
    with out_pivot.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(pivot[0].keys()))
        w.writeheader()
        w.writerows(pivot)

    # write markdown summary
    out_md = qual_dir / f"{args.out_prefix}_summary.md"
    def md_table(records, headers):
        lines = []
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for r in records:
            lines.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
        return "\n".join(lines)

    md_headers = [
        "instance_id",
        "base_solved","A_solved","B_solved","C_solved",
        "base_makespan","A_makespan","B_makespan","C_makespan",
        "A_delta_makespan_vs_base","B_delta_makespan_vs_base","C_delta_makespan_vs_base",
        "base_total_wait","A_total_wait","B_total_wait","C_total_wait",
        "A_delta_wait_vs_base","B_delta_wait_vs_base","C_delta_wait_vs_base",
        "base_reached_agents","A_reached_agents","B_reached_agents","C_reached_agents",
    ]
    with out_md.open("w", encoding="utf-8") as f:
        f.write(f"# Phase 2 Qualitative Summary\n\n")
        f.write(f"- map: `{map_name}`\n")
        f.write(f"- instances: {instance_ids}\n")
        f.write(f"- variants: {variants}\n\n")
        f.write(md_table(pivot, md_headers))
        f.write("\n")

    print(f"[ok] wrote:\n  {out_long}\n  {out_pivot}\n  {out_md}")

if __name__ == "__main__":
    main()
