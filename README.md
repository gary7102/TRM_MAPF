

# Usage
`python -m venv .venv && source .venv/bin/activate`

1. **Create instances**
```
python scripts/01_prepare_instances.py  \
--scen data/scen/maze-128-128-1-random-1.scen \
--out_dir data/instances \
--map_filter maze-128-128-1.map \
--num_instances 50   \
--num_agents 50 \
--seed 42 \
--unique_goal \
--unique_pair
```

2. **Run pypibt for each instance**
記得修改02_run_pypibt_collect.py 中的--menifest and --runs_dir
```
python scripts/02_run_pypibt_collect.py \
--timeout 120 \
--use_uv \
--max_instances 50 \
```

3. **彙總成 map-level 的 $P_{raw}$**
```
python scripts/03_aggregate_p_raw.py --map_name random-32-32-10.map --only_solved --alpha 1 --beta 1 --out_dir outputs/p_raw_C_combo
```

---
'''
TRM_MAPF/
  third_party/
    pypibt/                  # git submodule (Kei18/pypibt)
    mapf-visulizer/          # git submodule (Kei18/mapf-visualizer)
  data/
    maps/                    # .map
    scen/                    # .scen
    instances/               # 切片後的 MAPF instances (每個instance N行任務)
  outputs/
    p_raw/
      <map_name>/
        wait_count.npy
        collision_count.npy
        p_raw.npy
        meta.json
        rollouts/ (optional)
  src/
    mapf_praw/
      io_map.py              # 讀 .map
      io_scen.py             # 讀 .scen + 抽樣組 instance
      features_topo.py       # (選做) 局部拓樸特徵圖：dead-end/junction/degree...
      metrics_praw.py        # 計算 wait/collision + log 壓縮
  scripts/
    01_prepare_instances.py  # 從 .scen 抽樣產生 N-agent instances
    02_run_pibt_collect.py   # 呼叫 pypibt 跑模擬 + 收集事件
    03_build_praw.py         # 彙總成 HxW heatmap，輸出 outputs/
    04_sanity_check_viz.py   # (選做) 畫 heatmap / 抽樣 episode 檢查
  configs/
    phase1_praw.yaml         # 地圖集合、N、instances、timelimit、seed
'''

# 目標（Phase 1）

在一批地圖（Maze-Hard / Room+Corridor 為主）上，反覆抽樣多組 MAPF 任務（N=100 也可），用 PIBT 做「流動性模擬」。

統計每個格子 𝑢 的：
* WaitCount(u)：停等/原地不動事件的累積
* CollisionCount(u)：衝突嘗試/被迫回退事件的累積（下方會給出可實作且可辯護的定義）

產生每張地圖一張 P_raw heatmap（= 𝑌𝑡𝑎𝑟𝑔𝑒𝑡），作為後續 TRM-H 的監督訊號與「Heatmap Heuristic baseline」的直接材料（符合你要求的比較基準）。