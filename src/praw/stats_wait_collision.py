# src/praw/stats_wait_collision.py
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

XY = Tuple[int, int]  # (x, y)


def read_movingai_map(map_path) -> Tuple[List[str], int, int, np.ndarray]:
    """
    MovingAI map format:
      type octile
      height H
      width W
      map
      <H lines of chars>
    Obstacles are typically: '@', 'T', 'O', 'W'
    """
    map_path = str(map_path)
    with open(map_path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]

    H = W = None
    idx_map = None
    for i, ln in enumerate(lines):
        low = ln.lower()
        if low.startswith("height"):
            H = int(ln.split()[-1])
        elif low.startswith("width"):
            W = int(ln.split()[-1])
        elif low == "map":
            idx_map = i + 1
            break

    if H is None or W is None or idx_map is None:
        raise ValueError(f"Invalid map header: {map_path}")

    grid = lines[idx_map : idx_map + H]
    if len(grid) != H:
        raise ValueError(f"Invalid map body (expected {H} lines): {map_path}")

    obstacles = np.zeros((H, W), dtype=np.uint8)
    obs_chars = set(["@", "T", "O", "W"])
    for y in range(H):
        row = grid[y]
        if len(row) < W:
            raise ValueError(f"Map row too short at y={y}: {map_path}")
        for x in range(W):
            if row[x] in obs_chars:
                obstacles[y, x] = 1

    return grid, H, W, obstacles


def _bfs_dist(obstacles: np.ndarray, goal: XY) -> np.ndarray:
    """4-neighbor BFS distance-to-goal on static grid. obstacles[y,x]==1 means blocked."""
    H, W = obstacles.shape
    gx, gy = goal
    INF = 10**9
    dist = np.full((H, W), INF, dtype=np.int32)
    if not (0 <= gx < W and 0 <= gy < H):
        return dist
    if obstacles[gy, gx]:
        return dist

    q = deque()
    dist[gy, gx] = 0
    q.append((gx, gy))
    while q:
        x, y = q.popleft()
        d = int(dist[y, x]) + 1
        if x > 0 and not obstacles[y, x - 1] and dist[y, x - 1] > d:
            dist[y, x - 1] = d
            q.append((x - 1, y))
        if x + 1 < W and not obstacles[y, x + 1] and dist[y, x + 1] > d:
            dist[y, x + 1] = d
            q.append((x + 1, y))
        if y > 0 and not obstacles[y - 1, x] and dist[y - 1, x] > d:
            dist[y - 1, x] = d
            q.append((x, y - 1))
        if y + 1 < H and not obstacles[y + 1, x] and dist[y + 1, x] > d:
            dist[y + 1, x] = d
            q.append((x, y + 1))
    return dist


def _first_reach_times(paths: List[List[XY]], goals: List[XY]) -> List[int]:
    """Return first timestep each agent reaches its goal; if never, return +inf (large)."""
    T = len(paths)
    N = len(paths[0]) if T > 0 else 0
    inf = 10**9
    reach = [inf] * N
    for i in range(N):
        gi = goals[i]
        for t in range(T):
            if paths[t][i] == gi:
                reach[i] = t
                break
    return reach


def compute_wait_collision_heatmaps(
    paths: List[List[XY]],
    goals: List[XY],
    H: int,
    W: int,
    obstacles: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict]:
    """
    wait_map:
      count pos[t+1]==pos[t] for agents BEFORE they reach goal (goal-camping excluded)

    collision_map (v2):
      blocking pressure: for agents BEFORE they reach goal,
      if intended shortest-step cell (via BFS dist-to-goal) != current AND agent stays,
      add 1 to the intended cell.

    occupancy_map:
      count visits for agents BEFORE they reach goal (goal-camping excluded)
    """
    if obstacles is None:
        raise ValueError("compute_wait_collision_heatmaps requires obstacles mask for BFS intention.")

    T = len(paths)
    if T == 0:
        raise ValueError("Empty paths")
    N = len(paths[0])
    if len(goals) != N:
        raise ValueError(f"goals size mismatch: goals={len(goals)} vs agents={N}")

    reach_t = _first_reach_times(paths, goals)

    wait_map = np.zeros((H, W), dtype=np.int32)
    collision_map = np.zeros((H, W), dtype=np.int32)
    occupancy_map = np.zeros((H, W), dtype=np.int32)

    # Precompute BFS dist map per unique goal to speed up
    dist_cache: Dict[XY, np.ndarray] = {}
    unique_goals = set(goals)
    for g in unique_goals:
        dist_cache[g] = _bfs_dist(obstacles, g)

    # Fixed neighbor order for determinism (R,L,D,U)
    nbs = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    total_wait = 0
    total_blocked = 0

    # occupancy (exclude after goal)
    for t in range(T):
        for i in range(N):
            if t > reach_t[i]:
                continue
            x, y = paths[t][i]
            if 0 <= x < W and 0 <= y < H:
                occupancy_map[y, x] += 1

    # wait + blocking pressure
    for t in range(T - 1):
        for i in range(N):
            if t >= reach_t[i]:
                continue  # goal-camping excluded

            cur = paths[t][i]
            nxt = paths[t + 1][i]

            cx, cy = cur
            if nxt == cur:
                if 0 <= cx < W and 0 <= cy < H:
                    wait_map[cy, cx] += 1
                total_wait += 1

            # compute intended (shortest-step via BFS)
            dist = dist_cache[goals[i]]
            if not (0 <= cx < W and 0 <= cy < H):
                continue
            if obstacles[cy, cx]:
                continue

            d_cur = int(dist[cy, cx])
            if d_cur >= 10**9:
                continue  # unreachable

            intend = cur
            best_d = d_cur
            for dx, dy in nbs:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < W and 0 <= ny < H and not obstacles[ny, nx]:
                    d_nb = int(dist[ny, nx])
                    if d_nb < best_d:
                        best_d = d_nb
                        intend = (nx, ny)

            # blocked: intended to move but stayed
            if intend != cur and nxt == cur:
                ix, iy = intend
                collision_map[iy, ix] += 1
                total_blocked += 1

    details = {
        "T": T,
        "N": N,
        "reach_t": reach_t,
        "total_wait": int(total_wait),
        "total_blocked": int(total_blocked),
    }
    return wait_map, collision_map, occupancy_map, details


def summarize_run_metrics(
    paths: List[List[XY]],
    goals: List[XY],
    wait_map: np.ndarray,
    collision_map: np.ndarray,
    runtime_s: float,
    solver_rc: int,
) -> Dict:
    T = len(paths)
    N = len(paths[0]) if T > 0 else 0
    reach_t = _first_reach_times(paths, goals)
    reached_agents = sum(1 for t in reach_t if t < 10**9)
    solved = 1 if reached_agents == N and solver_rc == 0 else 0
    makespan = T - 1

    return {
        "num_agents": int(N),
        "makespan": int(makespan),
        "solved": int(solved),
        "reached_agents": int(reached_agents),
        "total_wait": int(np.sum(wait_map)),
        "total_collision": int(np.sum(collision_map)),  # now means total_blocked (pressure)
        "runtime_s": float(runtime_s),
        "solver_rc": int(solver_rc),
    }
