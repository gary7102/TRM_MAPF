#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Phase 3 summary: summarize LaCAM3 result.txt for baseline vs heatmap.

Expected usage example:
  python scripts/phase3_summarize_results.py \
    --root outputs/phase3/random-32-32-20.map \
    --out_csv outputs/phase3/random-32-32-20.map/summary.csv

Or point --root to a map file to auto-search common result folders:
  python scripts/phase3_summarize_results.py \
    --root data/maps/random-32-32-20.map \
    --out_csv outputs/phase3/random-32-32-20.map/summary.csv \
    --require_pair

This script:
- Recursively finds *.txt under --root
- Identifies variant by filename containing "baseline" or "heatmap"
- Extracts instance id from filename (e.g., "00040" in "heatmap00040_result.txt")
- Parses key=value lines from each txt
- Joins baseline vs heatmap per instance id
- Outputs a CSV summary and prints a readable table to stdout
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List


KEYS_CORE = [
    # feasibility / speed / search effort
    "solved",
    "comp_time",
    "comp_time_initial_solution",
    "search_iteration",
    "num_high_level_node",
    "num_low_level_node",
    # solution quality
    "soc",
    "soc_lb",
    "makespan",
    "makespan_lb",
    "cost_initial_solution",
    "sum_of_loss",
    "sum_of_loss_lb",
]


@dataclass
class RunRecord:
    path: Path
    instance_id: str
    variant: str  # "baseline" or "heatmap"
    kv: Dict[str, Any]


def _try_cast(v: str) -> Any:
    v = v.strip()
    if v == "":
        return v
    # checkpoints=-1,2,3, style
    if "," in v and all(ch.isdigit() or ch in "+-., " for ch in v):
        # keep as string; we will parse checkpoints separately if needed
        return v

    # int
    try:
        if re.fullmatch(r"[+-]?\d+", v):
            return int(v)
    except Exception:
        pass

    # float
    try:
        if re.fullmatch(r"[+-]?\d+(\.\d+)?([eE][+-]?\d+)?", v):
            return float(v)
    except Exception:
        pass

    return v


def parse_result_txt(p: Path) -> Dict[str, Any]:
    kv: Dict[str, Any] = {}
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        kv[k] = _try_cast(v)

    # post-process checkpoints if present
    if "checkpoints" in kv and isinstance(kv["checkpoints"], str):
        raw = kv["checkpoints"]
        # " -1, " or "-1,2,3,"
        items = [s for s in raw.split(",") if s.strip() != ""]
        parsed: List[int] = []
        ok = True
        for it in items:
            it = it.strip()
            try:
                parsed.append(int(it))
            except Exception:
                ok = False
                break
        if ok:
            kv["checkpoints"] = parsed

    return kv


def resolve_search_roots(root: Path) -> List[Path]:
    if root.is_dir():
        return [root]
    if root.is_file():
        if root.suffix != ".map":
            raise SystemExit(f"[error] --root is a file but not a .map: {root}")
        map_name = root.name
        repo_root = Path(__file__).resolve().parents[1]
        candidates = [
            repo_root / "runs" / "phase3_top5" / "baseline" / map_name,
            repo_root / "runs" / "phase3_top5" / "heatmap" / map_name,
            repo_root / "outputs" / "phase3_top5" / map_name,
            repo_root / "outputs" / "phase3" / map_name,
        ]
        found = [c for c in candidates if c.exists()]
        if not found:
            raise SystemExit(
                "[error] no result dirs found for map: "
                f"{map_name}. Looked in: " + ", ".join(str(c) for c in candidates)
            )
        return found
    raise SystemExit(f"[error] --root not found: {root}")


def detect_variant(name: str) -> Optional[str]:
    low = name.lower()
    if "baseline" in low or "base" in low:
        return "baseline"
    if "heatmap" in low or "heat" in low:
        return "heatmap"
    return None


def extract_instance_id(name: str) -> Optional[str]:
    """
    Try to extract 5-digit or 2-5 digit id from filename.
    Prefer patterns like instance_00040 or heatmap00040.
    """
    # instance_00040
    m = re.search(r"instance[_\-]?(\d{5})", name, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    # heatmap00040 / baseline00040 / ...00040...
    m = re.search(r"(\d{5})", name)
    if m:
        return m.group(1)
    # fallback: 2~4 digits (e.g., 40) -> normalize to 5 digits
    m = re.search(r"(\d{2,4})", name)
    if m:
        return m.group(1).zfill(5)
    return None


def pct_change(new: float, old: float) -> Optional[float]:
    if old == 0:
        return None
    return (new - old) / old * 100.0


def fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isfinite(v):
            # keep compact
            return f"{v:.3f}".rstrip("0").rstrip(".")
        return str(v)
    return str(v)


def get_num(kv: Dict[str, Any], k: str) -> Optional[float]:
    if k not in kv:
        return None
    v = kv[k]
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except Exception:
        return None


def build_summary_row(instance_id: str,
                      base: Optional[Dict[str, Any]],
                      heat: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    row: Dict[str, Any] = {"instance_id": instance_id}

    def put(prefix: str, kv: Optional[Dict[str, Any]]):
        if kv is None:
            for k in KEYS_CORE:
                row[f"{prefix}_{k}"] = ""
            return
        for k in KEYS_CORE:
            row[f"{prefix}_{k}"] = kv.get(k, "")

        # derived gaps
        soc = get_num(kv, "soc")
        soc_lb = get_num(kv, "soc_lb")
        mk = get_num(kv, "makespan")
        mk_lb = get_num(kv, "makespan_lb")
        if soc is not None and soc_lb is not None:
            row[f"{prefix}_soc_gap"] = soc - soc_lb
        else:
            row[f"{prefix}_soc_gap"] = ""
        if mk is not None and mk_lb is not None:
            row[f"{prefix}_makespan_gap"] = mk - mk_lb
        else:
            row[f"{prefix}_makespan_gap"] = ""

    put("base", base)
    put("heat", heat)

    # deltas for core effort metrics
    for k in ["comp_time", "comp_time_initial_solution", "search_iteration",
              "num_high_level_node", "num_low_level_node",
              "cost_initial_solution", "soc", "makespan", "sum_of_loss"]:
        b = get_num(base or {}, k)
        h = get_num(heat or {}, k)
        if b is None or h is None:
            row[f"delta_{k}"] = ""
            row[f"delta_{k}_pct"] = ""
        else:
            row[f"delta_{k}"] = h - b
            pc = pct_change(h, b)
            row[f"delta_{k}_pct"] = "" if pc is None else pc

    # solved change
    bsol = get_num(base or {}, "solved")
    hsol = get_num(heat or {}, "solved")
    if bsol is None or hsol is None:
        row["delta_solved"] = ""
    else:
        row["delta_solved"] = int(hsol) - int(bsol)

    return row


def print_table(rows: List[Dict[str, Any]]) -> None:
    # A compact human-readable table for stdout
    headers = [
        "id",
        "sol(base→heat)",
        "time_ms(base→heat,Δ%)",
        "iter(base→heat,Δ%)",
        "HL(base→heat,Δ%)",
        "LL(base→heat,Δ%)",
        "soc(base→heat)",
        "mk(base→heat)",
        "init_cost(base→heat)",
    ]

    def cell(row: Dict[str, Any], k: str) -> Any:
        return row.get(k, "")

    print("\n=== Phase 3 Summary (baseline vs heatmap) ===")
    print(" | ".join(headers))
    print("-" * 120)
    for r in rows:
        bsol = cell(r, "base_solved")
        hsol = cell(r, "heat_solved")

        bt = get_num({"x": r.get("base_comp_time")}, "x")
        ht = get_num({"x": r.get("heat_comp_time")}, "x")
        dtp = r.get("delta_comp_time_pct", "")

        bi = get_num({"x": r.get("base_search_iteration")}, "x")
        hi = get_num({"x": r.get("heat_search_iteration")}, "x")
        dip = r.get("delta_search_iteration_pct", "")

        bhl = get_num({"x": r.get("base_num_high_level_node")}, "x")
        hhl = get_num({"x": r.get("heat_num_high_level_node")}, "x")
        dhlp = r.get("delta_num_high_level_node_pct", "")

        bll = get_num({"x": r.get("base_num_low_level_node")}, "x")
        hll = get_num({"x": r.get("heat_num_low_level_node")}, "x")
        dllp = r.get("delta_num_low_level_node_pct", "")

        bsoc = r.get("base_soc", "")
        hsoc = r.get("heat_soc", "")
        bmk = r.get("base_makespan", "")
        hmk = r.get("heat_makespan", "")
        bc0 = r.get("base_cost_initial_solution", "")
        hc0 = r.get("heat_cost_initial_solution", "")

        def pair(a, b) -> str:
            return f"{fmt(a)}→{fmt(b)}"

        def pair_pct(a, b, p) -> str:
            if p == "" or p is None:
                return f"{pair(a,b)}"
            return f"{pair(a,b)}, {fmt(p)}%"

        line = [
            r["instance_id"],
            pair(bsol, hsol),
            pair_pct(bt, ht, dtp),
            pair_pct(bi, hi, dip),
            pair_pct(bhl, hhl, dhlp),
            pair_pct(bll, hll, dllp),
            pair(bsoc, hsoc),
            pair(bmk, hmk),
            pair(bc0, hc0),
        ]
        print(" | ".join(line))

    print("-" * 120)


def aggregate_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    # overall solved rate and averages (only over solved instances per variant)
    def collect(prefix: str, key: str) -> List[float]:
        out = []
        for r in rows:
            solved = r.get(f"{prefix}_solved", "")
            if solved == "" or int(float(solved)) != 1:
                continue
            v = r.get(f"{prefix}_{key}", "")
            if v == "":
                continue
            try:
                out.append(float(v))
            except Exception:
                pass
        return out

    def avg(xs: List[float]) -> float:
        return sum(xs) / len(xs) if xs else float("nan")

    def solved_count(prefix: str) -> Tuple[int, int]:
        tot = 0
        sol = 0
        for r in rows:
            s = r.get(f"{prefix}_solved", "")
            if s == "":
                continue
            tot += 1
            if int(float(s)) == 1:
                sol += 1
        return sol, tot

    bsol, btot = solved_count("base")
    hsol, htot = solved_count("heat")

    stats = {
        "n_instances": len(rows),
        "baseline_solved": bsol,
        "baseline_total": btot,
        "baseline_solved_rate": (bsol / btot) if btot else float("nan"),
        "heat_solved": hsol,
        "heat_total": htot,
        "heat_solved_rate": (hsol / htot) if htot else float("nan"),
        "baseline_avg_comp_time_initial_solution": avg(
            collect("base", "comp_time_initial_solution")
        ),
        "heat_avg_comp_time_initial_solution": avg(
            collect("heat", "comp_time_initial_solution")
        ),
        "baseline_avg_soc_solved": avg(collect("base", "soc")),
        "heat_avg_soc_solved": avg(collect("heat", "soc")),
        "baseline_avg_makespan_solved": avg(collect("base", "makespan")),
        "heat_avg_makespan_solved": avg(collect("heat", "makespan")),
        "baseline_avg_sum_of_loss_solved": avg(collect("base", "sum_of_loss")),
        "heat_avg_sum_of_loss_solved": avg(collect("heat", "sum_of_loss")),
    }
    return stats


def _infer_map_name(root: Path) -> str:
    if root.is_file() and root.suffix == ".map":
        return root.name
    for part in root.parts:
        if part.endswith(".map"):
            return part
    return root.name


def _infer_lambda(root: Path) -> Optional[str]:
    for part in root.parts:
        m = re.search(r"lambda[_-]?([0-9]+(?:\.[0-9]+)?)", part)
        if m:
            return m.group(1)
    return None


def write_html(outp: Path, rows: List[Dict[str, Any]], stats: Dict[str, Any],
               map_name: str, lambda_value: str, top_n: int) -> None:
    def esc(v: Any) -> str:
        return html.escape(fmt(v))

    def num(v: Any) -> Optional[float]:
        if v == "" or v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    metrics = [
        ("solved", "solved", "higher"),
        ("search_iteration", "search_iteration", "lower"),
        ("num_high_level_node", "num_high_level_node", "lower"),
        ("num_low_level_node", "num_low_level_node", "lower"),
        ("comp_time", "comp_time", "lower"),
        ("comp_time_initial_solution", "comp_time_initial_solution", "lower"),
        ("cost_initial_solution", "cost_initial_solution", "lower"),
        ("soc", "soc", "lower"),
        ("soc_lb", "soc_lb", "lower"),
        ("soc_gap", "soc_gap", "lower"),
        ("makespan", "makespan", "lower"),
        ("makespan_lb", "makespan_lb", "lower"),
        ("makespan_gap", "mk_gap", "lower"),
        ("sum_of_loss", "sum_of_loss", "lower"),
    ]

    def difficulty_key(r: Dict[str, Any]) -> float:
        v = num(r.get("base_search_iteration", ""))
        if v is None:
            v = num(r.get("heat_search_iteration", ""))
        return v if v is not None else float("-inf")

    rows_sorted = sorted(rows, key=difficulty_key, reverse=True)
    if top_n > 0:
        rows_sorted = rows_sorted[:min(top_n, len(rows_sorted))]

    lines: List[str] = []
    lines.append("<!doctype html>")
    lines.append("<html lang=\"en\">")
    lines.append("<head>")
    lines.append("  <meta charset=\"utf-8\" />")
    lines.append("  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />")
    lines.append("  <title>Phase 3 Summary</title>")
    lines.append("  <style>")
    lines.append("    :root {")
    lines.append("      --bg: #f3f1ea;")
    lines.append("      --panel: #ffffff;")
    lines.append("      --text: #1b1f24;")
    lines.append("      --muted: #5c6773;")
    lines.append("      --accent: #0f5d5d;")
    lines.append("      --border: #e1e4e8;")
    lines.append("      --pos: #0f7b6c;")
    lines.append("      --neg: #a5362b;")
    lines.append("    }")
    lines.append("    body {")
    lines.append("      margin: 24px;")
    lines.append("      font-family: \"IBM Plex Sans\", \"Noto Sans\", \"Segoe UI\", sans-serif;")
    lines.append("      background: linear-gradient(180deg, #f3f1ea 0%, #eef2f0 100%);")
    lines.append("      color: var(--text);")
    lines.append("    }")
    lines.append("    h1 { font-size: 22px; margin: 0 0 8px; }")
    lines.append("    small { color: var(--muted); }")
    lines.append("    section {")
    lines.append("      background: var(--panel);")
    lines.append("      border: 1px solid var(--border);")
    lines.append("      border-radius: 12px;")
    lines.append("      padding: 16px;")
    lines.append("      box-shadow: 0 1px 2px rgba(0,0,0,0.04);")
    lines.append("      margin: 16px 0;")
    lines.append("    }")
    lines.append("    table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; }")
    lines.append("    th, td { border: 1px solid var(--border); padding: 8px 10px; vertical-align: top; }")
    lines.append("    th { position: sticky; top: 0; background: #f7f6f2; text-align: center; }")
    lines.append("    td.id { font-weight: 600; text-align: left; white-space: nowrap; }")
    lines.append("    tbody tr:nth-child(odd) { background: #fbfaf6; }")
    lines.append("    .table-wrap { overflow-x: auto; }")
    lines.append("    .cell { min-width: 140px; display: grid; gap: 4px; }")
    lines.append("    .line { display: flex; justify-content: space-between; gap: 8px; }")
    lines.append("    .tag { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }")
    lines.append("    .val { font-family: \"IBM Plex Mono\", \"Menlo\", monospace; }")
    lines.append("    .delta { font-weight: 600; }")
    lines.append("    .delta.pos { color: var(--pos); }")
    lines.append("    .delta.neg { color: var(--neg); }")
    lines.append("    .muted { color: var(--muted); }")
    lines.append("    .pct { color: var(--muted); font-weight: 400; }")
    lines.append("  </style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append(f"  <h1>Phase 3 Summary: {esc(map_name)}, lambda={esc(lambda_value)}</h1>")
    subtitle = "Each cell: base / heat / delta (signed change)"
    if top_n > 0:
        subtitle += f"; showing top {top_n} by base_search_iteration"
    lines.append(f"  <small>{esc(subtitle)}</small>")

    lines.append("  <section>")
    lines.append("    <div class=\"table-wrap\">")
    lines.append("      <table>")
    lines.append("        <thead><tr>")
    lines.append("          <th>instance_id</th>")
    for _, label, _ in metrics:
        lines.append(f"          <th>{esc(label)}</th>")
    lines.append("        </tr></thead>")
    lines.append("        <tbody>")
    avg_row: Dict[str, Any] = {"instance_id": f"AVG({len(rows_sorted)})"}
    for key, _, _ in metrics:
        base_key = f"base_{key}"
        heat_key = f"heat_{key}"
        base_vals = []
        heat_vals = []
        for r in rows_sorted:
            bv = num(r.get(base_key, ""))
            hv = num(r.get(heat_key, ""))
            if bv is not None:
                base_vals.append(bv)
            if hv is not None:
                heat_vals.append(hv)
        avg_row[base_key] = sum(base_vals) / len(base_vals) if base_vals else ""
        avg_row[heat_key] = sum(heat_vals) / len(heat_vals) if heat_vals else ""

    rows_with_avg = [avg_row] + rows_sorted
    for r in rows_with_avg:
        lines.append("          <tr>")
        lines.append(f"            <td class=\"id\">{esc(r.get('instance_id',''))}</td>")
        for key, _, better in metrics:
            base_key = f"base_{key}"
            heat_key = f"heat_{key}"
            base_v = r.get(base_key, "")
            heat_v = r.get(heat_key, "")
            b = num(base_v)
            h = num(heat_v)
            delta_val = None if b is None or h is None else (h - b)
            pct = None if delta_val is None or b in (None, 0) else (delta_val / b * 100.0)

            if delta_val is None:
                delta_cls = "muted"
                delta_html = "<span class=\"muted\">n/a</span>"
            else:
                if better == "lower":
                    delta_cls = "pos" if delta_val < 0 else ("neg" if delta_val > 0 else "")
                else:
                    delta_cls = "pos" if delta_val > 0 else ("neg" if delta_val < 0 else "")
                delta_disp = fmt(delta_val)
                if delta_val > 0:
                    delta_disp = f"+{delta_disp}"
                delta_html = f"{esc(delta_disp)}"
                if pct is not None:
                    pct_disp = fmt(pct)
                    if pct > 0:
                        pct_disp = f"+{pct_disp}"
                    delta_html += f" <span class=\"pct\">({esc(pct_disp)}%)</span>"

            lines.append("            <td>")
            lines.append("              <div class=\"cell\">")
            lines.append(f"                <div class=\"line\"><span class=\"tag\">base</span><span class=\"val\">{esc(base_v)}</span></div>")
            lines.append(f"                <div class=\"line\"><span class=\"tag\">heat</span><span class=\"val\">{esc(heat_v)}</span></div>")
            if delta_cls:
                lines.append(f"                <div class=\"line delta {delta_cls}\"><span class=\"tag\">delta</span><span class=\"val\">{delta_html}</span></div>")
            else:
                lines.append(f"                <div class=\"line delta\"><span class=\"tag\">delta</span><span class=\"val\">{delta_html}</span></div>")
            lines.append("              </div>")
            lines.append("            </td>")
        lines.append("          </tr>")
    lines.append("        </tbody>")
    lines.append("      </table>")
    lines.append("    </div>")
    lines.append("  </section>")

    lines.append("</body>")
    lines.append("</html>")

    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=str, required=True,
                    help="Root directory of result txt files, or a .map file to auto-search.")
    ap.add_argument("--out_csv", type=str, default="",
                    help="Write CSV summary to this path (optional).")
    ap.add_argument("--out_json", type=str, default="",
                    help="Write JSON summary to this path (optional).")
    ap.add_argument("--out_html", type=str, default="",
                    help="Write HTML summary to this path (optional).")
    ap.add_argument("--html_top_n", type=int, default=0,
                    help="Limit HTML to top N hardest instances by base_search_iteration.")
    ap.add_argument("--map_name", type=str, default="",
                    help="Map name for HTML title (optional).")
    ap.add_argument("--lambda", dest="lambda_value", type=str, default="",
                    help="Heatmap lambda for HTML title (optional).")
    ap.add_argument("--require_pair", action="store_true",
                    help="Only include instances that have BOTH baseline and heatmap.")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"[error] root not found: {root}")
    search_roots = resolve_search_roots(root)

    records: List[RunRecord] = []
    seen_paths = set()
    for sr in search_roots:
        for p in sr.rglob("*.txt"):
            if p in seen_paths:
                continue
            seen_paths.add(p)
            var = detect_variant(p.name)
            if var is None:
                continue
            iid = extract_instance_id(p.name)
            if iid is None:
                continue
            kv = parse_result_txt(p)
            records.append(RunRecord(path=p, instance_id=iid, variant=var, kv=kv))

    if not records:
        roots = ", ".join(str(p) for p in search_roots)
        raise SystemExit(
            "[error] no result txt found under: "
            f"{roots}. Ensure filenames include baseline/heatmap and an id."
        )

    by_id: Dict[str, Dict[str, RunRecord]] = {}
    for r in records:
        by_id.setdefault(r.instance_id, {})
        # if duplicates exist, keep the latest modified
        if r.variant in by_id[r.instance_id]:
            prev = by_id[r.instance_id][r.variant]
            if r.path.stat().st_mtime > prev.path.stat().st_mtime:
                by_id[r.instance_id][r.variant] = r
        else:
            by_id[r.instance_id][r.variant] = r

    rows: List[Dict[str, Any]] = []
    for iid in sorted(by_id.keys()):
        base_rec = by_id[iid].get("baseline")
        heat_rec = by_id[iid].get("heatmap")
        if args.require_pair and (base_rec is None or heat_rec is None):
            continue
        row = build_summary_row(
            iid,
            base_rec.kv if base_rec else None,
            heat_rec.kv if heat_rec else None
        )
        rows.append(row)

    # print readable table
    print_table(rows)

    # overall stats
    stats = aggregate_stats(rows)
    print("\n=== Overall Stats (solved-only averages) ===")
    for k, v in stats.items():
        if isinstance(v, float):
            if math.isnan(v):
                print(f"{k}: NaN")
            else:
                print(f"{k}: {v:.4f}")
        else:
            print(f"{k}: {v}")

    # write csv
    if args.out_csv:
        outp = Path(args.out_csv)
        outp.parent.mkdir(parents=True, exist_ok=True)

        # stable header order
        fieldnames = ["instance_id"]
        # baseline/heat core
        for prefix in ["base", "heat"]:
            for k in KEYS_CORE:
                fieldnames.append(f"{prefix}_{k}")
            fieldnames.append(f"{prefix}_soc_gap")
            fieldnames.append(f"{prefix}_makespan_gap")
        # deltas
        fieldnames += ["delta_solved"]
        for k in ["comp_time", "comp_time_initial_solution", "search_iteration",
                  "num_high_level_node", "num_low_level_node",
                  "cost_initial_solution", "soc", "makespan", "sum_of_loss"]:
            fieldnames.append(f"delta_{k}")
            fieldnames.append(f"delta_{k}_pct")

        with outp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                # ensure missing keys exist
                rr = {k: r.get(k, "") for k in fieldnames}
                w.writerow(rr)

        print(f"\n[ok] wrote CSV: {outp}")

    # write json
    if args.out_json:
        outp = Path(args.out_json)
        outp.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "rows": rows,
            "stats": stats,
        }
        with outp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        print(f"\n[ok] wrote JSON: {outp}")

    # write html
    if args.out_html:
        outp = Path(args.out_html)
        map_name = args.map_name or _infer_map_name(root)
        lambda_value = args.lambda_value or _infer_lambda(outp) or _infer_lambda(root) or "unknown"
        write_html(outp, rows, stats, map_name, lambda_value, args.html_top_n)
        print(f"\n[ok] wrote HTML: {outp}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
