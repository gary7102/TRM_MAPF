#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
from pathlib import Path
import numpy as np

def load_npz(npz_path: Path):
    d = np.load(npz_path)
    return {
        "wait": d["wait_map"].astype(np.int64),
        "pressure": d["collision_map"].astype(np.int64),   # collision_map 已被你定義為 blocking pressure
        "occ": d["occupancy_map"].astype(np.int64),
        "obstacles": d["obstacles"].astype(np.uint8),
        "H": int(d["H"]),
        "W": int(d["W"]),
        "makespan": int(d["makespan"]),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map_name", type=str, required=True,
                    help="e.g. random-32-32-10.map")
    ap.add_argument("--praw_dir", type=str, default="data/p_raw",
                    help="root dir that contains data/p_raw/<map_name>/instance_*.npz")
    ap.add_argument("--out_dir", type=str, default="outputs/p_raw",
                    help="root dir for aggregated outputs")
    ap.add_argument("--only_solved", action="store_true", default=True)
    ap.add_argument("--alpha", type=float, default=0.0, help="weight for wait_sum in P_raw (0 means ignore)")
    ap.add_argument("--beta", type=float, default=1.0, help="weight for pressure_sum in P_raw")
    ap.add_argument("--log1p", action="store_true", default=True)
    args = ap.parse_args()

    map_name = args.map_name
    in_dir = Path(args.praw_dir) / map_name
    out_dir = Path(args.out_dir) / map_name
    out_dir.mkdir(parents=True, exist_ok=True)

    npz_files = sorted(in_dir.glob("instance_*.npz"))
    if not npz_files:
        raise FileNotFoundError(f"No npz found under: {in_dir}")

    # Filter by meta if needed
    used = []
    stats = {
        "map_name": map_name,
        "num_instances_total": 0,
        "num_instances_used": 0,
        "solved_rate": None,
        "avg_makespan_used": None,
    }
    makespans = []
    solved_cnt = 0

    # Initialize sums with first npz shape
    first = load_npz(npz_files[0])
    H, W = first["H"], first["W"]
    wait_sum = np.zeros((H, W), dtype=np.int64)
    pressure_sum = np.zeros((H, W), dtype=np.int64)
    occ_sum = np.zeros((H, W), dtype=np.int64)
    obstacles = first["obstacles"]

    stats["num_instances_total"] = len(npz_files)

    for f in npz_files:
        meta = f.with_suffix(".meta.json")
        if meta.exists():
            m = json.loads(meta.read_text(encoding="utf-8"))
            solved = int(m["metrics"]["solved"])
            if solved == 1:
                solved_cnt += 1
            if args.only_solved and solved != 1:
                continue

        d = load_npz(f)
        # Basic sanity
        if d["H"] != H or d["W"] != W:
            raise ValueError(f"Shape mismatch: {f} has {(d['H'], d['W'])} but expected {(H,W)}")

        wait_sum += d["wait"]
        pressure_sum += d["pressure"]
        occ_sum += d["occ"]
        makespans.append(d["makespan"])
        used.append(f.name)

    stats["num_instances_used"] = len(used)
    stats["solved_rate"] = float(solved_cnt) / float(stats["num_instances_total"])
    stats["avg_makespan_used"] = float(np.mean(makespans)) if makespans else None
    stats["sum_wait_total"] = int(wait_sum.sum())
    stats["sum_pressure_total"] = int(pressure_sum.sum())
    stats["sum_occ_total"] = int(occ_sum.sum())
    stats["alpha"] = float(args.alpha)
    stats["beta"] = float(args.beta)
    stats["log1p"] = bool(args.log1p)
    stats["used_instances"] = used[:200]  # avoid huge json; keep first 200 names

    # Build P_raw
    raw = args.alpha * wait_sum + args.beta * pressure_sum
    if args.log1p:
        p_raw = np.log1p(raw.astype(np.float32))
    else:
        p_raw = raw.astype(np.float32)

    # Save
    np.save(out_dir / "wait_sum.npy", wait_sum.astype(np.int32))
    np.save(out_dir / "pressure_sum.npy", pressure_sum.astype(np.int32))
    np.save(out_dir / "occ_sum.npy", occ_sum.astype(np.int32))
    np.save(out_dir / "obstacles.npy", obstacles.astype(np.uint8))
    np.save(out_dir / "p_raw.npy", p_raw.astype(np.float32))
    (out_dir / "aggregate_meta.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] wrote aggregated outputs to: {out_dir}")
    print(f"     used {stats['num_instances_used']}/{stats['num_instances_total']} instances, solved_rate={stats['solved_rate']:.3f}")

if __name__ == "__main__":
    main()
