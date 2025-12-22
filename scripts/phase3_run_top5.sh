#!/usr/bin/env bash
set -euo pipefail

# === User-configurable ===
MAP="data/maps/random-32-32-20.map"
N_AGENTS=100
VERBOSE=0

HEAT_BIN="outputs/p_raw_C_combo/random-32-32-20.map/heatmap.f32.bin"
HEAT_META="outputs/p_raw_C_combo/random-32-32-20.map/heatmap.meta.json"
HEAT_LAMBDA=3

# Top-5 instances by total_wait
IDS=(40 32 45 35 5)
# IDS=(40)

# Output root
OUT_ROOT="runs/phase3_top5"
OUT_HEAT="${OUT_ROOT}/heatmap/random-32-32-20.map"
OUT_BASE="${OUT_ROOT}/baseline/random-32-32-20.map"

BIN="external/lacam3/build/main"

mkdir -p "${OUT_HEAT}" "${OUT_BASE}"

echo "[info] MAP=${MAP}"
echo "[info] HEAT_BIN=${HEAT_BIN}"
echo "[info] HEAT_META=${HEAT_META}"
echo "[info] HEAT_LAMBDA=${HEAT_LAMBDA}"
echo "[info] OUT_ROOT=${OUT_ROOT}"
echo

for id in "${IDS[@]}"; do
  inst=$(printf "data/instances/random-32-32-20.map/instance_%05d.scen" "${id}")

  out_heat=$(printf "%s/heatmap%05d_result.txt" "${OUT_HEAT}" "${id}")
  out_base=$(printf "%s/base%05d_result.txt" "${OUT_BASE}" "${id}")

  echo "============================================================"
  echo "[run] instance=$(printf "%05d" "${id}")"
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

  echo

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
