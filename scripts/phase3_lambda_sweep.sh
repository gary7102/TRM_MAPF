#!/usr/bin/env bash
set -euo pipefail

# === Config ===
MAP_name="random-32-32-20.map"
MAP="data/maps/${MAP_name}"
N_AGENTS=100
VERBOSE=0

HEAT_BIN="outputs/p_raw_C_combo/${MAP_name}/heatmap.f32.bin"
HEAT_META="outputs/p_raw_C_combo/${MAP_name}/heatmap.meta.json"

# Lambda sweep values
LAMBDAS=(4 6 8 10)

# Instance ids to sweep (keep as 2-digit strings if you want)
IDS=(00 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20)

BIN="external/lacam3/build/main"
OUT_ROOT="runs/phase3_sweep/${MAP_name}"
BASE_ROOT="${OUT_ROOT}/baseline"

mkdir -p "${BASE_ROOT}"

echo "[info] MAP=${MAP}"
echo "[info] HEAT_BIN=${HEAT_BIN}"
echo "[info] HEAT_META=${HEAT_META}"
echo "[info] LAMBDAS=${LAMBDAS[*]}"
echo "[info] OUT_ROOT=${OUT_ROOT}"
echo

if [[ ! -f "${MAP}" ]]; then
  echo "[error] map not found: ${MAP}" >&2
  exit 1
fi
if [[ ! -f "${HEAT_BIN}" ]]; then
  echo "[error] heatmap bin not found: ${HEAT_BIN}" >&2
  exit 1
fi

# 1) Baseline once (reused for every lambda)
for id in "${IDS[@]}"; do
  id_dec=$((10#$id))
  inst=$(printf "data/instances/%s/instance_%05d.scen" "${MAP_name}" "${id_dec}")
  out_base=$(printf "%s/base%05d_result.txt" "${BASE_ROOT}" "${id_dec}")

  if [[ -s "${out_base}" ]]; then
    echo "[skip] baseline instance=$(printf "%05d" "${id_dec}")"
    continue
  fi

  echo "[base] instance=$(printf "%05d" "${id_dec}") -> ${out_base}"
  "${BIN}" \
    -m "${MAP}" \
    -i "${inst}" \
    -N "${N_AGENTS}" \
    -o "${out_base}" \
    -v "${VERBOSE}"
done

# 2) Heatmap sweep per lambda
for lambda in "${LAMBDAS[@]}"; do
  L_DIR="${OUT_ROOT}/lambda_${lambda}"
  HEAT_DIR="${L_DIR}/heatmap"
  BASE_DIR="${L_DIR}/baseline"
  mkdir -p "${HEAT_DIR}" "${BASE_DIR}"

  # copy baseline into this lambda folder (so summary sees pairs)
  for id in "${IDS[@]}"; do
    id_dec=$((10#$id))
    src=$(printf "%s/base%05d_result.txt" "${BASE_ROOT}" "${id_dec}")
    dst=$(printf "%s/base%05d_result.txt" "${BASE_DIR}" "${id_dec}")
    if [[ -s "${src}" && ! -s "${dst}" ]]; then
      cp "${src}" "${dst}"
    fi
  done

  for id in "${IDS[@]}"; do
    id_dec=$((10#$id))
    inst=$(printf "data/instances/%s/instance_%05d.scen" "${MAP_name}" "${id_dec}")
    out_heat=$(printf "%s/heatmap%05d_result.txt" "${HEAT_DIR}" "${id_dec}")

    if [[ -s "${out_heat}" ]]; then
      echo "[skip] lambda=${lambda} instance=$(printf "%05d" "${id_dec}")"
      continue
    fi

    echo "[heat] lambda=${lambda} instance=$(printf "%05d" "${id_dec}") -> ${out_heat}"
    "${BIN}" \
      -m "${MAP}" \
      -i "${inst}" \
      -N "${N_AGENTS}" \
      --heatmap_bin "${HEAT_BIN}" \
      --heatmap_meta "${HEAT_META}" \
      --heat_lambda "${lambda}" \
      -o "${out_heat}" \
      -v "${VERBOSE}" \
      2>/dev/null
  done

  # summarize for this lambda
  SUM_DIR="outputs/phase3_sweep/${MAP_name}/lambda_${lambda}"
  mkdir -p "${SUM_DIR}"
  python scripts/phase3_summarize_results.py \
    --root "${L_DIR}" \
    --out_csv "${SUM_DIR}/summary.csv" \
    --out_html "${SUM_DIR}/summary.html" \
    --require_pair
done

echo
echo "[done] sweep results under:"
echo "  - outputs/phase3_sweep/${MAP_name}"
