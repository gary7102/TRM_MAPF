#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export p_raw.npy -> heatmap.f32.bin + heatmap.meta.json
- heatmap.f32.bin: float32, little-endian, row-major (C-order), index [y, x]
- meta.json: includes shape/stats and (optional) fields from aggregate_meta.json
"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np


def read_json_if_exists(p: Path) -> Optional[Dict[str, Any]]:
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    return None


def ensure_c_f32(a: np.ndarray) -> np.ndarray:
    # Force float32 + contiguous C-order (row-major)
    if a.dtype != np.float32:
        a = a.astype(np.float32, copy=False)
    if not a.flags["C_CONTIGUOUS"]:
        a = np.ascontiguousarray(a)
    return a


def parse_movingai_map_dims(map_path: Path) -> Optional[Dict[str, int]]:
    """
    Read MovingAI .map header to verify height/width.
    Returns {"height": H, "width": W} or None if parse failed.
    """
    if not map_path.exists():
        return None
    try:
        lines = map_path.read_text(encoding="utf-8").splitlines()
        h = w = None
        for ln in lines[:10]:
            ln = ln.strip()
            if ln.lower().startswith("height"):
                h = int(ln.split()[-1])
            elif ln.lower().startswith("width"):
                w = int(ln.split()[-1])
            if h is not None and w is not None:
                return {"height": h, "width": w}
    except Exception:
        return None
    return None


def export_one(npy_path: Path, map_path: Optional[Path], out_dir: Path, variant: str) -> None:
    if not npy_path.exists():
        raise FileNotFoundError(f"missing npy: {npy_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    p = np.load(npy_path)
    if p.ndim != 2:
        raise ValueError(f"p_raw must be 2D, got shape={p.shape} from {npy_path}")

    p = ensure_c_f32(p)
    H, W = p.shape

    # Optional: verify against .map header
    map_dims = None
    if map_path is not None:
        map_dims = parse_movingai_map_dims(map_path)
        if map_dims is not None:
            if map_dims["height"] != H or map_dims["width"] != W:
                raise ValueError(
                    f"shape mismatch: p_raw shape={p.shape} but map says "
                    f"{map_dims['height']}x{map_dims['width']} ({map_path})"
                )

    # Load aggregate_meta.json if present next to npy
    agg_meta = read_json_if_exists(npy_path.parent / "aggregate_meta.json")

    # Write binary
    bin_path = out_dir / "heatmap.f32.bin"
    with bin_path.open("wb") as f:
        f.write(p.tobytes(order="C"))  # row-major

    # Compose meta
    meta: Dict[str, Any] = {
        "map_name": npy_path.parent.name,  # folder name like random-32-32-10.map
        "variant": variant,
        "format": "f32.bin",
        "endianness": "little",
        "layout": "row-major",
        "indexing": "P[y,x] where y=row, x=col",
        "shape": {"height": int(H), "width": int(W)},
        "stats": {
            "min": float(np.min(p)),
            "max": float(np.max(p)),
            "mean": float(np.mean(p)),
        },
        "source": {
            "npy": str(npy_path),
        },
    }
    if map_path is not None:
        meta["source"]["map"] = str(map_path)
    if map_dims is not None:
        meta["map_header"] = map_dims
    if agg_meta is not None:
        meta["aggregate_meta"] = agg_meta

    meta_path = out_dir / "heatmap.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # Quick verification (read back)
    raw = np.fromfile(bin_path, dtype="<f4")
    if raw.size != H * W:
        raise RuntimeError(f"binary size mismatch: got {raw.size} floats, expected {H*W}")
    p2 = raw.reshape((H, W))
    # Allow exact match for float32 export
    if not np.allclose(p, p2, rtol=0, atol=0):
        raise RuntimeError("roundtrip verification failed (should be exact for f32)")

    print(f"[ok] {npy_path} -> {bin_path} + {meta_path} (H={H}, W={W})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--npy", type=str, help="path to p_raw.npy (single export)")
    ap.add_argument("--root", type=str, help="root folder containing <map>/p_raw.npy (batch)")
    ap.add_argument("--map_dir", type=str, default="data/maps",
                    help="where .map files live (for dimension sanity check)")
    ap.add_argument("--variant", type=str, default="unknown",
                    help="e.g., A_pressure / B_wait / C_combo")
    ap.add_argument("--out_mode", type=str, choices=["inplace", "subdir"], default="inplace",
                    help="inplace: write next to npy; subdir: write under <map>/export/")
    ap.add_argument("--out_subdir", type=str, default="export",
                    help="used when out_mode=subdir")
    args = ap.parse_args()

    map_dir = Path(args.map_dir)

    if args.npy:
        npy_path = Path(args.npy).resolve()
        map_name = npy_path.parent.name
        map_path = map_dir / map_name
        out_dir = npy_path.parent if args.out_mode == "inplace" else (npy_path.parent / args.out_subdir)
        export_one(npy_path, map_path, out_dir, args.variant)
        return 0

    if args.root:
        root = Path(args.root).resolve()
        if not root.exists():
            raise FileNotFoundError(f"root not found: {root}")
        # Expect structure: root/<map_name>/p_raw.npy
        maps = sorted([p for p in root.iterdir() if p.is_dir()])
        if not maps:
            raise RuntimeError(f"no map folders under: {root}")

        for mp in maps:
            npy_path = mp / "p_raw.npy"
            if not npy_path.exists():
                continue
            map_path = map_dir / mp.name
            out_dir = mp if args.out_mode == "inplace" else (mp / args.out_subdir)
            export_one(npy_path, map_path, out_dir, args.variant)
        return 0

    ap.error("provide --npy or --root")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
