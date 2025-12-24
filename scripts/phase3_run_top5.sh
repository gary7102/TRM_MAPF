#!/usr/bin/env bash
set -euo pipefail

# === User-configurable ===
MAP_name="random-32-32-20.map"
# MAP_name="maze-32-32-2.map"
# MAP_name="room-32-32-4.map"
# MAP_name="warehouse-10-20-10-2-1.map"
MAP="data/maps/${MAP_name}"
N_AGENTS=150
VERBOSE=0

HEAT_BIN="outputs/p_raw_A_pressure/${MAP_name}/heatmap.f32.bin"
HEAT_META="outputs/p_raw_A_pressure/${MAP_name}/heatmap.meta.json"
# HEAT_BIN="outputs/p_raw_B_wait/${MAP_name}/heatmap.f32.bin"
# HEAT_META="outputs/p_raw_B_wait/${MAP_name}/heatmap.meta.json"
# HEAT_BIN="outputs/p_raw_C_combo/${MAP_name}/heatmap.f32.bin"
# HEAT_META="outputs/p_raw_C_combo/${MAP_name}/heatmap.meta.json"
HEAT_LAMBDA=10

# All 50 instances (0..49)
# IDS=($(seq 0 49))
IDS=(5) # only instance 5

# Output root
OUT_ROOT="runs/phase3_top5"
OUT_HEAT="${OUT_ROOT}/heatmap/${MAP_name}"
OUT_BASE="${OUT_ROOT}/baseline/${MAP_name}"

BIN="external/lacam3/build/main"

mkdir -p "${OUT_HEAT}" "${OUT_BASE}"

echo "[info] MAP=${MAP}"
echo "[info] HEAT_BIN=${HEAT_BIN}"
echo "[info] HEAT_META=${HEAT_META}"
echo "[info] HEAT_LAMBDA=${HEAT_LAMBDA}"
echo "[info] OUT_ROOT=${OUT_ROOT}"
echo

for id in "${IDS[@]}"; do
  id_dec=$((10#$id))
  inst=$(printf "data/instances/${MAP_name}/instance_%05d.scen" "${id_dec}")

  out_heat=$(printf "%s/heatmap%05d_result.txt" "${OUT_HEAT}" "${id_dec}")
  out_base=$(printf "%s/base%05d_result.txt" "${OUT_BASE}" "${id_dec}")

  echo "============================================================"
  echo "[run] instance=$(printf "%05d" "${id_dec}")"
  echo "[run] scen=${inst}"
  echo

  # 1) Heatmap run
  echo "[heat] -> ${out_heat}"
  "${BIN}" \
    -m "${MAP}" \
    -i "${inst}" \
    -N "${N_AGENTS}" \
    --heatmap_bin "${HEAT_BIN}" \
    --heatmap_meta "${HEAT_META}" \
    --heat_lambda "${HEAT_LAMBDA}" \
    -o "${out_heat}" \
    2>/dev/null 
    # -v "${VERBOSE}"
  

  # 2) Baseline run (no heatmap args)
  echo "[base] -> ${out_base}"
  "${BIN}" \
    -m "${MAP}" \
    -i "${inst}" \
    -N "${N_AGENTS}" \
    -o "${out_base}" \
    # -v "${VERBOSE}"

  echo "[done] scen=${inst}"
done

echo "[done] results under:"
echo "  - ${OUT_HEAT}"
echo "  - ${OUT_BASE}"

python scripts/phase3_summarize_results.py \
   --root ${MAP} \
   --out_csv outputs/phase3/${MAP_name}/summary.csv \
   --map_name ${MAP_name} \
   --lambda ${HEAT_LAMBDA} \
   --require_pair

python scripts/phase3_summarize_results.py \
  --root ${MAP} \
  --out_html outputs/phase3/${MAP_name}/summary.html \
  --map_name ${MAP_name} \
  --lambda ${HEAT_LAMBDA} \
  --require_pair
