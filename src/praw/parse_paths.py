# -*- coding: utf-8 -*-
"""
Parse pypibt output.txt into per-agent trajectories.

Expected (visualizer-compatible) format example:
  0:(5,16),(21,29),(...)
  1:(5,17),(21,28),(...)
Each line is a timestep t, then positions of all agents at that time.
This is the planning-result format described by mapf-visualizer.citeturn1view0

This parser is defensive:
- It ignores non-solution header lines if any.
- It validates the agent count per timestep (if expected_num_agents provided).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import re


_TLINE_RE = re.compile(r"^\s*(\d+)\s*:\s*(.*)\s*$")
_XY_RE = re.compile(r"\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)")


def parse_output_txt(output_txt: Path, expected_num_agents: Optional[int] = None) -> Dict:
    """
    Returns:
      {
        "timesteps": [t0, t1, ...] (ints, usually 0..makespan),
        "positions_by_t": [ [(x,y),...], ... ] (len=T, each inner len=num_agents),
        "paths": [ [(x,y),...], ... ] (len=num_agents, each len=T),
      }
    """
    lines = output_txt.read_text(encoding="utf-8", errors="replace").splitlines()

    timesteps: List[int] = []
    pos_by_t: List[List[Tuple[int, int]]] = []

    for ln in lines:
        m = _TLINE_RE.match(ln)
        if not m:
            continue
        t = int(m.group(1))
        rest = m.group(2)
        xy = [(int(a), int(b)) for (a, b) in _XY_RE.findall(rest)]
        if not xy:
            # A timestep line must contain at least one (x,y)
            continue
        if expected_num_agents is not None and len(xy) != expected_num_agents:
            raise ValueError(
                f"Agent count mismatch at t={t}: got {len(xy)}, expected {expected_num_agents}. "
                f"Line='{ln[:120]}'"
            )
        timesteps.append(t)
        pos_by_t.append(xy)

    if not timesteps:
        raise ValueError(f"No solution lines found in {output_txt}")

    # Ensure timesteps are strictly increasing
    for i in range(1, len(timesteps)):
        if timesteps[i] <= timesteps[i - 1]:
            raise ValueError(f"Non-increasing timesteps in {output_txt}: {timesteps[i-1]} -> {timesteps[i]}")

    num_agents = len(pos_by_t[0])
    if expected_num_agents is not None:
        num_agents = expected_num_agents

    # Build per-agent paths
    paths: List[List[Tuple[int, int]]] = [[] for _ in range(num_agents)]
    for xy in pos_by_t:
        if len(xy) != num_agents:
            raise ValueError(f"Inconsistent agent count across timesteps. first={num_agents}, now={len(xy)}")
        for a in range(num_agents):
            paths[a].append(xy[a])

    return {
        "timesteps": timesteps,
        "positions_by_t": pos_by_t,
        "paths": paths,
        "num_agents": num_agents,
        "makespan": timesteps[-1],
    }
