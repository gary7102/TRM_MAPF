

# Usage
`python -m venv .venv && source .venv/bin/activate`

1. **Create instances**
切出 50 個 instances（確保 N_AGENTS 一致）
例：N=100、K=50
```
python scripts/01_prepare_instances.py \
  --scen data/scen/room-32-32-4-random-1.scen \
  --out_dir data/instances \
  --map_filter room-32-32-4.map \
  --num_instances 50 \
  --num_agents 100 \
  --seed 42 \
  --unique_goal \
  --unique_pair
```
note: 把 instance 檔轉成 tab 分隔（LaCAM3 要求）
```
perl -pe 's/[ \t]+/\t/g' -i data/instances/room-32-32-4.map/instance_*.scen
```
2. **Run pypibt for each instance**
```
python scripts/02_run_pypibt_collect.py \
  --manifest data/instances/room-32-32-4.map/instances_manifest.jsonl \
  --runs_dir runs/pypibt/room-32-32-4.map \
  --timeout 120 \
  --max_instances 50 \
  --use_uv
```

3. **彙總成 map-level 的 $P_{raw}$**
```
python scripts/03_aggregate_p_raw.py --map_name random-32-32-10.map --only_solved --alpha 1 --beta 0 --out_dir outputs/p_raw_A_pressure

python scripts/03_aggregate_p_raw.py --map_name random-32-32-10.map --only_solved --alpha 0 --beta 1 --out_dir outputs/p_raw_B_wait

python scripts/03_aggregate_p_raw.py --map_name random-32-32-10.map --only_solved --alpha 1 --beta 1 --out_dir outputs/p_raw_C_combo
```
3. **輸出 LaCAM3 需要的 heatmap bin/meta**
# C_combo
```
python scripts/04_export_heatmap_bin.py \
  --npy outputs/p_raw_C_combo/room-32-32-4.map/p_raw.npy \
  --variant C_combo
```

4. run the scripts
```
bash ./scripts/phase3_run_top5.sh
```
---

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

---

## 一、目前進度（已完成 Phase 1 + Phase 2）

### Phase 1：離線壅塞勢能圖 (P_{raw}) 產製（已完成）

你已經：

* 用 pypibt 跑 instances，成功產生 solver 輸出（paths/output.txt）與對應 supervision（npz + meta）。
* 修正了座標系一致性（MovingAI/scen 與輸出都回到 ((x,y)) / ((col,row)) 的可解讀版本）。
* 定義並計算出你 proposal 需要的訊號（Wait/Collision/Pressure/Occ 等），並完成聚合，得到：

  * `outputs/p_raw_A_pressure/.../p_raw.npy`
  * `outputs/p_raw_B_wait/.../p_raw.npy`
  * `outputs/p_raw_C_combo/.../p_raw.npy`
* 也完成了 `aggregate_meta.json`，可追溯 solved rate、平均 makespan、以及整張 heatmap 的統計範圍（你回報的 `p_raw min/max/mean` 屬於合理狀態）。

### Phase 2：pypibt qualitative check（已完成）

* 把 heatmap 以 **mask** 形式插入 pypibt，證明「heuristic 真的會改變行為」（路徑避開高熱區、穿越點改道等）。
* 同時也驗證出關鍵現象：

  1. **mask 在某些地圖會造成 chain deadlock / 不收斂**（尤其 pressure-only 且遮罩太激進時），也發現 `heat-q` 的敏感性。
  2. **maze 類圖的熱點很集中在少數瓶頸格**，mask 會變成「堵住關鍵孔洞」→ 反而更差。

**結論：Phase 2 已足夠，接下來必須進 LaCAM3 才能量化論文主張。**

---

## 二、Phase 3 的核心目標與為什麼一定要做

### Phase 3 的定位

**把「已經做好的 (P_{raw})（A/B/C 三版）」正式接入 LaCAM3（C++）**，完成 **Heatmap Baseline**（此時還沒有 TRM），用來回答論文的第一個硬問題：

> 「在 SOTA 的 LaCAM3 架構下，只要把 heuristic 變得更『懂壅塞』，是否就能提升 Success Rate / 降低 Search Stuck / 改善效率？」

這一步做完，你後面 Phase 4 才有意義：
Phase 4 的 TRM-H，本質上只是把「讀 (P_{raw})」換成「預測 (P_{raw})」，如果 Phase 3 證明 (P_{raw}) 插入 LaCAM3 沒有效果，那 TRM 再準也不會帶來系統收益。

### 為什麼要以 soft penalty + configuration-level scoring 當主要 baseline

你在 Phase 2 已經看到 mask 的工程風險：它會「改變可行域」，很容易把 bottleneck 直接封死，導致整體死鎖或行為失真。
因此進 LaCAM3 的主 baseline，應採：

* **soft penalty**：不封格子，只「提高代價」，保留可行性與解的存在性。
* **configuration-level scoring**：把 penalty 放在「整個配置 (Q) 的評分」上，而不是粗暴干預單一 agent 的局部走法。這更貼近 LaCAM 的高層搜尋本質（LaCAM3 是 search-based solver，而不是單純 PIBT rollout）。

---

## 三、Phase 3 你要交付的東西（論文導向的 deliverables）

Phase 3 完成後，你應該能交付以下內容（可直接對應論文第 4 章實驗）：

1. **LaCAM3 baseline**：原生 LaCAM3（不加 heatmap）。
2. **Heatmap Baseline（核心）**：LaCAM3 + (P_{raw})（A/B/C 各一版）

   * 主要用 **soft penalty + configuration-level scoring**
3. **插入點消融（加分）**：同一個 (P_{raw})，比較插入點 A vs B（下方我給你對照表）。
4. **最少一張可視化**：mapf-visualizer 對比「baseline vs heatmap」路徑差異（你 Phase 2 的 qualitative 經驗會在這裡變成論文圖）。
5. 指標（以 LaCAM 系統觀點）：

   * Success rate（最重要）
   * Runtime / time_limit 下解出比例
   * Search 的擴展量（若 LaCAM3 沒直接輸出，你就 patch 一個 counter）

---

## 四、Phase 3 詳細工程實作 Roadmap（最小可行 → 逐步加強）

> GitHub / 依賴

* **LaCAM3 官方**：`Kei18/lacam3`（C++17，CMake build，README 已提供 usage）([GitHub][1])
* 你已經有 **mapf-visualizer**（LaCAM3 也相容）([GitHub][1])
  -（可選）若你想保留「Python 主控」方案，LaCAM3 repo 提到 **pybind branch 可從 Python 呼叫**（但我建議先不要走這條，Phase 3 先把 C++ baseline 跑通）([GitHub][1])

---

### Step 3.0：把 LaCAM3 拉進你的專案（只做一次）

在你的 `TRM_MAPF/`：

1. 放到 `external/lacam3/`
2. build（Release）

LaCAM3 官方 build/usage 方式是 CMake + `build/main ...` ([GitHub][1])

你完成後，先跑一個 sanity check：

* 用你現成的 `data/maps/*.map` + `data/instances/*/instance_*.scen`
* 確認 LaCAM3 能吃你的 instance 格式並產出 `result.txt`

**輸出**：

* `runs/lacam3/<map>/<instance>/base/result.txt`（你自己規範路徑即可，重點是可重現）

---

### Step 3.1：Heatmap 檔案格式固定（避免 C++ 讀 .npy 的麻煩）

你現在的 `p_raw.npy` 很好，但 C++ 直接讀 `.npy` 會引入額外相依（cnpy 或自己刻 parser），不利於「最小 patch」。

**建議：加一個 Python 轉檔腳本（一次性）**
把每張 `p_raw.npy` 轉成：

* `heatmap.f32.bin`（row-major，float32）
* `heatmap.meta.json`（W/H、max、mean、log1p、alpha/beta、版本 A/B/C）

**輸出**（每張 map 各 3 份）：

* `outputs/p_raw_A_pressure/<map>/heatmap.f32.bin`
* `outputs/p_raw_B_wait/<map>/heatmap.f32.bin`
* `outputs/p_raw_C_combo/<map>/heatmap.f32.bin`

---

### Step 3.2：先做「Heatmap Baseline（configuration-level scoring）」——你的主 baseline

這是 Phase 3 的第一個「能寫進論文且最值錢」的結果。

**核心概念**：對每個高層節點（configuration）評分時，把 heat penalty 加進 (h(Q))。

推薦一個論文好寫、也好調參的形式：

[
h'(Q)=\sum_i dist(v_i, g_i);+;\lambda \sum_i \tilde{P}(v_i)
]

* (dist(\cdot))：LaCAM3 本來就有（最短路徑距離或其近似）
* (\tilde{P})：把你的 (P_{raw}) 做 normalization（例如除以 max，落在 ([0,1])）
* (\lambda)：一個小係數（先從 0.1、0.25、0.5 掃過就好）

**重要工程細節（你 Phase 2 踩過的坑要避免）**

* **已到 goal 的 agent 不要再加 penalty**：否則 goal camping/終點周圍會被過度懲罰，導致不合理繞路。
* penalty 是「軟」的：永遠不要改變可走/不可走，只是改評分。

**輸出**：

* `runs/lacam3/<map>/<instance>/heat_B/result.txt`（B=插入點 B）
* 同時 log：`lambda、heatmap 版本（A/B/C）、seed、time_limit`

---

### Step 3.3：再做「插入點 A：鄰居排序」作為消融（不是主 baseline）

你再加一個 patch：在 PIBT 的「選下一步」時，把 heat penalty 當作 tie-break 或次要排序項：

對候選鄰居 (u')：
[
score(u') = dist(u', g) + \lambda \tilde{P}(u')
]

這個 patch 能讓 qualitative 行為更明顯，但風險是：

* 容易出現你在 Phase 2 看過的「全體一起避開同一個洞」的 herd effect
* 更可能影響局部協調，讓某些 instance 的 makespan 變長

所以：**A 用來寫 “ablation/分析”，B 用來寫 “main baseline”。**

---

### Step 3.4：跑實驗矩陣（最小集合）

先不要貪多，你要的是「論文能站住腳」：

* maps：先從你已經最熟的 `random-32-32-10.map` 開始（Phase 2 已證明能看到效果）
* instances：先挑 10 個（包含你 Phase 2 用的高壅塞 case）
* variants：

  1. base
  2. +heat A/B/C（插入點 B，soft penalty）
  3. （選做）+heat A/B/C（插入點 A）

把結果整理成一張表：Success、Runtime、Makespan、（若有）Expanded nodes。

---

## 五、Phase 2 的最小 patch 設計（LaCAM3）——具體修改清單

> 我先給你「最小 patch 的設計清單」，**避免綁死在特定檔名**（因為你本機的 LaCAM3 版本與資料夾結構要以實際 clone 為準）。你照這份清單做，幾乎一定能落地。

### 你需要新增的東西（新增檔案）

1. `heatmap_loader.{h,cpp}`

* 讀 `heatmap.f32.bin` + `meta.json`
* 提供：`float get(y,x)`、`float get_norm(y,x)`、`max`、`H/W`

2. `heatmap_penalty.h`（或直接寫在 heuristic 模組）

* 提供：`double cell_penalty(v)`（含「到 goal 後不加」的邏輯）

### 你需要修改的東西（修改點）

1. **CLI 參數解析處**（通常在 `main.cpp` 或類似入口）

* 新增參數：

  * `--heatmap <path>`
  * `--heat_lambda <float>`
  * `--heat_variant <A|B|C|custom>`（你也可以只用 path 判定）
  * `--heat_insertion <config|neighbor|both>`（預設 config）
  * `--heat_norm <max|zscore|none>`（先做 max 就好）

2. **configuration-level scoring 的地方**（插入點 B）

* 找到計算 (h(Q)) 或計算節點優先順序/評分的函式（用 `rg "h("`, `rg "heuristic"`, `rg "eval"` 在 repo 內定位）
* 把 `+ lambda * sum_heat` 加進去

3. **PIBT 鄰居排序**（插入點 A）

* 找到 PIBT 選 action 的地方（`rg "PIBT"`、`rg "neighbors"`、`rg "sort"`）
* 在 neighbor ranking 中加入 penalty（建議先做 tie-break，不要一開始就完全改排序主因）

4. **log 輸出**

* 把 heatmap path、lambda、插入點、norm 方法寫進 `result.txt header`（論文可追溯）

---

## 六、插入點 A vs B 對照表（含優缺點與論文敘事）

| 面向                 | 插入點 A：鄰居排序（PIBT local）                | 插入點 B：Configuration-level scoring（LaCAM high-level）      |
| ------------------ | ------------------------------------- | -------------------------------------------------------- |
| 作用位置               | 低層：每個 agent 的下一步選擇                    | 高層：整個 configuration 節點的評分/擴展順序                           |
| 行為可視性              | 很強（路徑會明顯避開熱區）                         | 中等（更偏向「搜尋選對分支」）                                          |
| 風險                 | 容易 herd effect；局部協調被扭曲；類 mask 的副作用較接近 | 風險較低；保留 PIBT 行為，主要影響 search 導向                           |
| 對 Success Rate 的潛力 | 不穩定（看 map/threshold/λ）                | 通常更穩定（因為對準 LaCAM 的核心機制）                                  |
| 論文敘事               | 「我們以壅塞勢能引導局部動作選擇」→ 需要解釋為何不破壞多智能體協調    | 「我們以壅塞勢能修正 (h(Q))，改善 search stuck」→ 更貼合 LaCAM 系統論述（建議主線） |
| 建議定位               | Ablation / 補充實驗                       | **主 baseline**（你指定的 soft penalty + config scoring）       |

---

## 七、你接下來要做什麼（Phase 3 Next Actions）

1. 把 `external/lacam3` 建起來並用你的 `instance_*.scen` 跑通 baseline（產生 `result.txt`）。([GitHub][1])
2. 寫一個 Python 轉檔：`p_raw.npy -> heatmap.f32.bin + meta.json`（A/B/C 都轉）。
3. 先做插入點 B（configuration-level scoring）的 soft penalty patch，跑 10 個 instances，得到第一張可寫進論文的表。
4. 再補插入點 A 當消融（可選但很加分）。

你把第 1 步 baseline 跑通的 `result.txt`（一個 instance 就好）和 LaCAM3 的 repo tree（`tree external/lacam3 | head -n 50`）貼我，我就能把「插入點 B 的實際檔案位置」精準鎖定到你本機版本，並把 patch 的程式骨架寫到你可以直接改的程度。

[1]: https://github.com/Kei18/lacam3?utm_source=chatgpt.com "GitHub - Kei18/lacam3: Engineering LaCAM*: Towards Real-Time, Large-Scale, and Near-Optimal Multi-Agent Pathfinding (AAMAS-24)"


